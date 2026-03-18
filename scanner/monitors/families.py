"""
Monitor Families — canonical recommendation layer.

This module is the single source of truth for monitor family definitions,
eligibility logic, and expansion. The existing presets.py delegates to
this module for consistency.

Monitor families are composable building blocks that map 1:1 to existing
watch types in scope.py. Users can select multiple families simultaneously
(e.g., pipeline_health + ingestion_reliability), and the system generates
topology-aware groups for each.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..lineage.graph import (
    AssetKind,
    LineageGraph,
    LineageNode,
    PlatformDomain,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MonitorFamilyDefinition:
    """Definition of a monitor family."""
    key: str
    label: str
    description: str
    eligible_domains: List[str]     # PlatformDomain values
    eligible_asset_kinds: List[str] # AssetKind values (empty = any)
    watch_type: str                 # Maps to scope.py watch type recipe
    is_meta: bool = False           # True for full_coverage (expands to all applicable)
    estimated_monitors: str = "6-12"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "eligible_domains": self.eligible_domains,
            "eligible_asset_kinds": self.eligible_asset_kinds,
            "watch_type": self.watch_type,
            "is_meta": self.is_meta,
            "estimated_monitors": self.estimated_monitors,
        }


@dataclass
class FamilyEligibility:
    """Eligibility result for a family given a scope."""
    family: MonitorFamilyDefinition
    eligible: bool
    matching_node_count: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.family.to_dict(),
            "eligible": self.eligible,
            "matching_node_count": self.matching_node_count,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Family definitions
# ---------------------------------------------------------------------------

MONITOR_FAMILIES: Dict[str, MonitorFamilyDefinition] = {
    "pipeline_health": MonitorFamilyDefinition(
        key="pipeline_health",
        label="Pipeline Health",
        description="Freshness, volume, and schema checks on warehouse tables and their upstream dependencies.",
        eligible_domains=["warehouse", "ingestion", "orchestration", "transform"],
        eligible_asset_kinds=[],
        watch_type="pipeline_health",
        estimated_monitors="8-12",
    ),
    "data_drift": MonitorFamilyDefinition(
        key="data_drift",
        label="Data Drift",
        description="Schema changes, null checks, uniqueness checks, and outlier detection across data assets.",
        eligible_domains=["warehouse", "transform", "ingestion"],
        eligible_asset_kinds=["table", "view", "model", "dataset"],
        watch_type="data_drift",
        estimated_monitors="6-10",
    ),
    "ingestion_reliability": MonitorFamilyDefinition(
        key="ingestion_reliability",
        label="Ingestion Reliability",
        description="Sync lag, failed syncs, and connector schema drift for ingestion sources.",
        eligible_domains=["ingestion"],
        eligible_asset_kinds=["connector"],
        watch_type="source_guard",
        estimated_monitors="3-6",
    ),
    "bi_reliability": MonitorFamilyDefinition(
        key="bi_reliability",
        label="BI Reliability",
        description="Dashboard freshness, content health, and upstream break risk for BI assets.",
        eligible_domains=["bi"],
        eligible_asset_kinds=["dashboard", "report", "workbook", "question", "explore"],
        watch_type="dashboard_shield",
        estimated_monitors="8-15",
    ),
    "model_quality": MonitorFamilyDefinition(
        key="model_quality",
        label="Model Quality",
        description="dbt test failures, model freshness, and source freshness checks.",
        eligible_domains=["transform"],
        eligible_asset_kinds=["model"],
        watch_type="model_quality",
        estimated_monitors="6-10",
    ),
    "ingestion_ops": MonitorFamilyDefinition(
        key="ingestion_ops",
        label="Ingestion Ops",
        description="Sync lag, failed syncs, and connector schema drift for ingestion tools (Fivetran, Airbyte, etc.).",
        eligible_domains=["ingestion"],
        eligible_asset_kinds=["connector", "job", "stream"],
        watch_type="ingestion_ops",
        estimated_monitors="3-6",
    ),
    "orchestration_ops": MonitorFamilyDefinition(
        key="orchestration_ops",
        label="Orchestration Ops",
        description="DAG run status, schedule lag, and task failure rates for orchestrators (Airflow, Dagster, Prefect).",
        eligible_domains=["orchestration"],
        eligible_asset_kinds=["job", "dag", "task", "pipeline"],
        watch_type="orchestration_ops",
        estimated_monitors="3-8",
    ),
    "transform_ops": MonitorFamilyDefinition(
        key="transform_ops",
        label="Transform Ops",
        description="dbt test failures, model freshness, and source freshness for transformation tools.",
        eligible_domains=["transform"],
        eligible_asset_kinds=["model", "job", "task"],
        watch_type="transform_ops",
        estimated_monitors="3-8",
    ),
    "warehouse_ops": MonitorFamilyDefinition(
        key="warehouse_ops",
        label="Warehouse Ops",
        description="Query performance, cost anomalies, and storage growth for data warehouses (Snowflake, BigQuery, Redshift).",
        eligible_domains=["warehouse"],
        eligible_asset_kinds=[],
        watch_type="warehouse_ops",
        estimated_monitors="3-6",
    ),
    "bi_ops": MonitorFamilyDefinition(
        key="bi_ops",
        label="BI Ops",
        description="Dashboard freshness, upstream break risk, content health, and refresh failures for BI tools.",
        eligible_domains=["bi"],
        eligible_asset_kinds=["dashboard", "report", "workbook", "question", "explore"],
        watch_type="bi_ops",
        estimated_monitors="4-8",
    ),
    "infrastructure_ops": MonitorFamilyDefinition(
        key="infrastructure_ops",
        label="Infrastructure Ops",
        description="Certificate expiry, server health (CPU/memory/disk), and log error analysis for Linux servers.",
        eligible_domains=["infrastructure", "other"],
        eligible_asset_kinds=[],
        watch_type="infrastructure_ops",
        estimated_monitors="3-6",
    ),
    "full_coverage": MonitorFamilyDefinition(
        key="full_coverage",
        label="Full Coverage",
        description="Enable all applicable monitor families for maximum coverage.",
        eligible_domains=[],  # Any
        eligible_asset_kinds=[],
        watch_type="full_pipeline",  # Used only if no other families match
        is_meta=True,
        estimated_monitors="15-40",
    ),
}


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def _count_matching_nodes(
    nodes: List[LineageNode],
    family: MonitorFamilyDefinition,
) -> int:
    """Count how many nodes match a family's eligible domains and asset kinds."""
    count = 0
    for node in nodes:
        domain_ok = (
            not family.eligible_domains
            or node.platform_domain.value in family.eligible_domains
        )
        kind_ok = (
            not family.eligible_asset_kinds
            or node.asset_kind.value in family.eligible_asset_kinds
        )
        if domain_ok and kind_ok:
            count += 1
    return count


