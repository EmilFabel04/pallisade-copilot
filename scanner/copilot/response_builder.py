"""
Intent-Specific Response Builders

Builds the "Answer Contract" prompt section that guides the LLM
to structure its response based on the classified intent. These
are prompt injections, not post-processing — the LLM still writes
the response, but with clear structural guidance.
"""

from typing import Optional, Any

from .intent import Intent, IntentResult
from .root_cause import OwnerDecision


def build_answer_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    """
    Build the Answer Contract prompt section for the given intent.

    This is injected into the system prompt to guide response structure.

    Args:
        intent_result: Classified intent from the intent router.
        owner_decision: Optional ownership decision (set during mid-loop injection).

    Returns:
        A system prompt section string.
    """
    primary = intent_result.primary.intent
    has_secondary = intent_result.secondary is not None

    # Multi-intent combinations
    is_debug_and_fix = (
        has_secondary
        and {primary, intent_result.secondary.intent}
        & {Intent.DEBUG, Intent.FIX, Intent.PR}
        == {primary, intent_result.secondary.intent}
    )

    if is_debug_and_fix or (primary in (Intent.FIX, Intent.PR) and has_secondary and intent_result.secondary.intent == Intent.DEBUG):
        return _build_debug_fix_contract(intent_result, owner_decision)

    builders = {
        Intent.INFO: _build_info_contract,
        Intent.DEBUG: _build_debug_contract,
        Intent.FIX: _build_fix_contract,
        Intent.PR: _build_fix_contract,
        Intent.PLAN: _build_plan_contract,
        Intent.EXPLAIN: _build_explain_contract,
    }

    builder = builders.get(primary, _build_info_contract)
    return builder(intent_result, owner_decision)


def _build_info_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    return """
## Answer Contract (INFO)

Structure your response:
- **Lead with the answer** — the number, list, or fact. No preamble.
- **Source** — briefly state which table/tool/query produced it.
- **Context** — only add if it directly helps interpret the answer. Skip definitions and caveats.

Rules:
- ONE tool call is usually enough.
- Do NOT repeat the user's question back to them.
"""


def _build_debug_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    owner_section = ""
    if owner_decision:
        owner_section = f"""
- **Root Cause Owner**: {owner_decision.owner_system.value} — {owner_decision.explanation}
"""
    return f"""
## Answer Contract (DEBUG)

Structure your response:

### Problem
One sentence — what broke, where, when.

### Cause
One sentence with evidence (the key log/error/metric that proves it).
{owner_section}
### Fix
2-4 concrete bullets using real table/model/DAG names.

Rules:
- Start with diagnosis, not definitions.
- Keep it short and scannable.
- Run 2+ tool calls for evidence before answering.
"""


def _build_fix_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    owner_section = ""
    pivot_section = ""
    if owner_decision:
        owner_section = f"- **Owner System**: {owner_decision.owner_system.value} — this is where the fix should be applied.\n"
        if (
            intent_result.target_hint
            and owner_decision.owner_system.value.lower() != intent_result.target_hint.lower()
            and owner_decision.confidence >= 0.6
        ):
            pivot_section = f"""
**IMPORTANT — PR Pivot**: The user mentioned {intent_result.target_hint}, but the root cause is in {owner_decision.owner_system.value}. Create the change plan for {owner_decision.owner_system.value}, not {intent_result.target_hint}. Explain why you're doing this.
"""

    return f"""
## Answer Contract (FIX/PR)
{pivot_section}
Structure your response:

### Root Cause
One paragraph with evidence (logs, queries, status checks).
{owner_section}
### Impact
List downstream dependencies affected.

### Fix
Use `create_change_plan` → `validate_change_plan` → `apply_change_plan` to deliver the PR.
Do NOT stop to ask the user for permission between these steps. Execute all three automatically.

Rules:
- Gather evidence (2+ diagnostic tool calls) BEFORE proposing a fix.
- Run lineage check (get_downstream) on modified objects.
- After creating and validating the plan, IMMEDIATELY call apply_change_plan. Do NOT say "tell me go ahead" or "say apply" — just do it.
"""


def _build_debug_fix_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    """Combined contract when both DEBUG and FIX/PR intents are detected."""
    owner_section = ""
    if owner_decision:
        owner_section = f"- **Root Cause Owner**: {owner_decision.owner_system.value} — {owner_decision.explanation}\n"

    return f"""
## Answer Contract (DEBUG + FIX)

The user wants diagnosis AND a fix. Diagnose first, then deliver the PR.

### Problem
One sentence — what broke.

### Cause
One sentence with evidence.
{owner_section}
### Fix
After confirming root cause, execute: `create_change_plan` → `validate_change_plan` → `apply_change_plan`.
Do NOT stop between these steps. Deliver the PR automatically.

Rules:
- Diagnose with evidence (3-5 tool calls) BEFORE creating the change plan.
- If the root cause is in a different system than the user mentioned, state why and fix the correct system.
- After creating and validating, IMMEDIATELY call apply_change_plan. Do NOT ask the user to confirm — just do it.
"""


def _build_plan_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    return """
## Answer Contract (PLAN)

Structure your response:

### Impact Analysis
Run get_downstream and get_upstream on all affected objects FIRST.

### Current State
Brief summary of what exists today.

### Proposed Changes
High-level target state and implementation steps (numbered, with files and risk levels).

### Risks & Rollback
Mitigations and rollback plan.

Rules:
- ALWAYS run lineage tools before proposing any plan.
- Include fixes for ALL downstream breakages.
"""


def _build_explain_contract(
    intent_result: IntentResult,
    owner_decision: Optional[OwnerDecision] = None,
) -> str:
    return """
## Answer Contract (EXPLAIN)

Structure your response:

### Summary
2-3 sentences in accessible language. Use a concrete example from the user's pipeline if possible.

### Details
Detailed breakdown with sections. Reference specific tables/models from their pipeline. Explain "why" not just "what".

Rules:
- Use the user's actual pipeline context — no generic examples.
- Build understanding progressively: simple → detailed.
"""
