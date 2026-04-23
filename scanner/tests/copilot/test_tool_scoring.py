"""Tests for intent-aware tool relevance scoring."""

import pytest
from copilot.tools.base import Tool, ToolParameter, ToolCategory
from copilot.tools.registry import score_tool_relevance, build_tool_recommendations
from copilot.intent import Intent, IntentResult, ScoredIntent


class TestScoreToolRelevance:
    """Test the scoring function."""

    def _make_intent(self, intent: Intent, target_hint: str = None) -> IntentResult:
        return IntentResult(
            primary=ScoredIntent(intent=intent, score=0.9),
            target_hint=target_hint,
        )

    def test_query_token_match_on_name(self):
        tool = Tool(name="get_dag_run_history", description="Get DAG runs", category=ToolCategory.ORCHESTRATION)
        intent = self._make_intent(Intent.INFO)
        score = score_tool_relevance(tool, {"dag", "run", "history"}, intent)
        assert score >= 15

    def test_query_token_match_on_description(self):
        tool = Tool(name="get_upstream", description="Get all upstream dependencies including tables and models", category=ToolCategory.LINEAGE)
        intent = self._make_intent(Intent.INFO)
        score = score_tool_relevance(tool, {"dependencies"}, intent)
        assert score >= 2

    def test_category_token_match(self):
        tool = Tool(name="get_dbt_model", description="Get dbt model details", category=ToolCategory.DBT)
        intent = self._make_intent(Intent.INFO)
        score = score_tool_relevance(tool, {"dbt"}, intent)
        assert score >= 8

    def test_intent_boost_debug(self):
        tool = Tool(name="get_dag_run_history", description="Get DAG runs", category=ToolCategory.ORCHESTRATION)
        intent = self._make_intent(Intent.DEBUG)
        score = score_tool_relevance(tool, set(), intent)
        assert score >= 10

    def test_intent_boost_fix(self):
        tool = Tool(name="create_change_plan", description="Create a plan", category=ToolCategory.CHANGE_PLAN)
        intent = self._make_intent(Intent.FIX)
        score = score_tool_relevance(tool, set(), intent)
        assert score >= 10

    def test_target_hint_boost(self):
        tool = Tool(name="get_dag_run_history", description="Get DAG runs", category=ToolCategory.ORCHESTRATION)
        intent = self._make_intent(Intent.DEBUG, target_hint="airflow")
        score_with_hint = score_tool_relevance(tool, set(), intent)

        intent_no_hint = self._make_intent(Intent.DEBUG)
        score_without_hint = score_tool_relevance(tool, set(), intent_no_hint)

        assert score_with_hint > score_without_hint
        assert score_with_hint - score_without_hint == 5

    def test_no_match_returns_zero(self):
        tool = Tool(name="get_powerbi_gateway_status", description="Power BI gateway", category=ToolCategory.REPORTING)
        intent = self._make_intent(Intent.INFO)
        score = score_tool_relevance(tool, {"airflow", "dag"}, intent)
        assert score == 0

    def test_debug_query_about_dag_ranks_orchestration_highest(self):
        tools = [
            Tool(name="get_dag_run_history", description="Get recent DAG run history", category=ToolCategory.ORCHESTRATION),
            Tool(name="query_warehouse", description="Execute SQL query", category=ToolCategory.WAREHOUSE),
            Tool(name="get_upstream", description="Get upstream dependencies", category=ToolCategory.LINEAGE),
            Tool(name="get_dbt_model", description="Get dbt model details", category=ToolCategory.DBT),
        ]
        intent = self._make_intent(Intent.DEBUG, target_hint="airflow")
        query_tokens = {"dag", "fail"}

        scores = [(t.name, score_tool_relevance(t, query_tokens, intent)) for t in tools]
        scores.sort(key=lambda x: x[1], reverse=True)
        assert scores[0][0] == "get_dag_run_history"

    def test_info_query_about_orders_ranks_warehouse_highest(self):
        tools = [
            Tool(name="query_warehouse", description="Execute SQL query against warehouse", category=ToolCategory.WAREHOUSE),
            Tool(name="get_upstream", description="Get upstream dependencies", category=ToolCategory.LINEAGE),
            Tool(name="get_dag_run_history", description="Get DAG runs", category=ToolCategory.ORCHESTRATION),
        ]
        intent = self._make_intent(Intent.INFO)
        query_tokens = {"orders"}

        scores = [(t.name, score_tool_relevance(t, query_tokens, intent)) for t in tools]
        scores.sort(key=lambda x: x[1], reverse=True)
        assert scores[0][0] == "query_warehouse"


class TestBuildToolRecommendations:
    """Test the recommendation string builder."""

    def _make_intent(self, intent: Intent, target_hint: str = None) -> IntentResult:
        return IntentResult(
            primary=ScoredIntent(intent=intent, score=0.9),
            target_hint=target_hint,
        )

    def test_returns_markdown_section(self):
        tools = [
            Tool(name="query_warehouse", description="Run SQL", category=ToolCategory.WAREHOUSE),
            Tool(name="get_upstream", description="Get upstream deps", category=ToolCategory.LINEAGE),
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "how many orders", intent)
        assert "## Recommended Tools" in result
        assert "`query_warehouse`" in result

    def test_respects_top_n(self):
        tools = [
            Tool(name=f"tool_{i}", description=f"Tool {i}", category=ToolCategory.LINEAGE)
            for i in range(10)
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "lineage", intent, top_n=3)
        numbered_lines = [l for l in result.split("\n") if l.strip() and l.strip()[0].isdigit() and "." in l[:3]]
        assert len(numbered_lines) <= 3

    def test_omits_zero_score_tools_from_ranked_list(self):
        tools = [
            Tool(name="query_warehouse", description="Run SQL", category=ToolCategory.WAREHOUSE),
            Tool(name="get_powerbi_gateway_status", description="Power BI gateway", category=ToolCategory.REPORTING),
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "how many orders in bigquery", intent)
        assert "`get_powerbi_gateway_status`" not in result.split("All tools remain available")[0]

    def test_includes_other_tools_note(self):
        tools = [
            Tool(name="query_warehouse", description="Run SQL", category=ToolCategory.WAREHOUSE),
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "orders", intent)
        assert "All tools remain available" in result

    def test_returns_empty_when_no_scores(self):
        tools = [
            Tool(name="get_powerbi_gateway_status", description="Power BI gateway", category=ToolCategory.REPORTING),
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "dag failure", intent)
        assert result == ""
