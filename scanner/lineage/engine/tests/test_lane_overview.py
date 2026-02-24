"""
Tests for lane-based Pipeline Overview, bridge rules, planner, and reconciler.

Fixture: n8n + BigQuery raw.* + dbt models → analytics.*

Assertions (Requirement J):
1. Raw datasets are assigned to lane=warehouse_raw and dataset_zone=raw
2. Ingestion actor exists upstream (inferred bridge if needed)
3. dbt items render in lane=transformation
4. Analytics outputs render in lane=warehouse_analytics
5. No dataset is labeled as 'source' purely because indegree=0
6. Planner returns sensible order (warehouse before dbt before n8n)
7. Reconciler proposes n8n->raw writes when missing
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from scanner.lineage.graph import (
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
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.views import ViewBuilder
from scanner.lineage.engine.zones import (
    DatasetZone,
    ActorCapability,
    PipelineLane,
    classify_dataset_zone,
    classify_actor_capability,
    assign_lane,
)
from scanner.lineage.engine.bridge import BridgeRuleEngine, BridgeResult
from scanner.lineage.engine.planner import (
    ExtractionPlan,
    PlannerInput,
    plan_heuristic,
)


# ---- Helpers ----

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
    raw_metadata: dict = None,
) -> LineageNode:
    node = LineageNode(
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
    if raw_metadata:
        node.raw_metadata = raw_metadata
    return node


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


# ---- Fixture: n8n + BigQuery raw + dbt → analytics ----

@pytest.fixture
def n8n_bq_dbt_graph() -> LineageGraph:
    """
    Scenario: n8n ingests data to BigQuery raw.*, dbt transforms to analytics.*
    But ingestion edges are MISSING (the raw-tables-as-sources problem).

    Nodes:
      - n8n service (ingestion)
      - n8n workflow "stripe_sync" (ingestion job)
      - BigQuery raw.stripe.charges (raw dataset, no upstream writer)
      - BigQuery raw.stripe.customers (raw dataset, no upstream writer)
      - dbt model stg_charges (staging)
      - dbt model stg_customers (staging)
      - dbt model fct_revenue (mart)
      - BigQuery analytics.marts.fct_revenue (mart dataset)
      - Looker dashboard "Revenue Dashboard" (BI semantic)

    Edges:
      - n8n service runs stripe_sync workflow
      - raw.stripe.charges → stg_charges (derives)
      - raw.stripe.customers → stg_customers (derives)
      - stg_charges → fct_revenue (derives)
      - stg_customers → fct_revenue (derives)
      - fct_revenue → analytics.marts.fct_revenue (materializes)
      - analytics.marts.fct_revenue → Revenue Dashboard (reads_from)

    MISSING: n8n → raw tables writes edges (the problem to solve)
    """
    graph = LineageGraph()

    # n8n service
    n8n_svc = _make_node(
        "n8n", NodeType.CONNECTOR, "n8n",
        PlatformDomain.INGESTION, integration_id="n8n_001",
    )
    n8n_svc.canonical_type = "service"

    # n8n workflow (job)
    n8n_workflow = _make_node(
        "stripe_sync", NodeType.WORKFLOW, "n8n",
        PlatformDomain.INGESTION, integration_id="n8n_001",
    )

    # BigQuery raw tables (no upstream writer — the problem!)
    bq_raw_charges = _make_node(
        "charges", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="raw", schema="stripe",
        fqn="raw.stripe.charges", integration_id="bq_001",
    )
    bq_raw_customers = _make_node(
        "customers", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="raw", schema="stripe",
        fqn="raw.stripe.customers", integration_id="bq_001",
    )

    # dbt staging models
    dbt_stg_charges = _make_node(
        "stg_charges", NodeType.MODEL, "dbt",
        PlatformDomain.TRANSFORM, database="analytics", schema="staging",
        fqn="analytics.staging.stg_charges", integration_id="dbt_001",
        raw_metadata={"dbt_resource_type": "model", "dbt_path": "models/staging/stg_charges.sql"},
    )
    dbt_stg_customers = _make_node(
        "stg_customers", NodeType.MODEL, "dbt",
        PlatformDomain.TRANSFORM, database="analytics", schema="staging",
        fqn="analytics.staging.stg_customers", integration_id="dbt_001",
        raw_metadata={"dbt_resource_type": "model", "dbt_path": "models/staging/stg_customers.sql"},
    )

    # dbt mart model
    dbt_fct_revenue = _make_node(
        "fct_revenue", NodeType.MODEL, "dbt",
        PlatformDomain.TRANSFORM, database="analytics", schema="marts",
        fqn="analytics.marts.fct_revenue", integration_id="dbt_001",
        raw_metadata={"dbt_resource_type": "model", "dbt_path": "models/marts/fct_revenue.sql"},
    )

    # BigQuery analytics mart table
    bq_mart_revenue = _make_node(
        "fct_revenue", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="analytics", schema="marts",
        fqn="analytics.marts.fct_revenue", integration_id="bq_001",
    )

    # Looker dashboard
    looker_dash = _make_node(
        "Revenue Dashboard", NodeType.DASHBOARD, "looker",
        PlatformDomain.BI, integration_id="looker_001",
    )

    # Add all nodes
    for node in [n8n_svc, n8n_workflow,
                 bq_raw_charges, bq_raw_customers,
                 dbt_stg_charges, dbt_stg_customers, dbt_fct_revenue,
                 bq_mart_revenue, looker_dash]:
        graph.add_node(node)

    # n8n service runs workflow
    graph.add_edge(_make_edge(
        n8n_svc.id, n8n_workflow.id, EdgeType.TRIGGERS,
    ))

    # raw → dbt staging (derives)
    graph.add_edge(_make_edge(
        bq_raw_charges.id, dbt_stg_charges.id, EdgeType.DERIVED_FROM, confidence=0.9,
    ))
    graph.add_edge(_make_edge(
        bq_raw_customers.id, dbt_stg_customers.id, EdgeType.DERIVED_FROM, confidence=0.9,
    ))

    # dbt staging → dbt mart (depends_on)
    graph.add_edge(_make_edge(
        dbt_stg_charges.id, dbt_fct_revenue.id, EdgeType.DEPENDS_ON, confidence=0.95,
    ))
    graph.add_edge(_make_edge(
        dbt_stg_customers.id, dbt_fct_revenue.id, EdgeType.DEPENDS_ON, confidence=0.95,
    ))

    # dbt mart → BQ analytics table (materializes)
    graph.add_edge(_make_edge(
        dbt_fct_revenue.id, bq_mart_revenue.id, EdgeType.MATERIALIZES, confidence=1.0,
    ))

    # BQ analytics → Looker (reads_from)
    graph.add_edge(_make_edge(
        bq_mart_revenue.id, looker_dash.id, EdgeType.READS_FROM, confidence=0.8,
    ))

    # Apply canonical types
    canonicalize_graph_in_place(graph.nodes, graph.edges)

    return graph


# ---- 1) Raw datasets → lane=warehouse_raw, zone=raw ----

class TestRawDatasetLaneAssignment:
    def test_raw_datasets_have_zone_raw(self, n8n_bq_dbt_graph):
        """Raw BigQuery tables should be classified as zone=raw."""
        graph = n8n_bq_dbt_graph
        raw_charges = graph.nodes["node:bigquery:charges"]
        raw_customers = graph.nodes["node:bigquery:customers"]

        assert classify_dataset_zone(raw_charges) == DatasetZone.RAW
        assert classify_dataset_zone(raw_customers) == DatasetZone.RAW

    def test_raw_datasets_assigned_to_warehouse_raw_lane(self, n8n_bq_dbt_graph):
        """Raw datasets should be placed in the warehouse_raw lane."""
        graph = n8n_bq_dbt_graph
        for node_id in ["node:bigquery:charges", "node:bigquery:customers"]:
            node = graph.nodes[node_id]
            ct = node.canonical_type or "dataset"
            zone = classify_dataset_zone(node)
            lane = assign_lane(node, ct, zone)
            assert lane == PipelineLane.WAREHOUSE_RAW.value, (
                f"{node.name} should be in warehouse_raw, got {lane}"
            )

    def test_lane_overview_has_bigquery_tool_in_warehouse_raw(self, n8n_bq_dbt_graph):
        """ViewBuilder.build_lane_pipeline_overview places BigQuery tool in warehouse_raw lane."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_raw_nodes = [
            n for n in view.nodes
            if n.platform == "bigquery" and n.layer == PipelineLane.WAREHOUSE_RAW.value
        ]
        assert len(bq_raw_nodes) >= 1, "BigQuery should appear in warehouse_raw lane"


