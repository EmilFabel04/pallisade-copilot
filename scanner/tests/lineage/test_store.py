"""
Tests for GraphStore query API with filtering.
"""

import os
import pytest

from scanner.lineage.engine.store import GraphStore, Filters, CoverageStats
from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    NodeType,
    PlatformDomain,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG_PATH = os.path.join(FIXTURES_DIR, "config.yml")


@pytest.fixture
def built_store():
    """Build a graph from all fixtures."""
    store = GraphStore()
    store.build_graph_from_yaml(CONFIG_PATH)
    return store


class TestGraphBuild:
    def test_build_from_yaml(self, built_store):
        assert built_store.graph is not None
        assert len(built_store.graph.nodes) > 0
        assert len(built_store.graph.edges) > 0

    def test_build_has_resolution_stats(self, built_store):
        assert built_store.resolution_stats is not None

    def test_multiple_adapters_contribute(self, built_store):
        """Nodes from all three adapters should be present."""
        platforms = {n.platform for n in built_store.graph.nodes.values()}
        # At least warehouse (postgres) and transform (dbt) should be present
        assert len(platforms) >= 2


class TestUpstreamDownstream:
    def test_get_upstream(self, built_store):
        # Find a node that should have upstream
        for node_id, node in built_store.graph.nodes.items():
            if node.name == "dim_customers" and node.platform_domain == PlatformDomain.TRANSFORM:
                upstream = built_store.get_upstream(node_id, depth=3)
                assert len(upstream) >= 1
                return
        pytest.skip("dim_customers transform node not found")

    def test_get_downstream(self, built_store):
        # Find a source node
        for node_id, node in built_store.graph.nodes.items():
            if node.name == "customers" and node.platform_domain == PlatformDomain.WAREHOUSE:
                downstream = built_store.get_downstream(node_id, depth=5)
                assert len(downstream) >= 1
                return
        pytest.skip("customers warehouse node not found")

    def test_nonexistent_node_returns_empty(self, built_store):
        assert built_store.get_upstream("nonexistent_id") == []
        assert built_store.get_downstream("nonexistent_id") == []


class TestFiltering:
    def test_filter_by_lineage_level(self, built_store):
        """Only return nodes connected by table-level edges."""
        filters = Filters(lineage_levels={LineageLevel.TABLE})
        # This tests that the filter struct is accepted
        for node_id in list(built_store.graph.nodes.keys())[:3]:
            result = built_store.get_upstream(node_id, depth=2, filters=filters)
            # Result should be a list (possibly empty)
            assert isinstance(result, list)

    def test_filter_by_platform_domain(self, built_store):
        filters = Filters(platform_domains={PlatformDomain.WAREHOUSE})
        for node_id in list(built_store.graph.nodes.keys())[:3]:
            result = built_store.get_upstream(node_id, depth=2, filters=filters)
            for n in result:
                assert n.platform_domain == PlatformDomain.WAREHOUSE

    def test_filter_by_asset_kind(self, built_store):
        filters = Filters(asset_kinds={AssetKind.TABLE})
        for node_id in list(built_store.graph.nodes.keys())[:3]:
            result = built_store.get_upstream(node_id, depth=2, filters=filters)
            for n in result:
                assert n.asset_kind == AssetKind.TABLE

    def test_filter_by_min_confidence(self, built_store):
        filters = Filters(min_confidence=0.9)
        # This should work without error
        sub = built_store.subgraph(
            list(built_store.graph.nodes.keys())[:2],
            depth=2,
            filters=filters,
        )
        for edge in sub.edges.values():
            assert edge.confidence >= 0.9

    def test_filter_by_system(self, built_store):
        filters = Filters(systems={"dbt"})
        for node_id in list(built_store.graph.nodes.keys())[:3]:
            result = built_store.get_upstream(node_id, depth=2, filters=filters)
            for n in result:
                assert n.platform == "dbt"

    def test_exclude_systems(self, built_store):
        filters = Filters(exclude_systems={"looker"})
        for node_id in list(built_store.graph.nodes.keys())[:3]:
            result = built_store.get_downstream(node_id, depth=2, filters=filters)
            for n in result:
                assert n.platform != "looker"


class TestBlastRadius:
    def test_blast_radius_structure(self, built_store):
        node_id = list(built_store.graph.nodes.keys())[0]
        result = built_store.blast_radius(node_id)
        assert "total_downstream" in result
        assert "by_kind" in result
        assert "by_domain" in result
        assert isinstance(result["total_downstream"], int)

    def test_blast_radius_with_filters(self, built_store):
        node_id = list(built_store.graph.nodes.keys())[0]
        filters = Filters(min_confidence=0.5)
        result = built_store.blast_radius(node_id, filters=filters)
        assert isinstance(result["total_downstream"], int)


class TestSubgraph:
    def test_subgraph_extraction(self, built_store):
        seeds = list(built_store.graph.nodes.keys())[:2]
        sub = built_store.subgraph(seeds, depth=2)
        assert len(sub.nodes) >= 2
        # All edges should reference nodes in the subgraph
        for edge in sub.edges.values():
            assert edge.source_id in sub.nodes
            assert edge.target_id in sub.nodes


class TestExplainEdge:
    def test_explain_existing_edge(self, built_store):
        if not built_store.graph.edges:
            pytest.skip("No edges in graph")
        edge_id = list(built_store.graph.edges.keys())[0]
        result = built_store.explain_edge(edge_id)
        assert "edge_id" in result
        assert "confidence" in result
        assert "evidence" in result
        assert "lineage_level" in result

    def test_explain_nonexistent_edge(self, built_store):
        result = built_store.explain_edge("nonexistent")
        assert "error" in result


class TestCoverageStats:
    def test_stats_structure(self, built_store):
        stats = built_store.get_stats()
        assert isinstance(stats, CoverageStats)
        assert stats.total_nodes > 0
        assert stats.total_edges >= 0
        assert 0 <= stats.coverage_table <= 1.0
        assert 0 <= stats.coverage_column <= 1.0
        assert 0 <= stats.coverage_tool <= 1.0

    def test_stats_confidence_distribution(self, built_store):
        stats = built_store.get_stats()
        total_pct = stats.high_confidence_pct + stats.medium_confidence_pct + stats.low_confidence_pct
        # Should approximately sum to 1.0 (ratios, not percentages)
        assert 0.99 <= total_pct <= 1.01 or stats.total_edges == 0

    def test_stats_to_dict(self, built_store):
        stats = built_store.get_stats()
        d = stats.to_dict()
        assert "total_nodes" in d
        assert "coverage_table" in d
        assert "resolution_stats" in d
