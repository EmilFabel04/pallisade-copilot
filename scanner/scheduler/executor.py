"""
Task Executor.

Handles execution of both prompt-based and structured monitor tasks.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Optional

import structlog

from scanner.monitors.executor import MonitorExecutor, MONITOR_REGISTRY
from scanner.monitors.base import MonitorResult, MonitorStatus
from scanner.monitors.infrastructure import INFRA_MONITOR_TYPES
from scanner.monitors.tools import TOOL_MONITOR_TYPES, TOOL_MONITOR_REGISTRY

logger = structlog.get_logger()

# Warehouse pipeline node tool types (lowercase, matching PipelineNode.toolType)
_WAREHOUSE_TOOL_TYPES = ("bigquery", "snowflake", "postgres", "redshift")


def _get_encryption_key() -> bytes:
    """Get the AES-256 encryption key (mirrors lib/crypto.ts getEncryptionKey)."""
    key_hex = os.environ.get("ENCRYPTION_KEY", "")
    if key_hex:
        return bytes.fromhex(key_hex)
    # Development fallback — matches the TypeScript scryptSync('pallisade-dev-key', 'salt', 32)
    return hashlib.scrypt(b"pallisade-dev-key", salt=b"salt", n=16384, r=8, p=1, dklen=32)


def _decrypt(encrypted_hex: str) -> str:
    """Decrypt AES-256-GCM data produced by lib/crypto.ts encrypt().

    Format: iv_hex (32 chars) + auth_tag_hex (32 chars) + ciphertext_hex
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key()
    iv = bytes.fromhex(encrypted_hex[:32])
    auth_tag = bytes.fromhex(encrypted_hex[32:64])
    ciphertext = bytes.fromhex(encrypted_hex[64:])

    aesgcm = AESGCM(key)
    # GCM tag is appended to ciphertext for the cryptography library
    plaintext = aesgcm.decrypt(iv, ciphertext + auth_tag, None)
    return plaintext.decode("utf-8")


def _get_query_func(integration_config: Dict[str, Any], dialect: str):
    """Build a warehouse query function from integration config.

    Creates the adapter, calls connect(), and returns the bound execute_query method.
    """
    if dialect == "bigquery":
        from scanner.adapters.bigquery import BigQueryAdapter

        adapter = BigQueryAdapter(integration_config)
        adapter.connect()
        return adapter.execute_query, "bigquery"
    elif dialect == "snowflake":
        from scanner.adapters.snowflake import SnowflakeAdapter

        adapter = SnowflakeAdapter(integration_config)
        adapter.connect()
        return adapter.execute_query, "snowflake"
    elif dialect in ("postgres", "postgresql", "redshift"):
        from scanner.adapters.postgres import PostgresAdapter

        adapter = PostgresAdapter(integration_config)
        adapter.connect()
        return adapter.execute_query, "postgres"
    else:
        raise ValueError(f"Unsupported dialect: {dialect}")


def _detect_dialect(integration_type: str) -> str:
    """Map integration type to SQL dialect."""
    mapping = {
        "bigquery": "bigquery",
        "snowflake": "snowflake",
        "postgres": "postgres",
        "postgresql": "postgres",
        "redshift": "redshift",
    }
    return mapping.get(integration_type.lower(), "postgres")


def _discover_numeric_columns(
    query_func, database: str, schema: str, table: str, dialect: str
) -> list[str]:
    """Query INFORMATION_SCHEMA to find numeric columns in a table."""
    if dialect == "bigquery":
        sql = (
            f"SELECT column_name FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = '{table}' "
            f"AND data_type IN ('INT64', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC', 'INTEGER', 'FLOAT') "
            f"ORDER BY ordinal_position"
        )
    elif dialect == "snowflake":
        sql = (
            f"SELECT COLUMN_NAME FROM {database}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{schema.upper()}' AND TABLE_NAME = '{table.upper()}' "
            f"AND DATA_TYPE IN ('NUMBER', 'DECIMAL', 'NUMERIC', 'INT', 'INTEGER', "
            f"'BIGINT', 'SMALLINT', 'TINYINT', 'BYTEINT', 'FLOAT', 'FLOAT4', "
            f"'FLOAT8', 'DOUBLE', 'DOUBLE PRECISION', 'REAL') "
            f"ORDER BY ORDINAL_POSITION"
        )
    else:
        # Postgres / Redshift
        sql = (
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
            f"AND data_type IN ('integer', 'bigint', 'smallint', 'numeric', "
            f"'decimal', 'real', 'double precision', 'float') "
            f"ORDER BY ordinal_position"
        )

    try:
        rows = query_func(sql)
        return [
            row.get("column_name") or row.get("COLUMN_NAME", "")
            for row in rows
            if row.get("column_name") or row.get("COLUMN_NAME")
        ]
    except Exception as e:
        logger.warning(f"[Executor] Failed to discover columns: {e}")
        return []


