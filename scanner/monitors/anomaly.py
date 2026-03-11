"""
Statistical anomaly monitor.

Implements anomaly detection for arbitrary column metrics —
null rates, distinct counts, min/max values, distribution statistics.
Supports seasonality via day-of-week bucketing.

Uses the shared StatEngine for robust z-score/MAD scoring,
confidence scaling, adaptive thresholds, and min-effect-size filtering.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import score_anomaly, build_confidence_info


# Default minimum absolute change by metric type.
# Rate metrics (0-1 scale) need a larger floor to avoid noise.
# Count metrics use 0 (any statistically significant change matters).
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
    Detects statistical anomalies on column-level metrics.

    Config keys:
        column : str
            Target column to monitor.
        metric : str
            Metric to track. One of: "null_rate", "distinct_count",
            "distinct_rate", "min", "max", "avg", "sum", "stddev",
            "zero_rate", "row_count".
        anomaly_threshold : float
            Z-score threshold (default: 3.0).
        min_effect_size : float | None
            Minimum absolute change to trigger anomaly. Prevents alerts
            on statistically significant but practically irrelevant changes.
            Default depends on metric type (0.01 for rates, 0 for counts).
        detection_method : str
            "auto" (default), "zscore", "mad", or "pct_change".
        seasonality : str | None
            Seasonality mode. "day_of_week" to compute baselines
            per weekday (default: None).
        lookback_days : int
            Number of days of history for baseline (default: 30).
        timestamp_column : str | None
            Column for time bucketing (default: None = single snapshot).
        historical_values : list[float] | None
            Pre-computed historical metric values for baseline.
    """

    monitor_type = "anomaly"

    # Metrics that work on ANY column type (string, numeric, etc.)
    ALL_COLUMN_METRICS = {"null_rate", "distinct_count", "distinct_rate"}
    # Metrics that require numeric columns only
    NUMERIC_ONLY_METRICS = {"min", "max", "avg", "sum", "stddev", "zero_rate"}

    # Metrics that require a column
    METRIC_SQL = {
        "null_rate": (
            "CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS FLOAT) "
            "/ NULLIF(COUNT(*), 0)"
        ),
        "distinct_count": "COUNT(DISTINCT {col})",
        "distinct_rate": (
            "CAST(COUNT(DISTINCT {col}) AS FLOAT) / NULLIF(COUNT(*), 0)"
        ),
        "min": "MIN(CAST({col} AS FLOAT))",
        "max": "MAX(CAST({col} AS FLOAT))",
        "avg": "AVG(CAST({col} AS FLOAT))",
        "sum": "SUM(CAST({col} AS FLOAT))",
        "stddev": "STDDEV(CAST({col} AS FLOAT))",
        "zero_rate": (
            "CAST(SUM(CASE WHEN {col} = 0 THEN 1 ELSE 0 END) AS FLOAT) "
            "/ NULLIF(COUNT(*), 0)"
        ),
    }

    # Table-level metrics (no column required)
    TABLE_METRIC_SQL = {
        "row_count": "COUNT(*)",
    }

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.column: str = self.config.get("column", "")
        # Default to row_count (table-level) when no column is specified,
        # avg (column-level) when a column is provided.
        default_metric = "row_count" if not self.column else "avg"
        self.metric: str = self.config.get("metric", default_metric)
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

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        is_table_metric = self.metric in self.TABLE_METRIC_SQL
        if not self.column and not is_table_metric:
            raise ValueError(
                "AnomalyMonitor requires a 'column' in its config for column-level metrics. "
                "Example: config={'column': 'revenue', 'metric': 'null_rate'}. "
                "For table-level metrics (row_count), column is not required."
            )
        fqn = self._fqn(database, schema, table)
        metric_expr = self._metric_expression(dialect)

        if self.timestamp_column:
            ts = self.timestamp_column

            if dialect == "bigquery":
                # BigQuery uses EXTRACT(DAYOFWEEK FROM ...) (not DOW)
                # and DATE_SUB / INTERVAL n DAY (not INTERVAL 'n days').
                # Double-cast via TIMESTAMP so STRING columns containing
                # ISO timestamps ('2024-04-21T06:54:03Z') are handled
                # correctly — CAST(string AS DATE) cannot parse them.
                ts_date = f"CAST(CAST({ts} AS TIMESTAMP) AS DATE)"
                dow_expr = f"EXTRACT(DAYOFWEEK FROM {ts_date})"
                if self.lookback_days and self.lookback_days > 0:
                    where = (
                        f"WHERE {ts_date} >= DATE_SUB(CURRENT_DATE(), "
                        f"INTERVAL {self.lookback_days} DAY)"
                    )
                else:
                    # lookback_days=0: no date filter — use all available data
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

            # Skip sqlglot transpilation for BigQuery — already native.
            if dialect == "bigquery":
                return sql
        else:
            # Single snapshot — current metric value only.
            sql = (
                f"SELECT {metric_expr} AS metric_value FROM {fqn}"
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
                message="No results returned from anomaly query.",
            )

        # If historical values are pre-computed, use them.
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

        # If we have time-series results, compute baseline inline.
        if len(query_results) >= 3:
            values = [
                float(r["metric_value"])
                for r in query_results
                if r.get("metric_value") is not None
            ]
            if len(values) >= 3:
                current = values[-1]
                baseline = values[:-1]

                # Handle seasonality by filtering baseline to same day-of-week.
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

        # Not enough data for anomaly detection — report the current value
        # as a baseline observation instead of skipping entirely.
        current_value = self._extract_current_value(query_results)
        label = f"{self.column}.{self.metric}" if self.column else self.metric
        n = len(query_results)

        has_ts = bool(self.timestamp_column)
        if has_ts:
            hint = (
                f"The table has fewer than 3 days of data in the last "
                f"{self.lookback_days} days for column '{self.timestamp_column}'. "
                f"Anomaly detection will activate automatically once more "
                f"historical data is available."
            )
        else:
            hint = (
                "No timestamp column was detected, so anomaly detection "
                "cannot backfill from historical data. To fix this, either: "
                "(1) specify a timestamp_column in the config so the monitor "
                "can query the last 30 days of history in one shot, or "
                "(2) set up a scheduled scan so the system collects daily "
                "snapshots and builds a baseline over time."
            )

        if current_value is not None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=current_value,
                message=(
                    f"{label}: current value is {current_value:.4f}. "
                    f"Anomaly detection is not ready yet — have {n} data "
                    f"point{'s' if n != 1 else ''}, need >= 3. {hint}"
                ),
                details={
                    "data_points": n,
                    "column": self.column,
                    "metric": self.metric,
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
                f"Insufficient historical data for anomaly detection on "
                f"'{label}' and could not extract current value. "
                f"Need at least 3 data points. {hint}"
            ),
            details={
                "data_points": n,
                "column": self.column,
                "metric": self.metric,
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
        """Evaluate using the shared StatEngine."""
        score = score_anomaly(
            current=current,
            baseline=baseline,
            threshold=self.anomaly_threshold,
            min_effect_size=self.min_effect_size,
            method=self.detection_method,
        )

        label = f"{self.column}.{self.metric}" if self.column else self.metric

        # Confidence-based auto-downgrade: low-confidence anomalies
        # become WARN instead of FAIL
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
                    evaluation_mode="seasonal_dow" if self.seasonality == "day_of_week" else "statistical",
                    downgraded=score.is_anomaly and score.confidence_pct < 50,
                ),
            },
        )

    def _metric_expression(self, dialect: str = "postgres") -> str:
        # Table-level metrics (no column needed)
        table_template = self.TABLE_METRIC_SQL.get(self.metric)
        if table_template:
            return table_template

        # Column-level metrics
        template = self.METRIC_SQL.get(self.metric)
        if not template:
            # Fall back to a raw column select.
            return self.column
        expr = template.format(col=self.column)
        # BigQuery uses FLOAT64 instead of FLOAT.
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
