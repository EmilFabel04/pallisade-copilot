"""
Tests for LinePlane classification on edges and plane-aware filtering.

Covers:
- LinePlane enum serialization/deserialization
- LineageEdge plane field defaults and persistence
- Filters.planes filtering in GraphStore
- _by_plane index population in LineageGraph
- get_cross_links() query
- get_control_plane_subgraph() query
"""

import pytest
from datetime import datetime

from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.store import Filters, GraphStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(node_id: str, name: str, node_type: NodeType,
               domain: PlatformDomain = PlatformDomain.WAREHOUSE,
               kind: AssetKind = AssetKind.TABLE,
               raw_metadata: dict | None = None) -> LineageNode:
    return LineageNode(
        id=node_id, name=name, fqn=name,
        node_type=node_type,
        platform_domain=domain,
        asset_kind=kind,
        raw_metadata=raw_metadata or {},
    )


def _make_edge(edge_id: str, src: str, tgt: str,
               edge_type: EdgeType = EdgeType.DEPENDS_ON,
               level: LineageLevel = LineageLevel.TABLE,
               plane: LinePlane = LinePlane.DATA,
               confidence: float = 1.0) -> LineageEdge:
    return LineageEdge(
        id=edge_id, source_id=src, target_id=tgt,
        edge_type=edge_type, lineage_level=level,
        plane=plane, confidence=confidence,
        evidence=[Evidence(adapter_id="test", source_ref="test")],
    )


def _build_test_graph() -> LineageGraph:
    """Build a graph with data-plane, control-plane, and cross-plane edges.

    Structure:
        DAG(dag1) --CONTROL--> TASK(task1) --CONTROL--> TASK(task2)
        table_a --CROSS(READS_FROM)--> task1
        task2 --CROSS(WRITES_TO)--> table_b
        table_a --DATA(DEPENDS_ON)--> table_b
    """
    g = LineageGraph()

    g.add_node(_make_node("dag1", "my_dag", NodeType.DAG,
                           PlatformDomain.ORCHESTRATION, AssetKind.JOB,
                           raw_metadata={"schedule": "@daily"}))
    g.add_node(_make_node("task1", "extract", NodeType.TASK,
                           PlatformDomain.ORCHESTRATION, AssetKind.TASK,
                           raw_metadata={"dag_id": "my_dag"}))
    g.add_node(_make_node("task2", "load", NodeType.TASK,
                           PlatformDomain.ORCHESTRATION, AssetKind.TASK,
                           raw_metadata={"dag_id": "my_dag"}))
    g.add_node(_make_node("table_a", "raw.events", NodeType.TABLE))
    g.add_node(_make_node("table_b", "analytics.summary", NodeType.TABLE))

    # Control-plane edges
    g.add_edge(_make_edge("e1", "dag1", "task1", EdgeType.DEPENDS_ON,
                          LineageLevel.TOOL, LinePlane.CONTROL))
    g.add_edge(_make_edge("e2", "task1", "task2", EdgeType.DEPENDS_ON,
                          LineageLevel.TOOL, LinePlane.CONTROL))

    # Cross-plane edges
    g.add_edge(_make_edge("e3", "table_a", "task1", EdgeType.READS_FROM,
                          LineageLevel.TABLE, LinePlane.CROSS))
    g.add_edge(_make_edge("e4", "task2", "table_b", EdgeType.WRITES_TO,
                          LineageLevel.TABLE, LinePlane.CROSS))

    # Data-plane edge
    g.add_edge(_make_edge("e5", "table_a", "table_b", EdgeType.DEPENDS_ON,
                          LineageLevel.TABLE, LinePlane.DATA))

    return g


# ---------------------------------------------------------------------------
# LinePlane enum basics
# ---------------------------------------------------------------------------

class TestLinePlaneEnum:
    def test_values(self):
        assert LinePlane.DATA.value == "data"
        assert LinePlane.CONTROL.value == "control"
        assert LinePlane.CROSS.value == "cross"

    def test_from_string(self):
        assert LinePlane("data") == LinePlane.DATA
        assert LinePlane("control") == LinePlane.CONTROL
        assert LinePlane("cross") == LinePlane.CROSS

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            LinePlane("invalid")


# ---------------------------------------------------------------------------
# LineageEdge plane field
# ---------------------------------------------------------------------------

class TestEdgePlaneField:
    def test_default_is_data(self):
        edge = LineageEdge(
            id="e", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
        )
        assert edge.plane == LinePlane.DATA

    def test_explicit_plane(self):
        edge = LineageEdge(
            id="e", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
            plane=LinePlane.CONTROL,
        )
        assert edge.plane == LinePlane.CONTROL

    def test_to_dict_includes_plane(self):
        edge = LineageEdge(
            id="e", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
            plane=LinePlane.CROSS,
        )
        d = edge.to_dict()
        assert d["plane"] == "cross"

    def test_to_dict_default_plane(self):
        edge = LineageEdge(
            id="e", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
        )
        d = edge.to_dict()
        assert d["plane"] == "data"


# ---------------------------------------------------------------------------
# LineageGraph serialization round-trip
# ---------------------------------------------------------------------------

