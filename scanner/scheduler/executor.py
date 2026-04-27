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
from scanner.monitors.bi import BI_MONITOR_TYPES, BI_MONITOR_REGISTRY

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


def _run_coro_sync(coro):
    """Run an async coroutine from sync code, regardless of whether the
    calling thread already has a running event loop.

    The dbt-core validation client is built synchronously but is itself
    invoked from inside the scheduler's async pipeline, so a naïve
    ``asyncio.get_event_loop().run_until_complete(...)`` either errors
    ('no current event loop' on Python 3.12+) or deadlocks ('This event
    loop is already running') depending on the caller. This helper picks
    the right strategy: ``asyncio.run`` if no loop is running, otherwise
    run in a worker thread with its own fresh loop.
    """
    import asyncio as _asyncio
    import concurrent.futures as _cf
    try:
        _asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False
    if not running:
        return _asyncio.run(coro)
    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_asyncio.run, coro).result()


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


def _resilient_query_func(adapter, connect_error_msg: str):
    """Wrap adapter.execute_query so transient disconnects auto-reconnect once.

    Production robustness: idle-timeouts, network blips, and gRPC channel
    deaths can leave an adapter's `_connection` stale between queries. On
    ConnectionError (or a driver-level "closed connection" message), this
    wrapper reconnects and retries the query exactly once before giving up.
    """
    _TRANSIENT_HINTS = (
        "not connected to database",
        "connection closed",
        "connection already closed",
        "server closed the connection",
        "ssl connection has been closed",
        "broken pipe",
        "eof detected",
    )

    def _is_transient(exc: Exception) -> bool:
        if isinstance(exc, ConnectionError):
            return True
        msg = str(exc).lower()
        return any(hint in msg for hint in _TRANSIENT_HINTS)

    def query(sql: str, params=None):
        try:
            return adapter.execute_query(sql, params) if params else adapter.execute_query(sql)
        except Exception as exc:
            if not _is_transient(exc):
                raise
            logger.warning(
                "[Executor] Transient warehouse disconnect, reconnecting once",
                adapter=type(adapter).__name__,
                error=str(exc)[:200],
            )
            if not adapter.connect():
                raise ConnectionError(
                    f"Reconnect failed after transient error: {connect_error_msg}"
                ) from exc
            return adapter.execute_query(sql, params) if params else adapter.execute_query(sql)

    return query


def _get_query_func(integration_config: Dict[str, Any], dialect: str):
    """Build a warehouse query function from integration config.

    Creates the adapter, calls connect(), and returns a resilient wrapper
    around execute_query that reconnects once on transient disconnects.
    Raises ConnectionError if the adapter cannot make the initial connection.
    """
    if dialect == "bigquery":
        from scanner.adapters.bigquery import BigQueryAdapter

        adapter = BigQueryAdapter(integration_config)
        connect_err = (
            f"BigQuery project "
            f"{integration_config.get('project') or integration_config.get('project_id', '?')}. "
            f"Check credentials and project ID."
        )
        if not adapter.connect():
            raise ConnectionError(f"Failed to connect to {connect_err}")
        return _resilient_query_func(adapter, connect_err), "bigquery"
    elif dialect == "snowflake":
        from scanner.adapters.snowflake import SnowflakeAdapter

        adapter = SnowflakeAdapter(integration_config)
        connect_err = (
            f"Snowflake {integration_config.get('account', '?')}. "
            f"Check credentials and account."
        )
        if not adapter.connect():
            raise ConnectionError(f"Failed to connect to {connect_err}")
        return _resilient_query_func(adapter, connect_err), "snowflake"
    elif dialect in ("postgres", "postgresql", "redshift"):
        from scanner.adapters.postgres import PostgresAdapter

        adapter = PostgresAdapter(integration_config)
        connect_err = (
            f"{dialect} {integration_config.get('host', '?')}:{integration_config.get('port', '?')}. "
            f"Check credentials and host."
        )
        if not adapter.connect():
            raise ConnectionError(f"Failed to connect to {connect_err}")
        return _resilient_query_func(adapter, connect_err), "postgres"
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


# Column-type → recommended metric presets for Outlier Detection.
# null_rate and distinct_count are owned by dedicated monitors
# (null_check, uniqueness_check) and should NOT be run here.
_STRING_METRICS: list[str] = []  # string columns handled by null_check + uniqueness_check
_NUMERIC_METRICS = ["avg", "min", "max", "zero_rate"]
_DATETIME_METRICS = ["min", "max"]

# Type classification sets
_NUMERIC_TYPES = {
    "integer", "bigint", "smallint", "int", "int64", "float64", "numeric",
    "bignumeric", "decimal", "real", "double precision", "float", "float4",
    "float8", "double", "number", "tinyint", "byteint",
}
_DATETIME_TYPES = {
    "date", "datetime", "timestamp", "timestamptz",
    "timestamp with time zone", "timestamp without time zone",
    "timestamp_ltz", "timestamp_ntz", "timestamp_tz",
}


