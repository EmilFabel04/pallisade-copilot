"""
Statistical anomaly monitor.

Implements Z-score anomaly detection for arbitrary column metrics —
null rates, distinct counts, min/max values, distribution statistics.
Supports seasonality via day-of-week bucketing.

This is the tech-agnostic equivalent of Elementary's anomaly detection
tests, but works against any warehouse Pallisade can connect to.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class AnomalyMonitor(BaseMonitor):
    """
    Detects statistical anomalies on column-level metrics.

    Config keys:
        column : str
            Target column to monitor.
        metric : str
            Metric to track. One of: "null_rate", "distinct_count",
            "distinct_rate", "min", "max", "avg", "sum", "stddev",
            "zero_rate".
        anomaly_threshold : float
            Z-score threshold (default: 3.0).
        seasonality : str | None
            Seasonality mode. "day_of_week" to compute baselines
            per weekday (default: None).
        lookback_days : int
            Number of days of history for baseline (default: 30).
        timestamp_column : str | None
            Column for time bucketing (default: None = single snapshot).
        historical_values : list[float] | None
            Pre-computed historical metric values for Z-score baseline.
    """

    monitor_type = "anomaly"

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

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.column: str = self.config.get("column", "")
        self.metric: str = self.config.get("metric", "null_rate")
        self.anomaly_threshold: float = float(
            self.config.get("anomaly_threshold", 3.0)
        )
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
        if not self.column:
            raise ValueError(
                "AnomalyMonitor requires a 'column' in its config. "
                "Example: config={'column': 'revenue', 'metric': 'null_rate'}"
            )
        fqn = self._fqn(database, schema, table)
        metric_expr = self._metric_expression(dialect)

        if self.timestamp_column and self.lookback_days:
            ts = self.timestamp_column

            if dialect == "bigquery":
                # BigQuery uses EXTRACT(DAYOFWEEK FROM ...) (not DOW)
                # and DATE_SUB / INTERVAL n DAY (not INTERVAL 'n days').
                # Double-cast via TIMESTAMP so STRING columns containing
                # ISO timestamps ('2024-04-21T06:54:03Z') are handled
                # correctly — CAST(string AS DATE) cannot parse them.
                ts_date = f"CAST(CAST({ts} AS TIMESTAMP) AS DATE)"
                dow_expr = f"EXTRACT(DAYOFWEEK FROM {ts_date})"
                where = (
                    f"WHERE {ts_date} >= DATE_SUB(CURRENT_DATE(), "
                    f"INTERVAL {self.lookback_days} DAY)"
                )
            else:
                dow_expr = f"EXTRACT(DOW FROM CAST({ts} AS DATE))"
                where = (
                    f"WHERE {ts} >= CURRENT_DATE "
                    f"- INTERVAL '{self.lookback_days} days'"
                )

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
            return self._zscore_evaluate(
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

                return self._zscore_evaluate(current, baseline, target_fqn)

        # Not enough data for Z-score — report the current value as a
        # baseline observation instead of skipping entirely.
        current_value = self._extract_current_value(query_results)
        label = f"{self.column}.{self.metric}"
        n = len(query_results)

        if current_value is not None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=current_value,
                message=(
                    f"{label}: current value is {current_value:.4f} "
                    f"(based on {n} data point{'s' if n != 1 else ''} — "
                    f"anomaly detection requires ≥ 3; "
                    f"reporting as baseline observation)."
                ),
                details={
                    "data_points": n,
                    "column": self.column,
                    "metric": self.metric,
                    "baseline_observation": True,
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
                f"Need at least 3 data points."
            ),
            details={
                "data_points": n,
                "column": self.column,
                "metric": self.metric,
            },
        )

    def _zscore_evaluate(
        self,
        current: float,
        baseline: List[float],
        target_fqn: str,
    ) -> MonitorResult:
        mean = sum(baseline) / len(baseline)
        variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
        stddev = math.sqrt(variance) if variance > 0 else 0.0

        if stddev == 0:
            is_anomaly = current != mean
            z_score = float("inf") if is_anomaly else 0.0
        else:
            z_score = (current - mean) / stddev
            is_anomaly = abs(z_score) > self.anomaly_threshold

        label = f"{self.column}.{self.metric}"

        if is_anomaly:
            direction = "above" if z_score > 0 else "below"
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=current,
                threshold=self.anomaly_threshold,
                expected_range={
                    "min": mean - self.anomaly_threshold * stddev,
                    "max": mean + self.anomaly_threshold * stddev,
                }
                if stddev > 0
                else {"min": mean, "max": mean},
                message=(
                    f"Anomaly detected on {label}: "
                    f"value {current:.4f} is {direction} expected range "
                    f"(z-score: {z_score:.2f}, mean: {mean:.4f})."
                ),
                details={
                    "column": self.column,
                    "metric": self.metric,
                    "z_score": round(z_score, 4),
                    "baseline_mean": round(mean, 4),
                    "baseline_stddev": round(stddev, 4),
                    "baseline_count": len(baseline),
                    "seasonality": self.seasonality,
                },
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=current,
            message=(
                f"{label}: value {current:.4f} is within expected range "
                f"(z-score: {z_score:.2f}, mean: {mean:.4f})."
            ),
            details={
                "column": self.column,
                "metric": self.metric,
                "z_score": round(z_score, 4),
                "baseline_mean": round(mean, 4),
                "baseline_stddev": round(stddev, 4),
                "baseline_count": len(baseline),
            },
        )

    def _metric_expression(self, dialect: str = "postgres") -> str:
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
