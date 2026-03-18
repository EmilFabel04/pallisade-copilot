"""Tests for pipeline monitor presets and smart builder."""

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
from scanner.monitors.presets import (
    PRESET_DEFINITIONS,
    PresetPreviewResult,
    check_preset_eligibility,
    get_all_presets,
    preview_preset,
    smart_build_preview,
)
from scanner.monitors.scope import DEFAULT_SCOPE, _recipe_for_watch_type


# ---------------------------------------------------------------------------
# Helpers — build mock lineage graphs
# ---------------------------------------------------------------------------

def _make_node(
    id: str,
    name: str,
    fqn: str,
    platform_domain: PlatformDomain,
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
    """Helper to add a simple edge to the graph."""
    edge = LineageEdge(
        id=f"{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.DERIVED_FROM,
    )
    graph.add_edge(edge)


def _build_warehouse_pipeline_graph() -> LineageGraph:
    """Build a simple pipeline: connector -> raw_table -> model -> final_table (anchor)."""
    graph = LineageGraph()

    connector = _make_node(
        "conn-1", "fivetran_connector", "fivetran.connector_1",
        PlatformDomain.INGESTION, NodeType.CONNECTOR, AssetKind.CONNECTOR,
        platform="fivetran",
    )
    raw_table = _make_node(
        "raw-1", "raw_events", "project.raw.events",
        PlatformDomain.WAREHOUSE, NodeType.TABLE, AssetKind.TABLE,
        downstream_count=3,
    )
    dbt_model = _make_node(
        "model-1", "stg_events", "project.staging.stg_events",
        PlatformDomain.TRANSFORM, NodeType.MODEL, AssetKind.MODEL,
        platform="dbt_cloud",
    )
    final_table = _make_node(
        "final-1", "dim_events", "project.analytics.dim_events",
        PlatformDomain.WAREHOUSE, NodeType.TABLE, AssetKind.TABLE,
        criticality="high", downstream_count=10,
    )

    graph.add_node(connector)
    graph.add_node(raw_table)
    graph.add_node(dbt_model)
    graph.add_node(final_table)

    _add_edge(graph,connector.id, raw_table.id)
    _add_edge(graph,raw_table.id, dbt_model.id)
    _add_edge(graph,dbt_model.id, final_table.id)

    return graph


def _build_bi_pipeline_graph() -> LineageGraph:
    """Build pipeline with BI: connectors -> raw tables -> models -> final tables -> dashboard.

    Large enough that the dashboard_shield watch (capped to its scope) doesn't cover
    everything, leaving monitors for the second pipeline_health watch.
    """
    graph = LineageGraph()

    # 2 connectors
    for i in range(2):
        graph.add_node(_make_node(
            f"conn-{i}", f"connector_{i}", f"fivetran.conn_{i}",
            PlatformDomain.INGESTION, NodeType.CONNECTOR, AssetKind.CONNECTOR,
            platform="fivetran",
        ))

    # 4 raw warehouse tables
    for i in range(4):
        graph.add_node(_make_node(
            f"raw-{i}", f"raw_table_{i}", f"project.raw.table_{i}",
            PlatformDomain.WAREHOUSE, NodeType.TABLE, AssetKind.TABLE,
            downstream_count=2,
        ))
        _add_edge(graph, f"conn-{i % 2}", f"raw-{i}")

    # 4 dbt models
    for i in range(4):
        graph.add_node(_make_node(
            f"model-{i}", f"stg_model_{i}", f"project.staging.stg_{i}",
            PlatformDomain.TRANSFORM, NodeType.MODEL, AssetKind.MODEL,
            platform="dbt_cloud",
        ))
        _add_edge(graph, f"raw-{i}", f"model-{i}")

    # 2 final warehouse tables
    for i in range(2):
        graph.add_node(_make_node(
            f"final-{i}", f"dim_table_{i}", f"project.analytics.dim_{i}",
            PlatformDomain.WAREHOUSE, NodeType.TABLE, AssetKind.TABLE,
            criticality="high", downstream_count=5,
        ))
        _add_edge(graph, f"model-{i * 2}", f"final-{i}")
        _add_edge(graph, f"model-{i * 2 + 1}", f"final-{i}")

    # Dashboard depends on both final tables
    dashboard = _make_node(
        "dash-1", "Revenue Dashboard", "looker.dashboard.revenue",
        PlatformDomain.BI, NodeType.DASHBOARD, AssetKind.DASHBOARD,
        platform="looker", criticality="critical", downstream_count=0,
    )
    graph.add_node(dashboard)
    _add_edge(graph, "final-0", "dash-1")
    _add_edge(graph, "final-1", "dash-1")

    return graph


def _build_wide_graph() -> LineageGraph:
    """Build a wide graph with many nodes across domains for Full Coverage test."""
    graph = LineageGraph()

    # 3 connectors
    for i in range(3):
        graph.add_node(_make_node(
            f"conn-{i}", f"connector_{i}", f"fivetran.conn_{i}",
            PlatformDomain.INGESTION, NodeType.CONNECTOR, AssetKind.CONNECTOR,
            platform="fivetran",
        ))

    # 5 raw warehouse tables
    for i in range(5):
        graph.add_node(_make_node(
            f"raw-{i}", f"raw_table_{i}", f"project.raw.table_{i}",
            PlatformDomain.WAREHOUSE, NodeType.TABLE, AssetKind.TABLE,
            downstream_count=3,
        ))
        # Wire connectors to raw tables
        _add_edge(graph,f"conn-{i % 3}", f"raw-{i}")

    # 3 dbt models
    for i in range(3):
        graph.add_node(_make_node(
            f"model-{i}", f"stg_model_{i}", f"project.staging.stg_{i}",
            PlatformDomain.TRANSFORM, NodeType.MODEL, AssetKind.MODEL,
            platform="dbt_cloud",
        ))
        _add_edge(graph,f"raw-{i}", f"model-{i}")

    # 3 warehouse final tables
    for i in range(3):
        graph.add_node(_make_node(
            f"final-{i}", f"dim_table_{i}", f"project.analytics.dim_{i}",
            PlatformDomain.WAREHOUSE, NodeType.TABLE, AssetKind.TABLE,
            criticality="high", downstream_count=5,
        ))
        _add_edge(graph,f"model-{i}", f"final-{i}")

    # 1 dashboard
    graph.add_node(_make_node(
        "dash-0", "Main Dashboard", "looker.dashboard.main",
        PlatformDomain.BI, NodeType.DASHBOARD, AssetKind.DASHBOARD,
        platform="looker", criticality="critical",
    ))
    _add_edge(graph,"final-0", "dash-0")

    # 1 DAG
    graph.add_node(_make_node(
        "dag-0", "etl_pipeline", "airflow.dag.etl_pipeline",
        PlatformDomain.ORCHESTRATION, NodeType.DAG, AssetKind.WORKFLOW,
        platform="airflow",
    ))
    _add_edge(graph,"dag-0", "model-0")

    return graph


# ---------------------------------------------------------------------------
# data_drift scope config & recipe
# ---------------------------------------------------------------------------

class TestDataDriftScopeConfig:
    def test_data_drift_in_default_scope(self):
        assert "data_drift" in DEFAULT_SCOPE

    def test_data_drift_scope_values(self):
        cfg = DEFAULT_SCOPE["data_drift"]
        assert cfg["maxDepth"] == 3
        assert cfg["maxNodes"] == 12
        assert cfg["maxMonitors"] == 10
        assert "warehouse" in cfg["domainFilters"]
        assert "transform" in cfg["domainFilters"]
        assert "ingestion" in cfg["domainFilters"]

    def test_data_drift_recipe_includes_quality_monitors(self):
        """Data drift recipe should include quality-focused monitors (new canonical types)."""
        anchor = _make_node("x", "x", "x", PlatformDomain.WAREHOUSE)
        recipe = _recipe_for_watch_type("data_drift", anchor)
        monitor_keys = [r[0] for r in recipe]
        assert "SCHEMA_CHANGE" in monitor_keys
        assert "VOLUME" in monitor_keys
        assert "NULL_CHECK" in monitor_keys
        assert "UNIQUENESS_CHECK" in monitor_keys
        assert "FRESHNESS" in monitor_keys
        assert "OUTLIER_DETECTION" in monitor_keys

    def test_data_drift_recipe_includes_drift_monitors(self):
        anchor = _make_node("x", "x", "x", PlatformDomain.WAREHOUSE)
        recipe = _recipe_for_watch_type("data_drift", anchor)
        monitor_keys = [r[0] for r in recipe]
        assert "CONNECTOR_SCHEMA_DRIFT" in monitor_keys
        assert "NULL_CHECK" in monitor_keys


# ---------------------------------------------------------------------------
# Preset eligibility
# ---------------------------------------------------------------------------

class TestPresetEligibility:
    def test_pipeline_health_eligible_for_warehouse(self):
        node = _make_node("n", "t", "t", PlatformDomain.WAREHOUSE)
        assert check_preset_eligibility(node, "pipeline_health") is True

    def test_pipeline_health_not_eligible_for_bi(self):
        node = _make_node(
            "n", "d", "d", PlatformDomain.BI,
            node_type=NodeType.DASHBOARD, asset_kind=AssetKind.DASHBOARD,
        )
        assert check_preset_eligibility(node, "pipeline_health") is False

    def test_bi_reliability_eligible_for_bi(self):
        node = _make_node(
            "n", "d", "d", PlatformDomain.BI,
            node_type=NodeType.DASHBOARD, asset_kind=AssetKind.DASHBOARD,
        )
        assert check_preset_eligibility(node, "bi_reliability") is True

    def test_bi_reliability_not_eligible_for_warehouse(self):
        node = _make_node("n", "t", "t", PlatformDomain.WAREHOUSE)
        assert check_preset_eligibility(node, "bi_reliability") is False

    def test_full_coverage_eligible_for_any_domain(self):
        for domain in [PlatformDomain.WAREHOUSE, PlatformDomain.BI, PlatformDomain.INGESTION]:
            node = _make_node("n", "t", "t", domain)
            assert check_preset_eligibility(node, "full_coverage") is True

    def test_data_drift_eligible_for_warehouse_and_transform(self):
        wh = _make_node("n", "t", "t", PlatformDomain.WAREHOUSE)
        tr = _make_node("n", "t", "t", PlatformDomain.TRANSFORM, asset_kind=AssetKind.MODEL)
        assert check_preset_eligibility(wh, "data_drift") is True
        assert check_preset_eligibility(tr, "data_drift") is True

    def test_unknown_preset_returns_false(self):
        node = _make_node("n", "t", "t", PlatformDomain.WAREHOUSE)
        assert check_preset_eligibility(node, "nonexistent") is False


class TestGetAllPresets:
    def test_returns_all_five_presets(self):
        presets = get_all_presets()
        assert len(presets) == 5
        keys = {p["key"] for p in presets}
        assert keys == {"pipeline_health", "data_drift", "ingestion_watch", "bi_reliability", "full_coverage"}

    def test_eligibility_filtering(self):
        wh_node = _make_node("n", "t", "t", PlatformDomain.WAREHOUSE)
        presets = get_all_presets(wh_node)
        eligible_keys = {p["key"] for p in presets if p["eligible"]}
        assert "pipeline_health" in eligible_keys
        assert "bi_reliability" not in eligible_keys


# ---------------------------------------------------------------------------
# Pipeline Health preset
# ---------------------------------------------------------------------------

class TestPipelineHealthPreset:
    def test_creates_one_watch(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "pipeline_health")
        assert len(result.watches) == 1
        assert result.watches[0].watch_type == "pipeline_health"

    def test_anchor_matches_selected(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "pipeline_health")
        assert result.watches[0].anchor_node_id == "final-1"

    def test_generates_monitors(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "pipeline_health")
        assert result.total_monitors > 0
        assert result.total_monitors <= 12  # cap


# ---------------------------------------------------------------------------
# Data Drift preset
# ---------------------------------------------------------------------------

class TestDataDriftPreset:
    def test_creates_one_watch(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "data_drift")
        assert len(result.watches) == 1
        assert result.watches[0].watch_type == "data_drift"

    def test_monitors_are_drift_focused(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "data_drift")
        monitor_keys = {r.monitor_key for r in result.watches[0].scope_result.recommendations}
        # Should contain quality-focused monitors
        assert "SCHEMA_CHANGE" in monitor_keys or "VOLUME" in monitor_keys or "NULL_RATE" in monitor_keys
        # Should have at least some drift monitors
        assert len(monitor_keys) > 0


# ---------------------------------------------------------------------------
# Ingestion Watch preset
# ---------------------------------------------------------------------------

class TestIngestionWatchPreset:
    def test_discovers_upstream_connectors(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "ingestion_watch")
        # Should find the upstream connector and create a source_guard watch
        if result.watches:
            assert result.watches[0].watch_type == "source_guard"
        else:
            # If no watches, should have a warning
            assert len(result.warnings) > 0

    def test_zero_connectors_produces_warning(self):
        """Graph with no connectors should produce a warning."""
        graph = LineageGraph()
        table = _make_node("t-1", "table", "project.table", PlatformDomain.WAREHOUSE)
        graph.add_node(table)
        result = preview_preset(graph, "t-1", "ingestion_watch")
        assert len(result.watches) == 0
        assert any("connector" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# BI Reliability preset
# ---------------------------------------------------------------------------

class TestBIReliabilityPreset:
    def test_creates_two_watches(self):
        graph = _build_bi_pipeline_graph()
        result = preview_preset(graph, "dash-1", "bi_reliability")
        assert len(result.watches) == 2

    def test_watch_types(self):
        graph = _build_bi_pipeline_graph()
        result = preview_preset(graph, "dash-1", "bi_reliability")
        watch_types = {w.watch_type for w in result.watches}
        assert "dashboard_shield" in watch_types
        assert "pipeline_health" in watch_types

    def test_dedup_across_watches(self):
        graph = _build_bi_pipeline_graph()
        result = preview_preset(graph, "dash-1", "bi_reliability")
        # Collect all (monitor_key, target_fqn) pairs across all watches
        all_pairs = []
        for w in result.watches:
            for rec in w.scope_result.recommendations:
                all_pairs.append((rec.monitor_key, rec.target_fqn))
        # No duplicates
        assert len(all_pairs) == len(set(all_pairs))


# ---------------------------------------------------------------------------
# Full Coverage preset
# ---------------------------------------------------------------------------

class TestFullCoveragePreset:
    def test_creates_multiple_watches(self):
        graph = _build_wide_graph()
        result = preview_preset(graph, "dash-0", "full_coverage")
        assert len(result.watches) >= 1
        assert len(result.watches) <= 4

    def test_respects_global_cap(self):
        graph = _build_wide_graph()
        result = preview_preset(graph, "dash-0", "full_coverage")
        assert result.total_monitors <= 40

    def test_domain_grouping(self):
        graph = _build_wide_graph()
        result = preview_preset(graph, "dash-0", "full_coverage")
        watch_types = {w.watch_type for w in result.watches}
        # Should have at least dashboard_shield since anchor is a dashboard
        # and some other types based on upstream
        assert len(watch_types) >= 1

    def test_no_duplicate_monitors(self):
        graph = _build_wide_graph()
        result = preview_preset(graph, "dash-0", "full_coverage")
        all_pairs = []
        for w in result.watches:
            for rec in w.scope_result.recommendations:
                all_pairs.append((rec.monitor_key, rec.target_fqn))
        assert len(all_pairs) == len(set(all_pairs))


# ---------------------------------------------------------------------------
# Smart Builder
# ---------------------------------------------------------------------------

class TestSmartBuilder:
    def test_auto_creates_watches_from_graph_shape(self):
        graph = _build_wide_graph()
        result = smart_build_preview(graph, "dash-0")
        assert result.preset_key == "smart_build"
        assert len(result.watches) >= 1
        assert result.total_monitors > 0

    def test_dedup_works(self):
        graph = _build_wide_graph()
        result = smart_build_preview(graph, "dash-0")
        all_pairs = []
        for w in result.watches:
            for rec in w.scope_result.recommendations:
                all_pairs.append((rec.monitor_key, rec.target_fqn))
        assert len(all_pairs) == len(set(all_pairs))

    def test_respects_global_cap(self):
        graph = _build_wide_graph()
        result = smart_build_preview(graph, "dash-0")
        assert result.total_monitors <= 40

    def test_existing_monitors_marked(self):
        graph = _build_warehouse_pipeline_graph()
        existing = {"FRESHNESS:project.analytics.dim_events"}
        result = smart_build_preview(graph, "final-1", existing_monitor_fqns=existing)
        for w in result.watches:
            for rec in w.scope_result.recommendations:
                if rec.monitor_key == "FRESHNESS" and rec.target_fqn == "project.analytics.dim_events":
                    assert rec.already_monitored is True


# ---------------------------------------------------------------------------
# Preset preview result shape
# ---------------------------------------------------------------------------

class TestPresetPreviewShape:
    def test_to_dict_shape(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "pipeline_health")
        d = result.to_dict()
        assert "preset_key" in d
        assert "watches" in d
        assert "total_monitors" in d
        assert "total_nodes" in d
        assert "deduplicated_count" in d
        assert "warnings" in d

    def test_watch_preview_to_dict_shape(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "pipeline_health")
        assert len(result.watches) > 0
        wd = result.watches[0].to_dict()
        assert "watch_type" in wd
        assert "anchor_node_id" in wd
        assert "anchor_name" in wd
        assert "scope_result" in wd
        assert "monitor_count" in wd
        assert "coverage_pct" in wd

    def test_unknown_preset_returns_warning(self):
        graph = _build_warehouse_pipeline_graph()
        result = preview_preset(graph, "final-1", "nonexistent_preset")
        assert len(result.warnings) > 0
        assert len(result.watches) == 0
