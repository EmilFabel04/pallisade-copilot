"""Tests for cross-link queries: get_cross_links(), get_control_plane_subgraph().

Focused on the GraphStore methods that PR4's copilot tools depend on.
"""

import pytest

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

def _node(nid: str, name: str, ntype: NodeType,
          domain: PlatformDomain = PlatformDomain.WAREHOUSE,
          kind: AssetKind = AssetKind.TABLE,
          raw_metadata: dict | None = None) -> LineageNode:
    return LineageNode(
        id=nid, name=name, fqn=name,
        node_type=ntype,
        platform_domain=domain,
        asset_kind=kind,
        raw_metadata=raw_metadata or {},
    )


def _edge(eid: str, src: str, tgt: str,
          etype: EdgeType = EdgeType.DEPENDS_ON,
          level: LineageLevel = LineageLevel.TABLE,
          plane: LinePlane = LinePlane.DATA,
          conf: float = 1.0) -> LineageEdge:
    return LineageEdge(
        id=eid, source_id=src, target_id=tgt,
        edge_type=etype, lineage_level=level,
        plane=plane, confidence=conf,
        evidence=[Evidence(adapter_id="test", source_ref="test")],
    )


def _build_mixed_graph() -> LineageGraph:
    """Graph with data, control, and cross-plane edges.

    Structure:
        DAG(etl_dag) --CONTROL--> TASK(extract) --CONTROL--> TASK(load)
        raw_table --CROSS(READS_FROM)--> extract
        load --CROSS(WRITES_TO)--> output_table
        raw_table --DATA--> output_table
    """
    g = LineageGraph()
    g.add_node(_node("dag1", "etl_dag", NodeType.DAG,
                      PlatformDomain.ORCHESTRATION, AssetKind.JOB))
    g.add_node(_node("t1", "extract", NodeType.TASK,
                      PlatformDomain.ORCHESTRATION, AssetKind.TASK,
                      raw_metadata={"dag_id": "etl_dag"}))
    g.add_node(_node("t2", "load", NodeType.TASK,
                      PlatformDomain.ORCHESTRATION, AssetKind.TASK,
                      raw_metadata={"dag_id": "etl_dag"}))
    g.add_node(_node("raw", "raw_table", NodeType.TABLE))
    g.add_node(_node("out", "output_table", NodeType.TABLE))

    # Control-plane
    g.add_edge(_edge("e1", "dag1", "t1", EdgeType.DEPENDS_ON,
                      LineageLevel.TOOL, LinePlane.CONTROL))
    g.add_edge(_edge("e2", "dag1", "t2", EdgeType.DEPENDS_ON,
                      LineageLevel.TOOL, LinePlane.CONTROL))
    g.add_edge(_edge("e3", "t1", "t2", EdgeType.DEPENDS_ON,
                      LineageLevel.TOOL, LinePlane.CONTROL))

    # Cross-plane
    g.add_edge(_edge("e4", "raw", "t1", EdgeType.READS_FROM,
                      LineageLevel.TABLE, LinePlane.CROSS))
    g.add_edge(_edge("e5", "t2", "out", EdgeType.WRITES_TO,
                      LineageLevel.TABLE, LinePlane.CROSS))

    # Data-plane
    g.add_edge(_edge("e6", "raw", "out", EdgeType.DEPENDS_ON,
                      LineageLevel.TABLE, LinePlane.DATA))

    return g


@pytest.fixture
def store():
    g = _build_mixed_graph()
    s = GraphStore()
    s.graph = g
    return s


# ---------------------------------------------------------------------------
# get_cross_links
# ---------------------------------------------------------------------------

