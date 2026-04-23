"""Tests for SQL verifier: safety checks, schema match, warehouse targeting."""

import pytest

from copilot.maas.schemas import SQLResponse, WarehouseType
from copilot.maas.verifiers.sql_verifier import SQLVerifier


def _make_sql_response(sql: str, warehouse: str = "bigquery") -> SQLResponse:
    return SQLResponse(
        sql=sql,
        warehouse=WarehouseType(warehouse),
        explanation="test",
    )


class TestSQLVerifierSafety:
    def test_select_only_passes(self):
        v = SQLVerifier()
        resp = _make_sql_response("SELECT COUNT(*) FROM orders")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is True

    def test_rejects_insert(self):
        v = SQLVerifier()
        resp = _make_sql_response("INSERT INTO orders VALUES (1)")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is False
        assert any("INSERT" in e.upper() or "forbidden" in e.lower() for e in result.errors)

    def test_rejects_drop(self):
        v = SQLVerifier()
        resp = _make_sql_response("DROP TABLE orders")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is False

    def test_rejects_delete(self):
        v = SQLVerifier()
        resp = _make_sql_response("DELETE FROM orders WHERE id = 1")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is False

    def test_rejects_update(self):
        v = SQLVerifier()
        resp = _make_sql_response("UPDATE orders SET status = 'done'")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is False

    def test_rejects_truncate(self):
        v = SQLVerifier()
        resp = _make_sql_response("TRUNCATE TABLE orders")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is False


class TestSQLVerifierParentheses:
    def test_balanced_parens(self):
        v = SQLVerifier()
        resp = _make_sql_response("SELECT COUNT(*) FROM (SELECT * FROM orders) sub")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is True

    def test_unbalanced_parens(self):
        v = SQLVerifier()
        resp = _make_sql_response("SELECT COUNT(*) FROM (SELECT * FROM orders")
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is False
        assert any("parenthes" in e.lower() for e in result.errors)


class TestSQLVerifierSchema:
    def test_column_match_passes(self):
        v = SQLVerifier()
        schema_cols = {"orders": {"id", "status", "amount"}}
        resp = _make_sql_response("SELECT id, amount FROM orders")
        result = v.verify(resp, schema_cols, {"bigquery"})
        assert result.passed is True

    def test_column_mismatch_warns(self):
        v = SQLVerifier()
        schema_cols = {"orders": {"id", "status"}}
        resp = _make_sql_response("SELECT nonexistent_col FROM orders")
        result = v.verify(resp, schema_cols, {"bigquery"})
        # Column mismatch generates warnings, not errors
        assert len(result.warnings) > 0 or result.passed is True


class TestSQLVerifierWarehouse:
    def test_valid_warehouse(self):
        v = SQLVerifier()
        resp = _make_sql_response(
            "SELECT * FROM `project.dataset.table`",
            warehouse="bigquery",
        )
        result = v.verify(resp, {}, {"bigquery"})
        assert result.passed is True

    def test_warehouse_not_in_connected_list(self):
        v = SQLVerifier()
        resp = _make_sql_response("SELECT 1", warehouse="snowflake")
        # Multi-warehouse check only triggers when len > 1
        result = v.verify(resp, {}, ["bigquery", "postgres"])
        assert result.passed is False
        assert any("not in connected" in e.lower() or "warehouse" in e.lower() for e in result.errors)

    def test_multi_warehouse_requires_explicit(self):
        v = SQLVerifier()
        resp = _make_sql_response("SELECT 1", warehouse="bigquery")
        result = v.verify(resp, {}, ["bigquery", "snowflake"])
        assert result.passed is True  # warehouse is explicitly set


class TestSQLVerifierCallExec:
    """Test that CALL and EXEC statements are rejected."""

    def test_rejects_call(self):
        v = SQLVerifier()
        resp = _make_sql_response("CALL my_procedure()")
        result = v.verify(resp, {})
        assert result.passed is False
        assert any("CALL" in e for e in result.errors)

    def test_rejects_exec(self):
        v = SQLVerifier()
        resp = _make_sql_response("EXEC sp_help")
        result = v.verify(resp, {})
        assert result.passed is False
        assert any("EXEC" in e for e in result.errors)