# ---- 2) Ingestion actor exists upstream (bridge if needed) ----

class TestBridgeMissingIngestion:
    def test_bridge_creates_inferred_writer(self, n8n_bq_dbt_graph):
        """
        When n8n exists but raw datasets have no upstream writes edge,
        the bridge rule should create an inferred loader job.
        """
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()

        assert result.total_changes > 0
        assert len(result.added_nodes) >= 1

        # Check that an inferred loader node was created
        loader_nodes = [
            n for n in result.added_nodes
            if "unknown_loader" in n.id
        ]
        assert len(loader_nodes) >= 1
        loader = loader_nodes[0]
        assert loader.inferred is True
        assert loader.platform == "n8n"
        assert loader.canonical_type == "job"

    def test_bridge_creates_writes_edges(self, n8n_bq_dbt_graph):
        """Bridge should create writes edges from loader to raw datasets."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()

        writes_edges = [
            e for e in result.added_edges
            if e.canonical_edge_type == "writes"
        ]
        # Should have writes edges to both raw tables
        assert len(writes_edges) >= 2

        targets = {e.target_id for e in writes_edges}
        assert "node:bigquery:charges" in targets
        assert "node:bigquery:customers" in targets

    def test_bridge_edges_are_low_confidence(self, n8n_bq_dbt_graph):
        """Inferred bridge edges should have confidence=0.4."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()

        for edge in result.added_edges:
            if edge.canonical_edge_type == "writes":
                assert edge.confidence == 0.4
                assert edge.inferred is True

    def test_bridge_adds_runs_edge_from_service_to_loader(self, n8n_bq_dbt_graph):
        """Bridge should connect n8n service to the loader job via runs edge."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()

        runs_edges = [
            e for e in result.added_edges
            if e.canonical_edge_type == "runs"
        ]
        assert len(runs_edges) >= 1

    def test_after_bridge_raw_datasets_have_upstream_writer(self, n8n_bq_dbt_graph):
        """After bridge, raw datasets should no longer be orphans."""
        graph = n8n_bq_dbt_graph
        engine = BridgeRuleEngine(graph)
        engine.apply_all()

        for raw_id in ["node:bigquery:charges", "node:bigquery:customers"]:
            upstream = graph._upstream.get(raw_id, set())
            writer_found = False
            for up_id in upstream:
                up_node = graph.nodes.get(up_id)
                if up_node and up_node.canonical_type in ("service", "job"):
                    writer_found = True
                    break
            assert writer_found, f"Raw dataset {raw_id} still has no upstream writer after bridge"

    def test_no_bridge_when_writer_exists(self, n8n_bq_dbt_graph):
        """If raw datasets already have a writer, bridge should not add duplicates."""
        graph = n8n_bq_dbt_graph

        # Manually add a writes edge to one raw table
        loader_node = _make_node(
            "manual_loader", NodeType.WORKFLOW, "n8n",
            PlatformDomain.INGESTION, integration_id="n8n_001",
        )
        loader_node.canonical_type = "job"
        graph.add_node(loader_node)

        writes_edge = _make_edge(
            loader_node.id, "node:bigquery:charges", EdgeType.WRITES_TO,
        )
        writes_edge.canonical_edge_type = "writes"
        graph.add_edge(writes_edge)

        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # Only 1 raw orphan remains (customers), not charges
        bridge_writes = [
            e for e in result.added_edges
            if e.canonical_edge_type == "writes"
        ]
        targets = {e.target_id for e in bridge_writes}
        assert "node:bigquery:charges" not in targets
        assert "node:bigquery:customers" in targets


# ---- 3) dbt items render in lane=transformation ----

class TestDbtLaneAssignment:
    def test_dbt_staging_models_in_transformation_lane(self, n8n_bq_dbt_graph):
        """dbt staging models should be in the transformation lane."""
        graph = n8n_bq_dbt_graph
        for node_id in ["node:dbt:stg_charges", "node:dbt:stg_customers"]:
            node = graph.nodes[node_id]
            zone = classify_dataset_zone(node)
            assert zone == DatasetZone.STAGING
            lane = assign_lane(node, node.canonical_type, zone)
            assert lane == PipelineLane.TRANSFORMATION.value

    def test_dbt_mart_model_classified_as_mart(self, n8n_bq_dbt_graph):
        """dbt fct_revenue model should be classified as mart zone."""
        node = n8n_bq_dbt_graph.nodes["node:dbt:fct_revenue"]
        zone = classify_dataset_zone(node)
        assert zone == DatasetZone.MART

    def test_lane_overview_dbt_tool_in_transformation(self, n8n_bq_dbt_graph):
        """ViewBuilder places dbt tool in transformation lane."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        dbt_nodes = [
            n for n in view.nodes
            if n.platform == "dbt" and n.layer == PipelineLane.TRANSFORMATION.value
        ]
        assert len(dbt_nodes) >= 1, "dbt should appear in transformation lane"


