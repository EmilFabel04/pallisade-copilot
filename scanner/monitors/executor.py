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
from .infrastructure import INFRA_MONITOR_TYPES, INFRA_MONITOR_REGISTRY


# Type alias for a warehouse query function.
# Signature: (sql: str) -> List[Dict[str, Any]]
QueryFunc = Callable[[str], List[Dict[str, Any]]]


MONITOR_REGISTRY: Dict[str, type] = {
    "freshness": FreshnessMonitor,
    "volume": VolumeMonitor,
    "schema_change": SchemaMonitor,
    "anomaly": AnomalyMonitor,
}

# Map UI-only monitor types to real backend implementations.
# Each entry is (backend_type, default_config_overrides).
MONITOR_ROUTING: Dict[str, tuple] = {
    "null_rate": ("anomaly", {"metric": "null_rate", "column": "*"}),
    "uniqueness": ("anomaly", {"metric": "distinct_rate", "column": "*"}),
    "distribution": ("anomaly", {"metric": "avg", "column": "*"}),
}


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
        query_func: QueryFunc,
        dialect: str = "postgres",
    ):
        self.query_func = query_func
        self.dialect = dialect

    def run_monitor(
        self,
        monitor: BaseMonitor,
        database: str,
        schema: str,
        table: str,
    ) -> MonitorResult:
        """Execute a single monitor and return its result."""
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
        return result

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
        # Try shorter windows per user request (30 → 25 → 20),
        # then all available data (0 = no date filter).
        fallback_lookbacks = [25, 20, 0]

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
            elif resolved_type == "volume" and not config.get("min_rows") and not config.get("max_rows"):
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
        logger.info(
            "[AutoConfig] Freshness auto-configured",
            max_hours=max_hours,
            p95_gap=round(p95_gap, 1),
            data_points=len(gaps_hours),
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

        # min = mean - 3σ (floored at 0), max = mean + 3σ
        min_rows = max(0, int(mean - 3 * stddev))
        max_rows = int(mean + 3 * stddev)

        config["min_rows"] = min_rows
        config["max_rows"] = max_rows
        config["time_bucket_column"] = ts_col
        config["_auto_configured"] = True
        logger.info(
            "[AutoConfig] Volume auto-configured",
            min_rows=min_rows,
            max_rows=max_rows,
            mean=round(mean, 0),
            stddev=round(stddev, 0),
            data_points=len(counts),
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
    def resolve_monitor_type(
        monitor_type: str, config: Dict[str, Any] | None = None
    ) -> tuple:
        """Resolve a monitor type, applying routing for UI-only types.

        Returns (resolved_type, merged_config).
        """
        config = dict(config) if config else {}
        key = monitor_type.lower()

        routing = MONITOR_ROUTING.get(key)
        if routing:
            backend_type, default_config = routing
            # Merge: default_config provides fallbacks, user config wins
            merged = {**default_config, **config}
            return backend_type, merged

        return key, config

    @staticmethod
    def create_monitor(
        monitor_type: str, config: Dict[str, Any] | None = None
    ) -> Optional[BaseMonitor]:
        """Factory method to create a monitor by type name.

        Handles routing for UI-only types (null_rate, uniqueness, distribution).
        """
        resolved_type, merged_config = MonitorExecutor.resolve_monitor_type(
            monitor_type, config
        )
        cls = MONITOR_REGISTRY.get(resolved_type)
        if cls:
            return cls(merged_config)
        return None
