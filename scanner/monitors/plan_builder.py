"""
Monitoring Plan Builder — orchestrates family resolution, scope selection,
and topology-aware partitioning to generate a full plan preview.

This is the main entry point for the unified "Set Up Monitoring" flow.
It composes families.py, scope.py, and partitioner.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..lineage.graph import LineageGraph, LineageNode
from .families import (
    MONITOR_FAMILIES,
    get_family_eligibility,
    get_family_watch_type,
    resolve_families,
)
from .partitioner import (
    Partition,
    PartitionPlan,
    partition_scope,
)
from .scope import (
    ScopeResult,
    build_watch_scope,
    _node_priority_score,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GroupPreview:
    """Preview of a single monitor group within a plan."""
    group_index: int
    family: str
    watch_type: str
    anchor_id: str
    anchor_name: str
    anchor_fqn: str
    anchor_node_type: str
    anchor_platform: str
    node_count: int
    monitor_count: int
    coverage_pct: float
    shared_node_ids: List[str] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_index": self.group_index,
            "family": self.family,
            "watch_type": self.watch_type,
            "anchor_id": self.anchor_id,
            "anchor_name": self.anchor_name,
            "anchor_fqn": self.anchor_fqn,
            "anchor_node_type": self.anchor_node_type,
            "anchor_platform": self.anchor_platform,
            "node_count": self.node_count,
            "monitor_count": self.monitor_count,
            "coverage_pct": self.coverage_pct,
            "shared_node_ids": self.shared_node_ids,
            "recommendations": self.recommendations,
        }


@dataclass
class MonitoringPlanPreview:
    """Full preview of a monitoring plan."""
    scope_type: str
    mode: str
    families: List[str]
    groups: List[GroupPreview] = field(default_factory=list)
    total_nodes: int = 0
    total_monitors: int = 0
    raw_monitor_count: int = 0   # Before dedup
    dedup_count: int = 0
    coverage_pct: float = 0.0
    warnings: List[str] = field(default_factory=list)
    family_eligibility: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "mode": self.mode,
            "families": self.families,
            "groups": [g.to_dict() for g in self.groups],
            "total_nodes": self.total_nodes,
            "total_monitors": self.total_monitors,
            "raw_monitor_count": self.raw_monitor_count,
            "dedup_count": self.dedup_count,
            "coverage_pct": self.coverage_pct,
            "warnings": self.warnings,
            "family_eligibility": self.family_eligibility,
        }


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------

def _resolve_scope_nodes(
    graph: LineageGraph,
    scope_type: str,
    scope_config: Dict[str, Any],
) -> Set[str]:
    """
    Resolve scope into a set of node IDs.

    Scope types:
      - pipeline: all nodes in graph
      - stream: BFS upstream from anchor(s)
      - asset: single anchor + immediate neighbors
      - tool: all nodes of a given tool/platform type
      - custom: explicit list of user-selected node IDs
    """
    if scope_type == "custom":
        # User-selected nodes — use exactly the provided IDs
        node_ids = scope_config.get("nodeIds", [])
        return {nid for nid in node_ids if nid in graph.nodes}

    if scope_type == "pipeline":
        return set(graph.nodes.keys())

    anchor_ids = scope_config.get("anchorNodeIds", [])
    max_depth = scope_config.get("maxDepth", 5)

    if scope_type == "stream":
        nodes: Set[str] = set()
        for anchor_id in anchor_ids:
            if anchor_id in graph.nodes:
                nodes.add(anchor_id)
                upstream = graph.get_upstream_with_depth(anchor_id, depth=max_depth)
                for node, _ in upstream:
                    nodes.add(node.id)
        return nodes

    if scope_type == "asset":
        nodes = set()
        for anchor_id in anchor_ids:
            if anchor_id in graph.nodes:
                nodes.add(anchor_id)
                # Immediate upstream and downstream
                for up_id in graph._upstream.get(anchor_id, set()):
                    nodes.add(up_id)
                for ds_id in graph._downstream.get(anchor_id, set()):
                    nodes.add(ds_id)
        return nodes

    if scope_type == "tool":
        tool_type = scope_config.get("toolType", "")
        platform = scope_config.get("platform", "")
        nodes = set()
        for nid, node in graph.nodes.items():
            if tool_type and getattr(node, "platform", "") == tool_type:
                nodes.add(nid)
            elif platform and getattr(node, "platform", "") == platform:
                nodes.add(nid)
        return nodes

    logger.warning("[PlanBuilder] Unknown scope type: %s", scope_type)
    return set()


# ---------------------------------------------------------------------------
# Core: preview_monitoring_plan
# ---------------------------------------------------------------------------

def preview_monitoring_plan(
    graph: LineageGraph,
    scope_type: str,
    scope_config: Dict[str, Any],
    mode: str,
    families: List[str],
    manual_selections: Optional[Dict[str, List[str]]] = None,
    existing_monitor_fqns: Optional[Set[str]] = None,
) -> MonitoringPlanPreview:
    """
    Generate a full monitoring plan preview without persisting anything.

    Args:
        graph: The lineage graph.
        scope_type: "pipeline" | "stream" | "asset" | "tool"
        scope_config: { anchorNodeIds, maxDepth, toolType, platform }
        mode: "recommended" | "manual"
        families: Selected family keys.
        manual_selections: Node-to-monitor-type mapping for manual mode.
                           { node_id: [monitorType, ...] }
        existing_monitor_fqns: Set of "KEY:fqn" for dedup marking.

    Returns:
        MonitoringPlanPreview with per-group breakdowns.
    """
    existing_fqns = set(existing_monitor_fqns or [])

    # Resolve scope
    scope_node_ids = _resolve_scope_nodes(graph, scope_type, scope_config)
    if not scope_node_ids:
        return MonitoringPlanPreview(
            scope_type=scope_type,
            mode=mode,
            families=families,
            warnings=["No nodes found in the selected scope"],
        )

    # Get scope nodes as LineageNode objects
    scope_nodes = [
        graph.nodes[nid] for nid in scope_node_ids
        if nid in graph.nodes
    ]

    # Check family eligibility
    eligibility = get_family_eligibility(scope_nodes)
    eligibility_dicts = [e.to_dict() for e in eligibility]

    if mode == "recommended":
        return _preview_recommended(
            graph=graph,
            scope_type=scope_type,
            scope_node_ids=scope_node_ids,
            scope_nodes=scope_nodes,
            selected_families=families,
            existing_fqns=existing_fqns,
            eligibility_dicts=eligibility_dicts,
        )
    else:
        return _preview_manual(
            graph=graph,
            scope_type=scope_type,
            scope_node_ids=scope_node_ids,
            manual_selections=manual_selections or {},
            existing_fqns=existing_fqns,
            eligibility_dicts=eligibility_dicts,
        )


# ---------------------------------------------------------------------------
# Recommended mode
# ---------------------------------------------------------------------------

def _preview_recommended(
    graph: LineageGraph,
    scope_type: str,
    scope_node_ids: Set[str],
    scope_nodes: List[LineageNode],
    selected_families: List[str],
    existing_fqns: Set[str],
    eligibility_dicts: List[Dict[str, Any]],
) -> MonitoringPlanPreview:
    """Generate preview for recommended mode."""
    # Resolve families (expand full_coverage if needed)
    concrete_families = resolve_families(selected_families, scope_nodes)

    if not concrete_families:
        return MonitoringPlanPreview(
            scope_type=scope_type,
            mode="recommended",
            families=selected_families,
            family_eligibility=eligibility_dicts,
            warnings=["No applicable monitor families for this scope"],
        )

    all_groups: List[GroupPreview] = []
    cumulative_fqns: Set[str] = set(existing_fqns)
    total_dedup = 0
    total_raw = 0
    group_idx = 0

    for family_key in concrete_families:
        watch_type = get_family_watch_type(family_key)
        if not watch_type:
            continue

        # Filter scope nodes to those relevant for this family
        family_def = MONITOR_FAMILIES.get(family_key)
        if not family_def:
            continue

        # Skip families with no eligible nodes in scope
        from .families import _count_matching_nodes
        if not family_def.is_meta and _count_matching_nodes(scope_nodes, family_def) == 0:
            logger.info(
                "[PlanBuilder] Skipping family %s — no eligible nodes in scope",
                family_key,
            )
            continue

        # Use partition_scope to create topology-aware groups
        # Pass preferred anchor domains so BI families pick BI nodes as anchors,
        # ingestion families pick connectors, etc.
        preferred_domains = family_def.eligible_domains if family_def.eligible_domains else None
        plan = partition_scope(
            graph=graph,
            scope_node_ids=scope_node_ids,
            watch_type=watch_type,
            existing_fqns=cumulative_fqns,
            preferred_anchor_domains=preferred_domains,
        )

        total_dedup += plan.dedup_count

        for partition in plan.partitions:
            if not partition.scope_result:
                continue

            recs = partition.scope_result.recommendations
            total_raw += len(recs) + plan.dedup_count

            # Track cumulative fqns for cross-family dedup
            for rec in recs:
                cumulative_fqns.add(f"{rec.monitor_key}:{rec.target_fqn}")

            all_groups.append(GroupPreview(
                group_index=group_idx,
                family=family_key,
                watch_type=watch_type,
                anchor_id=partition.anchor_id,
                anchor_name=partition.anchor_name,
                anchor_fqn=partition.anchor_fqn,
                anchor_node_type=partition.anchor_node_type,
                anchor_platform=partition.anchor_platform,
                node_count=len(partition.node_ids),
                monitor_count=len(recs),
                coverage_pct=partition.scope_result.coverage_pct,
                shared_node_ids=partition.shared_node_ids,
                recommendations=[r.to_dict() for r in recs],
            ))
            group_idx += 1

    total_monitors = sum(g.monitor_count for g in all_groups)
    all_node_ids: Set[str] = set()
    for g in all_groups:
        for rec in g.recommendations:
            all_node_ids.add(rec.get("target_node_id", ""))

    coverage_pct = (
        len(all_node_ids) / len(scope_node_ids)
        if scope_node_ids else 0.0
    )

    return MonitoringPlanPreview(
        scope_type=scope_type,
        mode="recommended",
        families=selected_families,
        groups=all_groups,
        total_nodes=len(all_node_ids),
        total_monitors=total_monitors,
        raw_monitor_count=total_raw if total_raw > total_monitors else total_monitors,
        dedup_count=total_dedup,
        coverage_pct=round(coverage_pct, 3),
        family_eligibility=eligibility_dicts,
    )


# ---------------------------------------------------------------------------
# Manual mode
# ---------------------------------------------------------------------------

def _preview_manual(
    graph: LineageGraph,
    scope_type: str,
    scope_node_ids: Set[str],
    manual_selections: Dict[str, List[str]],
    existing_fqns: Set[str],
    eligibility_dicts: List[Dict[str, Any]],
) -> MonitoringPlanPreview:
    """Generate preview for manual mode."""
    from .recommender import MonitorRecommendation, _build_config_hints

    if not manual_selections:
        return MonitoringPlanPreview(
            scope_type=scope_type,
            mode="manual",
            families=[],
            family_eligibility=eligibility_dicts,
            warnings=["No monitors selected"],
        )

    # Build recommendations from manual selections
    all_recs: List[MonitorRecommendation] = []
    seen_keys: Set[str] = set()
    total_raw = 0

    for node_id, monitor_types in manual_selections.items():
        node = graph.nodes.get(node_id)
        if not node:
            continue

        for mon_type in monitor_types:
            total_raw += 1
            dedup_key = f"{mon_type}:{node.fqn}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            already_monitored = dedup_key in existing_fqns
            all_recs.append(MonitorRecommendation(
                monitor_key=mon_type,
                target_fqn=node.fqn,
                target_node_id=node_id,
                source="manual",
                reason=f"Manually selected {mon_type} for {node.name}",
                priority=2,
                config_hints=_build_config_hints(node, mon_type),
                integration_type=node.platform or "",
                already_monitored=already_monitored,
            ))

    # Filter out already-monitored
    new_recs = [r for r in all_recs if not r.already_monitored]
    dedup_count = total_raw - len(new_recs)

    # Partition the selected nodes
    selected_node_ids = set(manual_selections.keys()) & scope_node_ids
    plan = partition_scope(
        graph=graph,
        scope_node_ids=selected_node_ids,
        watch_type="custom_watch",
        existing_fqns=existing_fqns,
    )

    # Map recommendations to partitions
    groups: List[GroupPreview] = []
    node_to_partition: Dict[str, str] = {}
    for partition in plan.partitions:
        for nid in partition.node_ids:
            node_to_partition[nid] = partition.partition_id

    # Group recs by partition
    partition_recs: Dict[str, List[MonitorRecommendation]] = {}
    for rec in new_recs:
        part_id = node_to_partition.get(rec.target_node_id, "default")
        if part_id not in partition_recs:
            partition_recs[part_id] = []
        partition_recs[part_id].append(rec)

    group_idx = 0
    for partition in plan.partitions:
        recs = partition_recs.get(partition.partition_id, [])
        if not recs:
            continue

        groups.append(GroupPreview(
            group_index=group_idx,
            family="custom",
            watch_type="custom_watch",
            anchor_id=partition.anchor_id,
            anchor_name=partition.anchor_name,
            anchor_fqn=partition.anchor_fqn,
            anchor_node_type=partition.anchor_node_type,
            anchor_platform=partition.anchor_platform,
            node_count=len(partition.node_ids),
            monitor_count=len(recs),
            coverage_pct=partition.scope_result.coverage_pct if partition.scope_result else 0.0,
            shared_node_ids=partition.shared_node_ids,
            recommendations=[r.to_dict() for r in recs],
        ))
        group_idx += 1

    # Handle recs not assigned to any partition
    default_recs = partition_recs.get("default", [])
    if default_recs:
        # Pick best node as anchor
        best_node_id = None
        best_score = -1.0
        for rec in default_recs:
            node = graph.nodes.get(rec.target_node_id)
            if node:
                score = _node_priority_score(node, 0)
                if score > best_score:
                    best_score = score
                    best_node_id = rec.target_node_id

        anchor = graph.nodes.get(best_node_id) if best_node_id else None
        if anchor:
            groups.append(GroupPreview(
                group_index=group_idx,
                family="custom",
                watch_type="custom_watch",
                anchor_id=best_node_id,
                anchor_name=anchor.name,
                anchor_fqn=anchor.fqn,
                anchor_node_type=anchor.node_type.value,
                anchor_platform=anchor.platform or "",
                node_count=len(set(r.target_node_id for r in default_recs)),
                monitor_count=len(default_recs),
                coverage_pct=0.0,
                recommendations=[r.to_dict() for r in default_recs],
            ))

    total_monitors = sum(g.monitor_count for g in groups)
    all_node_ids = set()
    for g in groups:
        for rec in g.recommendations:
            all_node_ids.add(rec.get("target_node_id", ""))

    coverage_pct = (
        len(all_node_ids) / len(scope_node_ids)
        if scope_node_ids else 0.0
    )

    return MonitoringPlanPreview(
        scope_type=scope_type,
        mode="manual",
        families=["custom"],
        groups=groups,
        total_nodes=len(all_node_ids),
        total_monitors=total_monitors,
        raw_monitor_count=total_raw,
        dedup_count=dedup_count,
        coverage_pct=round(coverage_pct, 3),
        family_eligibility=eligibility_dicts,
    )
