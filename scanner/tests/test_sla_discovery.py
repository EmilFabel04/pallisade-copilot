"""Tests for the SLA discovery module."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, PropertyMock

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


def _col(name: str, dtype: str = "STRING", pk: bool = False, nullable: bool = True, ordinal: int = 0):
    """Build a mock ColumnMetadata."""
    c = MagicMock()
    c.name = name
    c.data_type = dtype
    c.is_primary_key = pk
    c.is_nullable = nullable
    c.ordinal_position = ordinal
    return c


def _mock_adapter(hours_since=4.0, row_count=10000, null_rates=None, columns=None):
    """Build a mock adapter with get_table_freshness, get_null_rates, get_columns."""
    adapter = MagicMock()
    adapter.get_table_freshness.return_value = {
        "last_updated": datetime.now(timezone.utc) - timedelta(hours=hours_since),
        "hours_since_update": hours_since,
        "row_count": row_count,
        "timestamp_column": "updated_at",
        "source": "column",
    }
    adapter.get_null_rates.return_value = null_rates or {"col_a": 0.01, "col_b": 0.05, "col_c": 0.0}
    adapter.quote_identifier.side_effect = lambda x: f"`{x}`"

    col_mocks = []
    for name, dtype in (columns or [("id", "INT64"), ("name", "STRING"), ("updated_at", "TIMESTAMP")]):
        c = MagicMock()
        c.name = name
        c.data_type = dtype
        col_mocks.append(c)
    adapter.get_columns.return_value = col_mocks

    return adapter


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
        dbt_model = _make_node("dbt.schema.model", platform_domain=PlatformDomain.TRANSFORM, node_type=NodeType.MODEL)
        graph = _make_graph(dbt_model)
        result = _find_warehouse_ancestor(dbt_model, graph)
        assert result is None

    def test_finds_nearest_ancestor(self):
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor
        deep = _make_node("db.schema.source", platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.TABLE)
        mid = _make_node("db.schema.staging", platform_domain=PlatformDomain.WAREHOUSE, node_type=NodeType.VIEW)
        leaf = _make_node("dbt.schema.model", platform_domain=PlatformDomain.TRANSFORM, node_type=NodeType.MODEL)
        graph = _make_graph(deep, mid, leaf, ("db.schema.source", "db.schema.staging"), ("db.schema.staging", "dbt.schema.model"))
        result = _find_warehouse_ancestor(leaf, graph)
        assert result is mid


# ---------------------------------------------------------------------------
# _compute_freshness
# ---------------------------------------------------------------------------

class TestComputeFreshness:

    def test_basic_freshness(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        metadata = {"hours_since_update": 4.0, "row_count": 1000}
        result = _compute_freshness(None, "db.schema.table", metadata=metadata)
        assert result is not None
        assert result["enabled"] is True
        assert result["maxHours"] >= result["warningHours"]
        assert result["warningHours"] >= 1

    def test_very_fresh_table(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        metadata = {"hours_since_update": 0.5, "row_count": 1000}
        result = _compute_freshness(None, "db.schema.table", metadata=metadata)
        assert result is not None
        assert result["warningHours"] == 1
        assert result["maxHours"] == 2

    def test_stale_table(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        metadata = {"hours_since_update": 48.0, "row_count": 1000}
        result = _compute_freshness(None, "db.schema.table", metadata=metadata)
        assert result is not None
        assert result["warningHours"] >= 48
        assert result["maxHours"] > result["warningHours"]

    def test_no_metadata_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        result = _compute_freshness(None, "db.schema.table", metadata=None)
        assert result is None

    def test_empty_metadata_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_freshness
        result = _compute_freshness(None, "db.schema.table", metadata={})
        assert result is None


# ---------------------------------------------------------------------------
# _compute_volume
# ---------------------------------------------------------------------------

class TestComputeVolume:

    def test_basic_volume(self):
        from scanner.lineage.sla_discovery import _compute_volume
        metadata = {"row_count": 50000, "hours_since_update": 4.0}
        result = _compute_volume(None, "db.schema.table", metadata=metadata)
        assert result is not None
        assert result["enabled"] is True
        assert result["currentRows"] == 50000
        assert "minRows" not in result  # user sets these manually

    def test_zero_rows_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_volume
        metadata = {"row_count": 0}
        result = _compute_volume(None, "db.schema.table", metadata=metadata)
        assert result is None

    def test_no_metadata_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_volume
        result = _compute_volume(None, "db.schema.table", metadata=None)
        assert result is None


# ---------------------------------------------------------------------------
# _compute_quality
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _compute_schema
# ---------------------------------------------------------------------------

class TestComputeSchema:

    def test_standard_columns_suggest_strict(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("name", "STRING"), ("ts", "TIMESTAMP")])
        result = _compute_schema(adapter, "db.schema.table")
        assert result is not None
        assert result["strictness"] == "strict"
        assert result["allowEvolution"] is False
        assert result["columnCount"] == 3

    def test_json_columns_suggest_warn(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("payload", "JSON"), ("ts", "TIMESTAMP")])
        result = _compute_schema(adapter, "db.schema.table")
        assert result is not None
        assert result["strictness"] == "warn"
        assert result["allowEvolution"] is True

    def test_variant_columns_suggest_warn(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("data", "VARIANT")])
        result = _compute_schema(adapter, "db.schema.table")
        assert result is not None
        assert result["strictness"] == "warn"
        assert result["allowEvolution"] is True

    def test_exception_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_columns.side_effect = Exception("access denied")
        result = _compute_schema(adapter, "db.schema.table")
        assert result is None

    def test_empty_columns_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_columns.return_value = []
        result = _compute_schema(adapter, "db.schema.table")
        assert result is None


# ---------------------------------------------------------------------------
# _detect_pk_columns
# ---------------------------------------------------------------------------

class TestDetectPKColumns:

    def test_declared_pk_preferred(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("user_id", pk=False), _col("id", pk=False), _col("email", pk=True)]
        result = _detect_pk_columns(cols)
        assert result == (["email"], "declared_pk")

    def test_multiple_declared_pks(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("org_id", pk=True), _col("user_id", pk=True), _col("name")]
        result = _detect_pk_columns(cols)
        assert result == (["org_id", "user_id"], "declared_pk")

    def test_fallback_id_column(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("id"), _col("name"), _col("email")]
        result = _detect_pk_columns(cols)
        assert result == (["id"], "heuristic_id")

    def test_fallback_underscore_id_pattern(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("user_id"), _col("name"), _col("email")]
        result = _detect_pk_columns(cols)
        assert result == (["user_id"], "heuristic_id_suffix")

    def test_fallback_uuid(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("uuid"), _col("payload"), _col("created_at")]
        result = _detect_pk_columns(cols)
        assert result == (["uuid"], "heuristic_common_name")

    def test_fallback_guid(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("data"), _col("guid"), _col("ts")]
        result = _detect_pk_columns(cols)
        assert result == (["guid"], "heuristic_common_name")

    def test_no_pk_detected(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("payload"), _col("metadata"), _col("created_at")]
        result = _detect_pk_columns(cols)
        assert result == ([], "none")

    def test_empty_columns(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        result = _detect_pk_columns([])
        assert result == ([], "none")


# ---------------------------------------------------------------------------
# _compute_uniqueness
# ---------------------------------------------------------------------------

class TestComputeUniqueness:

    def test_zero_duplicates(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id", pk=True), _col("name")]
        # APPROX_COUNT_DISTINCT returns 1000, COUNT(*) returns 1000
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 1000}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is not None
        assert result["enabled"] is True
        assert result["duplicateRate"] == 0.0
        assert result["primaryKeyColumns"] == ["id"]
        assert result["totalRows"] == 1000
        assert result["distinctRows"] == 1000

    def test_some_duplicates(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id"), _col("name")]
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 970}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is not None
        assert result["duplicateRate"] == pytest.approx(0.03, abs=0.001)
        assert result["detectionMethod"] == "heuristic_id"
        assert result["approximate"] is True

    def test_no_pk_skips(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("payload"), _col("metadata")]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is not None
        assert result["enabled"] is False
        assert result["skipped"] is True
        assert "no PK" in result["reason"]

    def test_query_failure_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id")]
        adapter.execute_query.side_effect = Exception("timeout")
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is None

    def test_get_columns_failure_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.side_effect = Exception("access denied")
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is None

    def test_postgres_uses_exact_count(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "postgres"
        adapter.get_columns.return_value = [_col("id")]
        adapter.execute_query.return_value = [{"_total": 500, "_distinct": 500}]
        result = _compute_uniqueness(adapter, "public.table")
        assert result is not None
        assert result["approximate"] is False

    def test_threshold_suggestion(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id")]
        # 2% duplicate rate -> threshold should be max(0.02 * 1.5, 0.01) = 0.03
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 980}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result["suggestedThreshold"] == pytest.approx(0.03, abs=0.001)

    def test_threshold_floor(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id")]
        # 0% duplicate rate -> threshold floor at 0.01
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 1000}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result["suggestedThreshold"] == pytest.approx(0.01, abs=0.001)
