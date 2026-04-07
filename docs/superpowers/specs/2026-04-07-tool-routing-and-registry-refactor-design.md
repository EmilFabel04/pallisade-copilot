# Tool Pre-Routing & Registry Refactor

**Date:** 2026-04-07
**Status:** Draft
**Goal:** Improve copilot tool selection accuracy by (1) refactoring the monolithic tool registry into a decorator-based plugin pattern, and (2) adding intent-aware tool relevance scoring that dynamically recommends tools in the system prompt.

---

## Problem

The copilot currently sends all ~30 available tools to the LLM with no ranking or guidance beyond a hardcoded "preferred tools" string. The LLM sometimes picks the wrong tool or ignores relevant ones. Intent classification exists but only drives a static text policy block — it doesn't influence which tools are surfaced.

The tool registry (`tools.py`) is a ~1400-line monolith where all tools are defined in a single `_register_all_tools()` method, making it hard to add or modify tools.

## Approach

- **Rank & annotate** — send all tools to the LLM but inject a scored "Recommended Tools" section in the system prompt. No tools are hidden; the LLM gets clear guidance on what to reach for first.
- **Decorator-based registry** — each tool gets a `@register_tool` decorator. Tools split into category files. Execution logic in `tool_executor.py` stays unchanged.

---

## 1. Decorator-Based Tool Registry

### File Structure

```
scanner/copilot/tools/
  __init__.py          # re-exports ToolRegistry, Tool, ToolParameter, ToolResult, ToolCategory
  base.py              # Tool, ToolParameter, ToolResult, ToolCategory dataclasses (moved from tools.py)
  registry.py          # ToolRegistry class, @register_tool decorator, scoring functions
  lineage.py           # get_upstream, get_downstream, get_node_details, search_lineage,
                       #   get_column_lineage, analyze_change_impact, explain_edge, get_lineage_stats
  warehouse.py         # query_warehouse, get_table_stats, get_query_history, get_table_dependencies
  dbt.py               # get_dbt_model, get_dbt_run_history, get_dbt_test_results, get_dbt_lineage
  orchestration.py     # get_dag_run_history, get_dagster_asset_status, get_prefect_flow_status,
                       #   get_asset_orchestration_context
  observability.py     # create_watch, run_coverage_monitor
  actions.py           # create_change_plan, validate_change_plan, apply_change_plan
```

Additional category files for ingestion, reporting, storage, knowledge, coverage, policy, onboarding, and infrastructure tools as needed — each following the same pattern.

### Decorator API

```python
from scanner.copilot.tools.registry import register_tool
from scanner.copilot.tools.base import ToolCategory, ToolParameter

@register_tool(
    name="get_upstream",
    description="Get all upstream dependencies (tables/models that feed into this node)...",
    category=ToolCategory.LINEAGE,
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS",
                              "DBT_CLOUD", "DBT_CORE", "TABLEAU", "POWERBI"},
    parameters=[
        ToolParameter("node_id", "string", "The fully qualified name of the node"),
        ToolParameter("depth", "integer", "How many levels upstream to traverse", required=False, default=-1),
        ToolParameter("level", "string", "Filter by lineage level", required=False, enum=["tool", "table", "column"]),
        ToolParameter("min_confidence", "number", "Minimum edge confidence (0.0-1.0)", required=False),
        ToolParameter("system", "string", "Filter to a specific system", required=False),
    ],
)
def _meta_get_upstream():
    """Marker only — execution handled by ToolExecutor._execute_get_upstream()."""
    pass
```

The decorator creates a `Tool` dataclass and registers it in a global `_GLOBAL_REGISTRY` dict. The marker function is never called — it exists purely so the decorator runs at import time.

### ToolRegistry Changes

```python
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._load_from_global_registry()  # replaces _register_all_tools()

    def _load_from_global_registry(self):
        """Import all category modules to trigger @register_tool decorators,
        then copy the global registry into this instance."""
        from scanner.copilot.tools import lineage, warehouse, dbt, orchestration, observability, actions
        # ... additional category imports
        self._tools = dict(_GLOBAL_REGISTRY)
```

All existing public methods (`get_tool`, `get_all_tools`, `get_available_tools`, `to_anthropic_tools`, `to_openai_tools`, `merge_mcp_tools`) remain identical. No API changes.

