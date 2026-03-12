"""Tests for the node-aware monitor recommendation engine."""

import pytest
from ...lineage.graph import (
    LineageNode, NodeType, PlatformDomain, AssetKind, HealthStatus,
)
from ..recommender import (
    recommend_for_node, get_bundles,
    MonitorRecommendation, MonitorBundle,
    FRESHNESS, VOLUME, SCHEMA_CHANGE, NULL_RATE, UNIQUENESS, ANOMALY,
    SYNC_LAG, FAILED_SYNCS, CONNECTOR_SCHEMA_DRIFT,
    DAG_LAST_RUN, DAG_SCHEDULE_LAG,
    DBT_TEST_FAILURES, DBT_MODEL_FRESHNESS, DBT_SOURCE_FRESHNESS,
    BUNDLE_CAP,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_node(
    id: str = "node1",
    name: str = "orders",
    fqn: str = "project.dataset.orders",
    node_type: NodeType = NodeType.TABLE,
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    asset_kind: AssetKind = AssetKind.TABLE,
    platform: str = "bigquery",
    criticality: str = "medium",
    columns: list = None,
    integration_id: str = None,
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
        columns=columns or [],
        integration_id=integration_id,
    )


def _rec_keys(recs: list) -> set:
    """Extract set of monitor_key values from recommendations."""
    return {r.monitor_key for r in recs}


def _rec_keys_for_target(recs: list, target_fqn: str) -> set:
    """Extract monitor keys targeting a specific FQN."""
    return {r.monitor_key for r in recs if r.target_fqn == target_fqn}


# ---------------------------------------------------------------------------
# 1. Direct recommendation tests
# ---------------------------------------------------------------------------

class TestDirectRecommendations:

    def test_warehouse_table_gets_freshness_volume_schema(self):
        node = _make_node()
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert FRESHNESS in keys
        assert VOLUME in keys
        assert SCHEMA_CHANGE in keys

    def test_warehouse_view_gets_same_monitors(self):
        node = _make_node(asset_kind=AssetKind.VIEW, node_type=NodeType.VIEW)
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert FRESHNESS in keys
        assert VOLUME in keys

    def test_critical_table_gets_extra_monitors(self):
        node = _make_node(criticality="critical")
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert NULL_RATE in keys
        assert UNIQUENESS in keys
        assert ANOMALY in keys
        # Should also have the base monitors
        assert FRESHNESS in keys
        assert VOLUME in keys

    def test_high_criticality_gets_extra_monitors(self):
        node = _make_node(criticality="high")
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert NULL_RATE in keys
        assert UNIQUENESS in keys

    def test_medium_criticality_no_extra_monitors(self):
        node = _make_node(criticality="medium")
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert NULL_RATE not in keys
        assert UNIQUENESS not in keys
        assert ANOMALY not in keys

    def test_ingestion_connector_gets_sync_monitors(self):
        node = _make_node(
            node_type=NodeType.CONNECTOR,
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.CONNECTOR,
            platform="fivetran",
            fqn="fivetran.connector.orders_sync",
        )
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert SYNC_LAG in keys
        assert FAILED_SYNCS in keys

    def test_ingestion_connector_with_columns_gets_schema_drift(self):
        node = _make_node(
            node_type=NodeType.CONNECTOR,
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.CONNECTOR,
            platform="fivetran",
            columns=[{"name": "id", "type": "INT64"}, {"name": "status", "type": "STRING"}],
        )
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert CONNECTOR_SCHEMA_DRIFT in keys

    def test_orchestration_dag_gets_run_monitors(self):
        node = _make_node(
            node_type=NodeType.DAG,
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            platform="airflow",
            fqn="airflow.etl_daily",
        )
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert DAG_LAST_RUN in keys
        assert DAG_SCHEDULE_LAG in keys

    def test_dbt_model_gets_test_freshness(self):
        node = _make_node(
            node_type=NodeType.MODEL,
            platform_domain=PlatformDomain.TRANSFORM,
            asset_kind=AssetKind.MODEL,
            platform="dbt",
            fqn="dbt.staging.stg_orders",
        )
        recs = recommend_for_node(node)
        keys = _rec_keys(recs)
        assert DBT_TEST_FAILURES in keys
        assert DBT_MODEL_FRESHNESS in keys

    def test_bi_dashboard_no_direct_monitors(self):
        node = _make_node(
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
            platform="looker",
            fqn="looker.dashboard.sales_overview",
        )
        recs = recommend_for_node(node)
        # No direct monitors for BI nodes (only upstream)
        direct_recs = [r for r in recs if r.source == "direct"]
        assert len(direct_recs) == 0

    def test_all_direct_recs_have_source_direct(self):
        node = _make_node()
        recs = recommend_for_node(node)
        for r in recs:
            assert r.source == "direct"


# ---------------------------------------------------------------------------
# 2. Upstream recommendation tests
# ---------------------------------------------------------------------------

class TestUpstreamRecommendations:

    def test_upstream_warehouse_tables_get_freshness(self):
        target = _make_node(
            name="mart_orders",
            fqn="project.analytics.mart_orders",
        )
        upstream = [
            _make_node(id="raw1", name="raw_orders", fqn="project.raw.orders"),
            _make_node(id="raw2", name="raw_payments", fqn="project.raw.payments"),
        ]
        recs = recommend_for_node(target, upstream_nodes=upstream)
        upstream_recs = [r for r in recs if r.source == "upstream"]
        assert len(upstream_recs) >= 2
        # Each upstream table should get FRESHNESS
        for up in upstream:
            assert FRESHNESS in _rec_keys_for_target(upstream_recs, up.fqn)

    def test_upstream_mixed_domains(self):
        target = _make_node()
        upstream = [
            _make_node(id="wh1", name="source_table", fqn="proj.raw.source",
                       platform_domain=PlatformDomain.WAREHOUSE),
            _make_node(id="ing1", name="fivetran_conn", fqn="fivetran.conn.x",
                       node_type=NodeType.CONNECTOR,
                       platform_domain=PlatformDomain.INGESTION,
                       asset_kind=AssetKind.CONNECTOR, platform="fivetran"),
            _make_node(id="orch1", name="daily_dag", fqn="airflow.daily_dag",
                       node_type=NodeType.DAG,
                       platform_domain=PlatformDomain.ORCHESTRATION,
                       asset_kind=AssetKind.JOB, platform="airflow"),
        ]
        recs = recommend_for_node(target, upstream_nodes=upstream)
        upstream_recs = [r for r in recs if r.source == "upstream"]
        upstream_keys = _rec_keys(upstream_recs)
        assert FRESHNESS in upstream_keys
        assert SYNC_LAG in upstream_keys
        assert DAG_LAST_RUN in upstream_keys

    def test_upstream_empty_returns_empty(self):
        target = _make_node()
        recs = recommend_for_node(target, upstream_nodes=[])
        upstream_recs = [r for r in recs if r.source == "upstream"]
        assert len(upstream_recs) == 0

    def test_upstream_recs_reference_target_in_reason(self):
        target = _make_node(name="mart_orders")
        upstream = [
            _make_node(id="raw1", name="raw_orders", fqn="proj.raw.orders"),
        ]
        recs = recommend_for_node(target, upstream_nodes=upstream)
        upstream_recs = [r for r in recs if r.source == "upstream"]
        for r in upstream_recs:
            assert "mart_orders" in r.reason


# ---------------------------------------------------------------------------
# 3. Bundle tests
# ---------------------------------------------------------------------------

class TestBundles:

    def test_asset_stability_bundle(self):
        node = _make_node()
        bundles = get_bundles(node)
        asset_bundle = next((b for b in bundles if b.bundle_key == "asset_stability"), None)
        assert asset_bundle is not None
        assert len(asset_bundle.recommendations) >= 3
        keys = _rec_keys(asset_bundle.recommendations)
        assert FRESHNESS in keys
        assert VOLUME in keys

    def test_upstream_stability_bundle(self):
        target = _make_node()
        upstream = [
            _make_node(id="up1", name="src", fqn="proj.raw.src"),
        ]
        bundles = get_bundles(target, upstream_nodes=upstream)
        up_bundle = next((b for b in bundles if b.bundle_key == "upstream_stability"), None)
        assert up_bundle is not None
        assert len(up_bundle.recommendations) > 0

    def test_reporting_health_bundle_bi_only(self):
        # Non-BI node should NOT get reporting_health
        wh_node = _make_node()
        bundles = get_bundles(wh_node, upstream_nodes=[
            _make_node(id="up1", name="src", fqn="proj.raw.src"),
        ])
        assert not any(b.bundle_key == "reporting_health" for b in bundles)

        # BI node SHOULD get reporting_health
        bi_node = _make_node(
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
            platform="looker",
            fqn="looker.dashboard.sales",
        )
        bundles = get_bundles(bi_node, upstream_nodes=[
            _make_node(id="up1", name="src", fqn="proj.raw.src"),
        ])
        rh = next((b for b in bundles if b.bundle_key == "reporting_health"), None)
        assert rh is not None
        assert len(rh.recommendations) > 0

    def test_bi_node_no_asset_stability_bundle(self):
        bi_node = _make_node(
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
        )
        bundles = get_bundles(bi_node)
        assert not any(b.bundle_key == "asset_stability" for b in bundles)

    def test_bundle_cap_at_8(self):
        target = _make_node(
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
            fqn="looker.dash.main",
        )
        # Create 10 upstream warehouse tables to exceed cap
        upstream = [
            _make_node(
                id=f"up{i}", name=f"table_{i}", fqn=f"proj.raw.table_{i}",
                platform_domain=PlatformDomain.WAREHOUSE,
            )
            for i in range(10)
        ]
        bundles = get_bundles(target, upstream_nodes=upstream)
        for b in bundles:
            assert len(b.recommendations) <= BUNDLE_CAP

    def test_bundle_recommendations_have_source_bundle(self):
        node = _make_node()
        bundles = get_bundles(node)
        for b in bundles:
            for r in b.recommendations:
                assert r.source == "bundle"

    def test_no_bundles_for_node_without_upstream(self):
        bi_node = _make_node(
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
        )
        bundles = get_bundles(bi_node, upstream_nodes=[])
        # No upstream stability, no reporting health (no upstream)
        assert not any(b.bundle_key == "upstream_stability" for b in bundles)
        assert not any(b.bundle_key == "reporting_health" for b in bundles)


# ---------------------------------------------------------------------------
# 4. Dedup and bounds tests
# ---------------------------------------------------------------------------

class TestDedupAndBounds:

    def test_existing_monitors_marked_covered(self):
        node = _make_node()
        existing = {f"FRESHNESS:{node.fqn}"}
        recs = recommend_for_node(node, existing_monitor_fqns=existing)
        freshness_rec = next(r for r in recs if r.monitor_key == FRESHNESS)
        assert freshness_rec.already_monitored is True
        # Others should not be marked
        volume_rec = next(r for r in recs if r.monitor_key == VOLUME)
        assert volume_rec.already_monitored is False

    def test_no_duplicate_keys_per_target(self):
        target = _make_node()
        upstream = [
            _make_node(id="up1", name="src", fqn="proj.raw.src"),
        ]
        recs = recommend_for_node(target, upstream_nodes=upstream)
        seen = set()
        for r in recs:
            key = f"{r.monitor_key}:{r.target_fqn}"
            assert key not in seen, f"Duplicate recommendation: {key}"
            seen.add(key)

    def test_recommendations_sorted_by_priority(self):
        node = _make_node(criticality="critical")
        recs = recommend_for_node(node)
        priorities = [r.priority for r in recs]
        assert priorities == sorted(priorities)

    def test_config_hints_timestamp_column(self):
        node = _make_node(columns=[
            {"name": "id", "type": "INT64"},
            {"name": "updated_at", "type": "TIMESTAMP"},
            {"name": "status", "type": "STRING"},
        ])
        recs = recommend_for_node(node)
        freshness_rec = next(r for r in recs if r.monitor_key == FRESHNESS)
        assert freshness_rec.config_hints.get("timestamp_column") == "updated_at"

    def test_config_hints_connector_id(self):
        node = _make_node(
            node_type=NodeType.CONNECTOR,
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.CONNECTOR,
            platform="fivetran",
            integration_id="int_abc123",
        )
        recs = recommend_for_node(node)
        sync_rec = next(r for r in recs if r.monitor_key == SYNC_LAG)
        assert sync_rec.config_hints.get("connector_id") == "int_abc123"

    def test_config_hints_dag_id(self):
        node = _make_node(
            name="daily_etl",
            node_type=NodeType.DAG,
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            platform="airflow",
        )
        recs = recommend_for_node(node)
        dag_rec = next(r for r in recs if r.monitor_key == DAG_LAST_RUN)
        assert dag_rec.config_hints.get("dag_id") == "daily_etl"


# ---------------------------------------------------------------------------
# 5. Prefill shape tests
# ---------------------------------------------------------------------------

class TestPrefillShape:

    def test_prefill_shape_matches_create_task_api(self):
        """Verify recommendation to_dict() has all fields needed for prefill."""
        node = _make_node()
        recs = recommend_for_node(node)
        for r in recs:
            d = r.to_dict()
            assert "monitor_key" in d
            assert "target_fqn" in d
            assert "config_hints" in d
            assert "integration_type" in d
            assert isinstance(d["config_hints"], dict)

    def test_to_dict_roundtrip(self):
        node = _make_node()
        recs = recommend_for_node(node)
        for r in recs:
            d = r.to_dict()
            assert d["monitor_key"] == r.monitor_key
            assert d["target_fqn"] == r.target_fqn
            assert d["source"] == r.source

    def test_bundle_to_dict(self):
        node = _make_node()
        bundles = get_bundles(node)
        for b in bundles:
            d = b.to_dict()
            assert "bundle_key" in d
            assert "label" in d
            assert "recommendations" in d
            assert isinstance(d["recommendations"], list)
            for r in d["recommendations"]:
                assert "monitor_key" in r
