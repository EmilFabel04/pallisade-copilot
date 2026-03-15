"""Tests for monitor families — canonical recommendation layer."""

from __future__ import annotations

import pytest

from scanner.lineage.graph import (
    AssetKind,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.monitors.families import (
    MONITOR_FAMILIES,
    check_node_eligibility,
    expand_full_coverage,
    get_all_families,
    get_family_eligibility,
    get_family_watch_type,
    resolve_families,
)


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Tests: eligibility
# ---------------------------------------------------------------------------

class TestFamilyEligibility:
    def test_pipeline_health_eligible_for_warehouse_nodes(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
        ]
        results = get_family_eligibility(nodes)
        ph = next(r for r in results if r.family.key == "pipeline_health")
        assert ph.eligible is True
        assert ph.matching_node_count >= 1

    def test_bi_reliability_not_eligible_without_bi_nodes(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
            _make_node("c1", "connector", "fivetran.c1", PlatformDomain.INGESTION,
                       NodeType.CONNECTOR, AssetKind.CONNECTOR),
        ]
        results = get_family_eligibility(nodes)
        bi = next(r for r in results if r.family.key == "bi_reliability")
        assert bi.eligible is False
        assert bi.matching_node_count == 0
        assert "bi" in bi.reason.lower()

    def test_data_drift_only_warehouse_transform(self):
        nodes = [
            _make_node("c1", "connector", "fivetran.c1", PlatformDomain.INGESTION,
                       NodeType.CONNECTOR, AssetKind.CONNECTOR),
        ]
        results = get_family_eligibility(nodes)
        dd = next(r for r in results if r.family.key == "data_drift")
        assert dd.eligible is False

        # Add a warehouse node — should be eligible now
        nodes.append(
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
        )
        results = get_family_eligibility(nodes)
        dd = next(r for r in results if r.family.key == "data_drift")
        assert dd.eligible is True

    def test_ingestion_reliability_needs_ingestion_nodes(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
        ]
        results = get_family_eligibility(nodes)
        ir = next(r for r in results if r.family.key == "ingestion_reliability")
        assert ir.eligible is False

    def test_model_quality_needs_transform_nodes(self):
        nodes = [
            _make_node("m1", "model1", "dbt.model1", PlatformDomain.TRANSFORM,
                       NodeType.TABLE, AssetKind.MODEL, platform="dbt"),
        ]
        results = get_family_eligibility(nodes)
        mq = next(r for r in results if r.family.key == "model_quality")
        assert mq.eligible is True

    def test_empty_scope_all_ineligible(self):
        results = get_family_eligibility([])
        for r in results:
            assert r.eligible is False


# ---------------------------------------------------------------------------
# Tests: full_coverage expansion
# ---------------------------------------------------------------------------

class TestFullCoverageExpansion:
    def test_full_coverage_expands_to_all_applicable(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
            _make_node("c1", "connector", "fivetran.c1", PlatformDomain.INGESTION,
                       NodeType.CONNECTOR, AssetKind.CONNECTOR),
            _make_node("d1", "dashboard", "looker.dash1", PlatformDomain.BI,
                       NodeType.DASHBOARD, AssetKind.DASHBOARD, platform="looker"),
        ]
        expanded = expand_full_coverage(nodes)
        assert "pipeline_health" in expanded
        assert "ingestion_reliability" in expanded
        assert "bi_reliability" in expanded
        assert "full_coverage" not in expanded  # Meta shouldn't appear

    def test_full_coverage_excludes_inapplicable(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
        ]
        expanded = expand_full_coverage(nodes)
        assert "pipeline_health" in expanded
        assert "bi_reliability" not in expanded
        assert "ingestion_reliability" not in expanded


# ---------------------------------------------------------------------------
# Tests: resolve_families
# ---------------------------------------------------------------------------

class TestResolveFamilies:
    def test_multiple_families_composable(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
            _make_node("c1", "connector", "fivetran.c1", PlatformDomain.INGESTION,
                       NodeType.CONNECTOR, AssetKind.CONNECTOR),
        ]
        result = resolve_families(
            ["pipeline_health", "ingestion_reliability"], nodes
        )
        assert "pipeline_health" in result
        assert "ingestion_reliability" in result
        assert len(result) == 2

    def test_resolve_full_coverage_expands(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
            _make_node("c1", "connector", "fivetran.c1", PlatformDomain.INGESTION,
                       NodeType.CONNECTOR, AssetKind.CONNECTOR),
        ]
        result = resolve_families(["full_coverage"], nodes)
        assert "pipeline_health" in result
        assert "ingestion_reliability" in result
        assert "full_coverage" not in result

    def test_dedup_when_family_and_full_coverage(self):
        nodes = [
            _make_node("t1", "table1", "db.schema.t1", PlatformDomain.WAREHOUSE),
        ]
        result = resolve_families(["pipeline_health", "full_coverage"], nodes)
        # pipeline_health should appear only once
        assert result.count("pipeline_health") == 1

    def test_unknown_family_ignored(self):
        result = resolve_families(["nonexistent_family"], [])
        assert result == []


# ---------------------------------------------------------------------------
# Tests: node eligibility + watch type mapping
# ---------------------------------------------------------------------------

class TestNodeEligibility:
    def test_warehouse_node_eligible_for_pipeline_health(self):
        node = _make_node("t1", "table1", "db.t1", PlatformDomain.WAREHOUSE)
        assert check_node_eligibility(node, "pipeline_health") is True

    def test_warehouse_node_not_eligible_for_bi_reliability(self):
        node = _make_node("t1", "table1", "db.t1", PlatformDomain.WAREHOUSE)
        assert check_node_eligibility(node, "bi_reliability") is False

    def test_family_maps_to_watch_type(self):
        assert get_family_watch_type("pipeline_health") == "pipeline_health"
        assert get_family_watch_type("bi_reliability") == "dashboard_shield"
        assert get_family_watch_type("ingestion_reliability") == "source_guard"
        assert get_family_watch_type("model_quality") == "model_quality"
        assert get_family_watch_type("data_drift") == "data_drift"
        assert get_family_watch_type("nonexistent") is None


class TestGetAllFamilies:
    def test_returns_all_families(self):
        result = get_all_families()
        assert len(result) == len(MONITOR_FAMILIES)
        keys = {f["key"] for f in result}
        assert "pipeline_health" in keys
        assert "full_coverage" in keys

    def test_with_scope_nodes_includes_eligibility(self):
        nodes = [
            _make_node("t1", "table1", "db.t1", PlatformDomain.WAREHOUSE),
        ]
        result = get_all_families(scope_nodes=nodes)
        # Should have eligible field
        for f in result:
            assert "eligible" in f
