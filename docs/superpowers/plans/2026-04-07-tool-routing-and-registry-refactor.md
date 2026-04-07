# Tool Pre-Routing & Registry Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve copilot tool selection accuracy by splitting the monolithic tool registry into decorator-based category files and adding intent-aware tool relevance scoring that injects dynamic recommendations into the system prompt.

**Architecture:** The monolithic `tools.py` becomes a `tools/` package. Each category (lineage, warehouse, dbt, etc.) gets its own file with `@register_tool` decorators. A new `score_tool_relevance()` function scores tools against user query + classified intent, and `build_tool_recommendations()` formats the top-scored tools into a system prompt section that replaces the hardcoded `preferred_tools` line.

**Tech Stack:** Python 3.14, dataclasses, pytest

---

## File Structure

```
scanner/copilot/tools/          # NEW package (replaces scanner/copilot/tools.py)
  __init__.py                   # Re-exports: Tool, ToolParameter, ToolResult, ToolCategory, ToolRegistry, get_tool_registry
  base.py                       # Tool, ToolParameter, ToolResult, ToolCategory (moved from tools.py)
  registry.py                   # _GLOBAL_REGISTRY, @register_tool, ToolRegistry, score_tool_relevance, build_tool_recommendations
  lineage.py                    # 8 tools: get_upstream, get_downstream, get_node_details, search_lineage, get_column_lineage, analyze_change_impact, explain_edge, get_lineage_stats
  warehouse.py                  # 4 tools: query_warehouse, get_table_stats, get_query_history, get_table_dependencies
  dbt.py                        # 4 tools: get_dbt_model, get_dbt_run_history, get_dbt_test_results, get_dbt_lineage
  orchestration.py              # 10 tools: get_asset_orchestration_context, get_dag_run_history, get_dagster_*, get_prefect_*, get_n8n_*
  ingestion.py                  # 5 tools: get_fivetran_*, get_airbyte_*
  reporting.py                  # 10 tools: get_looker_*, get_tableau_*, get_powerbi_*, get_metabase_*
  storage.py                    # 3 tools: list_storage_objects, get_storage_object_metadata, list_storage_buckets
  knowledge.py                  # 1 tool: search_knowledge_base
  observability.py              # 5 tools: get_active_incidents, get_asset_quality, trace_incident_root_cause, get_quality_checks, get_incident_details
  coverage.py                   # 6 tools: get_coverage_report, get_coverage_gaps, get_node_coverage, get_monitor_recommendations, run_coverage_monitor, create_watch, run_watch
  actions.py                    # 5 tools: create_change_plan, validate_change_plan, get_change_plan, apply_change_plan, list_change_plans
  github.py                     # 3 tools: list_github_repos, get_github_tree, get_github_file
  onboarding.py                 # 3 tools: get_pending_questions, save_onboarding_context, complete_onboarding
  infrastructure.py             # 6 tools: check_server_health, check_certificates, analyze_server_logs, list_server_services, check_integration_health, list_integration_assets, get_integration_capabilities

scanner/copilot/llm.py          # MODIFY: replace preferred_tools injection with build_tool_recommendations()

scanner/tests/copilot/test_tool_registry.py     # NEW: registry completeness tests
scanner/tests/copilot/test_tool_scoring.py      # NEW: scoring + recommendation tests
```

---

### Task 1: Create base.py — Move Dataclasses Out of tools.py

**Files:**
- Create: `scanner/copilot/tools/base.py`
- Test: `scanner/tests/copilot/test_tool_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# scanner/tests/copilot/test_tool_registry.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'copilot.tools.base'`

- [ ] **Step 3: Create the tools/ package directory**

```bash
mkdir -p scanner/copilot/tools
```

- [ ] **Step 4: Write base.py**

Copy lines 1-158 from `scanner/copilot/tools.py` into `scanner/copilot/tools/base.py`. The file should contain exactly:

```python
"""
Co-Pilot Tool Base Types

Dataclasses for tool definitions, parameters, results, and categories.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum


class ToolCategory(Enum):
    """Categories of tools."""
    LINEAGE = "lineage"
    WAREHOUSE = "warehouse"
    DBT = "dbt"
    ORCHESTRATION = "orchestration"
    INGESTION = "ingestion"
    REPORTING = "reporting"
    STORAGE = "storage"
    KNOWLEDGE = "knowledge"
    OBSERVABILITY = "observability"
    COVERAGE = "coverage"
    POLICY = "policy"
    CHANGE_PLAN = "change_plan"
    ONBOARDING = "onboarding"
    INFRASTRUCTURE = "infrastructure"


@dataclass
class ToolParameter:
    """A parameter for a tool."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None
    items: Optional[Dict[str, Any]] = None


@dataclass
class Tool:
    """
    Definition of a tool available to the co-pilot.

    Tools map to specific functionality in the integration adapters.
    """
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)
    required_integrations: Set[str] = field(default_factory=set)
    alternative_integrations: Set[str] = field(default_factory=set)
    requires_confirmation: bool = False

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Convert to Anthropic tool format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.type == "array" and param.items:
                prop["items"] = param.items
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }

    def to_openai_tool(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.type == "array" and param.items:
                prop["items"] = param.items
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }

    def is_available(self, user_integrations: Set[str]) -> bool:
        """Check if this tool is available for the user's integrations."""
        upper_user = {u.upper() for u in user_integrations}

        if self.required_integrations:
            upper_req = {r.upper() for r in self.required_integrations}
            if not upper_req.issubset(upper_user):
                return False

        if self.alternative_integrations:
            upper_alt = {a.upper() for a in self.alternative_integrations}
            if not upper_alt & upper_user:
                return False

        return True


@dataclass
class ToolResult:
    """Result of executing a tool."""
    success: bool
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/tools/base.py scanner/tests/copilot/test_tool_registry.py
git commit -m "refactor: extract tool base types into copilot/tools/base.py"
```

