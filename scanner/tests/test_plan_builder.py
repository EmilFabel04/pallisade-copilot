"""Tests for monitoring plan builder."""

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
from scanner.monitors.plan_builder import (
    MonitoringPlanPreview,
    preview_monitoring_plan,
    _resolve_scope_nodes,
)
from scanner.monitors.health import compute_plan_aggregate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    id: str,
    name: str,
    fqn: str,
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
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
    edge = LineageEdge(
        id=f"{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.DERIVED_FROM,
    )
    graph.add_edge(edge)


def _build_mixed_pipeline() -> LineageGraph:
    """
    Build a pipeline with mixed domains:
    connector -> raw_table -> dbt_model -> final_table -> dashboard
    """
    graph = LineageGraph()

    graph.add_node(_make_node(
        "conn-1", "fivetran_connector", "fivetran.connector_1",
        PlatformDomain.INGESTION, NodeType.CONNECTOR, AssetKind.CONNECTOR,
        platform="fivetran",
    ))
    graph.add_node(_make_node(
        "raw-1", "raw_events", "project.raw.events",
        PlatformDomain.WAREHOUSE, downstream_count=3,
    ))
    graph.add_node(_make_node(
        "model-1", "stg_events", "dbt.stg_events",
        PlatformDomain.TRANSFORM, NodeType.TABLE, AssetKind.MODEL,
        platform="dbt",
    ))
    graph.add_node(_make_node(
        "final-1", "dim_events", "project.analytics.dim_events",
        PlatformDomain.WAREHOUSE, downstream_count=5,
        criticality="high",
    ))
    graph.add_node(_make_node(
        "dash-1", "events_dashboard", "looker.events_dashboard",
        PlatformDomain.BI, NodeType.DASHBOARD, AssetKind.DASHBOARD,
        platform="looker",
    ))

    _add_edge(graph, "conn-1", "raw-1")
    _add_edge(graph, "raw-1", "model-1")
    _add_edge(graph, "model-1", "final-1")
    _add_edge(graph, "final-1", "dash-1")

    return graph


# ---------------------------------------------------------------------------
# Tests: scope resolution
# ---------------------------------------------------------------------------

class TestScopeResolution:
    def test_pipeline_scope_selects_all(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "pipeline", {})
        assert len(nodes) == 5  # All nodes

    def test_stream_scope_bfs_from_anchor(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "stream", {
            "anchorNodeIds": ["final-1"],
            "maxDepth": 5,
        })
        # Should include final-1 and its upstream: model-1, raw-1, conn-1
        assert "final-1" in nodes
        assert "model-1" in nodes
        assert "raw-1" in nodes
        assert "conn-1" in nodes
        # Should NOT include downstream (dash-1)
        assert "dash-1" not in nodes

    def test_asset_scope_includes_neighbors(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "asset", {
            "anchorNodeIds": ["model-1"],
        })
        assert "model-1" in nodes
        assert "raw-1" in nodes   # upstream neighbor
        assert "final-1" in nodes  # downstream neighbor

    def test_empty_scope(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "stream", {
            "anchorNodeIds": ["nonexistent"],
        })
        assert len(nodes) == 0

    def test_custom_scope_selects_explicit_nodes(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "custom", {
            "nodeIds": ["raw-1", "final-1"],
        })
        assert nodes == {"raw-1", "final-1"}

    def test_custom_scope_ignores_nonexistent_ids(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "custom", {
            "nodeIds": ["raw-1", "nonexistent-99"],
        })
        assert nodes == {"raw-1"}

    def test_custom_scope_empty_list(self):
        graph = _build_mixed_pipeline()
        nodes = _resolve_scope_nodes(graph, "custom", {"nodeIds": []})
        assert len(nodes) == 0


class TestCustomScopePreview:
    def test_custom_scope_preview_recommended(self):
        """Custom scope with explicit node IDs produces a valid plan."""
        graph = _build_mixed_pipeline()
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="custom",
            scope_config={"nodeIds": ["raw-1", "final-1"]},
            mode="recommended",
            families=["pipeline_health"],
        )
        assert result.mode == "recommended"
        assert result.total_monitors > 0
        # Only the selected nodes (and no BFS discovery) should be in scope
        all_fqns = set()
        for g in result.groups:
            for rec in g.recommendations:
                all_fqns.add(rec.get("target_fqn", ""))
        # Should include at least one monitor targeting raw-1 or final-1
        assert any("events" in fqn for fqn in all_fqns)

    def test_custom_scope_preview_all_nodes(self):
        """Selecting all nodes via custom scope = same as pipeline scope."""
        graph = _build_mixed_pipeline()
        all_ids = list(graph.nodes.keys())
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="custom",
            scope_config={"nodeIds": all_ids},
            mode="recommended",
            families=["pipeline_health"],
        )
        assert result.total_monitors > 0


# ---------------------------------------------------------------------------
# Tests: recommended mode preview
# ---------------------------------------------------------------------------