def _discover_columns_with_types(
    query_func, database: str, schema: str, table: str, dialect: str
) -> list[tuple[str, str]]:
    """Discover columns with their data types.

    Returns list of (column_name, data_type) tuples.
    Excludes complex types (STRUCT, ARRAY, JSON, etc.).
    """
    if dialect == "bigquery":
        exclude = "'STRUCT', 'ARRAY', 'GEOGRAPHY', 'JSON', 'RECORD'"
        sql = (
            f"SELECT column_name, data_type FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = '{table}' AND data_type NOT IN ({exclude}) "
            f"ORDER BY ordinal_position"
        )
    elif dialect == "snowflake":
        exclude = "'VARIANT', 'OBJECT', 'ARRAY'"
        sql = (
            f"SELECT COLUMN_NAME, DATA_TYPE FROM {database}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{schema.upper()}' AND TABLE_NAME = '{table.upper()}' "
            f"AND DATA_TYPE NOT IN ({exclude}) ORDER BY ORDINAL_POSITION"
        )
    else:
        exclude = "'json', 'jsonb', 'xml', 'point', 'polygon', 'line'"
        sql = (
            f"SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
            f"AND data_type NOT IN ({exclude}) ORDER BY ordinal_position"
        )

    try:
        rows = query_func(sql)
        result = []
        for row in rows:
            name = row.get("column_name") or row.get("COLUMN_NAME", "")
            dtype = (row.get("data_type") or row.get("DATA_TYPE", "")).lower()
            if name:
                result.append((name, dtype))
        return result
    except Exception as e:
        logger.warning(f"[Executor] Failed to discover columns with types: {e}")
        return []


def _metrics_for_type(data_type: str) -> list[str]:
    """Return the recommended metric presets for a given column data type."""
    dt = data_type.lower().strip()
    # Strip precision/length
    paren = dt.find("(")
    if paren > 0:
        dt = dt[:paren].strip()

    if dt in _NUMERIC_TYPES:
        return _NUMERIC_METRICS
    if dt in _DATETIME_TYPES:
        return _DATETIME_METRICS
    # Default: string/boolean/other
    return _STRING_METRICS


