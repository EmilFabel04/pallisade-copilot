"""Tests for the multi-intent classifier."""

import pytest
from copilot.intent import classify_intent, Intent, IntentResult


class TestClassifyIntent:
    """Unit tests for classify_intent()."""

    # --- INFO intent ---

    def test_simple_info_question(self):
        result = classify_intent("how many orders do I have?")
        assert result.primary.intent == Intent.INFO
        assert result.primary.score >= 0.2

    def test_info_count_question(self):
        result = classify_intent("what is the total revenue for last month?")
        assert result.primary.intent == Intent.INFO

    def test_info_show_me(self):
        result = classify_intent("show me the top 10 customers")
        assert result.primary.intent == Intent.INFO

    def test_info_list(self):
        result = classify_intent("list all tables in my warehouse")
        assert result.primary.intent == Intent.INFO

    # --- DEBUG intent ---

    def test_debug_failure(self):
        result = classify_intent("why did my daily_etl DAG fail last night?")
        assert result.primary.intent == Intent.DEBUG
        assert result.target_hint == "airflow"

    def test_debug_broken(self):
        result = classify_intent("my pipeline is broken")
        assert result.primary.intent == Intent.DEBUG

    def test_debug_why_question(self):
        result = classify_intent("why are the numbers wrong today?")
        assert result.primary.intent == Intent.DEBUG

    def test_debug_error(self):
        result = classify_intent("there's an error in the orders model")
        assert result.primary.intent == Intent.DEBUG

    def test_debug_anomaly(self):
        result = classify_intent("I see an anomaly in the revenue data")
        assert result.primary.intent == Intent.DEBUG

    def test_debug_stale(self):
        result = classify_intent("the dashboard data looks stale")
        assert result.primary.intent == Intent.DEBUG

    # --- FIX intent ---

    def test_fix_intent(self):
        result = classify_intent("fix the broken dbt model")
        assert result.primary.intent in (Intent.FIX, Intent.DEBUG)

    def test_fix_apply(self):
        result = classify_intent("apply a fix for the schema drift issue")
        assert result.primary.intent == Intent.FIX

    def test_fix_generate(self):
        result = classify_intent("generate a fix for the failing test")
        assert result.primary.intent == Intent.FIX

    # --- PR intent ---

    def test_pr_create(self):
        result = classify_intent("create a PR to fix the orders model")
        assert result.primary.intent == Intent.PR

    def test_pr_open(self):
        result = classify_intent("open a pull request for this change")
        assert result.primary.intent == Intent.PR

    # --- PLAN intent ---

    def test_plan_migrate(self):
        result = classify_intent("how should I migrate from BigQuery to Snowflake?")
        assert result.primary.intent == Intent.PLAN

    def test_plan_refactor(self):
        result = classify_intent("plan for refactoring the staging models")
        assert result.primary.intent == Intent.PLAN

    def test_plan_strategy(self):
        result = classify_intent("what's the best approach for restructuring the DAGs?")
        assert result.primary.intent == Intent.PLAN

    # --- EXPLAIN intent ---

    def test_explain(self):
        result = classify_intent("explain how incremental models work in dbt")
        assert result.primary.intent == Intent.EXPLAIN

    def test_explain_teach(self):
        result = classify_intent("teach me about data lineage")
        assert result.primary.intent == Intent.EXPLAIN

    def test_explain_how_does(self):
        result = classify_intent("how does Snowflake handle clustering?")
        assert result.primary.intent == Intent.EXPLAIN

    # --- Multi-intent ---

    def test_multi_intent_debug_and_fix(self):
        result = classify_intent("my pipeline is broken, can you fix it and open a PR?")
        # Should detect both DEBUG and FIX/PR
        intents = {result.primary.intent}
        if result.secondary:
            intents.add(result.secondary.intent)
        assert intents & {Intent.DEBUG, Intent.FIX, Intent.PR}

    def test_multi_intent_debug_and_pr(self):
        result = classify_intent("why is the DAG failing? create a PR to fix it")
        intents = {result.primary.intent}
        if result.secondary:
            intents.add(result.secondary.intent)
        assert Intent.DEBUG in intents or Intent.PR in intents

    # --- History-based intent ---

    def test_pr_from_history(self):
        history = [
            {"role": "user", "content": "why is my pipeline failing?"},
            {"role": "assistant", "content": "The root cause is a schema change in the orders table..."},
        ]
        result = classify_intent("go ahead and fix it", history)
        assert result.primary.intent in (Intent.PR, Intent.FIX)

    def test_proceed_from_history(self):
        history = [
            {"role": "user", "content": "what went wrong with the dbt run?"},
            {"role": "assistant", "content": "The model stg_orders has a compilation error..."},
        ]
        result = classify_intent("proceed", history)
        assert result.primary.intent in (Intent.PR, Intent.FIX)

    # --- Target hint extraction ---

    def test_target_hint_airflow(self):
        result = classify_intent("why did my Airflow DAG fail?")
        assert result.target_hint == "airflow"

    def test_target_hint_dbt(self):
        result = classify_intent("check my dbt model for errors")
        assert result.target_hint == "dbt"

    def test_target_hint_fivetran(self):
        result = classify_intent("is my fivetran connector syncing properly?")
        assert result.target_hint == "fivetran"

    def test_target_hint_snowflake(self):
        result = classify_intent("query my snowflake warehouse")
        assert result.target_hint == "snowflake"

    def test_target_hint_none(self):
        result = classify_intent("how many orders yesterday?")
        assert result.target_hint is None

    # --- Target entity extraction ---

    def test_target_entities_fqn(self):
        result = classify_intent("check the project.raw.orders table")
        assert any("project.raw.orders" in e for e in result.target_entities)

    def test_target_entities_backtick(self):
        result = classify_intent("query `analytics.customers`")
        assert any("analytics.customers" in e for e in result.target_entities)

    def test_target_entities_named_table(self):
        result = classify_intent("look at the orders table")
        assert any("orders" in e for e in result.target_entities)

    # --- Edge cases ---

    def test_empty_message(self):
        result = classify_intent("")
        assert result.primary.intent == Intent.INFO  # fallback
        assert result.primary.score <= 0.5

    def test_ambiguous_message(self):
        result = classify_intent("hello")
        assert result.primary is not None  # should not crash

    def test_fallback_to_info(self):
        result = classify_intent("what time is it?")
        # Not a strong match for any intent, should fall back
        assert result.primary is not None

    # --- IntentResult structure ---

    def test_result_has_raw_scores(self):
        result = classify_intent("why did my DAG fail?")
        assert Intent.DEBUG in result.raw_scores
        assert Intent.INFO in result.raw_scores

    def test_result_evidence_populated(self):
        result = classify_intent("fix the broken model")
        assert len(result.primary.evidence) > 0


class TestIntentToMode:
    """Test the intent-to-mode bridge."""

    def test_info_maps_to_ask(self):
        from copilot.intent import intent_to_mode
        result = classify_intent("how many orders?")
        assert intent_to_mode(result) == "ask"

    def test_debug_maps_to_debug(self):
        from copilot.intent import intent_to_mode
        result = classify_intent("why did my pipeline fail?")
        assert intent_to_mode(result) == "debug"

    def test_fix_maps_to_fix(self):
        from copilot.intent import intent_to_mode
        result = classify_intent("apply a fix for the failing test")
        assert intent_to_mode(result) == "fix"

    def test_plan_maps_to_plan(self):
        from copilot.intent import intent_to_mode
        result = classify_intent("how should I migrate to Snowflake?")
        assert intent_to_mode(result) == "plan"

    def test_explain_maps_to_explain(self):
        from copilot.intent import intent_to_mode
        result = classify_intent("explain incremental models")
        assert intent_to_mode(result) == "explain"
