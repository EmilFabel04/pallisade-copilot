"""Tests for plane-filtered BFS traversal in LineageGraph.

Validates that get_upstream(planes=...) and get_downstream(planes=...) restrict
BFS to edges in specified planes, matching data-lineage surface visibility.
"""

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
          kind: AssetKind = AssetKind.TABLE) -> LineageNode:
    return LineageNode(
        id=nid, name=name, fqn=name,
        node_type=ntype,
        platform_domain=domain,
        asset_kind=kind,
        raw_metadata={},
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


def _build_graph() -> LineageGraph:
    """Graph with data, control, and cross-plane edges.

    Structure:
        raw_table --DATA--> staging --DATA--> output_table
        airflow_task --CROSS(WRITES_TO)--> staging
        airflow_dag --CONTROL--> airflow_task
        connector --CROSS(READS_FROM)--> raw_table
    """
    g = LineageGraph()
    g.add_node(_node("raw", "raw_table", NodeType.TABLE))
    g.add_node(_node("stg", "staging", NodeType.TABLE))
    g.add_node(_node("out", "output_table", NodeType.TABLE))
    g.add_node(_node("task1", "airflow_task", NodeType.TASK,
                      PlatformDomain.ORCHESTRATION, AssetKind.TASK))
    g.add_node(_node("dag1", "airflow_dag", NodeType.DAG,
                      PlatformDomain.ORCHESTRATION, AssetKind.JOB))
    g.add_node(_node("conn1", "fivetran_connector", NodeType.CONNECTOR,
                      PlatformDomain.INGESTION, AssetKind.CONNECTOR))

    # DATA plane: raw -> staging -> output
    g.add_edge(_edge("d1", "raw", "stg", plane=LinePlane.DATA))
    g.add_edge(_edge("d2", "stg", "out", plane=LinePlane.DATA))

    # CROSS plane: task writes to staging, connector reads raw
    g.add_edge(_edge("x1", "task1", "stg", EdgeType.WRITES_TO,
                      LineageLevel.TOOL, LinePlane.CROSS))
    g.add_edge(_edge("x2", "conn1", "raw", EdgeType.WRITES_TO,
                      LineageLevel.TOOL, LinePlane.CROSS))

    # CONTROL plane: dag -> task
    g.add_edge(_edge("c1", "dag1", "task1", EdgeType.DEPENDS_ON,
                      LineageLevel.TOOL, LinePlane.CONTROL))

    return g


# ---------------------------------------------------------------------------
# get_upstream with plane filter
# ---------------------------------------------------------------------------

class TestGetUpstreamPlaneFilter:
    def test_data_plane_only_excludes_cross_link_nodes(self):
        """BFS with planes={DATA} should not reach orchestration nodes via CROSS edges."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes={LinePlane.DATA})
        ids = {n.id for n in upstream}
        assert ids == {"raw", "stg"}
        assert "task1" not in ids
        assert "dag1" not in ids
        assert "conn1" not in ids

    def test_no_plane_filter_returns_all_reachable(self):
        """BFS without planes (None) should traverse all edges — backward compat."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes=None)
        ids = {n.id for n in upstream}
        # output -> staging (DATA), staging <- task1 (CROSS), task1 <- dag1 (CONTROL),
        # staging <- raw (DATA), raw <- conn1 (CROSS)
        assert "raw" in ids
        assert "stg" in ids
        assert "task1" in ids
        assert "dag1" in ids
        assert "conn1" in ids

    def test_cross_only_reaches_cross_linked_nodes(self):
        """BFS with planes={CROSS} should only follow CROSS edges."""
        g = _build_graph()
        # From staging upstream via CROSS: task1 writes to staging
        upstream = g.get_upstream("stg", depth=10, planes={LinePlane.CROSS})
        ids = {n.id for n in upstream}
        assert "task1" in ids
        # task1 -> dag1 is CONTROL, not CROSS, so dag1 should not be reached
        assert "dag1" not in ids
        # raw -> stg is DATA, not CROSS, so raw should not be reached
        assert "raw" not in ids

    def test_data_plane_depth_limited(self):
        """Plane-filtered BFS should still respect depth limits."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=1, planes={LinePlane.DATA})
        ids = {n.id for n in upstream}
        assert ids == {"stg"}
        assert "raw" not in ids

    def test_airflow_task_only_reachable_via_cross(self):
        """Regression: an Airflow task connected only via CROSS edge must not
        appear when BFS is restricted to DATA plane."""
        g = _build_graph()
        upstream = g.get_upstream("stg", depth=10, planes={LinePlane.DATA})
        ids = {n.id for n in upstream}
        assert ids == {"raw"}
        assert "task1" not in ids

    def test_empty_planes_set_returns_nothing(self):
        """An empty planes set means no edges are eligible — BFS returns nothing."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes=set())
        assert upstream == []

    def test_multiple_planes_union(self):
        """planes={DATA, CROSS} should follow both DATA and CROSS edges."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes={LinePlane.DATA, LinePlane.CROSS})
        ids = {n.id for n in upstream}
        assert "raw" in ids
        assert "stg" in ids
        assert "task1" in ids
        assert "conn1" in ids
        # dag1 is only reachable via CONTROL, so excluded
        assert "dag1" not in ids


# ---------------------------------------------------------------------------
# get_downstream with plane filter
# ---------------------------------------------------------------------------

class TestGetDownstreamPlaneFilter:
    def test_data_plane_only(self):
        """BFS downstream with planes={DATA} should stay on data plane."""
        g = _build_graph()
        downstream = g.get_downstream("raw", depth=10, planes={LinePlane.DATA})
        ids = {n.id for n in downstream}
        assert ids == {"stg", "out"}
        assert "task1" not in ids

    def test_no_plane_filter_returns_all_reachable(self):
        """BFS without planes should traverse all edges."""
        g = _build_graph()
        downstream = g.get_downstream("raw", depth=10, planes=None)
        ids = {n.id for n in downstream}
        assert "stg" in ids
        assert "out" in ids


# ---------------------------------------------------------------------------
# GraphStore integration
# ---------------------------------------------------------------------------

class TestGraphStorePlaneFilter:
    def test_upstream_with_plane_filter_via_graphstore(self):
        """GraphStore.get_upstream with Filters.planes should restrict BFS."""
        g = _build_graph()
        store = GraphStore.__new__(GraphStore)
        store.graph = g
        store._adapter_registry = None

        filters = Filters(planes={LinePlane.DATA})
        nodes = store.get_upstream("out", depth=10, filters=filters)
        ids = {n.id for n in nodes}
        assert ids == {"raw", "stg"}
        assert "task1" not in ids
        assert "dag1" not in ids

    def test_upstream_without_plane_filter_via_graphstore(self):
        """GraphStore.get_upstream without planes should return all reachable."""
        g = _build_graph()
        store = GraphStore.__new__(GraphStore)
        store.graph = g
        store._adapter_registry = None

        nodes = store.get_upstream("out", depth=10, filters=None)
        ids = {n.id for n in nodes}
        assert "task1" in ids
        assert "dag1" in ids


# ---------------------------------------------------------------------------
# Regression: connector node not in data lineage must not appear in bundle
# ---------------------------------------------------------------------------

class TestBundleRegressions:
    def test_connector_node_excluded_from_data_plane_upstream(self):
        """A connector/tool node reachable only via CROSS edge must not appear
        in DATA-plane-only upstream results. This is the exact bug that caused
        bundle monitors to include hidden nodes."""
        g = _build_graph()
        upstream = g.get_upstream("raw", depth=10, planes={LinePlane.DATA})
        ids = {n.id for n in upstream}
        # raw has no DATA-plane upstream
        assert ids == set()
        # connector is only linked via CROSS — must NOT appear
        assert "conn1" not in ids

    def test_orchestration_dag_excluded_from_data_plane_upstream(self):
        """An orchestration DAG must not appear in DATA-plane upstream even
        if it is transitively reachable through CROSS + CONTROL edges."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes={LinePlane.DATA})
        ids = {n.id for n in upstream}
        assert "dag1" not in ids
        assert "task1" not in ids


# ---------------------------------------------------------------------------
# End-to-end: simulates the full bundle upstream discovery pipeline
# (plane-filtered BFS + visibility post-filter matching CreateTaskModal logic)
# ---------------------------------------------------------------------------

def _is_visible_in_data_lineage(node: LineageNode) -> bool:
    """Python equivalent of the frontend isVisibleInDataLineage filter.

    Mirrors CreateTaskModal.tsx + ViewBuilder data-plane view rules:
    only canonical_type 'dataset' or 'semantic' appear on the canvas.
    """
    from scanner.lineage.engine.canonical import map_node_type
    ct = (node.canonical_type or map_node_type(node).value).lower()
    return ct in ("dataset", "semantic")


class TestEndToEndBundleDiscovery:
    """Simulates the full bundle upstream discovery pipeline as the frontend
    would execute it: plane-filtered BFS + visibility post-filter."""

    def test_mixed_graph_bundle_discovery(self):
        """Starting from output_table, bundle should only find data assets."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes={LinePlane.DATA})
        visible = [n for n in upstream if _is_visible_in_data_lineage(n)]
        ids = {n.id for n in visible}
        assert ids == {"raw", "stg"}

    def test_no_plane_filter_leaks_orchestration_nodes(self):
        """Without plane filter, orchestration nodes leak through — this is
        the pre-fix behavior that the bundle code must avoid."""
        g = _build_graph()
        upstream = g.get_upstream("out", depth=10, planes=None)
        ids = {n.id for n in upstream}
        # Orchestration nodes ARE reachable without plane filter
        assert "task1" in ids
        assert "dag1" in ids
        # But the visibility post-filter catches them
        visible = [n for n in upstream if _is_visible_in_data_lineage(n)]
        visible_ids = {n.id for n in visible}
        assert "task1" not in visible_ids
        assert "dag1" not in visible_ids

    def test_canonical_type_filter_excludes_connectors(self):
        """The canonical_type whitelist (dataset+semantic) excludes connector
        nodes even if they are reachable. Connectors map to canonical type
        'job', not 'dataset'."""
        g = _build_graph()
        all_planes = g.get_upstream("out", depth=10, planes=None)
        visible = [n for n in all_planes if _is_visible_in_data_lineage(n)]
        visible_ids = {n.id for n in visible}
        # conn1 is a CONNECTOR → canonical_type 'job', not 'dataset'
        assert "conn1" not in visible_ids
        # task1 is a TASK → canonical_type 'job', not 'dataset'
        assert "task1" not in visible_ids
        # dag1 is a DAG → canonical_type 'job', not 'dataset'
        assert "dag1" not in visible_ids
        # Only actual data assets remain
        assert visible_ids == {"raw", "stg"}

    def test_bi_node_finds_upstream_via_cross_edges(self):
        """BI→table edges use CROSS plane. With planes={DATA, CROSS} and the
        canonical type whitelist, a dashboard should find its upstream tables
        but NOT orchestration nodes also reachable via CROSS."""
        g = _build_graph()
        # Add a dashboard node connected to output_table via CROSS edge
        g.add_node(_node("dash1", "sales_dashboard", NodeType.DASHBOARD,
                          PlatformDomain.BI, AssetKind.DASHBOARD))
        # Edge direction: table → dashboard (table SERVES dashboard)
        # upstream of dash1 = out
        g.add_edge(_edge("x3", "out", "dash1", EdgeType.READS_FROM,
                          LineageLevel.TOOL, LinePlane.CROSS))

        # With DATA+CROSS, dashboard reaches tables AND orchestration nodes
        upstream = g.get_upstream("dash1", depth=10,
                                  planes={LinePlane.DATA, LinePlane.CROSS})
        all_ids = {n.id for n in upstream}
        assert "out" in all_ids
        assert "raw" in all_ids
        assert "stg" in all_ids

        # But canonical type whitelist excludes orchestration nodes
        visible = [n for n in upstream if _is_visible_in_data_lineage(n)]
        visible_ids = {n.id for n in visible}
        assert visible_ids == {"raw", "stg", "out"}
        assert "task1" not in visible_ids
        assert "conn1" not in visible_ids
        assert "dag1" not in visible_ids