### Backward Compatibility

The old `scanner.copilot.tools` module becomes `scanner.copilot.tools/__init__.py` which re-exports everything at the same import paths:

```python
# scanner/copilot/tools/__init__.py
from .base import Tool, ToolParameter, ToolResult, ToolCategory
from .registry import ToolRegistry, register_tool
```

Callers using `from scanner.copilot.tools import ToolRegistry` continue to work unchanged.

---

## 2. Intent-Aware Tool Relevance Scoring

### Scoring Function

```python
def score_tool_relevance(
    tool: Tool,
    query_tokens: Set[str],
    intent_result: IntentResult,
) -> int:
```

**Scoring layers:**

#### Layer 1: Query Token Matching (max ~15 points)

Uses the existing `tokenize_query()` from `context_builder.py`.

| Match type | Points |
|-----------|--------|
| Tool name matches a query token | +5 |
| Tool description word matches a query token | +2 |
| Tool category name matches a query token | +3 |

Tool name is tokenized by splitting on `_` (e.g., `get_dag_run_history` -> `{"get", "dag", "run", "history"}`). Description is tokenized the same way, filtered through stop words.

#### Layer 2: Intent Boost (max +10 points)

Static boost map keyed by intent. These encode the knowledge currently hardcoded in `_build_tool_policy()`:

```python
INTENT_TOOL_BOOSTS: Dict[Intent, Dict[str, int]] = {
    Intent.INFO: {
        "query_warehouse": 10,
        "search_lineage": 8,
        "get_node_details": 6,
        "get_table_stats": 6,
        "get_column_lineage": 4,
    },
    Intent.DEBUG: {
        "get_dag_run_history": 10,
        "get_dbt_run_history": 10,
        "query_warehouse": 8,
        "run_coverage_monitor": 8,
        "get_downstream": 6,
        "get_fivetran_sync_logs": 6,
        "get_airbyte_sync_history": 6,
        "get_asset_orchestration_context": 6,
    },
    Intent.FIX: {
        "create_change_plan": 10,
        "validate_change_plan": 10,
        "apply_change_plan": 10,
        "get_downstream": 8,
        "get_upstream": 8,
        "analyze_change_impact": 8,
        "query_warehouse": 6,
    },
    Intent.PLAN: {
        "get_downstream": 10,
        "get_upstream": 10,
        "analyze_change_impact": 10,
        "query_warehouse": 6,
        "get_node_details": 6,
    },
    Intent.PR: {
        "create_change_plan": 10,
        "validate_change_plan": 10,
        "apply_change_plan": 10,
        "get_downstream": 8,
        "get_upstream": 8,
    },
    Intent.EXPLAIN: {
        "get_node_details": 10,
        "get_upstream": 8,
        "get_downstream": 8,
        "get_column_lineage": 6,
        "explain_edge": 6,
    },
}
```

#### Layer 3: Target Hint Boost (+5 points)

When `IntentResult.target_hint` identifies a specific system, tools in the matching category get +5:

```python
TARGET_CATEGORY_MAP: Dict[str, ToolCategory] = {
    "airflow": ToolCategory.ORCHESTRATION,
    "dagster": ToolCategory.ORCHESTRATION,
    "prefect": ToolCategory.ORCHESTRATION,
    "dbt": ToolCategory.DBT,
    "fivetran": ToolCategory.INGESTION,
    "airbyte": ToolCategory.INGESTION,
    "bigquery": ToolCategory.WAREHOUSE,
    "snowflake": ToolCategory.WAREHOUSE,
    "postgres": ToolCategory.WAREHOUSE,
    "redshift": ToolCategory.WAREHOUSE,
    "looker": ToolCategory.REPORTING,
    "tableau": ToolCategory.REPORTING,
    "powerbi": ToolCategory.REPORTING,
}
```

If `target_hint == "airflow"` and tool.category == `ToolCategory.ORCHESTRATION`, that tool gets +5.

### Recommendation Builder

```python
def build_tool_recommendations(
    available_tools: List[Tool],
    query: str,
    intent_result: IntentResult,
    top_n: int = 5,
) -> str:
```

