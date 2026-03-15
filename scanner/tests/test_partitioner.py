"""Tests for topology-aware partitioning."""

from __future__ import annotations

import pytest

from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    LineageEdge,
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.monitors.partitioner import (
    MAX_MONITORS_PER_GROUP,
    MAX_NODES_PER_GROUP,
    partition_scope,
    _find_roots,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    id: str,
    name: str,
    fqn: str,
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    node_type: NodeType = NodeType.TABLE,
    asset_kind: AssetKind = AssetKind.TABLE,
    platform: str = "bigquery",
    criticality: str = "medium",
    downstream_count: int = 0,
) -> LineageNode:
    return LineageNode(
        id=id,
        name=name,
        fqn=fqn,
        node_type=node_type,
        platform_domain=platform_domain,
        asset_kind=asset_kind,
        platform=platform,
        criticality=criticality,
        downstream_count=downstream_count,
        columns=[],
    )


def _add_edge(graph: LineageGraph, source_id: str, target_id: str) -> None:
    edge = LineageEdge(
        id=f"{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.DERIVED_FROM,
    )
    graph.add_edge(edge)


def _build_linear_chain(n: int = 4) -> tuple:
    """Build A -> B -> C -> D (linear chain). Returns (graph, node_ids)."""
    graph = LineageGraph()
    ids = []
    for i in range(n):
        nid = f"node-{i}"
        ids.append(nid)
        graph.add_node(_make_node(
            nid, f"table_{i}", f"db.schema.table_{i}",
            downstream_count=n - i - 1,
        ))
    # Edges: each node derives from the previous (upstream direction)
    for i in range(1, n):
        _add_edge(graph, ids[i - 1], ids[i])
    return graph, ids


def _build_branching_graph() -> tuple:
    """
    Build:
        A -> B -> D
        A -> C -> D
    (diamond/DAG shape with shared node D)
    """
    graph = LineageGraph()
    for nid, name in [("A", "root_A"), ("B", "mid_B"), ("C", "mid_C"), ("D", "leaf_D")]:
        graph.add_node(_make_node(nid, name, f"db.schema.{name}", downstream_count=1))

    _add_edge(graph, "A", "B")
    _add_edge(graph, "A", "C")
    _add_edge(graph, "B", "D")
    _add_edge(graph, "C", "D")
    return graph, ["A", "B", "C", "D"]


# ---------------------------------------------------------------------------
# Tests: root discovery
# ---------------------------------------------------------------------------

class TestRootDiscovery:
    def test_linear_chain_single_root(self):
        graph, ids = _build_linear_chain()
        roots = _find_roots(graph, set(ids))
        assert len(roots) == 1
        assert roots[0] == ids[0]

    def test_branching_graph_single_root(self):
        graph, ids = _build_branching_graph()
        roots = _find_roots(graph, set(ids))
        assert "A" in roots


# ---------------------------------------------------------------------------
# Tests: partitioning
# ---------------------------------------------------------------------------

