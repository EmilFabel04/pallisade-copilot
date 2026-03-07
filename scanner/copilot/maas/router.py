"""
Intent-to-specialist routing with smart data query detection.

Routes each intent to the appropriate specialist(s) and evidence tools,
with budget constraints.
"""

import re
import logging
from typing import List, Optional, Set
from dataclasses import dataclass

from copilot.intent import Intent, IntentResult
from copilot.context_builder import CopilotContext, tokenize_query

from .budgets import get_budget, IntentBudget

logger = logging.getLogger(__name__)


@dataclass
class SpecialistRoute:
    """Defines which specialists to call and in what order for an intent."""
    specialists: List[str]       # ordered: ["sql"], ["logs", "codefix"], etc.
    evidence_tools: List[str]    # tools to call BEFORE specialists
    budget: IntentBudget
    required_specialists: List[str]   # must be available, else full fallback
    optional_specialists: List[str]   # can be skipped if unavailable


# Strong signal patterns for data queries
_DATA_QUERY_PATTERNS = re.compile(
    r"\b(count|sum|avg|average|min|max|total|rows|records|entries|"
    r"how many|how much|show me .{0,30}(data|rows|records|table)|"
    r"from table|in table|query|select|group by|order by|"
    r"top \d+|bottom \d+|latest|oldest|newest|most recent)\b",
    re.IGNORECASE,
)


def _is_data_query(query: str, context: CopilotContext) -> bool:
    """
    Conservative heuristic: only True on strong signals.

    Strong signals (any one triggers True):
    - Aggregate keywords (count, sum, avg, total, rows, etc.)
    - Table/column name overlap with warehouse schema
    - Explicit data patterns ("how many", "show me ... data/rows")

    Defaults to False when in doubt.
    """
    # 1. Check for strong keyword patterns
    if _DATA_QUERY_PATTERNS.search(query):
        return True

    # 2. Check if query mentions schema table/column names
    if context.warehouse_schema:
        query_tokens = set(tokenize_query(query.lower()))
        for schema_key, tables in context.warehouse_schema.items():
            for table in tables:
                table_lower = table.name.lower()
                table_parts = set(re.findall(r"[a-z][a-z0-9]*", table_lower))

                # Table name overlap
                if query_tokens & table_parts:
                    return True

                # Exact table name in query
                if table_lower in query.lower():
                    return True

                # Column name overlap
                col_names = {
                    c.get("name", "").lower()
                    for c in table.columns
                    if c.get("name")
                }
                if query_tokens & col_names:
                    return True

    return False


def route_intent(
    intent_result: IntentResult,
    context: CopilotContext,
) -> SpecialistRoute:
    """
    Map an IntentResult to a SpecialistRoute.

    Returns which specialists to call, what evidence to gather first,
    and the budget constraints.
    """
    primary = intent_result.primary.intent
    secondary = intent_result.secondary.intent if intent_result.secondary else None
    budget = get_budget(primary)

    # --- INFO: SQL specialist only if it's a data query ---
    if primary == Intent.INFO:
        if context.has_warehouse() and _is_data_query(context.query, context):
            return SpecialistRoute(
                specialists=["sql"],
                evidence_tools=[],
                budget=budget,
                required_specialists=["sql"],
                optional_specialists=[],
            )
        else:
            # Non-data question → GPT-5 only
            return SpecialistRoute(
                specialists=[],
                evidence_tools=[],
                budget=budget,
                required_specialists=[],
                optional_specialists=[],
            )

    # --- DEBUG: Logs specialist, optional CodeFix ---
    if primary == Intent.DEBUG:
        evidence_tools = _debug_evidence_tools(intent_result)
        specialists = ["logs"]
        optional = []
        if secondary in (Intent.FIX, Intent.PR):
            specialists.append("codefix")
            optional.append("codefix")
        return SpecialistRoute(
            specialists=specialists,
            evidence_tools=evidence_tools,
            budget=budget,
            required_specialists=["logs"],
            optional_specialists=optional,
        )

    # --- FIX/PR: Logs triage + CodeFix ---
    if primary in (Intent.FIX, Intent.PR):
        evidence_tools = _fix_evidence_tools(intent_result)
        return SpecialistRoute(
            specialists=["logs", "codefix"],
            evidence_tools=evidence_tools,
            budget=budget,
            required_specialists=["logs"],
            optional_specialists=["codefix"],
        )

    # --- PLAN: upstream/downstream + CodeFix draft ---
    if primary == Intent.PLAN:
        return SpecialistRoute(
            specialists=["codefix"],
            evidence_tools=["get_upstream", "get_downstream"],
            budget=budget,
            required_specialists=[],
            optional_specialists=["codefix"],
        )

    # --- EXPLAIN: no specialist, GPT-5 only ---
    if primary == Intent.EXPLAIN:
        return SpecialistRoute(
            specialists=[],
            evidence_tools=[],
            budget=budget,
            required_specialists=[],
            optional_specialists=[],
        )

    # Fallback
    return SpecialistRoute(
        specialists=[],
        evidence_tools=[],
        budget=get_budget(Intent.INFO),
        required_specialists=[],
        optional_specialists=[],
    )


def _debug_evidence_tools(intent_result: IntentResult) -> List[str]:
    """Determine which evidence-gathering tools to call for DEBUG."""
    target = intent_result.target_hint
    tools: List[str] = []

    if target == "airflow":
        tools.append("get_dag_run_history")
    elif target == "dbt":
        tools.extend(["get_dbt_run_history", "get_dbt_test_results"])
    elif target == "fivetran":
        tools.append("get_fivetran_connector_status")
    elif target == "airbyte":
        tools.append("get_airbyte_connection_status")

    # Always check downstream impact if we have target entities
    if intent_result.target_entities:
        tools.append("get_downstream")

    return tools


def _fix_evidence_tools(intent_result: IntentResult) -> List[str]:
    """Determine evidence tools for FIX/PR — superset of debug tools."""
    tools = _debug_evidence_tools(intent_result)
    if "get_downstream" not in tools:
        tools.append("get_downstream")
    if "get_upstream" not in tools:
        tools.append("get_upstream")
    return tools


def filter_evidence_requests(
    requested_tools: List[str],
    available_tools: Set[str],
) -> List[str]:
    """
    Filter specialist-requested evidence tools against available tools.

    Returns only valid tools, substituting deterministic fallbacks for invalid ones.
    """
    filtered = []
    for tool_name in requested_tools:
        if tool_name in available_tools:
            filtered.append(tool_name)
        else:
            # Deterministic fallback: try search_lineage for lineage tools
            if any(k in tool_name for k in ("lineage", "upstream", "downstream")):
                if "search_lineage" in available_tools:
                    filtered.append("search_lineage")
            logger.warning(
                f"[MAAS/Router] Filtered out unavailable tool '{tool_name}'"
            )
    return filtered
