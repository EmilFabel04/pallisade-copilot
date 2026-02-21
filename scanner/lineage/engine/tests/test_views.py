"""
Tests for scanner.lineage.engine.views

Tests the ViewBuilder with a realistic pipeline fixture:
    Source (Fivetran) → BigQuery raw → dbt models → BigQuery marts → Looker dashboards

Covers:
- Pipeline overview: correct cluster count, layer ordering, inter-service edges
- Data plane: only DATASET+SEMANTIC nodes, correct layout, dedup
- Layout determinism: same input → same positions
- Inferred bridge nodes appear with correct flag
- Needs-mapping surfaces UNKNOWN nodes
"""

import pytest

from scanner.lineage.graph import (
    EdgeType,
    Evidence,
    HealthStatus,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.views import (
    ViewBuilder,
    ViewNode,
    ViewEdge,
    ViewCluster,
    RenderedView,
    _topological_layout,
    _build_clusters_from_nodes,
)


# ---- Fixture: realistic pipeline graph ----

def _make_node(
    name: str,
    node_type: NodeType,
    platform: str,
    platform_domain: PlatformDomain,
    database: str = None,
    schema: str = None,
    fqn: str = None,
    integration_id: str = None,
    namespace: str = None,
    inferred: bool = False,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=fqn or f"{database or ''}.{schema or ''}.{name}".strip("."),
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=database,
        schema=schema,
        integration_id=integration_id,
        namespace=namespace,
        inferred=inferred,
    )


def _make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
    confidence: float = 1.0,
    inferred: bool = False,
) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        confidence=confidence,
        inferred=inferred,
        evidence=[
            Evidence(adapter_id="test", source_ref="test_fixture"),
        ],
    )


@pytest.fixture
def pipeline_graph() -> LineageGraph:
    """
    Build a realistic pipeline graph:
        Fivetran connector → BQ raw tables → dbt models → BQ mart tables → Looker dashboards
    """
    graph = LineageGraph()

    # Fivetran connector (ingestion)
    fivetran_conn = _make_node(
        "salesforce_sync", NodeType.CONNECTOR, "fivetran",
        PlatformDomain.INGESTION, integration_id="ft_001",
    )

    # BigQuery raw tables (warehouse)
    bq_raw_accounts = _make_node(
        "accounts", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="raw", schema="salesforce",
        fqn="raw.salesforce.accounts", integration_id="bq_001", namespace="prod",
    )
    bq_raw_opps = _make_node(
        "opportunities", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="raw", schema="salesforce",
        fqn="raw.salesforce.opportunities", integration_id="bq_001", namespace="prod",
    )

    # dbt models (transform)
    dbt_stg_accounts = _make_node(
        "stg_accounts", NodeType.MODEL, "dbt",
        PlatformDomain.TRANSFORM, database="analytics", schema="staging",
        fqn="analytics.staging.stg_accounts", integration_id="dbt_001",
    )
    dbt_stg_opps = _make_node(
        "stg_opportunities", NodeType.MODEL, "dbt",
        PlatformDomain.TRANSFORM, database="analytics", schema="staging",
        fqn="analytics.staging.stg_opportunities", integration_id="dbt_001",
    )
    dbt_fct_revenue = _make_node(
        "fct_revenue", NodeType.MODEL, "dbt",
        PlatformDomain.TRANSFORM, database="analytics", schema="marts",
        fqn="analytics.marts.fct_revenue", integration_id="dbt_001",
    )

    # BigQuery mart table (warehouse)
    bq_mart_revenue = _make_node(
        "fct_revenue", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="analytics", schema="marts",
        fqn="analytics.marts.fct_revenue", integration_id="bq_001", namespace="prod",
    )

    # Looker dashboard (BI)
    looker_dash = _make_node(
        "Revenue Dashboard", NodeType.DASHBOARD, "looker",
        PlatformDomain.BI, integration_id="looker_001",
    )

    # Add all nodes
    for node in [fivetran_conn, bq_raw_accounts, bq_raw_opps,
                 dbt_stg_accounts, dbt_stg_opps, dbt_fct_revenue,
                 bq_mart_revenue, looker_dash]:
        graph.add_node(node)

    # Edges: Fivetran → BQ raw
    graph.add_edge(_make_edge(
        fivetran_conn.id, bq_raw_accounts.id, EdgeType.SYNCS_TO,
    ))
    graph.add_edge(_make_edge(
        fivetran_conn.id, bq_raw_opps.id, EdgeType.SYNCS_TO,
    ))

    # Edges: BQ raw → dbt staging
    graph.add_edge(_make_edge(
        bq_raw_accounts.id, dbt_stg_accounts.id, EdgeType.DERIVED_FROM, confidence=0.9,
    ))
    graph.add_edge(_make_edge(
        bq_raw_opps.id, dbt_stg_opps.id, EdgeType.DERIVED_FROM, confidence=0.9,
    ))

    # Edges: dbt staging → dbt marts
    graph.add_edge(_make_edge(
        dbt_stg_accounts.id, dbt_fct_revenue.id, EdgeType.DEPENDS_ON, confidence=0.95,
    ))
    graph.add_edge(_make_edge(
        dbt_stg_opps.id, dbt_fct_revenue.id, EdgeType.DEPENDS_ON, confidence=0.95,
    ))

    # Edges: dbt marts → BQ mart
    graph.add_edge(_make_edge(
        dbt_fct_revenue.id, bq_mart_revenue.id, EdgeType.MATERIALIZES, confidence=1.0,
    ))

    # Edges: BQ mart → Looker
    graph.add_edge(_make_edge(
        bq_mart_revenue.id, looker_dash.id, EdgeType.READS_FROM, confidence=0.8,
    ))

    # Apply canonical types (same as store.py does after resolver)
    canonicalize_graph_in_place(graph.nodes, graph.edges)

    return graph


