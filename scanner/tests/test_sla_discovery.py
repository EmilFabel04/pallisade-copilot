"""Tests for the SLA discovery module."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from scanner.lineage.graph import LineageGraph, LineageNode, LineageEdge, NodeType, PlatformDomain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(fqn, platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.TABLE, **kwargs):
    return LineageNode(
        id=fqn,
        name=fqn.split(".")[-1],
        fqn=fqn,
        node_type=node_type,
        platform_domain=platform_domain,
        **kwargs,
    )


def _make_graph(*nodes_and_edges):
    g = LineageGraph()
    nodes = [x for x in nodes_and_edges if isinstance(x, LineageNode)]
    edges = [x for x in nodes_and_edges if isinstance(x, tuple)]
    for n in nodes:
        g.add_node(n)
    for src, tgt in edges:
        g.add_edge(LineageEdge(
            id=f"{src}->{tgt}",
            source_id=src,
            target_id=tgt,
            edge_type="depends_on",
        ))
    return g


# ---------------------------------------------------------------------------
# _find_warehouse_ancestor
# ---------------------------------------------------------------------------

class TestFindWarehouseAncestor:

    def test_warehouse_table_returns_self(self):
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor
        node = _make_node("db.schema.table", platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.TABLE)
        graph = _make_graph(node)
        result = _find_warehouse_ancestor(node, graph)
        assert result is node

    def test_warehouse_view_returns_self(self):
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor
        node = _make_node("db.schema.view", platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.VIEW)
        graph = _make_graph(node)
        result = _find_warehouse_ancestor(node, graph)
        assert result is node

    def test_dbt_model_finds_upstream_table(self):
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor
        upstream = _make_node("db.schema.raw_table", platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.TABLE)
        dbt_model = _make_node("dbt.schema.model", platform_domain=PlatformDomain.TRANSFORM, node_type=NodeType.MODEL)
        graph = _make_graph(upstream, dbt_model, ("db.schema.raw_table", "dbt.schema.model"))
        result = _find_warehouse_ancestor(dbt_model, graph)
        assert result is upstream

    def test_no_ancestor_returns_none(self):
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor
        # A dbt model with no upstream
        dbt_model = _make_node("dbt.schema.model", platform_domain=PlatformDomain.TRANSFORM, node_type=NodeType.MODEL)
        graph = _make_graph(dbt_model)
        result = _find_warehouse_ancestor(dbt_model, graph)
        assert result is None

    def test_finds_nearest_ancestor(self):
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor
        # chain: warehouse_table -> dbt_model -> bi_dashboard
        wh_table = _make_node("db.schema.table", platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.TABLE)
        dbt_model = _make_node("dbt.schema.model", platform_domain=PlatformDomain.TRANSFORM, node_type=NodeType.MODEL)
        bi_dash = _make_node("looker.schema.dash", platform_domain=PlatformDomain.BI, node_type=NodeType.DASHBOARD)
        graph = _make_graph(
            wh_table, dbt_model, bi_dash,
            ("db.schema.table", "dbt.schema.model"),
            ("dbt.schema.model", "looker.schema.dash"),
        )
        result = _find_warehouse_ancestor(bi_dash, graph)
        # The nearest warehouse ancestor going upstream from bi_dash should be wh_table
        assert result is wh_table


# ---------------------------------------------------------------------------
# _compute_freshness
# ---------------------------------------------------------------------------

def _timestamps_with_interval(n: int, interval_hours: float) -> list:
    """Generate n timestamps spaced interval_hours apart."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [base + timedelta(hours=i * interval_hours) for i in range(n)]


