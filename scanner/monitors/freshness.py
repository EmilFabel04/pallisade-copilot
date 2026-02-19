"""
Freshness monitor.

Checks how recently a table was updated by examining a timestamp column
or warehouse metadata. Works across any SQL warehouse.
"""

from __future__ import annotations

import structlog
from typing import Any, Callable, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus

logger = structlog.get_logger()

# Priority order for auto-detecting the freshness column.
# Lower index = higher priority.  Matched case-insensitively.
_TIMESTAMP_COLUMN_PRIORITY = [
    "_partitiontime",       # BigQuery partition pseudo-column (load time)
    "loaded_at",
    "_loaded_at",
    "ingested_at",
    "_ingested_at",
    "_etl_loaded_at",
    "_fivetran_synced",     # Fivetran sync timestamp
    "_airbyte_extracted_at",  # Airbyte extraction timestamp
    "created_at",
    "created",
    "inserted_at",
    "updated_at",
    "modified_at",
    "timestamp",
    "event_time",
    "event_timestamp",
]


def _pick_best_column(columns: List[str]) -> Optional[str]:
    """Pick the best timestamp column from a list of available columns.

    Returns the highest-priority match, or the first column if none match
    the priority list.
    """
    if not columns:
        return None

    lower_map = {c.lower(): c for c in columns}

    for candidate in _TIMESTAMP_COLUMN_PRIORITY:
        if candidate in lower_map:
            return lower_map[candidate]

    # No priority match — return the first timestamp column found
    return columns[0]


def build_discovery_query(
    database: str,
    schema: str,
    table: str,
    dialect: str = "postgres",
) -> str:
    """Query INFORMATION_SCHEMA to find all timestamp/datetime columns."""
    if dialect == "bigquery":
        return (
            f"SELECT column_name, data_type "
            f"FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = '{table}' "
            f"AND data_type IN ('TIMESTAMP', 'DATETIME', 'DATE')"
        )

    # Postgres / Snowflake / Redshift
    return (
        f"SELECT column_name, data_type "
        f"FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' "
        f"AND table_name = '{table}' "
        f"AND data_type IN "
        f"('timestamp with time zone', 'timestamp without time zone', "
        f"'timestamptz', 'timestamp', 'date', 'datetime', "
        f"'TIMESTAMP_LTZ', 'TIMESTAMP_NTZ', 'TIMESTAMP_TZ')"
    )


def discover_timestamp_column(
    query_func: Callable,
    database: str,
    schema: str,
    table: str,
    dialect: str = "postgres",
) -> Optional[str]:
    """Run a discovery query and return the best timestamp column name."""
    sql = build_discovery_query(database, schema, table, dialect)
    try:
        rows = query_func(sql)
        column_names = [r.get("column_name") for r in rows if r.get("column_name")]
        best = _pick_best_column(column_names)
        if best:
            logger.info(
                "[Freshness] Auto-detected timestamp column",
                column=best,
                candidates=column_names,
                table=f"{database}.{schema}.{table}",
            )
        else:
            logger.warning(
                "[Freshness] No timestamp columns found",
                table=f"{database}.{schema}.{table}",
            )
        return best
    except Exception as e:
        logger.warning(f"[Freshness] Discovery query failed: {e}")
        return None


class FreshnessMonitor(BaseMonitor):
    """
    Monitors data freshness by measuring the time since the most recent
    row in a timestamp column.

    When no timestamp_column is configured, the caller should use
    discover_timestamp_column() to find the best column before running
    the monitor.

    Config keys:
        timestamp_column : str | None
            Column to check for recency.  When omitted, the executor
            auto-discovers the best timestamp column from the table schema.
        max_hours : float
            Maximum acceptable age in hours (default: 24).
        warn_hours : float
            Warning threshold in hours (default: max_hours * 0.75).
    """

    monitor_type = "freshness"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        # Empty string or None → needs auto-detection before build_query()
        self._user_specified_column: bool = bool(self.config.get("timestamp_column"))
        self.timestamp_column: str = (
            self.config.get("timestamp_column") or ""
        )
        self.max_hours: float = float(self.config.get("max_hours", 24))
        self.warn_hours: float = float(
            self.config.get("warn_hours", self.max_hours * 0.75)
        )

    @property
    def needs_column_discovery(self) -> bool:
        return not self.timestamp_column

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        fqn = self._fqn(database, schema, table)
        col = self.timestamp_column

        if not col:
            # Fallback if discovery wasn't run — use updated_at
            col = "updated_at"

        if dialect == "bigquery":
            return (
                f"SELECT "
                f"MAX({col}) AS last_value, "
                f"TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), "
                f"CAST(MAX({col}) AS TIMESTAMP), SECOND) / 3600.0 "
                f"AS hours_since_update, "
                f"COUNT(*) AS total_rows "
                f"FROM {fqn} "
                f"WHERE {col} IS NOT NULL"
            )

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
        total_rows = row.get("total_rows", 0)
        hours = row.get("hours_since_update")

        if hours is None:
            if not total_rows:
                # Empty table — nothing to check freshness against
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.SKIPPED,
                    message="Table is empty — no rows to check freshness against.",
                    details={
                        "timestamp_column": self.timestamp_column,
                        "total_rows": 0,
                    },
                )
            # Non-empty table but all NULLs in the timestamp column
            if self._user_specified_column:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.ERROR,
                    message=(
                        f"Column '{self.timestamp_column}' has no non-null values "
                        f"({total_rows} rows checked)."
                    ),
                    details={
                        "timestamp_column": self.timestamp_column,
                        "total_rows": total_rows,
                    },
                )
            else:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.SKIPPED,
                    message=(
                        f"Auto-detected column '{self.timestamp_column}' has no "
                        f"non-null values. Specify a timestamp_column manually."
                    ),
                    details={
                        "timestamp_column": self.timestamp_column,
                        "total_rows": total_rows,
                        "auto_detected": True,
                    },
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
