"""
Custom SQL monitor.

Executes a user-provided SQL query and evaluates the resulting numeric
value against configurable thresholds. The query must return at least
one row with a single numeric column.

Status is determined by comparing the returned value against
min_value / max_value bounds:
- FAIL when the value is outside [min_value, max_value]
- PASS otherwise
- ERROR when the query returns no rows or a non-numeric value

The query is executed verbatim — no FQN substitution is performed — so
users can reference multiple tables, joins, CTEs, or warehouse-specific
syntax. The target database.schema.table is passed through as metadata
for display purposes only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class CustomSqlMonitor(BaseMonitor):
    """
    Executes a custom SQL check and evaluates the result against bounds.

    Config keys:
        sql : str (REQUIRED)
            The SQL query to execute. Must return at least one row with
            a single numeric column (the first column of the first row
            is used as the check value).
        min_value : float | None
            Minimum acceptable value (inclusive). None = no lower bound.
        max_value : float | None
            Maximum acceptable value (inclusive). None = no upper bound.
        warn_min_value : float | None
            Warning lower bound. Value below this but above min_value
            triggers WARN. Defaults to min_value.
        warn_max_value : float | None
            Warning upper bound. Value above this but below max_value
            triggers WARN. Defaults to max_value.
        label : str | None
            Optional human-readable label for the metric (used in
            messages). Defaults to "result".
    """

    monitor_type = "custom_sql"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.sql: str = str(self.config.get("sql", "")).strip()
        self.min_value: Optional[float] = self._coerce_optional_float(
            self.config.get("min_value")
        )
        self.max_value: Optional[float] = self._coerce_optional_float(
            self.config.get("max_value")
        )
        self.warn_min_value: Optional[float] = self._coerce_optional_float(
            self.config.get("warn_min_value")
        )
        self.warn_max_value: Optional[float] = self._coerce_optional_float(
            self.config.get("warn_max_value")
        )
        self.label: str = str(self.config.get("label") or "result")

    @staticmethod
    def _coerce_optional_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if not self.sql:
            raise ValueError(
                "CustomSqlMonitor requires a non-empty 'sql' in config."
            )
        return self.sql

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
                message="Custom SQL query returned no rows.",
                details={"sql": self.sql},
            )

        row = query_results[0]
        if not row:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message="Custom SQL query returned an empty row.",
                details={"sql": self.sql},
            )

        # Use the first column of the first row as the check value
        first_key = next(iter(row.keys()))
        raw_value = row[first_key]

        if raw_value is None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message=(
                    f"Custom SQL query returned NULL for column '{first_key}'. "
                    f"The query must return a numeric value."
                ),
                details={"sql": self.sql, "column": first_key},
            )

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message=(
                    f"Custom SQL query returned non-numeric value "
                    f"'{raw_value}' in column '{first_key}'."
                ),
                details={"sql": self.sql, "column": first_key, "raw_value": str(raw_value)},
            )

        details: Dict[str, Any] = {
            "sql": self.sql,
            "column": first_key,
            "value": value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "warn_min_value": self.warn_min_value,
            "warn_max_value": self.warn_max_value,
        }

        warn_min = self.warn_min_value if self.warn_min_value is not None else self.min_value
        warn_max = self.warn_max_value if self.warn_max_value is not None else self.max_value

        status = MonitorStatus.PASS
        message_parts: List[str] = []

        below_min = self.min_value is not None and value < self.min_value
        above_max = self.max_value is not None and value > self.max_value

        if below_min or above_max:
            status = MonitorStatus.FAIL
            if below_min:
                message_parts.append(
                    f"{self.label} = {value} is below min {self.min_value}"
                )
            if above_max:
                message_parts.append(
                    f"{self.label} = {value} exceeds max {self.max_value}"
                )
        else:
            warn_below = (
                warn_min is not None
                and self.warn_min_value is not None
                and value < warn_min
            )
            warn_above = (
                warn_max is not None
                and self.warn_max_value is not None
                and value > warn_max
            )
            if warn_below or warn_above:
                status = MonitorStatus.WARN
                if warn_below:
                    message_parts.append(
                        f"{self.label} = {value} is below warn threshold {warn_min}"
                    )
                if warn_above:
                    message_parts.append(
                        f"{self.label} = {value} exceeds warn threshold {warn_max}"
                    )

        if not message_parts:
            bounds_desc = self._describe_bounds()
            message = (
                f"Custom SQL check passed: {self.label} = {value}"
                + (f" ({bounds_desc})" if bounds_desc else "")
            )
        else:
            message = "; ".join(message_parts)

        threshold = self.max_value if above_max else (self.min_value if below_min else None)

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=value,
            threshold=threshold,
            message=message,
            details=details,
        )

    def _describe_bounds(self) -> str:
        parts: List[str] = []
        if self.min_value is not None:
            parts.append(f">= {self.min_value}")
        if self.max_value is not None:
            parts.append(f"<= {self.max_value}")
        return " and ".join(parts)
