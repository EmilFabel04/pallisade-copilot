"""
Volume monitor.

Checks row counts and detects anomalous volume changes using
the shared StatEngine (z-score, MAD, adaptive thresholds).

Supports three volume modes:
- "total": Simple total row count (for full-refresh tables)
- "period": Rows added per time bucket (for append-only tables)
- "auto": Auto-detects based on table behavior
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import score_anomaly, detrend_linear, build_confidence_info


class VolumeMonitor(BaseMonitor):
    """
    Monitors table volume (row count) against historical baselines.

    Uses the shared StatEngine for anomaly scoring with MAD robustness,
    confidence scaling, and minimum-effect-size filtering.

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
        volume_mode : str
            "total" (full row count), "period" (rows per bucket), or
            "auto" (auto-detect). Default: "auto".
        time_bucket_column : str | None
            Column to bucket by time for time-series volume analysis.
        time_bucket_interval : str
            Interval for time buckets (default: "1 day"). For daily mode,
            uses rolling 24-hour windows ending at NOW (not calendar days)
            so monitor runs at any time of day produce apples-to-apples
            comparisons against historical windows.
        lookback_days : int
            How many days of history to analyze (default: 30).
        detrend : bool
            Whether to remove linear trend before scoring (default: False).
            Useful for growing tables where volume increases steadily.
        detection_method : str
            "auto" (default), "zscore", "mad", or "pct_change".
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
        self.volume_mode: str = self.config.get("volume_mode", "auto")
        self.time_bucket_column: Optional[str] = self.config.get(
            "time_bucket_column"
        )
        self.detrend: bool = self.config.get("detrend", False)
        self.detection_method: str = self.config.get("detection_method", "auto")
        self.min_abs_delta: int = int(self.config.get("min_abs_delta", 10))
        self.min_rel_delta: float = float(self.config.get("min_rel_delta", 0.01))
        self.max_scan_days: int = int(self.config.get("max_scan_days", 90))
        self.lookback_days: int = min(
            int(self.config.get("lookback_days", 30)),
            self.max_scan_days,
        )
        self.seasonality: Optional[str] = self.config.get("seasonality")  # "day_of_week" or None
        self.time_bucket_interval: str = self.config.get("time_bucket_interval", "1 day")  # "1 day" or "1 hour" (opt-in)
        self.partition_column: Optional[str] = self.config.get("partition_column")

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        fqn = self._fqn(database, schema, table)

        if self.time_bucket_column:
            col = self.time_bucket_column
            is_hourly = self.time_bucket_interval == "1 hour"

            if dialect == "bigquery":
                if is_hourly:
                    # Hourly mode: still uses calendar hour buckets
                    bucket_expr = f"TIMESTAMP_TRUNC(CAST({col} AS TIMESTAMP), HOUR)"
                    bucket_alias = "bucket_ts"
                    sql = (
                        f"SELECT "
                        f"{bucket_expr} AS {bucket_alias}, "
                        f"COUNT(*) AS row_count "
                        f"FROM {fqn} "
                        f"WHERE {bucket_expr} >= "
                        f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.lookback_days} DAY) "
                        f"GROUP BY {bucket_alias} "
                        f"ORDER BY {bucket_alias}"
                    )
                    return sql

                # Daily mode: rolling 24-hour windows ending at NOW (not calendar days).
                # bucket_ts marks the end of each 24h window; bucket 0 is last 24h.
                days_ago_expr = (
                    f"DIV(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), "
                    f"CAST({col} AS TIMESTAMP), SECOND), 86400)"
                )
                sql = (
                    f"SELECT "
                    f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), "
                    f"INTERVAL {days_ago_expr} DAY) AS bucket_ts, "
                    f"CAST(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), "
                    f"INTERVAL {days_ago_expr} DAY) AS DATE) AS bucket_date, "
                    f"COUNT(*) AS row_count "
                    f"FROM {fqn} "
                    f"WHERE CAST({col} AS TIMESTAMP) >= "
                    f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.lookback_days} DAY) "
                    f"AND CAST({col} AS TIMESTAMP) < CURRENT_TIMESTAMP() "
                    f"GROUP BY bucket_ts, bucket_date "
                    f"ORDER BY bucket_ts"
                )
                return sql

            if is_hourly:
                bucket_expr = f"DATE_TRUNC('hour', {col})"
                bucket_alias = "bucket_ts"
                sql = (
                    f"SELECT "
                    f"{bucket_expr} AS {bucket_alias}, "
                    f"COUNT(*) AS row_count "
                    f"FROM {fqn} "
                    f"WHERE {col} >= NOW() - INTERVAL '{self.lookback_days} days' "
                    f"GROUP BY {bucket_expr} "
                    f"ORDER BY {bucket_alias}"
                )
            else:
                # Daily mode: rolling 24-hour windows ending at NOW.
                # Postgres/Snowflake/Redshift compatible form.
                days_ago_expr = (
                    f"FLOOR(EXTRACT(EPOCH FROM (NOW() - {col})) / 86400)"
                )
                sql = (
                    f"SELECT "
                    f"NOW() - INTERVAL '1 day' * {days_ago_expr} AS bucket_ts, "
                    f"CAST(NOW() - INTERVAL '1 day' * {days_ago_expr} AS DATE) AS bucket_date, "
                    f"COUNT(*) AS row_count "
                    f"FROM {fqn} "
                    f"WHERE {col} >= NOW() - INTERVAL '{self.lookback_days} days' "
                    f"AND {col} < NOW() "
                    f"GROUP BY bucket_ts, bucket_date "
                    f"ORDER BY bucket_ts"
                )
        elif self.partition_column:
            # Partition-aware: count per partition value
            pcol = self.partition_column
            if dialect == "bigquery" and pcol.upper() in ("_PARTITIONTIME", "_PARTITIONDATE"):
                pcol = "_PARTITIONDATE"
            sql = (
                f"SELECT {pcol} AS partition_value, COUNT(*) AS row_count "
                f"FROM {fqn} "
                f"GROUP BY {pcol} "
                f"ORDER BY {pcol}"
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
        elif self.partition_column and any("partition_value" in r for r in query_results):
            return self._evaluate_partitioned(query_results, target_fqn)
        else:
            return self._evaluate_simple(query_results, target_fqn)

    def _evaluate_simple(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        row_count = int(query_results[0].get("row_count", 0))

        # Zero-row detection: always FAIL if table is empty
        # (unless min_rows is explicitly set to 0)
        if row_count == 0 and self.min_rows != 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=0.0,
                message=(
                    "Table has 0 rows. This may indicate data was deleted "
                    "or an upstream pipeline failed to load."
                ),
                details={
                    "explanation": "Zero-row detection: table is empty.",
                },
            )

        # Explicit min/max threshold checks (user-configured guardrails).
        # Note: historical_mean/historical_stddev are daily volume stats and
        # must NOT be compared against total row counts here. Daily volume
        # anomaly detection happens in _evaluate_time_series instead.
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
                details={
                    "explanation": (
                        f"Row count {row_count:,} is below the configured "
                        f"minimum of {self.min_rows:,}."
                    ),
                },
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
                details={
                    "explanation": (
                        f"Row count {row_count:,} exceeds the configured "
                        f"maximum of {self.max_rows:,}."
                    ),
                },
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=float(row_count),
            message=f"Row count {row_count:,} is within expected range.",
            details={
                "explanation": f"Row count {row_count:,} is within configured thresholds.",
            },
        )

    def _evaluate_time_series(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        """Evaluate time-bucketed volume using the StatEngine."""
        if len(query_results) < 3:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.SKIPPED,
                message=(
                    "Insufficient historical data for time-series volume "
                    "analysis (need at least 3 data points)."
                ),
                details={
                    "data_points": len(query_results),
                    "explanation": (
                        f"Only {len(query_results)} daily buckets available. "
                        f"Need at least 3 for anomaly detection."
                    ),
                },
            )

        counts = [int(r.get("row_count", 0)) for r in query_results]
        latest = counts[-1]
        baseline = counts[:-1]

        # Weekday seasonality: filter baseline to same day-of-week as latest bucket
        seasonal_filtered = False
        if self.seasonality == "day_of_week" and len(query_results) >= 3:
            latest_row = query_results[-1]
            # Support both bucket_date (daily) and bucket_ts (hourly)
            bucket_val = latest_row.get("bucket_date") or latest_row.get("bucket_ts")
            if bucket_val is not None:
                try:
                    from datetime import datetime as _dt
                    if isinstance(bucket_val, str):
                        bucket_val = _dt.fromisoformat(bucket_val)
                    if isinstance(bucket_val, _dt):
                        target_dow = bucket_val.weekday()
                    else:
                        target_dow = bucket_val.weekday()  # date object

                    dow_baseline = []
                    for r in query_results[:-1]:
                        bd = r.get("bucket_date") or r.get("bucket_ts")
                        if bd is None:
                            continue
                        if isinstance(bd, str):
                            bd = _dt.fromisoformat(bd)
                        if isinstance(bd, _dt):
                            row_dow = bd.weekday()
                        else:
                            row_dow = bd.weekday()
                        if row_dow == target_dow:
                            dow_baseline.append(int(r.get("row_count", 0)))

                    if len(dow_baseline) >= 3:
                        baseline = dow_baseline
                        seasonal_filtered = True
                except (ValueError, TypeError, AttributeError):
                    pass  # Fall back to full baseline

        # Zero-row detection on latest bucket
        if latest == 0 and any(c > 0 for c in baseline):
            baseline_avg = sum(baseline) / len(baseline)
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=0.0,
                message=(
                    f"Latest daily volume is 0 rows (baseline average: "
                    f"{baseline_avg:,.0f}). This likely indicates a failed "
                    f"or missing data load."
                ),
                details={
                    "baseline_mean": round(baseline_avg, 2),
                    "data_points": len(counts),
                    "explanation": (
                        f"Zero rows in latest bucket vs baseline average of "
                        f"{baseline_avg:,.0f} rows/day over {len(baseline)} days."
                    ),
                },
            )

        # Daily threshold checks: min_rows/max_rows apply to daily volume
        if self.min_rows is not None and latest < self.min_rows:
            baseline_avg = sum(baseline) / len(baseline)
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=float(latest),
                threshold=float(self.min_rows),
                message=(
                    f"Daily volume {latest:,} is below the "
                    f"minimum threshold of {self.min_rows:,} rows/day."
                ),
                details={
                    "baseline_mean": round(baseline_avg, 2),
                    "data_points": len(counts),
                    "explanation": (
                        f"Latest daily volume ({latest:,} rows) is below "
                        f"the configured minimum of {self.min_rows:,} rows/day. "
                        f"Baseline average: {baseline_avg:,.0f} rows/day."
                    ),
                },
            )

        if self.max_rows is not None and latest > self.max_rows:
            baseline_avg = sum(baseline) / len(baseline)
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=float(latest),
                threshold=float(self.max_rows),
                message=(
                    f"Daily volume {latest:,} exceeds the "
                    f"maximum threshold of {self.max_rows:,} rows/day."
                ),
                details={
                    "baseline_mean": round(baseline_avg, 2),
                    "data_points": len(counts),
                    "explanation": (
                        f"Latest daily volume ({latest:,} rows) exceeds "
                        f"the configured maximum of {self.max_rows:,} rows/day. "
                        f"Baseline average: {baseline_avg:,.0f} rows/day."
                    ),
                },
            )

        # Optional detrending for growing tables
        scoring_baseline = baseline
        scoring_current = float(latest)
        if self.detrend and len(baseline) >= 5:
            all_values = baseline + [latest]
            detrended = detrend_linear(all_values)
            scoring_baseline = detrended[:-1]
            scoring_current = detrended[-1]

        # Use StatEngine for robust scoring
        score = score_anomaly(
            current=scoring_current,
            baseline=scoring_baseline,
            threshold=self.anomaly_threshold,
            min_effect_size=float(self.min_abs_delta),
            method=self.detection_method,
        )

        # Build result details
        raw_mean = sum(baseline) / len(baseline)
        eval_mode = "seasonal_dow" if seasonal_filtered else "time_series"
        details: Dict[str, Any] = {
            "z_score": score.z_score,
            "mad_score": score.mad_score,
            "baseline_mean": round(raw_mean, 2),
            "baseline_stddev": score.baseline_stddev,
            "baseline_count": score.baseline_count,
            "data_points": len(counts),
            "confidence_pct": score.confidence_pct,
            "method_used": score.method_used,
            "threshold_used": score.threshold_used,
            "direction": score.direction,
            "detrended": self.detrend,
            "seasonal_filtered": seasonal_filtered,
            "explanation": score.explanation,
            "confidence_info": build_confidence_info(
                confidence_pct=score.confidence_pct,
                baseline_count=score.baseline_count,
                evaluation_mode=eval_mode,
                downgraded=score.is_anomaly and score.confidence_pct < 50,
            ),
        }

        if score.is_anomaly:
            # Confidence-based downgrade
            status = MonitorStatus.FAIL
            if score.confidence_pct < 50:
                status = MonitorStatus.WARN

            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=status,
                value=float(latest),
                threshold=score.threshold_used,
                expected_range={
                    "min": round(
                        raw_mean - score.threshold_used * score.baseline_stddev, 0
                    ),
                    "max": round(
                        raw_mean + score.threshold_used * score.baseline_stddev, 0
                    ),
                }
                if score.baseline_stddev > 0
                else {"min": raw_mean, "max": raw_mean},
                message=(
                    f"Latest daily volume {latest:,} is anomalous "
                    f"({score.method_used}: {score.z_score:.2f}, "
                    f"baseline mean: {raw_mean:,.0f}, "
                    f"{score.confidence_pct}% confidence)."
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=float(latest),
            message=(
                f"Daily volume {latest:,} is within expected range "
                f"(baseline mean: {raw_mean:,.0f}, "
                f"{score.method_used}: {score.z_score:.2f})."
            ),
            details=details,
        )

    def _evaluate_partitioned(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        """Evaluate per-partition row counts. Returns worst status across partitions."""
        partition_issues: List[Dict[str, Any]] = []
        worst_status = MonitorStatus.PASS
        total_rows = 0

        for r in query_results:
            pval = r.get("partition_value", "unknown")
            count = int(r.get("row_count", 0))
            total_rows += count

            issue: Optional[Dict[str, Any]] = None
            if count == 0 and self.min_rows != 0:
                issue = {"partition": str(pval), "row_count": count, "reason": "empty partition"}
                worst_status = MonitorStatus.FAIL
            elif self.min_rows is not None and count < self.min_rows:
                issue = {"partition": str(pval), "row_count": count, "reason": f"below min_rows ({self.min_rows})"}
                worst_status = MonitorStatus.FAIL
            elif self.max_rows is not None and count > self.max_rows:
                issue = {"partition": str(pval), "row_count": count, "reason": f"above max_rows ({self.max_rows})"}
                worst_status = MonitorStatus.FAIL

            if issue:
                partition_issues.append(issue)

        details: Dict[str, Any] = {
            "partition_column": self.partition_column,
            "partition_count": len(query_results),
            "total_rows": total_rows,
            "partition_issues": partition_issues,
        }

        if partition_issues:
            issue_summary = "; ".join(
                f"{p['partition']}: {p['reason']} ({p['row_count']:,} rows)"
                for p in partition_issues[:5]
            )
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=worst_status,
                value=float(total_rows),
                message=(
                    f"{len(partition_issues)} partition issue(s): {issue_summary}"
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.PASS,
            value=float(total_rows),
            message=(
                f"All {len(query_results)} partitions within expected range "
                f"(total: {total_rows:,} rows)."
            ),
            details=details,
        )
