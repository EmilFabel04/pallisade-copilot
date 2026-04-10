"""
Freshness monitor.

Checks how recently a table was updated by examining a timestamp column
or warehouse metadata. Works across any SQL warehouse.

Supports two freshness modes:
- "ingestion": Checks when data was last loaded (ETL timestamps)
- "business_event": Checks when the latest business event occurred

Supports cadence-aware thresholds with separate weekday/weekend SLAs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import structlog
from typing import Any, Callable, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import baseline_confidence, build_confidence_info

logger = structlog.get_logger()


# Ingestion timestamp columns — indicate when data was loaded/synced.
_INGESTION_COLUMNS = [
    "_partitiontime",       # BigQuery partition pseudo-column (load time)
    "loaded_at",
    "_loaded_at",
    "ingested_at",
    "_ingested_at",
    "_etl_loaded_at",
    "_fivetran_synced",     # Fivetran sync timestamp
    "_airbyte_extracted_at",  # Airbyte extraction timestamp
]

# Business-event timestamp columns — indicate when the event happened.
_BUSINESS_EVENT_COLUMNS = [
    "created_at",
    "created",
    "inserted_at",
    "updated_at",
    "modified_at",
    "timestamp",
    "event_time",
    "event_timestamp",
    "occurred_at",
    "transaction_date",
]

# Combined priority list (ingestion first, then business-event).
_TIMESTAMP_COLUMN_PRIORITY = _INGESTION_COLUMNS + _BUSINESS_EVENT_COLUMNS


def _classify_column_mode(column_name: str) -> str:
    """Classify a timestamp column as ingestion or business_event."""
    lower = column_name.lower()
    for ingestion_col in _INGESTION_COLUMNS:
        if lower == ingestion_col:
            return "ingestion"
    return "business_event"


def build_discovery_query(
    database: str,
    schema: str,
    table: str,
    dialect: str = "postgres",
) -> str:
    """Query INFORMATION_SCHEMA to find all timestamp/datetime columns."""
    if dialect == "bigquery":
        return (
            f"SELECT column_name, data_type "
            f"FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = '{table}' "
            f"AND data_type IN ('TIMESTAMP', 'DATETIME', 'DATE')"
        )

    # Postgres / Snowflake / Redshift
    return (
        f"SELECT column_name, data_type "
        f"FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' "
        f"AND table_name = '{table}' "
        f"AND data_type IN "
        f"('timestamp with time zone', 'timestamp without time zone', "
        f"'timestamptz', 'timestamp', 'date', 'datetime', "
        f"'TIMESTAMP_LTZ', 'TIMESTAMP_NTZ', 'TIMESTAMP_TZ')"
    )


def _score_candidate(
    column_name: str,
    preferred_mode: Optional[str] = None,
    non_null_rate: Optional[float] = None,
    max_value: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a single timestamp candidate column.

    Returns a dict with column_name, mode, score (0-100), and reasoning.
    Score components:
    - Name priority (0-50): how well the name matches known conventions
    - Non-null rate (0-30): percentage of non-null values (higher = better)
    - Recency (0-20): how recent the MAX value is
    """
    lower = column_name.lower()
    mode = _classify_column_mode(column_name)
    reasons: List[str] = []

    # Name priority score (0-50)
    if preferred_mode == "ingestion":
        priority = _INGESTION_COLUMNS + _BUSINESS_EVENT_COLUMNS
    elif preferred_mode == "business_event":
        priority = _BUSINESS_EVENT_COLUMNS + _INGESTION_COLUMNS
    else:
        priority = _TIMESTAMP_COLUMN_PRIORITY

    name_score = 0.0
    for idx, known in enumerate(priority):
        if lower == known:
            # Higher position in list → higher score
            name_score = 50.0 * (1.0 - idx / max(len(priority), 1))
            reasons.append(f"Known {mode} column (rank {idx + 1}/{len(priority)})")
            break
    if name_score == 0:
        # Unknown column name — give partial credit for containing time-related words
        time_keywords = {"time", "date", "timestamp", "created", "updated", "at"}
        if any(kw in lower for kw in time_keywords):
            name_score = 10.0
            reasons.append("Contains time-related keyword")
        else:
            reasons.append("Unknown timestamp column name")

    # Non-null rate score (0-30)
    null_score = 0.0
    if non_null_rate is not None:
        null_score = 30.0 * non_null_rate
        if non_null_rate >= 0.99:
            reasons.append(f"Excellent non-null rate ({non_null_rate:.1%})")
        elif non_null_rate >= 0.9:
            reasons.append(f"Good non-null rate ({non_null_rate:.1%})")
        else:
            reasons.append(f"Low non-null rate ({non_null_rate:.1%})")
    else:
        null_score = 15.0  # assume decent if unknown

    # Recency score (0-20)
    recency_score = 10.0  # default if unknown
    if max_value:
        try:
            from datetime import datetime as _dt
            max_dt = _dt.fromisoformat(str(max_value).replace("Z", "+00:00"))
            if max_dt.tzinfo is None:
                max_dt = max_dt.replace(tzinfo=timezone.utc)
            hours_ago = (datetime.now(timezone.utc) - max_dt).total_seconds() / 3600
            if hours_ago <= 24:
                recency_score = 20.0
                reasons.append("Updated within last 24h")
            elif hours_ago <= 168:
                recency_score = 15.0
                reasons.append(f"Updated {hours_ago:.0f}h ago")
            elif hours_ago <= 720:
                recency_score = 8.0
                reasons.append(f"Updated {hours_ago / 24:.0f} days ago")
            else:
                recency_score = 2.0
                reasons.append(f"Stale — last value {hours_ago / 24:.0f} days ago")
        except (ValueError, TypeError):
            pass

    total_score = round(name_score + null_score + recency_score, 1)

    return {
        "column_name": column_name,
        "mode": mode,
        "score": total_score,
        "name_score": round(name_score, 1),
        "null_score": round(null_score, 1),
        "recency_score": round(recency_score, 1),
        "reasons": reasons,
    }