def _discover_all_columns(
    query_func, database: str, schema: str, table: str, dialect: str
) -> list[str]:
    """Discover all columns suitable for null_rate/distinct_rate.

    Returns every column except complex/nested types (STRUCT, ARRAY,
    GEOGRAPHY, JSON, RECORD, etc.) that cannot be meaningfully
    compared for null or distinct counts.
    """
    if dialect == "bigquery":
        exclude = "'STRUCT', 'ARRAY', 'GEOGRAPHY', 'JSON', 'RECORD'"
        sql = (
            f"SELECT column_name FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = '{table}' AND data_type NOT IN ({exclude}) "
            f"ORDER BY ordinal_position"
        )
    elif dialect == "snowflake":
        exclude = "'VARIANT', 'OBJECT', 'ARRAY'"
        sql = (
            f"SELECT COLUMN_NAME FROM {database}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{schema.upper()}' AND TABLE_NAME = '{table.upper()}' "
            f"AND DATA_TYPE NOT IN ({exclude}) ORDER BY ORDINAL_POSITION"
        )
    else:
        # Postgres / Redshift
        exclude = "'json', 'jsonb', 'xml', 'point', 'polygon', 'line'"
        sql = (
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
            f"AND data_type NOT IN ({exclude}) ORDER BY ordinal_position"
        )

    try:
        rows = query_func(sql)
        return [
            row.get("column_name") or row.get("COLUMN_NAME", "")
            for row in rows
            if row.get("column_name") or row.get("COLUMN_NAME")
        ]
    except Exception as e:
        logger.warning(f"[Executor] Failed to discover all columns: {e}")
        return []


