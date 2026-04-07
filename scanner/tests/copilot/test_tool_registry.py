"""Tests for the refactored tool registry."""

import pytest
from copilot.tools.base import Tool, ToolParameter, ToolResult, ToolCategory


class TestBaseDataclasses:
    """Verify dataclasses are importable and functional."""

    def test_tool_category_has_expected_values(self):
        assert ToolCategory.LINEAGE.value == "lineage"
        assert ToolCategory.WAREHOUSE.value == "warehouse"
        assert ToolCategory.DBT.value == "dbt"
        assert ToolCategory.ORCHESTRATION.value == "orchestration"

    def test_tool_parameter_creation(self):
        param = ToolParameter("node_id", "string", "The node ID")
        assert param.name == "node_id"
        assert param.type == "string"
        assert param.required is True

    def test_tool_creation(self):
        tool = Tool(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.LINEAGE,
            parameters=[ToolParameter("id", "string", "ID")],
        )
        assert tool.name == "test_tool"
        assert tool.category == ToolCategory.LINEAGE
        assert len(tool.parameters) == 1

    def test_tool_availability_with_required_integrations(self):
        tool = Tool(
            name="t",
            description="d",
            category=ToolCategory.DBT,
            required_integrations={"DBT_CLOUD"},
        )
        assert tool.is_available({"DBT_CLOUD", "BIGQUERY"}) is True
        assert tool.is_available({"BIGQUERY"}) is False

    def test_tool_availability_with_alternative_integrations(self):
        tool = Tool(
            name="t",
            description="d",
            category=ToolCategory.WAREHOUSE,
            alternative_integrations={"SNOWFLAKE", "BIGQUERY"},
        )
        assert tool.is_available({"BIGQUERY"}) is True
        assert tool.is_available({"POSTGRES"}) is False

    def test_tool_to_anthropic_tool(self):
        tool = Tool(
            name="query_warehouse",
            description="Run SQL",
            category=ToolCategory.WAREHOUSE,
            parameters=[
                ToolParameter("sql", "string", "The SQL query"),
                ToolParameter("limit", "integer", "Max rows", required=False, default=100),
            ],
        )
        result = tool.to_anthropic_tool()
        assert result["name"] == "query_warehouse"
        assert "sql" in result["input_schema"]["properties"]
        assert "sql" in result["input_schema"]["required"]
        assert "limit" not in result["input_schema"]["required"]

    def test_tool_to_openai_tool(self):
        tool = Tool(
            name="query_warehouse",
            description="Run SQL",
            category=ToolCategory.WAREHOUSE,
            parameters=[ToolParameter("sql", "string", "The SQL query")],
        )
        result = tool.to_openai_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "query_warehouse"

    def test_tool_result(self):
        result = ToolResult(success=True, data={"count": 42})
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"]["count"] == 42
