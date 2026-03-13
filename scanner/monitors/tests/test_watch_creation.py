"""Tests for Group Monitor creation path — upstream monitor generation.

Validates that the recommend-monitors endpoint returns upstream monitor specs
for all relevant node types (DATASET, SEMANTIC, JOB) so that group monitor
creation produces monitors for both the anchor and upstream assets.
"""

import pytest
from ...lineage.graph import (
    LineageNode, NodeType, PlatformDomain, AssetKind,
)
from ...lineage.engine.canonical import map_node_type, CanonicalNodeType
from ..recommender import (
    recommend_for_node, get_bundles, is_bi_node,
    FRESHNESS, VOLUME, SCHEMA_CHANGE,
    SYNC_LAG, FAILED_SYNCS,
    DAG_LAST_RUN,
    DBT_TEST_FAILURES, DBT_MODEL_FRESHNESS,
    BI_FRESHNESS_PROXY, BI_CONTENT_HEALTH, BI_UPSTREAM_BREAK_RISK,
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
    return {r.monitor_key for r in recs}


def _rec_keys_for_target(recs: list, target_fqn: str) -> set:
    return {r.monitor_key for r in recs if r.target_fqn == target_fqn}


def _rec_targets(recs: list) -> set:
    return {r.target_fqn for r in recs}


# Simulate the endpoint-level canonical type filter (post-fix)
_RECOMMEND_NODE_TYPES = {
    CanonicalNodeType.DATASET.value,
    CanonicalNodeType.SEMANTIC.value,
    CanonicalNodeType.JOB.value,
}


def _apply_endpoint_filter(nodes: list) -> list:
    """Simulate the recommend-monitors endpoint filter."""
    return [
        n for n in nodes
        if (getattr(n, 'canonical_type', None) or map_node_type(n).value)
        in _RECOMMEND_NODE_TYPES
    ]


# ---------------------------------------------------------------------------
# 1. Canonical type filter tests — JOB nodes must pass through
# ---------------------------------------------------------------------------

class TestEndpointFilterAllowsJobNodes:
    """Verify that the widened canonical type filter lets JOB nodes through."""

    def test_connector_passes_filter(self):
        node = _make_node(
            id="conn1", name="fivetran_conn", fqn="fivetran.conn.x",
            node_type=NodeType.CONNECTOR,
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.CONNECTOR, platform="fivetran",
        )
        assert map_node_type(node) == CanonicalNodeType.JOB
        filtered = _apply_endpoint_filter([node])
        assert len(filtered) == 1

    def test_dag_passes_filter(self):
        node = _make_node(
            id="dag1", name="daily_dag", fqn="airflow.daily_dag",
            node_type=NodeType.DAG,
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB, platform="airflow",
        )
        assert map_node_type(node) == CanonicalNodeType.JOB
        filtered = _apply_endpoint_filter([node])
        assert len(filtered) == 1

    def test_workflow_passes_filter(self):
        node = _make_node(
            id="wf1", name="etl_flow", fqn="prefect.etl_flow",
            node_type=NodeType.WORKFLOW,
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB, platform="prefect",
        )
        assert map_node_type(node) == CanonicalNodeType.JOB
        filtered = _apply_endpoint_filter([node])
        assert len(filtered) == 1

    def test_table_still_passes_filter(self):
        node = _make_node()
        assert map_node_type(node) == CanonicalNodeType.DATASET
        filtered = _apply_endpoint_filter([node])
        assert len(filtered) == 1

    def test_dashboard_still_passes_filter(self):
        node = _make_node(
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD, platform="looker",
        )
        assert map_node_type(node) == CanonicalNodeType.SEMANTIC
        filtered = _apply_endpoint_filter([node])
        assert len(filtered) == 1

    def test_mixed_upstream_all_pass_filter(self):
        nodes = [
            _make_node(id="t1", fqn="proj.raw.orders"),
            _make_node(
                id="c1", fqn="fivetran.conn.x",
                node_type=NodeType.CONNECTOR,
                platform_domain=PlatformDomain.INGESTION,
                asset_kind=AssetKind.CONNECTOR,
            ),
            _make_node(
                id="d1", fqn="airflow.daily",
                node_type=NodeType.DAG,
                platform_domain=PlatformDomain.ORCHESTRATION,
                asset_kind=AssetKind.JOB,
            ),
            _make_node(
                id="m1", fqn="dbt.stg_orders",
                node_type=NodeType.MODEL,
                platform_domain=PlatformDomain.TRANSFORM,
                asset_kind=AssetKind.MODEL, platform="dbt",
            ),
        ]
        filtered = _apply_endpoint_filter(nodes)
        assert len(filtered) == len(nodes), (
            f"Expected all {len(nodes)} nodes to pass filter, got {len(filtered)}"
        )


# ---------------------------------------------------------------------------
# 2. pipeline_health watch — anchor + upstream monitors
# ---------------------------------------------------------------------------

class TestPipelineHealthWatch:
    """Simulate pipeline_health watch creation with mixed upstream nodes."""

    def _anchor(self):
        return _make_node(
            id="anchor", name="mart_orders",
            fqn="project.analytics.mart_orders",
        )

    def _upstream(self):
        return [
            _make_node(id="t1", name="raw_orders", fqn="proj.raw.orders"),
            _make_node(
                id="c1", name="fivetran_conn", fqn="fivetran.conn.orders",
                node_type=NodeType.CONNECTOR,
                platform_domain=PlatformDomain.INGESTION,
                asset_kind=AssetKind.CONNECTOR, platform="fivetran",
            ),
            _make_node(
                id="d1", name="daily_dag", fqn="airflow.daily_dag",
                node_type=NodeType.DAG,
                platform_domain=PlatformDomain.ORCHESTRATION,
                asset_kind=AssetKind.JOB, platform="airflow",
            ),
        ]

    def test_creates_direct_and_upstream_monitors(self):
        anchor = self._anchor()
        upstream = self._upstream()
        # Simulate endpoint filter
        filtered_upstream = _apply_endpoint_filter(upstream)
        recs = recommend_for_node(anchor, upstream_nodes=filtered_upstream)

        direct = [r for r in recs if r.source == "direct"]
        upstream_recs = [r for r in recs if r.source == "upstream"]

        # Anchor must have core warehouse monitors
        anchor_keys = _rec_keys_for_target(recs, anchor.fqn)
        assert FRESHNESS in anchor_keys
        assert VOLUME in anchor_keys
        assert SCHEMA_CHANGE in anchor_keys

        # Upstream must have type-specific monitors
        assert len(upstream_recs) >= 3
        assert FRESHNESS in _rec_keys_for_target(recs, "proj.raw.orders")
        assert SYNC_LAG in _rec_keys_for_target(recs, "fivetran.conn.orders")
        assert DAG_LAST_RUN in _rec_keys_for_target(recs, "airflow.daily_dag")

    def test_monitors_target_different_fqns(self):
        anchor = self._anchor()
        upstream = self._upstream()
        filtered_upstream = _apply_endpoint_filter(upstream)
        recs = recommend_for_node(anchor, upstream_nodes=filtered_upstream)

        targets = _rec_targets(recs)
        assert len(targets) >= 4, (
            f"Expected monitors on anchor + 3 upstream, got targets: {targets}"
        )
        assert anchor.fqn in targets
        assert "proj.raw.orders" in targets
        assert "fivetran.conn.orders" in targets
        assert "airflow.daily_dag" in targets


# ---------------------------------------------------------------------------
# 3. dashboard_shield watch — anchor + upstream monitors
# ---------------------------------------------------------------------------

class TestDashboardShieldWatch:
    """Simulate dashboard_shield watch creation."""

    def _anchor(self):
        return _make_node(
            id="dash1", name="Sales Overview",
            fqn="looker.dashboard.sales_overview",
            node_type=NodeType.DASHBOARD,
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD, platform="looker",
        )

    def _upstream(self):
        return [
            _make_node(id="t1", name="orders", fqn="proj.raw.orders"),
            _make_node(id="t2", name="payments", fqn="proj.raw.payments"),
            _make_node(
                id="c1", name="fivetran_conn", fqn="fivetran.conn.orders",
                node_type=NodeType.CONNECTOR,
                platform_domain=PlatformDomain.INGESTION,
                asset_kind=AssetKind.CONNECTOR, platform="fivetran",
            ),
        ]

    def test_creates_anchor_plus_upstream_monitors(self):
        anchor = self._anchor()
        upstream = self._upstream()
        filtered_upstream = _apply_endpoint_filter(upstream)
        recs = recommend_for_node(anchor, upstream_nodes=filtered_upstream)

        # Anchor must have BI monitors
        anchor_keys = _rec_keys_for_target(recs, anchor.fqn)
        assert BI_FRESHNESS_PROXY in anchor_keys
        assert BI_CONTENT_HEALTH in anchor_keys

        # Upstream tables must have FRESHNESS
        assert FRESHNESS in _rec_keys_for_target(recs, "proj.raw.orders")
        assert FRESHNESS in _rec_keys_for_target(recs, "proj.raw.payments")

        # Upstream connector must have SYNC_LAG
        assert SYNC_LAG in _rec_keys_for_target(recs, "fivetran.conn.orders")

    def test_bundles_include_upstream_stability(self):
        anchor = self._anchor()
        upstream = self._upstream()
        filtered_upstream = _apply_endpoint_filter(upstream)
        bundles = get_bundles(anchor, upstream_nodes=filtered_upstream)

        upstream_bundle = next(
            (b for b in bundles if b.bundle_key == "upstream_stability"), None
        )
        assert upstream_bundle is not None, (
            f"Expected upstream_stability bundle, got: {[b.bundle_key for b in bundles]}"
        )
        bundle_targets = {r.target_fqn for r in upstream_bundle.recommendations}
        assert anchor.fqn not in bundle_targets, (
            "Upstream stability bundle should not contain anchor monitors"
        )

    def test_monitors_have_distinct_target_fqns(self):
        anchor = self._anchor()
        upstream = self._upstream()
        filtered_upstream = _apply_endpoint_filter(upstream)
        recs = recommend_for_node(anchor, upstream_nodes=filtered_upstream)

        targets = _rec_targets(recs)
        # At minimum: anchor + 2 tables + 1 connector
        assert len(targets) >= 4


# ---------------------------------------------------------------------------
# 4. Dedup — existing monitors are linked, uncovered ones created
# ---------------------------------------------------------------------------

class TestDedupDoesNotDropUncoveredMonitors:
    """Verify dedup marks existing monitors but does not remove uncovered ones."""

    def test_existing_monitors_marked_not_dropped(self):
        anchor = _make_node(
            id="anchor", name="mart_orders",
            fqn="project.analytics.mart_orders",
        )
        upstream = [
            _make_node(id="t1", name="raw_orders", fqn="proj.raw.orders"),
            _make_node(
                id="c1", name="fivetran_conn", fqn="fivetran.conn.orders",
                node_type=NodeType.CONNECTOR,
                platform_domain=PlatformDomain.INGESTION,
                asset_kind=AssetKind.CONNECTOR, platform="fivetran",
            ),
        ]
        # Simulate that FRESHNESS:proj.raw.orders already exists
        existing = {"FRESHNESS:proj.raw.orders"}

        recs = recommend_for_node(anchor, upstream_nodes=upstream, existing_monitor_fqns=existing)

        # The existing monitor should be marked
        freshness_raw = next(
            (r for r in recs if r.monitor_key == FRESHNESS and r.target_fqn == "proj.raw.orders"),
            None,
        )
        assert freshness_raw is not None, "FRESHNESS rec for raw_orders should still exist"
        assert freshness_raw.already_monitored is True

        # The non-existing monitor should NOT be marked
        sync_lag = next(
            (r for r in recs if r.monitor_key == SYNC_LAG and r.target_fqn == "fivetran.conn.orders"),
            None,
        )
        assert sync_lag is not None, "SYNC_LAG rec for connector should exist"
        assert sync_lag.already_monitored is False

    def test_all_upstream_recs_preserved_despite_some_existing(self):
        anchor = _make_node()
        upstream = [
            _make_node(id="t1", fqn="proj.raw.orders"),
            _make_node(id="t2", fqn="proj.raw.payments"),
        ]
        # Even if one upstream monitor exists, the other must still be recommended
        existing = {"FRESHNESS:proj.raw.orders"}
        recs = recommend_for_node(anchor, upstream_nodes=upstream, existing_monitor_fqns=existing)

        upstream_recs = [r for r in recs if r.source == "upstream"]
        targets = {r.target_fqn for r in upstream_recs}
        assert "proj.raw.orders" in targets, "Existing upstream should still be in recommendations"
        assert "proj.raw.payments" in targets, "Non-existing upstream must not be dropped"


# ---------------------------------------------------------------------------
# 5. Selected monitors survive mock submission
# ---------------------------------------------------------------------------

class TestMonitorsSurviveSubmission:
    """Validate that building a monitor spec list from recommendations
    preserves upstream entries with correct targetFqn values — simulating
    what CreateTaskModal.parseRecommendData + handleSubmit do."""

    def test_submit_payload_has_upstream_target_fqns(self):
        anchor = _make_node(
            id="anchor", name="mart_orders",
            fqn="project.analytics.mart_orders",
        )
        upstream = [
            _make_node(id="t1", name="raw_orders", fqn="proj.raw.orders"),
            _make_node(
                id="c1", name="fivetran_conn", fqn="fivetran.conn.orders",
                node_type=NodeType.CONNECTOR,
                platform_domain=PlatformDomain.INGESTION,
                asset_kind=AssetKind.CONNECTOR, platform="fivetran",
            ),
        ]
        filtered_upstream = _apply_endpoint_filter(upstream)
        recs = recommend_for_node(anchor, upstream_nodes=filtered_upstream)

        # Simulate frontend parseRecommendData → handleSubmit
        # (maps rec.monitor_key → monitorType, rec.target_fqn → targetFqn)
        seen = set()
        monitors_payload = []
        for rec in recs:
            key = f"{rec.monitor_key}:{rec.target_fqn}"
            if key in seen:
                continue
            seen.add(key)
            monitors_payload.append({
                "name": f"{rec.monitor_key.lower()} — {rec.target_fqn.split('.')[-1]}",
                "monitorType": rec.monitor_key,
                "targetFqn": rec.target_fqn,
                "config": rec.config_hints,
            })

        # Payload must contain monitors for different FQNs
        payload_fqns = {m["targetFqn"] for m in monitors_payload}
        assert anchor.fqn in payload_fqns
        assert "proj.raw.orders" in payload_fqns
        assert "fivetran.conn.orders" in payload_fqns

        # Every monitor must have a valid monitorType
        for m in monitors_payload:
            assert m["monitorType"] is not None
            assert m["monitorType"] != ""
