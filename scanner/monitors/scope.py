"""
Group Monitor Scope Selection.

Given an anchor node and a watch type, selects which upstream nodes to monitor
and generates monitor recommendations, respecting depth, node, and monitor caps.

Algorithm:
  1. Bounded BFS via get_upstream_with_depth()
  2. Domain filter — remove nodes outside scopeConfig.domainFilters
  3. Priority scoring — closer + more critical + more connected = higher score
  4. Cap nodes at maxNodes
  5. Generate monitors per watch-type recipe
  6. Cap monitors at maxMonitors
  7. Compute coverage = monitored nodes / total upstream
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..lineage.graph import (
    AssetKind,
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from .recommender import (
    MonitorRecommendation,
    _build_config_hints,
    is_bi_node,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default scope configs per watch type (mirrors types/health-watch.ts)
# ---------------------------------------------------------------------------

DEFAULT_SCOPE = {
    "pipeline_health": {
        "maxDepth": 3,
        "maxNodes": 15,
        "maxMonitors": 12,
        "domainFilters": ["warehouse", "ingestion", "orchestration", "transform"],
    },
    "dashboard_shield": {
        "maxDepth": 4,
        "maxNodes": 20,
        "maxMonitors": 15,
        "domainFilters": ["warehouse", "ingestion", "transform", "orchestration"],
    },
    "source_guard": {
        "maxDepth": 1,
        "maxNodes": 5,
        "maxMonitors": 6,
        "domainFilters": ["ingestion", "warehouse"],
    },
    "model_quality": {
        "maxDepth": 2,
        "maxNodes": 10,
        "maxMonitors": 10,
        "domainFilters": ["transform", "warehouse", "ingestion"],
    },
    "custom_watch": {
        "maxDepth": 2,
        "maxNodes": 10,
        "maxMonitors": 8,
        "domainFilters": [],
    },
}


# ---------------------------------------------------------------------------
# Watch type inference
# ---------------------------------------------------------------------------

def infer_watch_type(node: LineageNode) -> str:
    """Auto-detect the best watch type for a given anchor node."""
    if is_bi_node(node):
        return "dashboard_shield"
    if node.platform_domain == PlatformDomain.INGESTION:
        return "source_guard"
    if node.platform_domain == PlatformDomain.TRANSFORM and node.asset_kind == AssetKind.MODEL:
        return "model_quality"
    if node.platform_domain == PlatformDomain.WAREHOUSE:
        return "pipeline_health"
    return "custom_watch"


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

def _node_priority_score(node: LineageNode, depth_from_anchor: int) -> float:
    """Score a node for inclusion in the watch scope. Higher = more important."""
    score = (10 - min(depth_from_anchor, 10)) * 3.0

    crit_scores = {"critical": 20, "high": 15, "medium": 5, "low": 0}
    score += crit_scores.get(node.criticality, 5)

    score += min(node.downstream_count, 20)

    if node.platform_domain == PlatformDomain.WAREHOUSE:
        score += 5

    return score


# ---------------------------------------------------------------------------
# Scope result
# ---------------------------------------------------------------------------

@dataclass
class ScopeResult:
    """Result of scope selection for a group monitor."""
    anchor_id: str
    anchor_name: str
    watch_type: str
    nodes_with_depth: List[Tuple[str, int, float]]  # (node_id, depth, score)
    recommendations: List[MonitorRecommendation]
    total_upstream_count: int
    scoped_node_count: int
    coverage_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "anchor_name": self.anchor_name,
            "watch_type": self.watch_type,
            "nodes": [
                {"node_id": nid, "depth": d, "score": s}
                for nid, d, s in self.nodes_with_depth
            ],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_upstream_count": self.total_upstream_count,
            "scoped_node_count": self.scoped_node_count,
            "coverage_pct": self.coverage_pct,
        }


# ---------------------------------------------------------------------------
# Monitor recipe per watch type
# ---------------------------------------------------------------------------

# Each recipe entry: (monitor_key, priority, per_type_cap, applicable_check)
# applicable_check is a callable (node, depth) -> bool

_WAREHOUSE_ASSET = {AssetKind.TABLE, AssetKind.VIEW, AssetKind.MODEL, AssetKind.DATASET}
_TRANSFORM_ASSET = {AssetKind.MODEL, AssetKind.TABLE, AssetKind.VIEW}
_ORCH_TYPES = {NodeType.DAG, NodeType.FLOW, NodeType.PIPELINE, NodeType.WORKFLOW}

RecipeEntry = Tuple[str, int, int, Any]  # (key, priority, cap, check_fn)


def _recipe_for_watch_type(watch_type: str, anchor: LineageNode) -> List[RecipeEntry]:
    """Return monitor recipe entries for a given watch type."""

    if watch_type == "pipeline_health":
        return [
            # Direct on anchor
            ("FRESHNESS", 1, 1, lambda n, d: d == 0 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            ("VOLUME", 2, 1, lambda n, d: d == 0 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            ("SCHEMA_CHANGE", 2, 1, lambda n, d: d == 0 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            # Upstream warehouse
            ("FRESHNESS", 2, 3, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            # Ingestion
            ("SYNC_LAG", 2, 2, lambda n, d: n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR),
            # Orchestration
            ("DAG_LAST_RUN", 2, 2, lambda n, d: n.platform_domain == PlatformDomain.ORCHESTRATION and n.node_type in _ORCH_TYPES),
            # dbt
            ("DBT_TEST_FAILURES", 3, 2, lambda n, d: n.platform_domain == PlatformDomain.TRANSFORM and n.asset_kind in _TRANSFORM_ASSET),
        ]

    if watch_type == "dashboard_shield":
        return [
            # BI direct monitors on anchor
            ("BI_FRESHNESS_PROXY", 1, 1, lambda n, d: d == 0 and is_bi_node(n)),
            ("BI_CONTENT_HEALTH", 2, 1, lambda n, d: d == 0 and is_bi_node(n)),
            # Upstream warehouse
            ("FRESHNESS", 1, 5, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            ("SCHEMA_CHANGE", 1, 5, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            ("VOLUME", 2, 3, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            # Ingestion
            ("SYNC_LAG", 2, 2, lambda n, d: n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR),
            # dbt
            ("DBT_TEST_FAILURES", 3, 3, lambda n, d: n.platform_domain == PlatformDomain.TRANSFORM and n.asset_kind in _TRANSFORM_ASSET),
        ]

    if watch_type == "source_guard":
        return [
            # Direct on connector
            ("SYNC_LAG", 1, 1, lambda n, d: d == 0 and (n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR)),
            ("FAILED_SYNCS", 1, 1, lambda n, d: d == 0 and (n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR)),
            ("CONNECTOR_SCHEMA_DRIFT", 2, 1, lambda n, d: d == 0 and (n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR)),
            # Downstream destination tables (uses depth=-1 meaning "downstream")
            ("FRESHNESS", 2, 3, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
        ]

    if watch_type == "model_quality":
        return [
            # Direct on dbt model
            ("DBT_TEST_FAILURES", 1, 1, lambda n, d: d == 0 and n.platform_domain == PlatformDomain.TRANSFORM and n.asset_kind in _TRANSFORM_ASSET),
            ("DBT_MODEL_FRESHNESS", 1, 1, lambda n, d: d == 0 and n.platform_domain == PlatformDomain.TRANSFORM and n.asset_kind in _TRANSFORM_ASSET),
            # Warehouse materialization
            ("FRESHNESS", 2, 1, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            ("SCHEMA_CHANGE", 2, 1, lambda n, d: d >= 1 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            # Upstream warehouse sources
            ("FRESHNESS", 2, 3, lambda n, d: d >= 2 and n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
            # Upstream connectors
            ("SYNC_LAG", 3, 2, lambda n, d: n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR),
        ]

    # custom_watch — generic recipe
    return [
        ("FRESHNESS", 2, 3, lambda n, d: n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
        ("SCHEMA_CHANGE", 2, 2, lambda n, d: n.platform_domain == PlatformDomain.WAREHOUSE and n.asset_kind in _WAREHOUSE_ASSET),
        ("SYNC_LAG", 2, 2, lambda n, d: n.platform_domain == PlatformDomain.INGESTION or n.asset_kind == AssetKind.CONNECTOR),
        ("DAG_LAST_RUN", 2, 2, lambda n, d: n.platform_domain == PlatformDomain.ORCHESTRATION and n.node_type in _ORCH_TYPES),
        ("DBT_TEST_FAILURES", 3, 2, lambda n, d: n.platform_domain == PlatformDomain.TRANSFORM and n.asset_kind in _TRANSFORM_ASSET),
    ]


# ---------------------------------------------------------------------------
# Core: build_watch_scope
# ---------------------------------------------------------------------------

def build_watch_scope(
    graph: LineageGraph,
    anchor_id: str,
    watch_type: str,
    scope_config: Optional[Dict[str, Any]] = None,
    existing_monitor_fqns: Optional[Set[str]] = None,
) -> ScopeResult:
    """
    Build the scope for a group monitor.

    Args:
        graph: The lineage graph to traverse.
        anchor_id: Node ID of the anchor asset.
        watch_type: One of the valid watch types.
        scope_config: Override for default scope params.
        existing_monitor_fqns: Set of "KEY:fqn" for dedup marking.

    Returns:
        ScopeResult with scoped nodes, recommendations, and coverage.
    """
    anchor = graph.nodes.get(anchor_id)
    if not anchor:
        return ScopeResult(
            anchor_id=anchor_id,
            anchor_name="unknown",
            watch_type=watch_type,
            nodes_with_depth=[],
            recommendations=[],
            total_upstream_count=0,
            scoped_node_count=0,
            coverage_pct=0.0,
        )

    # Merge scope config with defaults
    defaults = DEFAULT_SCOPE.get(watch_type, DEFAULT_SCOPE["custom_watch"])
    cfg = {**defaults, **(scope_config or {})}
    max_depth = cfg["maxDepth"]
    max_nodes = cfg["maxNodes"]
    max_monitors = cfg["maxMonitors"]
    domain_filters = set(cfg.get("domainFilters", []))
    include_ids = set(cfg.get("includeNodeIds", []))
    exclude_ids = set(cfg.get("excludeNodeIds", []))

    existing_monitor_fqns = existing_monitor_fqns or set()

    # Phase 1: Bounded BFS
    all_upstream = graph.get_upstream_with_depth(anchor_id, depth=max_depth)
    total_upstream_count = len(all_upstream)

    # For source_guard, also get downstream depth=1
    downstream_with_depth: List[Tuple[LineageNode, int]] = []
    if watch_type == "source_guard":
        downstream_nodes = graph.get_downstream(anchor_id, depth=1)
        downstream_with_depth = [(n, 1) for n in downstream_nodes]

    # Phase 2: Domain filter
    def _passes_domain_filter(node: LineageNode) -> bool:
        if not domain_filters:
            return True
        return node.platform_domain.value in domain_filters

    filtered = [
        (n, d) for n, d in all_upstream
        if _passes_domain_filter(n) and n.id not in exclude_ids
    ]
    # Add downstream for source_guard
    filtered.extend([
        (n, d) for n, d in downstream_with_depth
        if _passes_domain_filter(n) and n.id not in exclude_ids
    ])

    # Phase 3: Priority scoring
    scored = [
        (n, d, _node_priority_score(n, d))
        for n, d in filtered
    ]
    scored.sort(key=lambda x: x[2], reverse=True)

    # Phase 4: Cap nodes
    # Always include forced-include nodes
    include_set = set()
    scoped: List[Tuple[LineageNode, int, float]] = []
    for n, d, s in scored:
        if n.id in include_ids:
            include_set.add(n.id)
            scoped.append((n, d, s))

    for n, d, s in scored:
        if n.id in include_set:
            continue
        if len(scoped) >= max_nodes:
            break
        scoped.append((n, d, s))

    # Build node lookup for depth
    node_depth: Dict[str, int] = {n.id: d for n, d, _ in scoped}
    # Include anchor at depth 0
    node_depth[anchor_id] = 0

    # Phase 5: Generate monitors from recipe
    recipe = _recipe_for_watch_type(watch_type, anchor)
    recommendations: List[MonitorRecommendation] = []
    seen_keys: Set[str] = set()
    recipe_counts: Dict[str, int] = {}  # recipe entry index -> count

    # Candidate nodes = anchor + scoped
    candidate_nodes = [(anchor, 0)] + [(n, d) for n, d, _ in scoped]

    for entry_idx, (mon_key, priority, cap, check_fn) in enumerate(recipe):
        count_key = f"{entry_idx}"
        recipe_counts[count_key] = 0

        for node, depth in candidate_nodes:
            if recipe_counts[count_key] >= cap:
                break
            if not check_fn(node, depth):
                continue

            dedup_key = f"{mon_key}:{node.fqn}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            already_monitored = (
                dedup_key in existing_monitor_fqns
                or node.fqn in existing_monitor_fqns
            )

            source = "direct" if depth == 0 else "upstream"
            if depth < 0:
                source = "downstream"

            recommendations.append(MonitorRecommendation(
                monitor_key=mon_key,
                target_fqn=node.fqn,
                target_node_id=node.id,
                source=source,
                reason=_build_reason(mon_key, node, anchor, depth),
                priority=priority,
                config_hints=_build_config_hints(node, mon_key),
                integration_type=node.platform or "",
                already_monitored=already_monitored,
            ))
            recipe_counts[count_key] += 1

    # Cap total monitors
    recommendations.sort(key=lambda r: r.priority)
    recommendations = recommendations[:max_monitors]

    # Phase 6: Coverage
    nodes_with_monitors = {r.target_node_id for r in recommendations}
    coverage_pct = (
        len(nodes_with_monitors) / total_upstream_count
        if total_upstream_count > 0
        else 1.0
    )

    return ScopeResult(
        anchor_id=anchor_id,
        anchor_name=anchor.name,
        watch_type=watch_type,
        nodes_with_depth=[(n.id, d, s) for n, d, s in scoped],
        recommendations=recommendations,
        total_upstream_count=total_upstream_count,
        scoped_node_count=len(scoped),
        coverage_pct=round(coverage_pct, 3),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_reason(mon_key: str, node: LineageNode, anchor: LineageNode, depth: int) -> str:
    """Generate a human-readable reason for a monitor recommendation."""
    if depth == 0:
        return f"Direct check on {anchor.name}"

    direction = "upstream" if depth > 0 else "downstream"
    key_labels = {
        "FRESHNESS": "stale data",
        "VOLUME": "row count anomaly",
        "SCHEMA_CHANGE": "schema change",
        "NULL_RATE": "null spikes",
        "UNIQUENESS": "key degradation",
        "ANOMALY": "metric anomaly",
        "SYNC_LAG": "sync lag",
        "FAILED_SYNCS": "sync failure",
        "CONNECTOR_SCHEMA_DRIFT": "schema drift",
        "DAG_LAST_RUN": "run failure",
        "DAG_SCHEDULE_LAG": "schedule lag",
        "DBT_TEST_FAILURES": "test failure",
        "DBT_MODEL_FRESHNESS": "model staleness",
        "DBT_SOURCE_FRESHNESS": "source staleness",
        "BI_FRESHNESS_PROXY": "dashboard staleness",
        "BI_CONTENT_HEALTH": "content issue",
        "BI_UPSTREAM_BREAK_RISK": "upstream break risk",
        "BI_REFRESH_FAILURE": "refresh failure",
    }
    label = key_labels.get(mon_key, mon_key.lower().replace("_", " "))
    return f"Detect {label} in {direction} dependency {node.name} (depth {abs(depth)} from {anchor.name})"