# ---- 4) Analytics outputs render in lane=warehouse_analytics ----

class TestAnalyticsLaneAssignment:
    def test_analytics_mart_table_in_warehouse_analytics_lane(self, n8n_bq_dbt_graph):
        """BigQuery analytics.marts.fct_revenue should be in warehouse_analytics lane."""
        node = n8n_bq_dbt_graph.nodes["node:bigquery:fct_revenue"]
        zone = classify_dataset_zone(node)
        assert zone in (DatasetZone.MART, DatasetZone.ANALYTICS)
        lane = assign_lane(node, node.canonical_type, zone)
        assert lane == PipelineLane.WAREHOUSE_ANALYTICS.value

    def test_dbt_mart_model_in_warehouse_analytics_lane(self, n8n_bq_dbt_graph):
        """dbt fct_revenue should be in warehouse_analytics (mart → analytics lane)."""
        node = n8n_bq_dbt_graph.nodes["node:dbt:fct_revenue"]
        zone = classify_dataset_zone(node)
        lane = assign_lane(node, node.canonical_type, zone)
        assert lane == PipelineLane.WAREHOUSE_ANALYTICS.value

    def test_lane_overview_bigquery_in_warehouse_analytics(self, n8n_bq_dbt_graph):
        """ViewBuilder places BigQuery analytics tool in warehouse_analytics lane."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_analytics_nodes = [
            n for n in view.nodes
            if n.platform == "bigquery" and n.layer == PipelineLane.WAREHOUSE_ANALYTICS.value
        ]
        assert len(bq_analytics_nodes) >= 1, "BigQuery should appear in warehouse_analytics lane"


# ---- 5) No dataset labeled as 'source' because indegree=0 ----

class TestNoFalseSourceLabel:
    def test_raw_datasets_not_labeled_source(self, n8n_bq_dbt_graph):
        """
        Raw datasets should NOT be classified as 'source' just because
        they have indegree=0. They should be zone=raw, lane=warehouse_raw.
        """
        graph = n8n_bq_dbt_graph
        for node_id in ["node:bigquery:charges", "node:bigquery:customers"]:
            node = graph.nodes[node_id]
            zone = classify_dataset_zone(node)

            # The zone should be 'raw', not relying on indegree
            assert zone == DatasetZone.RAW
            # They should never be treated as a "source" node — they're data assets
            assert node.canonical_type == "dataset"

    def test_lane_overview_no_source_canonical_type(self, n8n_bq_dbt_graph):
        """No node in the lane overview should have a canonical_type of 'source'."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for vn in view.nodes:
            assert vn.canonical_type != "source", (
                f"Node {vn.name} has canonical_type='source', "
                f"which should not exist in the canonical taxonomy"
            )

    def test_after_bridge_raw_datasets_are_not_leaf_sources(self, n8n_bq_dbt_graph):
        """After bridge, raw datasets should have upstream edges (not be leaf sources)."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        engine.apply_all()

        for raw_id in ["node:bigquery:charges", "node:bigquery:customers"]:
            upstream = n8n_bq_dbt_graph._upstream.get(raw_id, set())
            assert len(upstream) > 0, (
                f"Raw dataset {raw_id} is still a leaf source after bridge"
            )


# ---- 6) Planner returns sensible order ----

class TestPlannerOrder:
    def test_heuristic_order_warehouse_first(self):
        """Heuristic planner should put warehouse before dbt before n8n."""
        integrations = [
            {"tool_type": "n8n"},
            {"tool_type": "dbt_core"},
            {"tool_type": "bigquery"},
            {"tool_type": "looker"},
        ]
        plan = plan_heuristic(integrations)

        assert plan.source == "heuristic"
        assert len(plan.plan) == 4

        bq_idx = plan.plan.index("bigquery")
        dbt_idx = plan.plan.index("dbt_core")
        n8n_idx = plan.plan.index("n8n")
        looker_idx = plan.plan.index("looker")

        # warehouse < transform < ingestion < reporting
        assert bq_idx < dbt_idx, "BigQuery should come before dbt"
        assert dbt_idx < n8n_idx, "dbt should come before n8n"
        assert n8n_idx < looker_idx, "n8n should come before Looker"

    def test_heuristic_all_integrations_present(self):
        """All input integrations should appear in the plan."""
        integrations = [
            {"tool_type": "snowflake"},
            {"tool_type": "dbt_cloud"},
            {"tool_type": "airbyte"},
            {"tool_type": "airflow"},
            {"tool_type": "tableau"},
        ]
        plan = plan_heuristic(integrations)

        for intg in integrations:
            assert intg["tool_type"] in plan.plan

    def test_heuristic_reasons_provided(self):
        """Each adapter in the plan should have a reason."""
        integrations = [
            {"tool_type": "bigquery"},
            {"tool_type": "dbt_core"},
            {"tool_type": "n8n"},
        ]
        plan = plan_heuristic(integrations)

        for tool in plan.plan:
            assert tool in plan.reasons
            assert len(plan.reasons[tool]) > 0

    def test_plan_serialization_roundtrip(self):
        """ExtractionPlan should survive dict serialization."""
        plan = ExtractionPlan(
            plan=["bigquery", "dbt_core", "n8n"],
            reasons={"bigquery": "warehouse first", "dbt_core": "transform", "n8n": "ingestion"},
            source="heuristic",
        )
        d = plan.to_dict()
        restored = ExtractionPlan.from_dict(d)

        assert restored.plan == plan.plan
        assert restored.reasons == plan.reasons
        assert restored.source == plan.source

    def test_planner_input_serialization(self):
        """PlannerInput should serialize cleanly."""
        pi = PlannerInput(
            integrations=[{"tool_type": "bigquery"}, {"tool_type": "n8n"}],
            goals=["connect ingestion to raw"],
        )
        d = pi.to_dict()
        assert len(d["integrations"]) == 2
        assert d["goals"] == ["connect ingestion to raw"]


# ---- 7) Reconciler proposes n8n->raw writes when missing ----
# (Uses bridge rules as a proxy — LLM reconciler would do the same
# but requires LLM call; we test the deterministic bridge equivalent)

class TestReconcilerBridgeEquivalent:
    def test_bridge_result_documents_rule(self, n8n_bq_dbt_graph):
        """Bridge result should document which rule was applied."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()

        assert len(result.rules_applied) >= 1
        rule_info = result.rules_applied[0]
        assert rule_info["rule"] == "bridge_missing_ingestion"
        assert rule_info["orphaned_raw_datasets"] >= 2
        assert "n8n" in rule_info["ingestion_platforms"]

    def test_bridge_result_serializes(self, n8n_bq_dbt_graph):
        """BridgeResult.to_dict() should produce clean output."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()
        d = result.to_dict()

        assert isinstance(d["added_nodes"], int)
        assert isinstance(d["added_edges"], int)
        assert d["added_nodes"] >= 1
        assert d["added_edges"] >= 2


# ---- Lane overview view integration tests ----

class TestLaneOverviewView:
    def test_view_type_is_lane_pipeline_overview(self, n8n_bq_dbt_graph):
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()
        assert view.view_type == "lane_pipeline_overview"

    def test_has_lane_metadata(self, n8n_bq_dbt_graph):
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        assert view.lanes is not None
        assert len(view.lanes) >= 1

        lane_names = {l.name for l in view.lanes}
        # At minimum: warehouse_raw and transformation should be populated
        assert PipelineLane.WAREHOUSE_RAW.value in lane_names
        assert PipelineLane.TRANSFORMATION.value in lane_names

    def test_lane_x_positions_increase_left_to_right(self, n8n_bq_dbt_graph):
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        lane_by_name = {l.name: l for l in view.lanes}
        all_lanes = sorted(view.lanes, key=lambda l: l.order)
        for i in range(len(all_lanes) - 1):
            assert all_lanes[i].x <= all_lanes[i + 1].x

    def test_edges_connect_nodes_in_view(self, n8n_bq_dbt_graph):
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        node_ids = {n.id for n in view.nodes}
        for edge in view.edges:
            assert edge.source_id in node_ids, f"Edge source {edge.source_id} not in node set"
            assert edge.target_id in node_ids, f"Edge target {edge.target_id} not in node set"

    def test_deterministic_positions(self, n8n_bq_dbt_graph):
        """Same graph → same positions on repeated calls."""
        builder1 = ViewBuilder(n8n_bq_dbt_graph)
        view1 = builder1.build_lane_pipeline_overview()

        builder2 = ViewBuilder(n8n_bq_dbt_graph)
        view2 = builder2.build_lane_pipeline_overview()

        nodes1 = sorted(view1.nodes, key=lambda n: n.id)
        nodes2 = sorted(view2.nodes, key=lambda n: n.id)

        assert len(nodes1) == len(nodes2)
        for n1, n2 in zip(nodes1, nodes2):
            assert n1.id == n2.id
            assert n1.x == n2.x
            assert n1.y == n2.y

    def test_serialization_to_dict(self, n8n_bq_dbt_graph):
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()
        d = view.to_dict()

        assert d["viewType"] == "lane_pipeline_overview"
        assert isinstance(d["nodes"], list)
        assert isinstance(d["edges"], list)
        assert "lanes" in d
        assert isinstance(d["lanes"], list)

    def test_n8n_tool_in_ingestion_lane(self, n8n_bq_dbt_graph):
        """n8n tool should appear in the ingestion lane."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        n8n_nodes = [n for n in view.nodes if n.platform == "n8n"]
        assert len(n8n_nodes) >= 1, "n8n should appear in overview"
        for vn in n8n_nodes:
            assert vn.layer == PipelineLane.INGESTION.value, (
                f"n8n tool {vn.name} should be in ingestion lane, got {vn.layer}"
            )

    def test_looker_in_reporting_lane(self, n8n_bq_dbt_graph):
        """Looker dashboard should be in reporting lane."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        looker_nodes = [n for n in view.nodes if n.platform == "looker"]
        assert len(looker_nodes) >= 1
        for vn in looker_nodes:
            assert vn.layer == PipelineLane.REPORTING.value


# ---- Zone classification unit tests ----

class TestZoneClassification:
    def test_raw_schema_pattern(self):
        """Node with 'raw' in schema should be classified as raw."""
        node = _make_node(
            "events", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="raw", schema="analytics_events",
            fqn="raw.analytics_events.events",
        )
        assert classify_dataset_zone(node) == DatasetZone.RAW

    def test_staging_path_pattern(self):
        """dbt model with staging path should be classified as staging."""
        node = _make_node(
            "stg_users", NodeType.MODEL, "dbt",
            PlatformDomain.TRANSFORM,
            raw_metadata={"dbt_resource_type": "model", "dbt_path": "models/staging/stg_users.sql"},
        )
        assert classify_dataset_zone(node) == DatasetZone.STAGING

    def test_mart_pattern(self):
        """Node with 'mart' in schema should be classified as mart."""
        node = _make_node(
            "dim_customer", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="analytics", schema="marts",
            fqn="analytics.marts.dim_customer",
        )
        assert classify_dataset_zone(node) == DatasetZone.MART

    def test_analytics_pattern(self):
        """Node with 'analytics' in name should be classified as analytics."""
        node = _make_node(
            "analytics_daily_revenue", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="reporting", schema="analytics",
            fqn="reporting.analytics.analytics_daily_revenue",
        )
        assert classify_dataset_zone(node) == DatasetZone.ANALYTICS


class TestActorCapabilityClassification:
    def test_n8n_is_ingestion(self):
        node = _make_node("n8n", NodeType.CONNECTOR, "n8n", PlatformDomain.INGESTION)
        assert classify_actor_capability(node) == ActorCapability.INGESTION

    def test_dbt_is_transformation(self):
        node = _make_node("dbt_run", NodeType.TASK, "dbt", PlatformDomain.TRANSFORM)
        assert classify_actor_capability(node) == ActorCapability.TRANSFORMATION

    def test_airflow_is_orchestration(self):
        node = _make_node("daily_dag", NodeType.DAG, "airflow", PlatformDomain.ORCHESTRATION)
        assert classify_actor_capability(node) == ActorCapability.ORCHESTRATION

    def test_looker_is_reporting(self):
        node = _make_node("looker", NodeType.DASHBOARD, "looker", PlatformDomain.BI)
        assert classify_actor_capability(node) == ActorCapability.REPORTING
