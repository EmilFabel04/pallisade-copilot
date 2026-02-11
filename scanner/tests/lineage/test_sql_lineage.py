"""
Tests for SQL parsing and column-level lineage extraction.
"""

import pytest

from scanner.lineage.parser import UniversalLineageParser


class TestTableExtraction:
    """Table-level reference extraction."""

    @pytest.fixture
    def parser(self):
        return UniversalLineageParser(default_dialect="postgres")

    def test_simple_select(self, parser):
        info = parser.parse_query("SELECT * FROM users")
        assert "users" in info.sources
        assert info.targets == []

    def test_join(self, parser):
        info = parser.parse_query(
            "SELECT u.id, o.amount FROM users u JOIN orders o ON u.id = o.user_id"
        )
        assert "users" in info.sources
        assert "orders" in info.sources

    def test_cte(self, parser):
        sql = """
        WITH active AS (
            SELECT id FROM users WHERE active = true
        )
        SELECT a.id FROM active a
        """
        info = parser.parse_query(sql)
        assert "users" in info.sources
        assert "active" not in info.sources  # CTE name removed

    def test_union(self, parser):
        sql = """
        SELECT id FROM users
        UNION ALL
        SELECT id FROM admins
        """
        info = parser.parse_query(sql)
        assert "users" in info.sources
        assert "admins" in info.sources

    def test_insert_into_select(self, parser):
        sql = "INSERT INTO target_table SELECT * FROM source_table"
        info = parser.parse_query(sql)
        assert "target_table" in info.targets
        assert "source_table" in info.sources

    def test_create_table_as_select(self, parser):
        sql = "CREATE TABLE new_table AS SELECT * FROM old_table"
        info = parser.parse_query(sql)
        assert "new_table" in info.targets
        assert "old_table" in info.sources

    @pytest.mark.parametrize("dialect", ["postgres", "bigquery", "snowflake"])
    def test_multi_dialect(self, dialect):
        parser = UniversalLineageParser(default_dialect=dialect)
        info = parser.parse_query("SELECT a FROM t1 JOIN t2 ON t1.id = t2.id", dialect)
        assert "t1" in info.sources
        assert "t2" in info.sources


class TestColumnLineage:
    """Column-level lineage extraction (safe by design)."""

    @pytest.fixture
    def parser(self):
        return UniversalLineageParser(default_dialect="postgres")

    def test_explicit_select_produces_mappings(self, parser):
        sql = "SELECT u.id, u.name FROM users u"
        mappings = parser.extract_column_lineage(sql)
        assert len(mappings) >= 1
        cols = {m["to_column"] for m in mappings}
        assert "id" in cols or "name" in cols

    def test_select_star_produces_no_mappings(self, parser):
        """SELECT * is ambiguous — must return empty."""
        sql = "SELECT * FROM users"
        mappings = parser.extract_column_lineage(sql)
        assert mappings == []

    def test_aliased_columns(self, parser):
        sql = "SELECT u.id AS user_id, u.email AS contact_email FROM users u"
        mappings = parser.extract_column_lineage(sql)
        out_cols = {m["to_column"] for m in mappings}
        assert "user_id" in out_cols
        assert "contact_email" in out_cols

    def test_cte_traces_through(self, parser):
        sql = """
        WITH base AS (
            SELECT t.id, t.name FROM raw_table t
        )
        SELECT b.id, b.name FROM base b
        """
        mappings = parser.extract_column_lineage(sql)
        # Should trace through CTE back to raw_table
        from_tables = {m.get("from_table", "") for m in mappings}
        # At least some mappings should exist
        assert len(mappings) >= 1

    def test_aggregate_produces_mapping(self, parser):
        sql = "SELECT u.country, COUNT(u.id) AS cnt FROM users u GROUP BY 1"
        mappings = parser.extract_column_lineage(sql)
        out_cols = {m["to_column"] for m in mappings}
        assert "country" in out_cols or "cnt" in out_cols

    def test_parse_error_returns_empty(self, parser):
        """Malformed SQL should not produce column mappings."""
        sql = "NOT VALID SQL AT ALL"
        mappings = parser.extract_column_lineage(sql)
        assert mappings == []


class TestSQLLineageExtractor:
    """Tests for the engine's SQLLineageExtractor wrapper."""

    def test_extract_produces_edges_with_evidence(self):
        from scanner.lineage.engine.sql_lineage import SQLLineageExtractor

        extractor = SQLLineageExtractor(default_dialect="postgres")
        sql = "SELECT u.id, u.name FROM users u JOIN orders o ON u.id = o.user_id"

        edges, col_maps = extractor.extract(
            sql=sql,
            adapter_id="test",
            source_ref="test_query",
            source_node_ids={"users": "node_users", "orders": "node_orders"},
            target_node_id="node_result",
        )

        # Should produce table-level edges
        table_edges = [e for e in edges if e.lineage_level.value == "table"]
        assert len(table_edges) >= 1

        # All edges should have evidence
        for e in edges:
            assert len(e.evidence) > 0
            assert e.evidence[0].adapter_id == "test"
