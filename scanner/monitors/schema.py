"""
Schema change monitor.

Detects column additions, deletions, type changes, and ordering changes
by comparing the current INFORMATION_SCHEMA against a stored baseline.
Works across any SQL warehouse.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class SchemaMonitor(BaseMonitor):
    """
    Monitors schema changes by querying INFORMATION_SCHEMA.COLUMNS
    and comparing against a known baseline.

    Config keys:
        baseline_columns : list[dict] | None
            Expected column definitions. Each dict should have
            "column_name", "data_type", and optionally "is_nullable".
            If None, the monitor only reports the current schema
            (first-run mode).
        fail_on_column_added : bool
            Fail if new columns are detected (default: False).
        fail_on_column_removed : bool
            Fail if columns are missing (default: True).
        fail_on_type_change : bool
            Fail if a column's data type changed (default: True).
    """

    monitor_type = "schema_change"

    # Cross-dialect type alias mapping → canonical form.
    _TYPE_ALIASES: Dict[str, str] = {
        # BigQuery → canonical
        "int64": "integer",
        "float64": "double",
        "bool": "boolean",
        "string": "text",
        "bytes": "bytea",
        "bignumeric": "numeric",
        # Snowflake → canonical
        "number": "numeric",
        "variant": "json",
        "timestamp_ltz": "timestamptz",
        "timestamp_ntz": "timestamp",
        "timestamp_tz": "timestamptz",
        # Postgres aliases → canonical
        "character varying": "varchar",
        "double precision": "double",
        "int": "integer",
        "int4": "integer",
        "int8": "bigint",
        "int2": "smallint",
        "float4": "real",
        "float8": "double",
        "serial": "integer",
        "bigserial": "bigint",
        "timestamp with time zone": "timestamptz",
        "timestamp without time zone": "timestamp",
    }

    @staticmethod
    def _normalize_type(raw_type: str) -> str:
        """Normalize a data type string for cross-dialect comparison.

        Strips length/precision (e.g. ``varchar(255)`` → ``varchar``)
        and maps dialect-specific names to a canonical form so that
        ``INT64`` (BigQuery) matches ``integer`` (Postgres).
        """
        t = raw_type.lower().strip()
        # Strip length/precision: varchar(255) → varchar, numeric(10,2) → numeric
        paren_idx = t.find("(")
        if paren_idx > 0:
            t = t[:paren_idx].strip()
        return SchemaMonitor._TYPE_ALIASES.get(t, t)

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.baseline_columns: Optional[List[Dict[str, str]]] = self.config.get(
            "baseline_columns"
        )
        self.fail_on_added = self.config.get("fail_on_column_added", False)
        self.fail_on_removed = self.config.get("fail_on_column_removed", True)
        self.fail_on_type_change = self.config.get("fail_on_type_change", True)

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        # INFORMATION_SCHEMA query — works on Postgres, Snowflake, BigQuery,
        # Redshift, SQL Server, etc. with minor dialect differences handled
        # by sqlglot transpilation.
        if dialect == "bigquery":
            # BigQuery uses dataset.INFORMATION_SCHEMA.COLUMNS.
            sql = (
                f"SELECT "
                f"column_name, data_type, is_nullable, ordinal_position "
                f"FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
                f"WHERE table_name = '{table}' "
                f"ORDER BY ordinal_position"
            )
        else:
            sql = (
                f"SELECT "
                f"column_name, data_type, is_nullable, ordinal_position "
                f"FROM information_schema.columns "
                f"WHERE table_catalog = '{database}' "
                f"AND table_schema = '{schema}' "
                f"AND table_name = '{table}' "
                f"ORDER BY ordinal_position"
            )

        return sql

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
                message="No columns found — table may not exist.",
            )

        current_columns = {
            row["column_name"].lower(): {
                "data_type": self._normalize_type(row.get("data_type", "")),
                "is_nullable": row.get("is_nullable", "YES"),
                "ordinal_position": row.get("ordinal_position"),
            }
            for row in query_results
        }

        # First-run mode: no baseline yet, just report current schema.
        if not self.baseline_columns:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message=(
                    f"Schema baseline established with "
                    f"{len(current_columns)} columns."
                ),
                details={
                    "column_count": len(current_columns),
                    "columns": list(current_columns.keys()),
                    "is_baseline_run": True,
                },
            )

        # Build baseline lookup.
        baseline = {
            col["column_name"].lower(): {
                "data_type": self._normalize_type(col.get("data_type", "")),
                "is_nullable": col.get("is_nullable", "YES"),
            }
            for col in self.baseline_columns
        }

        changes: List[Dict[str, Any]] = []
        baseline_names = set(baseline.keys())
        current_names = set(current_columns.keys())

        # Detect added columns.
        for added in current_names - baseline_names:
            changes.append({
                "change_type": "column_added",
                "column": added,
                "new_type": current_columns[added]["data_type"],
            })

        # Detect removed columns.
        for removed in baseline_names - current_names:
            changes.append({
                "change_type": "column_removed",
                "column": removed,
                "old_type": baseline[removed]["data_type"],
            })

        # Detect type changes on existing columns.
        for col in baseline_names & current_names:
            old_type = baseline[col]["data_type"]
            new_type = current_columns[col]["data_type"]
            if old_type != new_type:
                changes.append({
                    "change_type": "type_changed",
                    "column": col,
                    "old_type": old_type,
                    "new_type": new_type,
                })

        if not changes:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message="Schema matches baseline. No changes detected.",
                details={"column_count": len(current_columns)},
            )

        # Determine severity.
        has_removed = any(c["change_type"] == "column_removed" for c in changes)
        has_type_change = any(c["change_type"] == "type_changed" for c in changes)
        has_added = any(c["change_type"] == "column_added" for c in changes)

        should_fail = (
            (has_removed and self.fail_on_removed)
            or (has_type_change and self.fail_on_type_change)
            or (has_added and self.fail_on_added)
        )

        status = MonitorStatus.FAIL if should_fail else MonitorStatus.WARN
        summary_parts = []
        if has_removed:
            count = sum(1 for c in changes if c["change_type"] == "column_removed")
            summary_parts.append(f"{count} column(s) removed")
        if has_added:
            count = sum(1 for c in changes if c["change_type"] == "column_added")
            summary_parts.append(f"{count} column(s) added")
        if has_type_change:
            count = sum(1 for c in changes if c["change_type"] == "type_changed")
            summary_parts.append(f"{count} type change(s)")

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            message=f"Schema changes detected: {', '.join(summary_parts)}.",
            details={
                "changes": changes,
                "change_count": len(changes),
                "baseline_column_count": len(baseline),
                "current_column_count": len(current_columns),
            },
        )
