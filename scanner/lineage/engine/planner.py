"""
LLM-Driven Extraction Planner

Determines the order in which adapters should run for lineage extraction.
Uses an LLM to reason about which adapters to run first based on:
  - Currently known integrations
  - Last run diagnostics (gaps, missing links)
  - Desired goals (connect ingestion→raw, connect dbt→warehouse)

Includes a deterministic fallback when LLM is unavailable:
  Default heuristic order: warehouse → transform → ingestion → orchestration → infra

Output schema:
  {
    "plan": ["adapter_name", ...],
    "reasons": {"adapter_name": "reason", ...}
  }
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic fallback ordering
# ---------------------------------------------------------------------------

# Default heuristic: discover data assets first (warehouse), then map
# transforms, then connect ingestion writers, then orchestration/infra.
# Derived from the platform registry (single source of truth).
from .platforms import PLATFORM_REGISTRY

HEURISTIC_ORDER: Dict[str, int] = {
    name: info.heuristic_order
    for name, info in PLATFORM_REGISTRY.items()
    if name == info.name  # exclude aliases
}


# ---------------------------------------------------------------------------
# Planner data classes
# ---------------------------------------------------------------------------

class ExtractionPlan:
    """Ordered plan for adapter execution."""

    def __init__(
        self,
        plan: List[str],
        reasons: Dict[str, str],
        source: str = "heuristic",
    ):
        self.plan = plan
        self.reasons = reasons
        self.source = source  # "heuristic" or "llm"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan": self.plan,
            "reasons": self.reasons,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionPlan":
        return cls(
            plan=data.get("plan", []),
            reasons=data.get("reasons", {}),
            source=data.get("source", "unknown"),
        )


class PlannerInput:
    """Input context for the planner."""

    def __init__(
        self,
        integrations: List[Dict[str, Any]],
        last_diagnostics: Optional[Dict[str, Any]] = None,
        goals: Optional[List[str]] = None,
    ):
        self.integrations = integrations
        self.last_diagnostics = last_diagnostics
        self.goals = goals or [
            "connect ingestion to raw warehouse datasets",
            "connect dbt models to warehouse tables",
            "establish full pipeline flow from ingestion to reporting",
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "integrations": self.integrations,
            "last_diagnostics": self.last_diagnostics,
            "goals": self.goals,
        }


# ---------------------------------------------------------------------------
# Deterministic planner (no LLM)
# ---------------------------------------------------------------------------

def plan_heuristic(integrations: List[Dict[str, Any]]) -> ExtractionPlan:
    """
    Deterministic fallback planner.

    Orders adapters by the HEURISTIC_ORDER table: warehouse first,
    then transform, ingestion, orchestration, reporting, infra.
    """
    # Extract tool types from integrations
    tool_types: List[str] = []
    for intg in integrations:
        tool_type = (
            intg.get("tool_type")
            or intg.get("toolType")
            or intg.get("type", "")
        ).lower()
        if tool_type:
            tool_types.append(tool_type)

    # Sort by heuristic order
    sorted_tools = sorted(
        tool_types,
        key=lambda t: HEURISTIC_ORDER.get(t, 99),
    )

    reasons = {}
    for tool in sorted_tools:
        order = HEURISTIC_ORDER.get(tool, 99)
        if order < 20:
            reasons[tool] = "Warehouse: discover all tables and schemas first"
        elif order < 30:
            reasons[tool] = "Transform: map dbt/transform models to discovered warehouse tables"
        elif order < 40:
            reasons[tool] = "Ingestion: connect loaders to raw warehouse tables"
        elif order < 50:
            reasons[tool] = "Orchestration: connect DAGs/workflows to jobs"
        elif order < 60:
            reasons[tool] = "Reporting: connect dashboards to analytics datasets"
        elif order < 70:
            reasons[tool] = "Quality: add test/monitor coverage"
        else:
            reasons[tool] = "Infrastructure/support: add hosting and version control context"

    return ExtractionPlan(
        plan=sorted_tools,
        reasons=reasons,
        source="heuristic",
    )


# ---------------------------------------------------------------------------
# LLM-driven planner
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are a Data Pipeline Extraction Planner.

Given a list of integrations (tools connected to a data pipeline), determine the optimal ORDER in which to run lineage extraction adapters.

CRITICAL RULES:
1) Output MUST be valid JSON ONLY. No prose, no markdown.
2) The plan must include ALL integrations from the input.
3) Order should maximize cross-tool correlation:
   - Run warehouse adapters FIRST (BigQuery, Snowflake, etc.) to discover all tables
   - Run transform adapters SECOND (dbt) to map models to warehouse tables
   - Run ingestion adapters THIRD (n8n, Fivetran) to connect loaders to raw tables
   - Run orchestration FOURTH (Airflow) to connect DAGs to jobs
   - Run reporting LAST (Looker, Tableau) to connect dashboards to datasets
4) If last_diagnostics show specific gaps, adjust order to fill those gaps first.

OUTPUT SCHEMA:
{
  "plan": ["adapter_name_1", "adapter_name_2", ...],
  "reasons": {
    "adapter_name_1": "why this adapter runs at this position",
    "adapter_name_2": "why this adapter runs at this position"
  }
}

Return ONLY the JSON object."""


async def plan_with_llm(
    planner_input: PlannerInput,
    provider: str = "anthropic",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ExtractionPlan:
    """
    Use an LLM to determine adapter execution order.

    Falls back to heuristic ordering if LLM call fails.
    """
    input_json = json.dumps(planner_input.to_dict(), default=str)

    try:
        if provider == "anthropic":
            result = await _call_anthropic_planner(input_json, model, api_key)
        elif provider == "openai":
            result = await _call_openai_planner(input_json, model, api_key)
        else:
            logger.warning("[Planner] Unknown provider '%s', using heuristic", provider)
            return plan_heuristic(planner_input.integrations)

        plan = ExtractionPlan(
            plan=result.get("plan", []),
            reasons=result.get("reasons", {}),
            source="llm",
        )

        # Validate: ensure all integrations are in the plan
        input_tools = {
            (i.get("tool_type") or i.get("toolType") or i.get("type", "")).lower()
            for i in planner_input.integrations
        }
        plan_tools = set(plan.plan)
        missing = input_tools - plan_tools
        if missing:
            logger.warning(
                "[Planner] LLM plan missing integrations: %s, appending",
                missing,
            )
            for tool in sorted(missing):
                plan.plan.append(tool)
                plan.reasons[tool] = "Added by validator (missing from LLM output)"

        return plan

    except Exception as e:
        logger.error("[Planner] LLM call failed: %s, falling back to heuristic", e)
        return plan_heuristic(planner_input.integrations)


async def _call_anthropic_planner(
    input_json: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.AsyncAnthropic(api_key=key, max_retries=2)
    response = await client.messages.create(
        model=model or "claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0.0,
        system=PLANNER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": input_json}],
    )

    raw_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw_text += block.text

    return _parse_json(raw_text)


async def _call_openai_planner(
    input_json: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    import openai

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY not set")

    client = openai.AsyncOpenAI(api_key=key, max_retries=2)
    response = await client.chat.completions.create(
        model=model or "gpt-4o",
        max_tokens=2048,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": input_json},
        ],
    )

    raw_text = response.choices[0].message.content or "{}"
    return _parse_json(raw_text)


def _parse_json(raw_text: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, handling markdown fences."""
    text = raw_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    logger.error("[Planner] Failed to parse LLM response: %s...", text[:200])
    return {"plan": [], "reasons": {}}