def get_family_eligibility(
    scope_nodes: List[LineageNode],
    family_keys: Optional[List[str]] = None,
) -> List[FamilyEligibility]:
    """
    Check eligibility of monitor families for a given set of scope nodes.

    Args:
        scope_nodes: Nodes in the user-selected scope.
        family_keys: Optional filter — only check these families.
                     If None, checks all non-meta families.

    Returns:
        List of FamilyEligibility, one per family.
    """
    keys_to_check = family_keys or [
        k for k, f in MONITOR_FAMILIES.items() if not f.is_meta
    ]
    results = []

    for key in keys_to_check:
        family = MONITOR_FAMILIES.get(key)
        if not family:
            continue
        if family.is_meta:
            # Meta families are always eligible if any nodes exist
            results.append(FamilyEligibility(
                family=family,
                eligible=len(scope_nodes) > 0,
                matching_node_count=len(scope_nodes),
                reason="" if scope_nodes else "No assets in scope",
            ))
            continue

        matching = _count_matching_nodes(scope_nodes, family)
        eligible = matching > 0
        reason = "" if eligible else f"No {'/'.join(family.eligible_domains)} assets in scope"

        results.append(FamilyEligibility(
            family=family,
            eligible=eligible,
            matching_node_count=matching,
            reason=reason,
        ))

    return results


def check_node_eligibility(node: LineageNode, family_key: str) -> bool:
    """Check if a specific node can serve as anchor for a given family."""
    family = MONITOR_FAMILIES.get(family_key)
    if not family:
        return False
    if family.is_meta:
        return True
    domain_ok = (
        not family.eligible_domains
        or node.platform_domain.value in family.eligible_domains
    )
    kind_ok = (
        not family.eligible_asset_kinds
        or node.asset_kind.value in family.eligible_asset_kinds
    )
    return domain_ok and kind_ok


# ---------------------------------------------------------------------------
# Family resolution & expansion
# ---------------------------------------------------------------------------

def expand_full_coverage(scope_nodes: List[LineageNode]) -> List[str]:
    """
    Expand the 'full_coverage' meta-family into all applicable concrete families.

    Returns family keys for every non-meta family that has at least one
    matching node in scope.
    """
    applicable = []
    for key, family in MONITOR_FAMILIES.items():
        if family.is_meta:
            continue
        if _count_matching_nodes(scope_nodes, family) > 0:
            applicable.append(key)
    return applicable


def resolve_families(
    selected_families: List[str],
    scope_nodes: List[LineageNode],
) -> List[str]:
    """
    Resolve selected family keys into concrete (non-meta) family keys.

    If 'full_coverage' is in the selection, it expands to all applicable
    concrete families. Deduplicates the result.

    Args:
        selected_families: Family keys selected by the user.
        scope_nodes: Nodes in scope for eligibility checking.

    Returns:
        Deduplicated list of concrete family keys.
    """
    concrete: List[str] = []
    seen: Set[str] = set()

    for key in selected_families:
        family = MONITOR_FAMILIES.get(key)
        if not family:
            logger.warning("[Families] Unknown family key: %s", key)
            continue

        if family.is_meta:
            expanded = expand_full_coverage(scope_nodes)
            for ek in expanded:
                if ek not in seen:
                    seen.add(ek)
                    concrete.append(ek)
        else:
            if key not in seen:
                seen.add(key)
                concrete.append(key)

    return concrete


def get_family_watch_type(family_key: str) -> Optional[str]:
    """Get the watch type that a family maps to."""
    family = MONITOR_FAMILIES.get(family_key)
    return family.watch_type if family else None


def get_all_families(
    scope_nodes: Optional[List[LineageNode]] = None,
) -> List[Dict[str, Any]]:
    """
    Return all family definitions with optional eligibility.

    Used by the GET /families API endpoint.
    """
    if scope_nodes is not None:
        eligibility = get_family_eligibility(scope_nodes)
        return [e.to_dict() for e in eligibility]

    return [f.to_dict() for f in MONITOR_FAMILIES.values()]
