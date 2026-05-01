"""
NULL Check monitor.

Detects unexpected null values in one or more columns. Supports both
hard threshold mode (max_null_rate) and baseline-aware statistical
detection via the shared StatEngine.

When historical data is available, uses z-score/MAD anomaly detection
on null rates to catch drift. Falls back to a hard threshold when no
baseline exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import score_anomaly, build_confidence_info

# Default maximum null rate before FAIL (5%).
_DEFAULT_MAX_NULL_RATE = 0.05


class NullCheckMonitor(BaseMonitor):
    """
    Monitors null rates across one or more columns.

    Config keys:
        columns : list[str] | str
            Column(s) to check. Use "*" to scan all columns.
            A single string is treated as one column.
        max_null_rate : float
            Hard threshold — null rate above this triggers FAIL
            (default: 0.05 = 5%). Set to None to rely purely on
            baseline anomaly detection.
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

    monitor_type = "null_check"

    _NULL_RATE_SQL = (
        "CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS FLOAT) "
        "/ NULLIF(COUNT(*), 0)"
    )

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        raw_cols = self.config.get("columns", self.config.get("column", "*"))
        if isinstance(raw_cols, str):
            self.columns: List[str] = [raw_cols]
        else:
            self.columns = list(raw_cols)
        self.max_null_rate: Optional[float] = self.config.get(
            "max_null_rate", _DEFAULT_MAX_NULL_RATE
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
        fqn = self._fqn(database, schema, table, dialect)
        # Reject any user-supplied column with SQL metacharacters before they
        # reach the f-string interpolation below.
        for c in self.columns:
            if c != "*":
                self._validate_column(c)
        if self.timestamp_column:
            self._validate_column(self.timestamp_column)

        if self.columns == ["*"]:
            # Wildcard mode: query INFORMATION_SCHEMA to discover columns,
            # then generate a multi-column null rate scan.
            # The executor should call auto_configure first to resolve "*"
            # into real column names. If still "*", we fall back to a
            # table-level aggregate null rate.
            return self._build_table_null_query(fqn, dialect)

        # Build per-column null rate expressions.
        col_exprs = []
        for col in self.columns:
            expr = self._NULL_RATE_SQL.format(col=col)
            if dialect == "bigquery":
                expr = expr.replace("AS FLOAT)", "AS FLOAT64)")
            col_exprs.append(f"{expr} AS null_rate_{col}")

        select_cols = ", ".join(col_exprs)

        if self.timestamp_column:
            return self._build_timeseries_query(
                fqn, select_cols, dialect
            )

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
                message="No results returned from null check query.",
            )

        # Time-series mode: use baseline anomaly detection.
        if self.timestamp_column and len(query_results) >= 3:
            return self._evaluate_timeseries(query_results, target_fqn)

        # Snapshot mode: check against hard threshold.
        return self._evaluate_snapshot(query_results, target_fqn)

    # ------------------------------------------------------------------
    # Query builders
    # ------------------------------------------------------------------

    def _build_table_null_query(self, fqn: str, dialect: str) -> str:
        """Table-level aggregate null rate (wildcard mode fallback)."""
        # This produces one row with overall null rate.
        # When columns are resolved, build_query uses per-column mode instead.
        expr = (
            "CAST(SUM(CASE WHEN 1=0 THEN 1 ELSE 0 END) AS FLOAT) "
            "/ NULLIF(COUNT(*), 0)"
        )
        # Wildcard unresolved — return a simple count so executor can
        # auto-configure columns and re-run.
        sql = f"SELECT COUNT(*) AS row_count FROM {fqn}"
        return self.transpile_sql(sql, dialect)

    def _build_timeseries_query(
        self,
        fqn: str,
        select_cols: str,
        dialect: str,
    ) -> str:
        """Build a time-bucketed query for baseline mode."""
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
        """Evaluate a single-point null rate snapshot against threshold."""
        row = query_results[0]
        column_results: List[Dict[str, Any]] = []
        worst_status = MonitorStatus.PASS
        worst_rate = 0.0
        worst_col = ""

        for col in self.columns:
            if col == "*":
                continue
            key = f"null_rate_{col}"
            rate = row.get(key)
            if rate is None:
                continue
            rate = float(rate)

            col_status = MonitorStatus.PASS
            if self.max_null_rate is not None and rate > self.max_null_rate:
                col_status = MonitorStatus.FAIL
                if worst_status != MonitorStatus.FAIL:
                    worst_status = MonitorStatus.FAIL

            if rate > worst_rate:
                worst_rate = rate
                worst_col = col

            column_results.append({
                "column": col,
                "null_rate": round(rate, 6),
                "status": col_status.value,
                "threshold": self.max_null_rate,
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
            cols_list = ", ".join(c["column"] for c in failing)
            message = (
                f"NULL check failed: {len(failing)} column(s) exceed "
                f"{self.max_null_rate:.0%} null rate threshold — {cols_list}."
            )
        else:
            message = (
                f"NULL check passed: all {len(column_results)} column(s) "
                f"within {self.max_null_rate:.0%} null rate threshold."
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=worst_status,
            value=worst_rate,
            threshold=self.max_null_rate,
            message=message,
            details={
                "columns": column_results,
                "worst_column": worst_col,
                "worst_null_rate": worst_rate,
            },
        )

    def _evaluate_timeseries(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        """Evaluate null rates using baseline anomaly detection."""
        column_results: List[Dict[str, Any]] = []
        worst_status = MonitorStatus.PASS
        worst_rate = 0.0
        worst_col = ""

        for col in self.columns:
            if col == "*":
                continue
            key = f"null_rate_{col}"
            values = [
                float(r[key])
                for r in query_results
                if r.get(key) is not None
            ]
            if len(values) < 3:
                continue

            current = values[-1]
            baseline = values[:-1]

            # Seasonal filtering
            if (
                self.seasonality == "day_of_week"
                and query_results[-1].get("day_of_week") is not None
            ):
                target_dow = query_results[-1]["day_of_week"]
                seasonal = [
                    float(r[key])
                    for r in query_results[:-1]
                    if r.get("day_of_week") == target_dow
                    and r.get(key) is not None
                ]
                if len(seasonal) >= 3:
                    baseline = seasonal

            score = score_anomaly(
                current=current,
                baseline=baseline,
                threshold=self.anomaly_threshold,
                min_effect_size=0.01,
                method=self.detection_method,
            )

            col_status = MonitorStatus.PASS
            # Check baseline anomaly
            if score.is_anomaly:
                col_status = MonitorStatus.FAIL
                if score.confidence_pct < 50:
                    col_status = MonitorStatus.WARN
            # Also check hard threshold as a floor
            elif self.max_null_rate is not None and current > self.max_null_rate:
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
                "null_rate": round(current, 6),
                "status": col_status.value,
                "z_score": score.z_score,
                "baseline_mean": score.baseline_mean,
                "baseline_count": score.baseline_count,
                "confidence_pct": score.confidence_pct,
                "method_used": score.method_used,
                "is_anomaly": score.is_anomaly,
                "threshold": self.max_null_rate,
            })

        if not column_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message="Insufficient data for null check baseline.",
                details={"anomaly_ready": False},
            )

        failing = [c for c in column_results if c["status"] == "fail"]
        warning = [c for c in column_results if c["status"] == "warn"]

        if failing:
            cols_list = ", ".join(c["column"] for c in failing)
            message = (
                f"NULL check anomaly: {len(failing)} column(s) have "
                f"anomalous null rates — {cols_list}."
            )
        elif warning:
            cols_list = ", ".join(c["column"] for c in warning)
            message = (
                f"NULL check warning: {len(warning)} column(s) have "
                f"elevated null rates (low confidence) — {cols_list}."
            )
        else:
            message = (
                f"NULL check passed: all {len(column_results)} column(s) "
                f"have normal null rates."
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=worst_status,
            value=worst_rate,
            threshold=self.max_null_rate,
            message=message,
            details={
                "columns": column_results,
                "worst_column": worst_col,
                "worst_null_rate": worst_rate,
                "confidence_info": build_confidence_info(
                    confidence_pct=column_results[0].get("confidence_pct", 0)
                    if column_results else 0,
                    baseline_count=column_results[0].get("baseline_count", 0)
                    if column_results else 0,
                    evaluation_mode="baseline_null_check",
                ),
            },
        )


def _run_null_check_for_custom_source(task: Dict[str, Any]) -> Dict[str, Any]:
    from scanner.monitors.custom_source_results import latest_probe_run_for

    integration_id = task["integrationId"]
    config = task.get("config") or {}
    dataset_id = config.get("dataset_id")
    column = config.get("column")
    if not dataset_id or not column:
        return {"status": "ERROR", "message": "config.dataset_id and config.column required"}

    run = latest_probe_run_for(integration_id, dataset_id)
    if not run:
        return {"status": "ERROR", "message": "no probe run yet"}

    row_count = int(run.get("row_count") or 0)
    null_counts = run.get("null_counts") or {}
    if row_count == 0:
        return {"status": "OK", "value": 0.0, "threshold": None, "message": "empty dataset"}

    null_count = int(null_counts.get(column) or 0)
    null_rate = null_count / row_count

    threshold = float(config.get("max_null_rate", 0.0))
    status = "ALERT" if null_rate > threshold else "OK"
    return {
        "status": status,
        "value": null_rate,
        "threshold": threshold,
        "message": f"null rate for {column!r}: {null_rate:.3f} (max {threshold:.3f})",
    }