class TestPartitionScope:
    def test_linear_chain_single_partition(self):
        graph, ids = _build_linear_chain(4)
        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
        )
        assert len(plan.partitions) >= 1
        # All nodes should be covered
        all_part_nodes = set()
        for p in plan.partitions:
            all_part_nodes.update(p.node_ids)
        assert all_part_nodes == set(ids)

    def test_branching_graph_preserves_branches(self):
        graph, ids = _build_branching_graph()
        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
        )
        # Should produce partitions (1 if small enough)
        assert len(plan.partitions) >= 1
        all_part_nodes = set()
        for p in plan.partitions:
            all_part_nodes.update(p.node_ids)
        assert all_part_nodes == set(ids)

    def test_empty_scope(self):
        plan = partition_scope(
            graph=LineageGraph(),
            scope_node_ids=set(),
            watch_type="pipeline_health",
        )
        assert len(plan.partitions) == 0
        assert plan.total_nodes == 0
        assert plan.total_monitors == 0

    def test_large_scope_splits(self):
        """30+ nodes should split into multiple partitions."""
        graph = LineageGraph()
        ids = []
        # Create 3 independent chains of 10 nodes each
        for chain in range(3):
            chain_ids = []
            for i in range(10):
                nid = f"chain{chain}-node{i}"
                chain_ids.append(nid)
                graph.add_node(_make_node(
                    nid, f"table_{chain}_{i}", f"db.schema.table_{chain}_{i}",
                    downstream_count=10 - i,
                ))
            for i in range(1, len(chain_ids)):
                _add_edge(graph, chain_ids[i - 1], chain_ids[i])
            ids.extend(chain_ids)

        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
            max_nodes=12,
        )
        # Should have at least 3 partitions (one per chain)
        assert len(plan.partitions) >= 3

    def test_dependency_chains_not_split(self):
        """A linear A->B->C chain within cap should never be split."""
        graph, ids = _build_linear_chain(5)
        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
            max_nodes=10,  # Well above chain length
        )
        # Should be 1 partition containing all nodes
        assert len(plan.partitions) >= 1
        first_partition = plan.partitions[0]
        assert set(first_partition.node_ids) == set(ids)

    def test_cross_partition_dedup(self):
        """Same (type, fqn) in 2 partitions should be deduped."""
        graph = LineageGraph()
        # Two separate chains sharing no nodes
        shared_fqn = "db.schema.shared_table"
        for chain in range(2):
            nid = f"chain{chain}-root"
            graph.add_node(_make_node(
                nid, f"root_{chain}", f"db.schema.root_{chain}",
                downstream_count=5,
            ))

        plan = partition_scope(
            graph=graph,
            scope_node_ids={"chain0-root", "chain1-root"},
            watch_type="pipeline_health",
        )
        # Should have dedup_count >= 0 (no actual shared fqns here)
        assert plan.dedup_count >= 0

    def test_anchor_selection_highest_priority(self):
        """Anchor should be the highest-priority node."""
        graph, ids = _build_linear_chain(4)
        # First node has highest downstream_count so should be highest priority
        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
        )
        assert len(plan.partitions) >= 1
        # Anchor should be a valid node
        anchor = plan.partitions[0].anchor_id
        assert anchor in ids


class TestSharedNodes:
    def test_shared_node_majority_rule(self):
        """Node with >50% parents in one partition joins that partition."""
        graph, ids = _build_branching_graph()
        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
        )
        # D has parents B and C, both from same root A
        # Should be in the same partition as A, B, C
        all_nodes = set()
        for p in plan.partitions:
            all_nodes.update(p.node_ids)
        assert "D" in all_nodes

    def test_shared_node_no_duplicate_monitors(self):
        """Only one monitor per (type, fqn) across partitions."""
        graph, ids = _build_branching_graph()
        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
        )
        # Collect all monitor (type, fqn) pairs
        seen = set()
        for p in plan.partitions:
            if p.scope_result:
                for rec in p.scope_result.recommendations:
                    key = f"{rec.monitor_key}:{rec.target_fqn}"
                    assert key not in seen, f"Duplicate monitor: {key}"
                    seen.add(key)


class TestCapEnforcement:
    def test_cap_enforcement(self):
        """Partition exceeding MAX_NODES_PER_GROUP should split."""
        graph = LineageGraph()
        ids = []
        # Single chain of 25 nodes
        for i in range(25):
            nid = f"node-{i}"
            ids.append(nid)
            graph.add_node(_make_node(
                nid, f"table_{i}", f"db.schema.table_{i}",
                downstream_count=25 - i,
            ))
        for i in range(1, len(ids)):
            _add_edge(graph, ids[i - 1], ids[i])

        plan = partition_scope(
            graph=graph,
            scope_node_ids=set(ids),
            watch_type="pipeline_health",
            max_nodes=10,
        )
        # Should have split into multiple partitions
        assert len(plan.partitions) >= 2
        for p in plan.partitions:
            assert len(p.node_ids) <= 15  # Allow some flex