class TestGetCrossLinks:
    def test_returns_cross_edges_for_table(self, store: GraphStore):
        edges = store.get_cross_links("raw")
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.READS_FROM
        assert edges[0].plane == LinePlane.CROSS

    def test_returns_cross_edges_for_task(self, store: GraphStore):
        edges = store.get_cross_links("t1")
        assert len(edges) == 1
        assert edges[0].source_id == "raw"

    def test_returns_cross_edges_for_output_table(self, store: GraphStore):
        edges = store.get_cross_links("out")
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.WRITES_TO
        assert edges[0].source_id == "t2"

    def test_no_cross_links_for_dag(self, store: GraphStore):
        """DAG itself has no cross-plane edges, only control-plane."""
        edges = store.get_cross_links("dag1")
        assert len(edges) == 0

    def test_nonexistent_node_returns_empty(self, store: GraphStore):
        edges = store.get_cross_links("nonexistent")
        assert edges == []


# ---------------------------------------------------------------------------
# get_control_plane_subgraph
# ---------------------------------------------------------------------------

class TestGetControlPlaneSubgraph:
    def test_returns_all_orchestration_nodes(self, store: GraphStore):
        sub = store.get_control_plane_subgraph()
        node_types = {n.node_type for n in sub.nodes.values()}
        assert NodeType.DAG in node_types
        assert NodeType.TASK in node_types

    def test_includes_cross_linked_tables(self, store: GraphStore):
        sub = store.get_control_plane_subgraph()
        node_names = {n.name for n in sub.nodes.values()}
        assert "raw_table" in node_names
        assert "output_table" in node_names

    def test_subgraph_has_control_and_cross_edges(self, store: GraphStore):
        sub = store.get_control_plane_subgraph()
        planes = {e.plane for e in sub.edges.values()}
        assert LinePlane.CONTROL in planes
        assert LinePlane.CROSS in planes
        # Data-plane edge should NOT be in the control-plane subgraph
        assert LinePlane.DATA not in planes

    def test_filter_by_dag_name(self, store: GraphStore):
        sub = store.get_control_plane_subgraph(dag_id="etl_dag")
        # Should contain DAG + tasks + cross-linked tables
        assert "dag1" in sub.nodes
        assert "t1" in sub.nodes
        assert "t2" in sub.nodes

    def test_nonexistent_dag_returns_empty(self, store: GraphStore):
        sub = store.get_control_plane_subgraph(dag_id="nonexistent")
        assert len(sub.nodes) == 0
        assert len(sub.edges) == 0


# ---------------------------------------------------------------------------
# Plane filtering via Filters + _edge_passes
# ---------------------------------------------------------------------------

def _filtered_edges(store: GraphStore, filters: Filters):
    """Get edges from the graph that pass the given filters."""
    return [
        e for e in store.graph.edges.values()
        if store._edge_passes(e, filters)
    ]


class TestPlaneFiltering:
    def test_filter_data_plane_only(self, store: GraphStore):
        f = Filters(planes={LinePlane.DATA})
        edges = _filtered_edges(store, f)
        for e in edges:
            assert e.plane == LinePlane.DATA
        assert len(edges) == 1  # only raw->out

    def test_filter_control_plane_only(self, store: GraphStore):
        f = Filters(planes={LinePlane.CONTROL})
        edges = _filtered_edges(store, f)
        for e in edges:
            assert e.plane == LinePlane.CONTROL
        assert len(edges) == 3  # dag->t1, dag->t2, t1->t2

    def test_filter_cross_plane_only(self, store: GraphStore):
        f = Filters(planes={LinePlane.CROSS})
        edges = _filtered_edges(store, f)
        for e in edges:
            assert e.plane == LinePlane.CROSS
        assert len(edges) == 2  # raw->t1, t2->out

    def test_filter_multiple_planes(self, store: GraphStore):
        f = Filters(planes={LinePlane.DATA, LinePlane.CROSS})
        edges = _filtered_edges(store, f)
        planes = {e.plane for e in edges}
        assert planes == {LinePlane.DATA, LinePlane.CROSS}
        assert len(edges) == 3

    def test_no_plane_filter_returns_all(self, store: GraphStore):
        all_edges = list(store.graph.edges.values())
        assert len(all_edges) == 6
