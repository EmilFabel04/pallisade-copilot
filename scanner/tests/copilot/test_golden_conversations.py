"""
Golden conversation tests.

Integration-style tests that verify the full pipeline:
intent classification → prompt building → response structure.

These test the system prompt generation (not LLM output),
verifying that the correct Answer Contract and tool policy
are injected for each conversation type.
"""

import pytest
from unittest.mock import MagicMock, patch
from copilot.intent import classify_intent, Intent, IntentResult, ScoredIntent
from copilot.root_cause import resolve_fix_owner, OwnerSystem, OwnerDecision, format_owner_hint
from copilot.response_builder import build_answer_contract
from copilot.modes import mode_from_intent, get_mode_config


class TestInfoConversation:
    """
    Golden test: Simple data question.
    User: "How many orders yesterday?"
    Expected: INFO intent, system prompt has INFO Answer Contract, tool policy says min 1 call.
    """

    def test_intent_classification(self):
        result = classify_intent("How many orders yesterday?")
        assert result.primary.intent == Intent.INFO

    def test_mode_mapping(self):
        result = classify_intent("How many orders yesterday?")
        mode_config = mode_from_intent(result)
        assert mode_config.mode.value == "ask"

    def test_answer_contract_injected(self):
        result = classify_intent("How many orders yesterday?")
        contract = build_answer_contract(result)
        assert "INFO" in contract
        assert "answer" in contract.lower()

    def test_tool_policy(self):
        """Tool policy should specify minimum 1 tool call."""
        result = classify_intent("How many orders yesterday?")
        # Simulate what llm.py does
        from copilot.llm import CopilotLLM
        llm = CopilotLLM.__new__(CopilotLLM)  # Skip __init__
        policy = llm._build_tool_policy(result)
        assert "Minimum: 1" in policy
        assert "Maximum: 3" in policy


class TestDebugConversation:
    """
    Golden test: Pipeline failure investigation.
    User: "Dashboard numbers wrong today"
    Expected: DEBUG intent, system prompt has DEBUG Answer Contract, tool policy says min 2 calls.
    """

    def test_intent_classification(self):
        result = classify_intent("Dashboard numbers wrong today")
        assert result.primary.intent == Intent.DEBUG

    def test_answer_contract_has_debug_format(self):
        result = classify_intent("Dashboard numbers wrong today")
        contract = build_answer_contract(result)
        assert "Problem" in contract
        assert "Cause" in contract
        assert "Fix" in contract

    def test_tool_policy(self):
        result = classify_intent("Dashboard numbers wrong today")
        from copilot.llm import CopilotLLM
        llm = CopilotLLM.__new__(CopilotLLM)
        policy = llm._build_tool_policy(result)
        assert "Minimum: 2" in policy


class TestPRPivotConversation:
    """
    Golden test: PR pivot scenario.
    User: "Create a PR to fix my Airflow DAG failure"
    Evidence: Airflow logs show `dbt run` failed on model X.
    Expected: Root cause is dbt; change plan targets dbt, not airflow.
    """

    def test_intent_has_airflow_target(self):
        result = classify_intent("Create a PR to fix my Airflow DAG failure")
        assert result.target_hint == "airflow"
        assert result.primary.intent in (Intent.PR, Intent.FIX)

    def test_root_cause_pivots_to_dbt(self):
        """Evidence shows dbt failing inside Airflow → owner is dbt."""
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
        intent = IntentResult(
            primary=ScoredIntent(intent=Intent.PR, score=0.9, evidence=["create a pr"]),
            target_hint="airflow",
        )
        decision = resolve_fix_owner(tool_results, intent)
        assert decision.owner_system == OwnerSystem.DBT
        assert decision.confidence >= 0.7

    def test_pivot_hint_message(self):
        """The hint should explicitly state to fix in dbt, not airflow."""
        decision = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.85,
            explanation="dbt command failing within Airflow task.",
        )
        hint = format_owner_hint(decision, target_hint="airflow")
        assert "dbt" in hint
        assert "airflow" in hint
        # Should tell LLM to create fix in dbt
        assert "fix in dbt" in hint.lower() or "Create the fix in dbt" in hint

    def test_answer_contract_includes_pivot(self):
        """Answer contract should mention the PR pivot."""
        owner = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.85,
            explanation="dbt command failing in Airflow",
        )
        intent = IntentResult(
            primary=ScoredIntent(intent=Intent.FIX, score=0.9, evidence=["fix"]),
            target_hint="airflow",
        )
        contract = build_answer_contract(intent, owner_decision=owner)
        assert "airflow" in contract.lower()
        assert "dbt" in contract.lower()


class TestUncertainOwnerConversation:
    """
    Golden test: Uncertain ownership scenario.
    Evidence is ambiguous → Copilot should suggest more evidence tools
    and (via prompt) ask ONE clarifying question.
    """

    def test_low_confidence_with_ambiguous_evidence(self):
        tool_results = [
            {
                "tool": "query_warehouse",
                "result": {"success": True, "data": {"rows": [{"count": 0}]}},
            },
        ]
        intent = IntentResult(
            primary=ScoredIntent(intent=Intent.DEBUG, score=0.8, evidence=["why"]),
        )
        decision = resolve_fix_owner(tool_results, intent)
        assert decision.confidence < 0.6
        assert len(decision.suggested_tools) > 0

    def test_hint_suggests_clarification(self):
        decision = OwnerDecision(
            owner_system=OwnerSystem.UNKNOWN,
            confidence=0.3,
            explanation="Could not determine root cause.",
            suggested_tools=["get_dbt_run_history", "get_fivetran_connector_status"],
        )
        hint = format_owner_hint(decision)
        assert "clarifying question" in hint.lower() or "Confidence is low" in hint
        assert "get_dbt_run_history" in hint

    def test_tool_policy_still_requires_evidence(self):
        """Even with uncertain owner, FIX policy should require evidence."""
        result = IntentResult(
            primary=ScoredIntent(intent=Intent.FIX, score=0.9, evidence=["fix"]),
        )
        from copilot.llm import CopilotLLM
        llm = CopilotLLM.__new__(CopilotLLM)
        policy = llm._build_tool_policy(result)
        assert "CRITICAL" in policy or "MUST" in policy
        assert "evidence" in policy.lower()


class TestModeFromIntent:
    """Test that intent→mode bridge preserves existing mode behavior."""

    def test_all_intents_produce_valid_modes(self):
        """Every intent should map to a valid mode with a system prompt section."""
        test_messages = {
            Intent.INFO: "how many rows?",
            Intent.DEBUG: "why did my pipeline fail?",
            Intent.FIX: "apply a fix for the broken model",
            Intent.PR: "create a PR for this change",
            Intent.PLAN: "how should I migrate?",
            Intent.EXPLAIN: "explain incremental models",
        }
        for intent_type, msg in test_messages.items():
            result = classify_intent(msg)
            config = mode_from_intent(result)
            assert config is not None
            assert config.system_prompt_section  # Non-empty prompt section
            assert config.display_name  # Has a display name

    def test_fix_mode_has_change_plan_tools(self):
        result = classify_intent("fix the broken model and create a PR")
        config = mode_from_intent(result)
        # FIX mode should have change plan tools
        all_tools = config.preferred_tools + config.exclusive_tools
        assert "create_change_plan" in all_tools or "validate_change_plan" in all_tools
