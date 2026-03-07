"""Tests for EvidenceStore: truncation, scoping, caching."""

import pytest
from unittest.mock import MagicMock

from copilot.maas.evidence_store import (
    EvidenceStore,
    EvidenceItem,
    MAX_TOOL_RESULT_CHARS,
    MAX_LOG_LINES,
    MAX_LINEAGE_NODES,
    MAX_TOTAL_EVIDENCE_CHARS,
)
from copilot.context_builder import TableSchema

from .conftest import make_context, make_table_schema


class TestEvidenceStoreBounds:
    def test_truncates_tool_result(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        large_data = {"data": "x" * (MAX_TOOL_RESULT_CHARS + 1000)}
        store.add_tool_result("query_warehouse", large_data)

        assert len(store.items) == 1
        assert store.items[0].char_count <= MAX_TOOL_RESULT_CHARS + 100  # +overhead for truncation msg

    def test_truncates_log_lines(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        log_text = "\n".join([f"line {i}" for i in range(200)])
        store.add_log_excerpt("airflow", log_text)

        assert len(store.items) == 1
        lines = store.items[0].data.split("\n")
        assert len(lines) <= MAX_LOG_LINES + 1  # +1 for truncation message

    def test_truncates_lineage_nodes(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        nodes = [{"id": f"node_{i}", "name": f"table_{i}"} for i in range(50)]
        store.add_lineage("upstream", nodes)

        assert len(store._lineage_upstream) == MAX_LINEAGE_NODES

    def test_total_evidence_cap(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        # Add many items to exceed total cap
        for i in range(20):
            store.add_tool_result(f"tool_{i}", {"data": "x" * 2000})

        blob = store.for_specialist("logs", "test query")
        assert len(blob) <= MAX_TOTAL_EVIDENCE_CHARS + 50  # +overhead


class TestEvidenceStoreScoping:
    def test_sql_specialist_gets_schema(self):
        tables = [make_table_schema("orders", [{"name": "id", "type": "INT"}])]
        ctx = make_context(warehouse_schema={"BIGQUERY:analytics": tables})
        store = EvidenceStore(context=ctx)

        blob = store.for_specialist("sql", "count orders")
        assert "Schema" in blob

    def test_logs_specialist_gets_lineage(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)
        store.add_lineage("downstream", [{"name": "dashboard_revenue"}])

        blob = store.for_specialist("logs", "why did the job fail")
        assert "Lineage" in blob
        assert "dashboard_revenue" in blob

    def test_warehouse_filter(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        store.add_tool_result("query_warehouse", {"data": "bq_result"}, warehouse="bigquery")
        store.add_tool_result("query_warehouse", {"data": "sf_result"}, warehouse="snowflake")

        blob = store.for_specialist("sql", "test", warehouse_filter="bigquery")
        assert "bq_result" in blob
        assert "sf_result" not in blob


class TestEvidenceStoreCache:
    def test_cache_and_retrieve(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        store.cache_result("hash_abc", {"data": "cached"})
        assert store.get_cached_result("hash_abc") == {"data": "cached"}

    def test_cache_miss(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        assert store.get_cached_result("nonexistent") is None


class TestEvidenceStoreCategorization:
    def test_categorizes_query_result(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        store.add_tool_result("query_warehouse", {"data": {"rows": []}})
        assert store.items[0].category == "query_result"

    def test_categorizes_log(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        store.add_tool_result("get_dag_run_log", {"data": "log text"})
        assert store.items[0].category == "log"

    def test_summarizes_list_result(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        store.add_tool_result("search_lineage", {"success": True, "data": [1, 2, 3]})
        assert store.items[0].summary == "Returned 3 items"

    def test_summarizes_failed_result(self):
        ctx = make_context()
        store = EvidenceStore(context=ctx)

        store.add_tool_result("query_warehouse", {"success": False, "error": "timeout"})
        assert "FAILED" in store.items[0].summary
