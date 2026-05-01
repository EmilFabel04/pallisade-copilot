"""
Monitor executor.

Runs monitors against any connected warehouse adapter. Handles
dialect transpilation, execution, and result collection.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger()

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .freshness import FreshnessMonitor
from .volume import VolumeMonitor
from .schema import SchemaMonitor
from .anomaly import AnomalyMonitor
from .referential import ReferentialIntegrityMonitor
from .null_check import NullCheckMonitor
from .uniqueness_check import UniquenessCheckMonitor
from .range_validation import RangeValidationMonitor
from .accepted_values import AcceptedValuesMonitor
from .date_consistency import DateConsistencyMonitor
from .custom_sql import CustomSqlMonitor
from .explainer import enrich_result
from .infrastructure import INFRA_MONITOR_TYPES, INFRA_MONITOR_REGISTRY
from .bi import BI_MONITOR_TYPES, BI_MONITOR_REGISTRY


# Type alias for a warehouse query function.
# Signature: (sql: str) -> List[Dict[str, Any]]
QueryFunc = Callable[[str], List[Dict[str, Any]]]


MONITOR_REGISTRY: Dict[str, type] = {
    "freshness": FreshnessMonitor,
    "volume": VolumeMonitor,
    "schema_change": SchemaMonitor,
    "anomaly": AnomalyMonitor,
    "referential": ReferentialIntegrityMonitor,
    "null_check": NullCheckMonitor,
    "uniqueness_check": UniquenessCheckMonitor,
    "range_validation": RangeValidationMonitor,
    "accepted_values": AcceptedValuesMonitor,
    "date_consistency": DateConsistencyMonitor,
    "custom_sql": CustomSqlMonitor,
    # data_type_validation uses SchemaMonitor with mode="type_validation"
    "data_type_validation": SchemaMonitor,
}

# Maximum number of columns to scan in multi-column anomaly mode.
MAX_MULTI_COLUMNS = 50

# Legacy routing: old UI-only monitor types → new canonical types.
# Existing monitors saved in DB with these types continue to execute.
LEGACY_ROUTING: Dict[str, tuple] = {
    "null_rate": ("null_check", {}),
    "uniqueness": ("uniqueness_check", {}),
    "distribution": ("anomaly", {"metric": "avg", "column": "*"}),
    "outlier_detection": ("anomaly", {"column": "*"}),
}

# Kept for backward compat — callers that reference MONITOR_ROUTING
# directly still get routed correctly.
MONITOR_ROUTING: Dict[str, tuple] = LEGACY_ROUTING


class MonitorExecutor:
    """
    Executes monitors against a warehouse using a provided query function.

    The query function abstracts away the warehouse connection details,
    making this executor truly tech-agnostic. It can be backed by:
    - Direct Snowflake/BigQuery/Postgres connections
    - dbt warehouse adapters
    - MCP database servers
    - Any other SQL-capable connection
    """

    def __init__(
        self,
        query_func: Optional[QueryFunc] = None,
        dialect: str = "postgres",
    ):
        self.query_func = query_func
        self.dialect = dialect

    def run_monitor(
        self,
        monitor: Any,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
    ) -> MonitorResult:
        """Execute a single monitor and return its result.

        Two calling shapes are supported:

        1. Legacy / SQL warehouse path:
              ``run_monitor(monitor: BaseMonitor, database, schema, table)``
           — builds SQL via the monitor, executes via ``self.query_func``,
           and dispatches to ``monitor.evaluate``.

        2. Task-envelope path (used by the scheduler for non-SQL
           integrations such as CUSTOM_SOURCE):
              ``run_monitor(task: Dict[str, Any])``
           — when the first positional argument is a ``dict``, the
           ``integrationType`` key is inspected. ``CUSTOM_SOURCE`` tasks
           are routed to dedicated helpers that read from
           ``CustomSourceProbeRun`` rather than running SQL.
        """
        # CUSTOM_SOURCE integrations (and any future task-envelope-only
        # integration types) don't run SQL queries; they read from
        # dedicated helpers. Detect the task-envelope shape and dispatch
        # before any SQL machinery touches the monitor.
        if isinstance(monitor, dict):
            task = monitor
            integration_type = (task.get("integrationType") or "").upper()
            if integration_type == "CUSTOM_SOURCE":
                return self._run_custom_source_monitor(task)
            return self._build_error_result(
                task,
                f"run_monitor task envelope received for unsupported "
                f"integrationType {integration_type!r}",
            )

        # Legacy SQL warehouse path: monitor is a BaseMonitor instance.
        target_fqn = f"{database}.{schema}.{table}"
        start = time.monotonic()

        try:
            sql = monitor.build_query(database, schema, table, self.dialect)
            results = self.query_func(sql)
            result = monitor.evaluate(results, target_fqn)
            result.sql_executed = sql

            # Adaptive lookback for anomaly monitors: if not enough data
            # points with the default window, retry with shorter windows
            # and finally with no date filter (all available data).
            if (
                isinstance(monitor, AnomalyMonitor)
                and result.details
                and result.details.get("anomaly_ready") is False
                and monitor.timestamp_column
            ):
                adaptive = self._retry_anomaly_adaptive(
                    monitor, database, schema, table, target_fqn,
                )
                if adaptive is not None:
                    result = adaptive
        except Exception as exc:
            result = MonitorResult(
                monitor_type=monitor.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message=f"Monitor execution failed: {exc}",
            )

        result.executed_at = datetime.now(timezone.utc)
        result.duration_ms = int((time.monotonic() - start) * 1000)

        # Enrich with structured explanation
        try:
            enrich_result(result)
        except Exception:
            pass  # Explanation enrichment is best-effort

        return result

    # ------------------------------------------------------------------
    # CUSTOM_SOURCE dispatch
    # ------------------------------------------------------------------

    # Map the helper-dict status strings ("OK"/"ALERT"/"ERROR") onto
    # MonitorStatus enum values.
    _CUSTOM_SOURCE_STATUS_MAP: Dict[str, MonitorStatus] = {
        "OK": MonitorStatus.PASS,
        "PASS": MonitorStatus.PASS,
        "ALERT": MonitorStatus.FAIL,
        "FAIL": MonitorStatus.FAIL,
        "WARN": MonitorStatus.WARN,
        "ERROR": MonitorStatus.ERROR,
        "SKIPPED": MonitorStatus.SKIPPED,
    }

    def _run_custom_source_monitor(
        self, task: Dict[str, Any]
    ) -> MonitorResult:
        """Route to the CUSTOM_SOURCE-specific helper for the requested
        monitor type and package its dict result as a ``MonitorResult``."""
        from scanner.monitors.freshness import _run_freshness_for_custom_source
        from scanner.monitors.volume import _run_volume_for_custom_source
        from scanner.monitors.null_check import _run_null_check_for_custom_source
        from scanner.monitors.schema import _run_schema_for_custom_source

        monitor_type = (task.get("monitorType") or "").lower()
        helpers = {
            "freshness": _run_freshness_for_custom_source,
            "volume": _run_volume_for_custom_source,
            "null_check": _run_null_check_for_custom_source,
            "schema_change": _run_schema_for_custom_source,
            "schema": _run_schema_for_custom_source,
        }
        helper = helpers.get(monitor_type)
        if helper is None:
            return self._build_error_result(
                task,
                f"CUSTOM_SOURCE does not support monitor type {monitor_type!r}",
            )

        start = time.monotonic()
        try:
            result_dict = helper(task)
        except Exception as exc:
            result = self._build_error_result(
                task, f"CUSTOM_SOURCE monitor execution failed: {exc}"
            )
            result.duration_ms = int((time.monotonic() - start) * 1000)
            return result

        result = self._build_result_from_dict(task, result_dict)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    def _build_result_from_dict(
        self, task: Dict[str, Any], result_dict: Dict[str, Any]
    ) -> MonitorResult:
        """Convert a helper's status dict into a populated MonitorResult."""
        raw_status = str(result_dict.get("status") or "ERROR").upper()
        status = self._CUSTOM_SOURCE_STATUS_MAP.get(
            raw_status, MonitorStatus.ERROR
        )

        target_fqn = (
            task.get("targetFqn")
            or task.get("target_fqn")
            or f"custom_source:{task.get('integrationId', 'unknown')}"
            f":{(task.get('config') or {}).get('dataset_id', 'unknown')}"
        )

        value = result_dict.get("value")
        threshold = result_dict.get("threshold")

        return MonitorResult(
            monitor_type=(task.get("monitorType") or "custom_source").lower(),
            target_fqn=target_fqn,
            status=status,
            value=float(value) if isinstance(value, (int, float)) else None,
            threshold=(
                float(threshold)
                if isinstance(threshold, (int, float))
                else None
            ),
            message=str(result_dict.get("message") or ""),
            details=dict(result_dict.get("details") or {}),
            executed_at=datetime.now(timezone.utc),
        )

    def _build_error_result(
        self, task: Dict[str, Any], message: str
    ) -> MonitorResult:
        """Construct an ERROR-status MonitorResult for a task envelope."""
        target_fqn = (
            task.get("targetFqn")
            or task.get("target_fqn")
            or f"custom_source:{task.get('integrationId', 'unknown')}"
            f":{(task.get('config') or {}).get('dataset_id', 'unknown')}"
        )
        return MonitorResult(
            monitor_type=(task.get("monitorType") or "custom_source").lower(),
            target_fqn=target_fqn,
            status=MonitorStatus.ERROR,
            message=message,
            executed_at=datetime.now(timezone.utc),
        )

    def _retry_anomaly_adaptive(
        self,
        monitor: AnomalyMonitor,
        database: str,
        schema: str,
        table: str,
        target_fqn: str,
    ) -> Optional[MonitorResult]:
        """Retry anomaly monitor with adaptive lookback windows.

        Tries progressively shorter windows, then falls back to all
        available data (lookback_days=0).  Returns *None* if no retry
        produced enough data points for Z-score analysis.
        """
        original_lookback = monitor.lookback_days
        # Try shorter windows (30 → 25 → 20 → 14 → 7).
        # Never fall back to 0 (unbounded) to avoid scanning entire tables.
        fallback_lookbacks = [25, 20, 14, 7]

        for lookback in fallback_lookbacks:
            if lookback >= original_lookback:
                continue

            monitor.lookback_days = lookback
            try:
                sql = monitor.build_query(
                    database, schema, table, self.dialect,
                )
                results = self.query_func(sql)
                result = monitor.evaluate(results, target_fqn)
                result.sql_executed = sql

                # Check if we now have enough data for Z-score
                if result.details and result.details.get(
                    "anomaly_ready", True
                ):
                    # Success — annotate with lookback metadata
                    result.details["original_lookback_days"] = original_lookback
                    result.details["actual_lookback_days"] = (
                        lookback if lookback > 0 else "all_available"
                    )
                    monitor.lookback_days = original_lookback
                    return result
            except Exception:
                continue

        # Restore original value; caller will use the initial result.
        monitor.lookback_days = original_lookback
        return None

    def auto_configure(
        self,
        monitor_type: str,
        database: str,
        schema: str,
        table: str,
        existing_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fill in missing config keys by querying the warehouse.

        Non-destructive — never overwrites user-provided values.
        Returns the merged config with auto-detected defaults.
        """
        config = dict(existing_config)
        resolved_type = monitor_type.lower()

        # Apply routing first
        routing = MONITOR_ROUTING.get(resolved_type)
        if routing:
            resolved_type = routing[0]

        try:
            if resolved_type == "freshness" and not config.get("max_hours"):
                config = self._auto_config_freshness(
                    database, schema, table, config
                )
            elif resolved_type == "null_check":
                raw_cols = config.get("columns", config.get("column", "*"))
                if raw_cols == "*" or raw_cols == ["*"]:
                    config = self._auto_resolve_null_columns(
                        database, schema, table, config
                    )
            elif resolved_type == "volume":
                # Always discover timestamp column so daily bucketing works,
                # even when user has set min_rows/max_rows thresholds.
                if not config.get("time_bucket_column"):
                    config = self._auto_discover_volume_timestamp(
                        database, schema, table, config
                    )
                # Only auto-compute baselines if user hasn't set thresholds
                if not config.get("min_rows") and not config.get("max_rows") and not config.get("historical_mean"):
                    config = self._auto_config_volume(
                        database, schema, table, config
                    )
        except Exception as e:
            logger.warning(
                "[AutoConfig] Failed, using defaults",
                monitor_type=monitor_type,
                error=str(e),
            )

        return config

    def _auto_config_freshness(
        self,
        database: str,
        schema: str,
        table: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Auto-detect max_hours from historical update gaps."""
        from .freshness import discover_timestamp_column

        # Discover timestamp column if not set
        ts_col = config.get("timestamp_column")
        if not ts_col:
            ts_col = discover_timestamp_column(
                self.query_func, database, schema, table, self.dialect
            )
            if ts_col:
                config["timestamp_column"] = ts_col

        if not ts_col:
            return config

        # Query daily max timestamps to compute gap distribution
        fqn = f"`{database}.{schema}.{table}`" if self.dialect == "bigquery" else f"{database}.{schema}.{table}"

        if self.dialect == "bigquery":
            sql = (
                f"SELECT CAST(CAST({ts_col} AS TIMESTAMP) AS DATE) AS day, "
                f"MAX(CAST({ts_col} AS TIMESTAMP)) AS last_ts "
                f"FROM {fqn} "
                f"WHERE CAST(CAST({ts_col} AS TIMESTAMP) AS DATE) >= "
                f"DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) "
                f"GROUP BY day ORDER BY day"
            )
        else:
            sql = (
                f"SELECT CAST({ts_col} AS DATE) AS day, "
                f"MAX({ts_col}) AS last_ts "
                f"FROM {fqn} "
                f"WHERE {ts_col} >= CURRENT_DATE - INTERVAL '30 days' "
                f"GROUP BY CAST({ts_col} AS DATE) ORDER BY day"
            )

        rows = self.query_func(sql)
        if len(rows) < 2:
            return config

        # Compute gaps between consecutive days' last timestamps (in hours)
        gaps_hours: List[float] = []
        for i in range(1, len(rows)):
            prev_ts = rows[i - 1].get("last_ts")
            curr_ts = rows[i].get("last_ts")
            if prev_ts and curr_ts:
                try:
                    from datetime import datetime as dt
                    # Handle various timestamp formats
                    if hasattr(curr_ts, 'timestamp'):
                        gap = (curr_ts.timestamp() - prev_ts.timestamp()) / 3600
                    else:
                        t1 = dt.fromisoformat(str(prev_ts).replace("Z", "+00:00"))
                        t2 = dt.fromisoformat(str(curr_ts).replace("Z", "+00:00"))
                        gap = (t2 - t1).total_seconds() / 3600
                    if gap > 0:
                        gaps_hours.append(gap)
                except (ValueError, TypeError):
                    continue

        if not gaps_hours:
            return config

        # P95 gap × 1.5 = max_hours threshold
        gaps_hours.sort()
        p95_idx = int(len(gaps_hours) * 0.95)
        p95_gap = gaps_hours[min(p95_idx, len(gaps_hours) - 1)]
        max_hours = math.ceil(p95_gap * 1.5)
        # Clamp to reasonable range: at least 1h, at most 168h (1 week)
        max_hours = max(1, min(max_hours, 168))

        config["max_hours"] = max_hours
        config["_auto_configured"] = True

        # Store raw gaps for cadence-aware mode (enables learning from history)
        if len(gaps_hours) >= 5:
            config["cadence_aware"] = True
            config["cadence_gaps"] = [round(g, 2) for g in gaps_hours]

        logger.info(
            "[AutoConfig] Freshness auto-configured",
            max_hours=max_hours,
            p95_gap=round(p95_gap, 1),
            data_points=len(gaps_hours),
            cadence_aware=config.get("cadence_aware", False),
        )
        return config

    def _auto_discover_volume_timestamp(
        self,
        database: str,
        schema: str,
        table: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Discover a timestamp column for daily volume bucketing."""
        from .freshness import discover_timestamp_column

        ts_col = discover_timestamp_column(
            self.query_func, database, schema, table, self.dialect
        )
        if ts_col:
            config["time_bucket_column"] = ts_col
            logger.info(
                "[AutoConfig] Volume timestamp column discovered",
                column=ts_col,
            )
        return config

    def _auto_config_volume(
        self,
        database: str,
        schema: str,
        table: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Auto-compute min/max row thresholds from 30-day history."""
        from .freshness import discover_timestamp_column

        # Need a timestamp column to bucket by day
        ts_col = discover_timestamp_column(
            self.query_func, database, schema, table, self.dialect
        )

        if not ts_col:
            # No timestamp → just get current count, can't compute range
            return config

        fqn = f"`{database}.{schema}.{table}`" if self.dialect == "bigquery" else f"{database}.{schema}.{table}"

        if self.dialect == "bigquery":
            sql = (
                f"SELECT CAST(CAST({ts_col} AS TIMESTAMP) AS DATE) AS day, "
                f"COUNT(*) AS row_count "
                f"FROM {fqn} "
                f"WHERE CAST(CAST({ts_col} AS TIMESTAMP) AS DATE) >= "
                f"DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) "
                f"GROUP BY day ORDER BY day"
            )
        else:
            sql = (
                f"SELECT CAST({ts_col} AS DATE) AS day, "
                f"COUNT(*) AS row_count "
                f"FROM {fqn} "
                f"WHERE {ts_col} >= CURRENT_DATE - INTERVAL '30 days' "
                f"GROUP BY CAST({ts_col} AS DATE) ORDER BY day"
            )

        rows = self.query_func(sql)
        if len(rows) < 3:
            return config

        counts = [int(r.get("row_count", 0)) for r in rows]
        mean = sum(counts) / len(counts)
        variance = sum((x - mean) ** 2 for x in counts) / len(counts)
        stddev = math.sqrt(variance) if variance > 0 else 0

        # Prefer z-score baseline over min/max thresholds.
        config["historical_mean"] = mean
        config["historical_stddev"] = stddev
        config["time_bucket_column"] = ts_col
        config["_auto_configured"] = True

        # Only set min/max as fallback if stddev is zero (constant volume)
        if stddev == 0:
            config["min_rows"] = max(0, int(mean * 0.5))
            config["max_rows"] = int(mean * 2)

        # Table-type auto-detection: detect full-refresh vs append-only
        # by comparing recent rows to total rows
        if not config.get("volume_mode") or config.get("volume_mode") == "auto":
            try:
                total_sql = (
                    f"SELECT COUNT(*) AS total FROM {fqn}"
                )
                total_rows_result = self.query_func(total_sql)
                total_rows = int(total_rows_result[0].get("total", 0)) if total_rows_result else 0

                if total_rows > 0:
                    recent_rows = sum(counts)
                    ratio = recent_rows / total_rows

                    if ratio > 0.8:
                        detected_mode = "total"
                        reason = f"{ratio:.0%} of rows in last 30 days — likely full-refresh table"
                        confidence = "high" if ratio > 0.95 else "medium"
                    else:
                        detected_mode = "period"
                        reason = f"{ratio:.0%} of rows in last 30 days — likely append-only table"
                        confidence = "high" if ratio < 0.3 else "medium"

                    config["_detected_volume_mode"] = detected_mode
                    config["_detection_reason"] = reason
                    config["_detection_confidence"] = confidence
                    config["volume_mode"] = detected_mode
            except Exception:
                pass  # Skip auto-detection on failure

        logger.info(
            "[AutoConfig] Volume auto-configured (baseline mode)",
            mean=round(mean, 0),
            stddev=round(stddev, 0),
            data_points=len(counts),
            has_min_max=stddev == 0,
            detected_mode=config.get("_detected_volume_mode"),
        )
        return config

    def _auto_resolve_null_columns(
        self,
        database: str,
        schema: str,
        table: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve wildcard '*' columns for null_check by querying INFORMATION_SCHEMA."""
        if self.dialect == "bigquery":
            fqn = f"`{database}.{schema}.INFORMATION_SCHEMA.COLUMNS`"
            sql = (
                f"SELECT column_name FROM {fqn} "
                f"WHERE table_name = '{table}' "
                f"ORDER BY ordinal_position"
            )
        else:
            # Postgres / Redshift / Snowflake all support information_schema.columns
            sql = (
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
                f"ORDER BY ordinal_position"
            )

        rows = self.query_func(sql)
        if rows:
            columns = [r["column_name"] for r in rows if r.get("column_name")]
            if columns:
                config["columns"] = columns
                config["_auto_configured"] = True
                logger.info(
                    "[AutoConfig] Null check columns resolved",
                    table=f"{database}.{schema}.{table}",
                    column_count=len(columns),
                )

        return config

    def run_all(
        self,
        monitors: List[BaseMonitor],
        database: str,
        schema: str,
        table: str,
    ) -> List[MonitorResult]:
        """Execute multiple monitors against the same table."""
        return [
            self.run_monitor(m, database, schema, table)
            for m in monitors
        ]

    def run_suite(
        self,
        tables: List[Dict[str, str]],
        monitor_configs: List[Dict[str, Any]],
    ) -> Dict[str, List[MonitorResult]]:
        """
        Run a suite of monitors across multiple tables.

        Parameters
        ----------
        tables : list of dict
            Each dict must have "database", "schema", "table" keys.
        monitor_configs : list of dict
            Each dict must have "type" key and optional "config" dict.

        Returns
        -------
        dict
            Mapping of table FQN to list of MonitorResults.
        """
        monitors = []
        for mc in monitor_configs:
            monitor_cls = MONITOR_REGISTRY.get(mc["type"])
            if monitor_cls:
                monitors.append(monitor_cls(mc.get("config", {})))

        results: Dict[str, List[MonitorResult]] = {}
        for t in tables:
            fqn = f"{t['database']}.{t['schema']}.{t['table']}"
            results[fqn] = self.run_all(
                monitors, t["database"], t["schema"], t["table"]
            )

        return results

    @staticmethod
    def execute_infrastructure_monitor(
        monitor_type: str,
        config: Dict[str, Any],
        server_adapter: Any,
    ) -> MonitorResult:
        """Execute a non-SQL infrastructure monitor using a ServerAdapter.

        Returns a MonitorResult from the infrastructure monitor.
        """
        key = monitor_type.lower()
        if key not in INFRA_MONITOR_TYPES:
            return MonitorResult(
                monitor_type=key,
                target_fqn="unknown",
                status=MonitorStatus.ERROR,
                message=f"Unknown infrastructure monitor type: {monitor_type}",
            )

        monitor_cls = INFRA_MONITOR_REGISTRY[key]
        monitor = monitor_cls(config)

        start = time.monotonic()
        try:
            result = monitor.execute(server_adapter)
        except Exception as exc:
            result = MonitorResult(
                monitor_type=key,
                target_fqn=server_adapter._config.get("host", "unknown"),
                status=MonitorStatus.ERROR,
                message=f"Infrastructure monitor failed: {exc}",
            )

        result.executed_at = datetime.now(timezone.utc)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    @staticmethod
    def execute_bi_monitor(
        monitor_type: str,
        config: Dict[str, Any],
        bi_client: Any,
        engine_store: Any = None,
        monitor_history_func: Any = None,
    ) -> MonitorResult:
        """Execute a BI/reporting monitor using a BI platform adapter.

        Returns a MonitorResult from the BI monitor.
        """
        key = monitor_type.lower()
        if key not in BI_MONITOR_TYPES:
            return MonitorResult(
                monitor_type=key,
                target_fqn="unknown",
                status=MonitorStatus.ERROR,
                message=f"Unknown BI monitor type: {monitor_type}",
            )

        monitor_cls = BI_MONITOR_REGISTRY[key]
        monitor = monitor_cls(config)

        start = time.monotonic()
        try:
            # Different monitors accept different kwargs
            if key == "bi_upstream_break_risk":
                result = monitor.execute(
                    bi_client=bi_client,
                    engine_store=engine_store,
                    monitor_history_func=monitor_history_func,
                )
            elif key == "bi_freshness_proxy":
                result = monitor.execute(
                    bi_client=bi_client,
                    engine_store=engine_store,
                )
            else:
                result = monitor.execute(bi_client)
        except Exception as exc:
            result = MonitorResult(
                monitor_type=key,
                target_fqn=f"bi:{config.get('asset_id', 'unknown')}",
                status=MonitorStatus.ERROR,
                message=f"BI monitor failed: {exc}",
            )

        result.executed_at = datetime.now(timezone.utc)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    @staticmethod
    def resolve_monitor_type(
        monitor_type: str, config: Dict[str, Any] | None = None
    ) -> tuple:
        """Resolve a monitor type, applying routing for legacy UI types.

        Returns (resolved_type, merged_config).
        """
        config = dict(config) if config else {}
        key = monitor_type.lower()

        # Legacy routing: old type names → new canonical types
        routing = LEGACY_ROUTING.get(key)
        if routing:
            backend_type, default_config = routing
            merged = {**default_config, **config}
            logger.debug(
                "[MonitorRouting] Legacy type routed",
                original=key,
                resolved=backend_type,
            )
            return backend_type, merged

        # data_type_validation is SchemaMonitor with mode override
        if key == "data_type_validation":
            config.setdefault("mode", "type_validation")
            return "data_type_validation", config

        return key, config

    @staticmethod
    def create_monitor(
        monitor_type: str, config: Dict[str, Any] | None = None
    ) -> Optional[BaseMonitor]:
        """Factory method to create a monitor by type name.

        Handles routing for legacy UI types and the new canonical set.
        """
        resolved_type, merged_config = MonitorExecutor.resolve_monitor_type(
            monitor_type, config
        )
        cls = MONITOR_REGISTRY.get(resolved_type)
        if cls:
            return cls(merged_config)
        return None
