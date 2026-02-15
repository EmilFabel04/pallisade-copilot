"""
Freshness monitor.

Checks how recently a table was updated by examining a timestamp column
or warehouse metadata. Works across any SQL warehouse.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class FreshnessMonitor(BaseMonitor):
    """
    Monitors data freshness by measuring the time since the most recent
    row in a timestamp column.

    Config keys:
        timestamp_column : str
            Column to check for recency (default: inferred or "updated_at").
        max_hours : float
            Maximum acceptable age in hours (default: 24).
        warn_hours : float
            Warning threshold in hours (default: max_hours * 0.75).
    """

    monitor_type = "freshness"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.timestamp_column: str = self.config.get(
            "timestamp_column", "updated_at"
        )
        self.max_hours: float = float(self.config.get("max_hours", 24))
        self.warn_hours: float = float(
            self.config.get("warn_hours", self.max_hours * 0.75)
        )

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        fqn = self._fqn(database, schema, table)
        col = self.timestamp_column

        if dialect == "bigquery":
            # BigQuery has no EXTRACT(EPOCH FROM ...).
            # Use TIMESTAMP_DIFF instead.
            sql = (
                f"SELECT "
                f"MAX({col}) AS last_value, "
                f"TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), "
                f"CAST(MAX({col}) AS TIMESTAMP), SECOND) / 3600.0 "
                f"AS hours_since_update, "
                f"COUNT(*) AS total_rows "
                f"FROM {fqn} "
                f"WHERE {col} IS NOT NULL"
            )
            return sql

        # Generic SQL using EXTRACT(EPOCH ...) — transpiled per dialect.
        sql = (
            f"SELECT "
            f"MAX({col}) AS last_value, "
            f"EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX({col}))) / 3600.0 "
            f"AS hours_since_update, "
            f"COUNT(*) AS total_rows "
            f"FROM {fqn} "
            f"WHERE {col} IS NOT NULL"
        )
        return self.transpile_sql(sql, dialect)

    def evaluate(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        if not query_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message="No results returned from freshness query.",
            )

        row = query_results[0]
        hours = row.get("hours_since_update")

        if hours is None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message=(
                    f"Column '{self.timestamp_column}' has no non-null values."
                ),
            )

        hours = float(hours)

        if hours > self.max_hours:
            status = MonitorStatus.FAIL
            message = (
                f"Data is {hours:.1f}h old, exceeding the "
                f"{self.max_hours}h freshness SLA."
            )
        elif hours > self.warn_hours:
            status = MonitorStatus.WARN
            message = (
                f"Data is {hours:.1f}h old, approaching the "
                f"{self.max_hours}h freshness SLA."
            )
        else:
            status = MonitorStatus.PASS
            message = f"Data is {hours:.1f}h old. Within the {self.max_hours}h SLA."

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=hours,
            threshold=self.max_hours,
            expected_range={"min": 0, "max": self.max_hours},
            message=message,
            details={
                "timestamp_column": self.timestamp_column,
                "last_value": str(row.get("last_value", "")),
                "total_rows": row.get("total_rows"),
                "warn_hours": self.warn_hours,
            },
        )