---

### Task 2: Create registry.py — @register_tool Decorator and ToolRegistry

**Files:**
- Create: `scanner/copilot/tools/registry.py`
- Modify: `scanner/tests/copilot/test_tool_registry.py`

- [ ] **Step 1: Write the failing tests**

Append to `scanner/tests/copilot/test_tool_registry.py`:

```python
from copilot.tools.registry import register_tool, ToolRegistry, _GLOBAL_REGISTRY


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py::TestRegisterToolDecorator -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'copilot.tools.registry'`

- [ ] **Step 3: Write registry.py**

```python
"""
Co-Pilot Tool Registry

Decorator-based tool registration and ToolRegistry class.
"""

from typing import Dict, List, Optional, Set, Any
from .base import Tool, ToolParameter, ToolResult, ToolCategory

# Global registry populated by @register_tool at import time
_GLOBAL_REGISTRY: Dict[str, Tool] = {}


def register_tool(
    name: str,
    description: str,
    category: ToolCategory,
    parameters: Optional[List[ToolParameter]] = None,
    required_integrations: Optional[Set[str]] = None,
    alternative_integrations: Optional[Set[str]] = None,
    requires_confirmation: bool = False,
):
    """
    Decorator that registers a tool in the global registry.

    The decorated function is a no-op marker — execution is handled
    by ToolExecutor._execute_<name>() methods.
    """
    def decorator(fn):
        if name in _GLOBAL_REGISTRY:
            raise ValueError(f"Tool '{name}' already registered")
        _GLOBAL_REGISTRY[name] = Tool(
            name=name,
            description=description,
            category=category,
            parameters=parameters or [],
            required_integrations=required_integrations or set(),
            alternative_integrations=alternative_integrations or set(),
            requires_confirmation=requires_confirmation,
        )
        return fn
    return decorator


class ToolRegistry:
    """
    Registry of all available tools.

    Tools are organized by category and filtered based on
    what integrations the user has connected.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._load_from_global_registry()

    def _load_from_global_registry(self):
        """Import category modules to trigger decorators, then copy registry."""
        from scanner.copilot.tools import (
            lineage, warehouse, dbt, orchestration, ingestion,
            reporting, storage, knowledge, observability, coverage,
            actions, github, onboarding, infrastructure,
        )
        self._tools = dict(_GLOBAL_REGISTRY)

    def _register(self, tool: Tool) -> None:
        """Register a tool directly (for backward compatibility)."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_available_tools(self, user_integrations: Set[str]) -> List[Tool]:
        """Get tools available for the user's integrations."""
        return [
            tool for tool in self._tools.values()
            if tool.is_available(user_integrations)
        ]

    def get_tools_by_category(self, category: ToolCategory) -> List[Tool]:
        """Get all tools in a category."""
        return [
            tool for tool in self._tools.values()
            if tool.category == category
        ]

    def to_anthropic_tools(self, user_integrations: Set[str]) -> List[Dict[str, Any]]:
        """Convert available tools to Anthropic format."""
        available = self.get_available_tools(user_integrations)
        return [tool.to_anthropic_tool() for tool in available]

    def to_openai_tools(self, user_integrations: Set[str]) -> List[Dict[str, Any]]:
        """Convert available tools to OpenAI format."""
        available = self.get_available_tools(user_integrations)
        return [tool.to_openai_tool() for tool in available]

    @staticmethod
    def merge_mcp_tools(
        static_tools: List[Dict[str, Any]],
        mcp_tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge MCP-discovered tools with static registry tools."""
        return static_tools + mcp_tools
```

Note: The `_load_from_global_registry` method imports category modules. For tests that manipulate `_GLOBAL_REGISTRY` directly, we bypass this by constructing `ToolRegistry` after populating the global registry in the test. The actual category module imports will be wired in Task 3.

For tests to pass at this stage, temporarily make `_load_from_global_registry` handle missing modules gracefully:

