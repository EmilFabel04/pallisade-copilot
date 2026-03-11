"""
Referential integrity monitor.

Checks that foreign key values in a child table actually exist
in the parent table. Supports sampling for large tables.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class ReferentialIntegrityMonitor(BaseMonitor):
    """
    Monitors referential integrity between two tables.

    Detects orphaned records — rows in the child table whose foreign key
    value does not exist in the parent table.

    Config keys:
        parent_fqn : str
            Fully qualified name of the parent table (database.schema.table).
        parent_column : str
            Primary key column in the parent table.
        child_column : str
            Foreign key column in the child table.
        sample_pct : float | None
            Percentage of rows to sample (0-100). None = full scan.
            Useful for very large tables.
        max_orphans : int
            Maximum allowed orphan count before FAIL (default: 0).
        warn_orphans : int
            Orphan count threshold for WARN (default: 0, same as max).
    """

    monitor_type = "referential"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.parent_fqn: str = self.config.get("parent_fqn", "")
        self.parent_column: str = self.config.get("parent_column", "")
        self.child_column: str = self.config.get("child_column", "")
        self.sample_pct: Optional[float] = self.config.get("sample_pct")
        self.max_orphans: int = int(self.config.get("max_orphans", 0))
        self.warn_orphans: int = int(self.config.get("warn_orphans", self.max_orphans))

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if not self.parent_fqn or not self.parent_column or not self.child_column:
            raise ValueError(
                "ReferentialIntegrityMonitor requires 'parent_fqn', "
                "'parent_column', and 'child_column' in config."
            )

        child_fqn = self._fqn(database, schema, table)

        # Build the orphan detection query
        sample_clause = ""
        if self.sample_pct and 0 < self.sample_pct < 100:
            if dialect == "bigquery":
                # BigQuery uses TABLESAMPLE SYSTEM with percentage
                sample_clause = f"TABLESAMPLE SYSTEM ({self.sample_pct} PERCENT)"
            elif dialect == "snowflake":
                sample_clause = f"SAMPLE ({self.sample_pct})"
            else:
                # Postgres/Redshift: TABLESAMPLE BERNOULLI
                sample_clause = f"TABLESAMPLE BERNOULLI ({self.sample_pct})"

        # Count orphans + get a sample of orphaned values
        if dialect == "bigquery":
            sql = (
                f"SELECT "
                f"COUNT(*) AS orphan_count, "
                f"COUNT(DISTINCT c.{self.child_column}) AS orphan_distinct, "
                f"COUNT(*) OVER () AS child_total "
                f"FROM {child_fqn} {sample_clause} c "
                f"LEFT JOIN {self.parent_fqn} p "
                f"ON c.{self.child_column} = p.{self.parent_column} "
                f"WHERE p.{self.parent_column} IS NULL "
                f"AND c.{self.child_column} IS NOT NULL"
            )
        else:
            sql = (
                f"WITH orphans AS ("
                f"SELECT c.{self.child_column} AS orphan_value "
                f"FROM {child_fqn} {sample_clause} c "
                f"LEFT JOIN {self.parent_fqn} p "
                f"ON c.{self.child_column} = p.{self.parent_column} "
                f"WHERE p.{self.parent_column} IS NULL "
                f"AND c.{self.child_column} IS NOT NULL"
                f") "
                f"SELECT "
                f"COUNT(*) AS orphan_count, "
                f"COUNT(DISTINCT orphan_value) AS orphan_distinct "
                f"FROM orphans"
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
                message="No results returned from referential integrity query.",
            )

        row = query_results[0]
        orphan_count = int(row.get("orphan_count", 0))
        orphan_distinct = int(row.get("orphan_distinct", 0))

        details: Dict[str, Any] = {
            "orphan_count": orphan_count,
            "orphan_distinct_values": orphan_distinct,
            "parent_fqn": self.parent_fqn,
            "parent_column": self.parent_column,
            "child_column": self.child_column,
            "sampled": self.sample_pct is not None,
            "sample_pct": self.sample_pct,
        }

        if orphan_count == 0:
            details["explanation"] = (
                f"All {self.child_column} values in {target_fqn} "
                f"have matching {self.parent_column} values in {self.parent_fqn}."
            )
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message=(
                    f"Referential integrity intact: all {self.child_column} "
                    f"values exist in {self.parent_fqn}.{self.parent_column}."
                ),
                details=details,
            )

        sample_note = ""
        if self.sample_pct:
            sample_note = f" (based on {self.sample_pct}% sample)"

        details["explanation"] = (
            f"{orphan_count:,} rows in {target_fqn}.{self.child_column} "
            f"reference {orphan_distinct:,} distinct values that don't exist "
            f"in {self.parent_fqn}.{self.parent_column}{sample_note}."
        )

        if orphan_count > self.max_orphans:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=float(orphan_count),
                threshold=float(self.max_orphans),
                message=(
                    f"{orphan_count:,} orphaned records found — "
                    f"{self.child_column} references {orphan_distinct:,} "
                    f"non-existent {self.parent_column} values in "
                    f"{self.parent_fqn}{sample_note}."
                ),
                details=details,
            )

        if orphan_count > self.warn_orphans:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.WARN,
                value=float(orphan_count),
                threshold=float(self.warn_orphans),
                message=(
                    f"{orphan_count:,} orphaned records found "
                    f"(warn threshold: {self.warn_orphans}){sample_note}."
                ),
                details=details,
            )

        # Below warn threshold
        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=float(orphan_count),
            message=(
                f"{orphan_count:,} orphaned records found "
                f"(below threshold of {self.max_orphans}){sample_note}."
            ),
            details=details,
        )
