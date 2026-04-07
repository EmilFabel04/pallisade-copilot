"""Tests for the refactored tool registry."""

import pytest
from copilot.tools.base import Tool, ToolParameter, ToolResult, ToolCategory
from copilot.tools.registry import register_tool, ToolRegistry, _GLOBAL_REGISTRY


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


class TestRegisterToolDecorator:
    """Test the @register_tool decorator."""

    def setup_method(self):
        """Clear global registry before each test."""
        _GLOBAL_REGISTRY.clear()

    def test_register_tool_adds_to_global_registry(self):
        @register_tool(
            name="test_tool_1",
            description="A test tool",
            category=ToolCategory.LINEAGE,
        )
        def _meta():
            pass

        assert "test_tool_1" in _GLOBAL_REGISTRY
        assert _GLOBAL_REGISTRY["test_tool_1"].name == "test_tool_1"
        assert _GLOBAL_REGISTRY["test_tool_1"].category == ToolCategory.LINEAGE

    def test_register_tool_with_parameters(self):
        @register_tool(
            name="test_tool_2",
            description="Tool with params",
            category=ToolCategory.WAREHOUSE,
            parameters=[
                ToolParameter("sql", "string", "The SQL query"),
                ToolParameter("limit", "integer", "Max rows", required=False),
            ],
            alternative_integrations={"BIGQUERY", "SNOWFLAKE"},
        )
        def _meta():
            pass

        tool = _GLOBAL_REGISTRY["test_tool_2"]
        assert len(tool.parameters) == 2
        assert tool.alternative_integrations == {"BIGQUERY", "SNOWFLAKE"}

    def test_register_tool_with_confirmation(self):
        @register_tool(
            name="test_tool_3",
            description="Destructive tool",
            category=ToolCategory.CHANGE_PLAN,
            requires_confirmation=True,
        )
        def _meta():
            pass

        assert _GLOBAL_REGISTRY["test_tool_3"].requires_confirmation is True

    def test_duplicate_registration_raises(self):
        @register_tool(name="dup", description="d", category=ToolCategory.LINEAGE)
        def _meta():
            pass

        with pytest.raises(ValueError, match="already registered"):
            @register_tool(name="dup", description="d2", category=ToolCategory.LINEAGE)
            def _meta2():
                pass


class TestToolRegistryFromGlobal:
    """Test ToolRegistry loading from global registry."""

    def setup_method(self):
        _GLOBAL_REGISTRY.clear()

    def test_load_from_global_registry(self):
        @register_tool(name="tool_a", description="A", category=ToolCategory.LINEAGE)
        def _a():
            pass

        @register_tool(name="tool_b", description="B", category=ToolCategory.WAREHOUSE,
                       alternative_integrations={"BIGQUERY"})
        def _b():
            pass

        registry = ToolRegistry()
        assert registry.get_tool("tool_a") is not None
        assert registry.get_tool("tool_b") is not None
        assert len(registry.get_all_tools()) == 2

    def test_get_available_tools_filters(self):
        @register_tool(name="bq_tool", description="BQ", category=ToolCategory.WAREHOUSE,
                       required_integrations={"BIGQUERY"})
        def _bq():
            pass

        @register_tool(name="any_tool", description="Any", category=ToolCategory.LINEAGE)
        def _any():
            pass

        registry = ToolRegistry()
        available = registry.get_available_tools({"SNOWFLAKE"})
        names = [t.name for t in available]
        assert "any_tool" in names
        assert "bq_tool" not in names

    def test_to_anthropic_tools(self):
        @register_tool(name="t1", description="D1", category=ToolCategory.LINEAGE)
        def _t1():
            pass

        registry = ToolRegistry()
        tools = registry.to_anthropic_tools(set())
        assert len(tools) == 1
        assert tools[0]["name"] == "t1"

    def test_to_openai_tools(self):
        @register_tool(name="t1", description="D1", category=ToolCategory.LINEAGE)
        def _t1():
            pass

        registry = ToolRegistry()
        tools = registry.to_openai_tools(set())
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "t1"

    def test_merge_mcp_tools(self):
        static = [{"name": "t1"}]
        mcp = [{"name": "mcp_airflow__get_dags"}]
        merged = ToolRegistry.merge_mcp_tools(static, mcp)
        assert len(merged) == 2

    def test_get_tools_by_category(self):
        @register_tool(name="lin", description="L", category=ToolCategory.LINEAGE)
        def _l():
            pass

        @register_tool(name="wh", description="W", category=ToolCategory.WAREHOUSE,
                       alternative_integrations={"BIGQUERY"})
        def _w():
            pass

        registry = ToolRegistry()
        lineage_tools = registry.get_tools_by_category(ToolCategory.LINEAGE)
        assert len(lineage_tools) == 1
        assert lineage_tools[0].name == "lin"
