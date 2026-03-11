"""
Uniqueness monitor.

First-class monitor for column-level uniqueness/distinct-rate tracking.
Wraps AnomalyMonitor's statistical evaluation but adds:
- likely-key detection (auto-tightens threshold when all historical values > 0.99)
- trend direction analysis (detects gradual degradation)
- standardized confidence reporting

Uses the shared StatEngine for robust anomaly scoring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import (
    baseline_confidence,
    build_confidence_info,
    detrend_linear,
    score_anomaly,
)


class UniquenessMonitor(BaseMonitor):
    """
    Monitors column uniqueness (distinct rate) with key detection and trend analysis.

    Config keys:
        column : str
            Target column to monitor.
        anomaly_threshold : float
            Z-score threshold for anomaly detection (default: 3.0).
            Auto-tightened to 2.0 when likely_key is True.
        detection_method : str
            "auto" (default), "zscore", "mad", or "pct_change".
        likely_key : bool | None
            If True, column is treated as a key (tighter threshold).
            Auto-detected from history when None.
        historical_values : list[float] | None
            Pre-computed distinct_rate values for baseline.
        timestamp_column : str | None
            Column for time bucketing (default: None = single snapshot).
        lookback_days : int
            Number of days of history for baseline (default: 30).
    """

    monitor_type = "uniqueness"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.column: str = self.config.get("column", "")
        self.anomaly_threshold: float = float(
            self.config.get("anomaly_threshold", 3.0)
        )
        self.detection_method: str = self.config.get("detection_method", "auto")
        self.likely_key: Optional[bool] = self.config.get("likely_key")
        self.historical_values: Optional[List[float]] = self.config.get(
            "historical_values"
        )
        self.timestamp_column: Optional[str] = self.config.get("timestamp_column")
        self.lookback_days: int = int(self.config.get("lookback_days", 30))

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if not self.column or self.column == "*":
            raise ValueError(
                "UniquenessMonitor requires a specific 'column' in its config. "
                "Use column='*' with the scheduler for multi-column auto-discovery."
            )
        fqn = self._fqn(database, schema, table)

        float_type = "FLOAT64" if dialect == "bigquery" else "FLOAT"
        distinct_rate = (
            f"CAST(COUNT(DISTINCT {self.column}) AS {float_type}) "
            f"/ NULLIF(COUNT(*), 0)"
        )
        distinct_count = f"COUNT(DISTINCT {self.column})"
        total_count = "COUNT(*)"

        if self.timestamp_column:
            ts = self.timestamp_column
            if dialect == "bigquery":
                ts_date = f"CAST(CAST({ts} AS TIMESTAMP) AS DATE)"
                where = (
                    f"WHERE {ts_date} >= DATE_SUB(CURRENT_DATE(), "
                    f"INTERVAL {self.lookback_days} DAY)"
                ) if self.lookback_days > 0 else ""
                sql = (
                    f"SELECT {ts_date} AS bucket_date, "
                    f"{distinct_rate} AS metric_value, "
                    f"{distinct_count} AS distinct_count, "
                    f"{total_count} AS total_count "
                    f"FROM {fqn} {where} "
                    f"GROUP BY bucket_date ORDER BY bucket_date"
                )
                return sql
            else:
                where = (
                    f"WHERE {ts} >= CURRENT_DATE - INTERVAL '{self.lookback_days} days'"
                ) if self.lookback_days > 0 else ""
                sql = (
                    f"SELECT CAST({ts} AS DATE) AS bucket_date, "
                    f"{distinct_rate} AS metric_value, "
                    f"{distinct_count} AS distinct_count, "
                    f"{total_count} AS total_count "
                    f"FROM {fqn} {where} "
                    f"GROUP BY CAST({ts} AS DATE) ORDER BY bucket_date"
                )
        else:
            sql = (
                f"SELECT "
                f"{distinct_rate} AS metric_value, "
                f"{distinct_count} AS distinct_count, "
                f"{total_count} AS total_count "
                f"FROM {fqn}"
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
                message="No results returned from uniqueness query.",
            )

        # Build baseline from historical_values or time-series results
        baseline: Optional[List[float]] = None
        current: Optional[float] = None

        if self.historical_values and len(self.historical_values) >= 3:
            baseline = self.historical_values
            current = self._extract_value(query_results[-1])
        elif len(query_results) >= 3:
            values = [
                float(r["metric_value"])
                for r in query_results
                if r.get("metric_value") is not None
            ]
            if len(values) >= 3:
                current = values[-1]
                baseline = values[:-1]

        if current is None:
            current = self._extract_value(query_results[-1])

        if current is None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message="Could not extract current distinct rate.",
            )

        # Extract extra info from latest result
        latest = query_results[-1]
        distinct_count = latest.get("distinct_count")
        total_count = latest.get("total_count")

        if baseline is None or len(baseline) < 3:
            return self._insufficient_baseline(
                current, distinct_count, total_count, target_fqn, query_results
            )

        return self._stat_evaluate(
            current, baseline, distinct_count, total_count, target_fqn
        )

    def _stat_evaluate(
        self,
        current: float,
        baseline: List[float],
        distinct_count: Any,
        total_count: Any,
        target_fqn: str,
    ) -> MonitorResult:
        """Evaluate uniqueness using StatEngine with key detection and trend."""
        # Likely-key detection: if all historical values > 0.99, tighten threshold
        is_likely_key = self.likely_key
        if is_likely_key is None:
            is_likely_key = all(v > 0.99 for v in baseline)

        threshold = self.anomaly_threshold
        if is_likely_key:
            threshold = min(threshold, 2.0)

        score = score_anomaly(
            current=current,
            baseline=baseline,
            threshold=threshold,
            min_effect_size=0.01,
            method=self.detection_method,
        )

        # Trend analysis: linear slope of the distinct_rate series
        trend_direction = "stable"
        trend_slope = 0.0
        all_values = baseline + [current]
        if len(all_values) >= 5:
            trend_slope = self._compute_slope(all_values)
            if trend_slope < -0.001:
                trend_direction = "degrading"
            elif trend_slope > 0.001:
                trend_direction = "improving"

        confidence = score.confidence_pct
        eval_mode = "likely_key" if is_likely_key else "statistical"

        # Build details
        details: Dict[str, Any] = {
            "column": self.column,
            "distinct_count": distinct_count,
            "total_count": total_count,
            "distinct_rate": round(current, 6),
            "z_score": score.z_score,
            "mad_score": score.mad_score,
            "baseline_mean": score.baseline_mean,
            "baseline_stddev": score.baseline_stddev,
            "baseline_count": score.baseline_count,
            "confidence_pct": confidence,
            "method_used": score.method_used,
            "threshold_used": score.threshold_used,
            "direction": score.direction,
            "likely_key": is_likely_key,
            "trend_direction": trend_direction,
            "trend_slope": round(trend_slope, 6),
            "explanation": score.explanation,
            "confidence_info": build_confidence_info(
                confidence_pct=confidence,
                baseline_count=score.baseline_count,
                evaluation_mode=eval_mode,
                downgraded=score.is_anomaly and confidence < 50,
            ),
        }

        if score.is_anomaly:
            status = MonitorStatus.FAIL
            if confidence < 50:
                status = MonitorStatus.WARN

            msg = (
                f"Uniqueness anomaly on '{self.column}': "
                f"distinct rate {current:.4f} is {score.direction} expected "
                f"({score.method_used}: {score.z_score:.2f}, "
                f"mean: {score.baseline_mean:.4f}, "
                f"{score.baseline_count} points, "
                f"{confidence}% confidence)."
            )
            if is_likely_key:
                msg += " Column appears to be a key (threshold tightened to 2.0)."
            if trend_direction == "degrading":
                msg += (
                    f" Uniqueness is gradually degrading "
                    f"(slope: {trend_slope:.4f}/day)."
                )

            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=status,
                value=current,
                threshold=score.threshold_used,
                expected_range={
                    "min": round(
                        score.baseline_mean
                        - score.threshold_used * score.baseline_stddev,
                        6,
                    ),
                    "max": round(
                        score.baseline_mean
                        + score.threshold_used * score.baseline_stddev,
                        6,
                    ),
                }
                if score.baseline_stddev > 0
                else {"min": score.baseline_mean, "max": score.baseline_mean},
                message=msg,
                details=details,
            )

        msg = (
            f"Uniqueness on '{self.column}': distinct rate {current:.4f} "
            f"is within expected range "
            f"({score.method_used}: {score.z_score:.2f}, "
            f"mean: {score.baseline_mean:.4f}, "
            f"{score.baseline_count} points)."
        )
        if trend_direction == "degrading":
            msg += (
                f" Note: uniqueness is gradually degrading "
                f"(slope: {trend_slope:.4f}/day)."
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=current,
            message=msg,
            details=details,
        )

    def _insufficient_baseline(
        self,
        current: float,
        distinct_count: Any,
        total_count: Any,
        target_fqn: str,
        query_results: List[Dict[str, Any]],
    ) -> MonitorResult:
        """Not enough history for statistical evaluation."""
        n = len(query_results)
        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=current,
            message=(
                f"Uniqueness on '{self.column}': distinct rate {current:.4f}. "
                f"Anomaly detection not ready — have {n} data point(s), need >= 3."
            ),
            details={
                "column": self.column,
                "distinct_count": distinct_count,
                "total_count": total_count,
                "distinct_rate": round(current, 6),
                "data_points": n,
                "anomaly_ready": False,
            },
        )

    @staticmethod
    def _extract_value(row: Dict[str, Any]) -> Optional[float]:
        val = row.get("metric_value")
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _compute_slope(values: List[float]) -> float:
        """Compute linear regression slope (value per day)."""
        n = len(values)
        if n < 3:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return numerator / denominator
