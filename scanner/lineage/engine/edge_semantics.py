"""Semantic edge policy layer for Pipeline Overview.

Derives correct semanticType for tool→tool edges based on
(src_category, tgt_category, evidence_type) rather than lane adjacency.
Enforces constraints so nonsensical labels (e.g. "BigQuery orchestrates dbt")
are impossible.
"""

from __future__ import annotations

import logging
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evidence type constants
# ---------------------------------------------------------------------------

DATA_DERIVATION = "data_derivation"
JOB_ORCHESTRATION = "job_orchestration"
CODE_OWNERSHIP = "code_ownership"
HOSTING = "hosting"
MONITORING = "monitoring"
INFERRED_ADJACENCY = "inferred_adjacency"

# ---------------------------------------------------------------------------
# Category layer order (for tie-breaking direction)
# ---------------------------------------------------------------------------

CATEGORY_ORDER: Dict[str, int] = {
    "ingestion": 0,
    "warehouse": 1,
    "transformation": 2,
    "orchestration": 3,
    "reporting": 4,
    "quality": 5,
    "infrastructure": 6,
    "version_control": 7,
}

# ---------------------------------------------------------------------------
# Data-derivation rules: (src_category, tgt_category) → (code, label)
# ---------------------------------------------------------------------------

_DATA_DERIVATION_RULES: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("ingestion", "warehouse"): ("ingests", "Ingests"),
    ("warehouse", "transformation"): ("feeds", "Feeds"),
    ("transformation", "warehouse"): ("builds", "Builds"),
    ("warehouse", "reporting"): ("serves", "Serves"),
    ("transformation", "reporting"): ("serves", "Serves"),
    ("ingestion", "transformation"): ("ingests", "Ingests"),
}

# Targets that orchestration tools can orchestrate
_ORCHESTRATION_TARGETS: FrozenSet[str] = frozenset(
    {"ingestion", "transformation", "warehouse", "reporting"}
)

# Targets for code ownership
_CODE_TARGETS: FrozenSet[str] = frozenset(
    {"transformation", "orchestration", "warehouse", "reporting"}
)

# Targets for hosting
_HOSTING_TARGETS: FrozenSet[str] = frozenset(
    {"ingestion", "orchestration", "transformation", "warehouse", "reporting"}
)

# Targets for monitoring/quality
_MONITORING_TARGETS: FrozenSet[str] = frozenset(
    {"warehouse", "transformation", "orchestration", "reporting"}
)

# ---------------------------------------------------------------------------
# Lane-pair fallback for inferred adjacency (mirrors legacy logic)
# ---------------------------------------------------------------------------

_LANE_PAIR_MAP: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("ingestion", "warehouse_raw"): ("ingests", "Ingests"),
    ("ingestion", "warehouse_analytics"): ("ingests", "Ingests"),
    ("warehouse_raw", "transformation"): ("feeds", "Feeds"),
    ("transformation", "warehouse_analytics"): ("builds", "Builds"),
    ("transformation", "warehouse_raw"): ("builds", "Builds"),
    ("warehouse_analytics", "reporting"): ("serves", "Serves"),
    ("warehouse_raw", "reporting"): ("serves", "Serves"),
}

_DATA_FLOW = ("data_flow", "Data Flow")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_semantic_type(
    src_category: Optional[str],
    tgt_category: Optional[str],
    evidence_type: str,
    src_lane: Optional[str] = None,
    tgt_lane: Optional[str] = None,
) -> Tuple[str, str]:
    """Derive a semantic edge type from categories and evidence.

    Returns (semantic_type_code, display_label).
    """
    src_cat = (src_category or "").lower()
    tgt_cat = (tgt_category or "").lower()

    if evidence_type == DATA_DERIVATION:
        result = _DATA_DERIVATION_RULES.get((src_cat, tgt_cat))
        if result:
            return result
        return _DATA_FLOW

    if evidence_type == JOB_ORCHESTRATION:
        if src_cat == "orchestration" and tgt_cat in _ORCHESTRATION_TARGETS:
            return ("orchestrates", "Orchestrates")
        logger.debug(
            "Unexpected orchestration edge: %s → %s", src_cat, tgt_cat,
        )
        return _DATA_FLOW

    if evidence_type == CODE_OWNERSHIP:
        if src_cat == "version_control" and tgt_cat in _CODE_TARGETS:
            return ("manages_code_for", "Manages Code")
        return _DATA_FLOW

    if evidence_type == HOSTING:
        if src_cat == "infrastructure" and tgt_cat in _HOSTING_TARGETS:
            return ("hosts", "Hosts")
        return _DATA_FLOW

    if evidence_type == MONITORING:
        if src_cat == "quality" and tgt_cat in _MONITORING_TARGETS:
            return ("monitors", "Monitors")
        return _DATA_FLOW

    if evidence_type == INFERRED_ADJACENCY:
        # Fall back to lane-pair map (legacy behaviour)
        if src_lane and tgt_lane:
            result = _LANE_PAIR_MAP.get((src_lane, tgt_lane))
            if result:
                return result
            # Heuristic fallbacks
            if src_lane == "transformation" or tgt_lane == "transformation":
                if tgt_lane == "transformation":
                    return ("feeds", "Feeds")
                return ("builds", "Builds")
        return _DATA_FLOW

    # Unknown evidence type — safe fallback
    return _DATA_FLOW


def enforce_semantic_constraints(
    semantic_type: str,
    label: str,
    src_category: Optional[str],
    tgt_category: Optional[str],
    evidence_type: str,
) -> Tuple[str, str]:
    """Guardrail: downgrade invalid semantic labels to 'data_flow'.

    Returns (corrected_type, corrected_label).
    """
    src_cat = (src_category or "").lower()

    # Orchestrates must originate from ORCHESTRATION
    if semantic_type == "orchestrates" and src_cat != "orchestration":
        logger.warning(
            "Downgrade: '%s' invalid for src_category=%s; expected orchestration",
            semantic_type, src_cat,
        )
        return _DATA_FLOW

    # Hosts must originate from INFRASTRUCTURE
    if semantic_type == "hosts" and src_cat != "infrastructure":
        logger.warning(
            "Downgrade: '%s' invalid for src_category=%s; expected infrastructure",
            semantic_type, src_cat,
        )
        return _DATA_FLOW

    # Manages code must originate from VERSION_CONTROL
    if semantic_type == "manages_code_for" and src_cat != "version_control":
        logger.warning(
            "Downgrade: '%s' invalid for src_category=%s; expected version_control",
            semantic_type, src_cat,
        )
        return _DATA_FLOW

    # Monitors must originate from QUALITY
    if semantic_type == "monitors" and src_cat != "quality":
        logger.warning(
            "Downgrade: '%s' invalid for src_category=%s; expected quality",
            semantic_type, src_cat,
        )
        return _DATA_FLOW

    # Data-flow verbs require data_derivation evidence
    if semantic_type in ("ingests", "feeds", "builds", "serves"):
        if evidence_type not in (DATA_DERIVATION, INFERRED_ADJACENCY):
            logger.warning(
                "Downgrade: '%s' requires data_derivation evidence, got %s",
                semantic_type, evidence_type,
            )
            return _DATA_FLOW

    return (semantic_type, label)
