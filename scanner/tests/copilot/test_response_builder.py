"""Tests for the response builder / Answer Contract."""

import pytest
from copilot.intent import Intent, ScoredIntent, IntentResult
from copilot.root_cause import OwnerDecision, OwnerSystem
from copilot.response_builder import build_answer_contract


def _make_intent(primary_intent: Intent, secondary_intent: Intent = None, target_hint=None):
    """Helper to create an IntentResult."""
    primary = ScoredIntent(intent=primary_intent, score=0.9, evidence=["test"])
    secondary = None
    if secondary_intent:
        secondary = ScoredIntent(intent=secondary_intent, score=0.7, evidence=["test"])
    return IntentResult(
        primary=primary,
        secondary=secondary,
        target_hint=target_hint,
    )


class TestBuildAnswerContract:
    """Unit tests for build_answer_contract()."""

    # --- INFO ---

    def test_info_contract_structure(self):
        contract = build_answer_contract(_make_intent(Intent.INFO))
        assert "Answer Contract" in contract
        assert "Lead with the answer" in contract

    def test_info_contract_direct_answer(self):
        contract = build_answer_contract(_make_intent(Intent.INFO))
        assert "answer" in contract.lower()

    def test_info_contract_source(self):
        contract = build_answer_contract(_make_intent(Intent.INFO))
        assert "source" in contract.lower() or "table" in contract.lower()

    # --- DEBUG ---

    def test_debug_contract_structure(self):
        contract = build_answer_contract(_make_intent(Intent.DEBUG))
        assert "Problem" in contract
        assert "Cause" in contract
        assert "Fix" in contract

    def test_debug_contract_evidence(self):
        contract = build_answer_contract(_make_intent(Intent.DEBUG))
        assert "evidence" in contract.lower()

    def test_debug_contract_scannable(self):
        contract = build_answer_contract(_make_intent(Intent.DEBUG))
        assert "short" in contract.lower() or "scannable" in contract.lower()

    # --- FIX/PR ---

    def test_fix_contract_change_plan(self):
        contract = build_answer_contract(_make_intent(Intent.FIX))
        assert "change_plan" in contract.lower() or "create_change_plan" in contract

    def test_fix_contract_evidence_required(self):
        contract = build_answer_contract(_make_intent(Intent.FIX))
        assert "evidence" in contract.lower() or "diagnostic" in contract.lower()

    def test_fix_contract_validation(self):
        contract = build_answer_contract(_make_intent(Intent.FIX))
        assert "validate" in contract.lower()

    def test_pr_contract_same_as_fix(self):
        fix_contract = build_answer_contract(_make_intent(Intent.FIX))
        pr_contract = build_answer_contract(_make_intent(Intent.PR))
        # Both should mention change plan
        assert "change_plan" in fix_contract.lower() or "create_change_plan" in fix_contract
        assert "change_plan" in pr_contract.lower() or "create_change_plan" in pr_contract

    # --- FIX with owner decision ---

    def test_fix_with_owner(self):
        owner = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.9,
            explanation="dbt compilation error",
        )
        contract = build_answer_contract(_make_intent(Intent.FIX), owner_decision=owner)
        assert "dbt" in contract.lower()

    def test_fix_with_pivot(self):
        """When user said airflow but root cause is dbt."""
        owner = OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.9,
            explanation="dbt command failing in Airflow",
        )
        contract = build_answer_contract(
            _make_intent(Intent.FIX, target_hint="airflow"),
            owner_decision=owner,
        )
        assert "airflow" in contract.lower()
        assert "dbt" in contract.lower()
        assert "pivot" in contract.lower() or "Pivot" in contract

    # --- PLAN ---

    def test_plan_contract_lineage(self):
        contract = build_answer_contract(_make_intent(Intent.PLAN))
        assert "lineage" in contract.lower() or "get_downstream" in contract or "get_upstream" in contract

    def test_plan_contract_impact(self):
        contract = build_answer_contract(_make_intent(Intent.PLAN))
        assert "impact" in contract.lower()

    # --- EXPLAIN ---

    def test_explain_contract_progressive(self):
        contract = build_answer_contract(_make_intent(Intent.EXPLAIN))
        assert "summary" in contract.lower() or "high-level" in contract.lower()

    def test_explain_contract_examples(self):
        contract = build_answer_contract(_make_intent(Intent.EXPLAIN))
        assert "example" in contract.lower()

    # --- Multi-intent ---

    def test_debug_fix_multi_intent(self):
        contract = build_answer_contract(
            _make_intent(Intent.DEBUG, secondary_intent=Intent.FIX)
        )
        assert "DEBUG + FIX" in contract or "Diagnose" in contract or "diagnosis" in contract.lower()
        assert "Problem" in contract or "Cause" in contract
        assert "Fix" in contract or "apply_change_plan" in contract

    def test_debug_pr_multi_intent(self):
        contract = build_answer_contract(
            _make_intent(Intent.DEBUG, secondary_intent=Intent.PR)
        )
        assert "DEBUG + FIX" in contract or "Diagnose" in contract or "diagnosis" in contract.lower()

    def test_fix_debug_multi_intent(self):
        """When FIX is primary and DEBUG is secondary."""
        contract = build_answer_contract(
            _make_intent(Intent.FIX, secondary_intent=Intent.DEBUG)
        )
        # Should still get the combined contract
        assert "Diagnose" in contract or "evidence" in contract.lower() or "diagnosis" in contract.lower()