class TaskExecutor:
    """Executes a scheduled task (structured monitor or LLM prompt)."""

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task and return the result dict.

        Returns:
            Dict with keys: status, value, threshold, message, details, sql_executed
        """
        task_mode = task.get("taskMode", "structured")
        monitor_type_raw = (task.get("monitorType") or "").lower()

        if task_mode == "prompt" or monitor_type_raw == "ai_prompt":
            return await self._execute_prompt(task)

        # Check if this is a tool monitor (Fivetran/Airflow/dbt) before
        # falling through to the warehouse-SQL structured path.
        monitor_type = (task.get("monitorType") or "").lower()
        if monitor_type in TOOL_MONITOR_TYPES:
            return await self._execute_tool_monitor(task, monitor_type)

        # BI monitors use dashboard/report names (not SQL FQNs) — handle separately
        if monitor_type in BI_MONITOR_TYPES:
            return await self._execute_bi(task, monitor_type)

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

        # --- Policy-aware config merge ---
        policy_config = task.get("policyConfig")
        policy_overrides = task.get("policyOverrides") or []
        if policy_config:
            from scanner.monitors.policy_config import merge_policy_config
            config, provenance = merge_policy_config(
                monitor_type=monitor_type,
                config=config,
                policy_config=policy_config,
                policy_overrides=policy_overrides,
            )
            logger.info(
                "[Executor] Policy config merged",
                provenance=provenance,
                override_count=len(policy_overrides),
            )

        # Create monitor instance from resolved config
        monitor = monitor_cls(config=config) if config else monitor_cls()

        # Check if monitor needs user configuration before it can run
        if hasattr(monitor, 'needs_configuration') and monitor.needs_configuration:
            return {
                "status": "WARN",
                "message": "Monitor needs configuration before it can run. Please edit the monitor config to set required fields (e.g. column for outlier detection).",
                "change": "Needs configuration",
                "metric": "config",
                "current": "Not configured",
                "baseline": "N/A",
                "status_reason": "Monitor requires additional configuration (e.g. column) before it can execute.",
            }

        # Get warehouse query function — use pre-fetched config or look up by ID/org
        # Also try config.nodeId (mirrors tasks/[taskId]/run/route.ts step 2)
        task_config = task.get("config") or {}
        config_node_id = task_config.get("nodeId") if isinstance(task_config, dict) else None
        integration_config = task.get("integrationConfig") or await self._get_integration_config(
            task.get("integrationId"), task.get("organizationId"),
            node_id=config_node_id,
        )

        if not integration_config:
            logger.warning("[Executor] No integration config resolved")
            return {
                "status": "ERROR",
                "message": "No warehouse integration configured for this task. Connect a warehouse integration or select one when creating the task.",
            }

        integration_type = integration_config.get("type", "postgres")
        dialect = _detect_dialect(integration_type)

        # The FQN database may not match the connected warehouse's project/database.
        # e.g. FQN "postgres.public.orders" from Fivetran lineage where the actual
        # data lives in BigQuery project "acme-484520". Remap to the real project.
        integration_db = (
            integration_config.get("project_id")
            or integration_config.get("project")
            or integration_config.get("database")
            or ""
        )
        if integration_db and database.lower() != integration_db.lower():
            logger.info(
                "[Executor] Remapping FQN database to integration project",
                fqn_database=database,
                integration_database=integration_db,
            )
            database = integration_db

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
            # Log resolved config keys for debugging connection issues
            safe_keys = [k for k in integration_config.keys() if k not in ("credentials", "credentials_json", "password", "private_key")]
            logger.info(
                "[Executor] Connecting to warehouse",
                dialect=dialect,
                config_keys=safe_keys,
                has_credentials="credentials" in integration_config or "credentials_json" in integration_config,
                has_password="password" in integration_config,
                project=integration_config.get("project") or integration_config.get("project_id"),
                host=integration_config.get("host"),
            )
            query_func, sql_dialect = _get_query_func(integration_config, dialect)
            logger.info("[Executor] Connected, running auto-configure", monitor_type=resolved_type)
            executor = MonitorExecutor(query_func=query_func, dialect=sql_dialect)

            # Auto-configure: fill in missing config from warehouse data
            config = executor.auto_configure(
                resolved_type, database, schema, table, config
            )
            logger.info("[Executor] Auto-configure done, executing monitor", monitor_type=resolved_type)

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
        """Discover numeric columns and run distribution outlier check on each.

        Uses distribution mode (IQR-based) by default — one query per
        numeric column, giving stats + outlier counts in a single pass.
        String/datetime columns are skipped (handled by null_check and
        uniqueness_check monitors).

        Returns an aggregated result with per-column details.
        """
        from scanner.monitors.anomaly import AnomalyMonitor
        from scanner.monitors.base import MonitorStatus
        from scanner.monitors.executor import MAX_MULTI_COLUMNS

        mode = config.get("mode", "distribution")

        # Discover columns with types
        columns_with_types = _discover_columns_with_types(
            executor.query_func, database, schema, table, dialect
        )

        if not columns_with_types:
            # Fallback to old discovery (types unknown)
            columns = _discover_numeric_columns(
                executor.query_func, database, schema, table, dialect
            )
            columns_with_types = [(c, "unknown") for c in columns]

        # Filter to numeric columns only for distribution mode
        if mode == "distribution":
            numeric_cols = [
                (name, dtype) for name, dtype in columns_with_types
                if dtype.lower().strip().split("(")[0] in _NUMERIC_TYPES
                or dtype == "unknown"
            ]
        else:
            numeric_cols = columns_with_types

        numeric_cols = numeric_cols[:MAX_MULTI_COLUMNS]

        if not numeric_cols:
            return {
                "status": "PASS",
                "message": f"No numeric columns found in {database}.{schema}.{table} for outlier detection",
            }

        logger.info(
            f"[Executor] Multi-column outlier detection: "
            f"checking {len(numeric_cols)} numeric columns",
            columns=[c[0] for c in numeric_cols],
            mode=mode,
        )
        per_column: list[dict] = []
        anomalies: list[str] = []
        warnings: list[str] = []

        for col_name, col_type in numeric_cols:
            col_config = {**config, "column": col_name}
            # Ensure distribution mode for the per-column monitor
            if mode == "distribution":
                col_config["mode"] = "distribution"

            col_monitor = AnomalyMonitor(config=col_config)

            try:
                result = executor.run_monitor(
                    col_monitor, database, schema, table
                )
                entry = result.to_dict()
                entry["column"] = col_name
                per_column.append(entry)

                if result.status == MonitorStatus.FAIL:
                    anomalies.append(f"{col_name}: {result.message}")
                elif result.status == MonitorStatus.WARN:
                    warnings.append(f"{col_name}: {result.message}")
            except Exception as e:
                logger.warning(f"[Executor] Column {col_name} failed: {e}")
                per_column.append({
                    "column": col_name,
                    "status": "ERROR",
                    "message": str(e),
                })

        n_cols = len(numeric_cols)
        if anomalies:
            return {
                "status": "FAIL",
                "message": (
                    f"Outliers detected in {len(anomalies)} of "
                    f"{n_cols} columns: {'; '.join(anomalies[:5])}"
                ),
                "details": {
                    "columns_checked": n_cols,
                    "anomalies": len(anomalies),
                    "warnings": len(warnings),
                    "per_column": per_column,
                },
            }

        if warnings:
            return {
                "status": "WARN",
                "message": (
                    f"Minor outliers in {len(warnings)} of "
                    f"{n_cols} columns: {'; '.join(warnings[:5])}"
                ),
                "details": {
                    "columns_checked": n_cols,
                    "anomalies": 0,
                    "warnings": len(warnings),
                    "per_column": per_column,
                },
            }

        return {
            "status": "PASS",
            "message": (
                f"No outliers detected across {n_cols} numeric columns"
            ),
            "details": {
                "columns_checked": n_cols,
                "anomalies": 0,
                "warnings": 0,
                "per_column": per_column,
            },
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
        tool_config = task.get("config") or {}
        tool_node_id = (tool_config.get("toolNodeId") or tool_config.get("nodeId")) if isinstance(tool_config, dict) else None
        integration_config = task.get("integrationConfig") or await self._get_tool_config(
            task.get("integrationId"),
            task.get("organizationId"),
            monitor_type,
            node_id=tool_node_id,
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
                "dbt_core_source_validation": "dbt Core",
                "dbt_core_ref_integrity": "dbt Core",
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
            client = self._create_tool_client(monitor_type, integration_config, task=task)
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

        # Resolve connector_id for Fivetran/Airbyte monitors: if the stored
        # connector_id looks like a Pallisade CUID (not a real Fivetran ID),
        # try to resolve the real one from the integration's connector list.
        if monitor_type in ("sync_lag", "failed_syncs", "connector_schema_drift"):
            stored_cid = config.get("connector_id", "")
            if stored_cid and len(stored_cid) > 20 and stored_cid.startswith("c") and not stored_cid.startswith("connector_"):
                # Looks like a Pallisade CUID, not a real Fivetran connector ID.
                # Try to resolve from the Fivetran API.
                try:
                    connectors = client.get_connectors()
                    if connectors and len(connectors) == 1:
                        # Single connector — use it directly
                        real_id = getattr(connectors[0], "id", "")
                        if real_id:
                            logger.info(
                                "[Executor] Resolved Fivetran connector_id",
                                old=stored_cid, new=real_id,
                            )
                            config = {**config, "connector_id": real_id}
                    elif connectors:
                        # Multiple connectors — try to match by target_fqn
                        target = task.get("targetFqn", "").lower()
                        for conn in connectors:
                            conn_name = (getattr(conn, "schema", "") or getattr(conn, "id", "")).lower()
                            service = (getattr(conn, "service", "") or "").lower()
                            if conn_name and (conn_name in target or target in conn_name or service in target):
                                real_id = getattr(conn, "id", "")
                                if real_id:
                                    logger.info(
                                        "[Executor] Resolved Fivetran connector_id by name match",
                                        old=stored_cid, new=real_id, match=conn_name,
                                    )
                                    config = {**config, "connector_id": real_id}
                                    break
                except Exception as e:
                    logger.warning(f"[Executor] Failed to resolve Fivetran connector_id: {e}")

        # Inject baseline_schema for connector_schema_drift from the latest
        # persisted snapshot so the monitor can diff against it.
        if monitor_type == "connector_schema_drift" and not config.get("baseline_schema"):
            try:
                from scanner.monitors.baseline_store import BaselineStore
                from scanner.scheduler.service import _get_connection

                store_conn = _get_connection()
                try:
                    store = BaselineStore(store_conn)
                    latest = store.get_latest_details(
                        task.get("id", ""), "connector_schema"
                    )
                    if latest and isinstance(latest.get("schema_snapshot"), dict):
                        config = {
                            **config,
                            "baseline_schema": {"tables": latest["schema_snapshot"]},
                        }
                        logger.info(
                            "[Executor] Injected baseline schema for connector_schema_drift",
                            table_count=len(latest["schema_snapshot"]),
                        )
                finally:
                    store_conn.close()
            except Exception as e:
                logger.debug(f"[Executor] Could not load connector baseline schema: {e}")

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

    async def _execute_bi(
        self, task: Dict[str, Any], monitor_type: str
    ) -> Dict[str, Any]:
        """Run a BI/reporting monitor (dashboard freshness, content health, etc.).

        BI monitors use dashboard/report names as targetFqn (not SQL table FQNs)
        and query BI platform APIs instead of running SQL.
        """
        config = task.get("config") or {}
        target_fqn = task.get("targetFqn", "")

        # Use targetFqn as asset_id if not explicitly set in config
        if not config.get("asset_id") and target_fqn:
            config["asset_id"] = target_fqn

        monitor_cls = BI_MONITOR_REGISTRY.get(monitor_type)
        if not monitor_cls:
            return {
                "status": "ERROR",
                "message": f"Unknown BI monitor type: {monitor_type}",
            }

        # Resolve BI integration config
        integration_config = task.get("integrationConfig") or {}
        bi_client = self._create_bi_client(integration_config)

        if not bi_client:
            platform = integration_config.get("type", "BI platform")
            return {
                "status": "SKIPPED",
                "message": (
                    f"No live {platform} integration found. "
                    f"BI monitors require a connected BI platform (Looker, Tableau, Power BI, or Metabase) "
                    f"with API access. Connect one on the Pipeline page to enable this monitor."
                ),
            }

        try:
            result: MonitorResult = MonitorExecutor.execute_bi_monitor(
                monitor_type, config, bi_client,
            )
            result_dict = result.to_dict()

            # LLM validation for FAIL/WARN results
            llm_validate = config.get("llm_validate", True)
            target = target_fqn or f"bi:{config.get('asset_id', 'unknown')}"
            if llm_validate and result.status in (MonitorStatus.FAIL, MonitorStatus.WARN):
                result_dict["raw_status"] = result_dict["status"]
                result_dict = await self._llm_validate_result(
                    result_dict, monitor_type, target
                )
                result_dict["final_status"] = result_dict["status"]

            return result_dict
        except Exception as e:
            logger.error(f"[Executor] BI monitor failed: {e}")
            return {
                "status": "ERROR",
                "message": f"BI monitor execution failed: {str(e)}",
            }

    def _create_bi_client(
        self, integration_config: Dict[str, Any]
    ) -> Any:
        """Create a BI platform client from integration config.

        Returns a client with get_asset_metadata(asset_id) method,
        or None if no BI integration is configured.
        """
        bi_type = (integration_config.get("type") or "").lower()

        try:
            if bi_type == "looker":
                from scanner.integrations.looker import LookerClient
                return LookerClient(integration_config)
            elif bi_type == "tableau":
                from scanner.integrations.tableau import TableauClient
                return TableauClient(integration_config)
            elif bi_type in ("powerbi", "power_bi"):
                from scanner.integrations.powerbi import PowerBIClient
                return PowerBIClient(integration_config)
            elif bi_type == "metabase":
                from scanner.integrations.metabase import MetabaseClient
                return MetabaseClient(integration_config)
        except Exception as e:
            logger.warning(f"[Executor] Failed to create BI client ({bi_type}): {e}")

        return None

    def _create_tool_client(
        self,
        monitor_type: str,
        integration_config: Dict[str, Any],
        task: Optional[Dict[str, Any]] = None,
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

        if monitor_type in ("dbt_core_source_validation", "dbt_core_ref_integrity"):
            return self._create_dbt_core_validation_client(integration_config, task)

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

    def _create_dbt_core_validation_client(
        self,
        integration_config: Dict[str, Any],
        task: Optional[Dict[str, Any]],
    ) -> Any:
        """Build a DbtCoreValidationClient: parsed manifest + warehouse adapter.

        Manifest resolution order:
          1. integration_config["manifest"] (pre-parsed / uploaded).
          2. source_mode=="project" with project_files → parse_dbt_project.
          3. source_mode=="github" → fetch + parse.
        """
        from scanner.monitors.tools import DbtCoreValidationClient

        manifest = integration_config.get("manifest")
        if isinstance(manifest, str):
            import json as _json
            try:
                manifest = _json.loads(manifest)
            except Exception:
                manifest = None

        if not manifest:
            source_mode = integration_config.get("source_mode", "")
            warehouse_type = integration_config.get("warehouse_type", "bigquery")
            try:
                from scanner.lineage.dbt_project_parser import parse_dbt_project
            except ImportError:
                from lineage.dbt_project_parser import parse_dbt_project  # type: ignore

            if source_mode == "project" and isinstance(integration_config.get("project_files"), dict):
                try:
                    manifest = parse_dbt_project(
                        files=integration_config["project_files"],
                        project_name=integration_config.get("project_name", ""),
                        default_database=integration_config.get("database", ""),
                        warehouse_type=warehouse_type,
                    )
                except Exception as e:
                    raise ValueError(f"Failed to parse dbt project files: {e}")
            elif source_mode == "github":
                try:
                    import asyncio
                    try:
                        from scanner.lineage.github_reader import fetch_dbt_project_files_with_fallback
                    except ImportError:
                        from lineage.github_reader import fetch_dbt_project_files_with_fallback  # type: ignore
                    dbt_inline_token = (
                        (integration_config.get("github") or {}).get("token")
                        or integration_config.get("github_token")
                    )
                    org_id_for_token = (task or {}).get("organizationId")
                    workspace_token = (
                        None if dbt_inline_token else self._get_workspace_github_token(org_id_for_token)
                    )
                    token = dbt_inline_token or workspace_token
                    repo = integration_config.get("github_repo")
                    if not token or not repo:
                        # Diagnostic so the run-history error string tells us *why*
                        # the token chain failed instead of an opaque "missing".
                        logger.error(
                            "[dbt_core] token chain exhausted",
                            has_dbt_inline_token=bool(dbt_inline_token),
                            has_workspace_token=bool(workspace_token),
                            org_id_present=bool(org_id_for_token),
                            has_repo=bool(repo),
                            integration_config_keys=list(integration_config.keys()),
                        )
                        raise ValueError(
                            "dbt_core GitHub mode missing token or repo. "
                            f"(dbt_inline_token={'set' if dbt_inline_token else 'absent'}, "
                            f"workspace_token={'set' if workspace_token else 'absent'}, "
                            f"org_id={'set' if org_id_for_token else 'absent'}, "
                            f"repo={'set' if repo else 'absent'})"
                        )
                    project_files, fallback = _run_coro_sync(
                        fetch_dbt_project_files_with_fallback(
                            repo=repo,
                            token=token,
                            branch=integration_config.get("github_branch", "main"),
                            dbt_root=integration_config.get("dbt_project_path", ""),
                        )
                    )
                    if project_files:
                        manifest = parse_dbt_project(
                            files=project_files,
                            project_name=integration_config.get("project_name", ""),
                            default_database=integration_config.get("database", ""),
                            warehouse_type=warehouse_type,
                        )
                    elif fallback:
                        manifest = fallback
                except ValueError:
                    raise
                except Exception as e:
                    raise ValueError(f"Failed to load dbt project from GitHub: {e}")

        if not manifest:
            raise ValueError(
                "dbt_core integration has no manifest available. Re-upload the project "
                "or manifest.json, or reconnect the GitHub source."
            )

        warehouse_adapter = self._resolve_warehouse_adapter_for_dbt(
            integration_config, task
        )
        return DbtCoreValidationClient(manifest=manifest, warehouse_adapter=warehouse_adapter)

    def _resolve_warehouse_adapter_for_dbt(
        self,
        dbt_config: Dict[str, Any],
        task: Optional[Dict[str, Any]],
    ) -> Any:
        """Find a CONNECTED warehouse PipelineNode in the same pipeline and build its adapter."""
        from scanner.scheduler.service import _get_connection

        integration_id = (task or {}).get("integrationId")
        tool_cfg = (task or {}).get("config") or {}
        node_id = tool_cfg.get("toolNodeId") or tool_cfg.get("nodeId") if isinstance(tool_cfg, dict) else None

        warehouse_types = ("bigquery", "snowflake", "postgres", "redshift")

        try:
            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    # 1. Resolve dbt_core node's stackId.
                    stack_id = None
                    if integration_id:
                        cur.execute(
                            'SELECT "stackId" FROM "PipelineNode" WHERE "integrationId" = %s LIMIT 1',
                            (integration_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            stack_id = row[0]
                    if not stack_id and node_id:
                        cur.execute(
                            'SELECT "stackId" FROM "PipelineNode" WHERE id = %s',
                            (node_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            stack_id = row[0]

                    if not stack_id:
                        logger.warning("[Executor] dbt_core monitor: no stackId resolved; skipping warehouse adapter")
                        return None

                    # 2. Find a CONNECTED warehouse node in the same stack.
                    cur.execute(
                        """
                        SELECT pn."toolType", i.credentials AS int_creds, pn.config
                        FROM "PipelineNode" pn
                        LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                        WHERE pn."stackId" = %s
                          AND pn."toolType" = ANY(%s)
                          AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                        ORDER BY pn."updatedAt" DESC
                        LIMIT 1
                        """,
                        (stack_id, list(warehouse_types)),
                    )
                    row = cur.fetchone()
                    if not row:
                        logger.warning("[Executor] dbt_core monitor: no warehouse sibling in stack %s", stack_id)
                        return None

                    warehouse_type, int_creds, node_cfg = row
                    merged_cfg: Dict[str, Any] = {}
                    if isinstance(node_cfg, dict):
                        merged_cfg.update(node_cfg)
                    if isinstance(int_creds, dict):
                        merged_cfg.update(int_creds)
                    # Map common alt field names adapters expect.
                    if merged_cfg.get("username") and not merged_cfg.get("user"):
                        merged_cfg["user"] = merged_cfg["username"]
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[Executor] Failed to resolve warehouse adapter for dbt_core: {e}")
            return None

        try:
            try:
                from adapters.bigquery import BigQueryAdapter
                from adapters.snowflake import SnowflakeAdapter
                from adapters.postgres import PostgresAdapter
                from adapters.redshift import RedshiftAdapter
            except ImportError:
                from scanner.adapters.bigquery import BigQueryAdapter
                from scanner.adapters.snowflake import SnowflakeAdapter
                from scanner.adapters.postgres import PostgresAdapter
                from scanner.adapters.redshift import RedshiftAdapter

            adapters_map = {
                "bigquery": BigQueryAdapter,
                "snowflake": SnowflakeAdapter,
                "postgres": PostgresAdapter,
                "redshift": RedshiftAdapter,
            }
            cls = adapters_map.get(warehouse_type.lower())
            if not cls:
                return None
            return cls(merged_cfg)
        except Exception as e:
            logger.warning(f"[Executor] Failed to build {warehouse_type} adapter: {e}")
            return None

    # Mapping from tool monitor types to the PipelineNode toolType(s) that provide them.
    # dbt Cloud monitors require a live API (job_id) and don't apply to dbt Core projects.
    # dbt Core validation monitors run static checks against the parsed manifest.
    _TOOL_MONITOR_NODE_TYPES: Dict[str, list] = {
        "sync_lag": ["fivetran", "airbyte"],
        "failed_syncs": ["fivetran", "airbyte"],
        "connector_schema_drift": ["fivetran", "airbyte"],
        "dag_last_run": ["airflow", "dagster"],
        "dag_schedule_lag": ["airflow", "dagster"],
        "task_failure_rate": ["airflow", "dagster"],
        "dbt_test_failures": ["dbt_cloud"],
        "dbt_model_freshness": ["dbt_cloud"],
        "dbt_source_freshness": ["dbt_cloud"],
        "dbt_core_source_validation": ["dbt_core"],
        "dbt_core_ref_integrity": ["dbt_core"],
    }

    async def _get_tool_config(
        self,
        integration_id: Optional[str],
        organization_id: Optional[str],
        monitor_type: str,
        node_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch tool integration config from PipelineNode.

        Resolution order (mirrors tasks/[taskId]/run/route.ts):
        1. integration_id → PipelineNode with that FK
        2. node_id (from config.toolNodeId/nodeId) → specific PipelineNode by ID
        3. organization_id → auto-discover first matching tool node
        """
        if not integration_id and not node_id and not organization_id:
            return None

        required_types = self._TOOL_MONITOR_NODE_TYPES.get(monitor_type)
        if not required_types:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    row = None

                    # 1. Try integration_id
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
                        row = cur.fetchone()

                    # 2. Try node_id (config.toolNodeId)
                    if not row and node_id:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType",
                                   i.credentials AS int_creds, pn.config
                            FROM "PipelineNode" pn
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE pn.id = %s
                              AND pn."toolType" = ANY(%s)
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (node_id, required_types),
                        )
                        row = cur.fetchone()

                    # 3. Auto-discover
                    if not row and organization_id:
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

                    found_node_id, node_name, tool_type, int_creds, raw_config = row

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
                        "id": found_node_id,
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
        config = task.get("config") or {}
        prompt = task.get("prompt") or config.get("prompt", "")
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
            target_fqn = task.get("targetFqn", "")
            fqn_context = f"\nTarget table: {target_fqn}" if target_fqn and "." in target_fqn else ""
            system_msg = (
                "You are a data quality monitor. Execute the user's check instruction "
                "against the data pipeline. Use the query_warehouse tool to run SQL queries "
                "and inspect the data. You MUST run at least one query to validate the check. "
                "After analysis, respond with a JSON object "
                'containing: {"status": "PASS"|"WARN"|"FAIL", "message": "one sentence summary of what was checked and the result", '
                '"details": {"queries_run": N, "findings": "..."}}. Only respond with valid JSON.'
                f"{fqn_context}"
            )

            # Get integration config for warehouse access
            prompt_config = task.get("config") or {}
            prompt_node_id = prompt_config.get("nodeId") if isinstance(prompt_config, dict) else None
            integration_config = task.get("integrationConfig") or await self._get_integration_config(
                task.get("integrationId"), task.get("organizationId"),
                node_id=prompt_node_id,
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
            for iteration in range(5):
                api_kwargs: Dict[str, Any] = {
                    "model": "gpt-5-mini",
                    "max_completion_tokens": 2048,
                    "messages": messages,
                }
                if tools:
                    api_kwargs["tools"] = tools

                response = client.chat.completions.create(**api_kwargs)
                choice = response.choices[0] if response.choices else None
                if not choice:
                    break

                msg = choice.message

                # Check if LLM wants to call tools (check both finish_reason and tool_calls presence)
                if msg.tool_calls:
                    # Serialize the assistant message properly for the conversation
                    assistant_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ]
                    messages.append(assistant_msg)
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

            # If loop ended with tool calls but no final text, force a final call without tools
            if not response_text:
                messages.append({
                    "role": "user",
                    "content": "Now provide your final assessment as JSON: {\"status\": \"PASS\"|\"WARN\"|\"FAIL\", \"message\": \"summary\", \"details\": {}}",
                })
                try:
                    final_resp = client.chat.completions.create(
                        model="gpt-5-mini",
                        max_completion_tokens=1024,
                        messages=messages,
                    )
                    if final_resp.choices:
                        response_text = final_resp.choices[0].message.content or ""
                except Exception as e:
                    logger.warning(f"[Executor] Final assessment call failed: {e}")

            if not response_text:
                return {
                    "status": "ERROR",
                    "message": "AI monitor did not produce a final assessment after querying the warehouse.",
                    "details": {"iterations": iteration + 1},
                }

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
                    "message": response_text[:500] if response_text.strip() else "Check completed (no structured result from AI)",
                    "details": {"raw_response": response_text} if response_text.strip() else {},
                }

        except Exception as e:
            logger.error(f"[Executor] Prompt task failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Prompt execution failed: {str(e)}",
            }

    def _get_workspace_github_token(self, organization_id: Optional[str]) -> Optional[str]:
        """Look up the workspace-level GITHUB integration's OAuth access token.

        Used as a fallback when a per-tool integration (e.g. dbt Core in
        GitHub mode) doesn't carry its own github_token field — the user has
        a separately-connected GitHub OAuth integration whose accessToken
        column holds the credential. Returns None if the org has no active
        GitHub integration or the lookup fails.
        """
        if not organization_id:
            logger.info("[GitHub] workspace token lookup skipped — no organization_id on task")
            return None
        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, status, "accessToken" IS NOT NULL AS has_token
                        FROM "Integration"
                        WHERE type = 'GITHUB'
                          AND "organizationId" = %s
                        ORDER BY "updatedAt" DESC
                        LIMIT 5
                        """,
                        (organization_id,),
                    )
                    diag_rows = cur.fetchall() or []
                    logger.info(
                        "[GitHub] candidate integrations for org",
                        org_id=organization_id,
                        rows=[
                            {"id": r[0], "status": r[1], "has_token": bool(r[2])}
                            for r in diag_rows
                        ],
                    )

                    cur.execute(
                        """
                        SELECT "accessToken"
                        FROM "Integration"
                        WHERE type = 'GITHUB'
                          AND "organizationId" = %s
                          AND status = 'ACTIVE'
                          AND "accessToken" IS NOT NULL
                        ORDER BY "updatedAt" DESC
                        LIMIT 1
                        """,
                        (organization_id,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        logger.info("[GitHub] resolved workspace token from active GITHUB integration")
                        return row[0]
                    logger.info("[GitHub] no ACTIVE GITHUB integration with accessToken found for org")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[Executor] Failed to look up workspace GitHub token: {e}")
        return None

    async def _get_integration_config(
        self, integration_id: Optional[str], organization_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch warehouse connection config.

        Resolution order (mirrors tasks/[taskId]/run/route.ts):
        1. integration_id → PipelineNode with that FK
        2. node_id (from config.nodeId) → specific PipelineNode by ID
        3. organization_id → auto-discover first connected warehouse node

        Prefers Integration.credentials (where pipeline save stores them),
        falling back to PipelineNode.config (legacy nodes).
        """
        if not integration_id and not node_id and not organization_id:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    row = None

                    # 1. Try integration_id (FK to Integration → find its PipelineNode)
                    if integration_id:
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config,
                                   i.credentials AS int_credentials
                            FROM "PipelineNode" pn
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE pn."integrationId" = %s
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (integration_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            logger.info("[Executor] Resolved warehouse from integrationId")

                    # 2. Try node_id (config.nodeId — PipelineNode ID)
                    if not row and node_id:
                        tool_types = list(_WAREHOUSE_TOOL_TYPES)
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config,
                                   i.credentials AS int_credentials
                            FROM "PipelineNode" pn
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
                            WHERE pn.id = %s
                              AND pn."toolType" = ANY(%s)
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (node_id, tool_types),
                        )
                        row = cur.fetchone()
                        if row:
                            logger.info("[Executor] Resolved warehouse from config.nodeId")

                    # 3. Auto-discover: find first connected warehouse node in the org
                    if not row and organization_id:
                        tool_types = list(_WAREHOUSE_TOOL_TYPES)
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config,
                                   i.credentials AS int_credentials
                            FROM "PipelineNode" pn
                            JOIN "PipelineStack" ps ON pn."stackId" = ps.id
                            LEFT JOIN "Integration" i ON pn."integrationId" = i.id
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

                    found_node_id, node_name, tool_type, raw_config, int_credentials = row

                    # Prefer Integration.credentials over PipelineNode.config
                    # (mirrors pickConfig in run/route.ts)
                    config_source = int_credentials or raw_config or {}
                    if isinstance(config_source, str):
                        config_source = json.loads(config_source)

                    # Decrypt credentials (same as lib/crypto.ts)
                    credentials: Dict[str, Any] = {}
                    if isinstance(config_source, dict) and "encrypted" in config_source:
                        try:
                            decrypted = _decrypt(config_source["encrypted"])
                            credentials = json.loads(decrypted)
                        except Exception as e:
                            logger.warning(f"[Executor] Failed to decrypt config for {node_name}: {e}")
                            return None
                    elif isinstance(config_source, dict):
                        credentials = {k: v for k, v in config_source.items() if k != "_cached"}

                    cfg_result = {
                        "id": found_node_id,
                        "name": node_name,
                        "type": tool_type,
                        **credentials,
                    }

                    # Field mapping: username → user (same as copilot/chat/route.ts)
                    upper_type = tool_type.upper() if tool_type else ""
                    if upper_type in ("SNOWFLAKE", "POSTGRES", "REDSHIFT"):
                        if "username" in cfg_result and "user" not in cfg_result:
                            cfg_result["user"] = cfg_result.pop("username")

                    logger.info(
                        "[Executor] Resolved warehouse config",
                        node=node_name,
                        type=tool_type,
                        source="integration_credentials" if int_credentials else "pipeline_node_config",
                    )
                    return cfg_result
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[Executor] Failed to fetch integration config: {e}")
            return None
