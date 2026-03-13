"""
Shared monitor-based health and coverage scoring utility (Python mirror).

Mirrors the TypeScript version in lib/monitor-scoring.ts.
Used by views.py for tool-level coverage if backend enrichment is needed.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Applicable monitor types per asset/tool category
# ---------------------------------------------------------------------------

APPLICABLE_MONITORS: Dict[str, List[str]] = {
    "warehouse": [
        "FRESHNESS",
        "VOLUME",
        "SCHEMA_CHANGE",
        "ANOMALY",
        "UNIQUENESS",
        "NULL_RATE",
        "REFERENTIAL",
    ],
    "bi": [
        "BI_FRESHNESS_PROXY",
        "BI_CONTENT_HEALTH",
        "BI_UPSTREAM_BREAK_RISK",
        "BI_REFRESH_FAILURE",
    ],
    "ingestion": [
        "SYNC_LAG",
        "FAILED_SYNCS",
        "CONNECTOR_SCHEMA_DRIFT",
    ],
    "orchestration": [
        "DAG_LAST_RUN",
        "DAG_SCHEDULE_LAG",
        "TASK_FAILURE_RATE",
    ],
    "dbt_transform": [
        "DBT_TEST_FAILURES",
        "DBT_MODEL_FRESHNESS",
        "DBT_SOURCE_FRESHNESS",
    ],
    "infra": [
        "SERVER_HEALTH",
        "CERTIFICATE",
        "LOG_ANALYSIS",
    ],
}

_WAREHOUSE_GOOD_THRESHOLD = 80  # percent

# Status → numeric score.  None means exclude from denominator.
_STATUS_SCORE: Dict[str, Optional[float]] = {
    "PASS": 100.0,
    "WARN": 50.0,
    "FAIL": 0.0,
    "ERROR": 0.0,
    "SKIPPED": None,
    "RUNNING": None,
}


# ---------------------------------------------------------------------------
# Category resolver
# ---------------------------------------------------------------------------

def resolve_asset_category(
    platform_domain: str = "",
    platform: str = "",
    layer: str = "",
) -> Optional[str]:
    """Map node metadata to an asset category key."""
    pd = platform_domain.lower()
    p = platform.lower()
    l = layer.upper()

    # Platform-domain first
    if pd in ("bi", "reporting"):
        return "bi"
    if pd == "ingestion":
        return "ingestion"
    if pd == "orchestration":
        return "orchestration"
    if pd in ("transform", "transformation"):
        return "dbt_transform"
    if pd == "warehouse":
        return "warehouse"
    if pd in ("infrastructure", "infra"):
        return "infra"

    # Fallback to layer
    if l == "REPORTING":
        return "bi"
    if l == "INGESTION":
        return "ingestion"
    if l == "ORCHESTRATION":
        return "orchestration"
    if l == "TRANSFORMATION":
        return "dbt_transform"
    if l == "WAREHOUSE":
        return "warehouse"
    if l == "INFRASTRUCTURE":
        return "infra"

    return None


# ---------------------------------------------------------------------------
# Health scoring
# ---------------------------------------------------------------------------

def compute_asset_health_score(
    statuses: List[Optional[str]],
) -> Tuple[Optional[float], str]:
    """
    Compute health score from latest monitor statuses.

    Returns (score, status_label).
    score is None when there are no stable signals.
    """
    if not statuses:
        return None, "unmonitored"

    total = 0.0
    count = 0
    for s in statuses:
        key = (s or "").upper()
        score = _STATUS_SCORE.get(key)
        if score is not None:
            total += score
            count += 1

    if count == 0:
        return None, "unmonitored"

    avg = round(total / count, 1)
    return avg, health_status_from_score(avg)


def health_status_from_score(score: float) -> str:
    if score >= 90:
        return "healthy"
    if score >= 70:
        return "degraded"
    if score >= 40:
        return "at_risk"
    return "unhealthy"


# ---------------------------------------------------------------------------
# Coverage scoring
# ---------------------------------------------------------------------------

def compute_asset_coverage(
    configured_types: Set[str],
    category: str,
) -> Dict:
    """
    Compute monitor coverage for an asset or tool category.

    Returns dict with coveragePct, coverageStatus, configured, available, missingTypes.
    """
    applicable = APPLICABLE_MONITORS.get(category, [])
    if not applicable:
        return {
            "coveragePct": 0,
            "coverageStatus": "none",
            "configured": 0,
            "available": 0,
            "missingTypes": [],
        }

    upper_configured = {t.upper() for t in configured_types}
    configured_count = sum(1 for t in applicable if t in upper_configured)
    available_count = len(applicable)
    pct = round(configured_count / available_count * 100, 1)

    missing = [t for t in applicable if t not in upper_configured]

    if configured_count == 0:
        status = "none"
    elif category == "warehouse":
        status = "good" if pct >= _WAREHOUSE_GOOD_THRESHOLD else "partial"
    else:
        status = "good" if pct >= 100 else "partial"

    return {
        "coveragePct": pct,
        "coverageStatus": status,
        "configured": configured_count,
        "available": available_count,
        "missingTypes": missing,
    }


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def compute_monitor_scoring(
    monitors: List[Dict],
    category: str,
) -> Dict:
    """
    Compute health + coverage for an asset or tool.

    Each monitor dict must have 'monitorType' and 'lastStatus' keys.
    """
    statuses = [m.get("lastStatus") for m in monitors]
    health_score, health_status = compute_asset_health_score(statuses)

    configured_types = {m["monitorType"].upper() for m in monitors if m.get("monitorType")}
    coverage = compute_asset_coverage(configured_types, category)

    return {
        "healthScore": health_score,
        "healthStatus": health_status,
        **coverage,
    }