```python
    def _load_from_global_registry(self):
        """Import category modules to trigger decorators, then copy registry."""
        try:
            from scanner.copilot.tools import (
                lineage, warehouse, dbt, orchestration, ingestion,
                reporting, storage, knowledge, observability, coverage,
                actions, github, onboarding, infrastructure,
            )
        except ImportError:
            pass  # Category modules not yet created; tests populate _GLOBAL_REGISTRY directly
        self._tools = dict(_GLOBAL_REGISTRY)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tools/registry.py scanner/tests/copilot/test_tool_registry.py
git commit -m "feat: add @register_tool decorator and ToolRegistry in registry.py"
```

---

### Task 3: Create Category Modules — Move All Tool Definitions

**Files:**
- Create: `scanner/copilot/tools/lineage.py`
- Create: `scanner/copilot/tools/warehouse.py`
- Create: `scanner/copilot/tools/dbt.py`
- Create: `scanner/copilot/tools/orchestration.py`
- Create: `scanner/copilot/tools/ingestion.py`
- Create: `scanner/copilot/tools/reporting.py`
- Create: `scanner/copilot/tools/storage.py`
- Create: `scanner/copilot/tools/knowledge.py`
- Create: `scanner/copilot/tools/observability.py`
- Create: `scanner/copilot/tools/coverage.py`
- Create: `scanner/copilot/tools/actions.py`
- Create: `scanner/copilot/tools/github.py`
- Create: `scanner/copilot/tools/onboarding.py`
- Create: `scanner/copilot/tools/infrastructure.py`
- Modify: `scanner/tests/copilot/test_tool_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `scanner/tests/copilot/test_tool_registry.py`:

```python
class TestCategoryModuleCompleteness:
    """Verify all tools from the old registry exist in the new category modules."""

    EXPECTED_TOOL_NAMES = {
        # Lineage (8)
        "get_upstream", "get_downstream", "get_node_details", "search_lineage",
        "get_column_lineage", "analyze_change_impact", "explain_edge", "get_lineage_stats",
        # Warehouse (4)
        "query_warehouse", "get_table_stats", "get_query_history", "get_table_dependencies",
        # DBT (4)
        "get_dbt_model", "get_dbt_run_history", "get_dbt_test_results", "get_dbt_lineage",
        # Orchestration (10)
        "get_asset_orchestration_context", "get_dag_run_history",
        "get_dagster_asset_status", "get_dagster_run_history",
        "get_prefect_flow_status", "get_prefect_flow_runs",
        "get_n8n_workflows", "get_n8n_workflow_details", "get_n8n_executions",
        "get_n8n_execution_details", "get_n8n_recent_failures",
        # Ingestion (5)
        "get_fivetran_connector_status", "get_fivetran_sync_logs", "get_fivetran_schema_changes",
        "get_airbyte_connection_status", "get_airbyte_sync_history",
        # Reporting (10)
        "get_looker_dashboard_status", "get_looker_model_info",
        "get_tableau_workbook_status", "get_tableau_datasource_info", "get_tableau_refresh_history",
        "get_powerbi_dataset_status", "get_powerbi_refresh_history", "get_powerbi_gateway_status",
        "get_metabase_dashboard_status", "get_metabase_card_info", "get_metabase_database_status",
        # Storage (3)
        "list_storage_objects", "get_storage_object_metadata", "list_storage_buckets",
        # Knowledge (1)
        "search_knowledge_base",
        # Observability (5)
        "get_active_incidents", "get_asset_quality", "trace_incident_root_cause",
        "get_quality_checks", "get_incident_details",
        # Coverage (7)
        "get_coverage_report", "get_coverage_gaps", "get_node_coverage",
        "get_monitor_recommendations", "run_coverage_monitor", "create_watch", "run_watch",
        # Actions / Change Plan (5)
        "create_change_plan", "validate_change_plan", "get_change_plan",
        "apply_change_plan", "list_change_plans",
        # GitHub (3)
        "list_github_repos", "get_github_tree", "get_github_file",
        # Onboarding (3)
        "get_pending_questions", "save_onboarding_context", "complete_onboarding",
        # Infrastructure (7)
        "check_server_health", "check_certificates", "analyze_server_logs",
        "list_server_services", "check_integration_health", "list_integration_assets",
        "get_integration_capabilities",
    }

    def test_all_tools_registered(self):
        """Every tool from the old monolith must exist in the new registry."""
        _GLOBAL_REGISTRY.clear()
        # Force re-import of all category modules
        import importlib
        import scanner.copilot.tools.lineage as _l
        import scanner.copilot.tools.warehouse as _w
        import scanner.copilot.tools.dbt as _d
        import scanner.copilot.tools.orchestration as _o
        import scanner.copilot.tools.ingestion as _i
        import scanner.copilot.tools.reporting as _r
        import scanner.copilot.tools.storage as _s
        import scanner.copilot.tools.knowledge as _k
        import scanner.copilot.tools.observability as _ob
        import scanner.copilot.tools.coverage as _c
        import scanner.copilot.tools.actions as _a
        import scanner.copilot.tools.github as _g
        import scanner.copilot.tools.onboarding as _on
        import scanner.copilot.tools.infrastructure as _inf

        for mod in [_l, _w, _d, _o, _i, _r, _s, _k, _ob, _c, _a, _g, _on, _inf]:
            importlib.reload(mod)

        registered_names = set(_GLOBAL_REGISTRY.keys())
        missing = self.EXPECTED_TOOL_NAMES - registered_names
        extra = registered_names - self.EXPECTED_TOOL_NAMES

        assert not missing, f"Missing tools: {missing}"
        # Extra tools are OK (new additions) but flag them
        if extra:
            print(f"Note: extra tools not in expected set: {extra}")

    def test_tool_count_matches(self):
        """Sanity check: at least 75 tools registered."""
        _GLOBAL_REGISTRY.clear()
        import importlib
        import scanner.copilot.tools.lineage as _l
        for mod_name in [
            "scanner.copilot.tools.lineage", "scanner.copilot.tools.warehouse",
            "scanner.copilot.tools.dbt", "scanner.copilot.tools.orchestration",
            "scanner.copilot.tools.ingestion", "scanner.copilot.tools.reporting",
            "scanner.copilot.tools.storage", "scanner.copilot.tools.knowledge",
            "scanner.copilot.tools.observability", "scanner.copilot.tools.coverage",
            "scanner.copilot.tools.actions", "scanner.copilot.tools.github",
            "scanner.copilot.tools.onboarding", "scanner.copilot.tools.infrastructure",
        ]:
            importlib.reload(importlib.import_module(mod_name))

        assert len(_GLOBAL_REGISTRY) >= 75
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py::TestCategoryModuleCompleteness::test_all_tools_registered -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create all category modules**

