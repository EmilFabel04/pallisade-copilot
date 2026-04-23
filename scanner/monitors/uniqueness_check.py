"""
Uniqueness Check monitor.

Detects duplicate values in columns expected to be unique. Supports
both hard threshold mode (max_duplicate_rate) and baseline-aware
statistical detection via the shared StatEngine.

Includes heuristic PK detection for auto-configuration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import score_anomaly, build_confidence_info

# Default maximum duplicate rate before FAIL (1%).
_DEFAULT_MAX_DUPLICATE_RATE = 0.01

# Column name patterns that suggest a primary/unique key.
_PK_PATTERNS = {"id", "uuid", "guid", "pk", "key"}
_PK_SUFFIXES = ("_id", "_uuid", "_guid", "_pk", "_key")


def _is_likely_key_column(column_name: str) -> bool:
    """Heuristic: does this column name look like a primary/unique key?"""
    lower = column_name.lower().strip()
    if lower in _PK_PATTERNS:
        return True
    return any(lower.endswith(s) for s in _PK_SUFFIXES)


class UniquenessCheckMonitor(BaseMonitor):
    """
    Monitors uniqueness / duplicate rates on specified columns.

    Config keys:
        columns : list[str] | str
            Column(s) to check for uniqueness. A single string is
            treated as one column.
        max_duplicate_rate : float
            Hard threshold — duplicate rate above this triggers FAIL
            (default: 0.01 = 1%). Set to None for pure baseline mode.
        timestamp_column : str | None
            Column for time bucketing (enables baseline mode).
        lookback_days : int
            Days of history for baseline (default: 30).
        anomaly_threshold : float
            Z-score threshold for baseline mode (default: 3.0).
        detection_method : str
            "auto" (default), "zscore", "mad", or "pct_change".
        seasonality : str | None
            "day_of_week" for DOW-based baselines.
    """

    monitor_type = "uniqueness_check"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        raw_cols = self.config.get("columns", self.config.get("column", ""))
        if isinstance(raw_cols, str):
            self.columns: List[str] = [raw_cols] if raw_cols else []
        else:
            self.columns = list(raw_cols)
        self.max_duplicate_rate: Optional[float] = self.config.get(
            "max_duplicate_rate", _DEFAULT_MAX_DUPLICATE_RATE
        )
        self.timestamp_column: Optional[str] = self.config.get("timestamp_column")
        self.lookback_days: int = int(self.config.get("lookback_days", 30))
        self.anomaly_threshold: float = float(
            self.config.get("anomaly_threshold", 3.0)
        )
        self.detection_method: str = self.config.get("detection_method", "auto")
        self.seasonality: Optional[str] = self.config.get("seasonality")

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if not self.columns:
            raise ValueError(
                "UniquenessCheckMonitor requires at least one column in 'columns' config."
            )

        fqn = self._fqn(database, schema, table)
        col_exprs = []
        for col in self.columns:
            col_exprs.append(f"COUNT(DISTINCT {col}) AS distinct_{col}")
        col_exprs.append("COUNT(*) AS total_rows")

        select_cols = ", ".join(col_exprs)

        if self.timestamp_column:
            return self._build_timeseries_query(fqn, select_cols, dialect)

        sql = f"SELECT {select_cols} FROM {fqn}"
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
                message="No results returned from uniqueness check query.",
            )

        if self.timestamp_column and len(query_results) >= 3:
            return self._evaluate_timeseries(query_results, target_fqn)

        return self._evaluate_snapshot(query_results, target_fqn)

    # ------------------------------------------------------------------
    # Query builders
    # ------------------------------------------------------------------

    def _build_timeseries_query(
        self, fqn: str, select_cols: str, dialect: str
    ) -> str:
        ts = self.timestamp_column

        if dialect == "bigquery":
            ts_date = f"CAST(CAST({ts} AS TIMESTAMP) AS DATE)"
            dow_expr = f"EXTRACT(DAYOFWEEK FROM {ts_date})"
            if self.lookback_days and self.lookback_days > 0:
                where = (
                    f"WHERE {ts_date} >= DATE_SUB(CURRENT_DATE(), "
                    f"INTERVAL {self.lookback_days} DAY)"
                )
            else:
                where = ""
        else:
            ts_date = f"CAST({ts} AS DATE)"
            dow_expr = f"EXTRACT(DOW FROM {ts_date})"
            if self.lookback_days and self.lookback_days > 0:
                where = (
                    f"WHERE {ts} >= CURRENT_DATE "
                    f"- INTERVAL '{self.lookback_days} days'"
                )
            else:
                where = ""

        if self.seasonality == "day_of_week":
            sql = (
                f"SELECT {ts_date} AS bucket_date, "
                f"{dow_expr} AS day_of_week, "
                f"{select_cols} "
                f"FROM {fqn} {where} "
                f"GROUP BY bucket_date, day_of_week "
                f"ORDER BY bucket_date"
            )
        else:
            sql = (
                f"SELECT {ts_date} AS bucket_date, "
                f"{select_cols} "
                f"FROM {fqn} {where} "
                f"GROUP BY bucket_date "
                f"ORDER BY bucket_date"
            )

        if dialect == "bigquery":
            return sql
        return self.transpile_sql(sql, dialect)

    # ------------------------------------------------------------------
    # Evaluators
    # ------------------------------------------------------------------

    def _evaluate_snapshot(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        row = query_results[0]
        total = int(row.get("total_rows", 0))
        if total == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message="Table is empty — uniqueness check skipped.",
            )

        column_results: List[Dict[str, Any]] = []
        worst_status = MonitorStatus.PASS
        worst_rate = 0.0
        worst_col = ""

        for col in self.columns:
            distinct = row.get(f"distinct_{col}")
            if distinct is None:
                continue
            distinct = int(distinct)
            duplicate_rate = 1.0 - (distinct / total) if total > 0 else 0.0

            col_status = MonitorStatus.PASS
            if (
                self.max_duplicate_rate is not None
                and duplicate_rate > self.max_duplicate_rate
            ):
                col_status = MonitorStatus.FAIL
                worst_status = MonitorStatus.FAIL

            if duplicate_rate > worst_rate:
                worst_rate = duplicate_rate
                worst_col = col

            column_results.append({
                "column": col,
                "distinct_count": distinct,
                "total_rows": total,
                "duplicate_rate": round(duplicate_rate, 6),
                "duplicate_count": total - distinct,
                "status": col_status.value,
                "threshold": self.max_duplicate_rate,
            })

        if not column_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message="No columns to check.",
            )

        failing = [c for c in column_results if c["status"] == "fail"]
        if failing:
            cols_list = ", ".join(
                f"{c['column']} ({c['duplicate_rate']:.2%})" for c in failing
            )
            message = (
                f"Uniqueness check failed: {len(failing)} column(s) exceed "
                f"{self.max_duplicate_rate:.1%} duplicate rate — {cols_list}."
            )
        else:
            message = (
                f"Uniqueness check passed: all {len(column_results)} column(s) "
                f"within {self.max_duplicate_rate:.1%} duplicate rate threshold."
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=worst_status,
            value=worst_rate,
            threshold=self.max_duplicate_rate,
            message=message,
            details={
                "columns": column_results,
                "worst_column": worst_col,
                "worst_duplicate_rate": worst_rate,
            },
        )

    def _evaluate_timeseries(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        column_results: List[Dict[str, Any]] = []
        worst_status = MonitorStatus.PASS
        worst_rate = 0.0
        worst_col = ""

        for col in self.columns:
            distinct_key = f"distinct_{col}"
            # Compute duplicate rates per bucket
            rates = []
            for r in query_results:
                d = r.get(distinct_key)
                t = r.get("total_rows")
                if d is not None and t is not None and int(t) > 0:
                    rates.append(1.0 - (int(d) / int(t)))

            if len(rates) < 3:
                continue

            current = rates[-1]
            baseline = rates[:-1]

            # Seasonal filtering
            if (
                self.seasonality == "day_of_week"
                and query_results[-1].get("day_of_week") is not None
            ):
                target_dow = query_results[-1]["day_of_week"]
                seasonal_rates = []
                for i, r in enumerate(query_results[:-1]):
                    if r.get("day_of_week") == target_dow:
                        d = r.get(distinct_key)
                        t = r.get("total_rows")
                        if d is not None and t is not None and int(t) > 0:
                            seasonal_rates.append(1.0 - (int(d) / int(t)))
                if len(seasonal_rates) >= 3:
                    baseline = seasonal_rates

            score = score_anomaly(
                current=current,
                baseline=baseline,
                threshold=self.anomaly_threshold,
                min_effect_size=0.005,
                method=self.detection_method,
            )

            col_status = MonitorStatus.PASS
            if score.is_anomaly:
                col_status = MonitorStatus.FAIL
                if score.confidence_pct < 50:
                    col_status = MonitorStatus.WARN
            elif (
                self.max_duplicate_rate is not None
                and current > self.max_duplicate_rate
            ):
                col_status = MonitorStatus.FAIL

            if col_status == MonitorStatus.FAIL:
                worst_status = MonitorStatus.FAIL
            elif col_status == MonitorStatus.WARN and worst_status != MonitorStatus.FAIL:
                worst_status = MonitorStatus.WARN

            if current > worst_rate:
                worst_rate = current
                worst_col = col

            column_results.append({
                "column": col,
                "duplicate_rate": round(current, 6),
                "status": col_status.value,
                "z_score": score.z_score,
                "baseline_mean": score.baseline_mean,
                "baseline_count": score.baseline_count,
                "confidence_pct": score.confidence_pct,
                "method_used": score.method_used,
                "is_anomaly": score.is_anomaly,
                "threshold": self.max_duplicate_rate,
            })

        if not column_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message="Insufficient data for uniqueness baseline.",
                details={"anomaly_ready": False},
            )

        failing = [c for c in column_results if c["status"] == "fail"]
        warning = [c for c in column_results if c["status"] == "warn"]

        if failing:
            cols_list = ", ".join(c["column"] for c in failing)
            message = (
                f"Uniqueness anomaly: {len(failing)} column(s) have "
                f"anomalous duplicate rates — {cols_list}."
            )
        elif warning:
            cols_list = ", ".join(c["column"] for c in warning)
            message = (
                f"Uniqueness warning: {len(warning)} column(s) have "
                f"elevated duplicate rates (low confidence) — {cols_list}."
            )
        else:
            message = (
                f"Uniqueness check passed: all {len(column_results)} column(s) "
                f"have normal duplicate rates."
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=worst_status,
            value=worst_rate,
            threshold=self.max_duplicate_rate,
            message=message,
            details={
                "columns": column_results,
                "worst_column": worst_col,
                "worst_duplicate_rate": worst_rate,
                "confidence_info": build_confidence_info(
                    confidence_pct=column_results[0].get("confidence_pct", 0)
                    if column_results else 0,
                    baseline_count=column_results[0].get("baseline_count", 0)
                    if column_results else 0,
                    evaluation_mode="baseline_uniqueness_check",
                ),
            },
        )