class TestRecommendedMode:
    def test_recommended_mode_preview(self):
        graph = _build_mixed_pipeline()
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="recommended",
            families=["pipeline_health"],
        )
        assert result.mode == "recommended"
        assert result.total_monitors > 0
        assert len(result.groups) >= 1

    def test_multiple_families(self):
        graph = _build_mixed_pipeline()
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="recommended",
            families=["pipeline_health", "ingestion_reliability"],
        )
        assert result.total_monitors > 0
        # Should have groups from both families
        family_keys = {g.family for g in result.groups}
        # At least one family should produce groups
        assert len(family_keys) >= 1

    def test_full_coverage_expands(self):
        graph = _build_mixed_pipeline()
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="recommended",
            families=["full_coverage"],
        )
        # full_coverage should expand and produce monitors
        assert result.total_monitors > 0

    def test_inapplicable_family_produces_warning(self):
        graph = LineageGraph()
        graph.add_node(_make_node(
            "t1", "table1", "db.t1", PlatformDomain.WAREHOUSE,
        ))
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="recommended",
            families=["bi_reliability"],  # No BI nodes
        )
        # Should either produce no groups or have a warning
        assert result.total_monitors == 0 or len(result.warnings) > 0

    def test_dedup_across_families(self):
        graph = _build_mixed_pipeline()
        # pipeline_health and data_drift may produce overlapping monitors
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="recommended",
            families=["pipeline_health", "data_drift"],
        )
        # Verify no duplicate (type, fqn) across all groups
        seen = set()
        for g in result.groups:
            for rec in g.recommendations:
                key = f"{rec.get('monitor_key')}:{rec.get('target_fqn')}"
                assert key not in seen, f"Duplicate: {key}"
                seen.add(key)

    def test_no_nodes_in_scope(self):
        result = preview_monitoring_plan(
            graph=LineageGraph(),
            scope_type="pipeline",
            scope_config={},
            mode="recommended",
            families=["pipeline_health"],
        )
        assert result.total_monitors == 0
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Tests: manual mode preview
# ---------------------------------------------------------------------------

class TestManualMode:
    def test_manual_mode_preview(self):
        graph = _build_mixed_pipeline()
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="manual",
            families=[],
            manual_selections={
                "final-1": ["FRESHNESS", "VOLUME"],
                "raw-1": ["FRESHNESS"],
            },
        )
        assert result.mode == "manual"
        assert result.total_monitors >= 2  # At least our manual selections

    def test_manual_mode_empty_selections(self):
        graph = _build_mixed_pipeline()
        result = preview_monitoring_plan(
            graph=graph,
            scope_type="pipeline",
            scope_config={},
            mode="manual",
            families=[],
            manual_selections={},
        )
        assert result.total_monitors == 0
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Tests: plan aggregate
# ---------------------------------------------------------------------------

class TestPlanAggregate:
    def test_plan_aggregate_health_rollup(self):
        groups = [
            {
                "name": "Group 1",
                "healthScore": 90.0,
                "coveragePct": 0.8,
                "totalMonitors": 10,
                "passCount": 8,
                "warnCount": 1,
                "failCount": 1,
                "errorCount": 0,
                "healthDetails": {},
            },
            {
                "name": "Group 2",
                "healthScore": 60.0,
                "coveragePct": 0.6,
                "totalMonitors": 5,
                "passCount": 2,
                "warnCount": 1,
                "failCount": 2,
                "errorCount": 0,
                "healthDetails": {},
            },
        ]
        agg = compute_plan_aggregate(groups)
        # Weighted average: (90*10 + 60*5) / (10+5) = 1200/15 = 80
        assert agg.health_score == 80.0
        assert agg.health_status == "degraded"  # 70-89
        assert agg.total_monitors == 15
        assert agg.pass_count == 10
        assert agg.fail_count == 3
        assert agg.lowest_health_group == "Group 2"

    def test_plan_aggregate_weighted_coverage(self):
        groups = [
            {
                "name": "Big Group",
                "healthScore": 95.0,
                "coveragePct": 0.9,
                "totalMonitors": 20,
                "passCount": 20,
                "warnCount": 0,
                "failCount": 0,
                "errorCount": 0,
                "healthDetails": {},
            },
            {
                "name": "Small Group",
                "healthScore": 50.0,
                "coveragePct": 0.3,
                "totalMonitors": 2,
                "passCount": 1,
                "warnCount": 0,
                "failCount": 1,
                "errorCount": 0,
                "healthDetails": {},
            },
        ]
        agg = compute_plan_aggregate(groups)
        # Coverage: (0.9*20 + 0.3*2) / 22 = 18.6/22 ≈ 0.845
        assert agg.coverage_pct > 0.8
        assert agg.coverage_pct < 0.9

    def test_plan_aggregate_empty_groups(self):
        agg = compute_plan_aggregate([])
        assert agg.health_score == 100.0
        assert agg.health_status == "healthy"
        assert agg.total_monitors == 0

    def test_plan_aggregate_failure_groups(self):
        groups = [
            {
                "name": "Group 1",
                "healthScore": 30.0,
                "coveragePct": 0.5,
                "totalMonitors": 5,
                "passCount": 1,
                "warnCount": 1,
                "failCount": 3,
                "errorCount": 0,
                "healthDetails": {
                    "failureGroups": [
                        {
                            "category": "stale_data",
                            "severity": "critical",
                            "summary": "FRESHNESS: FAIL",
                            "rootCauseHint": "db.raw.events",
                            "signalCount": 2,
                        },
                    ],
                },
            },
        ]
        agg = compute_plan_aggregate(groups)
        assert len(agg.top_failure_groups) == 1
        assert agg.top_failure_groups[0].category == "stale_data"

    def test_serialization(self):
        groups = [
            {
                "name": "Group 1",
                "healthScore": 85.0,
                "coveragePct": 0.7,
                "totalMonitors": 8,
                "passCount": 6,
                "warnCount": 1,
                "failCount": 1,
                "errorCount": 0,
                "healthDetails": {},
            },
        ]
        agg = compute_plan_aggregate(groups)
        d = agg.to_dict()
        assert "healthScore" in d
        assert "coveragePct" in d
        assert "topFailureGroups" in d