def discover_timestamp_candidates(
    query_func: Callable,
    database: str,
    schema: str,
    table: str,
    dialect: str = "postgres",
    preferred_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Discover and rank all timestamp columns in a table.

    Returns a list of scored candidates sorted by score (highest first).
    Each candidate dict has: column_name, mode, score, reasons.
    """
    sql = build_discovery_query(database, schema, table, dialect)
    try:
        rows = query_func(sql)
    except Exception as e:
        logger.warning(f"[Freshness] Discovery query failed: {e}")
        return []

    column_names = [r.get("column_name") for r in rows if r.get("column_name")]
    if not column_names:
        return []

    fqn = f"{database}.{schema}.{table}" if database else f"{schema}.{table}"
    if dialect == "bigquery":
        fqn = f"`{database}.{schema}.{table}`"

    candidates = []
    for col in column_names:
        non_null_rate = None
        max_value = None

        # Try to get stats for each column (non-null rate + MAX)
        try:
            if dialect == "bigquery":
                stats_sql = (
                    f"SELECT "
                    f"COUNTIF({col} IS NOT NULL) / COUNT(*) AS non_null_rate, "
                    f"CAST(MAX({col}) AS STRING) AS max_value "
                    f"FROM {fqn}"
                )
            else:
                stats_sql = (
                    f"SELECT "
                    f"CAST(SUM(CASE WHEN {col} IS NOT NULL THEN 1 ELSE 0 END) AS FLOAT) "
                    f"/ NULLIF(COUNT(*), 0) AS non_null_rate, "
                    f"CAST(MAX({col}) AS VARCHAR) AS max_value "
                    f"FROM {fqn}"
                )
            stats_rows = query_func(stats_sql)
            if stats_rows:
                r = stats_rows[0]
                if r.get("non_null_rate") is not None:
                    non_null_rate = float(r["non_null_rate"])
                max_value = r.get("max_value")
        except Exception:
            pass  # Score without stats

        scored = _score_candidate(
            col,
            preferred_mode=preferred_mode,
            non_null_rate=non_null_rate,
            max_value=max_value,
        )
        candidates.append(scored)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def discover_timestamp_column(
    query_func: Callable,
    database: str,
    schema: str,
    table: str,
    dialect: str = "postgres",
    preferred_mode: Optional[str] = None,
    return_candidates: bool = False,
) -> Any:
    """Run a discovery query and return the best timestamp column name.

    When return_candidates=True, returns a tuple of (best_column, all_candidates)
    so callers can store runner-up columns for transparency.
    """
    candidates = discover_timestamp_candidates(
        query_func, database, schema, table, dialect, preferred_mode
    )

    if not candidates:
        logger.warning(
            "[Freshness] No timestamp columns found",
            table=f"{database}.{schema}.{table}",
        )
        if return_candidates:
            return None, []
        return None

    best = candidates[0]["column_name"]
    mode = candidates[0]["mode"]
    logger.info(
        "[Freshness] Auto-detected timestamp column",
        column=best,
        mode=mode,
        score=candidates[0]["score"],
        candidates=[c["column_name"] for c in candidates],
        table=f"{database}.{schema}.{table}",
    )

    if return_candidates:
        return best, candidates
    return best


class FreshnessMonitor(BaseMonitor):
    """
    Monitors data freshness by measuring the time since the most recent
    row in a timestamp column.

    When no timestamp_column is configured, the caller should use
    discover_timestamp_column() to find the best column before running
    the monitor.

    Config keys:
        timestamp_column : str | None
            Column to check for recency.  When omitted, the executor
            auto-discovers the best timestamp column from the table schema.
        freshness_mode : str
            "ingestion" (check when data was loaded), "business_event"
            (check when event occurred), or "auto" (detect from column name).
            Default: "auto".
        max_hours : float
            Maximum acceptable age in hours (default: 24).
        warn_hours : float
            Warning threshold in hours (default: max_hours * 0.75).
        weekday_max_hours : float | None
            Max hours for weekdays (Mon-Fri). Overrides max_hours on weekdays.
        weekend_max_hours : float | None
            Max hours for weekends (Sat-Sun). Overrides max_hours on weekends.
    """

    monitor_type = "freshness"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        # Empty string or None → needs auto-detection before build_query()
        self._user_specified_column: bool = bool(self.config.get("timestamp_column"))
        self.timestamp_column: str = (
            self.config.get("timestamp_column") or ""
        )
        self.freshness_mode: str = self.config.get("freshness_mode", "auto")
        self.max_hours: float = float(self.config.get("max_hours", 24))
        self.warn_hours: float = float(
            self.config.get("warn_hours", self.max_hours * 0.75)
        )
        self.weekday_max_hours: Optional[float] = self.config.get("weekday_max_hours")
        self.weekend_max_hours: Optional[float] = self.config.get("weekend_max_hours")
        # Cadence-aware mode: learns update frequency from history
        self.cadence_aware: bool = self.config.get("cadence_aware", False)
        self.cadence_multiplier: float = float(
            self.config.get("cadence_multiplier", 2.0)
        )
        self.cadence_min_samples: int = int(
            self.config.get("cadence_min_samples", 5)
        )
        self.cadence_gaps: Optional[List[float]] = self.config.get("cadence_gaps")

    @property
    def needs_column_discovery(self) -> bool:
        return not self.timestamp_column

    def _effective_thresholds(self) -> tuple[float, float]:
        """Return (max_hours, warn_hours) based on current day of week.

        If weekday/weekend overrides are set, use them. Otherwise,
        fall back to the base max_hours/warn_hours.
        """
        now = datetime.now(timezone.utc)
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6

        if is_weekend and self.weekend_max_hours is not None:
            max_h = self.weekend_max_hours
        elif not is_weekend and self.weekday_max_hours is not None:
            max_h = self.weekday_max_hours
        else:
            max_h = self.max_hours

        # Warn at 75% of effective max
        warn_h = max_h * 0.75
        return max_h, warn_h

    def _resolved_mode(self) -> str:
        """Resolve freshness mode from config or column name."""
        if self.freshness_mode != "auto":
            return self.freshness_mode
        if self.timestamp_column:
            return _classify_column_mode(self.timestamp_column)
        return "auto"

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        fqn = self._fqn(database, schema, table)
        col = self.timestamp_column

        if not col:
            # Fallback if discovery wasn't run — use updated_at
            col = "updated_at"

        if dialect == "bigquery":
            return (
                f"SELECT "
                f"MAX({col}) AS last_value, "
                f"TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), "
                f"CAST(MAX({col}) AS TIMESTAMP), SECOND) / 3600.0 "
                f"AS hours_since_update, "
                f"COUNT(*) AS total_rows "
                f"FROM {fqn} "
                f"WHERE {col} IS NOT NULL"
            )

        sql = (
            f"SELECT "
            f"MAX({col}) AS last_value, "
            f"EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX({col}))) / 3600.0 "
            f"AS hours_since_update, "
            f"COUNT(*) AS total_rows "
            f"FROM {fqn} "
            f"WHERE {col} IS NOT NULL"
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
                message="No results returned from freshness query.",
            )

        row = query_results[0]
        total_rows = row.get("total_rows", 0)
        hours = row.get("hours_since_update")
        resolved_mode = self._resolved_mode()

        if hours is None:
            if not total_rows:
                # Empty table — nothing to check freshness against
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.SKIPPED,
                    message="Table is empty — no rows to check freshness against.",
                    details={
                        "timestamp_column": self.timestamp_column,
                        "freshness_mode": resolved_mode,
                        "total_rows": 0,
                    },
                )
            # Non-empty table but all NULLs in the timestamp column
            if self._user_specified_column:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.ERROR,
                    message=(
                        f"Column '{self.timestamp_column}' has no non-null values "
                        f"({total_rows} rows checked)."
                    ),
                    details={
                        "timestamp_column": self.timestamp_column,
                        "freshness_mode": resolved_mode,
                        "total_rows": total_rows,
                    },
                )
            else:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target_fqn,
                    status=MonitorStatus.SKIPPED,
                    message=(
                        f"Auto-detected column '{self.timestamp_column}' has no "
                        f"non-null values. Specify a timestamp_column manually."
                    ),
                    details={
                        "timestamp_column": self.timestamp_column,
                        "freshness_mode": resolved_mode,
                        "total_rows": total_rows,
                        "auto_detected": True,
                    },
                )

        hours = float(hours)
        max_h, warn_h = self._effective_thresholds()

        mode_label = {
            "ingestion": "Ingestion data",
            "business_event": "Business-event data",
        }.get(resolved_mode, "Data")

        # Cadence-aware check (before static thresholds)
        if self.cadence_aware and self.cadence_gaps and len(self.cadence_gaps) >= self.cadence_min_samples:
            cadence_result = self._evaluate_cadence(hours, target_fqn, resolved_mode, row, max_h, warn_h)
            if cadence_result is not None:
                return cadence_result

        if hours > max_h:
            status = MonitorStatus.FAIL
            message = (
                f"{mode_label} is {hours:.1f}h old, exceeding the "
                f"{max_h}h freshness SLA."
            )
        elif hours > warn_h:
            status = MonitorStatus.WARN
            message = (
                f"{mode_label} is {hours:.1f}h old, approaching the "
                f"{max_h}h freshness SLA."
            )
        else:
            status = MonitorStatus.PASS
            message = f"{mode_label} is {hours:.1f}h old. Within the {max_h}h SLA."

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            value=hours,
            threshold=max_h,
            expected_range={"min": 0, "max": max_h},
            message=message,
            details={
                "timestamp_column": self.timestamp_column,
                "freshness_mode": resolved_mode,
                "hours_since_update": round(hours, 2),
                "max_hours": max_h,
                "warn_hours": warn_h,
                "last_value": str(row.get("last_value", "")),
                "total_rows": row.get("total_rows"),
                "weekday_max_hours": self.weekday_max_hours,
                "weekend_max_hours": self.weekend_max_hours,
                "explanation": (
                    f"Checked {resolved_mode} freshness via column "
                    f"'{self.timestamp_column}'. Last value was {hours:.1f}h ago. "
                    f"Threshold: {max_h}h (warn: {warn_h}h)."
                ),
            },
        )

    def _evaluate_cadence(
        self,
        hours: float,
        target_fqn: str,
        resolved_mode: str,
        row: Dict[str, Any],
        max_h: float,
        warn_h: float,
    ) -> Optional[MonitorResult]:
        """Evaluate freshness against learned cadence pattern.

        The static threshold (max_h) acts as a hard ceiling — exceeding it is
        always a FAIL regardless of what cadence says.  Cadence provides early
        warnings when the pattern deviates but the SLA hasn't been breached yet.

        Returns a MonitorResult if cadence is violated, None to fall through
        to static threshold checks.
        """
        gaps = sorted(self.cadence_gaps)  # type: ignore[arg-type]
        median_gap = gaps[len(gaps) // 2]
        p95_idx = min(int(len(gaps) * 0.95), len(gaps) - 1)
        p95_gap = gaps[p95_idx]
        expected_max = median_gap * self.cadence_multiplier

        mode_label = {
            "ingestion": "Ingestion data",
            "business_event": "Business-event data",
        }.get(resolved_mode, "Data")

        cadence_details = {
            "timestamp_column": self.timestamp_column,
            "freshness_mode": resolved_mode,
            "hours_since_update": round(hours, 2),
            "cadence_aware": True,
            "learned_median_gap_hours": round(median_gap, 2),
            "learned_p95_gap_hours": round(p95_gap, 2),
            "cadence_multiplier": self.cadence_multiplier,
            "expected_max_hours": round(expected_max, 2),
            "static_max_hours": max_h,
            "cadence_samples": len(gaps),
            "last_value": str(row.get("last_value", "")),
            "total_rows": row.get("total_rows"),
            "confidence_info": build_confidence_info(
                confidence_pct=baseline_confidence(len(gaps)),
                baseline_count=len(gaps),
                evaluation_mode="cadence",
            ),
        }

        # Static SLA ceiling — always FAIL if breached, regardless of cadence
        if hours > max_h:
            message = (
                f"{mode_label} is {hours:.1f}h old, exceeding the "
                f"{max_h}h freshness SLA "
                f"(learned cadence: ~{median_gap:.1f}h)."
            )
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.FAIL,
                value=hours,
                threshold=max_h,
                expected_range={"min": 0, "max": max_h},
                message=message,
                details={
                    **cadence_details,
                    "explanation": (
                        f"Static SLA breach: {hours:.1f}h exceeds the "
                        f"{max_h}h threshold. Learned cadence "
                        f"(~{median_gap:.1f}h) does not override the SLA."
                    ),
                },
            )

        # Within learned cadence and within SLA — PASS
        if hours <= expected_max:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                value=hours,
                threshold=expected_max,
                expected_range={"min": 0, "max": round(expected_max, 1)},
                message=(
                    f"{mode_label} is {hours:.1f}h old. "
                    f"Within learned cadence of ~{median_gap:.1f}h "
                    f"(max: {expected_max:.1f}h)."
                ),
                details={
                    **cadence_details,
                    "explanation": (
                        f"Cadence-aware: expected update every "
                        f"~{median_gap:.1f}h (based on {len(gaps)} measurements). "
                        f"Current gap of {hours:.1f}h is within "
                        f"{self.cadence_multiplier}x the median "
                        f"({expected_max:.1f}h)."
                    ),
                },
            )

        # Exceeds cadence but still within static SLA — WARN
        message = (
            f"{mode_label} is {hours:.1f}h old, exceeding the learned "
            f"cadence of ~{median_gap:.1f}h "
            f"(expected max: {expected_max:.1f}h) "
            f"but within the {max_h}h SLA."
        )
        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=MonitorStatus.WARN,
            value=hours,
            threshold=expected_max,
            expected_range={"min": 0, "max": round(expected_max, 1)},
            message=message,
            details={
                **cadence_details,
                "explanation": (
                    f"Cadence-aware: expected update every "
                    f"~{median_gap:.1f}h (based on {len(gaps)} measurements). "
                    f"Current gap of {hours:.1f}h exceeds "
                    f"{self.cadence_multiplier}x the median "
                    f"({expected_max:.1f}h) but is within the "
                    f"{max_h}h static SLA."
                ),
            },
        )
