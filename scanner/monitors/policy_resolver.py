"""
Pipeline Monitoring Policy Resolver.

Centralized policy resolution logic. All policy precedence decisions live here —
no duplication in recommender, scope, or UI.

Resolution chain (field-by-field, first non-null wins):
1. Direct assignment override — per-node overrides JSON
2. Direct assignment profile — linked PolicyProfile values
3. Branch assignment — nearest ancestor's branch policy wins
4. Auto-discovered — inferred from warehouse history analysis
5. Criticality default — matches node domain + criticality
6. Domain default — matches node domain
7. Built-in fallback — hardcoded defaults
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EffectivePolicy — the resolved policy for a single node
# ---------------------------------------------------------------------------

@dataclass
class EffectivePolicy:
    """Resolved monitoring policy for a node, after applying the full resolution chain."""

    # Where this policy came from
    source: str = "builtin"  # direct_override | direct_profile | imported_dbt | branch | auto_discovered | criticality_default | domain_default | builtin
    profile_id: Optional[str] = None
    profile_name: Optional[str] = None

    # --- Freshness ---
    freshness_enabled: Optional[bool] = None
    freshness_max_hours: Optional[int] = None
    freshness_warning_hours: Optional[int] = None

    # --- Schema ---
    schema_enabled: Optional[bool] = None
    schema_strictness: Optional[str] = None       # "strict" | "warn" | "ignore"
    schema_allow_evolution: Optional[bool] = None

    # --- Volume ---
    volume_enabled: Optional[bool] = None
    volume_min_rows: Optional[int] = None
    volume_max_rows: Optional[int] = None
    volume_growth_threshold: Optional[float] = None

    # --- Anomaly ---
    anomaly_enabled: Optional[bool] = None
    anomaly_sensitivity: Optional[float] = None    # 0.0–1.0
    anomaly_lookback_days: Optional[int] = None

    # --- Quality ---
    quality_enabled: Optional[bool] = None
    quality_max_null_rate: Optional[float] = None
    quality_max_duplicate_rate: Optional[float] = None

    # --- Ingestion-specific ---
    sync_lag_tolerance_minutes: Optional[int] = None
    failure_tolerance: Optional[str] = None        # "strict" | "normal" | "relaxed"
    schema_drift_strictness: Optional[str] = None  # "strict" | "warn" | "ignore"

    # --- BI-specific ---
    bi_freshness_hours: Optional[int] = None
    content_health_enabled: Optional[bool] = None
    upstream_break_strictness: Optional[str] = None  # "strict" | "warn" | "ignore"
    refresh_failure_alerting: Optional[bool] = None

    # --- Orchestration-specific ---
    run_latency_minutes: Optional[int] = None
    schedule_lag_minutes: Optional[int] = None
    orch_failure_tolerance: Optional[str] = None  # "strict" | "normal" | "relaxed"

    # --- Transform-specific ---
    test_failure_tolerance: Optional[str] = None  # "strict" | "normal" | "relaxed"
    model_freshness_hours: Optional[int] = None


# Fields that can be resolved (all Optional fields on EffectivePolicy except metadata)
_RESOLVABLE_FIELDS = [
    f.name for f in fields(EffectivePolicy)
    if f.name not in ("source", "profile_id", "profile_name")
]


# ---------------------------------------------------------------------------
# Built-in profile defaults
# ---------------------------------------------------------------------------

BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "Critical SLA": {
        "description": "Tight monitoring for business-critical assets",
        "criticality": "critical",
        "freshnessConfig": {"enabled": True, "maxHours": 2, "warningHours": 1},
        "schemaConfig": {"enabled": True, "strictness": "strict", "allowEvolution": False},
        "volumeConfig": {"enabled": True, "growthRateThreshold": 0.05, "minRows": 1},
        "anomalyConfig": {"enabled": True, "sensitivity": 0.99, "lookbackDays": 30},
        "qualityConfig": {"enabled": True, "maxNullRate": 0.01, "maxDuplicateRate": 0.005},
        "ingestionConfig": {"syncLagToleranceMinutes": 15, "failureTolerance": "strict", "schemaDriftStrictness": "strict"},
        "biConfig": {"freshnessHours": 2, "contentHealthEnabled": True, "upstreamBreakStrictness": "strict"},
        "orchestrationConfig": {"runLatencyMinutes": 15, "scheduleLagMinutes": 5, "failureTolerance": "strict"},
        "transformConfig": {"testFailureTolerance": "strict", "modelFreshnessHours": 2},
    },
    "Standard": {
        "description": "Balanced monitoring for standard-priority assets",
        "criticality": "medium",
        "freshnessConfig": {"enabled": True, "maxHours": 12, "warningHours": 6},
        "schemaConfig": {"enabled": True, "strictness": "warn", "allowEvolution": True},
        "volumeConfig": {"enabled": True, "growthRateThreshold": 0.15, "minRows": 1},
        "anomalyConfig": {"enabled": True, "sensitivity": 0.95, "lookbackDays": 14},
        "qualityConfig": {"enabled": True, "maxNullRate": 0.05, "maxDuplicateRate": 0.02},
        "ingestionConfig": {"syncLagToleranceMinutes": 60, "failureTolerance": "normal", "schemaDriftStrictness": "warn"},
        "biConfig": {"freshnessHours": 6, "contentHealthEnabled": True, "upstreamBreakStrictness": "warn"},
        "orchestrationConfig": {"runLatencyMinutes": 30, "scheduleLagMinutes": 15, "failureTolerance": "normal"},
        "transformConfig": {"testFailureTolerance": "normal", "modelFreshnessHours": 12},
    },
    "Relaxed": {
        "description": "Lenient monitoring for low-priority assets",
        "criticality": "low",
        "freshnessConfig": {"enabled": True, "maxHours": 48, "warningHours": 24},
        "schemaConfig": {"enabled": False, "strictness": "ignore", "allowEvolution": True},
        "volumeConfig": {"enabled": False},
        "anomalyConfig": {"enabled": False},
        "qualityConfig": {"enabled": True, "maxNullRate": 0.10, "maxDuplicateRate": 0.05},
        "ingestionConfig": {"syncLagToleranceMinutes": 180, "failureTolerance": "relaxed", "schemaDriftStrictness": "ignore"},
        "biConfig": {"freshnessHours": 24, "contentHealthEnabled": False, "upstreamBreakStrictness": "ignore"},
        "orchestrationConfig": {"runLatencyMinutes": 60, "scheduleLagMinutes": 30, "failureTolerance": "relaxed"},
        "transformConfig": {"testFailureTolerance": "relaxed", "modelFreshnessHours": 48},
    },
    "BI Shield": {
        "description": "Optimized for BI/reporting assets — focuses on freshness and upstream integrity",
        "targetDomain": "bi",
        "biConfig": {"freshnessHours": 4, "contentHealthEnabled": True, "upstreamBreakStrictness": "strict"},
        "freshnessConfig": {"enabled": True, "maxHours": 6, "warningHours": 4},
    },
    "Source Guard": {
        "description": "Optimized for ingestion assets — sync lag and schema drift focus",
        "targetDomain": "ingestion",
        "ingestionConfig": {"syncLagToleranceMinutes": 30, "failureTolerance": "strict", "schemaDriftStrictness": "strict"},
        "freshnessConfig": {"enabled": True, "maxHours": 4, "warningHours": 2},
    },
}

# Criticality → default built-in profile mapping
CRITICALITY_PROFILE_MAP: Dict[str, str] = {
    "critical": "Critical SLA",
    "high": "Critical SLA",
    "medium": "Standard",
    "low": "Relaxed",
}


def policy_for_node(
    node_criticality: str,
    node_domain: str = "warehouse",
    assignments: Optional[List[Dict[str, Any]]] = None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    node_fqn: Optional[str] = None,
) -> EffectivePolicy:
    """Quick policy resolution for a node, using DB assignments if available or builtin fallback.

    This is the primary entry point for the plan builder / recommender to get
    a node's policy without needing the full resolve_policy() machinery.
    """
    # If we have DB assignments, use the full resolver
    if assignments and profiles and node_fqn:
        return resolve_policy(
            node_fqn=node_fqn,
            node_domain=node_domain,
            node_criticality=node_criticality,
            assignments=assignments,
            profiles=profiles,
        )

    # Fallback: use built-in profile from criticality
    profile_name = CRITICALITY_PROFILE_MAP.get(node_criticality, "Standard")
    profile_config = BUILTIN_PROFILES.get(profile_name, BUILTIN_PROFILES["Standard"])

    policy = EffectivePolicy(
        source="builtin",
        profile_name=profile_name,
    )
    # Extract fields from the built-in profile config
    profile_fields = _extract_all_fields_from_profile(profile_config)
    for field_name, value in profile_fields.items():
        if hasattr(policy, field_name) and value is not None:
            setattr(policy, field_name, value)

    return policy


def build_policy_map(
    nodes: List[Any],
    assignments: Optional[List[Dict[str, Any]]] = None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, "EffectivePolicy"]:
    """Build a fqn → EffectivePolicy map for a list of lineage nodes.

    Used by plan_builder and scope to thread policies into config_hints.
    """
    policy_map: Dict[str, EffectivePolicy] = {}
    for node in nodes:
        fqn = getattr(node, "fqn", None) or ""
        criticality = getattr(node, "criticality", "medium") or "medium"
        domain = "warehouse"
        if hasattr(node, "platform_domain"):
            domain = getattr(node.platform_domain, "value", "warehouse")

        policy_map[fqn] = policy_for_node(
            node_criticality=criticality,
            node_domain=domain,
            assignments=assignments,
            profiles=profiles,
            node_fqn=fqn,
        )
    return policy_map


# ---------------------------------------------------------------------------
# Profile config → EffectivePolicy field extraction
# ---------------------------------------------------------------------------

def _extract_fields_from_config(config_json: Optional[Dict], config_key: str) -> Dict[str, Any]:
    """Extract EffectivePolicy fields from a profile's JSON config blob."""
    if not config_json:
        return {}

    mapping: Dict[str, Dict[str, str]] = {
        "freshnessConfig": {
            "enabled": "freshness_enabled",
            "maxHours": "freshness_max_hours",
            "warningHours": "freshness_warning_hours",
        },
        "schemaConfig": {
            "enabled": "schema_enabled",
            "strictness": "schema_strictness",
            "allowEvolution": "schema_allow_evolution",
        },
        "volumeConfig": {
            "enabled": "volume_enabled",
            "minRows": "volume_min_rows",
            "maxRows": "volume_max_rows",
            "growthRateThreshold": "volume_growth_threshold",
        },
        "anomalyConfig": {
            "enabled": "anomaly_enabled",
            "sensitivity": "anomaly_sensitivity",
            "lookbackDays": "anomaly_lookback_days",
        },
        "qualityConfig": {
            "enabled": "quality_enabled",
            "maxNullRate": "quality_max_null_rate",
            "maxDuplicateRate": "quality_max_duplicate_rate",
        },
        "ingestionConfig": {
            "syncLagToleranceMinutes": "sync_lag_tolerance_minutes",
            "failureTolerance": "failure_tolerance",
            "schemaDriftStrictness": "schema_drift_strictness",
        },
        "biConfig": {
            "freshnessHours": "bi_freshness_hours",
            "contentHealthEnabled": "content_health_enabled",
            "upstreamBreakStrictness": "upstream_break_strictness",
        },
        "orchestrationConfig": {
            "runLatencyMinutes": "run_latency_minutes",
            "scheduleLagMinutes": "schedule_lag_minutes",
            "failureTolerance": "orch_failure_tolerance",
        },
        "transformConfig": {
            "testFailureTolerance": "test_failure_tolerance",
            "modelFreshnessHours": "model_freshness_hours",
        },
    }

    field_map = mapping.get(config_key, {})
    result = {}
    for json_key, policy_field in field_map.items():
        if json_key in config_json and config_json[json_key] is not None:
            result[policy_field] = config_json[json_key]
    return result