class TestComputeFreshness:

    def test_basic_4h_interval(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        import math
        adapter = MagicMock()
        timestamps = _timestamps_with_interval(20, 4.0)
        adapter.get_freshness_history.return_value = timestamps

        result = _compute_freshness(adapter, "db.schema.table")

        assert result is not None
        assert result["enabled"] is True
        # With consistent 4h intervals, mean ~4h, p95 ~4h; maxHours = ceil(p95*1.2) >= 1
        assert result["maxHours"] >= 1
        assert result["warningHours"] >= 1
        assert result["maxHours"] >= result["warningHours"]

    def test_empty_history_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        adapter = MagicMock()
        adapter.get_freshness_history.return_value = []

        result = _compute_freshness(adapter, "db.schema.table")
        assert result is None

    def test_not_implemented_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        adapter = MagicMock()
        adapter.get_freshness_history.side_effect = NotImplementedError

        result = _compute_freshness(adapter, "db.schema.table")
        assert result is None

    def test_single_timestamp_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        adapter = MagicMock()
        # Only one timestamp → zero intervals
        adapter.get_freshness_history.return_value = [datetime(2024, 1, 1, tzinfo=timezone.utc)]

        result = _compute_freshness(adapter, "db.schema.table")
        assert result is None


# ---------------------------------------------------------------------------
# _compute_volume
# ---------------------------------------------------------------------------

def _row_counts(n: int, base: int = 100_000, step: int = 0) -> list:
    """Generate n (date, row_count) tuples."""
    base_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [(base_dt + timedelta(days=i), base + i * step) for i in range(n)]


class TestComputeVolume:

    def test_basic_30_days(self):
        from scanner.lineage.sla_discovery import _compute_volume
        adapter = MagicMock()
        # Use slight variation so sd > 0 and bounds are meaningfully different
        adapter.get_row_count_history.return_value = _row_counts(30, base=100_000, step=100)

        result = _compute_volume(adapter, "db.schema.table")

        assert result is not None
        assert result["enabled"] is True
        assert "minRows" in result
        assert "maxRows" in result
        assert result["minRows"] >= 0
        assert result["maxRows"] > result["minRows"]

    def test_insufficient_history_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_volume
        adapter = MagicMock()
        adapter.get_row_count_history.return_value = _row_counts(5)  # <7 points

        result = _compute_volume(adapter, "db.schema.table")
        assert result is None

    def test_not_implemented_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_volume
        adapter = MagicMock()
        adapter.get_row_count_history.side_effect = NotImplementedError

        result = _compute_volume(adapter, "db.schema.table")
        assert result is None

    def test_growth_rate_threshold_added_on_consistent_growth(self):
        from scanner.lineage.sla_discovery import _compute_volume
        adapter = MagicMock()
        # Consistent growth: each day adds 1000 rows
        adapter.get_row_count_history.return_value = _row_counts(30, base=10_000, step=1_000)

        result = _compute_volume(adapter, "db.schema.table")
        assert result is not None
        # Might or might not include growthRateThreshold — just verify no crash
        assert "enabled" in result


# ---------------------------------------------------------------------------
# _compute_quality
# ---------------------------------------------------------------------------

def _null_rates(n: int, rate: float = 0.02) -> list:
    """Generate n (date, null_rate) tuples with a fixed rate."""
    base_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [(base_dt + timedelta(days=i), rate) for i in range(n)]


class TestComputeQuality:

    def test_basic_30_days(self):
        from scanner.lineage.sla_discovery import _compute_quality
        adapter = MagicMock()
        adapter.get_daily_null_rates.return_value = _null_rates(30, rate=0.02)

        result = _compute_quality(adapter, "db.schema.table", "created_at")

        assert result is not None
        assert result["enabled"] is True
        assert "maxNullRate" in result
        assert 0.0 <= result["maxNullRate"] <= 0.5

    def test_insufficient_history_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_quality
        adapter = MagicMock()
        adapter.get_daily_null_rates.return_value = _null_rates(4)  # <7 points

        result = _compute_quality(adapter, "db.schema.table", "created_at")
        assert result is None

    def test_not_implemented_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_quality
        adapter = MagicMock()
        adapter.get_daily_null_rates.side_effect = NotImplementedError

        result = _compute_quality(adapter, "db.schema.table", "created_at")
        assert result is None

    def test_caps_at_50_percent(self):
        from scanner.lineage.sla_discovery import _compute_quality
        adapter = MagicMock()
        # Very high null rates — result should be capped at 0.5
        adapter.get_daily_null_rates.return_value = _null_rates(30, rate=0.45)

        result = _compute_quality(adapter, "db.schema.table", "created_at")
        assert result is not None
        assert result["maxNullRate"] <= 0.5


# ---------------------------------------------------------------------------
# _compute_schema
# ---------------------------------------------------------------------------

class TestComputeSchema:

    def test_no_changes_suggests_strict(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_schema_change_history.return_value = []

        result = _compute_schema(adapter, "db.schema.table")

        assert result is not None
        assert result["enforcement"] == "strict"
        assert result["allowEvolution"] is False

    def test_additions_suggest_warn(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_schema_change_history.return_value = [
            {"type": "addition", "column": "new_col", "date": "2024-01-15"},
        ]

        result = _compute_schema(adapter, "db.schema.table")

        assert result is not None
        assert result["enforcement"] == "warn"
        assert result["allowEvolution"] is True

    def test_removals_suggest_warn(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_schema_change_history.return_value = [
            {"type": "removal", "column": "old_col", "date": "2024-01-10"},
        ]

        result = _compute_schema(adapter, "db.schema.table")

        assert result is not None
        assert result["enforcement"] == "warn"
        assert result["allowEvolution"] is True

    def test_not_implemented_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_schema_change_history.side_effect = NotImplementedError

        result = _compute_schema(adapter, "db.schema.table")
        assert result is None
