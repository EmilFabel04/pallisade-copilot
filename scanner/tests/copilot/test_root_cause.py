"""Tests for the root cause ownership resolver."""

import pytest
from copilot.root_cause import (
    resolve_fix_owner,
    OwnerSystem,
    OwnerDecision,
    format_owner_hint,
)
from copilot.intent import classify_intent, Intent, ScoredIntent, IntentResult


def _make_debug_intent(**kwargs):
    """Helper to create a DEBUG IntentResult."""
    return IntentResult(
        primary=ScoredIntent(intent=Intent.DEBUG, score=0.9, evidence=["test"]),
        **kwargs,
    )


def _make_fix_intent(target_hint=None):
    """Helper to create a FIX IntentResult."""
    return IntentResult(
        primary=ScoredIntent(intent=Intent.FIX, score=0.9, evidence=["test"]),
        target_hint=target_hint,
    )


class TestResolveFixOwner:
    """Unit tests for resolve_fix_owner()."""

    # --- dbt errors ---

    def test_dbt_compilation_error(self):
        tool_results = [{
            "tool": "get_dbt_run_history",
            "result": {
                "success": True,
                "data": {
                    "runs": [{
                        "status": "error",
                        "error": "Compilation Error in model stg_orders"
                    }]
                },
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.DBT
        assert decision.confidence >= 0.8

    def test_dbt_database_error(self):
        tool_results = [{
            "tool": "get_dbt_run_history",
            "result": {
                "success": True,
                "data": {"error": "Database Error in model analytics.dim_customers"},
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.DBT
        assert decision.confidence >= 0.8

    def test_dbt_relation_not_exist(self):
        tool_results = [{
            "tool": "get_dbt_test_results",
            "result": {
                "success": True,
                "data": {"error": "relation raw.orders does not exist"},
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.DBT
        assert decision.confidence >= 0.7

    # --- Airflow errors ---

    def test_airflow_dag_parse_error(self):
        tool_results = [{
            "tool": "mcp_airflow__get_task_logs",
            "result": {
                "success": True,
                "data": {
                    "logs": "DAG import error: ModuleNotFoundError: No module named 'custom_operators'"
                },
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.AIRFLOW
        assert decision.confidence >= 0.8

    def test_airflow_import_error(self):
        tool_results = [{
            "tool": "mcp_airflow__get_task_logs",
            "result": {
                "success": True,
                "data": {"logs": "ImportError: cannot import name 'dag_utils' from airflow plugins"},
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.AIRFLOW
        assert decision.confidence >= 0.8

    # --- dbt failing INSIDE Airflow ---

    def test_dbt_in_airflow(self):
        tool_results = [{
            "tool": "mcp_airflow__get_task_logs",
            "result": {
                "success": True,
                "data": {
                    "logs": (
                        "Running: dbt run --models stg_orders\n"
                        "Compilation Error in model stg_orders\n"
                        "Task failed with return code 1"
                    )
                },
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.DBT
        assert "dbt" in decision.explanation.lower()

    def test_dbt_in_airflow_inferred(self):
        """dbt invocation detected but only generic Airflow error patterns."""
        tool_results = [{
            "tool": "mcp_airflow__get_task_logs",
            "result": {
                "success": True,
                "data": {
                    "logs": (
                        "Executing dbt run --select stg_orders\n"
                        "dag_run failed"
                    )
                },
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        # Should still identify dbt as owner since dbt invocation detected
        assert decision.owner_system == OwnerSystem.DBT

    # --- Ingestion errors ---

    def test_fivetran_connector_broken(self):
        tool_results = [{
            "tool": "get_fivetran_connector_status",
            "result": {
                "success": True,
                "data": {"status": "broken", "error": "Authentication failed"},
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.INGESTION
        assert decision.confidence >= 0.8

    def test_fivetran_sync_failure(self):
        tool_results = [{
            "tool": "get_fivetran_sync_logs",
            "result": {
                "success": True,
                "data": {"logs": "sync failed due to source schema changed"},
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.INGESTION

    def test_schema_drift(self):
        tool_results = [{
            "tool": "get_fivetran_schema_changes",
            "result": {
                "success": True,
                "data": {"changes": [{"type": "schema change", "table": "orders"}]},
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.INGESTION

    # --- Warehouse errors ---

    def test_warehouse_permission_error(self):
        tool_results = [{
            "tool": "query_warehouse",
            "result": {
                "success": False,
                "error": "Permission denied for relation raw.orders",
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.WAREHOUSE
        assert decision.confidence >= 0.8

    def test_warehouse_quota_exceeded(self):
        tool_results = [{
            "tool": "query_warehouse",
            "result": {
                "success": False,
                "error": "RESOURCE_EXCEEDED: Query exceeded memory limits",
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.WAREHOUSE

    # --- Infrastructure errors ---

    def test_auth_error(self):
        tool_results = [{
            "tool": "mcp_airflow__get_dag_status",
            "result": {
                "success": False,
                "error": "401 Unauthorized",
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.INFRA

    def test_connection_refused(self):
        tool_results = [{
            "tool": "mcp_airflow__get_dag_status",
            "result": {
                "success": False,
                "error": "connection refused to airflow-webserver:8080",
            },
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.owner_system == OwnerSystem.INFRA

    # --- Low confidence / unknown ---

    def test_low_confidence_suggests_tools(self):
        tool_results = [{
            "tool": "query_warehouse",
            "result": {"success": True, "data": {"rows": [{"count": 0}]}},
        }]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        assert decision.confidence < 0.6
        assert len(decision.suggested_tools) > 0

    def test_unknown_with_no_results(self):
        decision = resolve_fix_owner([], _make_debug_intent())
        assert decision.owner_system == OwnerSystem.UNKNOWN
        assert decision.confidence <= 0.3

    def test_suggested_tools_excludes_already_called(self):
        tool_results = [
            {"tool": "get_dbt_run_history", "result": {"success": True, "data": {}}},
            {"tool": "query_warehouse", "result": {"success": True, "data": {}}},
        ]
        decision = resolve_fix_owner(tool_results, _make_debug_intent())
        if decision.suggested_tools:
            assert "get_dbt_run_history" not in decision.suggested_tools
            assert "query_warehouse" not in decision.suggested_tools


class TestFormatOwnerHint:
    """Tests for format_owner_hint()."""

    def test_basic_hint(self):
        decision = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.9,
            explanation="dbt Compilation Error detected",
        )
        hint = format_owner_hint(decision)
        assert "dbt" in hint
        assert "90%" in hint

    def test_pivot_hint(self):
        """When user mentioned airflow but root cause is dbt."""
        decision = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.85,
            explanation="dbt command failing within Airflow task",
        )
        hint = format_owner_hint(decision, target_hint="airflow")
        assert "airflow" in hint.lower()
        assert "dbt" in hint.lower()
        assert "fix in dbt" in hint.lower() or "Create the fix in dbt" in hint

    def test_no_pivot_when_same(self):
        decision = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.9,
            explanation="dbt error",
        )
        hint = format_owner_hint(decision, target_hint="dbt")
        assert "Note:" not in hint  # No pivot note

    def test_low_confidence_hint(self):
        decision = OwnerDecision(
            owner_system=OwnerSystem.UNKNOWN,
            confidence=0.3,
            explanation="Could not determine root cause",
            suggested_tools=["get_dbt_run_history", "get_fivetran_connector_status"],
        )
        hint = format_owner_hint(decision)
        assert "clarifying question" in hint.lower() or "Confidence is low" in hint

    def test_entities_in_hint(self):
        decision = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.9,
            explanation="dbt error",
            related_entities=["stg_orders", "raw.orders"],
        )
        hint = format_owner_hint(decision)
        assert "stg_orders" in hint
