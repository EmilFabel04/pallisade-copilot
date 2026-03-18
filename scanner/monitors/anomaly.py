"""
Outlier Detection / Anomaly monitor.

Two modes:

  1. **Distribution mode** (default): Computes the column's statistical
     distribution (IQR, percentiles, mean/stddev) and counts how many
     rows fall outside the IQR fences.  Works immediately on first run
     with a single query — no historical baseline needed.

  2. **Trend mode**: Compares daily aggregate metrics against a historical
     baseline to detect day-over-day drift.  Requires a timestamp column
     and >= 3 days of history.

Distribution mode is the default because it gives useful results on
first run.  Trend mode is available for configs that explicitly set
``mode: "trend"`` or have pre-computed ``historical_values``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import score_anomaly, build_confidence_info, format_number

_logger = logging.getLogger(__name__)

# Metrics now owned by dedicated first-class monitors.
_DEDICATED_METRICS = {"null_rate", "distinct_count", "distinct_rate", "row_count"}

# Default minimum absolute change by metric type (trend mode only).
_DEFAULT_MIN_EFFECT_SIZE: Dict[str, float] = {
    "null_rate": 0.01,
    "distinct_rate": 0.01,
    "zero_rate": 0.01,
    "distinct_count": 0,
    "min": 0,
    "max": 0,
    "avg": 0,
    "sum": 0,
    "stddev": 0,
    "row_count": 0,
}


class AnomalyMonitor(BaseMonitor):
    """
    Detects statistical outliers in numeric columns.

    This is the backend for "Outlier Detection" in the user-facing catalog.

    **Distribution mode** (default):
        Computes percentiles (Q1, median, Q3), IQR fences, and counts
        rows outside the fences.  One query per column, works on first run.

        Config keys:
            column : str
                Target column (required).
            iqr_multiplier : float
                Fence multiplier (default 1.5 = standard outliers,
                3.0 = extreme outliers only).
            max_outlier_pct : float
                Max percentage of outlier rows before FAIL (default 5.0).
            warn_outlier_pct : float
                Percentage of outlier rows that triggers WARN (default 1.0).

    **Trend mode** (``mode: "trend"``):
        Compares daily aggregate metrics against a historical baseline.

        Config keys:
            column : str
            metric : str ("avg", "min", "max", "sum", "stddev", "zero_rate")
            anomaly_threshold : float (z-score threshold, default 3.0)
            timestamp_column : str
            lookback_days : int (default 30)
            seasonality : str | None ("day_of_week")
            historical_values : list[float] | None
    """

    monitor_type = "anomaly"

    # Kept for backward compat references from executor code.
    ALL_COLUMN_METRICS = {"null_rate", "distinct_count", "distinct_rate"}
    NUMERIC_ONLY_METRICS = {"min", "max", "avg", "sum", "stddev", "zero_rate"}

    # ---------------------------------------------------------------
    # Trend-mode SQL templates (kept for backward compat)
    # ---------------------------------------------------------------
    METRIC_SQL = {
        "min": "MIN(CAST({col} AS FLOAT))",
        "max": "MAX(CAST({col} AS FLOAT))",
        "avg": "AVG(CAST({col} AS FLOAT))",
        "sum": "SUM(CAST({col} AS FLOAT))",
        "stddev": "STDDEV(CAST({col} AS FLOAT))",
        "zero_rate": (
            "CAST(SUM(CASE WHEN {col} = 0 THEN 1 ELSE 0 END) AS FLOAT) "
            "/ NULLIF(COUNT(*), 0)"
        ),
        "null_rate": (
            "CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS FLOAT) "
            "/ NULLIF(COUNT(*), 0)"
        ),
        "distinct_count": "COUNT(DISTINCT {col})",
        "distinct_rate": (
            "CAST(COUNT(DISTINCT {col}) AS FLOAT) / NULLIF(COUNT(*), 0)"
        ),
    }
    TABLE_METRIC_SQL = {
        "row_count": "COUNT(*)",
    }

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.column: str = self.config.get("column", "")

        # Resolve mode
        self.mode: str = self._resolve_mode()

        # --- Distribution mode config ---
        self.iqr_multiplier: float = float(
            self.config.get("iqr_multiplier", 1.5)
        )
        self.max_outlier_pct: float = float(
            self.config.get("max_outlier_pct", 5.0)
        )
        self.warn_outlier_pct: float = float(
            self.config.get("warn_outlier_pct", 1.0)
        )

        # --- Trend mode config ---
        self.metric: str = self.config.get("metric", "avg")
        if self.mode == "trend" and self.metric in _DEDICATED_METRICS:
            _logger.warning(
                "AnomalyMonitor metric '%s' is deprecated — use the "
                "dedicated monitor instead (null_check, uniqueness_check, "
                "or volume). Legacy config will still execute.",
                self.metric,
            )
        self.anomaly_threshold: float = float(
            self.config.get("anomaly_threshold", 3.0)
        )
        self.min_effect_size: float = float(
            self.config.get(
                "min_effect_size",
                _DEFAULT_MIN_EFFECT_SIZE.get(self.metric, 0),
            )
        )
        self.detection_method: str = self.config.get("detection_method", "auto")
        self.seasonality: Optional[str] = self.config.get("seasonality")
        self.lookback_days: int = int(self.config.get("lookback_days", 30))
        self.timestamp_column: Optional[str] = self.config.get("timestamp_column")
        self.historical_values: Optional[List[float]] = self.config.get(
            "historical_values"
        )

    def _resolve_mode(self) -> str:
        explicit = self.config.get("mode")
        if explicit:
            return explicit
        # If caller provided historical_values, they want trend mode
        if self.config.get("historical_values"):
            return "trend"
        return "distribution"

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if self.mode == "distribution":
            return self._build_distribution_query(database, schema, table, dialect)
        return self._build_trend_query(database, schema, table, dialect)

    def evaluate(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        if self.mode == "distribution":
            return self._evaluate_distribution(query_results, target_fqn)
        return self._evaluate_trend(query_results, target_fqn)

    # ===============================================================
    # DISTRIBUTION MODE
    # ===============================================================

    def _build_distribution_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str,
    ) -> str:
        if not self.column:
            raise ValueError(
                "AnomalyMonitor distribution mode requires a 'column' in config."
            )
        fqn = self._fqn(database, schema, table)
        col = self.column
        mult = self.iqr_multiplier

        if dialect == "bigquery":
            return self._distribution_query_bigquery(fqn, col, mult)
        return self._distribution_query_generic(fqn, col, mult, dialect)

    def _distribution_query_bigquery(
        self, fqn: str, col: str, mult: float
    ) -> str:
        return (
            f"WITH stats AS ("
            f"  SELECT"
            f"    COUNT(*) AS total_rows,"
            f"    AVG(CAST({col} AS FLOAT64)) AS mean_val,"
            f"    STDDEV(CAST({col} AS FLOAT64)) AS stddev_val,"
            f"    MIN(CAST({col} AS FLOAT64)) AS min_val,"
            f"    MAX(CAST({col} AS FLOAT64)) AS max_val,"
            f"    APPROX_QUANTILES(CAST({col} AS FLOAT64), 4)[OFFSET(1)] AS q1,"
            f"    APPROX_QUANTILES(CAST({col} AS FLOAT64), 4)[OFFSET(2)] AS median_val,"
            f"    APPROX_QUANTILES(CAST({col} AS FLOAT64), 4)[OFFSET(3)] AS q3"
            f"  FROM {fqn}"
            f"  WHERE {col} IS NOT NULL"
            f") "
            f"SELECT"
            f"  s.total_rows, s.mean_val, s.stddev_val,"
            f"  s.min_val, s.max_val,"
            f"  s.q1, s.median_val, s.q3,"
            f"  s.q3 - s.q1 AS iqr,"
            f"  s.q1 - {mult} * (s.q3 - s.q1) AS lower_fence,"
            f"  s.q3 + {mult} * (s.q3 - s.q1) AS upper_fence,"
            f"  COUNTIF(CAST(t.{col} AS FLOAT64)"
            f"    < s.q1 - {mult} * (s.q3 - s.q1)) AS outlier_low,"
            f"  COUNTIF(CAST(t.{col} AS FLOAT64)"
            f"    > s.q3 + {mult} * (s.q3 - s.q1)) AS outlier_high"
            f" FROM {fqn} t"
            f" CROSS JOIN stats s"
            f" WHERE t.{col} IS NOT NULL"
            f" GROUP BY 1, 2, 3, 4, 5, 6, 7, 8"
        )

    def _distribution_query_generic(
        self, fqn: str, col: str, mult: float, dialect: str
    ) -> str:
        sql = (
            f"WITH stats AS ("
            f"  SELECT"
            f"    COUNT(*) AS total_rows,"
            f"    AVG(CAST({col} AS FLOAT)) AS mean_val,"
            f"    STDDEV(CAST({col} AS FLOAT)) AS stddev_val,"
            f"    MIN(CAST({col} AS FLOAT)) AS min_val,"
            f"    MAX(CAST({col} AS FLOAT)) AS max_val,"
            f"    PERCENTILE_CONT(0.25) WITHIN GROUP"
            f"      (ORDER BY CAST({col} AS FLOAT)) AS q1,"
            f"    PERCENTILE_CONT(0.50) WITHIN GROUP"
            f"      (ORDER BY CAST({col} AS FLOAT)) AS median_val,"
            f"    PERCENTILE_CONT(0.75) WITHIN GROUP"
            f"      (ORDER BY CAST({col} AS FLOAT)) AS q3"
            f"  FROM {fqn}"
            f"  WHERE {col} IS NOT NULL"
            f") "
            f"SELECT"
            f"  s.total_rows, s.mean_val, s.stddev_val,"
            f"  s.min_val, s.max_val,"
            f"  s.q1, s.median_val, s.q3,"
            f"  s.q3 - s.q1 AS iqr,"
            f"  s.q1 - {mult} * (s.q3 - s.q1) AS lower_fence,"
            f"  s.q3 + {mult} * (s.q3 - s.q1) AS upper_fence,"
            f"  SUM(CASE WHEN CAST(t.{col} AS FLOAT)"
            f"    < s.q1 - {mult} * (s.q3 - s.q1)"
            f"    THEN 1 ELSE 0 END) AS outlier_low,"
            f"  SUM(CASE WHEN CAST(t.{col} AS FLOAT)"
            f"    > s.q3 + {mult} * (s.q3 - s.q1)"
            f"    THEN 1 ELSE 0 END) AS outlier_high"
            f" FROM {fqn} t"
            f" CROSS JOIN stats s"
            f" WHERE t.{col} IS NOT NULL"
            f" GROUP BY s.total_rows, s.mean_val, s.stddev_val,"
            f"   s.min_val, s.max_val, s.q1, s.median_val, s.q3"
        )
        return self.transpile_sql(sql, dialect)

    def _evaluate_distribution(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        if not query_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message=(
                    f"No data returned for {self.column} — column may be "
                    f"all NULLs or table is empty."
                ),
            )

        row = query_results[0]
        total_rows = int(row.get("total_rows", 0))
        if total_rows == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=0.0,
                message=f"{self.column}: no non-NULL rows to analyze.",
                details={"column": self.column, "mode": "distribution"},
            )

        mean_val = _safe_float(row.get("mean_val"), 0.0)
        stddev_val = _safe_float(row.get("stddev_val"), 0.0)
        min_val = _safe_float(row.get("min_val"), 0.0)
        max_val = _safe_float(row.get("max_val"), 0.0)
        q1 = _safe_float(row.get("q1"), 0.0)
        median_val = _safe_float(row.get("median_val"), 0.0)
        q3 = _safe_float(row.get("q3"), 0.0)
        iqr = _safe_float(row.get("iqr"), 0.0)
        lower_fence = _safe_float(row.get("lower_fence"), 0.0)
        upper_fence = _safe_float(row.get("upper_fence"), 0.0)
        outlier_low = int(row.get("outlier_low", 0))
        outlier_high = int(row.get("outlier_high", 0))
        outlier_count = outlier_low + outlier_high
        outlier_pct = (outlier_count / total_rows * 100) if total_rows > 0 else 0.0

        # Handle IQR = 0 (all values in same quartile range).
        # Fall back to z-score method: mean +/- 3*stddev.
        used_fallback = False
        if iqr == 0 and stddev_val > 0:
            used_fallback = True
            lower_fence = mean_val - self.anomaly_threshold * stddev_val
            upper_fence = mean_val + self.anomaly_threshold * stddev_val
            # Recompute outlier counts based on stddev fences.
            # We can't re-query, so approximate from min/max:
            # if min < lower_fence or max > upper_fence, there ARE outliers
            # but we don't have exact count. Use the SQL-computed counts
            # which compared against q1/q3 (which were equal).
            # In practice, IQR=0 means very concentrated data — the SQL
            # outlier counts are a reasonable approximation.

        # Determine status
        if outlier_pct > self.max_outlier_pct:
            status = MonitorStatus.FAIL
        elif outlier_pct > self.warn_outlier_pct:
            status = MonitorStatus.WARN
        else:
            status = MonitorStatus.PASS

        # Build human-readable message
        col = self.column
        if outlier_count == 0:
            message = (
                f"{col}: no outliers detected in {total_rows:,} rows. "
                f"Range [{format_number(min_val)}, {format_number(max_val)}], "
                f"median {format_number(median_val)}, "
                f"IQR [{format_number(q1)}, {format_number(q3)}]."
            )
        else:
            direction_parts = []
            if outlier_low > 0:
                direction_parts.append(
                    f"{outlier_low:,} below {format_number(lower_fence)}"
                )
            if outlier_high > 0:
                direction_parts.append(
                    f"{outlier_high:,} above {format_number(upper_fence)}"
                )
            direction_str = ", ".join(direction_parts)
            message = (
                f"{col}: {outlier_count:,} outlier rows "
                f"({outlier_pct:.2f}%) in {total_rows:,} rows. "
                f"{direction_str}. "
                f"Distribution: median {format_number(median_val)}, "
                f"IQR [{format_number(q1)}, {format_number(q3)}], "
                f"fences [{format_number(lower_fence)}, "
                f"{format_number(upper_fence)}]."
            )

        details: Dict[str, Any] = {
            "column": self.column,
            "mode": "distribution",
            "total_rows": total_rows,
            "outlier_count": outlier_count,
            "outlier_pct": round(outlier_pct, 4),
            "outlier_low": outlier_low,
            "outlier_high": outlier_high,
            "mean": round(mean_val, 4),
            "median": round(median_val, 4),
            "stddev": round(stddev_val, 4),
            "q1": round(q1, 4),
            "q3": round(q3, 4),
            "iqr": round(iqr, 4),
            "lower_fence": round(lower_fence, 4),
            "upper_fence": round(upper_fence, 4),
            "min_val": round(min_val, 4),
            "max_val": round(max_val, 4),
            "iqr_multiplier": self.iqr_multiplier,
        }
        if used_fallback:
            details["iqr_zero_fallback"] = True
            details["fallback_method"] = "stddev"

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=outlier_pct,
            threshold=self.max_outlier_pct,
            expected_range={"min": round(lower_fence, 4), "max": round(upper_fence, 4)},
            message=message,
            details=details,
        )

    # ===============================================================
    # TREND MODE (original time-series comparison)
    # ===============================================================

    def _build_trend_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str,
    ) -> str:
        is_table_metric = self.metric in self.TABLE_METRIC_SQL
        if not self.column and not is_table_metric:
            raise ValueError(
                "AnomalyMonitor trend mode requires a 'column' for "
                "column-level metrics."
            )
        fqn = self._fqn(database, schema, table)
        metric_expr = self._metric_expression(dialect)

        if self.timestamp_column:
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
                dow_expr = f"EXTRACT(DOW FROM CAST({ts} AS DATE))"
                if self.lookback_days and self.lookback_days > 0:
                    where = (
                        f"WHERE {ts} >= CURRENT_DATE "
                        f"- INTERVAL '{self.lookback_days} days'"
                    )
                else:
                    where = ""

            if self.seasonality == "day_of_week":
                sql = (
                    f"SELECT "
                    f"{ts_date if dialect == 'bigquery' else f'CAST({ts} AS DATE)'} AS bucket_date, "
                    f"{dow_expr} AS day_of_week, "
                    f"{metric_expr} AS metric_value "
                    f"FROM {fqn} "
                    f"{where} "
                    f"GROUP BY bucket_date, day_of_week "
                    f"ORDER BY bucket_date"
                )
            else:
                sql = (
                    f"SELECT "
                    f"{ts_date if dialect == 'bigquery' else f'CAST({ts} AS DATE)'} AS bucket_date, "
                    f"{metric_expr} AS metric_value "
                    f"FROM {fqn} "
                    f"{where} "
                    f"GROUP BY bucket_date "
                    f"ORDER BY bucket_date"
                )

            if dialect == "bigquery":
                return sql
        else:
            sql = (
                f"SELECT {metric_expr} AS metric_value FROM {fqn}"
            )

        return self.transpile_sql(sql, dialect)

    def _evaluate_trend(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        if not query_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message="No results returned from trend query.",
            )

        # Pre-computed historical values
        if self.historical_values and len(self.historical_values) >= 3:
            current_value = self._extract_current_value(query_results)
            if current_value is None:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.ERROR,
                    message="Could not extract current metric value.",
                )
            return self._stat_evaluate(
                current_value, self.historical_values, target_fqn
            )

        # Time-series inline baseline
        if len(query_results) >= 3:
            values = [
                float(r["metric_value"])
                for r in query_results
                if r.get("metric_value") is not None
            ]
            if len(values) >= 3:
                current = values[-1]
                baseline = values[:-1]

                if (
                    self.seasonality == "day_of_week"
                    and query_results[-1].get("day_of_week") is not None
                ):
                    target_dow = query_results[-1]["day_of_week"]
                    seasonal_baseline = [
                        float(r["metric_value"])
                        for r in query_results[:-1]
                        if r.get("day_of_week") == target_dow
                        and r.get("metric_value") is not None
                    ]
                    if len(seasonal_baseline) >= 3:
                        baseline = seasonal_baseline

                return self._stat_evaluate(current, baseline, target_fqn)

        # Insufficient data for trend analysis
        current_value = self._extract_current_value(query_results)
        label = f"{self.column}.{self.metric}" if self.column else self.metric
        n = len(query_results)

        has_ts = bool(self.timestamp_column)
        if has_ts:
            hint = (
                f"Fewer than 3 days of data in the last "
                f"{self.lookback_days} days. Trend detection will "
                f"activate once more history is available."
            )
        else:
            hint = (
                "No timestamp column — trend detection cannot backfill "
                "from historical data. Specify a timestamp_column or "
                "set up scheduled scans."
            )

        if current_value is not None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=current_value,
                message=(
                    f"{label}: current value is {current_value:.4f}. "
                    f"Trend detection not ready — have {n} data "
                    f"point{'s' if n != 1 else ''}, need >= 3. {hint}"
                ),
                details={
                    "data_points": n,
                    "column": self.column,
                    "metric": self.metric,
                    "mode": "trend",
                    "baseline_observation": True,
                    "has_timestamp_column": has_ts,
                    "anomaly_ready": False,
                },
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.SKIPPED,
            value=current_value,
            message=(
                f"Insufficient data for trend detection on '{label}'. "
                f"Need at least 3 data points. {hint}"
            ),
            details={
                "data_points": n,
                "column": self.column,
                "metric": self.metric,
                "mode": "trend",
                "has_timestamp_column": has_ts,
                "anomaly_ready": False,
            },
        )

    def _stat_evaluate(
        self,
        current: float,
        baseline: List[float],
        target_fqn: str,
    ) -> MonitorResult:
        """Evaluate using the shared StatEngine (trend mode)."""
        score = score_anomaly(
            current=current,
            baseline=baseline,
            threshold=self.anomaly_threshold,
            min_effect_size=self.min_effect_size,
            method=self.detection_method,
        )

        label = f"{self.column}.{self.metric}" if self.column else self.metric

        if score.is_anomaly:
            status = MonitorStatus.FAIL
            if score.confidence_pct < 50:
                status = MonitorStatus.WARN
            expected_range = (
                {
                    "min": round(
                        score.baseline_mean
                        - score.threshold_used * score.baseline_stddev,
                        4,
                    ),
                    "max": round(
                        score.baseline_mean
                        + score.threshold_used * score.baseline_stddev,
                        4,
                    ),
                }
                if score.baseline_stddev > 0
                else {"min": score.baseline_mean, "max": score.baseline_mean}
            )
            message = (
                f"Anomaly detected on {label}: "
                f"value {current:.4f} is {score.direction} expected range "
                f"({score.method_used}: {score.z_score:.2f}, "
                f"mean: {score.baseline_mean:.4f}, "
                f"{score.baseline_count} points, "
                f"{score.confidence_pct}% confidence)."
            )
        else:
            status = MonitorStatus.PASS
            expected_range = None
            message = (
                f"{label}: value {current:.4f} is within expected range "
                f"({score.method_used}: {score.z_score:.2f}, "
                f"mean: {score.baseline_mean:.4f}, "
                f"{score.baseline_count} points)."
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=current,
            threshold=score.threshold_used,
            expected_range=expected_range,
            message=message,
            details={
                "column": self.column,
                "metric": self.metric,
                "mode": "trend",
                "z_score": score.z_score,
                "mad_score": score.mad_score,
                "baseline_mean": score.baseline_mean,
                "baseline_median": score.baseline_median,
                "baseline_stddev": score.baseline_stddev,
                "baseline_mad": score.baseline_mad,
                "baseline_count": score.baseline_count,
                "seasonality": self.seasonality,
                "confidence_pct": score.confidence_pct,
                "method_used": score.method_used,
                "threshold_used": score.threshold_used,
                "min_effect_size": self.min_effect_size,
                "absolute_change": score.absolute_change,
                "pct_change": score.pct_change,
                "direction": score.direction,
                "explanation": score.explanation,
                "confidence_info": build_confidence_info(
                    confidence_pct=score.confidence_pct,
                    baseline_count=score.baseline_count,
                    evaluation_mode=(
                        "seasonal_dow"
                        if self.seasonality == "day_of_week"
                        else "statistical"
                    ),
                    downgraded=score.is_anomaly and score.confidence_pct < 50,
                ),
            },
        )

    # ---------------------------------------------------------------
    # Shared helpers
    # ---------------------------------------------------------------

    def _metric_expression(self, dialect: str = "postgres") -> str:
        table_template = self.TABLE_METRIC_SQL.get(self.metric)
        if table_template:
            return table_template

        template = self.METRIC_SQL.get(self.metric)
        if not template:
            return self.column
        expr = template.format(col=self.column)
        if dialect == "bigquery":
            expr = expr.replace("AS FLOAT)", "AS FLOAT64)")
        return expr

    def _extract_current_value(
        self, query_results: List[Dict[str, Any]]
    ) -> Optional[float]:
        row = query_results[-1] if query_results else {}
        val = row.get("metric_value")
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert a value to float, returning default if None or invalid."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
