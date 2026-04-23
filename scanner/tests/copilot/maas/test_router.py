"""Tests for intent-to-specialist routing + _is_data_query heuristic."""

import pytest
from unittest.mock import MagicMock

from copilot.intent import Intent
from copilot.context_builder import TableSchema

from copilot.maas.router import (
    route_intent,
    _is_data_query,
    filter_evidence_requests,
    SpecialistRoute,
)

from .conftest import make_intent_result, make_context, make_table_schema


class TestIsDataQuery:
    """Test the conservative _is_data_query heuristic."""

    def test_aggregate_keywords(self):
        ctx = make_context(query="how many orders do we have")
        assert _is_data_query("how many orders do we have", ctx) is True

    def test_count_keyword(self):
        ctx = make_context(query="count of active users")
        assert _is_data_query("count of active users", ctx) is True

    def test_sum_keyword(self):
        ctx = make_context(query="what is the sum of revenue")
        assert _is_data_query("what is the sum of revenue", ctx) is True

    def test_show_me_data(self):
        ctx = make_context(query="show me the data from orders table")
        assert _is_data_query("show me the data from orders table", ctx) is True

    def test_top_n_pattern(self):
        ctx = make_context(query="top 10 customers by revenue")
        assert _is_data_query("top 10 customers by revenue", ctx) is True

    def test_non_data_question(self):
        ctx = make_context(query="what integrations do I have")
        assert _is_data_query("what integrations do I have", ctx) is False

    def test_explain_pipeline(self):
        ctx = make_context(query="explain my pipeline setup")
        assert _is_data_query("explain my pipeline setup", ctx) is False

    def test_table_name_overlap(self):
        tables = [make_table_schema("orders", [{"name": "id", "type": "INT"}])]
        ctx = make_context(
            query="tell me about orders",
            warehouse_schema={"BIGQUERY:analytics": tables},
        )
        assert _is_data_query("tell me about orders", ctx) is True

    def test_column_name_overlap(self):
        tables = [make_table_schema("orders", [{"name": "revenue", "type": "FLOAT"}])]
        ctx = make_context(
            query="what is the revenue breakdown",
            warehouse_schema={"BIGQUERY:analytics": tables},
        )
        assert _is_data_query("what is the revenue breakdown", ctx) is True

    def test_no_schema_no_match(self):
        ctx = make_context(query="tell me about orders", warehouse_schema={})
        assert _is_data_query("tell me about orders", ctx) is False


class TestRouteIntent:
    def test_info_with_data_query(self):
        tables = [make_table_schema("orders", [{"name": "id", "type": "INT"}])]
        ctx = make_context(
            query="how many orders",
            warehouse_schema={"BIGQUERY:analytics": tables},
        )
        intent = make_intent_result(primary=Intent.INFO)
        route = route_intent(intent, ctx)
        assert "sql" in route.specialists
        assert "sql" in route.required_specialists

    def test_info_without_data_query(self):
        ctx = make_context(query="what integrations do I have")
        intent = make_intent_result(primary=Intent.INFO)
        route = route_intent(intent, ctx)
        assert route.specialists == []

    def test_debug_has_logs(self):
        ctx = make_context(query="why did the dbt run fail")
        intent = make_intent_result(primary=Intent.DEBUG, target_hint="dbt")
        route = route_intent(intent, ctx)
        assert "logs" in route.specialists
        assert "logs" in route.required_specialists

    def test_debug_with_fix_secondary(self):
        ctx = make_context(query="debug and fix the failure")
        intent = make_intent_result(
            primary=Intent.DEBUG,
            secondary=Intent.FIX,
        )
        route = route_intent(intent, ctx)
        assert route.specialists == ["logs"]
        assert route.required_specialists == ["logs"]

    def test_fix_has_logs_only(self):
        ctx = make_context(query="fix the dbt model")
        intent = make_intent_result(primary=Intent.FIX)
        route = route_intent(intent, ctx)
        assert route.specialists == ["logs"]
        assert route.required_specialists == ["logs"]

    def test_plan_has_no_specialists(self):
        ctx = make_context(query="plan the migration")
        intent = make_intent_result(primary=Intent.PLAN)
        route = route_intent(intent, ctx)
        assert route.specialists == []
        assert "get_upstream" in route.evidence_tools
        assert "get_downstream" in route.evidence_tools

    def test_explain_has_no_specialists(self):
        ctx = make_context(query="explain what lineage means")
        intent = make_intent_result(primary=Intent.EXPLAIN)
        route = route_intent(intent, ctx)
        assert route.specialists == []

    def test_fallback_for_unknown(self):
        ctx = make_context()
        # Use a known intent but test the fallback path
        intent = make_intent_result(primary=Intent.INFO)
        route = route_intent(intent, ctx)
        # Should return a valid route (the non-data INFO path)
        assert isinstance(route, SpecialistRoute)


class TestFilterEvidenceRequests:
    def test_filters_to_available(self):
        requested = ["get_dag_run_history", "get_downstream", "nonexistent"]
        available = {"get_dag_run_history", "get_downstream"}
        result = filter_evidence_requests(requested, available)
        assert "get_dag_run_history" in result
        assert "get_downstream" in result
        assert "nonexistent" not in result

    def test_lineage_fallback(self):
        requested = ["get_upstream"]
        available = {"search_lineage"}
        result = filter_evidence_requests(requested, available)
        assert "search_lineage" in result

    def test_empty_requested(self):
        result = filter_evidence_requests([], {"tool_a", "tool_b"})
        assert result == []


class TestNonDataQueryRouting:
    """INFO intent with non-data questions should route to GPT-5 only."""

    def test_info_non_data_routes_gpt5_only(self):
        ctx = make_context(query="what is a DAG?", warehouse_schema={})
        intent = make_intent_result(primary=Intent.INFO)
        route = route_intent(intent, ctx)
        assert route.specialists == []
        assert route.required_specialists == []

    def test_info_generic_without_schema(self):
        ctx = make_context(query="explain what BigQuery is", warehouse_schema={})
        intent = make_intent_result(primary=Intent.INFO)
        route = route_intent(intent, ctx)
        assert route.specialists == []
