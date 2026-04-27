"""
Date Consistency Check monitor.

Validates relationships between date/timestamp columns — for example,
ensuring start_date <= end_date or event_date <= CURRENT_DATE.
This is a deterministic, rule-based check.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus

# Supported comparison operators
_VALID_OPERATORS = {"<", "<=", "=", ">=", ">", "!="}


class DateConsistencyMonitor(BaseMonitor):
    """
    Validates date column relationships using configurable rules.

    Config keys:
        rules : list[dict]
            Each rule is a dict with:
              - left_column : str — Left-hand date/timestamp column
              - operator : str — One of: "<", "<=", "=", ">=", ">", "!="
              - right_column : str — Right-hand column, or "CURRENT_DATE"
                / "CURRENT_TIMESTAMP" for a dynamic comparison
            Example: [{"left_column": "start_date", "operator": "<=",
                       "right_column": "end_date"}]
        max_violation_pct : float
            Maximum percentage of rows that can violate any rule
            before FAIL (default: 0.0 = zero tolerance).
        warn_violation_pct : float
            Percentage threshold for WARN (default: 0.0).
        exclude_nulls : bool
            Skip rows where either column is NULL (default: True).
    """

    monitor_type = "date_consistency"

    _DYNAMIC_REFS = {"CURRENT_DATE", "CURRENT_TIMESTAMP", "NOW()"}

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.rules: List[Dict[str, str]] = list(self.config.get("rules", []))
        self.max_violation_pct: float = float(
            self.config.get("max_violation_pct", 0.0)
        )
        self.warn_violation_pct: float = float(
            self.config.get("warn_violation_pct", 0.0)
        )
        self.exclude_nulls: bool = self.config.get("exclude_nulls", True)

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if not self.rules:
            raise ValueError(
                "DateConsistencyMonitor requires at least one rule in 'rules' config."
            )

        fqn = self._fqn(database, schema, table, dialect)

        rule_exprs = []
        null_filters = []

        for i, rule in enumerate(self.rules):
            left = rule.get("left_column", "")
            op = rule.get("operator", "<=")
            right = rule.get("right_column", "")

            if not left or not right:
                raise ValueError(
                    f"Rule {i}: both 'left_column' and 'right_column' are required."
                )
            if op not in _VALID_OPERATORS:
                raise ValueError(
                    f"Rule {i}: operator '{op}' not supported. "
                    f"Use one of: {', '.join(sorted(_VALID_OPERATORS))}"
                )

            # Handle dynamic references (CURRENT_DATE, etc.)
            right_expr = right
            if right.upper() in self._DYNAMIC_REFS:
                right_expr = right.upper()
                if right_expr == "NOW()":
                    right_expr = "CURRENT_TIMESTAMP"
            else:
                # It's a column reference
                if self.exclude_nulls:
                    null_filters.append(f"{right} IS NOT NULL")

            if self.exclude_nulls:
                null_filters.append(f"{left} IS NOT NULL")

            # Violation = NOT satisfying the rule
            violation = f"NOT ({left} {op} {right_expr})"
            rule_exprs.append(
                f"SUM(CASE WHEN {violation} THEN 1 ELSE 0 END) AS violations_rule_{i}"
            )

        select_parts = ["COUNT(*) AS total_rows"] + rule_exprs

        where = ""
        if self.exclude_nulls and null_filters:
            # Deduplicate null filters
            unique_filters = list(dict.fromkeys(null_filters))
            where = f"WHERE {' AND '.join(unique_filters)}"

        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {fqn} {where}"
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
                message="No results returned from date consistency query.",
            )

        row = query_results[0]
        total = int(row.get("total_rows", 0))

        if total == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message="Table is empty — date consistency check skipped.",
            )

        rule_results: List[Dict[str, Any]] = []
        total_violations = 0
        worst_rule_idx = -1
        worst_violation_pct = 0.0

        for i, rule in enumerate(self.rules):
            violations = int(row.get(f"violations_rule_{i}", 0))
            total_violations += violations
            violation_pct = (violations / total) * 100 if total > 0 else 0.0

            if violation_pct > worst_violation_pct:
                worst_violation_pct = violation_pct
                worst_rule_idx = i

            rule_desc = (
                f"{rule.get('left_column', '')} "
                f"{rule.get('operator', '<=')} "
                f"{rule.get('right_column', '')}"
            )

            rule_results.append({
                "rule_index": i,
                "rule": rule_desc,
                "violations": violations,
                "violation_pct": round(violation_pct, 4),
                "left_column": rule.get("left_column", ""),
                "operator": rule.get("operator", "<="),
                "right_column": rule.get("right_column", ""),
            })

        # Overall violation rate (any rule)
        overall_violation_pct = (
            (total_violations / (total * len(self.rules))) * 100
            if total > 0 and self.rules
            else 0.0
        )

        details: Dict[str, Any] = {
            "total_rows": total,
            "rules": rule_results,
            "total_violations": total_violations,
            "overall_violation_pct": round(overall_violation_pct, 4),
            "worst_rule_index": worst_rule_idx,
            "exclude_nulls": self.exclude_nulls,
        }

        if total_violations == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message=(
                    f"Date consistency passed: all {len(self.rules)} rule(s) "
                    f"satisfied across {total:,} rows."
                ),
                details=details,
            )

        # Use worst individual rule violation pct for status
        if worst_violation_pct > self.max_violation_pct:
            status = MonitorStatus.FAIL
        elif worst_violation_pct > self.warn_violation_pct:
            status = MonitorStatus.WARN
        else:
            status = MonitorStatus.PASS

        failing_rules = [r for r in rule_results if r["violations"] > 0]
        rules_desc = "; ".join(
            f"{r['rule']} ({r['violations']:,} violations)"
            for r in failing_rules
        )

        message = (
            f"Date consistency violations: {total_violations:,} total across "
            f"{len(failing_rules)} rule(s) — {rules_desc}."
        )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=worst_violation_pct,
            threshold=self.max_violation_pct,
            message=message,
            details=details,
        )
