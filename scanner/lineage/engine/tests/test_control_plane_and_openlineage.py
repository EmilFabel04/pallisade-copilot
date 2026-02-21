"""
Tests for the Control Plane graph builder and OpenLineage event mapper.

Control Plane:
    scanner.lineage.engine.control_plane.build_control_plane_graph

OpenLineage:
    scanner.lineage.engine.openlineage.OpenLineageMapper (and helpers)
"""

import pytest

from scanner.lineage.graph import (
    AssetKind,
    ColumnMapping,
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
from scanner.lineage.engine.control_plane import (
    ControlPlaneEdge,
    ControlPlaneGraph,
    ControlPlaneNode,
    build_control_plane_graph,
    _DOMAIN_ORDER,
)
from scanner.lineage.engine.openlineage import (
    OpenLineageMapper,
    _parse_namespace,
    _infer_platform_domain,
    _event_type_to_health,
    _parse_fqn_parts,
)


# -----------------------------------------------------------------------
# Helpers to build test graphs quickly
# -----------------------------------------------------------------------

def _make_node(
    id: str,
    name: str,
    platform: str,
    platform_domain: PlatformDomain,
    node_type: NodeType = NodeType.TABLE,
    asset_kind: AssetKind = AssetKind.TABLE,
    health_status: HealthStatus = HealthStatus.UNKNOWN,
    integration_id: str | None = None,
    namespace: str | None = None,
) -> LineageNode:
    return LineageNode(
        id=id,
        name=name,
        fqn=f"{platform}.{name}",
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        asset_kind=asset_kind,
        health_status=health_status,
        integration_id=integration_id,
        namespace=namespace,
    )


def _make_edge(
    id: str,
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.DEPENDS_ON,
    plane: LinePlane = LinePlane.DATA,
) -> LineageEdge:
    return LineageEdge(
        id=id,
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        plane=plane,
    )


def _build_graph(nodes: list[LineageNode], edges: list[LineageEdge]) -> LineageGraph:
    """Create a LineageGraph from lists of nodes and edges."""
    g = LineageGraph()
    for n in nodes:
        g.add_node(n)
    for e in edges:
        g.add_edge(e)
    return g


# =======================================================================
#  CONTROL PLANE TESTS
# =======================================================================

class TestBuildControlPlaneGraph:
    """Tests for build_control_plane_graph()."""

    # ---- 1. Simple pipeline (Fivetran -> Snowflake -> dbt -> Looker) ----

    def test_simple_pipeline(self):
        """Four tools in a pipeline produce 4 CP nodes and 3 CP edges, ordered by position."""
        nodes = [
            _make_node("ft1", "orders_connector", "fivetran", PlatformDomain.INGESTION),
            _make_node("sf1", "raw.orders", "snowflake", PlatformDomain.WAREHOUSE),
            _make_node("dbt1", "stg_orders", "dbt", PlatformDomain.TRANSFORM),
            _make_node("lk1", "orders_dashboard", "looker", PlatformDomain.BI),
        ]
        edges = [
            _make_edge("e1", "ft1", "sf1"),
            _make_edge("e2", "sf1", "dbt1"),
            _make_edge("e3", "dbt1", "lk1"),
        ]
        graph = _build_graph(nodes, edges)
        cp = build_control_plane_graph(graph)

        assert len(cp.nodes) == 4
        assert len(cp.edges) == 3

        # Nodes should be sorted by position
        positions = [n.position for n in cp.nodes]
        assert positions == sorted(positions), "CP nodes must be sorted by ascending position"

        # Check that positions form a valid ordering relative to edges
        pos_by_id = {n.id: n.position for n in cp.nodes}
        for edge in cp.edges:
            assert pos_by_id[edge.source] < pos_by_id[edge.target], (
                f"Source {edge.source} (pos={pos_by_id[edge.source]}) must be "
                f"before target {edge.target} (pos={pos_by_id[edge.target]})"
            )

    # ---- 2. Same-platform dedup ----

    def test_same_platform_dedup(self):
        """Multiple Snowflake tables collapse into a single CP node; asset_count matches."""
        nodes = [
            _make_node("sf_a", "raw.orders", "snowflake", PlatformDomain.WAREHOUSE),
            _make_node("sf_b", "raw.customers", "snowflake", PlatformDomain.WAREHOUSE),
            _make_node("sf_c", "raw.products", "snowflake", PlatformDomain.WAREHOUSE),
        ]
        graph = _build_graph(nodes, [])
        cp = build_control_plane_graph(graph)

        assert len(cp.nodes) == 1
        sf_node = cp.nodes[0]
        assert sf_node.tool_type == "snowflake"
        assert sf_node.asset_count == 3

    # ---- 3. Health summary aggregation ----

    def test_health_summary_aggregation(self):
        """Health statuses from data-plane nodes are correctly counted on the CP node."""
        nodes = [
            _make_node("sf1", "t1", "snowflake", PlatformDomain.WAREHOUSE, health_status=HealthStatus.HEALTHY),
            _make_node("sf2", "t2", "snowflake", PlatformDomain.WAREHOUSE, health_status=HealthStatus.HEALTHY),
            _make_node("sf3", "t3", "snowflake", PlatformDomain.WAREHOUSE, health_status=HealthStatus.FAILING),
            _make_node("sf4", "t4", "snowflake", PlatformDomain.WAREHOUSE, health_status=HealthStatus.DEGRADED),
            _make_node("sf5", "t5", "snowflake", PlatformDomain.WAREHOUSE, health_status=HealthStatus.UNKNOWN),
        ]
        graph = _build_graph(nodes, [])
        cp = build_control_plane_graph(graph)

        assert len(cp.nodes) == 1
        health = cp.nodes[0].health_summary
        assert health["healthy"] == 2
        assert health["failing"] == 1
        assert health["degraded"] == 1
        assert health["unknown"] == 1

    # ---- 4. No cross-tool edges ----

    def test_no_cross_tool_edges(self):
        """Edges within the same platform should not produce CP edges."""
        nodes = [
            _make_node("sf1", "raw.orders", "snowflake", PlatformDomain.WAREHOUSE),
            _make_node("sf2", "clean.orders", "snowflake", PlatformDomain.WAREHOUSE),
        ]
        edges = [
            _make_edge("e1", "sf1", "sf2"),
        ]
        graph = _build_graph(nodes, edges)
        cp = build_control_plane_graph(graph)

        assert len(cp.nodes) == 1
        assert len(cp.edges) == 0

    # ---- 5. Control-plane edges are skipped ----

    def test_control_plane_edges_skipped(self):
        """Edges with plane=CONTROL should not contribute to CP overview edges."""
        nodes = [
            _make_node("af1", "dag1", "airflow", PlatformDomain.ORCHESTRATION),
            _make_node("sf1", "orders", "snowflake", PlatformDomain.WAREHOUSE),
        ]
        edges = [
            _make_edge("ctrl_e1", "af1", "sf1", plane=LinePlane.CONTROL),
        ]
        graph = _build_graph(nodes, edges)
        cp = build_control_plane_graph(graph)

        # Both platforms exist as CP nodes
        assert len(cp.nodes) == 2
        # But the CONTROL edge should be skipped, so no CP edges
        assert len(cp.edges) == 0

    # ---- 6. to_dict serialization ----

    def test_to_dict_serialization(self):
        """ControlPlaneGraph.to_dict() returns correct structure with nodes/edges/stats keys."""
        nodes = [
            _make_node("ft1", "connector", "fivetran", PlatformDomain.INGESTION),
            _make_node("sf1", "table", "snowflake", PlatformDomain.WAREHOUSE),
        ]
        edges = [_make_edge("e1", "ft1", "sf1")]
        graph = _build_graph(nodes, edges)
        cp = build_control_plane_graph(graph)

        d = cp.to_dict()

        assert "nodes" in d
        assert "edges" in d
        assert "stats" in d

        assert isinstance(d["nodes"], list)
        assert isinstance(d["edges"], list)
        assert isinstance(d["stats"], dict)

        assert d["stats"]["tool_count"] == 2
        assert d["stats"]["flow_count"] == 1

        # Verify node dict has expected keys
        node_d = d["nodes"][0]
        for key in ("id", "name", "toolType", "platformDomain", "integrationId",
                     "assetCount", "healthSummary", "position"):
            assert key in node_d, f"Node dict missing key: {key}"

        # Verify edge dict has expected keys
        edge_d = d["edges"][0]
        for key in ("id", "source", "target", "dataFlowCount", "sampleAssets"):
            assert key in edge_d, f"Edge dict missing key: {key}"

    # ---- 7. Empty graph ----

    def test_empty_graph(self):
        """Empty LineageGraph should produce empty ControlPlaneGraph."""
        graph = LineageGraph()
        cp = build_control_plane_graph(graph)

        assert len(cp.nodes) == 0
        assert len(cp.edges) == 0
        assert cp.to_dict()["stats"]["tool_count"] == 0
        assert cp.to_dict()["stats"]["flow_count"] == 0

    # ---- 8. Integration ID separation ----

    def test_integration_id_separation(self):
        """Two Snowflake instances with different integration_ids produce separate CP nodes."""
        nodes = [
            _make_node("sf_prod1", "orders", "snowflake", PlatformDomain.WAREHOUSE,
                        integration_id="int-prod"),
            _make_node("sf_prod2", "customers", "snowflake", PlatformDomain.WAREHOUSE,
                        integration_id="int-prod"),
            _make_node("sf_dev1", "orders", "snowflake", PlatformDomain.WAREHOUSE,
                        integration_id="int-dev"),
        ]
        graph = _build_graph(nodes, [])
        cp = build_control_plane_graph(graph)

        # Should have 2 separate CP nodes (one per integration_id)
        assert len(cp.nodes) == 2

        ids = {n.id for n in cp.nodes}
        assert "snowflake:int-prod" in ids
        assert "snowflake:int-dev" in ids

        # Asset counts
        for n in cp.nodes:
            if n.id == "snowflake:int-prod":
                assert n.asset_count == 2
            elif n.id == "snowflake:int-dev":
                assert n.asset_count == 1

    # ---- Additional: data_flow_count and sample_assets ----

    def test_data_flow_count_and_sample_assets(self):
        """CP edge data_flow_count reflects the number of underlying data edges."""
        nodes = [
            _make_node("ft1", "conn_a", "fivetran", PlatformDomain.INGESTION),
            _make_node("ft2", "conn_b", "fivetran", PlatformDomain.INGESTION),
            _make_node("sf1", "raw.a", "snowflake", PlatformDomain.WAREHOUSE),
            _make_node("sf2", "raw.b", "snowflake", PlatformDomain.WAREHOUSE),
        ]
        edges = [
            _make_edge("e1", "ft1", "sf1"),
            _make_edge("e2", "ft2", "sf2"),
        ]
        graph = _build_graph(nodes, edges)
        cp = build_control_plane_graph(graph)

        assert len(cp.edges) == 1
        cp_edge = cp.edges[0]
        assert cp_edge.data_flow_count == 2
        assert len(cp_edge.sample_assets) <= 3

    # ---- Domain ordering defaults ----

    def test_domain_order_defaults(self):
        """Verify initial positions match _DOMAIN_ORDER dict for each domain."""
        nodes = [
            _make_node("n_ingest", "x", "fivetran", PlatformDomain.INGESTION),
            _make_node("n_wh", "y", "snowflake", PlatformDomain.WAREHOUSE),
            _make_node("n_tx", "z", "dbt", PlatformDomain.TRANSFORM),
            _make_node("n_bi", "w", "looker", PlatformDomain.BI),
        ]
        graph = _build_graph(nodes, [])
        cp = build_control_plane_graph(graph)

        domain_to_cp = {n.platform_domain: n for n in cp.nodes}
        assert domain_to_cp["ingestion"].position == _DOMAIN_ORDER["ingestion"]
        assert domain_to_cp["warehouse"].position == _DOMAIN_ORDER["warehouse"]
        assert domain_to_cp["transform"].position == _DOMAIN_ORDER["transform"]
        assert domain_to_cp["bi"].position == _DOMAIN_ORDER["bi"]

    # ---- Position refinement corrects inverted edges ----

    def test_position_refinement_corrects_inverted_order(self):
        """When edge direction contradicts domain order, _refine_positions adjusts."""
        # BI (position 4) has an edge to WAREHOUSE (position 1) — unusual but should
        # still satisfy src.position < tgt.position after refinement.
        nodes = [
            _make_node("bi1", "dash", "looker", PlatformDomain.BI),
            _make_node("wh1", "table", "snowflake", PlatformDomain.WAREHOUSE),
        ]
        edges = [_make_edge("e1", "bi1", "wh1")]
        graph = _build_graph(nodes, edges)
        cp = build_control_plane_graph(graph)

        pos_by_id = {n.id: n.position for n in cp.nodes}
        for edge in cp.edges:
            assert pos_by_id[edge.source] < pos_by_id[edge.target]


# =======================================================================
#  OPENLINEAGE MAPPER TESTS
# =======================================================================

def _make_ol_event(
    event_type: str = "COMPLETE",
    job_namespace: str = "airflow://prod",
    job_name: str = "etl_dag.load_orders",
    inputs: list | None = None,
    outputs: list | None = None,
    run_id: str = "run-123",
    job_facets: dict | None = None,
) -> dict:
    """Helper: build a minimal OpenLineage RunEvent dict."""
    return {
        "eventType": event_type,
        "eventTime": "2024-01-15T10:00:00Z",
        "run": {"runId": run_id},
        "job": {
            "namespace": job_namespace,
            "name": job_name,
            "facets": job_facets or {},
        },
        "inputs": inputs or [],
        "outputs": outputs or [],
    }


class TestOpenLineageMapper:
    """Tests for OpenLineageMapper and its helper functions."""

    # ---- 1. Basic event mapping ----

    def test_basic_event_mapping(self):
        """Airflow RunEvent with 1 input and 1 output -> 3 nodes and 2 edges."""
        event = _make_ol_event(
            inputs=[{"namespace": "bigquery", "name": "raw.orders", "facets": {}}],
            outputs=[{"namespace": "bigquery", "name": "analytics.clean_orders", "facets": {}}],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        assert len(nodes) == 3  # job + input dataset + output dataset

        # There should be 2 table-level edges: READS_FROM and WRITES_TO
        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        assert len(table_edges) == 2

        edge_types = {e.edge_type for e in table_edges}
        assert EdgeType.READS_FROM in edge_types
        assert EdgeType.WRITES_TO in edge_types

        # Job node
        job_nodes = [n for n in nodes if n.node_type == NodeType.TASK]
        assert len(job_nodes) == 1
        assert job_nodes[0].platform == "airflow"
        assert job_nodes[0].health_status == HealthStatus.HEALTHY  # COMPLETE

        # Dataset nodes
        ds_nodes = [n for n in nodes if n.node_type == NodeType.TABLE]
        assert len(ds_nodes) == 2

    # ---- 2. Namespace parsing ----

    def test_parse_namespace_airflow(self):
        platform, instance = _parse_namespace("airflow://prod-airflow")
        assert platform == "airflow"
        assert instance == "prod-airflow"

    def test_parse_namespace_bare(self):
        platform, instance = _parse_namespace("bigquery")
        assert platform == "bigquery"
        assert instance == ""

    def test_parse_namespace_spark(self):
        platform, instance = _parse_namespace("spark://cluster1")
        assert platform == "spark"
        assert instance == "cluster1"

    def test_parse_namespace_case_normalization(self):
        platform, instance = _parse_namespace("BigQuery://MyProject")
        assert platform == "bigquery"
        assert instance == "MyProject"

    # ---- 3. Platform domain inference ----

    def test_infer_platform_domain_warehouse(self):
        assert _infer_platform_domain("bigquery") == PlatformDomain.WAREHOUSE
        assert _infer_platform_domain("snowflake") == PlatformDomain.WAREHOUSE
        assert _infer_platform_domain("postgres") == PlatformDomain.WAREHOUSE
        assert _infer_platform_domain("redshift") == PlatformDomain.WAREHOUSE

    def test_infer_platform_domain_orchestration(self):
        assert _infer_platform_domain("airflow") == PlatformDomain.ORCHESTRATION
        assert _infer_platform_domain("spark") == PlatformDomain.ORCHESTRATION

    def test_infer_platform_domain_transform(self):
        assert _infer_platform_domain("dbt") == PlatformDomain.TRANSFORM

    def test_infer_platform_domain_other(self):
        assert _infer_platform_domain("unknown") == PlatformDomain.OTHER
        assert _infer_platform_domain("custom_tool") == PlatformDomain.OTHER

    # ---- 4. Event type to health ----

    def test_event_type_to_health_complete(self):
        assert _event_type_to_health("COMPLETE") == HealthStatus.HEALTHY

    def test_event_type_to_health_fail(self):
        assert _event_type_to_health("FAIL") == HealthStatus.FAILING

    def test_event_type_to_health_abort(self):
        assert _event_type_to_health("ABORT") == HealthStatus.DEGRADED

    def test_event_type_to_health_start(self):
        assert _event_type_to_health("START") == HealthStatus.UNKNOWN

    def test_event_type_to_health_running(self):
        assert _event_type_to_health("RUNNING") == HealthStatus.UNKNOWN

    def test_event_type_to_health_unrecognized(self):
        assert _event_type_to_health("SOMETHING_ELSE") == HealthStatus.UNKNOWN

    def test_event_type_to_health_case_insensitive(self):
        assert _event_type_to_health("complete") == HealthStatus.HEALTHY
        assert _event_type_to_health("fail") == HealthStatus.FAILING

    # ---- 5. FQN parsing ----

    def test_parse_fqn_three_parts(self):
        db, schema, table = _parse_fqn_parts("db.schema.table")
        assert db == "db"
        assert schema == "schema"
        assert table == "table"

    def test_parse_fqn_two_parts(self):
        db, schema, table = _parse_fqn_parts("schema.table")
        assert db == ""
        assert schema == "schema"
        assert table == "table"

    def test_parse_fqn_one_part(self):
        db, schema, table = _parse_fqn_parts("table")
        assert db == ""
        assert schema == ""
        assert table == "table"

    def test_parse_fqn_more_than_three_parts(self):
        """Extra dots after the third are included in the table name."""
        db, schema, table = _parse_fqn_parts("project.dataset.table.nested")
        assert db == "project"
        assert schema == "dataset"
        assert table == "table.nested"

    # ---- 6. Column lineage facet ----

    def test_column_lineage_facet(self):
        """Output with columnLineage facet produces column-level DEPENDS_ON edge."""
        event = _make_ol_event(
            inputs=[{
                "namespace": "bigquery",
                "name": "raw.orders",
                "facets": {
                    "schema": {"fields": [{"name": "id", "type": "INT64"}]},
                },
            }],
            outputs=[{
                "namespace": "bigquery",
                "name": "analytics.clean_orders",
                "facets": {
                    "schema": {"fields": [{"name": "order_id", "type": "INT64"}]},
                    "columnLineage": {
                        "fields": {
                            "order_id": {
                                "inputFields": [
                                    {"namespace": "bigquery", "name": "raw.orders", "field": "id"}
                                ],
                                "transformationDescription": "renamed from id",
                            }
                        }
                    },
                },
            }],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        # Should have column-level edge in addition to table-level edges
        col_edges = [e for e in edges if e.lineage_level == LineageLevel.COLUMN]
        assert len(col_edges) == 1

        col_edge = col_edges[0]
        assert col_edge.edge_type == EdgeType.DEPENDS_ON
        assert len(col_edge.column_mappings) == 1

        mapping = col_edge.column_mappings[0]
        assert mapping.from_column == "id"
        assert mapping.to_column == "order_id"
        assert mapping.transform_expr == "renamed from id"
        assert mapping.confidence == 1.0

    # ---- 7. Schema facet ----

    def test_schema_facet_populates_columns(self):
        """Dataset with schema facet produces node with populated columns list."""
        event = _make_ol_event(
            inputs=[{
                "namespace": "bigquery",
                "name": "raw.orders",
                "facets": {
                    "schema": {
                        "fields": [
                            {"name": "id", "type": "INT64"},
                            {"name": "amount", "type": "FLOAT64"},
                            {"name": "customer_id", "type": "STRING", "description": "FK to customers"},
                        ]
                    },
                },
            }],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        ds_nodes = [n for n in nodes if n.node_type == NodeType.TABLE]
        assert len(ds_nodes) == 1

        columns = ds_nodes[0].columns
        assert len(columns) == 3
        assert columns[0]["name"] == "id"
        assert columns[0]["type"] == "INT64"
        assert columns[2]["description"] == "FK to customers"

    # ---- 8. Batch mapping ----

    def test_batch_mapping(self):
        """map_events with multiple events aggregates nodes and edges."""
        events = [
            _make_ol_event(
                job_name="dag.task_a", run_id="run-1",
                outputs=[{"namespace": "bigquery", "name": "db.schema.table_a", "facets": {}}],
            ),
            _make_ol_event(
                job_name="dag.task_b", run_id="run-2",
                outputs=[{"namespace": "bigquery", "name": "db.schema.table_b", "facets": {}}],
            ),
            _make_ol_event(
                job_name="dag.task_c", run_id="run-3",
                inputs=[{"namespace": "bigquery", "name": "db.schema.table_a", "facets": {}}],
                outputs=[{"namespace": "bigquery", "name": "db.schema.table_c", "facets": {}}],
            ),
        ]
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_events(events)

        # 3 job nodes + 4 dataset nodes (table_a appears twice as separate node objects)
        assert len(nodes) >= 7
        # Each event with outputs has WRITES_TO; event 3 also has READS_FROM
        assert len(edges) >= 4

    # ---- 9. Missing job name ----

    def test_missing_job_name_returns_empty(self):
        """Event without job.name should produce no nodes or edges."""
        event = {
            "eventType": "COMPLETE",
            "eventTime": "2024-01-15T10:00:00Z",
            "run": {"runId": "run-abc"},
            "job": {
                "namespace": "airflow://prod",
                "name": "",  # empty job name
                "facets": {},
            },
            "inputs": [],
            "outputs": [],
        }
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        assert len(nodes) == 0
        assert len(edges) == 0

    def test_missing_job_key_returns_empty(self):
        """Event without job.name key at all should produce no nodes or edges."""
        event = {
            "eventType": "COMPLETE",
            "eventTime": "2024-01-15T10:00:00Z",
            "run": {"runId": "run-abc"},
            "job": {
                "namespace": "airflow://prod",
                "facets": {},
            },
            "inputs": [],
            "outputs": [],
        }
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        assert len(nodes) == 0
        assert len(edges) == 0

    # ---- 10. dbt job type ----

    def test_dbt_job_type(self):
        """Job with platform 'dbt' gets node_type=MODEL and asset_kind=MODEL."""
        event = _make_ol_event(
            job_namespace="dbt://prod",
            job_name="stg_orders",  # no dot => dbt heuristic applies
            outputs=[{"namespace": "snowflake", "name": "analytics.stg_orders", "facets": {}}],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        job_nodes = [n for n in nodes if n.platform == "dbt"]
        assert len(job_nodes) == 1
        assert job_nodes[0].node_type == NodeType.MODEL
        assert job_nodes[0].asset_kind == AssetKind.MODEL

    # ---- Additional: edge planes and confidence ----

    def test_edges_have_cross_plane(self):
        """OpenLineage-derived edges should have plane=CROSS."""
        event = _make_ol_event(
            inputs=[{"namespace": "bigquery", "name": "raw.orders", "facets": {}}],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        _, edges = mapper.map_event(event)

        for e in edges:
            assert e.plane == LinePlane.CROSS

    def test_table_edge_confidence(self):
        """Table-level edges from OpenLineage have confidence 0.95."""
        event = _make_ol_event(
            inputs=[{"namespace": "bigquery", "name": "raw.orders", "facets": {}}],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        _, edges = mapper.map_event(event)

        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        for e in table_edges:
            assert e.confidence == 0.95

    def test_evidence_populated(self):
        """Edges carry evidence with adapter_id and source_ref."""
        event = _make_ol_event(
            inputs=[{"namespace": "bigquery", "name": "raw.orders", "facets": {}}],
        )
        mapper = OpenLineageMapper(adapter_id="test-adapter")
        _, edges = mapper.map_event(event)

        for e in edges:
            assert len(e.evidence) >= 1
            ev = e.evidence[0]
            assert ev.adapter_id == "test-adapter"
            assert ev.source_ref  # non-empty

    def test_dataset_node_attributes(self):
        """Verify dataset node attributes: database, schema, platform, domain."""
        event = _make_ol_event(
            inputs=[{
                "namespace": "snowflake://acme",
                "name": "mydb.public.users",
                "facets": {},
            }],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, _ = mapper.map_event(event)

        ds_nodes = [n for n in nodes if n.node_type == NodeType.TABLE]
        assert len(ds_nodes) == 1
        ds = ds_nodes[0]
        assert ds.database == "mydb"
        assert ds.schema == "public"
        assert ds.name == "users"
        assert ds.platform == "snowflake"
        assert ds.platform_domain == PlatformDomain.WAREHOUSE
        assert ds.namespace == "acme"

    def test_empty_dataset_name_skipped(self):
        """Input/output with empty name should be skipped gracefully."""
        event = _make_ol_event(
            inputs=[{"namespace": "bigquery", "name": "", "facets": {}}],
        )
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_event(event)

        # Only the job node — the empty-name dataset is skipped
        assert len(nodes) == 1
        assert nodes[0].node_type == NodeType.TASK
        assert len(edges) == 0

    def test_map_events_tolerates_bad_event(self):
        """map_events should log and skip events that raise exceptions, not crash."""
        good_event = _make_ol_event(job_name="good_job")
        # A malformed event that might cause issues internally
        bad_event = {"eventType": "COMPLETE"}  # missing job, run, etc.

        mapper = OpenLineageMapper(adapter_id="test")
        nodes, edges = mapper.map_events([good_event, bad_event])

        # At minimum the good event produced a node
        assert len(nodes) >= 1

    def test_job_node_raw_metadata_contains_run_id(self):
        """Job node raw_metadata includes the run_id from the event."""
        event = _make_ol_event(run_id="run-xyz-456")
        mapper = OpenLineageMapper(adapter_id="test")
        nodes, _ = mapper.map_event(event)

        job_node = [n for n in nodes if n.node_type == NodeType.TASK][0]
        assert job_node.raw_metadata["run_id"] == "run-xyz-456"
        assert job_node.raw_metadata["event_type"] == "COMPLETE"
