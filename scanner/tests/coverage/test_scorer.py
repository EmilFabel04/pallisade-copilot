"""
Tests for the Coverage Scorer.
"""

import pytest

from scanner.lineage.graph import (
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    NodeType,
    EdgeType,
    PlatformDomain,
    AssetKind,
    Evidence,
    ColumnMapping,
)
from scanner.coverage.scorer import CoverageScorer
from scanner.coverage.models import CoverageCategory, CoverageDimension


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_graph() -> LineageGraph:
    """Build a small but realistic lineage graph for testing."""
    g = LineageGraph()

    # Source table — raw data, no owner, no description.
    src = LineageNode(
        id="src_orders",
        name="raw.public.orders",
        fqn="raw.public.orders",
        node_type=NodeType.SOURCE,
        database="raw",
        schema="public",
        platform="postgres",
        platform_domain=PlatformDomain.WAREHOUSE,
        asset_kind=AssetKind.TABLE,
    )
    g.add_node(src)

    # Staging model — has owner and description.
    stg = LineageNode(
        id="stg_orders",
        name="analytics.staging.stg_orders",
        fqn="analytics.staging.stg_orders",
        node_type=NodeType.MODEL,
        database="analytics",
        schema="staging",
        platform="dbt",
        platform_domain=PlatformDomain.TRANSFORM,
        asset_kind=AssetKind.MODEL,
        owner="data-team",
        description="Staged orders from raw source.",
        tags=["core", "orders"],
        columns=[
            {"name": "order_id", "type": "integer"},
            {"name": "customer_id", "type": "integer"},
            {"name": "total", "type": "numeric"},
        ],
    )
    g.add_node(stg)

    # Mart table — critical, many consumers.
    mart = LineageNode(
        id="mart_orders",
        name="analytics.marts.orders",
        fqn="analytics.marts.orders",
        node_type=NodeType.TABLE,
        database="analytics",
        schema="marts",
        platform="snowflake",
        platform_domain=PlatformDomain.WAREHOUSE,
        asset_kind=AssetKind.TABLE,
        criticality="critical",
        owner="analytics-team",
        description="Final orders mart consumed by BI.",
        row_count=500000,
        expected_freshness_hours=24,
        columns=[
            {"name": "order_id", "type": "integer"},
            {"name": "total", "type": "numeric"},
        ],
    )
    g.add_node(mart)

    # Dashboard — leaf node.
    dash = LineageNode(
        id="dash_orders",
        name="Orders Dashboard",
        fqn="looker.orders_dashboard",
        node_type=NodeType.DASHBOARD,
        platform="looker",
        platform_domain=PlatformDomain.BI,
        asset_kind=AssetKind.DASHBOARD,
    )
    g.add_node(dash)

    # Edges: src -> stg -> mart -> dash.
    g.add_edge(LineageEdge(
        id="e1", source_id="src_orders", target_id="stg_orders",
        edge_type=EdgeType.DEPENDS_ON, lineage_level=LineageLevel.TABLE,
        evidence=[Evidence(adapter_id="dbt", source_ref="manifest")],
    ))
    g.add_edge(LineageEdge(
        id="e2", source_id="stg_orders", target_id="mart_orders",
        edge_type=EdgeType.DEPENDS_ON, lineage_level=LineageLevel.TABLE,
        evidence=[Evidence(adapter_id="dbt", source_ref="manifest")],
    ))
    # Column-level edge.
    g.add_edge(LineageEdge(
        id="e2c", source_id="stg_orders", target_id="mart_orders",
        edge_type=EdgeType.DERIVED_FROM, lineage_level=LineageLevel.COLUMN,
        column_mappings=[
            ColumnMapping(from_column="order_id", to_column="order_id"),
            ColumnMapping(from_column="total", to_column="total"),
        ],
        evidence=[Evidence(adapter_id="sql_parser", source_ref="sql")],
    ))
    g.add_edge(LineageEdge(
        id="e3", source_id="mart_orders", target_id="dash_orders",
        edge_type=EdgeType.READS_FROM, lineage_level=LineageLevel.TABLE,
        evidence=[Evidence(adapter_id="looker", source_ref="explore")],
    ))

    return g


@pytest.fixture
def graph():
    return _make_graph()


@pytest.fixture
def scorer_no_monitors(graph):
    """Scorer with no external monitors or contracts."""
    return CoverageScorer(graph=graph)


