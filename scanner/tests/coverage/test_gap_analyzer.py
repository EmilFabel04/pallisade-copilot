"""
Tests for the Gap Analyzer and Monitor Recommender.
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
)
from scanner.coverage.scorer import CoverageScorer
from scanner.coverage.gap_analyzer import GapAnalyzer
from scanner.coverage.models import (
    CoverageCategory,
    CoverageDimension,
    GapSeverity,
    MonitorType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_graph() -> LineageGraph:
    g = LineageGraph()

    # Critical table with many consumers.
    critical = LineageNode(
        id="critical_table",
        name="prod.core.transactions",
        fqn="prod.core.transactions",
        node_type=NodeType.TABLE,
        database="prod",
        schema="core",
        platform="snowflake",
        platform_domain=PlatformDomain.WAREHOUSE,
        asset_kind=AssetKind.TABLE,
        criticality="critical",
    )
    g.add_node(critical)

    # 5 downstream consumers.
    for i in range(5):
        downstream = LineageNode(
            id=f"consumer_{i}",
            name=f"analytics.reports.report_{i}",
            fqn=f"analytics.reports.report_{i}",
            node_type=NodeType.VIEW,
            database="analytics",
            schema="reports",
            platform="snowflake",
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.VIEW,
        )
        g.add_node(downstream)
        g.add_edge(LineageEdge(
            id=f"e_{i}", source_id="critical_table",
            target_id=f"consumer_{i}",
            edge_type=EdgeType.DEPENDS_ON,
            lineage_level=LineageLevel.TABLE,
            evidence=[Evidence(adapter_id="snowflake", source_ref="query_log")],
        ))

    # Low-priority table with no consumers.
    leaf = LineageNode(
        id="staging_temp",
        name="staging.tmp.temp_load",
        fqn="staging.tmp.temp_load",
        node_type=NodeType.TABLE,
        database="staging",
        schema="tmp",
        platform="postgres",
        platform_domain=PlatformDomain.WAREHOUSE,
        asset_kind=AssetKind.TABLE,
        criticality="low",
    )
    g.add_node(leaf)

    return g


@pytest.fixture
def graph():
    return _make_graph()


@pytest.fixture
def report_with_gaps(graph):
    scorer = CoverageScorer(graph=graph)
    report = scorer.score()
    analyzer = GapAnalyzer(graph)
    return analyzer.analyze(report)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGapAnalysis:
    def test_gaps_are_generated(self, report_with_gaps):
        assert len(report_with_gaps.gaps) > 0

    def test_gaps_sorted_by_severity(self, report_with_gaps):
        severity_order = {
            GapSeverity.CRITICAL: 0,
            GapSeverity.HIGH: 1,
            GapSeverity.MEDIUM: 2,
            GapSeverity.LOW: 3,
            GapSeverity.INFO: 4,
        }
        for i in range(len(report_with_gaps.gaps) - 1):
            current = severity_order[report_with_gaps.gaps[i].severity]
            next_gap = severity_order[report_with_gaps.gaps[i + 1].severity]
            # Allow same severity (sort is stable).
            assert current <= next_gap

    def test_critical_node_has_higher_severity_gaps(self, report_with_gaps):
        critical_gaps = [
            g for g in report_with_gaps.gaps
            if g.node_id == "critical_table"
        ]
        # At least some gaps for the critical table should be high or critical.
        high_or_critical = [
            g for g in critical_gaps
            if g.severity in (GapSeverity.CRITICAL, GapSeverity.HIGH)
        ]
        assert len(high_or_critical) > 0

    def test_low_priority_node_has_lower_gaps(self, report_with_gaps):
        staging_gaps = [
            g for g in report_with_gaps.gaps
            if g.node_id == "staging_temp"
        ]
        # Staging table should have lower severity than critical table.
        critical_count = sum(
            1 for g in staging_gaps
            if g.severity == GapSeverity.CRITICAL
        )
        # Low-criticality + no downstream = should have few/no critical gaps.
        assert critical_count == 0

    def test_gap_has_required_fields(self, report_with_gaps):
        for gap in report_with_gaps.gaps:
            assert gap.node_id
            assert gap.title
            assert gap.description
            assert gap.recommendation
            assert gap.severity in GapSeverity

    def test_summary_counts_match(self, report_with_gaps):
        report = report_with_gaps
        critical = sum(1 for g in report.gaps if g.severity == GapSeverity.CRITICAL)
        assert report.critical_gaps == critical


class TestMonitorRecommendations:
    def test_recommendations_generated(self, report_with_gaps):
        assert len(report_with_gaps.recommendations) > 0

    def test_recommendations_have_sql_templates(self, report_with_gaps):
        # At least some recommendations should have SQL templates.
        with_sql = [
            r for r in report_with_gaps.recommendations
            if r.sql_template is not None
        ]
        assert len(with_sql) > 0

    def test_recommendations_deduplicated(self, report_with_gaps):
        # No duplicate (node_id, monitor_type) pairs.
        seen = set()
        for rec in report_with_gaps.recommendations:
            key = (rec.target_node_id, rec.monitor_type)
            assert key not in seen, f"Duplicate recommendation: {key}"
            seen.add(key)

    def test_recommendation_closes_gaps(self, report_with_gaps):
        for rec in report_with_gaps.recommendations:
            assert len(rec.closes_gaps) > 0

    def test_recommendation_has_config(self, report_with_gaps):
        for rec in report_with_gaps.recommendations:
            assert isinstance(rec.config, dict)

    def test_recommendation_has_compatible_integrations(self, report_with_gaps):
        for rec in report_with_gaps.recommendations:
            assert len(rec.compatible_integrations) > 0

    def test_freshness_recommendation_for_critical(self, report_with_gaps):
        critical_recs = [
            r for r in report_with_gaps.recommendations
            if r.target_node_id == "critical_table"
            and r.monitor_type == MonitorType.FRESHNESS
        ]
        assert len(critical_recs) > 0

    def test_recommendation_serialization(self, report_with_gaps):
        for rec in report_with_gaps.recommendations:
            d = rec.to_dict()
            assert "monitor_type" in d
            assert "sql_template" in d
            assert "closes_gaps" in d
