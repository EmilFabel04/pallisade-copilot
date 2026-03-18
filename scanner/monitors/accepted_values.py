"""
Accepted Values Check monitor.

Ensures categorical column values are within an explicit allowed set.
This is a rules-driven check — no statistical baseline is used.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class AcceptedValuesMonitor(BaseMonitor):
    """
    Validates that column values are within an allowed set.

    Config keys:
        column : str
            Column to validate.
        allowed_values : list[str]
            Set of allowed values. Rows with values outside this set
            are flagged as violations.
        case_sensitive : bool
            Whether comparison is case-sensitive (default: False).
        max_violation_pct : float
            Maximum percentage of rows that can have unexpected values
            before FAIL (default: 0.0 = zero tolerance).
        warn_violation_pct : float
            Percentage of violations that triggers WARN (default: 0.0).
        allow_null : bool
            Whether NULL values are allowed (default: True).
    """

    monitor_type = "accepted_values"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.column: str = self.config.get("column", "")
        self.allowed_values: List[str] = list(
            self.config.get("allowed_values", [])
        )
        self.case_sensitive: bool = self.config.get("case_sensitive", False)
        self.max_violation_pct: float = float(
            self.config.get("max_violation_pct", 0.0)
        )
        self.warn_violation_pct: float = float(
            self.config.get("warn_violation_pct", 0.0)
        )
        self.allow_null: bool = self.config.get("allow_null", True)

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if not self.column:
            raise ValueError(
                "AcceptedValuesMonitor requires a 'column' in config."
            )
        if not self.allowed_values:
            raise ValueError(
                "AcceptedValuesMonitor requires 'allowed_values' in config."
            )

        fqn = self._fqn(database, schema, table)
        col = self.column

        # Build the IN clause with properly escaped values
        escaped = [v.replace("'", "''") for v in self.allowed_values]
        in_values = ", ".join(f"'{v}'" for v in escaped)

        if self.case_sensitive:
            col_expr = f"CAST({col} AS VARCHAR)"
            not_in_expr = f"{col_expr} NOT IN ({in_values})"
        else:
            if dialect == "bigquery":
                col_expr = f"LOWER(CAST({col} AS STRING))"
            else:
                col_expr = f"LOWER(CAST({col} AS VARCHAR))"
            lower_values = ", ".join(
                f"'{v.lower().replace(chr(39), chr(39)+chr(39))}'"
                for v in self.allowed_values
            )
            not_in_expr = f"{col_expr} NOT IN ({lower_values})"

        null_condition = ""
        if not self.allow_null:
            null_condition = f" OR {col} IS NULL"

        # Main query: count violations + sample unexpected values
        sql = (
            f"SELECT "
            f"COUNT(*) AS total_rows, "
            f"SUM(CASE WHEN ({not_in_expr}{null_condition}) "
            f"AND {col} IS NOT NULL THEN 1 ELSE 0 END) AS violation_count "
            f"FROM {fqn}"
        )

        if not self.allow_null:
            sql = (
                f"SELECT "
                f"COUNT(*) AS total_rows, "
                f"SUM(CASE WHEN ({not_in_expr}) OR ({col} IS NULL) "
                f"THEN 1 ELSE 0 END) AS violation_count "
                f"FROM {fqn}"
            )

        if dialect == "bigquery":
            return sql
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
                message="No results returned from accepted values query.",
            )

        row = query_results[0]
        total = int(row.get("total_rows", 0))
        violations = int(row.get("violation_count", 0))

        if total == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message="Table is empty — accepted values check skipped.",
            )

        violation_pct = (violations / total) * 100 if total > 0 else 0.0

        details: Dict[str, Any] = {
            "column": self.column,
            "total_rows": total,
            "violation_count": violations,
            "violation_pct": round(violation_pct, 4),
            "allowed_values": self.allowed_values,
            "case_sensitive": self.case_sensitive,
            "allow_null": self.allow_null,
        }

        allowed_display = ", ".join(f"'{v}'" for v in self.allowed_values[:10])
        if len(self.allowed_values) > 10:
            allowed_display += f" (+{len(self.allowed_values) - 10} more)"

        if violations == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message=(
                    f"Accepted values check passed: all {total:,} rows in "
                    f"{self.column} contain allowed values ({allowed_display})."
                ),
                details=details,
            )

        if violation_pct > self.max_violation_pct:
            status = MonitorStatus.FAIL
        elif violation_pct > self.warn_violation_pct:
            status = MonitorStatus.WARN
        else:
            status = MonitorStatus.PASS

        message = (
            f"Accepted values check: {violations:,} of {total:,} rows "
            f"({violation_pct:.2f}%) in {self.column} contain unexpected values. "
            f"Allowed: {allowed_display}."
        )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=violation_pct,
            threshold=self.max_violation_pct,
            message=message,
            details=details,
        )