@pytest.fixture
def scorer_with_monitors(graph):
    """Scorer with some monitors and contracts configured."""
    return CoverageScorer(
        graph=graph,
        monitors={
            "analytics.marts.orders": ["freshness", "volume", "schema_change"],
            "analytics.staging.stg_orders": ["null_rate"],
        },
        contracts={
            "analytics.marts.orders": {
                "freshnessEnabled": True,
                "schemaEnabled": True,
                "maxNullRate": 0.01,
                "maxDuplicateRate": 0.0,
                "owner": "analytics-team",
                "description": "Core orders mart.",
            },
        },
        observability_checks={
            "analytics.marts.orders": ["freshness_anomalies", "volume_anomalies"],
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCoverageScorerBasics:
    def test_scores_all_nodes(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        assert report.total_nodes == 4

    def test_overall_score_between_0_and_1(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        assert 0.0 <= report.overall_score <= 1.0

    def test_category_scores_present(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        assert len(report.category_scores) > 0

    def test_node_coverages_have_scores(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        for nc in report.node_coverages:
            assert 0.0 <= nc.overall_score <= 1.0
            assert nc.applicable_dimensions > 0


class TestCoverageWithMonitors:
    def test_monitors_increase_coverage(self, scorer_no_monitors, scorer_with_monitors):
        report_bare = scorer_no_monitors.score()
        report_mon = scorer_with_monitors.score()
        assert report_mon.overall_score > report_bare.overall_score

    def test_mart_has_freshness_coverage(self, scorer_with_monitors):
        report = scorer_with_monitors.score()
        mart = next(
            nc for nc in report.node_coverages if nc.node_id == "mart_orders"
        )
        assert CoverageDimension.FRESHNESS_MONITOR in mart.covered_dimensions

    def test_mart_has_schema_contract(self, scorer_with_monitors):
        report = scorer_with_monitors.score()
        mart = next(
            nc for nc in report.node_coverages if nc.node_id == "mart_orders"
        )
        assert CoverageDimension.SCHEMA_CONTRACT in mart.covered_dimensions

    def test_source_has_no_monitors(self, scorer_with_monitors):
        report = scorer_with_monitors.score()
        src = next(
            nc for nc in report.node_coverages if nc.node_id == "src_orders"
        )
        # Source should have no freshness monitor.
        assert CoverageDimension.FRESHNESS_MONITOR in src.uncovered_dimensions


class TestCoverageDimensions:
    def test_lineage_coverage_upstream(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        # stg_orders has upstream (src_orders), so UPSTREAM_LINKED covered.
        stg = next(
            nc for nc in report.node_coverages if nc.node_id == "stg_orders"
        )
        assert CoverageDimension.UPSTREAM_LINKED in stg.covered_dimensions

    def test_lineage_coverage_downstream(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        # mart_orders has downstream (dash_orders).
        mart = next(
            nc for nc in report.node_coverages if nc.node_id == "mart_orders"
        )
        assert CoverageDimension.DOWNSTREAM_LINKED in mart.covered_dimensions

    def test_column_lineage_on_mart(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        mart = next(
            nc for nc in report.node_coverages if nc.node_id == "mart_orders"
        )
        assert CoverageDimension.COLUMN_LINEAGE_MAPPED in mart.covered_dimensions

    def test_owner_on_model(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        stg = next(
            nc for nc in report.node_coverages if nc.node_id == "stg_orders"
        )
        assert CoverageDimension.OWNER_ASSIGNED in stg.covered_dimensions

    def test_description_on_model(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        stg = next(
            nc for nc in report.node_coverages if nc.node_id == "stg_orders"
        )
        assert CoverageDimension.DESCRIPTION_EXISTS in stg.covered_dimensions

    def test_no_owner_on_source(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        src = next(
            nc for nc in report.node_coverages if nc.node_id == "src_orders"
        )
        assert CoverageDimension.OWNER_ASSIGNED in src.uncovered_dimensions

    def test_freshness_sla_via_expected_hours(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        mart = next(
            nc for nc in report.node_coverages if nc.node_id == "mart_orders"
        )
        # mart has expected_freshness_hours=24 set directly on the node.
        assert CoverageDimension.FRESHNESS_SLA in mart.covered_dimensions


class TestCoverageSerialization:
    def test_report_to_dict(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        d = report.to_dict()
        assert "overall_score" in d
        assert "category_scores" in d
        assert "gaps_summary" in d

    def test_report_to_detailed_dict(self, scorer_with_monitors):
        report = scorer_with_monitors.score()
        d = report.to_detailed_dict()
        assert "node_coverages" in d
        assert len(d["node_coverages"]) == 4

    def test_node_coverage_to_dict(self, scorer_no_monitors):
        report = scorer_no_monitors.score()
        nc = report.node_coverages[0]
        d = nc.to_dict()
        assert "node_id" in d
        assert "overall_score" in d
        assert "category_scores" in d