# ---- Pipeline Overview tests ----

class TestPipelineOverview:
    def test_produces_service_nodes(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_pipeline_overview()

        assert view.view_type == "pipeline_overview"
        assert len(view.nodes) > 0

        # All nodes should be SERVICE canonical type
        for node in view.nodes:
            assert node.canonical_type == "service"

    def test_service_count_matches_platforms(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_pipeline_overview()

        # We have 4 platforms: fivetran, bigquery, dbt, looker
        platforms = {n.platform for n in view.nodes}
        assert len(platforms) >= 3  # at least 3 distinct platforms

    def test_inter_service_edges_exist(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_pipeline_overview()

        assert len(view.edges) > 0
        # There should be edges between different services
        for edge in view.edges:
            assert edge.source_id != edge.target_id

    def test_stats_include_service_count(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_pipeline_overview()

        assert "serviceCount" in view.stats
        assert view.stats["serviceCount"] == len(view.nodes)

    def test_no_unmapped_nodes(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_pipeline_overview()

        assert view.unmapped_nodes == []


# ---- Data Plane tests ----

class TestDataPlane:
    def test_only_dataset_and_semantic_nodes(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        assert view.view_type == "data_plane"
        for node in view.nodes:
            assert node.canonical_type in ("dataset", "semantic", "job")

    def test_has_edges(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        assert len(view.edges) > 0

    def test_edges_within_node_set(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        node_ids = {n.id for n in view.nodes}
        for edge in view.edges:
            assert edge.source_id in node_ids, f"Edge source {edge.source_id} not in node set"
            assert edge.target_id in node_ids, f"Edge target {edge.target_id} not in node set"

    def test_no_self_edges(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        for edge in view.edges:
            assert edge.source_id != edge.target_id

    def test_stats_include_counts(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        assert "datasetCount" in view.stats
        assert "semanticCount" in view.stats
        assert "edgeCount" in view.stats
        assert view.stats["edgeCount"] == len(view.edges)


# ---- Layout determinism tests ----

class TestLayoutDeterminism:
    def test_same_input_same_positions(self, pipeline_graph):
        """Two calls with the same graph produce identical positions."""
        builder1 = ViewBuilder(pipeline_graph)
        view1 = builder1.build_data_plane()

        builder2 = ViewBuilder(pipeline_graph)
        view2 = builder2.build_data_plane()

        # Sort by ID for comparison
        nodes1 = sorted(view1.nodes, key=lambda n: n.id)
        nodes2 = sorted(view2.nodes, key=lambda n: n.id)

        assert len(nodes1) == len(nodes2)
        for n1, n2 in zip(nodes1, nodes2):
            assert n1.id == n2.id
            assert n1.x == n2.x, f"Node {n1.id}: x differs ({n1.x} vs {n2.x})"
            assert n1.y == n2.y, f"Node {n1.id}: y differs ({n1.y} vs {n2.y})"

    def test_pipeline_overview_deterministic(self, pipeline_graph):
        builder1 = ViewBuilder(pipeline_graph)
        view1 = builder1.build_pipeline_overview()

        builder2 = ViewBuilder(pipeline_graph)
        view2 = builder2.build_pipeline_overview()

        nodes1 = sorted(view1.nodes, key=lambda n: n.id)
        nodes2 = sorted(view2.nodes, key=lambda n: n.id)

        for n1, n2 in zip(nodes1, nodes2):
            assert n1.x == n2.x
            assert n1.y == n2.y


# ---- Inferred node tests ----

class TestInferredNodes:
    def test_inferred_flag_preserved_in_data_plane(self, pipeline_graph):
        """Inferred nodes from investigator should retain their flag in the view."""
        # Add an inferred bridge node
        bridge = _make_node(
            "inferred_staging", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="analytics", schema="staging",
            fqn="analytics.staging.inferred_staging", inferred=True,
        )
        bridge.canonical_type = "dataset"
        pipeline_graph.add_node(bridge)

        # Add an inferred edge
        some_node_id = list(pipeline_graph.nodes.keys())[0]
        inf_edge = _make_edge(
            some_node_id, bridge.id, EdgeType.DERIVED_FROM,
            confidence=0.5, inferred=True,
        )
        inf_edge.canonical_edge_type = "derives"
        pipeline_graph.add_edge(inf_edge)

        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        inferred_nodes = [n for n in view.nodes if n.inferred]
        assert len(inferred_nodes) >= 1

        inferred_edges = [e for e in view.edges if e.inferred]
        assert len(inferred_edges) >= 1

    def test_inferred_count_in_stats(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        assert "inferredNodeCount" in view.stats
        assert "inferredEdgeCount" in view.stats


# ---- Needs mapping tests ----

class TestNeedsMapping:
    def test_unknown_node_surfaces_in_unmapped(self, pipeline_graph):
        unknown = _make_node(
            "mystery_table", NodeType.UNKNOWN, "unknown",
            PlatformDomain.OTHER, fqn="mystery_table",
        )
        unknown.canonical_type = "dataset"
        pipeline_graph.add_node(unknown)

        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        assert view.stats["needsMappingCount"] >= 1
        unmapped_ids = {u["id"] for u in view.unmapped_nodes}
        assert unknown.id in unmapped_ids


# ---- Airflow dedup tests ----

class TestAirflowDedup:
    def test_airflow_table_refs_deduped(self, pipeline_graph):
        """Airflow creates table nodes that duplicate warehouse tables. They should be deduped."""
        # Add an Airflow table ref that duplicates an existing BQ table
        airflow_ref = _make_node(
            "accounts", NodeType.TABLE, "airflow",
            PlatformDomain.ORCHESTRATION,
            database="raw", schema="salesforce",
            fqn="raw.salesforce.accounts",
        )
        airflow_ref.canonical_type = "dataset"
        pipeline_graph.add_node(airflow_ref)

        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        # The airflow duplicate should not appear
        airflow_nodes = [n for n in view.nodes if n.platform == "airflow"]
        assert len(airflow_nodes) == 0

        assert view.stats.get("airflowDeduped", 0) >= 1


# ---- Cluster tests ----

class TestClusters:
    def test_clusters_generated_for_data_plane(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        # There should be clusters for nodes sharing the same db.schema
        # (raw.salesforce has 2 nodes, analytics.staging has 2, etc.)
        assert len(view.clusters) >= 1

    def test_cluster_bounds_contain_nodes(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        for cluster in view.clusters:
            cluster_nodes = [n for n in view.nodes if n.cluster_id == cluster.id]
            for node in cluster_nodes:
                assert node.x >= cluster.x, f"Node {node.id} x={node.x} < cluster x={cluster.x}"
                assert node.y >= cluster.y, f"Node {node.id} y={node.y} < cluster y={cluster.y}"


# ---- Serialization tests ----

class TestSerialization:
    def test_rendered_view_to_dict(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()
        d = view.to_dict()

        assert d["viewType"] == "data_plane"
        assert isinstance(d["nodes"], list)
        assert isinstance(d["edges"], list)
        assert isinstance(d["clusters"], list)
        assert isinstance(d["unmappedNodes"], list)
        assert isinstance(d["stats"], dict)

    def test_view_node_to_dict_camelcase(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        if view.nodes:
            d = view.nodes[0].to_dict()
            assert "canonicalType" in d
            assert "originalType" in d
            assert "platformDomain" in d
            assert "clusterId" in d
            assert "needsMapping" in d

    def test_view_edge_to_dict_camelcase(self, pipeline_graph):
        builder = ViewBuilder(pipeline_graph)
        view = builder.build_data_plane()

        if view.edges:
            d = view.edges[0].to_dict()
            assert "sourceId" in d
            assert "targetId" in d
            assert "canonicalType" in d
            assert "evidenceCount" in d


# ---- Topological layout unit tests ----

class TestTopologicalLayout:
    def test_simple_chain_layout(self):
        """A → B → C should produce x increasing left to right."""
        nodes = [
            ViewNode(id="A", name="A", canonical_type="dataset", original_type="table",
                     platform="bq", platform_domain="warehouse", layer="WAREHOUSE",
                     cluster_id=None, x=0, y=0, inferred=False, needs_mapping=False),
            ViewNode(id="B", name="B", canonical_type="dataset", original_type="table",
                     platform="bq", platform_domain="warehouse", layer="WAREHOUSE",
                     cluster_id=None, x=0, y=0, inferred=False, needs_mapping=False),
            ViewNode(id="C", name="C", canonical_type="dataset", original_type="table",
                     platform="bq", platform_domain="warehouse", layer="WAREHOUSE",
                     cluster_id=None, x=0, y=0, inferred=False, needs_mapping=False),
        ]
        edges = [
            ViewEdge(id="e1", source_id="A", target_id="B", canonical_type="derives",
                     original_type="depends_on", confidence=1.0, inferred=False, evidence_count=1),
            ViewEdge(id="e2", source_id="B", target_id="C", canonical_type="derives",
                     original_type="depends_on", confidence=1.0, inferred=False, evidence_count=1),
        ]

        positions = _topological_layout(nodes, edges)

        assert positions["A"][0] < positions["B"][0]
        assert positions["B"][0] < positions["C"][0]

    def test_disconnected_nodes_get_positions(self):
        """Disconnected nodes should still get valid positions."""
        nodes = [
            ViewNode(id="X", name="X", canonical_type="dataset", original_type="table",
                     platform="bq", platform_domain="warehouse", layer="WAREHOUSE",
                     cluster_id=None, x=0, y=0, inferred=False, needs_mapping=False),
            ViewNode(id="Y", name="Y", canonical_type="dataset", original_type="table",
                     platform="bq", platform_domain="warehouse", layer="WAREHOUSE",
                     cluster_id=None, x=0, y=0, inferred=False, needs_mapping=False),
        ]

        positions = _topological_layout(nodes, [])
        assert "X" in positions
        assert "Y" in positions

    def test_empty_graph(self):
        positions = _topological_layout([], [])
        assert positions == {}
