"""
Volume monitor.

Checks row counts and detects anomalous volume changes using
Z-score analysis (inspired by Elementary's approach but tech-agnostic).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus


class VolumeMonitor(BaseMonitor):
    """
    Monitors table volume (row count) against historical baselines.

    If historical data is provided in config, uses Z-score anomaly detection.
    Otherwise, falls back to simple min/max threshold checking.

    Config keys:
        min_rows : int | None
            Minimum acceptable row count (default: None = no minimum).
        max_rows : int | None
            Maximum acceptable row count (default: None = no maximum).
        anomaly_threshold : float
            Z-score threshold for anomaly detection (default: 3.0).
        historical_mean : float | None
            Historical mean row count for Z-score calculation.
        historical_stddev : float | None
            Historical standard deviation for Z-score calculation.
        time_bucket_column : str | None
            Column to bucket by time for time-series volume analysis.
        time_bucket_interval : str
            Interval for time buckets (default: "1 day").
        lookback_days : int
            How many days of history to analyze (default: 30).
    """

    monitor_type = "volume"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.min_rows: Optional[int] = self.config.get("min_rows")
        self.max_rows: Optional[int] = self.config.get("max_rows")
        self.anomaly_threshold: float = float(
            self.config.get("anomaly_threshold", 3.0)
        )
        self.historical_mean: Optional[float] = self.config.get("historical_mean")
        self.historical_stddev: Optional[float] = self.config.get(
            "historical_stddev"
        )
        self.time_bucket_column: Optional[str] = self.config.get(
            "time_bucket_column"
        )
        self.min_abs_delta: int = int(self.config.get("min_abs_delta", 10))
        self.min_rel_delta: float = float(self.config.get("min_rel_delta", 0.01))
        self.max_scan_days: int = int(self.config.get("max_scan_days", 90))
        self.lookback_days: int = min(
            int(self.config.get("lookback_days", 30)),
            self.max_scan_days,
        )

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        fqn = self._fqn(database, schema, table)

        if self.time_bucket_column:
            # Time-series volume: count rows per day for the lookback window.
            col = self.time_bucket_column

            if dialect == "bigquery":
                # Double-cast via TIMESTAMP so STRING/TIMESTAMP columns
                # can be compared against DATE without type mismatch.
                ts_date = f"CAST(CAST({col} AS TIMESTAMP) AS DATE)"
                sql = (
                    f"SELECT "
                    f"{ts_date} AS bucket_date, "
                    f"COUNT(*) AS row_count "
                    f"FROM {fqn} "
                    f"WHERE {ts_date} >= DATE_SUB(CURRENT_DATE(), "
                    f"INTERVAL {self.lookback_days} DAY) "
                    f"GROUP BY bucket_date "
                    f"ORDER BY bucket_date"
                )
                return sql

            sql = (
                f"SELECT "
                f"CAST({col} AS DATE) AS bucket_date, "
                f"COUNT(*) AS row_count "
                f"FROM {fqn} "
                f"WHERE {col} >= CURRENT_DATE - INTERVAL '{self.lookback_days} days' "
                f"GROUP BY CAST({col} AS DATE) "
                f"ORDER BY bucket_date"
            )
        else:
            # Simple total row count.
            sql = f"SELECT COUNT(*) AS row_count FROM {fqn}"

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
                message="No results returned from volume query.",
            )

        if self.time_bucket_column:
            return self._evaluate_time_series(query_results, target_fqn)
        else:
            return self._evaluate_simple(query_results, target_fqn)

    def _evaluate_simple(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        row_count = int(query_results[0].get("row_count", 0))

        # Z-score check if we have historical data.
        if (
            self.historical_mean is not None
            and self.historical_stddev is not None
            and self.historical_stddev > 0
        ):
            z_score = (row_count - self.historical_mean) / self.historical_stddev
            if abs(z_score) > self.anomaly_threshold:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.FAIL,
                    value=float(row_count),
                    threshold=self.anomaly_threshold,
                    expected_range={
                        "min": self.historical_mean
                        - self.anomaly_threshold * self.historical_stddev,
                        "max": self.historical_mean
                        + self.anomaly_threshold * self.historical_stddev,
                    },
                    message=(
                        f"Row count {row_count:,} is anomalous "
                        f"(z-score: {z_score:.2f}, "
                        f"expected ~{self.historical_mean:,.0f})."
                    ),
                    details={
                        "z_score": round(z_score, 3),
                        "historical_mean": self.historical_mean,
                        "historical_stddev": self.historical_stddev,
                    },
                )

        # Simple threshold check.
        if self.min_rows is not None and row_count < self.min_rows:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=float(row_count),
                threshold=float(self.min_rows),
                message=(
                    f"Row count {row_count:,} is below the "
                    f"minimum threshold of {self.min_rows:,}."
                ),
            )

        if self.max_rows is not None and row_count > self.max_rows:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=float(row_count),
                threshold=float(self.max_rows),
                message=(
                    f"Row count {row_count:,} exceeds the "
                    f"maximum threshold of {self.max_rows:,}."
                ),
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=float(row_count),
            message=f"Row count {row_count:,} is within expected range.",
        )

    def _evaluate_time_series(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        """Evaluate time-bucketed volume using inline Z-score analysis."""
        if len(query_results) < 3:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.SKIPPED,
                message=(
                    "Insufficient historical data for time-series volume "
                    "analysis (need at least 3 data points)."
                ),
                details={"data_points": len(query_results)},
            )

        counts = [int(r.get("row_count", 0)) for r in query_results]
        latest = counts[-1]

        # Use all except the latest as the baseline.
        baseline = counts[:-1]
        mean = sum(baseline) / len(baseline)
        variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
        stddev = math.sqrt(variance) if variance > 0 else 0

        if stddev == 0:
            # Constant volume — check if the change exceeds noise thresholds.
            abs_delta = abs(latest - mean)
            rel_delta = abs_delta / mean if mean > 0 else float("inf")
            if abs_delta >= self.min_abs_delta and rel_delta >= self.min_rel_delta:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.WARN,
                    value=float(latest),
                    message=(
                        f"Volume changed from constant {mean:.0f} "
                        f"to {latest:,} (delta: {abs_delta:.0f}, "
                        f"{rel_delta:.1%} change)."
                    ),
                    details={
                        "baseline_mean": mean,
                        "baseline_stddev": 0,
                        "abs_delta": abs_delta,
                        "rel_delta": round(rel_delta, 4),
                        "data_points": len(counts),
                    },
                )
        else:
            z_score = (latest - mean) / stddev
            if abs(z_score) > self.anomaly_threshold:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.FAIL,
                    value=float(latest),
                    threshold=self.anomaly_threshold,
                    expected_range={
                        "min": mean - self.anomaly_threshold * stddev,
                        "max": mean + self.anomaly_threshold * stddev,
                    },
                    message=(
                        f"Latest daily volume {latest:,} is anomalous "
                        f"(z-score: {z_score:.2f}, "
                        f"baseline mean: {mean:,.0f})."
                    ),
                    details={
                        "z_score": round(z_score, 3),
                        "baseline_mean": round(mean, 2),
                        "baseline_stddev": round(stddev, 2),
                        "data_points": len(counts),
                    },
                )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=float(latest),
            message=(
                f"Daily volume {latest:,} is within expected range "
                f"(baseline mean: {mean:,.0f})."
            ),
            details={
                "baseline_mean": round(mean, 2),
                "baseline_stddev": round(stddev, 2) if stddev else 0,
                "data_points": len(counts),
            },
        )