Each file follows this pattern. Convert every `self._register(Tool(...))` call from the old `_register_all_tools()` into a `@register_tool(...)` decorator call.

Example — `scanner/copilot/tools/lineage.py`:

```python
"""Lineage tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_upstream",
    description="Get all upstream dependencies (tables/models that feed into this node). Use this to understand where data comes from. Supports optional filtering by lineage level, confidence, and system.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("node_id", "string", "The fully qualified name of the node (e.g., 'database.schema.table')"),
        ToolParameter("depth", "integer", "How many levels upstream to traverse (-1 for all)", required=False, default=-1),
        ToolParameter("level", "string", "Filter by lineage level", required=False, enum=["tool", "table", "column"]),
        ToolParameter("min_confidence", "number", "Minimum edge confidence (0.0-1.0)", required=False),
        ToolParameter("system", "string", "Filter to a specific system (e.g., 'bigquery', 'dbt', 'looker')", required=False),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "DBT_CLOUD", "DBT_CORE", "TABLEAU", "POWERBI"},
)
def _meta_get_upstream():
    pass


@register_tool(
    name="get_downstream",
    description="Get all downstream dependents (tables/models/dashboards that depend on this node). Use this to understand impact of changes. Supports optional filtering by lineage level, confidence, and system.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("node_id", "string", "The fully qualified name of the node"),
        ToolParameter("depth", "integer", "How many levels downstream to traverse (-1 for all)", required=False, default=-1),
        ToolParameter("level", "string", "Filter by lineage level", required=False, enum=["tool", "table", "column"]),
        ToolParameter("min_confidence", "number", "Minimum edge confidence (0.0-1.0)", required=False),
        ToolParameter("system", "string", "Filter to a specific system (e.g., 'bigquery', 'dbt', 'looker')", required=False),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "DBT_CLOUD", "DBT_CORE", "TABLEAU", "POWERBI"},
)
def _meta_get_downstream():
    pass

# ... (continue for all 8 lineage tools: get_node_details, search_lineage,
#      get_column_lineage, analyze_change_impact, explain_edge, get_lineage_stats)
```

Repeat this pattern for every category module. The tool definitions are 1:1 copies from the old `_register_all_tools()` — only the wrapping syntax changes from `self._register(Tool(...))` to `@register_tool(...)`.