class TaskExecutor:
    """Executes a scheduled task (structured monitor or LLM prompt)."""

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task and return the result dict.

        Returns:
            Dict with keys: status, value, threshold, message, details, sql_executed
        """
        task_mode = task.get("taskMode", "structured")

        if task_mode == "prompt":
            return await self._execute_prompt(task)

        # Check if this is a tool monitor (Fivetran/Airflow/dbt) before
        # falling through to the warehouse-SQL structured path.
        monitor_type = (task.get("monitorType") or "").lower()
        if monitor_type in TOOL_MONITOR_TYPES:
            return await self._execute_tool_monitor(task, monitor_type)

        return await self._execute_structured(task)

    async def _execute_structured(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run a structured monitor check."""
        monitor_type = task.get("monitorType", "").lower()
        target_fqn = task.get("targetFqn", "")
        config = task.get("config") or {}

        logger.info(
            "[Executor] _execute_structured",
            monitor_type=monitor_type,
            target_fqn=target_fqn,
            config_keys=list(config.keys()) if isinstance(config, dict) else str(config),
            has_integration_config=bool(task.get("integrationConfig")),
            has_integration_id=bool(task.get("integrationId")),
            has_org_id=bool(task.get("organizationId")),
        )

        if not monitor_type:
            logger.warning("[Executor] Missing monitorType")
            return {
                "status": "ERROR",
                "message": "Missing monitorType for structured task",
            }

        # Infrastructure monitors use SSH, not SQL — handle separately
        if monitor_type in INFRA_MONITOR_TYPES:
            return await self._execute_infrastructure(task, monitor_type, config)

        if not target_fqn:
            logger.warning("[Executor] Missing targetFqn")
            return {
                "status": "ERROR",
                "message": "Missing targetFqn for structured task",
            }

        # Parse FQN: database.schema.table or schema.table (2-part)
        parts = target_fqn.split(".")
        if len(parts) >= 3:
            database, schema, table = parts[0], parts[1], ".".join(parts[2:])
        elif len(parts) == 2:
            # 2-part FQN: infer database/project from integration config
            integration_config = task.get("integrationConfig") or {}
            database = (
                integration_config.get("project_id")
                or integration_config.get("project")
                or integration_config.get("database")
                or ""
            )
            schema, table = parts[0], parts[1]
            logger.info(f"[Executor] 2-part FQN '{target_fqn}', inferred database='{database}'")
        else:
            logger.warning(f"[Executor] Invalid FQN: {target_fqn}")
            return {
                "status": "ERROR",
                "message": f"Invalid target FQN format: {target_fqn} (expected database.schema.table or schema.table)",
            }

        # Resolve monitor type (routes UI-only types like null_rate → anomaly)
        resolved_type, resolved_config = MonitorExecutor.resolve_monitor_type(
            monitor_type, config
        )

        monitor_cls = MONITOR_REGISTRY.get(resolved_type)
        if not monitor_cls:
            logger.warning(f"[Executor] Unknown monitor type: {monitor_type} (resolved: {resolved_type}), registry keys: {list(MONITOR_REGISTRY.keys())}")
            return {
                "status": "ERROR",
                "message": f"Unknown monitor type: {monitor_type}",
            }

        logger.info(
            f"[Executor] Monitor resolved",
            original_type=monitor_type,
            resolved_type=resolved_type,
            routed=monitor_type != resolved_type,
        )

        # Inject stored baseline for monitors that support it
        config = resolved_config
        stored = config.pop("stored_baseline", None)
        if stored and stored.get("mean") is not None:
            mean = float(stored["mean"])
            stddev = float(stored.get("stddev", 0))
            count = int(stored.get("count", 10))

            if resolved_type == "anomaly" and count >= 3 and "historical_values" not in config:
                # Build deterministic values that reproduce stored mean/stddev
                # [mean-σ, mean, mean+σ] repeated → gives correct baseline stats
                if stddev > 0:
                    config["historical_values"] = [mean - stddev, mean, mean + stddev] * max(1, count // 3)
                else:
                    config["historical_values"] = [mean] * count
                logger.info("[Executor] Injected stored baseline for anomaly", mean=mean, stddev=stddev, count=count)

            elif resolved_type == "volume":
                # VolumeMonitor accepts historical_mean/historical_stddev directly
                if "historical_mean" not in config:
                    config["historical_mean"] = mean
                if "historical_stddev" not in config:
                    config["historical_stddev"] = stddev
                logger.info("[Executor] Injected stored baseline for volume", mean=mean, stddev=stddev)

        # Inject cadence gaps from MonitorBaseline for freshness monitors
        if resolved_type == "freshness" and not config.get("cadence_gaps"):
            try:
                from scanner.monitors.baseline_store import BaselineStore
                from scanner.scheduler.service import _get_connection

                store_conn = _get_connection()
                try:
                    store = BaselineStore(store_conn)
                    gaps = store.get_cadence_gaps(
                        task.get("id", ""), "hours_since_update"
                    )
                    if gaps and len(gaps) >= 5:
                        config["cadence_aware"] = True
                        config["cadence_gaps"] = gaps
                        logger.info(
                            "[Executor] Injected cadence gaps for freshness",
                            gap_count=len(gaps),
                            median_gap=round(sorted(gaps)[len(gaps) // 2], 1),
                        )
                finally:
                    store_conn.close()
            except Exception as e:
                logger.debug(f"[Executor] Could not load cadence gaps: {e}")

        # Create monitor instance from resolved config
        monitor = monitor_cls(config=config) if config else monitor_cls()

        # Get warehouse query function — use pre-fetched config or look up by ID/org
        integration_config = task.get("integrationConfig") or await self._get_integration_config(
            task.get("integrationId"), task.get("organizationId")
        )

        if not integration_config:
            logger.warning("[Executor] No integration config resolved")
            return {
                "status": "ERROR",
                "message": "No warehouse integration configured for this task. Connect a warehouse integration or select one when creating the task.",
            }

        integration_type = integration_config.get("type", "postgres")
        dialect = _detect_dialect(integration_type)
        logger.info(f"[Executor] Using dialect={dialect}, type={integration_type}")

        # Enforce dataset/schema visibility: if the integration restricts
        # which datasets are accessible, block monitors targeting other datasets.
        allowed_datasets = integration_config.get("datasets") or integration_config.get("schemas") or []
        if isinstance(allowed_datasets, str):
            allowed_datasets = [allowed_datasets]
        if allowed_datasets:
            # schema == dataset for BigQuery, schema for others
            allowed_lower = [d.lower() for d in allowed_datasets]
            if schema.lower() not in allowed_lower:
                logger.warning(
                    "[Executor] Target dataset not in allowed list",
                    target_schema=schema,
                    allowed=allowed_datasets,
                )
                return {
                    "status": "ERROR",
                    "message": (
                        f"Dataset '{schema}' is not in the configured dataset list "
                        f"({', '.join(allowed_datasets)}). Update the monitor target "
                        f"or add '{schema}' to the warehouse integration config."
                    ),
                }

        try:
            query_func, sql_dialect = _get_query_func(integration_config, dialect)
            executor = MonitorExecutor(query_func=query_func, dialect=sql_dialect)

            # Auto-configure: fill in missing config from warehouse data
            config = executor.auto_configure(
                resolved_type, database, schema, table, config
            )

            # Re-create monitor with auto-configured config
            monitor = monitor_cls(config=config) if config else monitor_cls()

            # Auto-detect timestamp column for freshness monitors
            if hasattr(monitor, "needs_column_discovery") and monitor.needs_column_discovery:
                from scanner.monitors.freshness import discover_timestamp_column

                discovered = discover_timestamp_column(
                    query_func, database, schema, table, sql_dialect
                )
                if discovered:
                    monitor.timestamp_column = discovered
                else:
                    return {
                        "status": "ERROR",
                        "message": f"No timestamp/datetime columns found in {target_fqn}. "
                        f"Specify a timestamp_column in the monitor config.",
                    }

            # Multi-column anomaly: if column is "*", discover all numeric
            # columns and run the anomaly monitor on each one.
            if (
                resolved_type == "anomaly"
                and getattr(monitor, "column", "") == "*"
            ):
                return self._run_multi_column_anomaly(
                    executor, config, database, schema, table, sql_dialect
                )

            result: MonitorResult = executor.run_monitor(
                monitor, database, schema, table
            )
            result_dict = result.to_dict()

            # LLM validation for FAIL/WARN results
            llm_validate = config.get("llm_validate", True)
            if llm_validate and result.status in (MonitorStatus.FAIL, MonitorStatus.WARN):
                result_dict["raw_status"] = result_dict["status"]
                result_dict = await self._llm_validate_result(
                    result_dict, resolved_type, target_fqn
                )
                result_dict["final_status"] = result_dict["status"]

            return result_dict
        except Exception as e:
            logger.error(f"[Executor] Structured task failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Execution failed: {str(e)}",
            }

    async def _llm_validate_result(
        self,
        result_dict: Dict[str, Any],
        monitor_type: str,
        target_fqn: str,
    ) -> Dict[str, Any]:
        """Use LLM to validate/contextualize a FAIL or WARN finding.

        The LLM can downgrade FAIL→WARN, add context, or confirm.
        Returns the (possibly modified) result dict.
        """
        try:
            import openai
            import os

            client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

            details = result_dict.get("details", {})
            # Build context for the LLM
            prompt = (
                f"A data quality monitor has flagged an issue. Review it and assess "
                f"whether this is a true positive or likely a false positive.\n\n"
                f"**Monitor**: {monitor_type} on `{target_fqn}`\n"
                f"**Status**: {result_dict.get('status')}\n"
                f"**Message**: {result_dict.get('message')}\n"
                f"**Current value**: {result_dict.get('value')}\n"
                f"**Threshold**: {result_dict.get('threshold')}\n"
                f"**Expected range**: {result_dict.get('expected_range')}\n"
                f"**Details**: z_score={details.get('z_score')}, "
                f"baseline_mean={details.get('baseline_mean')}, "
                f"baseline_count={details.get('baseline_count')}, "
                f"confidence={details.get('confidence_pct')}%\n\n"
                f"Respond with ONLY a JSON object:\n"
                f'{{"adjusted_status": "FAIL"|"WARN"|"PASS", '
                f'"explanation": "brief explanation", '
                f'"confidence": 0.0-1.0}}'
            )

            system_msg = (
                "You are a senior data quality analyst. Your job is to review automated "
                "monitor alerts and determine if they are true positives. Consider:\n"
                "- Weekend/holiday patterns (lower volume is often normal)\n"
                "- Gradual trends vs sudden drops\n"
                "- Whether the baseline has enough data points\n"
                "- Common false positive patterns\n"
                "Be conservative: only downgrade FAIL to WARN if you're confident it's "
                "a false positive. Add useful context to help the user understand.\n"
                "Respond with ONLY valid JSON, no markdown."
            )

            response = client.chat.completions.create(
                model="gpt-5-mini",
                max_completion_tokens=512,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
            )

            response_text = response.choices[0].message.content or "" if response.choices else ""

            # Parse LLM response
            import json as json_mod
            # Strip markdown code fences if present
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json_mod.loads(cleaned)
            original_status = result_dict["status"]
            adjusted_status = parsed.get("adjusted_status", original_status).upper()
            explanation = parsed.get("explanation", "")
            confidence = parsed.get("confidence", 0.5)

            # Constrain LLM adjustments:
            # 1. Never upgrade PASS → FAIL
            if original_status == "PASS" and adjusted_status == "FAIL":
                adjusted_status = original_status

            # 2. Only allow downgrade when confidence_pct < 60 or baseline_count < 7
            if adjusted_status != original_status:
                confidence_pct = details.get("confidence_pct", 100)
                baseline_count = details.get("baseline_count", 30)
                can_adjust = confidence_pct < 60 or baseline_count < 7
                if original_status in ("FAIL", "WARN") and not can_adjust:
                    adjusted_status = original_status  # reject the change

            # Apply adjustment
            if adjusted_status in ("FAIL", "WARN", "PASS"):
                result_dict["status"] = adjusted_status
                if explanation:
                    result_dict["message"] = (
                        f"{result_dict.get('message', '')} "
                        f"[AI Assessment: {explanation}]"
                    )
                if not result_dict.get("details"):
                    result_dict["details"] = {}
                result_dict["details"]["llm_validation"] = {
                    "original_status": original_status,
                    "adjusted_status": adjusted_status,
                    "explanation": explanation,
                    "confidence": confidence,
                }
                result_dict["details"]["llm_reason"] = explanation

            logger.info(
                "[Executor] LLM validation complete",
                original_status=original_status,
                adjusted_status=adjusted_status,
                confidence=confidence,
            )

        except Exception as e:
            # LLM validation is best-effort — don't fail the monitor run
            logger.warning(f"[Executor] LLM validation failed (non-fatal): {e}")

        return result_dict

    def _run_multi_column_anomaly(
        self,
        executor: "MonitorExecutor",
        config: Dict[str, Any],
        database: str,
        schema: str,
        table: str,
        dialect: str,
    ) -> Dict[str, Any]:
        """Discover columns and run anomaly check on each one.

        For metrics that work on any column type (null_rate, distinct_count,
        distinct_rate), discovers ALL columns excluding complex types.
        For numeric-only metrics (avg, min, max, etc.), discovers only
        numeric columns.

        Returns an aggregated result with per-column details.
        """
        from scanner.monitors.anomaly import AnomalyMonitor
        from scanner.monitors.base import MonitorStatus
        from scanner.monitors.executor import MAX_MULTI_COLUMNS

        metric = config.get("metric", "avg")

        if metric in AnomalyMonitor.ALL_COLUMN_METRICS:
            columns = _discover_all_columns(
                executor.query_func, database, schema, table, dialect
            )
        else:
            columns = _discover_numeric_columns(
                executor.query_func, database, schema, table, dialect
            )

        # Enforce column limit
        columns = columns[:MAX_MULTI_COLUMNS]

        if not columns:
            return {
                "status": "WARN",
                "message": f"No suitable columns found in {database}.{schema}.{table} for metric '{metric}'",
            }

        logger.info(
            f"[Executor] Multi-column anomaly: checking {len(columns)} columns",
            columns=columns,
            metric=metric,
        )
        per_column: list[dict] = []
        anomalies: list[str] = []

        for col in columns:
            col_config = {**config, "column": col, "metric": metric}
            col_monitor = AnomalyMonitor(config=col_config)

            try:
                result = executor.run_monitor(col_monitor, database, schema, table)
                entry = result.to_dict()
                entry["column"] = col
                per_column.append(entry)

                if result.status == MonitorStatus.FAIL:
                    anomalies.append(f"{col}: {result.message}")
            except Exception as e:
                logger.warning(f"[Executor] Column {col} failed: {e}")
                per_column.append({
                    "column": col,
                    "status": "ERROR",
                    "message": str(e),
                })

        # Aggregate status: FAIL if any anomaly, PASS if all pass
        if anomalies:
            return {
                "status": "FAIL",
                "message": f"Anomalies detected in {len(anomalies)}/{len(columns)} columns: {'; '.join(anomalies[:5])}",
                "details": {"columns_checked": len(columns), "anomalies": len(anomalies), "per_column": per_column},
            }

        return {
            "status": "PASS",
            "message": f"All {len(columns)} numeric columns within normal range ({metric})",
            "details": {"columns_checked": len(columns), "anomalies": 0, "per_column": per_column},
        }

    async def _execute_infrastructure(
        self, task: Dict[str, Any], monitor_type: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run an infrastructure monitor via SSH.

        Infrastructure monitors (certificate, server_health, log_analysis)
        connect to a server via SSH instead of querying a warehouse.
        """
        from scanner.adapters.server import ServerAdapter
        from scanner.monitors.executor import MonitorExecutor

        # Get server connection config from the integration
        integration_config = task.get("integrationConfig")
        if not integration_config:
            # Try serverNodeId from task config (PipelineNode ID)
            server_node_id = config.get("serverNodeId")
            integration_config = await self._get_server_config(
                task.get("integrationId"),
                task.get("organizationId"),
                server_node_id=server_node_id,
            )

        if not integration_config:
            return {
                "status": "ERROR",
                "message": "No server integration configured. Connect a Linux Server integration first.",
            }

        adapter = ServerAdapter()
        try:
            adapter.connect(integration_config)
            result = MonitorExecutor.execute_infrastructure_monitor(
                monitor_type, config, adapter
            )
            result_dict = result.to_dict()

            # LLM validation for FAIL/WARN results (reuse existing)
            llm_validate = config.get("llm_validate", True)
            if llm_validate and result.status in (MonitorStatus.FAIL, MonitorStatus.WARN):
                result_dict["raw_status"] = result_dict["status"]
                result_dict = await self._llm_validate_result(
                    result_dict, monitor_type, integration_config.get("host", "unknown")
                )
                result_dict["final_status"] = result_dict["status"]

            return result_dict
        except Exception as e:
            logger.error(f"[Executor] Infrastructure monitor failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Infrastructure monitor failed: {str(e)}",
            }
        finally:
            adapter.disconnect()

    async def _execute_tool_monitor(
        self, task: Dict[str, Any], monitor_type: str
    ) -> Dict[str, Any]:
        """Run a tool API monitor (Fivetran, Airflow, dbt Cloud).

        Tool monitors query external integration APIs instead of running SQL
        or SSH commands.  Follows the same pattern as _execute_infrastructure.
        """
        config = task.get("config") or {}

        monitor_cls = TOOL_MONITOR_REGISTRY.get(monitor_type)
        if not monitor_cls:
            return {
                "status": "ERROR",
                "message": f"Unknown tool monitor type: {monitor_type}",
            }

        # Resolve integration config (pre-fetched from Next.js or looked up)
        integration_config = task.get("integrationConfig") or await self._get_tool_config(
            task.get("integrationId"),
            task.get("organizationId"),
            monitor_type,
        )

        if not integration_config:
            # Map monitor type to human-readable tool name
            tool_names = {
                "sync_lag": "Fivetran/Airbyte", "failed_syncs": "Fivetran/Airbyte",
                "connector_schema_drift": "Fivetran/Airbyte",
                "dag_last_run": "Airflow", "dag_schedule_lag": "Airflow",
                "task_failure_rate": "Airflow",
                "dbt_test_failures": "dbt Cloud", "dbt_model_freshness": "dbt Cloud",
                "dbt_source_freshness": "dbt Cloud",
            }
            tool_name = tool_names.get(monitor_type, monitor_type)
            return {
                "status": "ERROR",
                "message": (
                    f"No live {tool_name} integration found. "
                    f"This monitor requires {tool_name} to be connected with a live instance "
                    f"(API connection). Go to the Pipeline page and either add a new {tool_name} "
                    f"integration or switch your existing one to API/instance mode."
                ),
            }

        try:
            client = self._create_tool_client(monitor_type, integration_config)
        except ValueError as e:
            # ValueError = configuration issue (e.g. GitHub mode, missing API key)
            logger.error(f"[Executor] Tool client config error: {e}")
            return {
                "status": "ERROR",
                "message": str(e),
            }
        except Exception as e:
            logger.error(f"[Executor] Failed to create tool client: {e}")
            return {
                "status": "ERROR",
                "message": f"Failed to connect to integration: {e}",
            }

        monitor = monitor_cls(config)
        try:
            result: MonitorResult = monitor.execute(client)
            result_dict = result.to_dict()

            # LLM validation for FAIL/WARN results
            llm_validate = config.get("llm_validate", True)
            target = task.get("targetFqn") or f"{monitor_type}:unknown"
            if llm_validate and result.status in (MonitorStatus.FAIL, MonitorStatus.WARN):
                result_dict["raw_status"] = result_dict["status"]
                result_dict = await self._llm_validate_result(
                    result_dict, monitor_type, target
                )
                result_dict["final_status"] = result_dict["status"]

            return result_dict
        except Exception as e:
            logger.error(f"[Executor] Tool monitor failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Tool monitor execution failed: {str(e)}",
            }

    def _create_tool_client(
        self, monitor_type: str, integration_config: Dict[str, Any]
    ) -> Any:
        """Instantiate the appropriate integration client for a tool monitor."""
        tool_type = (integration_config.get("type") or "").lower()

        if monitor_type in ("sync_lag", "failed_syncs", "connector_schema_drift"):
            from scanner.integrations.fivetran import FivetranIntegration

            return FivetranIntegration(integration_config)

        if monitor_type in ("dag_last_run", "dag_schedule_lag", "task_failure_rate"):
            # Airflow monitors require a live API connection — GitHub DAG-file mode
            # only provides static project files and cannot query run status.
            source_mode = integration_config.get("source_mode", "")
            has_host = bool(integration_config.get("host") or integration_config.get("base_url"))
            if source_mode == "github" or (not has_host and integration_config.get("github_repo")):
                raise ValueError(
                    "Airflow is connected in GitHub DAG-file mode (static project files only). "
                    "Airflow monitors require a live API connection. "
                    "Update the Airflow integration to use API mode with a host URL "
                    "(e.g. https://your-airflow.example.com)."
                )

            from scanner.integrations.airflow import AirflowIntegration

            return AirflowIntegration(integration_config)

        if monitor_type in ("dbt_test_failures", "dbt_model_freshness", "dbt_source_freshness"):
            # dbt_core (upload/project/github) doesn't have a live API — monitors require dbt Cloud
            source_mode = integration_config.get("source_mode", "")
            tool_t = (integration_config.get("type") or "").lower()
            if tool_t == "dbt_core" or source_mode in ("upload", "project", "github"):
                api_key = integration_config.get("api_key") or integration_config.get("token", "")
                if not api_key:
                    raise ValueError(
                        f'dbt integration is connected in {source_mode or "local"} mode '
                        "(static project files only). dbt monitors require a live dbt Cloud API "
                        "connection to check job runs and test results. Switch to a dbt Cloud "
                        "integration with an API key and account ID to enable monitors."
                    )

            from scanner.integrations.dbt import DbtCloudClient

            api_key = integration_config.get("api_key") or integration_config.get("token", "")
            account_id = integration_config.get("account_id")
            return DbtCloudClient(api_key=api_key, account_id=account_id)

        raise ValueError(f"No client mapping for monitor type: {monitor_type}")

    # Mapping from tool monitor types to the PipelineNode toolType(s) that provide them.
    _TOOL_MONITOR_NODE_TYPES: Dict[str, list] = {
        "sync_lag": ["fivetran", "airbyte"],
        "failed_syncs": ["fivetran", "airbyte"],
        "connector_schema_drift": ["fivetran", "airbyte"],
        "dag_last_run": ["airflow", "dagster"],
        "dag_schedule_lag": ["airflow", "dagster"],
        "task_failure_rate": ["airflow", "dagster"],
        "dbt_test_failures": ["dbt_cloud", "dbt_core"],
        "dbt_model_freshness": ["dbt_cloud", "dbt_core"],
        "dbt_source_freshness": ["dbt_cloud", "dbt_core"],
    }

    async def _get_tool_config(
        self,
        integration_id: Optional[str],
        organization_id: Optional[str],
        monitor_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch tool integration config from PipelineNode.

        Same pattern as _get_server_config, but dynamically filters by
        the toolType(s) required for the given monitor_type.
        """
        if not integration_id and not organization_id:
            return None

        required_types = self._TOOL_MONITOR_NODE_TYPES.get(monitor_type)
        if not required_types:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    # Query Integration.credentials (where the real config lives)
                    # and fall back to PipelineNode.config for legacy nodes
                    if integration_id:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType",
                                   i.credentials AS int_creds, pn.config
                            FROM "PipelineNode" pn
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE pn."integrationId" = %s
                              AND pn."toolType" = ANY(%s)
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (integration_id, required_types),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType",
                                   i.credentials AS int_creds, pn.config
                            FROM "PipelineNode" pn
                            JOIN "PipelineStack" ps ON pn."stackId" = ps.id
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE ps."organizationId" = %s
                              AND pn."toolType" = ANY(%s)
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            ORDER BY pn."createdAt" ASC
                            LIMIT 1
                            """,
                            (organization_id, required_types),
                        )

                    row = cur.fetchone()
                    if not row:
                        logger.warning(
                            f"[Executor] No {required_types} pipeline node found for {monitor_type}"
                        )
                        return None

                    node_id, node_name, tool_type, int_creds, raw_config = row

                    # Prefer Integration credentials (where pipeline save stores them),
                    # fall back to PipelineNode.config for legacy/unsaved nodes
                    config_source = int_creds or raw_config or {}
                    if isinstance(config_source, str):
                        config_source = json.loads(config_source)

                    # Decrypt credentials
                    credentials: Dict[str, Any] = {}
                    if isinstance(config_source, dict) and "encrypted" in config_source:
                        try:
                            decrypted = _decrypt(config_source["encrypted"])
                            credentials = json.loads(decrypted)
                        except Exception as e:
                            logger.warning(
                                f"[Executor] Failed to decrypt tool config for {node_name}: {e}"
                            )
                            return None
                    elif isinstance(config_source, dict):
                        credentials = {k: v for k, v in config_source.items() if k != "_cached"}

                    logger.info(
                        "[Executor] Resolved tool config",
                        node=node_name,
                        type=tool_type,
                        monitor=monitor_type,
                    )
                    return {
                        "id": node_id,
                        "name": node_name,
                        "type": tool_type,
                        **credentials,
                    }
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[Executor] Failed to fetch tool config: {e}")
            return None

    async def _get_server_config(
        self,
        integration_id: Optional[str],
        organization_id: Optional[str] = None,
        server_node_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch server connection config from a LINUX_SERVER pipeline node."""
        if not integration_id and not organization_id and not server_node_id:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    if server_node_id:
                        # Direct lookup by PipelineNode ID (from config.serverNodeId)
                        # Don't filter by status — user explicitly linked this node
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType",
                                   i.credentials AS int_creds, pn.config
                            FROM "PipelineNode" pn
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE pn.id = %s
                            LIMIT 1
                            """,
                            (server_node_id,),
                        )
                    elif integration_id:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType",
                                   i.credentials AS int_creds, pn.config
                            FROM "PipelineNode" pn
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE pn."integrationId" = %s
                              AND pn."toolType" = 'linux_server'
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (integration_id,),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType",
                                   i.credentials AS int_creds, pn.config
                            FROM "PipelineNode" pn
                            JOIN "PipelineStack" ps ON pn."stackId" = ps.id
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE ps."organizationId" = %s
                              AND pn."toolType" = 'linux_server'
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            ORDER BY pn."createdAt" ASC
                            LIMIT 1
                            """,
                            (organization_id,),
                        )

                    row = cur.fetchone()
                    if not row:
                        logger.warning("[Executor] No linux_server pipeline node found")
                        return None

                    node_id, node_name, tool_type, int_creds, raw_config = row
                    config_source = int_creds or raw_config or {}
                    if isinstance(config_source, str):
                        config_source = json.loads(config_source)

                    # Decrypt credentials
                    credentials: Dict[str, Any] = {}
                    if isinstance(config_source, dict) and "encrypted" in config_source:
                        try:
                            decrypted = _decrypt(config_source["encrypted"])
                            credentials = json.loads(decrypted)
                        except Exception as e:
                            logger.warning(f"[Executor] Failed to decrypt server config for {node_name}: {e}")
                            return None
                    elif isinstance(config_source, dict):
                        credentials = {k: v for k, v in config_source.items() if k != "_cached"}

                    logger.info(
                        "[Executor] Resolved server config",
                        node=node_name,
                        host=credentials.get("host"),
                    )
                    return credentials
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[Executor] Failed to fetch server config: {e}")
            return None

    async def _execute_prompt(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run an LLM prompt-based check."""
        prompt = task.get("prompt", "")
        if not prompt:
            return {
                "status": "ERROR",
                "message": "No prompt provided for prompt-based task",
            }

        try:
            import openai
            import os
            import asyncio

            client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

            # Build a system message that instructs the LLM to act as a monitor
            system_msg = (
                "You are a data quality monitor. Execute the user's check instruction "
                "against the data pipeline. Use the query_warehouse tool to run SQL queries "
                "and inspect the data. After analysis, respond with a JSON object "
                'containing: {"status": "PASS"|"WARN"|"FAIL", "message": "explanation", '
                '"details": {}}. Only respond with valid JSON.'
            )

            # Get integration config for warehouse access
            integration_config = task.get("integrationConfig") or await self._get_integration_config(
                task.get("integrationId"), task.get("organizationId")
            )

            # Set up warehouse query function if integration is available
            query_func = None
            dialect = None
            if integration_config:
                try:
                    tool_type = integration_config.get("type", "").lower()
                    dialect = _detect_dialect(tool_type)
                    query_func, dialect = _get_query_func(integration_config, dialect)
                except Exception as e:
                    logger.warning(f"[Executor] Could not connect warehouse for prompt task: {e}")

            # Define tools for the LLM (OpenAI function calling format)
            tools = []
            if query_func:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": "query_warehouse",
                        "description": "Execute a read-only SQL SELECT query against the data warehouse.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "sql": {"type": "string", "description": "The SQL SELECT query to execute"},
                            },
                            "required": ["sql"],
                        },
                    },
                })

            # Tool-calling loop (max 5 iterations)
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ]
            response_text = ""
            for _ in range(5):
                api_kwargs = {
                    "model": "gpt-5-mini",
                    "max_completion_tokens": 1024,
                    "messages": messages,
                }
                if tools:
                    api_kwargs["tools"] = tools

                response = client.chat.completions.create(**api_kwargs)
                choice = response.choices[0] if response.choices else None
                if not choice:
                    break

                msg = choice.message

                # Check if LLM wants to call tools
                if choice.finish_reason == "tool_calls" and msg.tool_calls:
                    # Append assistant message with tool calls
                    messages.append(msg)
                    for tool_call in msg.tool_calls:
                        if tool_call.function.name == "query_warehouse":
                            try:
                                args = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": "Error: Invalid tool arguments.",
                                })
                                continue
                            sql = args.get("sql", "")
                            # Validate read-only
                            sql_upper = sql.strip().upper()
                            if not (sql_upper.startswith("SELECT") or (sql_upper.startswith("WITH") and "SELECT" in sql_upper)):
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": "Error: Only SELECT queries are allowed.",
                                })
                                continue
                            try:
                                rows = await asyncio.to_thread(query_func, sql)
                                limited = rows[:100] if rows else []
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({"row_count": len(rows), "rows": limited[:20]}, default=str),
                                })
                            except Exception as qe:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": f"Query error: {str(qe)}",
                                })
                    continue

                # No tool call — extract final text response
                response_text = msg.content or ""
                break

            # Try to parse LLM response as JSON for structured result
            try:
                # Strip markdown code fences if present
                cleaned = response_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                parsed = json.loads(cleaned)
                return {
                    "status": parsed.get("status", "PASS").upper(),
                    "message": parsed.get("message", response_text),
                    "details": parsed.get("details", {}),
                }
            except json.JSONDecodeError:
                # LLM didn't return JSON — treat as informational PASS
                return {
                    "status": "PASS",
                    "message": response_text[:500],
                    "details": {"raw_response": response_text},
                }

        except Exception as e:
            logger.error(f"[Executor] Prompt task failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Prompt execution failed: {str(e)}",
            }

    async def _get_integration_config(
        self, integration_id: Optional[str], organization_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch warehouse connection config.

        Uses PipelineNode (where credentials live) rather than Integration.
        If organization_id is provided, auto-discovers the first connected
        warehouse node in the org's pipeline stack.
        """
        if not integration_id and not organization_id:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    if integration_id:
                        # Look up specific pipeline node by integration ID
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config
                            FROM "PipelineNode" pn
                            WHERE pn."integrationId" = %s
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (integration_id,),
                        )
                    else:
                        # Auto-discover: find first connected warehouse node in the org
                        tool_types = list(_WAREHOUSE_TOOL_TYPES)
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config
                            FROM "PipelineNode" pn
                            JOIN "PipelineStack" ps ON pn."stackId" = ps.id
                            WHERE ps."organizationId" = %s
                              AND pn."toolType" = ANY(%s)
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            ORDER BY pn."createdAt" ASC
                            LIMIT 1
                            """,
                            (organization_id, tool_types),
                        )

                    row = cur.fetchone()
                    if not row:
                        logger.warning("[Executor] No warehouse pipeline node found")
                        return None

                    node_id, node_name, tool_type, raw_config = row
                    config = raw_config or {}
                    if isinstance(config, str):
                        config = json.loads(config)

                    # Decrypt credentials (same as lib/crypto.ts)
                    credentials: Dict[str, Any] = {}
                    if isinstance(config, dict) and "encrypted" in config:
                        try:
                            decrypted = _decrypt(config["encrypted"])
                            credentials = json.loads(decrypted)
                        except Exception as e:
                            logger.warning(f"[Executor] Failed to decrypt config for {node_name}: {e}")
                            return None
                    elif isinstance(config, dict):
                        credentials = {k: v for k, v in config.items() if k != "_cached"}

                    result = {
                        "id": node_id,
                        "name": node_name,
                        "type": tool_type,
                        **credentials,
                    }

                    # Field mapping: username → user (same as copilot/chat/route.ts)
                    upper_type = tool_type.upper() if tool_type else ""
                    if upper_type in ("SNOWFLAKE", "POSTGRES", "REDSHIFT"):
                        if "username" in result and "user" not in result:
                            result["user"] = result.pop("username")

                    logger.info(
                        "[Executor] Resolved warehouse config",
                        node=node_name,
                        type=tool_type,
                    )
                    return result
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[Executor] Failed to fetch integration config: {e}")
            return None
