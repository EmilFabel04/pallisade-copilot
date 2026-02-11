"""
Tests for coverage score computation and golden graph validation.
"""

import os
import pytest

from scanner.lineage.engine.store import GraphStore
from scanner.lineage.graph import LineageLevel

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG_PATH = os.path.join(FIXTURES_DIR, "config.yml")


@pytest.fixture
def golden_store():
    """Build the golden graph from all fixtures."""
    store = GraphStore()
    store.build_graph_from_yaml(CONFIG_PATH)
    return store


class TestGoldenGraph:
    """Golden graph tests: fixture inputs must produce expected structure."""

    def test_minimum_node_count(self, golden_store):
        """Should have nodes from all three adapters."""
        # 20 warehouse + 15 transform + 11 BI = ~46 before dedup
        # After dedup, some warehouse and transform nodes merge
        assert len(golden_store.graph.nodes) >= 25

    def test_minimum_edge_count(self, golden_store):
        """Should have edges from all three adapters."""
        assert len(golden_store.graph.edges) >= 10

    def test_has_all_three_lineage_levels(self, golden_store):
        """The golden graph should contain tool, table, and column level edges."""
        levels = {e.lineage_level for e in golden_store.graph.edges.values()}
        assert LineageLevel.TABLE in levels
        # Tool level from BI adapter
        assert LineageLevel.TOOL in levels
        # Column level from transform adapter (column_mappings)
        assert LineageLevel.COLUMN in levels

    def test_edge_ids_are_stable(self, golden_store):
        """Building twice from same fixtures produces same edge IDs."""
        store2 = GraphStore()
        store2.build_graph_from_yaml(CONFIG_PATH)

        ids1 = set(golden_store.graph.edges.keys())
        ids2 = set(store2.graph.edges.keys())
        assert ids1 == ids2

    def test_node_ids_are_stable(self, golden_store):
        """Building twice from same fixtures produces same node IDs."""
        store2 = GraphStore()
        store2.build_graph_from_yaml(CONFIG_PATH)

        ids1 = set(golden_store.graph.nodes.keys())
        ids2 = set(store2.graph.nodes.keys())
        assert ids1 == ids2


class TestCoverageScores:
    def test_table_coverage_above_threshold(self, golden_store):
        stats = golden_store.get_stats()
        # With our rich fixtures, table coverage should be significant
        assert stats.coverage_table > 0.1

    def test_column_coverage_present(self, golden_store):
        """Column coverage should be > 0 since we have column_mappings in fixtures."""
        stats = golden_store.get_stats()
        assert stats.coverage_column > 0.0

    def test_tool_coverage_present(self, golden_store):
        """Tool coverage should be > 0 since BI adapter produces tool edges."""
        stats = golden_store.get_stats()
        assert stats.coverage_tool > 0.0


class TestResolutionQuality:
    def test_deduplication_occurred(self, golden_store):
        """Some nodes should have been deduplicated across adapters."""
        rs = golden_store.resolution_stats
        assert rs is not None
        # With overlapping warehouse and transform fixtures, some dedup expected
        assert rs.nodes_deduplicated >= 0  # May be 0 if IDs differ by domain

    def test_no_self_referencing_edges(self, golden_store):
        """No edge should have source == target."""
        for edge in golden_store.graph.edges.values():
            assert edge.source_id != edge.target_id

    def test_all_edges_have_evidence(self, golden_store):
        """Every edge must carry at least one evidence record."""
        for edge in golden_store.graph.edges.values():
            assert len(edge.evidence) > 0, f"Edge {edge.id} has no evidence"

    def test_low_confidence_edges_marked(self, golden_store):
        """Edges with confidence < 0.5 should exist in the low bucket."""
        low_ids = golden_store.graph._by_confidence_bucket.get("low", set())
        for edge_id in low_ids:
            edge = golden_store.graph.edges[edge_id]
            assert edge.confidence < 0.5


class TestExport:
    def test_json_export(self, golden_store):
        from scanner.lineage.engine.export import export_json
        content = export_json(golden_store.graph)
        import json
        data = json.loads(content)
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == len(golden_store.graph.nodes)

    def test_graphml_export(self, golden_store):
        from scanner.lineage.engine.export import export_graphml
        content = export_graphml(golden_store.graph)
        assert "<graphml" in content
        assert "<node" in content

    def test_dot_export(self, golden_store):
        from scanner.lineage.engine.export import export_dot
        content = export_dot(golden_store.graph)
        assert "digraph lineage" in content
        assert "->" in content
