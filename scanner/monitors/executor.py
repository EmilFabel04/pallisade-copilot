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
