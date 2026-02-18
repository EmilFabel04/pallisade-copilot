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
        else:
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
                result_dict = await self._llm_validate_result(
                    result_dict, resolved_type, target_fqn
                )

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
            from scanner.copilot.llm import CopilotLLM

            llm = CopilotLLM()

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

            llm_result = await llm.chat(
                message=prompt,
                system_prompt=system_msg,
                integrations=[],
            )

            response_text = llm_result.get("message", "")

            # Parse LLM response
            import json as json_mod
            # Strip markdown code fences if present
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json_mod.loads(cleaned)
            adjusted_status = parsed.get("adjusted_status", result_dict["status"]).upper()
            explanation = parsed.get("explanation", "")
            confidence = parsed.get("confidence", 0.5)

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
                    "adjusted_status": adjusted_status,
                    "explanation": explanation,
                    "confidence": confidence,
                }

            logger.info(
                "[Executor] LLM validation complete",
                original_status=result_dict.get("status"),
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
        """Discover numeric columns and run anomaly check on each one.

        Returns an aggregated result with per-column details.
        """
        from scanner.monitors.anomaly import AnomalyMonitor
        from scanner.monitors.base import MonitorStatus

        columns = _discover_numeric_columns(
            executor.query_func, database, schema, table, dialect
        )

        if not columns:
            return {
                "status": "WARN",
                "message": f"No numeric columns found in {database}.{schema}.{table}",
            }

        logger.info(
            f"[Executor] Multi-column anomaly: checking {len(columns)} columns",
            columns=columns,
        )

        metric = config.get("metric", "avg")
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
        integration_config = task.get("integrationConfig") or await self._get_server_config(
            task.get("integrationId"), task.get("organizationId")
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
                result_dict = await self._llm_validate_result(
                    result_dict, monitor_type, integration_config.get("host", "unknown")
                )

            return result_dict
        except Exception as e:
            logger.error(f"[Executor] Infrastructure monitor failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Infrastructure monitor failed: {str(e)}",
            }
        finally:
            adapter.disconnect()

    async def _get_server_config(
        self, integration_id: Optional[str], organization_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch server connection config from a LINUX_SERVER pipeline node."""
        if not integration_id and not organization_id:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    if integration_id:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config
                            FROM "PipelineNode" pn
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
                            SELECT pn.id, pn.name, pn."toolType", pn.config
                            FROM "PipelineNode" pn
                            JOIN "PipelineStack" ps ON pn."stackId" = ps.id
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

                    node_id, node_name, tool_type, raw_config = row
                    config = raw_config or {}
                    if isinstance(config, str):
                        config = json.loads(config)

                    # Decrypt credentials
                    credentials: Dict[str, Any] = {}
                    if isinstance(config, dict) and "encrypted" in config:
                        try:
                            decrypted = _decrypt(config["encrypted"])
                            credentials = json.loads(decrypted)
                        except Exception as e:
                            logger.warning(f"[Executor] Failed to decrypt server config for {node_name}: {e}")
                            return None
                    elif isinstance(config, dict):
                        credentials = {k: v for k, v in config.items() if k != "_cached"}

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
            from scanner.copilot.llm import CopilotLLM

            llm = CopilotLLM()

            # Build a system message that instructs the LLM to act as a monitor
            system_msg = (
                "You are a data quality monitor. Execute the user's check instruction "
                "against the data pipeline. After analysis, respond with a JSON object "
                "containing: {\"status\": \"PASS\"|\"WARN\"|\"FAIL\", \"message\": \"explanation\", "
                "\"details\": {}}. Only respond with valid JSON."
            )

            # Get integration config for warehouse access
            integration_config = task.get("integrationConfig") or await self._get_integration_config(
                task.get("integrationId"), task.get("organizationId")
            )

            # Build context with available tools
            result = await llm.chat(
                message=prompt,
                system_prompt=system_msg,
                integrations=[integration_config] if integration_config else [],
            )

            # Try to parse LLM response as JSON for structured result
            response_text = result.get("message", "")
            try:
                parsed = json.loads(response_text)
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