**Category → source line mapping** (from `scanner/copilot/tools.py`):
- `lineage.py`: lines 180-280 (8 tools)
- `warehouse.py`: lines 286-331 (4 tools)
- `dbt.py`: lines 337-377 (4 tools)
- `orchestration.py`: lines 385-537 (11 tools including n8n)
- `ingestion.py`: lines 543-598 (5 tools)
- `reporting.py`: lines 604-726 (11 tools including Metabase)
- `storage.py`: lines 732-766 (3 tools)
- `knowledge.py`: lines 772-800 (1 tool)
- `observability.py`: lines 806-913 (5 tools)
- `coverage.py`: lines 919-1123 (7 tools including create_watch, run_watch)
- `actions.py`: lines 1129-1252 (5 tools)
- `github.py`: lines 1258-1321 (3 tools)
- `onboarding.py`: lines 1327-1390 (3 tools)
- `infrastructure.py`: lines 1394-1536 (7 tools)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py::TestCategoryModuleCompleteness -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tools/lineage.py scanner/copilot/tools/warehouse.py \
  scanner/copilot/tools/dbt.py scanner/copilot/tools/orchestration.py \
  scanner/copilot/tools/ingestion.py scanner/copilot/tools/reporting.py \
  scanner/copilot/tools/storage.py scanner/copilot/tools/knowledge.py \
  scanner/copilot/tools/observability.py scanner/copilot/tools/coverage.py \
  scanner/copilot/tools/actions.py scanner/copilot/tools/github.py \
  scanner/copilot/tools/onboarding.py scanner/copilot/tools/infrastructure.py \
  scanner/tests/copilot/test_tool_registry.py
git commit -m "feat: add all tool category modules with @register_tool decorators"
```

---

### Task 4: Create __init__.py and Wire Up Backward-Compatible Imports

**Files:**
- Create: `scanner/copilot/tools/__init__.py`
- Delete: `scanner/copilot/tools.py` (the old monolith — now replaced by `tools/` package)
- Modify: `scanner/tests/copilot/test_tool_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `scanner/tests/copilot/test_tool_registry.py`:

```python
class TestBackwardCompatibility:
    """Verify old import paths still work."""

    def test_import_tool_from_package(self):
        from copilot.tools import Tool, ToolParameter, ToolResult, ToolCategory
        assert Tool is not None
        assert ToolParameter is not None
        assert ToolResult is not None
        assert ToolCategory is not None

    def test_import_registry_from_package(self):
        from copilot.tools import ToolRegistry, get_tool_registry
        registry = get_tool_registry()
        assert isinstance(registry, ToolRegistry)
        assert len(registry.get_all_tools()) >= 75

    def test_import_register_tool_from_package(self):
        from copilot.tools import register_tool
        assert callable(register_tool)

    def test_anthropic_format_parity(self):
        """Anthropic tool output must match old format exactly."""
        from copilot.tools import get_tool_registry
        registry = get_tool_registry()
        tools = registry.to_anthropic_tools(set())
        # Every tool must have name + input_schema
        for t in tools:
            assert "name" in t
            assert "input_schema" in t
            assert t["input_schema"]["type"] == "object"

    def test_openai_format_parity(self):
        """OpenAI tool output must match old format exactly."""
        from copilot.tools import get_tool_registry
        registry = get_tool_registry()
        tools = registry.to_openai_tools(set())
        for t in tools:
            assert t["type"] == "function"
            assert "name" in t["function"]
            assert "parameters" in t["function"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py::TestBackwardCompatibility -v`
Expected: FAIL (old `tools.py` file conflicts with `tools/` package)

- [ ] **Step 3: Rename old tools.py and create __init__.py**

First, rename the old file so it no longer conflicts:

```bash
mv scanner/copilot/tools.py scanner/copilot/tools_old.py
```

Then create `scanner/copilot/tools/__init__.py`:

```python
"""
Co-Pilot Tool Registry Package

Re-exports all public names for backward compatibility.
Old import: from copilot.tools import ToolRegistry, Tool, ...
New import: from copilot.tools.registry import ToolRegistry
            from copilot.tools.base import Tool, ToolParameter, ...
"""

from .base import Tool, ToolParameter, ToolResult, ToolCategory
from .registry import ToolRegistry, register_tool, _GLOBAL_REGISTRY

# Global registry instance
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Verify external importers still work**

Run: `cd scanner && python -c "from copilot.tools import ToolRegistry, Tool, ToolResult, get_tool_registry; r = get_tool_registry(); print(f'Tools: {len(r.get_all_tools())}')"`
Expected: prints `Tools: 75` (or higher)

- [ ] **Step 6: Remove old tools_old.py**

```bash
rm scanner/copilot/tools_old.py
```

- [ ] **Step 7: Run full test suite to verify nothing broke**

Run: `cd scanner && python -m pytest tests/copilot/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add scanner/copilot/tools/__init__.py scanner/tests/copilot/test_tool_registry.py
git rm scanner/copilot/tools.py
git commit -m "refactor: replace monolithic tools.py with tools/ package"
```

---

### Task 5: Add Tool Relevance Scoring

**Files:**
- Modify: `scanner/copilot/tools/registry.py`
- Create: `scanner/tests/copilot/test_tool_scoring.py`

- [ ] **Step 1: Write the failing tests**

```python
# scanner/tests/copilot/test_tool_scoring.py
"""Tests for intent-aware tool relevance scoring."""