def _extract_all_fields_from_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Extract all EffectivePolicy fields from a full profile dict."""
    result = {}
    config_keys = [
        "freshnessConfig", "schemaConfig", "volumeConfig", "anomalyConfig",
        "qualityConfig", "ingestionConfig", "biConfig", "orchestrationConfig",
        "transformConfig",
    ]
    for ck in config_keys:
        config_blob = profile.get(ck)
        if config_blob and isinstance(config_blob, dict):
            result.update(_extract_fields_from_config(config_blob, ck))
    return result


# ---------------------------------------------------------------------------
# Branch distance calculation
# ---------------------------------------------------------------------------

def _compute_branch_distances(
    node_fqn: str,
    branch_assignments: List[Dict[str, Any]],
    graph: Any,
) -> List[Tuple[Dict[str, Any], int]]:
    """
    For each branch assignment, compute graph distance from branchRootFqn to node_fqn.
    Returns list of (assignment, distance) sorted by distance ASC, then branchRootFqn ASC.
    Only includes assignments where the node is actually downstream of the root.
    """
    results = []

    for assignment in branch_assignments:
        root_fqn = assignment.get("branchRootFqn")
        if not root_fqn or not graph:
            continue

        # Find the root node ID in the graph
        root_node_id = None
        for nid, node in graph.nodes.items():
            if node.fqn == root_fqn:
                root_node_id = nid
                break
        if root_node_id is None:
            continue

        # BFS downstream from root to find target node and distance
        visited = {root_node_id: 0}
        queue = deque([root_node_id])
        found_distance = None

        while queue:
            current_id = queue.popleft()
            current_depth = visited[current_id]

            # Check if this is the target
            current_node = graph.nodes.get(current_id)
            if current_node and current_node.fqn == node_fqn and current_id != root_node_id:
                found_distance = current_depth
                break

            # Traverse downstream edges
            for edge in graph.edges.values():
                if edge.source_id == current_id and edge.target_id not in visited:
                    visited[edge.target_id] = current_depth + 1
                    queue.append(edge.target_id)

        if found_distance is not None:
            results.append((assignment, found_distance))

    # Sort: nearest first, then alphabetical by branchRootFqn for determinism
    results.sort(key=lambda x: (x[1], x[0].get("branchRootFqn", "")))
    return results


# ---------------------------------------------------------------------------
# Main resolution function
# ---------------------------------------------------------------------------

def resolve_policy(
    node_fqn: str,
    node_domain: str,
    node_criticality: str,
    assignments: List[Dict[str, Any]],
    profiles: Dict[str, Dict[str, Any]],
    graph: Any = None,
) -> EffectivePolicy:
    """
    Resolve the effective monitoring policy for a node.

    Args:
        node_fqn: Fully qualified name of the node
        node_domain: Platform domain ("warehouse", "ingestion", "bi", "orchestration", "transform")
        node_criticality: Criticality level ("critical", "high", "medium", "low")
        assignments: All PolicyAssignment records for the organization (as dicts)
        profiles: Profile ID → profile dict mapping
        graph: Optional LineageGraph for branch distance calculation

    Returns:
        EffectivePolicy with all resolved fields and source attribution
    """
    policy = EffectivePolicy()

    # Build the resolution layers (ordered by precedence)
    layers: List[Tuple[str, Dict[str, Any], Optional[str], Optional[str]]] = []
    # Each tuple: (source_label, field_values, profile_id, profile_name)

    # Direct assignment (override + profile)
    direct_assignments = [
        a for a in assignments
        if a.get("assignmentType") == "direct" and a.get("nodeFqn") == node_fqn
    ]
    if direct_assignments:
        da = direct_assignments[0]  # At most one per uniqueness constraint
        profile = profiles.get(da.get("profileId", ""), {})
        pid = da.get("profileId")
        pname = profile.get("name")

        # Override layer
        overrides = da.get("overrides")
        if overrides and isinstance(overrides, dict):
            override_fields = _extract_all_fields_from_profile(overrides)
            if override_fields:
                layers.append(("direct_override", override_fields, pid, pname))

        # Profile layer
        profile_fields = _extract_all_fields_from_profile(profile)
        if profile_fields:
            layers.append(("direct_profile", profile_fields, pid, pname))

    # Layer 4: Branch assignment (nearest ancestor wins)
    branch_assignments = [
        a for a in assignments
        if a.get("assignmentType") == "branch"
    ]
    if branch_assignments and graph:
        ranked = _compute_branch_distances(node_fqn, branch_assignments, graph)
        if ranked:
            nearest_assignment, _ = ranked[0]
            profile = profiles.get(nearest_assignment.get("profileId", ""), {})
            pid = nearest_assignment.get("profileId")
            pname = profile.get("name")

            # Branch overrides
            overrides = nearest_assignment.get("overrides")
            if overrides and isinstance(overrides, dict):
                override_fields = _extract_all_fields_from_profile(overrides)
                if override_fields:
                    layers.append(("branch", override_fields, pid, pname))

            # Branch profile
            profile_fields = _extract_all_fields_from_profile(profile)
            if profile_fields:
                layers.append(("branch", profile_fields, pid, pname))

    # Layer 5: Auto-discovered (from warehouse history analysis)
    auto_discovered_assignments = [
        a for a in assignments
        if a.get("assignmentType") == "auto_discovered"
        and a.get("nodeFqn") == node_fqn
    ]
    if auto_discovered_assignments:
        ad = auto_discovered_assignments[0]
        profile = profiles.get(ad.get("profileId", ""), {})
        pid = ad.get("profileId")
        pname = profile.get("name")
        profile_fields = _extract_all_fields_from_profile(profile)
        if profile_fields:
            layers.append(("auto_discovered", profile_fields, pid, pname))

    # Layer 6: Criticality default
    crit_defaults = [
        a for a in assignments
        if a.get("assignmentType") == "criticality_default"
        and a.get("nodeDomain") == node_domain
        and a.get("nodeCriticality") == node_criticality
    ]
    if crit_defaults:
        cd = crit_defaults[0]
        profile = profiles.get(cd.get("profileId", ""), {})
        pid = cd.get("profileId")
        pname = profile.get("name")
        profile_fields = _extract_all_fields_from_profile(profile)
        if profile_fields:
            layers.append(("criticality_default", profile_fields, pid, pname))

    # Layer 7: Domain default
    domain_defaults = [
        a for a in assignments
        if a.get("assignmentType") == "domain_default"
        and a.get("nodeDomain") == node_domain
        and not a.get("nodeCriticality")
    ]
    if domain_defaults:
        dd = domain_defaults[0]
        profile = profiles.get(dd.get("profileId", ""), {})
        pid = dd.get("profileId")
        pname = profile.get("name")
        profile_fields = _extract_all_fields_from_profile(profile)
        if profile_fields:
            layers.append(("domain_default", profile_fields, pid, pname))

    # Layer 8: Built-in fallback (use criticality mapping)
    builtin_name = CRITICALITY_PROFILE_MAP.get(node_criticality, "Standard")
    builtin_profile = BUILTIN_PROFILES.get(builtin_name, {})
    builtin_fields = _extract_all_fields_from_profile(builtin_profile)
    if builtin_fields:
        layers.append(("builtin", builtin_fields, None, builtin_name))

    # --- Merge layers: field-by-field, first non-null wins ---
    source_set = False
    for layer_source, layer_fields, layer_pid, layer_pname in layers:
        for field_name in _RESOLVABLE_FIELDS:
            current_val = getattr(policy, field_name)
            if current_val is None and field_name in layer_fields:
                setattr(policy, field_name, layer_fields[field_name])
                # Track the highest-precedence source that contributed
                if not source_set:
                    policy.source = layer_source
                    policy.profile_id = layer_pid
                    policy.profile_name = layer_pname
                    source_set = True

    return policy


# ---------------------------------------------------------------------------
# Bulk resolution
# ---------------------------------------------------------------------------

def resolve_policies_bulk(
    nodes: List[Dict[str, Any]],
    assignments: List[Dict[str, Any]],
    profiles: Dict[str, Dict[str, Any]],
    graph: Any = None,
) -> Dict[str, EffectivePolicy]:
    """
    Resolve effective policies for multiple nodes efficiently.

    Args:
        nodes: List of node dicts with at least {fqn, domain, criticality}
        assignments: All PolicyAssignment records for the org
        profiles: Profile ID → profile dict
        graph: Optional LineageGraph

    Returns:
        fqn → EffectivePolicy mapping
    """
    results = {}

    for node in nodes:
        fqn = node.get("fqn", "")
        domain = node.get("domain", "warehouse")
        criticality = node.get("criticality", "medium")

        results[fqn] = resolve_policy(
            node_fqn=fqn,
            node_domain=domain,
            node_criticality=criticality,
            assignments=assignments,
            profiles=profiles,
            graph=graph,
        )

    return results


# ---------------------------------------------------------------------------
# Policy status determination (for UI badges)
# ---------------------------------------------------------------------------

def get_policy_status(
    node_fqn: str,
    assignments: List[Dict[str, Any]],
    graph: Any = None,
) -> str:
    """
    Determine the policy badge status for a node.

    Returns:
        "assigned" — direct assignment exists
        "override" — direct assignment with overrides exists
        "inherited" — covered by a branch assignment
        "none" — no explicit policy (uses defaults)
    """
    for a in assignments:
        if a.get("assignmentType") in ("direct", "auto_discovered") and a.get("nodeFqn") == node_fqn:
            # Node-level status is always "assigned" — customized values
            # within the profile are the user's SLA/SLO configuration, not
            # an override.  "Override" only applies at the monitor level when
            # a running monitor's config diverges from the policy rules.
            return "assigned"

    # Check branch coverage
    branch_assignments = [a for a in assignments if a.get("assignmentType") == "branch"]
    if branch_assignments and graph:
        ranked = _compute_branch_distances(node_fqn, branch_assignments, graph)
        if ranked:
            return "inherited"

    return "none"
