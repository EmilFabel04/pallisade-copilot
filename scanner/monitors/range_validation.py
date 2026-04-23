"""
Range Validation monitor.

Ensures numeric column values fall within specified bounds (min/max).
This is a deterministic, threshold-based check — no statistical
baseline is used.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class RangeValidationMonitor(BaseMonitor):
    """
    Validates that numeric column values are within expected bounds.

    Config keys:
        column : str
            Column to validate.
        min_value : float | None
            Minimum allowed value (inclusive). None = no lower bound.
        max_value : float | None
            Maximum allowed value (inclusive). None = no upper bound.
        max_violation_pct : float
            Maximum percentage of rows that can violate bounds before
            FAIL (default: 0.0 = zero tolerance).
        warn_violation_pct : float
            Percentage of violations that triggers WARN (default: 0.0).
        allow_null : bool
            Whether NULL values are allowed (default: True).
            If False, NULLs count as violations.
    """

    monitor_type = "range_validation"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.column: str = self.config.get("column", "")
        self.min_value: Optional[float] = self.config.get("min_value")
        self.max_value: Optional[float] = self.config.get("max_value")
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
                "RangeValidationMonitor requires a 'column' in config."
            )
        if self.min_value is None and self.max_value is None:
            raise ValueError(
                "RangeValidationMonitor requires at least one of "
                "'min_value' or 'max_value' in config."
            )

        fqn = self._fqn(database, schema, table)
        col = self.column

        # Build violation conditions
        conditions = []
        if self.min_value is not None:
            conditions.append(f"CAST({col} AS FLOAT) < {self.min_value}")
        if self.max_value is not None:
            conditions.append(f"CAST({col} AS FLOAT) > {self.max_value}")

        violation_expr = " OR ".join(conditions)

        if not self.allow_null:
            violation_expr = f"({violation_expr}) OR ({col} IS NULL)"

        if dialect == "bigquery":
            violation_expr = violation_expr.replace("AS FLOAT)", "AS FLOAT64)")

        sql = (
            f"SELECT "
            f"COUNT(*) AS total_rows, "
            f"SUM(CASE WHEN {violation_expr} THEN 1 ELSE 0 END) AS violation_count, "
            f"MIN(CAST({col} AS FLOAT)) AS actual_min, "
            f"MAX(CAST({col} AS FLOAT)) AS actual_max "
            f"FROM {fqn}"
        )

        if dialect == "bigquery":
            sql = sql.replace("AS FLOAT)", "AS FLOAT64)")
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
                message="No results returned from range validation query.",
            )

        row = query_results[0]
        total = int(row.get("total_rows", 0))
        violations = int(row.get("violation_count", 0))
        actual_min = row.get("actual_min")
        actual_max = row.get("actual_max")

        if total == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message="Table is empty — range validation skipped.",
            )

        violation_pct = (violations / total) * 100 if total > 0 else 0.0

        details: Dict[str, Any] = {
            "column": self.column,
            "total_rows": total,
            "violation_count": violations,
            "violation_pct": round(violation_pct, 4),
            "min_value": self.min_value,
            "max_value": self.max_value,
            "actual_min": float(actual_min) if actual_min is not None else None,
            "actual_max": float(actual_max) if actual_max is not None else None,
            "allow_null": self.allow_null,
        }

        bounds_desc = []
        if self.min_value is not None:
            bounds_desc.append(f">= {self.min_value}")
        if self.max_value is not None:
            bounds_desc.append(f"<= {self.max_value}")
        bounds_str = " and ".join(bounds_desc)

        if violations == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message=(
                    f"Range validation passed: all {total:,} rows in "
                    f"{self.column} are {bounds_str}."
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
            f"Range validation: {violations:,} of {total:,} rows "
            f"({violation_pct:.2f}%) in {self.column} are outside bounds "
            f"({bounds_str})."
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
