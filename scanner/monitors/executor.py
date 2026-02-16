"""
Monitor executor.

Runs monitors against any connected warehouse adapter. Handles
dialect transpilation, execution, and result collection.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .freshness import FreshnessMonitor
from .volume import VolumeMonitor
from .schema import SchemaMonitor
from .anomaly import AnomalyMonitor


# Type alias for a warehouse query function.
# Signature: (sql: str) -> List[Dict[str, Any]]
QueryFunc = Callable[[str], List[Dict[str, Any]]]


MONITOR_REGISTRY: Dict[str, type] = {
    "freshness": FreshnessMonitor,
    "volume": VolumeMonitor,
    "schema_change": SchemaMonitor,
    "anomaly": AnomalyMonitor,
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
    def create_monitor(
        monitor_type: str, config: Dict[str, Any] | None = None
    ) -> Optional[BaseMonitor]:
        """Factory method to create a monitor by type name."""
        cls = MONITOR_REGISTRY.get(monitor_type)
        if cls:
            return cls(config)
        return None
