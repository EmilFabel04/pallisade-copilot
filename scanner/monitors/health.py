"""
Health Watch Aggregation.

Computes a weighted health score, groups failures by category,
and generates a human-readable health summary for a watch.

Score formula:
  score = Σ(weight × depth_mult × status_score) / Σ(weight × depth_mult) × 100

Thresholds:
  90-100 = healthy
  70-89  = degraded
  40-69  = at_risk
  0-39   = unhealthy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status scoring
# ---------------------------------------------------------------------------

STATUS_SCORE: Dict[str, float] = {
    "PASS": 1.0,
    "WARN": 0.5,
    "FAIL": 0.0,
    "ERROR": 0.0,
    "SKIPPED": 0.8,
    "RUNNING": 0.8,
}

DEPTH_MULTIPLIER: Dict[int, float] = {
    0: 2.0,   # Direct monitors on anchor
    1: 1.5,   # Immediate upstream
}
# Depth 2+ uses 1.0

PRIORITY_WEIGHT: Dict[int, float] = {
    1: 3.0,   # Critical priority
    2: 2.0,   # High priority
    3: 1.0,   # Medium priority
}
# Priority 4+ uses 0.5


# ---------------------------------------------------------------------------
# Monitor-type → failure category mapping
# ---------------------------------------------------------------------------

MONITOR_TYPE_TO_FAILURE_CATEGORY: Dict[str, str] = {
    "FRESHNESS": "stale_data",
    "DBT_MODEL_FRESHNESS": "stale_data",
    "DBT_SOURCE_FRESHNESS": "stale_data",
    "BI_FRESHNESS_PROXY": "stale_data",
    "SCHEMA_CHANGE": "schema_break",
    "CONNECTOR_SCHEMA_DRIFT": "schema_break",
    "SYNC_LAG": "ingestion_lag",
    "FAILED_SYNCS": "ingestion_lag",
    "DAG_LAST_RUN": "orchestration_failure",
    "DAG_SCHEDULE_LAG": "orchestration_failure",
    "TASK_FAILURE_RATE": "orchestration_failure",
    "VOLUME": "quality_anomaly",
    "NULL_RATE": "quality_anomaly",
    "UNIQUENESS": "quality_anomaly",
    "DISTRIBUTION": "quality_anomaly",
    "ANOMALY": "quality_anomaly",
    "REFERENTIAL": "quality_anomaly",
    "CUSTOM_SQL": "quality_anomaly",
    "BI_UPSTREAM_BREAK_RISK": "quality_anomaly",
    "BI_CONTENT_HEALTH": "quality_anomaly",
    "BI_REFRESH_FAILURE": "quality_anomaly",
    "DBT_TEST_FAILURES": "transform_failure",
}

FAILURE_CATEGORY_LABELS: Dict[str, str] = {
    "stale_data": "Stale Data",
    "schema_break": "Schema Break",
    "ingestion_lag": "Ingestion Lag",
    "orchestration_failure": "Orchestration Failure",
    "quality_anomaly": "Quality Anomaly",
    "transform_failure": "Transform Failure",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MonitorSignal:
    """A single monitor result used for health computation."""
    monitor_id: str
    monitor_name: str
    monitor_type: str
    target_fqn: str
    status: str            # PASS, FAIL, WARN, ERROR, SKIPPED
    message: Optional[str] = None
    depth: int = 0         # Depth from anchor (0 = direct)
    priority: int = 2      # Monitor priority (1=critical, 2=high, 3=medium)


@dataclass
class FailureGroup:
    """A group of related failing signals."""
    category: str
    severity: str          # "critical" | "warning"
    summary: str
    root_cause_hint: str
    signal_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "summary": self.summary,
            "rootCauseHint": self.root_cause_hint,
            "signalCount": self.signal_count,
        }


@dataclass
class HealthReport:
    """Complete health report for a watch."""
    health_score: float
    health_status: str     # healthy, degraded, at_risk, unhealthy
    summary: str
    direct_status: str     # pass, fail, mixed, none
    upstream_status: str   # pass, fail, mixed, none
    coverage_pct: float
    failure_groups: List[FailureGroup]
    computed_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthScore": self.health_score,
            "healthStatus": self.health_status,
            "summary": self.summary,
            "directStatus": self.direct_status,
            "upstreamStatus": self.upstream_status,
            "coveragePct": self.coverage_pct,
            "failureGroups": [fg.to_dict() for fg in self.failure_groups],
            "computedAt": self.computed_at,
        }


# ---------------------------------------------------------------------------
# Core: compute_health_score
# ---------------------------------------------------------------------------

def compute_health_score(signals: List[MonitorSignal]) -> float:
    """Compute weighted health score (0-100) from monitor signals.

    Each signal contributes:
      weight = priority_weight × depth_multiplier
      value  = weight × status_score

    Score = sum(values) / sum(weights) × 100
    """
    if not signals:
        return 100.0

    total_weighted_value = 0.0
    total_weight = 0.0

    for s in signals:
        status_val = STATUS_SCORE.get(s.status, 0.0)
        depth_mult = DEPTH_MULTIPLIER.get(s.depth, 1.0)
        prio_weight = PRIORITY_WEIGHT.get(s.priority, 0.5)

        weight = prio_weight * depth_mult
        total_weighted_value += weight * status_val
        total_weight += weight

    if total_weight == 0:
        return 100.0

    raw = (total_weighted_value / total_weight) * 100
    return round(raw, 1)


def health_status_from_score(score: float) -> str:
    """Map a numeric score to a health status label."""
    if score >= 90:
        return "healthy"
    if score >= 70:
        return "degraded"
    if score >= 40:
        return "at_risk"
    return "unhealthy"


# ---------------------------------------------------------------------------
# Failure grouping
# ---------------------------------------------------------------------------

def group_failures(signals: List[MonitorSignal]) -> List[FailureGroup]:
    """Group failing/warning signals by failure category."""
    failing = [s for s in signals if s.status in ("FAIL", "ERROR", "WARN")]
    if not failing:
        return []

    buckets: Dict[str, List[MonitorSignal]] = {}
    for s in failing:
        cat = MONITOR_TYPE_TO_FAILURE_CATEGORY.get(s.monitor_type, "quality_anomaly")
        buckets.setdefault(cat, []).append(s)

    groups = []
    for cat, cat_signals in buckets.items():
        has_critical = any(s.status in ("FAIL", "ERROR") for s in cat_signals)
        # Pick the deepest failing signal as root cause hint
        deepest = max(cat_signals, key=lambda s: s.depth)

        summary_parts = []
        for s in cat_signals[:3]:
            summary_parts.append(f"{s.monitor_name}: {s.status}")
        if len(cat_signals) > 3:
            summary_parts.append(f"+{len(cat_signals) - 3} more")

        groups.append(FailureGroup(
            category=cat,
            severity="critical" if has_critical else "warning",
            summary=", ".join(summary_parts),
            root_cause_hint=deepest.target_fqn or "unknown",
            signal_count=len(cat_signals),
        ))

    # Sort by severity (critical first) then signal count
    groups.sort(key=lambda g: (0 if g.severity == "critical" else 1, -g.signal_count))
    return groups


# ---------------------------------------------------------------------------
# Aggregate status helpers
# ---------------------------------------------------------------------------

def _aggregate_status(signals: List[MonitorSignal]) -> str:
    """Compute aggregate status from signals: pass, fail, mixed, none."""
    if not signals:
        return "none"
    statuses = {s.status for s in signals}
    has_fail = statuses & {"FAIL", "ERROR"}
    has_pass = "PASS" in statuses
    if has_fail and has_pass:
        return "mixed"
    if has_fail:
        return "fail"
    if "WARN" in statuses:
        return "mixed" if has_pass else "warn"
    if has_pass:
        return "pass"
    return "none"


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

def generate_summary(
    anchor_name: str,
    health_status: str,
    failure_groups: List[FailureGroup],
) -> str:
    """Generate a one-line health summary."""
    if not failure_groups:
        return f"{anchor_name} is {health_status}"

    top = failure_groups[0]
    cat_label = FAILURE_CATEGORY_LABELS.get(top.category, top.category.replace("_", " "))
    total_signals = sum(fg.signal_count for fg in failure_groups)

    if total_signals == 1:
        return f"{anchor_name} is {health_status}: {cat_label.lower()} detected"
    return f"{anchor_name} is {health_status}: {total_signals} signal{'s' if total_signals != 1 else ''} across {cat_label.lower()}"


# ---------------------------------------------------------------------------
# Public API: compute_health_report
# ---------------------------------------------------------------------------

def compute_health_report(
    signals: List[MonitorSignal],
    anchor_name: str,
    coverage_pct: float = 0.0,
) -> HealthReport:
    """Compute a complete health report from monitor signals.

    Args:
        signals: List of MonitorSignal from all monitors in the watch.
        anchor_name: Display name of the anchor asset.
        coverage_pct: Fraction of upstream nodes covered (0.0-1.0).

    Returns:
        HealthReport with score, status, summary, and failure groups.
    """
    score = compute_health_score(signals)
    status = health_status_from_score(score)
    failure_groups = group_failures(signals)

    direct_signals = [s for s in signals if s.depth == 0]
    upstream_signals = [s for s in signals if s.depth > 0]

    summary = generate_summary(anchor_name, status, failure_groups)

    return HealthReport(
        health_score=score,
        health_status=status,
        summary=summary,
        direct_status=_aggregate_status(direct_signals),
        upstream_status=_aggregate_status(upstream_signals),
        coverage_pct=coverage_pct,
        failure_groups=failure_groups,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )
