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
from scanner.lineage.engine.views import ViewBuilder, _derive_semantic_type
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

    def test_lane_overview_has_bigquery_tool_in_warehouse_layer(self, n8n_bq_dbt_graph):
        """After dedup, BigQuery should appear once with layer=WAREHOUSE and warehouse_raw in lanes."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_nodes = [n for n in view.nodes if n.platform == "bigquery"]
        assert len(bq_nodes) == 1, f"BigQuery should appear exactly once, got {len(bq_nodes)}"
        assert bq_nodes[0].layer == "WAREHOUSE"
        assert "warehouse_raw" in bq_nodes[0].metadata.get("lanes", [])


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
        """Inferred bridge edges should have confidence <= 0.5."""
        engine = BridgeRuleEngine(n8n_bq_dbt_graph)
        result = engine.apply_all()

        for edge in result.added_edges:
            if edge.canonical_edge_type == "writes":
                assert edge.confidence <= 0.5
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
        """ViewBuilder places dbt tool with layer=TRANSFORMATION."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        dbt_nodes = [
            n for n in view.nodes
            if n.platform == "dbt" and n.layer == "TRANSFORMATION"
        ]
        assert len(dbt_nodes) >= 1, "dbt should appear with TRANSFORMATION layer"


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

    def test_lane_overview_bigquery_has_warehouse_analytics_lane(self, n8n_bq_dbt_graph):
        """After dedup, the single BigQuery node should list warehouse_analytics in its lanes."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_nodes = [n for n in view.nodes if n.platform == "bigquery"]
        assert len(bq_nodes) == 1, "BigQuery should appear exactly once after dedup"
        assert "warehouse_analytics" in bq_nodes[0].metadata.get("lanes", []), (
            "BigQuery should list warehouse_analytics in its lanes metadata"
        )


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
        # After dedup, lanes use PipelineLayer names (WAREHOUSE, TRANSFORMATION, etc.)
        assert "WAREHOUSE" in lane_names
        assert "TRANSFORMATION" in lane_names

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

    def test_n8n_tool_in_ingestion_layer(self, n8n_bq_dbt_graph):
        """n8n tool should have layer=INGESTION after dedup."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        n8n_nodes = [n for n in view.nodes if n.platform == "n8n"]
        assert len(n8n_nodes) >= 1, "n8n should appear in overview"
        for vn in n8n_nodes:
            assert vn.layer == "INGESTION", (
                f"n8n tool {vn.name} should have INGESTION layer, got {vn.layer}"
            )

    def test_looker_in_reporting_layer(self, n8n_bq_dbt_graph):
        """Looker dashboard should have layer=REPORTING after dedup."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        looker_nodes = [n for n in view.nodes if n.platform == "looker"]
        assert len(looker_nodes) >= 1
        for vn in looker_nodes:
            assert vn.layer == "REPORTING"


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


# ---- Enriched ViewNode metadata tests ----

class TestEnrichedViewNodeMetadata:
    def test_health_summary_present(self, n8n_bq_dbt_graph):
        """Every ViewNode should have a healthSummary in metadata."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for vn in view.nodes:
            hs = vn.metadata.get("healthSummary")
            assert hs is not None, f"Node {vn.name} missing healthSummary"
            for key in ("healthy", "degraded", "failing", "unknown", "stale"):
                assert key in hs, f"Node {vn.name} healthSummary missing '{key}'"

    def test_job_count_present(self, n8n_bq_dbt_graph):
        """Every ViewNode should have a jobCount in metadata."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for vn in view.nodes:
            assert "jobCount" in vn.metadata, f"Node {vn.name} missing jobCount"
            assert isinstance(vn.metadata["jobCount"], int)

    def test_sub_nodes_present(self, n8n_bq_dbt_graph):
        """Every ViewNode should have subNodes list and totalSubNodeCount."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for vn in view.nodes:
            assert "subNodes" in vn.metadata, f"Node {vn.name} missing subNodes"
            assert isinstance(vn.metadata["subNodes"], list)
            assert "totalSubNodeCount" in vn.metadata
            # Sub-nodes should have required fields
            for sn in vn.metadata["subNodes"]:
                assert "id" in sn
                assert "name" in sn
                assert "type" in sn

    def test_coverage_gaps_present(self, n8n_bq_dbt_graph):
        """Every ViewNode should have a coverageGaps list."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for vn in view.nodes:
            assert "coverageGaps" in vn.metadata
            assert isinstance(vn.metadata["coverageGaps"], list)

    def test_pipeline_stack_tool_gets_no_data_gap(self):
        """A tool from pipeline stack with 0 assets should get 'no_data_extracted' gap."""
        graph = LineageGraph()
        tool_nodes = [{"toolType": "fivetran", "integrationId": "ft_001", "name": "Fivetran"}]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        view = builder.build_lane_pipeline_overview()

        ft_nodes = [n for n in view.nodes if n.platform == "fivetran"]
        assert len(ft_nodes) >= 1
        assert "no_data_extracted" in ft_nodes[0].metadata["coverageGaps"]

    def test_enriched_metadata_serializes(self, n8n_bq_dbt_graph):
        """Enriched metadata should survive to_dict() serialization."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()
        d = view.to_dict()

        for node_dict in d["nodes"]:
            meta = node_dict["metadata"]
            assert "healthSummary" in meta
            assert "jobCount" in meta
            assert "subNodes" in meta
            assert "coverageGaps" in meta


# ---- Semantic edge type tests ----

class TestSemanticEdgeTypes:
    def test_ingestion_to_warehouse_raw(self):
        sem, label = _derive_semantic_type("ingestion", "warehouse_raw")
        assert sem == "ingests"
        assert label == "Ingests"

    def test_transformation_to_warehouse_analytics(self):
        sem, label = _derive_semantic_type("transformation", "warehouse_analytics")
        assert sem == "transforms"
        assert label == "Builds"

    def test_warehouse_analytics_to_reporting(self):
        sem, label = _derive_semantic_type("warehouse_analytics", "reporting")
        assert sem == "serves"
        assert label == "Serves"

    def test_warehouse_raw_to_transformation(self):
        sem, label = _derive_semantic_type("warehouse_raw", "transformation")
        assert sem == "feeds"
        assert label == "Feeds"

    def test_unknown_pair_falls_back(self):
        sem, label = _derive_semantic_type("reporting", "ingestion")
        assert sem == "data_flow"

    def test_edges_have_semantic_metadata(self, n8n_bq_dbt_graph):
        """ViewEdges in lane overview should have semantic metadata."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for edge in view.edges:
            assert edge.metadata, f"Edge {edge.id} has no metadata"
            assert "semanticType" in edge.metadata
            assert "label" in edge.metadata
            assert "dataFlowCount" in edge.metadata
            if not edge.inferred:
                assert edge.metadata["dataFlowCount"] > 0

    def test_edge_metadata_serializes(self, n8n_bq_dbt_graph):
        """ViewEdge metadata should appear in to_dict() output."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()
        d = view.to_dict()

        for edge_dict in d["edges"]:
            assert "metadata" in edge_dict
            assert "semanticType" in edge_dict["metadata"]


# ---- OpsSummary stats tests ----

class TestOpsSummaryStats:
    def test_ops_summary_present(self, n8n_bq_dbt_graph):
        """Stats should contain an opsSummary object."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        assert "opsSummary" in view.stats
        ops = view.stats["opsSummary"]
        assert "totalTools" in ops
        assert "totalAssets" in ops
        assert "healthDistribution" in ops
        assert "coverageGapCount" in ops

    def test_ops_summary_total_tools_matches_nodes(self, n8n_bq_dbt_graph):
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        assert view.stats["opsSummary"]["totalTools"] == len(view.nodes)

    def test_ops_summary_health_distribution_sums(self, n8n_bq_dbt_graph):
        """Health distribution values should be non-negative integers."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        hd = view.stats["opsSummary"]["healthDistribution"]
        for key in ("healthy", "degraded", "failing", "unknown", "stale"):
            assert key in hd
            assert isinstance(hd[key], int)
            assert hd[key] >= 0


# ---- Inferred lane-adjacency edge tests ----

class TestInferredLaneEdges:
    """Test Step 4a: zero-edge tools get inferred lane-adjacency edges."""

    def test_pipeline_stack_dbt_gets_inferred_edge(self):
        """dbt from pipeline stack (no graph nodes) should get inferred edges to warehouse lane."""
        graph = LineageGraph()
        # Add a BigQuery service node so warehouse_raw lane is occupied
        bq_svc = _make_node(
            "raw_table", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="project", schema="raw",
            integration_id="bq_001",
        )
        graph.add_node(bq_svc)
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        tool_nodes = [
            {"toolType": "dbt_core", "integrationId": "dbt_001", "name": "dbt"},
        ]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        view = builder.build_lane_pipeline_overview()

        dbt_nodes = [n for n in view.nodes if n.platform == "dbt_core"]
        assert len(dbt_nodes) >= 1, "dbt tool node should exist"

        dbt_id = dbt_nodes[0].id
        dbt_edges = [
            e for e in view.edges
            if e.source_id == dbt_id or e.target_id == dbt_id
        ]
        assert len(dbt_edges) > 0, "dbt should have at least one inferred edge"
        assert all(e.inferred for e in dbt_edges), "all dbt edges should be inferred"
        assert any(
            e.metadata.get("inferredReason") == "lane_adjacency"
            for e in dbt_edges
        )

    def test_pipeline_stack_airflow_gets_inferred_edge(self):
        """Airflow from pipeline stack should connect to neighbouring lanes."""
        graph = LineageGraph()
        bq_svc = _make_node(
            "raw_table", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="project", schema="raw",
            integration_id="bq_001",
        )
        graph.add_node(bq_svc)
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        tool_nodes = [
            {"toolType": "airflow", "integrationId": "af_001", "name": "Airflow"},
        ]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        view = builder.build_lane_pipeline_overview()

        af_nodes = [n for n in view.nodes if n.platform == "airflow"]
        assert len(af_nodes) >= 1, "Airflow tool node should exist"

        af_id = af_nodes[0].id
        af_edges = [
            e for e in view.edges
            if e.source_id == af_id or e.target_id == af_id
        ]
        assert len(af_edges) > 0, "Airflow should have at least one inferred edge"

    def test_pipeline_stack_linux_gets_inferred_edge(self):
        """Linux Server from pipeline stack (ingestion lane) should connect to warehouse_raw."""
        graph = LineageGraph()
        bq_svc = _make_node(
            "raw_table", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="project", schema="raw",
            integration_id="bq_001",
        )
        graph.add_node(bq_svc)
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        tool_nodes = [
            {"toolType": "linux", "integrationId": "linux_001", "name": "Linux Server"},
        ]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        view = builder.build_lane_pipeline_overview()

        linux_nodes = [n for n in view.nodes if n.platform == "linux"]
        assert len(linux_nodes) >= 1, "Linux tool node should exist"

        linux_id = linux_nodes[0].id
        linux_edges = [
            e for e in view.edges
            if e.source_id == linux_id or e.target_id == linux_id
        ]
        assert len(linux_edges) > 0, "Linux should have at least one inferred edge to warehouse"
        # Linux is in ingestion → downstream neighbor is warehouse_raw
        downstream_edges = [
            e for e in linux_edges if e.source_id == linux_id
        ]
        assert len(downstream_edges) > 0, "Linux should have downstream edge"

    def test_no_inferred_edges_when_data_flow_exists(self, n8n_bq_dbt_graph):
        """Tools with real data-flow edges should NOT get additional inferred edges."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for edge in view.edges:
            if edge.evidence_count > 0:
                # This is a real edge — no inferred companion should duplicate it
                assert not edge.inferred

    def test_inferred_edges_have_correct_metadata(self):
        """Inferred edges should carry lane_adjacency reason and low confidence."""
        graph = LineageGraph()
        bq_svc = _make_node(
            "raw_table", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="project", schema="raw",
            integration_id="bq_001",
        )
        graph.add_node(bq_svc)
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        tool_nodes = [
            {"toolType": "dbt_core", "integrationId": "dbt_001", "name": "dbt"},
        ]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        view = builder.build_lane_pipeline_overview()

        inferred = [e for e in view.edges if e.inferred]
        for edge in inferred:
            assert edge.confidence <= 0.5, "Inferred edges should have low confidence"
            assert edge.evidence_count == 0
            assert edge.metadata.get("inferredReason") == "lane_adjacency"
            assert "semanticType" in edge.metadata
            assert "label" in edge.metadata


# ---- Deduplicated tool nodes tests ----

class TestDeduplicatedToolNodes:
    """Test Step 4b: tools spanning multiple lanes are deduplicated into one node."""

    def test_bigquery_appears_once(self, n8n_bq_dbt_graph):
        """BigQuery should appear exactly once even if it has raw + analytics datasets."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_nodes = [n for n in view.nodes if n.platform == "bigquery"]
        assert len(bq_nodes) == 1, (
            f"Expected 1 BigQuery node, got {len(bq_nodes)}: "
            f"{[n.id for n in bq_nodes]}"
        )

    def test_deduplicated_node_has_canonical_id(self, n8n_bq_dbt_graph):
        """Deduplicated node ID should be tool:{tool_id} (no lane prefix)."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_nodes = [n for n in view.nodes if n.platform == "bigquery"]
        assert len(bq_nodes) == 1
        # ID should NOT contain lane names
        for lane_name in ("warehouse_raw", "warehouse_analytics", "ingestion", "transformation", "reporting"):
            # The ID pattern is tool:{tool_id}, not tool:{lane}:{tool_id}
            # After the first "tool:" prefix, the next segment should be the platform, not a lane
            parts = bq_nodes[0].id.split(":", 2)
            if len(parts) >= 3:
                assert parts[1] != lane_name, (
                    f"Node ID {bq_nodes[0].id} still has lane prefix '{lane_name}'"
                )

    def test_deduplicated_node_merges_asset_counts(self, n8n_bq_dbt_graph):
        """Merged BigQuery node should have combined asset count from both lanes."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_node = [n for n in view.nodes if n.platform == "bigquery"][0]
        # Should include raw.charges, raw.customers, analytics.fct_revenue = 3
        assert bq_node.metadata["assetCount"] >= 3

    def test_deduplicated_node_has_lanes_metadata(self, n8n_bq_dbt_graph):
        """Merged node should list its original lanes in metadata."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_node = [n for n in view.nodes if n.platform == "bigquery"][0]
        lanes = bq_node.metadata.get("lanes", [])
        assert "warehouse_raw" in lanes
        assert "warehouse_analytics" in lanes

    def test_deduplicated_node_layer_is_pipeline_layer(self, n8n_bq_dbt_graph):
        """Merged BigQuery node should have layer='WAREHOUSE'."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        bq_node = [n for n in view.nodes if n.platform == "bigquery"][0]
        assert bq_node.layer == "WAREHOUSE"

    def test_edges_reference_canonical_ids(self, n8n_bq_dbt_graph):
        """All edge source/target should reference existing canonical node IDs."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        node_ids = {n.id for n in view.nodes}
        for edge in view.edges:
            assert edge.source_id in node_ids, (
                f"Edge source {edge.source_id} not in node set {node_ids}"
            )
            assert edge.target_id in node_ids, (
                f"Edge target {edge.target_id} not in node set {node_ids}"
            )

    def test_no_self_loop_edges_after_dedup(self, n8n_bq_dbt_graph):
        """No edge should have source == target after dedup merging."""
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for edge in view.edges:
            assert edge.source_id != edge.target_id, (
                f"Self-loop edge found: {edge.id} ({edge.source_id} → {edge.target_id})"
            )

    def test_all_layers_are_valid_pipeline_layers(self, n8n_bq_dbt_graph):
        """Every ViewNode.layer should be a valid PipelineLayer key for LAYER_COLORS."""
        VALID_LAYERS = {
            "INGESTION", "TRANSFORMATION", "WAREHOUSE", "REPORTING",
            "ORCHESTRATION", "INFRASTRUCTURE", "VERSION_CONTROL", "STORAGE",
        }
        builder = ViewBuilder(n8n_bq_dbt_graph)
        view = builder.build_lane_pipeline_overview()

        for vn in view.nodes:
            assert vn.layer in VALID_LAYERS, (
                f"Node {vn.name} has layer='{vn.layer}' which is not "
                f"a valid PipelineLayer for LAYER_COLORS"
            )


# ---- Job node enrichment tests (isJob + jobSupport) ----

class TestJobNodeEnrichment:
    """Verify that isJob and jobSupport metadata are correctly set for
    Airflow, Fivetran, dbt, and BigQuery tools in the lane overview."""

    @pytest.fixture
    def multi_tool_graph(self) -> LineageGraph:
        """Graph with Airflow DAG+TASK, Fivetran CONNECTOR, dbt MODEL, BQ TABLE, Linux Server."""
        graph = LineageGraph()

        # Airflow DAG
        af_dag = _make_node(
            "etl_pipeline", NodeType.DAG, "airflow",
            PlatformDomain.ORCHESTRATION, integration_id="af_001",
        )
        # Airflow TASK
        af_task = _make_node(
            "load_data", NodeType.TASK, "airflow",
            PlatformDomain.ORCHESTRATION, integration_id="af_001",
        )
        # Fivetran service
        ft_svc = _make_node(
            "Fivetran", NodeType.CONNECTOR, "fivetran",
            PlatformDomain.INGESTION, integration_id="ft_001",
        )
        ft_svc.canonical_type = "service"
        # Fivetran connector job
        ft_conn = _make_node(
            "stripe_connector", NodeType.CONNECTOR, "fivetran",
            PlatformDomain.INGESTION, integration_id="ft_001",
        )
        ft_conn.canonical_type = "job"
        # dbt model
        dbt_model = _make_node(
            "stg_orders", NodeType.MODEL, "dbt",
            PlatformDomain.TRANSFORM, database="analytics", schema="staging",
            fqn="analytics.staging.stg_orders", integration_id="dbt_001",
            raw_metadata={"dbt_resource_type": "model"},
        )
        # BigQuery table (plain warehouse — no jobs)
        bq_table = _make_node(
            "raw_orders", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="raw", schema="stripe",
            fqn="raw.stripe.raw_orders", integration_id="bq_001",
        )
        # Linux Server (infrastructure — no jobs)
        linux_svc = _make_node(
            "Linux Server", NodeType.SOURCE, "linux_server",
            PlatformDomain.OTHER, integration_id="linux_001",
        )
        linux_svc.canonical_type = "system"

        for node in [af_dag, af_task, ft_svc, ft_conn, dbt_model, bq_table, linux_svc]:
            graph.add_node(node)

        # Airflow: DAG → TASK
        graph.add_edge(_make_edge(
            af_dag.id, af_task.id, EdgeType.DEPENDS_ON,
        ))
        # Fivetran: service runs connector
        graph.add_edge(_make_edge(
            ft_svc.id, ft_conn.id, EdgeType.TRIGGERS,
        ))

        canonicalize_graph_in_place(graph.nodes, graph.edges)
        return graph

    def _find_tool(self, view, platform: str):
        """Find first ViewNode matching platform."""
        return next((vn for vn in view.nodes if vn.platform == platform), None)

    def test_airflow_job_count(self, multi_tool_graph):
        """Airflow tool should count DAG + TASK as jobs."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        af = self._find_tool(view, "airflow")
        assert af is not None, "Airflow tool not found in view"
        assert af.metadata["jobCount"] >= 2

    def test_airflow_sub_nodes_have_is_job(self, multi_tool_graph):
        """Airflow subNodes with canonical_type=job should have isJob=True."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        af = self._find_tool(view, "airflow")
        job_subs = [sn for sn in af.metadata["subNodes"] if sn.get("isJob")]
        assert len(job_subs) >= 2

    def test_fivetran_job_count(self, multi_tool_graph):
        """Fivetran connector should count as 1 job."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        ft = self._find_tool(view, "fivetran")
        assert ft is not None, "Fivetran tool not found in view"
        # Connector job node has canonical_type="job"
        assert ft.metadata["jobCount"] >= 1

    def test_fivetran_sub_node_is_job(self, multi_tool_graph):
        """Fivetran connector subNode should have isJob=True."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        ft = self._find_tool(view, "fivetran")
        job_subs = [sn for sn in ft.metadata["subNodes"] if sn.get("isJob")]
        assert len(job_subs) >= 1

    def test_dbt_model_is_job(self, multi_tool_graph):
        """dbt model should be counted as a job via dbt_resource_type."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        dbt = self._find_tool(view, "dbt")
        assert dbt is not None, "dbt tool not found in view"
        assert dbt.metadata["jobCount"] >= 1
        # Model has canonical_type="dataset" but isJob=True
        model_subs = [sn for sn in dbt.metadata["subNodes"]
                      if sn["name"] == "stg_orders"]
        assert len(model_subs) == 1
        assert model_subs[0]["isJob"] is True
        assert model_subs[0]["type"] == "dataset"

    def test_bigquery_job_count_zero(self, multi_tool_graph):
        """BigQuery warehouse tool should have jobCount=0."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        bq = self._find_tool(view, "bigquery")
        assert bq is not None, "BigQuery tool not found in view"
        assert bq.metadata["jobCount"] == 0

    def test_bigquery_job_support_not_applicable(self, multi_tool_graph):
        """BigQuery warehouse tool should have jobSupport='not_applicable'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        bq = self._find_tool(view, "bigquery")
        assert bq.metadata["jobSupport"] == "not_applicable"

    def test_bigquery_sub_nodes_not_jobs(self, multi_tool_graph):
        """Plain table subNodes should have isJob=False."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        bq = self._find_tool(view, "bigquery")
        for sn in bq.metadata["subNodes"]:
            assert sn.get("isJob") is False, (
                f"BigQuery subNode {sn['name']} should not be marked as job"
            )

    def test_orchestrator_job_support_full(self, multi_tool_graph):
        """Airflow (orchestrator) should have jobSupport='full'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        af = self._find_tool(view, "airflow")
        assert af.metadata["jobSupport"] == "full"

    def test_pipeline_stack_tool_job_support_no_data(self):
        """A pipeline-stack-only tool with 0 assets should have jobSupport='no_data'."""
        graph = LineageGraph()
        tool_nodes = [{"toolType": "fivetran", "integrationId": "ft_new", "name": "Fivetran"}]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        view = builder.build_lane_pipeline_overview()

        ft_nodes = [n for n in view.nodes if n.platform == "fivetran"]
        assert len(ft_nodes) >= 1
        assert ft_nodes[0].metadata["jobSupport"] == "no_data"

    def test_airflow_layer_is_orchestration(self, multi_tool_graph):
        """Airflow tool should have layer='ORCHESTRATION', not 'transformation'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        af = self._find_tool(view, "airflow")
        assert af is not None, "Airflow tool not found in view"
        assert af.layer == "ORCHESTRATION", f"Airflow layer should be ORCHESTRATION, got {af.layer}"

    def test_linux_server_layer_is_infrastructure(self, multi_tool_graph):
        """Linux Server should have layer='INFRASTRUCTURE', not 'ingestion'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        linux = self._find_tool(view, "linux_server")
        assert linux is not None, "Linux Server tool not found in view"
        assert linux.layer == "INFRASTRUCTURE", f"Linux Server layer should be INFRASTRUCTURE, got {linux.layer}"

    def test_bigquery_layer_is_warehouse(self, multi_tool_graph):
        """BigQuery should have layer='WAREHOUSE'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        bq = self._find_tool(view, "bigquery")
        assert bq is not None, "BigQuery tool not found in view"
        assert bq.layer == "WAREHOUSE", f"BigQuery layer should be WAREHOUSE, got {bq.layer}"

    def test_fivetran_layer_is_ingestion(self, multi_tool_graph):
        """Fivetran should have layer='INGESTION'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        ft = self._find_tool(view, "fivetran")
        assert ft is not None, "Fivetran tool not found in view"
        assert ft.layer == "INGESTION", f"Fivetran layer should be INGESTION, got {ft.layer}"

    def test_dbt_layer_is_transformation(self, multi_tool_graph):
        """dbt should have layer='TRANSFORMATION'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        dbt = self._find_tool(view, "dbt")
        assert dbt is not None, "dbt tool not found in view"
        assert dbt.layer == "TRANSFORMATION", f"dbt layer should be TRANSFORMATION, got {dbt.layer}"

    def test_linux_server_job_support_not_applicable(self, multi_tool_graph):
        """Linux Server (infrastructure) should have jobSupport='not_applicable'."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        linux = self._find_tool(view, "linux_server")
        assert linux is not None, "Linux Server tool not found in view"
        assert linux.metadata["jobSupport"] == "not_applicable"

    def test_linux_server_job_count_zero(self, multi_tool_graph):
        """Linux Server (infrastructure) should have jobCount=0."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        linux = self._find_tool(view, "linux_server")
        assert linux is not None, "Linux Server tool not found in view"
        assert linux.metadata["jobCount"] == 0

    def test_is_job_field_present_on_all_sub_nodes(self, multi_tool_graph):
        """Every subNode should have an isJob boolean field."""
        builder = ViewBuilder(multi_tool_graph)
        view = builder.build_lane_pipeline_overview()
        for vn in view.nodes:
            for sn in vn.metadata.get("subNodes", []):
                assert "isJob" in sn, (
                    f"subNode {sn['name']} in {vn.name} missing isJob field"
                )
                assert isinstance(sn["isJob"], bool)


# ---- Tool Details Tests ----

class TestToolDetails:
    """Tests for ViewBuilder.build_tool_details()."""

    @pytest.fixture
    def tool_details_graph(self) -> LineageGraph:
        """Graph with multiple tool types for detail testing."""
        graph = LineageGraph()

        # Fivetran connector
        ft_conn = _make_node(
            "stripe_connector", NodeType.CONNECTOR, "fivetran",
            PlatformDomain.INGESTION, integration_id="ft_001",
            raw_metadata={"connector_id": "conn_abc", "dest_schema": "raw_stripe",
                          "synced_tables": ["charges", "customers"], "node_role": "connector_job"},
        )
        ft_conn.canonical_type = "job"
        graph.add_node(ft_conn)

        # Fivetran destination table
        ft_dest = _make_node(
            "charges", NodeType.TABLE, "fivetran",
            PlatformDomain.INGESTION, database="raw", schema="raw_stripe",
            fqn="raw.raw_stripe.charges", integration_id="ft_001",
        )
        ft_dest.canonical_type = "dataset"
        graph.add_node(ft_dest)

        # dbt models
        dbt_stg = _make_node(
            "stg_charges", NodeType.MODEL, "dbt",
            PlatformDomain.TRANSFORM, database="analytics", schema="staging",
            fqn="analytics.staging.stg_charges",
            raw_metadata={"dbt_resource_type": "model", "materialized": "view", "zone": "staging"},
        )
        dbt_stg.canonical_type = "dataset"
        graph.add_node(dbt_stg)

        dbt_mart = _make_node(
            "fct_revenue", NodeType.MODEL, "dbt",
            PlatformDomain.TRANSFORM, database="analytics", schema="marts",
            fqn="analytics.marts.fct_revenue",
            raw_metadata={"dbt_resource_type": "model", "materialized": "table", "zone": "mart"},
        )
        dbt_mart.canonical_type = "dataset"
        graph.add_node(dbt_mart)

        dbt_test = _make_node(
            "not_null_orders_id", NodeType.MONITOR, "dbt",
            PlatformDomain.TRANSFORM,
            raw_metadata={"dbt_resource_type": "test"},
        )
        dbt_test.canonical_type = "test"
        graph.add_node(dbt_test)

        # BigQuery tables
        bq_raw = _make_node(
            "raw_orders", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="project", schema="raw",
            fqn="project.raw.raw_orders", integration_id="bq_001",
        )
        bq_raw.canonical_type = "dataset"
        graph.add_node(bq_raw)

        bq_analytics = _make_node(
            "dim_customers", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="project", schema="analytics",
            fqn="project.analytics.dim_customers", integration_id="bq_001",
        )
        bq_analytics.canonical_type = "dataset"
        graph.add_node(bq_analytics)

        # Linux server
        linux = _make_node(
            "prod-server-01", NodeType.SOURCE, "linux_server",
            PlatformDomain.OTHER,
            raw_metadata={"running_services": ["nginx", "postgres"], "hosted_tools": ["n8n"]},
        )
        linux.canonical_type = "system"
        graph.add_node(linux)

        # Edges: fivetran → bigquery
        graph.add_edge(_make_edge(ft_dest.id, bq_raw.id, EdgeType.DERIVED_FROM))
        # dbt reads bigquery
        graph.add_edge(_make_edge(bq_raw.id, dbt_stg.id, EdgeType.DERIVED_FROM))

        canonicalize_graph_in_place(graph.nodes, graph.edges)
        return graph

    def test_tool_details_warehouse(self, tool_details_graph):
        """BigQuery returns datasets + tables tabs."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:bigquery")

        assert result["platform"] == "bigquery"
        assert result["category"] == "warehouse"
        assert "error" not in result

        tab_keys = [t["key"] for t in result["tabs"]]
        assert "datasets" in tab_keys
        assert "tables" in tab_keys

        # Should have 2 tables (raw_orders + dim_customers)
        tables = result["groups"].get("tables", [])
        assert len(tables) == 2

        # Should have 2 schemas (raw + analytics)
        datasets = result["groups"].get("datasets", [])
        assert len(datasets) == 2

    def test_tool_details_transform(self, tool_details_graph):
        """dbt returns models + tests tabs."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:dbt")

        assert result["platform"] == "dbt"
        assert result["category"] == "transformation"

        tab_keys = [t["key"] for t in result["tabs"]]
        assert "models" in tab_keys
        assert "tests" in tab_keys

        models = result["groups"].get("models", [])
        assert len(models) == 2  # stg_charges + fct_revenue

        tests = result["groups"].get("tests", [])
        assert len(tests) == 1  # not_null_orders_id

        # Models should have zone info
        zones = {m["zone"] for m in models}
        assert "staging" in zones
        assert "mart" in zones

    def test_tool_details_ingestion(self, tool_details_graph):
        """Fivetran returns connectors + destinations tabs."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:fivetran:ft_001")

        assert result["platform"] == "fivetran"
        assert result["category"] == "ingestion"
        assert result["integrationId"] == "ft_001"

        tab_keys = [t["key"] for t in result["tabs"]]
        assert "connectors" in tab_keys
        assert "destinations" in tab_keys

        connectors = result["groups"].get("connectors", [])
        assert len(connectors) >= 1

        destinations = result["groups"].get("destinations", [])
        assert len(destinations) >= 1

    def test_tool_details_infra(self, tool_details_graph):
        """Linux server returns services + hosts tabs."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:linux_server")

        assert result["category"] == "infrastructure"

        tab_keys = [t["key"] for t in result["tabs"]]
        assert "services" in tab_keys
        assert "hosts" in tab_keys

        services = result["groups"].get("services", [])
        # Should have running_services (nginx, postgres) + hosted_tools (n8n) = 3
        assert len(services) == 3

    def test_tool_details_missing_tool(self, tool_details_graph):
        """Unknown tool_view_id returns empty with coverage gap."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:nonexistent_platform")

        assert result["summary"]["totalAssets"] == 0
        assert "no_data_extracted" in result["summary"]["coverageGaps"]

    def test_tool_details_connections(self, tool_details_graph):
        """BigQuery should show upstream (fivetran) and downstream (dbt) connections."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:bigquery")

        upstream = result["connections"]["upstream"]
        downstream = result["connections"]["downstream"]

        upstream_platforms = {c["platform"] for c in upstream}
        downstream_platforms = {c["platform"] for c in downstream}

        assert "fivetran" in upstream_platforms
        assert "dbt" in downstream_platforms

    def test_tool_details_response_shape(self, tool_details_graph):
        """Verify the response has all required top-level keys."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:bigquery")

        required_keys = {"toolId", "platform", "platformDomain", "category",
                         "displayName", "integrationId", "summary", "tabs",
                         "groups", "connections"}
        assert required_keys.issubset(set(result.keys()))

        summary_keys = {"totalAssets", "healthSummary", "jobCount", "lastRunTs", "coverageGaps"}
        assert summary_keys.issubset(set(result["summary"].keys()))

        conn_keys = {"upstream", "downstream"}
        assert conn_keys.issubset(set(result["connections"].keys()))

    def test_tool_details_alias_resolution(self, tool_details_graph):
        """Requesting tool:dbt_core should still find nodes with platform='dbt' (alias)."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:dbt_core")

        # dbt_core is the primary name, "dbt" is an alias — nodes have platform="dbt"
        assert result["category"] == "transformation"
        models = result["groups"].get("models", [])
        assert len(models) == 2  # stg_charges + fct_revenue

    def test_tool_details_original_type_on_items(self, tool_details_graph):
        """Items should have meaningful originalType from node_type.value, not empty."""
        builder = ViewBuilder(tool_details_graph)
        result = builder.build_tool_details("tool:dbt")

        models = result["groups"].get("models", [])
        for m in models:
            assert m["originalType"] != "", f"originalType should not be empty for {m['name']}"
            # dbt models have NodeType.MODEL → "model"
            assert m["originalType"] in ("model", "dataset")

    def test_tool_details_discovered_platforms(self, tool_details_graph):
        """After resolver merge, dbt models become bigquery nodes but retain discovered_platforms."""
        graph = tool_details_graph

        # Simulate resolver merge: node has platform=bigquery but discovered_platforms includes dbt
        merged = _make_node(
            "stg_merged", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, database="analytics", schema="staging",
            fqn="analytics.staging.stg_merged",
            raw_metadata={
                "dbt_resource_type": "model",
                "materialized": "view",
                "discovered_platforms": ["bigquery", "dbt_core"],
            },
        )
        merged.canonical_type = "dataset"
        graph.add_node(merged)

        builder = ViewBuilder(graph)
        result = builder.build_tool_details("tool:dbt")

        # The merged node should appear in dbt's models tab via discovered_platforms
        models = result["groups"].get("models", [])
        model_names = {m["name"] for m in models}
        assert "stg_merged" in model_names