import pytest
from copilot.tools.base import Tool, ToolParameter, ToolCategory
from copilot.tools.registry import score_tool_relevance, build_tool_recommendations, _GLOBAL_REGISTRY, register_tool
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
        # "dag" matches name token, "run" matches name token, "history" matches name token → 3 * 5 = 15
        assert score >= 15

    def test_query_token_match_on_description(self):
        tool = Tool(name="get_upstream", description="Get all upstream dependencies including tables and models", category=ToolCategory.LINEAGE)
        intent = self._make_intent(Intent.INFO)
        score = score_tool_relevance(tool, {"dependencies"}, intent)
        # "dependencies" matches description → +2
        assert score >= 2

    def test_category_token_match(self):
        tool = Tool(name="get_dbt_model", description="Get dbt model details", category=ToolCategory.DBT)
        intent = self._make_intent(Intent.INFO)
        score = score_tool_relevance(tool, {"dbt"}, intent)
        # "dbt" matches name token (+5) AND category (+3) = 8
        assert score >= 8

    def test_intent_boost_debug(self):
        tool = Tool(name="get_dag_run_history", description="Get DAG runs", category=ToolCategory.ORCHESTRATION)
        intent = self._make_intent(Intent.DEBUG)
        score = score_tool_relevance(tool, set(), intent)
        # DEBUG boosts get_dag_run_history +10
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
        """Integration test: 'why did my DAG fail' + DEBUG should rank orchestration tools top."""
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
        """Integration test: 'how many orders' + INFO should rank query_warehouse top."""
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
        # Should have at most 3 numbered entries
        numbered_lines = [l for l in result.split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5."))]
        assert len(numbered_lines) <= 3

    def test_omits_zero_score_tools_from_ranked_list(self):
        tools = [
            Tool(name="query_warehouse", description="Run SQL", category=ToolCategory.WAREHOUSE),
            Tool(name="get_powerbi_gateway_status", description="Power BI gateway", category=ToolCategory.REPORTING),
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "how many orders in bigquery", intent)
        # powerbi tool should not be in the numbered list (score 0)
        assert "`get_powerbi_gateway_status`" not in result.split("All tools remain available")[0]

    def test_includes_other_tools_note(self):
        tools = [
            Tool(name="query_warehouse", description="Run SQL", category=ToolCategory.WAREHOUSE),
        ]
        intent = self._make_intent(Intent.INFO)
        result = build_tool_recommendations(tools, "orders", intent)
        assert "All tools remain available" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_scoring.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_tool_relevance'`

- [ ] **Step 3: Add scoring functions to registry.py**

Append to `scanner/copilot/tools/registry.py`:

```python
import re
from typing import Tuple

# ---------------------------------------------------------------------------
# Intent-aware tool relevance scoring
# ---------------------------------------------------------------------------

# Common stop words (reused from context_builder.py pattern)
_STOP_WORDS = frozenset({
    "what", "which", "how", "many", "much", "show", "me", "my", "the",
    "a", "an", "is", "are", "was", "were", "do", "does", "did", "can",
    "get", "find", "list", "all", "from", "for", "in", "of", "to",
    "and", "or", "by", "with", "that", "this", "on", "at", "have",
    "has", "had", "be", "been", "being", "i", "we", "you", "they",
    "it", "its", "most", "least", "top", "bottom", "give", "tell",
    "about", "any", "some", "each", "every", "per", "total", "count",
    "number", "average", "sum", "min", "max", "between",
})


def _tokenize(text: str) -> set:
    """Split text into meaningful lowercase tokens."""
    tokens = re.findall(r'[a-z][a-z0-9]*', text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


# Static boost map: intent → tool_name → bonus points
INTENT_TOOL_BOOSTS = {
    "info": {
        "query_warehouse": 10,
        "search_lineage": 8,
        "get_node_details": 6,
        "get_table_stats": 6,
        "get_column_lineage": 4,
    },
    "debug": {
        "get_dag_run_history": 10,
        "get_dbt_run_history": 10,
        "query_warehouse": 8,
        "run_coverage_monitor": 8,
        "get_downstream": 6,
        "get_fivetran_sync_logs": 6,
        "get_airbyte_sync_history": 6,
        "get_asset_orchestration_context": 6,
        "get_active_incidents": 6,
        "trace_incident_root_cause": 4,
        "get_n8n_recent_failures": 6,
        "get_n8n_execution_details": 4,
    },
    "fix": {
        "create_change_plan": 10,
        "validate_change_plan": 10,
        "apply_change_plan": 10,
        "get_downstream": 8,
        "get_upstream": 8,
        "analyze_change_impact": 8,
        "query_warehouse": 6,
    },
    "plan": {
        "get_downstream": 10,
        "get_upstream": 10,
        "analyze_change_impact": 10,
        "query_warehouse": 6,
        "get_node_details": 6,
    },
    "pr": {
        "create_change_plan": 10,
        "validate_change_plan": 10,
        "apply_change_plan": 10,
        "get_downstream": 8,
        "get_upstream": 8,
    },
    "explain": {
        "get_node_details": 10,
        "get_upstream": 8,
        "get_downstream": 8,
        "get_column_lineage": 6,
        "explain_edge": 6,
    },
}

# Target hint → ToolCategory mapping
TARGET_CATEGORY_MAP = {
    "airflow": ToolCategory.ORCHESTRATION,
    "dagster": ToolCategory.ORCHESTRATION,
    "prefect": ToolCategory.ORCHESTRATION,
    "n8n": ToolCategory.ORCHESTRATION,
    "dbt": ToolCategory.DBT,
    "fivetran": ToolCategory.INGESTION,
    "airbyte": ToolCategory.INGESTION,
    "bigquery": ToolCategory.WAREHOUSE,
    "snowflake": ToolCategory.WAREHOUSE,
    "postgres": ToolCategory.WAREHOUSE,
    "redshift": ToolCategory.WAREHOUSE,
    "databricks": ToolCategory.WAREHOUSE,
    "looker": ToolCategory.REPORTING,
    "tableau": ToolCategory.REPORTING,
    "powerbi": ToolCategory.REPORTING,
    "metabase": ToolCategory.REPORTING,
    "monte_carlo": ToolCategory.OBSERVABILITY,
    "bigeye": ToolCategory.OBSERVABILITY,
    "soda": ToolCategory.OBSERVABILITY,
    "elementary": ToolCategory.OBSERVABILITY,
    "s3": ToolCategory.STORAGE,
    "gcs": ToolCategory.STORAGE,
    "adls": ToolCategory.STORAGE,
}


def score_tool_relevance(
    tool: Tool,
    query_tokens: set,
    intent_result,
) -> int:
    """
    Score how relevant a tool is to the user's query and intent.

    Scoring layers:
      1. Query token matching against tool name/description/category
      2. Intent-based static boost
      3. Target hint category boost
    """
    score = 0

    # Layer 1: Query token matching
    name_tokens = _tokenize(tool.name.replace("_", " "))
    desc_tokens = _tokenize(tool.description)
    category_tokens = _tokenize(tool.category.value.replace("_", " "))

    for token in query_tokens:
        if token in name_tokens:
            score += 5
        if token in desc_tokens:
            score += 2
        if token in category_tokens:
            score += 3

    # Layer 2: Intent boost
    intent_key = intent_result.primary.intent.value
    boosts = INTENT_TOOL_BOOSTS.get(intent_key, {})
    score += boosts.get(tool.name, 0)

    # Layer 3: Target hint boost
    target_hint = getattr(intent_result, "target_hint", None)
    if target_hint:
        target_category = TARGET_CATEGORY_MAP.get(target_hint.lower())
        if target_category and tool.category == target_category:
            score += 5

    return score


def build_tool_recommendations(
    available_tools: List[Tool],
    query: str,
    intent_result,
    top_n: int = 5,
) -> str:
    """
    Build a 'Recommended Tools' system prompt section.

    Scores all tools, ranks them, and returns a formatted markdown section
    with the top N tools and a note about remaining tools.
    """
    query_tokens = _tokenize(query)

    scored = [
        (tool, score_tool_relevance(tool, query_tokens, intent_result))
        for tool in available_tools
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Only include tools with score > 0 in the ranked list
    ranked = [(t, s) for t, s in scored if s > 0][:top_n]

    if not ranked:
        return ""

    lines = ["## Recommended Tools (for this query)"]
    for i, (tool, s) in enumerate(ranked, 1):
        # Use first sentence of description as short summary
        short_desc = tool.description.split(".")[0]
        lines.append(f"{i}. `{tool.name}` — {short_desc} (score: {s})")

    lines.append("")
    lines.append("All tools remain available. Use these first unless your investigation leads elsewhere.")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_scoring.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tools/registry.py scanner/tests/copilot/test_tool_scoring.py
git commit -m "feat: add intent-aware tool relevance scoring and recommendations"
```

---

### Task 6: Wire Recommendations into System Prompt

**Files:**
- Modify: `scanner/copilot/llm.py:306-315` (replace `preferred_tools` injection)
- Modify: `scanner/copilot/llm.py` (add `build_tool_recommendations` call)

- [ ] **Step 1: Read the current preferred_tools injection**

The current code at `scanner/copilot/llm.py:306-315`:

```python
        # Inject preferred tools for the active mode so the LLM knows
        # which tools to reach for first in this context
        if context.mode_config and context.mode_config.preferred_tools:
            tools_list = ", ".join(
                f"`{t}`" for t in context.mode_config.preferred_tools
            )
            prompt += (
                f"\n**Preferred tools for this mode**: {tools_list}. "
                "Use these tools first when they match the user's question.\n"
            )
```

- [ ] **Step 2: Add query parameter to build_system_prompt**

The `build_system_prompt` method needs access to the user's query and available tools to generate recommendations. Modify the method signature in `scanner/copilot/llm.py`:

Find the current signature:
```python
    def build_system_prompt(self, context: CopilotContext) -> str:
```

Replace with:
```python
    def build_system_prompt(self, context: CopilotContext, query: str = "", available_tools: list = None) -> str:
```

- [ ] **Step 3: Replace preferred_tools injection with dynamic recommendations**

Replace lines 306-315 (the `preferred_tools` block) with:

```python
        # Inject dynamically scored tool recommendations
        if query and context.intent_result and available_tools:
            from scanner.copilot.tools.registry import build_tool_recommendations
            recommendations = build_tool_recommendations(
                available_tools, query, context.intent_result, top_n=5,
            )
            if recommendations:
                prompt += f"\n{recommendations}\n"
        elif context.mode_config and context.mode_config.preferred_tools:
            # Fallback: static preferred tools when no query/intent available
            tools_list = ", ".join(
                f"`{t}`" for t in context.mode_config.preferred_tools
            )
            prompt += (
                f"\n**Preferred tools for this mode**: {tools_list}. "
                "Use these tools first when they match the user's question.\n"
            )
```

- [ ] **Step 4: Update callers of build_system_prompt**

Search for all calls to `build_system_prompt` in `llm.py` and pass `query` and `available_tools`. There are typically 2-3 call sites (in `_chat_anthropic`, `_chat_anthropic_stream`, `_chat_openai_stream`).

Find each call like:
```python
system_prompt = self.build_system_prompt(context)
```

Replace with:
```python
system_prompt = self.build_system_prompt(context, query=prompt_text, available_tools=available_tools_list)
```

Where `prompt_text` is the user's message (already available in those methods) and `available_tools_list` is the list of `Tool` objects (get from `self.tool_registry.get_available_tools(...)` which is already called nearby to build the API tool list).

To get `Tool` objects, add this near where `anthropic_tools` / `openai_tools` is built:

```python
from scanner.copilot.tools.base import Tool
available_tool_objects = self.tool_registry.get_available_tools(user_integrations)
```

Then pass it:
```python
system_prompt = self.build_system_prompt(context, query=user_message, available_tools=available_tool_objects)
```

- [ ] **Step 5: Run existing tests to verify nothing broke**

Run: `cd scanner && python -m pytest tests/copilot/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/llm.py
git commit -m "feat: wire dynamic tool recommendations into system prompt"
```

---

### Task 7: Update Import Paths in External Files

**Files:**
- Modify: `scanner/api/routers/copilot.py:16`
- Modify: `scanner/copilot/maas/orchestrator.py:20`

- [ ] **Step 1: Verify these files import from copilot.tools**

The known importers:
- `scanner/api/routers/copilot.py:16`: `from copilot.tools import get_tool_registry`
- `scanner/copilot/maas/orchestrator.py:20`: `from copilot.tools import ToolResult`
- `scanner/copilot/llm.py` (multiple lines): `from scanner.copilot.tools import ToolResult`

- [ ] **Step 2: No changes needed**

All these imports use `from copilot.tools import X` which resolves to `copilot/tools/__init__.py` — the same module that re-exports `ToolRegistry`, `Tool`, `ToolResult`, `get_tool_registry`, etc. The imports are already backward-compatible.

Verify with:
```bash
cd scanner && python -c "from copilot.tools import get_tool_registry, ToolResult; print('OK')"
cd scanner && python -c "from scanner.copilot.tools import ToolResult; print('OK')"
```

Expected: Both print `OK`

- [ ] **Step 3: Run full test suite**

Run: `cd scanner && python -m pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 4: Commit (if any changes were needed)**

```bash
git add -A
git commit -m "chore: verify import compatibility after tools package refactor"
```

---

### Task 8: Remove _load_from_global_registry Import Guard

**Files:**
- Modify: `scanner/copilot/tools/registry.py`

- [ ] **Step 1: Remove the try/except guard from _load_from_global_registry**

Now that all category modules exist, remove the `try/except ImportError` fallback added in Task 2:

Replace:
```python
    def _load_from_global_registry(self):
        """Import category modules to trigger decorators, then copy registry."""
        try:
            from scanner.copilot.tools import (
                lineage, warehouse, dbt, orchestration, ingestion,
                reporting, storage, knowledge, observability, coverage,
                actions, github, onboarding, infrastructure,
            )
        except ImportError:
            pass  # Category modules not yet created; tests populate _GLOBAL_REGISTRY directly
        self._tools = dict(_GLOBAL_REGISTRY)
```

With:
```python
    def _load_from_global_registry(self):
        """Import category modules to trigger decorators, then copy registry."""
        from scanner.copilot.tools import (
            lineage, warehouse, dbt, orchestration, ingestion,
            reporting, storage, knowledge, observability, coverage,
            actions, github, onboarding, infrastructure,
        )
        self._tools = dict(_GLOBAL_REGISTRY)
```

- [ ] **Step 2: Run all tests**

Run: `cd scanner && python -m pytest tests/copilot/test_tool_registry.py tests/copilot/test_tool_scoring.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scanner/copilot/tools/registry.py
git commit -m "chore: remove temporary import guard from registry"
```
