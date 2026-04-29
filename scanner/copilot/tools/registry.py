"""
Co-Pilot Tool Registry

Decorator-based tool registration and ToolRegistry class.
"""

import re
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
        _modules = (
            "lineage", "warehouse", "dbt", "orchestration", "ingestion",
            "reporting", "storage", "knowledge", "observability", "coverage",
            "actions", "github", "onboarding", "infrastructure",
        )
        # Try relative import first (works when running from scanner/ dir),
        # then absolute scanner.copilot.tools path (works when running from repo root).
        for prefix in ("copilot.tools", "scanner.copilot.tools"):
            try:
                import importlib
                for mod in _modules:
                    importlib.import_module(f"{prefix}.{mod}")
                break
            except ImportError:
                continue
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

    def get_available_tools(
        self,
        user_integrations: Set[str],
        exclude: Optional[Set[str]] = None,
    ) -> List[Tool]:
        """Get tools available for the user's integrations.

        If `exclude` is provided, tool names in that set are filtered out — used
        by the chat loop to enforce per-mode tool gating (modes.tools_excluded_for_mode).
        """
        excluded = exclude or set()
        return [
            tool for tool in self._tools.values()
            if tool.is_available(user_integrations) and tool.name not in excluded
        ]

    def get_tools_by_category(self, category: ToolCategory) -> List[Tool]:
        """Get all tools in a category."""
        return [
            tool for tool in self._tools.values()
            if tool.category == category
        ]

    def to_anthropic_tools(
        self,
        user_integrations: Set[str],
        exclude: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert available tools to Anthropic format. `exclude` filters by name."""
        available = self.get_available_tools(user_integrations, exclude=exclude)
        return [tool.to_anthropic_tool() for tool in available]

    def to_openai_tools(
        self,
        user_integrations: Set[str],
        exclude: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert available tools to OpenAI format. `exclude` filters by name."""
        available = self.get_available_tools(user_integrations, exclude=exclude)
        return [tool.to_openai_tool() for tool in available]

    @staticmethod
    def merge_mcp_tools(
        static_tools: List[Dict[str, Any]],
        mcp_tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge MCP-discovered tools with static registry tools."""
        return static_tools + mcp_tools


# ---------------------------------------------------------------------------
# Intent-aware tool relevance scoring
# ---------------------------------------------------------------------------

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


INTENT_TOOL_BOOSTS = {
    "info": {
        "query_warehouse": 10, "search_lineage": 8, "get_node_details": 6,
        "get_table_stats": 6, "get_column_lineage": 4,
    },
    "debug": {
        "get_dag_run_history": 10, "get_dbt_run_history": 10,
        "query_warehouse": 8, "run_coverage_monitor": 8,
        "get_downstream": 6, "get_fivetran_sync_logs": 6,
        "get_airbyte_sync_history": 6, "get_asset_orchestration_context": 6,
        "get_active_incidents": 6, "trace_incident_root_cause": 4,
        "get_n8n_recent_failures": 6, "get_n8n_execution_details": 4,
    },
    "fix": {
        "create_change_plan": 10, "validate_change_plan": 10,
        "apply_change_plan": 10, "get_downstream": 8, "get_upstream": 8,
        "analyze_change_impact": 8, "query_warehouse": 6,
    },
    "plan": {
        "get_downstream": 10, "get_upstream": 10, "analyze_change_impact": 10,
        "query_warehouse": 6, "get_node_details": 6,
    },
    "pr": {
        "create_change_plan": 10, "validate_change_plan": 10,
        "apply_change_plan": 10, "get_downstream": 8, "get_upstream": 8,
    },
    "explain": {
        "get_node_details": 10, "get_upstream": 8, "get_downstream": 8,
        "get_column_lineage": 6, "explain_edge": 6,
    },
}

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
      1. Query token matching against tool name/description/category (+5/+2/+3)
      2. Intent-based static boost (up to +10)
      3. Target hint category boost (+5)
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

    Scores all tools, ranks them, returns formatted markdown with top N.
    """
    query_tokens = _tokenize(query)

    scored = [
        (tool, score_tool_relevance(tool, query_tokens, intent_result))
        for tool in available_tools
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    ranked = [(t, s) for t, s in scored if s > 0][:top_n]

    if not ranked:
        return ""

    lines = ["## Recommended Tools (for this query)"]
    for i, (tool, s) in enumerate(ranked, 1):
        short_desc = tool.description.split(".")[0]
        lines.append(f"{i}. `{tool.name}` — {short_desc} (score: {s})")

    lines.append("")
    lines.append("All tools remain available. Use these first unless your investigation leads elsewhere.")

    return "\n".join(lines)
