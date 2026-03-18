"""Tests for recommender policy integration — config hints reflect policy values."""

from __future__ import annotations

from scanner.lineage.graph import (
    AssetKind,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.monitors.policy_resolver import EffectivePolicy
from scanner.monitors.recommender import _build_config_hints


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    id: str = "n1",
    name: str = "my_table",
    fqn: str = "db.schema.my_table",
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


# ---------------------------------------------------------------------------
# Tests: policy=None preserves existing behavior
# ---------------------------------------------------------------------------

class TestNoPolicyPreservesDefaults:
    def test_freshness_without_policy(self):
        node = _make_node()
        hints = _build_config_hints(node, "FRESHNESS", policy=None)
        # Should not have policy-driven keys
        assert "freshness_hours" not in hints
        assert "warning_hours" not in hints

    def test_schema_change_without_policy(self):
        node = _make_node()
        hints = _build_config_hints(node, "SCHEMA_CHANGE", policy=None)
        assert "strictness" not in hints

    def test_volume_without_policy(self):
        node = _make_node()
        hints = _build_config_hints(node, "VOLUME", policy=None)
        assert "growth_rate_threshold" not in hints


# ---------------------------------------------------------------------------
# Tests: policy-driven overrides
# ---------------------------------------------------------------------------

class TestPolicyDrivenHints:
    def test_freshness_uses_policy_hours(self):
        node = _make_node()
        policy = EffectivePolicy(freshness_max_hours=4, freshness_warning_hours=2)
        hints = _build_config_hints(node, "FRESHNESS", policy=policy)
        assert hints["max_hours"] == 4
        assert hints["warning_hours"] == 2

    def test_schema_change_uses_policy_strictness(self):
        node = _make_node()
        policy = EffectivePolicy(schema_strictness="strict")
        hints = _build_config_hints(node, "SCHEMA_CHANGE", policy=policy)
        assert hints["strictness"] == "strict"

    def test_volume_uses_policy_threshold(self):
        node = _make_node()
        policy = EffectivePolicy(volume_growth_threshold=0.05, volume_min_rows=100, volume_max_rows=10000)
        hints = _build_config_hints(node, "VOLUME", policy=policy)
        assert hints["growth_rate_threshold"] == 0.05
        assert hints["min_rows"] == 100
        assert hints["max_rows"] == 10000

    def test_anomaly_uses_policy_sensitivity(self):
        node = _make_node()
        policy = EffectivePolicy(anomaly_sensitivity=0.99, anomaly_lookback_days=30)
        hints = _build_config_hints(node, "ANOMALY", policy=policy)
        # 0.99 sensitivity → 2.0 z-score threshold
        assert hints["anomaly_threshold"] == 2.0
        assert hints["lookback_days"] == 30

    def test_anomaly_standard_sensitivity(self):
        node = _make_node()
        policy = EffectivePolicy(anomaly_sensitivity=0.95)
        hints = _build_config_hints(node, "ANOMALY", policy=policy)
        # 0.95 sensitivity → 3.0 z-score threshold
        assert hints["anomaly_threshold"] == 3.0

    def test_null_rate_uses_policy(self):
        node = _make_node()
        policy = EffectivePolicy(quality_max_null_rate=0.01)
        hints = _build_config_hints(node, "NULL_RATE", policy=policy)
        assert hints["max_null_rate"] == 0.01

    def test_sync_lag_uses_policy(self):
        node = _make_node(
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.CONNECTOR,
        )
        policy = EffectivePolicy(sync_lag_tolerance_minutes=15)
        hints = _build_config_hints(node, "SYNC_LAG", policy=policy)
        assert hints["max_lag_minutes"] == 15

    def test_connector_schema_drift_uses_policy(self):
        node = _make_node(
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.CONNECTOR,
        )
        policy = EffectivePolicy(schema_drift_strictness="strict")
        hints = _build_config_hints(node, "CONNECTOR_SCHEMA_DRIFT", policy=policy)
        assert hints["strictness"] == "strict"

    def test_bi_freshness_uses_policy(self):
        node = _make_node(
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
        )
        policy = EffectivePolicy(bi_freshness_hours=4)
        hints = _build_config_hints(node, "BI_FRESHNESS_PROXY", policy=policy)
        assert hints["max_stale_hours"] == 4

    def test_bi_upstream_break_uses_policy(self):
        node = _make_node(
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
        )
        policy = EffectivePolicy(upstream_break_strictness="strict")
        hints = _build_config_hints(node, "BI_UPSTREAM_BREAK_RISK", policy=policy)
        assert hints["strictness"] == "strict"

    def test_dag_last_run_uses_policy(self):
        node = _make_node(
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            name="my_dag",
        )
        policy = EffectivePolicy(run_latency_minutes=15)
        hints = _build_config_hints(node, "DAG_LAST_RUN", policy=policy)
        assert hints["max_latency_minutes"] == 15

    def test_dag_schedule_lag_uses_policy(self):
        node = _make_node(
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            name="my_dag",
        )
        policy = EffectivePolicy(schedule_lag_minutes=5)
        hints = _build_config_hints(node, "DAG_SCHEDULE_LAG", policy=policy)
        assert hints["max_schedule_lag_minutes"] == 5

    def test_policy_with_no_relevant_fields_no_effect(self):
        """Policy with only BI fields doesn't affect FRESHNESS hints."""
        node = _make_node()
        policy = EffectivePolicy(bi_freshness_hours=4)
        hints = _build_config_hints(node, "FRESHNESS", policy=policy)
        assert "freshness_hours" not in hints
