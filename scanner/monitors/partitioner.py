"""
Topology-Aware Partitioning for Monitoring Plans.

Splits a set of in-scope nodes into meaningful partitions (groups)
that preserve lineage structure. Each partition becomes a MonitorGroup.

Algorithm phases:
  1. Root Discovery — find nodes with no in-scope upstream
  2. Partition Growth — BFS downstream within scope
  3. Shared Node Resolution — majority rule + priority tiebreak
  4. Size Capping — split oversized partitions at branch boundaries
  5. Cross-Partition Dedup — ensure one monitor per (type, fqn)
  6. Anchor Selection — pick highest-priority root per partition
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..lineage.graph import LineageGraph
from .scope import (
    ScopeResult,
    _node_priority_score,
    build_watch_scope,
)

logger = logging.getLogger(__name__)

MAX_NODES_PER_GROUP = 20
MAX_MONITORS_PER_GROUP = 15


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Partition:
    """A single partition representing a future MonitorGroup."""
    partition_id: str
    anchor_id: str
    anchor_name: str
    anchor_fqn: str
    anchor_node_type: str
    anchor_platform: str
    watch_type: str
    node_ids: List[str]
    shared_node_ids: List[str] = field(default_factory=list)
    scope_result: Optional[ScopeResult] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "partition_id": self.partition_id,
            "anchor_id": self.anchor_id,
            "anchor_name": self.anchor_name,
            "anchor_fqn": self.anchor_fqn,
            "anchor_node_type": self.anchor_node_type,
            "anchor_platform": self.anchor_platform,
            "watch_type": self.watch_type,
            "node_ids": self.node_ids,
            "shared_node_ids": self.shared_node_ids,
            "node_count": len(self.node_ids),
            "monitor_count": len(self.scope_result.recommendations) if self.scope_result else 0,
            "coverage_pct": self.scope_result.coverage_pct if self.scope_result else 0.0,
        }
        if self.scope_result:
            result["scope_result"] = self.scope_result.to_dict()
        return result


@dataclass
class PartitionPlan:
    """Result of topology-aware partitioning."""
    partitions: List[Partition]
    total_nodes: int
    total_monitors: int
    dedup_count: int
    shared_node_count: int
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "partitions": [p.to_dict() for p in self.partitions],
            "total_nodes": self.total_nodes,
            "total_monitors": self.total_monitors,
            "dedup_count": self.dedup_count,
            "shared_node_count": self.shared_node_count,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Core: partition_scope
# ---------------------------------------------------------------------------

def partition_scope(
    graph: LineageGraph,
    scope_node_ids: Set[str],
    watch_type: str,
    max_nodes: int = MAX_NODES_PER_GROUP,
    max_monitors: int = MAX_MONITORS_PER_GROUP,
    existing_fqns: Optional[Set[str]] = None,
    preferred_anchor_domains: Optional[List[str]] = None,
) -> PartitionPlan:
    """
    Partition a set of in-scope nodes into topology-aware groups.

    Args:
        graph: The lineage graph.
        scope_node_ids: Node IDs in the user-selected scope.
        watch_type: Watch type for monitor recipe selection.
        max_nodes: Maximum nodes per partition.
        max_monitors: Maximum monitors per partition.
        existing_fqns: Set of "KEY:fqn" strings for dedup marking.

    Returns:
        PartitionPlan with partition breakdown.
    """
    if not scope_node_ids:
        return PartitionPlan(
            partitions=[],
            total_nodes=0,
            total_monitors=0,
            dedup_count=0,
            shared_node_count=0,
        )

    existing_fqns = existing_fqns or set()
    scope_set = set(scope_node_ids)

    # Phase 1: Root Discovery
    roots = _find_roots(graph, scope_set)
    if not roots:
        # If no roots found (all nodes have in-scope upstream),
        # use the highest-priority node as root
        best_id = _pick_best_node(graph, scope_set)
        if best_id:
            roots = [best_id]
        else:
            return PartitionPlan(
                partitions=[],
                total_nodes=0,
                total_monitors=0,
                dedup_count=0,
                shared_node_count=0,
                warnings=["No valid root nodes found in scope"],
            )

    # Phase 2 + 3: Partition Growth + Shared Node Resolution
    node_to_partition, shared_nodes = _grow_partitions(
        graph, scope_set, roots
    )

    # Build partition node lists
    partition_nodes: Dict[str, List[str]] = defaultdict(list)
    for node_id, part_id in node_to_partition.items():
        partition_nodes[part_id].append(node_id)

    # Phase 4: Size Capping
    final_partitions = _cap_partitions(
        graph, partition_nodes, max_nodes, roots, scope_set
    )

    # Phase 5: Build scope results for each partition
    cumulative_fqns: Set[str] = set(existing_fqns)
    partitions: List[Partition] = []
    total_dedup = 0

    for part_id, node_ids in final_partitions.items():
        if not node_ids:
            continue

        anchor_id = _pick_best_node(graph, set(node_ids), preferred_anchor_domains)
        if not anchor_id:
            continue

        anchor = graph.nodes.get(anchor_id)
        if not anchor:
            continue

        # Build scope using existing engine
        # restrictToNodeIds is partition-scoped (not the full scope set) so
        # each partition only generates monitors for its own nodes.  The
        # maxMonitors cap scales with the partition size so every node can
        # get its full set of applicable monitors.
        effective_max_monitors = max(max_monitors, len(node_ids) * 8)
        scope_config = {
            "maxDepth": 10,  # Use large depth since we constrain by node set
            "maxNodes": len(node_ids),
            "maxMonitors": effective_max_monitors,
            "domainFilters": [],
            "includeNodeIds": list(node_ids),
            "restrictToNodeIds": list(node_ids),  # Only generate monitors for this partition's nodes
        }
        scope_result = build_watch_scope(
            graph=graph,
            anchor_id=anchor_id,
            watch_type=watch_type,
            scope_config=scope_config,
            existing_monitor_fqns=cumulative_fqns,
        )

        # Cross-partition dedup
        new_recs = []
        for rec in scope_result.recommendations:
            dedup_key = f"{rec.monitor_key}:{rec.target_fqn}"
            if rec.already_monitored or dedup_key in cumulative_fqns:
                total_dedup += 1
                continue
            cumulative_fqns.add(dedup_key)
            new_recs.append(rec)
        scope_result.recommendations = new_recs

        if not scope_result.recommendations:
            continue

        # Determine shared nodes for this partition
        part_shared = [
            nid for nid in node_ids
            if nid in shared_nodes and node_to_partition.get(nid) != part_id
        ]

        partitions.append(Partition(
            partition_id=part_id,
            anchor_id=anchor_id,
            anchor_name=anchor.name,
            anchor_fqn=anchor.fqn,
            anchor_node_type=anchor.node_type.value,
            anchor_platform=anchor.platform or "",
            watch_type=watch_type,
            node_ids=list(node_ids),
            shared_node_ids=part_shared,
            scope_result=scope_result,
        ))

    total_monitors = sum(
        len(p.scope_result.recommendations) for p in partitions
        if p.scope_result
    )
    all_nodes = set()
    for p in partitions:
        all_nodes.update(p.node_ids)

    warnings = []
    if len(scope_set) > len(all_nodes):
        warnings.append(
            f"{len(scope_set) - len(all_nodes)} nodes excluded due to partitioning constraints"
        )

    return PartitionPlan(
        partitions=partitions,
        total_nodes=len(all_nodes),
        total_monitors=total_monitors,
        dedup_count=total_dedup,
        shared_node_count=len(shared_nodes),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Phase 1: Root Discovery
# ---------------------------------------------------------------------------

def _find_roots(graph: LineageGraph, scope_set: Set[str]) -> List[str]:
    """Find nodes with zero in-scope upstream parents."""
    roots = []
    for node_id in scope_set:
        upstream_ids = graph._upstream.get(node_id, set())
        in_scope_upstream = upstream_ids & scope_set
        if not in_scope_upstream:
            roots.append(node_id)
    return roots


# ---------------------------------------------------------------------------
# Phase 2 + 3: Partition Growth + Shared Node Resolution
# ---------------------------------------------------------------------------

def _grow_partitions(
    graph: LineageGraph,
    scope_set: Set[str],
    roots: List[str],
) -> Tuple[Dict[str, str], Set[str]]:
    """
    Grow partitions from roots via BFS downstream within scope.

    Returns:
        (node_to_partition, shared_nodes)
        - node_to_partition: node_id -> partition_id
        - shared_nodes: set of node_ids that belong to multiple root subgraphs
    """
    # Assign each root its own partition
    node_to_partition: Dict[str, str] = {}
    shared_nodes: Set[str] = set()

    # Track which partition each node was claimed by (for conflict detection)
    node_claims: Dict[str, List[str]] = defaultdict(list)

    for root_id in roots:
        part_id = str(uuid.uuid4())[:8]
        node_to_partition[root_id] = part_id
        node_claims[root_id].append(part_id)

    # BFS downstream from each root within scope
    # Process in waves to handle shared nodes properly
    queue: List[Tuple[str, str]] = []  # (node_id, partition_id)
    for root_id in roots:
        part_id = node_to_partition[root_id]
        downstream_ids = graph._downstream.get(root_id, set())
        for ds_id in downstream_ids:
            if ds_id in scope_set:
                queue.append((ds_id, part_id))

    visited_edges: Set[Tuple[str, str]] = set()  # (node_id, partition_id)

    while queue:
        node_id, from_part_id = queue.pop(0)
        edge_key = (node_id, from_part_id)
        if edge_key in visited_edges:
            continue
        visited_edges.add(edge_key)

        node_claims[node_id].append(from_part_id)

        # Continue BFS downstream
        downstream_ids = graph._downstream.get(node_id, set())
        for ds_id in downstream_ids:
            if ds_id in scope_set and (ds_id, from_part_id) not in visited_edges:
                queue.append((ds_id, from_part_id))

    # Resolve conflicts for nodes claimed by multiple partitions
    for node_id, claims in node_claims.items():
        if node_id in node_to_partition:
            continue  # Already assigned (root)

        unique_claims = list(dict.fromkeys(claims))  # Deduplicate preserving order

        if len(unique_claims) == 1:
            node_to_partition[node_id] = unique_claims[0]
        else:
            # Shared node — resolve by majority/priority
            shared_nodes.add(node_id)
            winner = _resolve_shared_node(
                graph, node_id, unique_claims, node_to_partition, scope_set
            )
            node_to_partition[node_id] = winner

    # Assign any remaining scope nodes not reached by BFS
    for node_id in scope_set:
        if node_id not in node_to_partition:
            # Orphan — assign to nearest partition or create new one
            node_to_partition[node_id] = _find_nearest_partition(
                graph, node_id, node_to_partition, scope_set
            )

    return node_to_partition, shared_nodes


def _resolve_shared_node(
    graph: LineageGraph,
    node_id: str,
    claim_partition_ids: List[str],
    node_to_partition: Dict[str, str],
    scope_set: Set[str],
) -> str:
    """
    Resolve which partition owns a shared node.

    Policy (in order):
    1. Majority rule — if >50% of in-scope upstream parents are in one partition
    2. Priority tiebreak — join the partition of the highest-priority parent
    """
    upstream_ids = graph._upstream.get(node_id, set())
    in_scope_upstream = upstream_ids & scope_set

    if not in_scope_upstream:
        return claim_partition_ids[0]

    # Count upstream parents per partition
    part_counts: Dict[str, int] = defaultdict(int)
    for up_id in in_scope_upstream:
        part_id = node_to_partition.get(up_id)
        if part_id:
            part_counts[part_id] += 1

    total_parents = sum(part_counts.values())
    if total_parents == 0:
        return claim_partition_ids[0]

    # Majority rule: >50% in one partition
    for part_id, count in part_counts.items():
        if count > total_parents / 2:
            return part_id

    # Priority tiebreak: highest-priority upstream parent
    best_score = -1.0
    best_partition = claim_partition_ids[0]
    for up_id in in_scope_upstream:
        node = graph.nodes.get(up_id)
        part_id = node_to_partition.get(up_id)
        if node and part_id:
            score = _node_priority_score(node, 0)
            if score > best_score:
                best_score = score
                best_partition = part_id

    return best_partition


def _find_nearest_partition(
    graph: LineageGraph,
    node_id: str,
    node_to_partition: Dict[str, str],
    scope_set: Set[str],
) -> str:
    """Find the partition of the nearest assigned neighbor."""
    # Check upstream first
    for up_id in graph._upstream.get(node_id, set()):
        if up_id in node_to_partition:
            return node_to_partition[up_id]
    # Then downstream
    for ds_id in graph._downstream.get(node_id, set()):
        if ds_id in node_to_partition:
            return node_to_partition[ds_id]
    # Last resort: create a new partition
    return str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# Phase 4: Size Capping
# ---------------------------------------------------------------------------

def _cap_partitions(
    graph: LineageGraph,
    partition_nodes: Dict[str, List[str]],
    max_nodes: int,
    roots: List[str],
    scope_set: Set[str],
) -> Dict[str, List[str]]:
    """
    Split oversized partitions at branch boundaries.

    A dependency chain (linear A→B→C) is never split unless it alone
    exceeds the cap.
    """
    result: Dict[str, List[str]] = {}

    for part_id, node_ids in partition_nodes.items():
        if len(node_ids) <= max_nodes:
            result[part_id] = node_ids
            continue

        # Need to split — find branch points within this partition
        part_set = set(node_ids)
        sub_partitions = _split_partition(graph, part_set, max_nodes)

        for i, sub_nodes in enumerate(sub_partitions):
            sub_id = f"{part_id}_{i}" if i > 0 else part_id
            result[sub_id] = list(sub_nodes)

    return result


def _split_partition(
    graph: LineageGraph,
    node_ids: Set[str],
    max_nodes: int,
) -> List[Set[str]]:
    """
    Split a partition into sub-partitions at branch boundaries.

    Strategy: find the node with the most downstream within the partition
    and split its downstream subtree into a new partition.
    """
    if len(node_ids) <= max_nodes:
        return [node_ids]

    # Find roots within this sub-partition
    sub_roots = []
    for nid in node_ids:
        upstream = graph._upstream.get(nid, set())
        if not (upstream & node_ids):
            sub_roots.append(nid)

    if not sub_roots:
        # Cyclic or no clear root — just chunk by priority
        scored = []
        for nid in node_ids:
            node = graph.nodes.get(nid)
            score = _node_priority_score(node, 0) if node else 0
            scored.append((nid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        chunk1 = {nid for nid, _ in scored[:max_nodes]}
        chunk2 = {nid for nid, _ in scored[max_nodes:]}
        result = [chunk1]
        if chunk2:
            result.extend(_split_partition(graph, chunk2, max_nodes))
        return result

    # BFS from each root to find subtrees
    subtrees: List[Set[str]] = []
    assigned: Set[str] = set()

    for root_id in sub_roots:
        subtree: Set[str] = set()
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            if current in assigned or current not in node_ids:
                continue
            assigned.add(current)
            subtree.add(current)
            for ds_id in graph._downstream.get(current, set()):
                if ds_id in node_ids and ds_id not in assigned:
                    queue.append(ds_id)

        if subtree:
            subtrees.append(subtree)

    # Assign unassigned nodes to the largest subtree
    unassigned = node_ids - assigned
    if unassigned and subtrees:
        subtrees[0].update(unassigned)

    # If we only got one subtree and it's still too large (e.g., linear chain),
    # force-chunk it by priority score to avoid infinite recursion
    if len(subtrees) == 1 and len(subtrees[0]) > max_nodes:
        scored = []
        for nid in subtrees[0]:
            node = graph.nodes.get(nid)
            score = _node_priority_score(node, 0) if node else 0
            scored.append((nid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        chunks: List[Set[str]] = []
        for i in range(0, len(scored), max_nodes):
            chunks.append({nid for nid, _ in scored[i:i + max_nodes]})
        return chunks

    # If any subtree is still too large, recursively split
    final: List[Set[str]] = []
    for subtree in subtrees:
        if len(subtree) <= max_nodes:
            final.append(subtree)
        else:
            final.extend(_split_partition(graph, subtree, max_nodes))

    return final if final else [node_ids]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_best_node(
    graph: LineageGraph,
    node_ids: Set[str],
    preferred_domains: Optional[List[str]] = None,
) -> Optional[str]:
    """Pick the highest-priority node from a set.

    If preferred_domains is given, first try to find a node in those domains.
    This ensures BI families pick BI nodes as anchors, ingestion families pick
    connectors, etc.
    """
    if preferred_domains:
        domain_set = set(preferred_domains)
        domain_candidates = {
            nid for nid in node_ids
            if graph.nodes.get(nid)
            and graph.nodes[nid].platform_domain.value in domain_set
        }
        if domain_candidates:
            return _pick_best_node(graph, domain_candidates)

    best_id = None
    best_score = -1.0
    for nid in node_ids:
        node = graph.nodes.get(nid)
        if node:
            score = _node_priority_score(node, 0)
            if score > best_score:
                best_score = score
                best_id = nid
    return best_id