class TestGraphSerialization:
    def test_round_trip_preserves_plane(self):
        g = _build_test_graph()
        data = g.to_dict()
        restored = LineageGraph.from_dict(data)

        for eid in ("e1", "e2"):
            assert restored.edges[eid].plane == LinePlane.CONTROL
        for eid in ("e3", "e4"):
            assert restored.edges[eid].plane == LinePlane.CROSS
        assert restored.edges["e5"].plane == LinePlane.DATA

    def test_missing_plane_defaults_to_data(self):
        """Old serialized graphs without 'plane' key deserialize as DATA."""
        data = {
            "nodes": [
                {"id": "a", "name": "a", "fqn": "a", "node_type": "table"},
                {"id": "b", "name": "b", "fqn": "b", "node_type": "table"},
            ],
            "edges": [
                {
                    "id": "e1", "source_id": "a", "target_id": "b",
                    "edge_type": "depends_on",
                    # No "plane" key — simulates old format
                },
            ],
        }
        g = LineageGraph.from_dict(data)
        assert g.edges["e1"].plane == LinePlane.DATA


# ---------------------------------------------------------------------------
# _by_plane index
# ---------------------------------------------------------------------------

class TestByPlaneIndex:
    def test_index_populated(self):
        g = _build_test_graph()
        assert "e1" in g._by_plane[LinePlane.CONTROL]
        assert "e2" in g._by_plane[LinePlane.CONTROL]
        assert "e3" in g._by_plane[LinePlane.CROSS]
        assert "e4" in g._by_plane[LinePlane.CROSS]
        assert "e5" in g._by_plane[LinePlane.DATA]

    def test_index_counts(self):
        g = _build_test_graph()
        assert len(g._by_plane[LinePlane.CONTROL]) == 2
        assert len(g._by_plane[LinePlane.CROSS]) == 2
        assert len(g._by_plane[LinePlane.DATA]) == 1


# ---------------------------------------------------------------------------
# Filters.planes
# ---------------------------------------------------------------------------

class TestPlaneFiltering:
    def test_filter_control_only(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        filters = Filters(planes={LinePlane.CONTROL})
        # All edges should pass or not based on plane
        passing = [e for e in g.edges.values() if store._edge_passes(e, filters)]
        assert len(passing) == 2
        assert all(e.plane == LinePlane.CONTROL for e in passing)

    def test_filter_data_only(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        filters = Filters(planes={LinePlane.DATA})
        passing = [e for e in g.edges.values() if store._edge_passes(e, filters)]
        assert len(passing) == 1
        assert passing[0].id == "e5"

    def test_filter_cross_only(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        filters = Filters(planes={LinePlane.CROSS})
        passing = [e for e in g.edges.values() if store._edge_passes(e, filters)]
        assert len(passing) == 2

    def test_filter_data_and_cross(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        filters = Filters(planes={LinePlane.DATA, LinePlane.CROSS})
        passing = [e for e in g.edges.values() if store._edge_passes(e, filters)]
        assert len(passing) == 3

    def test_no_plane_filter_passes_all(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        filters = Filters()  # No planes filter
        passing = [e for e in g.edges.values() if store._edge_passes(e, filters)]
        assert len(passing) == 5


# ---------------------------------------------------------------------------
# get_cross_links
# ---------------------------------------------------------------------------

class TestGetCrossLinks:
    def test_cross_links_for_table(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        links = store.get_cross_links("table_a")
        assert len(links) == 1
        assert links[0].id == "e3"
        assert links[0].plane == LinePlane.CROSS

    def test_cross_links_for_task(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        links = store.get_cross_links("task2")
        assert len(links) == 1
        assert links[0].id == "e4"

    def test_cross_links_empty_for_dag(self):
        """DAG only has CONTROL edges, no CROSS edges."""
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        links = store.get_cross_links("dag1")
        assert len(links) == 0

    def test_cross_links_no_graph(self):
        store = GraphStore()
        assert store.get_cross_links("anything") == []


# ---------------------------------------------------------------------------
# get_control_plane_subgraph
# ---------------------------------------------------------------------------

class TestControlPlaneSubgraph:
    def test_specific_dag(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        sub = store.get_control_plane_subgraph("my_dag")
        # Should include: dag1, task1, task2, and cross-linked tables
        assert "dag1" in sub.nodes
        assert "task1" in sub.nodes
        assert "task2" in sub.nodes
        assert "table_a" in sub.nodes  # cross-linked via e3
        assert "table_b" in sub.nodes  # cross-linked via e4

        # Should include CONTROL + CROSS edges
        edge_ids = set(sub.edges.keys())
        assert "e1" in edge_ids  # DAG→task1 (CONTROL)
        assert "e2" in edge_ids  # task1→task2 (CONTROL)
        assert "e3" in edge_ids  # table_a→task1 (CROSS)
        assert "e4" in edge_ids  # task2→table_b (CROSS)
        # Should NOT include data-plane edge
        assert "e5" not in edge_ids

    def test_all_dags(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        sub = store.get_control_plane_subgraph()
        assert "dag1" in sub.nodes
        assert "task1" in sub.nodes
        assert "task2" in sub.nodes

    def test_nonexistent_dag(self):
        g = _build_test_graph()
        store = GraphStore()
        store.graph = g

        sub = store.get_control_plane_subgraph("nonexistent")
        assert len(sub.nodes) == 0
        assert len(sub.edges) == 0

    def test_no_graph(self):
        store = GraphStore()
        sub = store.get_control_plane_subgraph("my_dag")
        assert len(sub.nodes) == 0


# ---------------------------------------------------------------------------
# New EdgeType values
# ---------------------------------------------------------------------------

class TestNewEdgeTypes:
    def test_produced_by(self):
        assert EdgeType.PRODUCED_BY.value == "produced_by"

    def test_materializes(self):
        assert EdgeType.MATERIALIZES.value == "materializes"

    def test_round_trip(self):
        edge = LineageEdge(
            id="e", source_id="a", target_id="b",
            edge_type=EdgeType.PRODUCED_BY,
            plane=LinePlane.CROSS,
        )
        d = edge.to_dict()
        assert d["edge_type"] == "produced_by"
        assert d["plane"] == "cross"