1. Calls `score_tool_relevance()` on each available tool
2. Sorts by score descending
3. Returns a formatted string:

```
## Recommended Tools (for this query)
1. `get_dag_run_history` - Check orchestration run history (score: 20)
2. `query_warehouse` - Run SQL queries against connected warehouses (score: 18)
3. `run_coverage_monitor` - Run anomaly/freshness detection (score: 16)
4. `get_downstream` - Check downstream impact (score: 12)
5. `get_dbt_run_history` - Check dbt run status and errors (score: 10)

All tools remain available. Use these first unless your investigation leads elsewhere.
```

Only tools with score > 0 appear in the ranked list. If fewer than `top_n` tools score above 0, show only those that do.

### System Prompt Integration

In `llm.py`, `build_system_prompt()`:

1. **Remove** the hardcoded `preferred_tools` injection (lines ~308-314)
2. **Replace** with `build_tool_recommendations(available_tools, query, intent_result)`
3. **Keep** `_build_tool_policy()` as-is — it covers sequencing rules (e.g., "call create_change_plan before apply_change_plan") that scoring doesn't replace

The recommendations section is injected after the tool-calling policy block, before the warehouse syntax section.

---

## 3. Data Flow

```
User message arrives
  |
  v
intent.classify(query)                    # existing, unchanged
  |
  v
context_builder.build(integrations, ...)  # existing, unchanged
  |
  v
ToolRegistry.get_available_tools(integrations)   # existing filter
  |
  v
score_tool_relevance(tool, query_tokens, intent)  # NEW — per tool
  |
  v
build_tool_recommendations(scored_tools)           # NEW — format top 5
  |
  v
llm.build_system_prompt(context, recommendations)  # inject recommendations
  |
  v
LLM API call with ALL available tools              # unchanged
```

---

## 4. Files Changed

| File | Change | Risk |
|------|--------|------|
| `scanner/copilot/tools.py` | Deleted — replaced by `tools/` package | Medium (many importers) |
| `scanner/copilot/tools/__init__.py` | New — re-exports all public names at same import paths | Low |
| `scanner/copilot/tools/base.py` | New — `Tool`, `ToolParameter`, `ToolResult`, `ToolCategory` moved here | Low |
| `scanner/copilot/tools/registry.py` | New — `ToolRegistry`, `@register_tool`, `score_tool_relevance()`, `build_tool_recommendations()` | Medium |
| `scanner/copilot/tools/lineage.py` | New — lineage tool definitions via decorator | Low |
| `scanner/copilot/tools/warehouse.py` | New — warehouse tool definitions via decorator | Low |
| `scanner/copilot/tools/dbt.py` | New — dbt tool definitions via decorator | Low |
| `scanner/copilot/tools/orchestration.py` | New — orchestration tool definitions via decorator | Low |
| `scanner/copilot/tools/observability.py` | New — observability tool definitions via decorator | Low |
| `scanner/copilot/tools/actions.py` | New — action/write tool definitions via decorator | Low |
| `scanner/copilot/llm.py` | Replace `preferred_tools` injection with `build_tool_recommendations()` | Low |
| `scanner/copilot/tool_executor.py` | Update import path only | Low |
| `scanner/copilot/context_builder.py` | No changes | None |

---

## 5. Testing

- **Unit tests for scoring:** Verify that `score_tool_relevance()` returns expected scores for known query+intent combinations (e.g., "why did my DAG fail" + DEBUG intent should rank `get_dag_run_history` highest)
- **Registry tests:** Verify all tools from old `_register_all_tools()` are present in new registry. Compare tool count, names, and parameter schemas.
- **Integration test:** Verify `to_anthropic_tools()` and `to_openai_tools()` produce identical output before and after refactor.
- **Recommendation format test:** Verify `build_tool_recommendations()` output is valid markdown and respects `top_n` limit.
- **Import compatibility:** Verify `from scanner.copilot.tools import ToolRegistry, Tool` still works.

---

## 6. Out of Scope

- Transcript compaction / token budget tracking (future work)
- Changing which tools are sent to the LLM API (all tools still sent)
- Modifying tool execution logic in `tool_executor.py`
- Changing intent classification logic
- MCP tool scoring (MCP tools are discovered dynamically and not in the static registry)
