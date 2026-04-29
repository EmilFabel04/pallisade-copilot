"""
Per-intent budget constraints and GPT-5 orchestrator prompt builder.

Budgets enforce maximum tool calls, specialist invocations, and retries per intent.
The orchestrator prompt is short (~300 lines vs ~800 for the existing system prompt)
because specialists have already done the heavy lifting.
"""

from dataclasses import dataclass
from typing import Dict

from copilot.intent import Intent


@dataclass(frozen=True)
class IntentBudget:
    """Budget constraints for a single intent type."""
    max_tool_calls: int
    max_specialist_calls: int
    max_revisions: int
    description: str


class BudgetTracker:
    """
    Live tracker that enforces an IntentBudget across a single MAAS request.

    Centralizes the "are we still allowed to spend?" decision so SQL
    execution, repair, and post-narration tool calls all check the same
    counters. Without this the soft `if count >= max: break` checks were
    scattered and easy to skip.
    """

    def __init__(self, budget: IntentBudget):
        self._budget = budget
        self.tool_calls = 0
        self.specialist_calls = 0
        self.exhausted = False

    @property
    def budget(self) -> IntentBudget:
        return self._budget

    def can_spend_tool(self, n: int = 1) -> bool:
        return self.tool_calls + n <= self._budget.max_tool_calls

    def can_spend_specialist(self, n: int = 1) -> bool:
        return self.specialist_calls + n <= self._budget.max_specialist_calls

    def consume_tool(self, n: int = 1) -> None:
        self.tool_calls += n
        if self.tool_calls >= self._budget.max_tool_calls:
            self.exhausted = True

    def consume_specialist(self, n: int = 1) -> None:
        self.specialist_calls += n

    def remaining_tool_budget(self) -> int:
        return max(0, self._budget.max_tool_calls - self.tool_calls)


INTENT_BUDGETS: Dict[Intent, IntentBudget] = {
    Intent.INFO: IntentBudget(
        max_tool_calls=3,
        max_specialist_calls=1,
        max_revisions=1,
        description="Data question: schema → SQL specialist → verify → execute → synthesize",
    ),
    Intent.DEBUG: IntentBudget(
        max_tool_calls=8,
        max_specialist_calls=2,
        max_revisions=1,
        description="Investigation: evidence → Logs specialist → triage → GPT-5 narrates",
    ),
    Intent.FIX: IntentBudget(
        max_tool_calls=6,
        max_specialist_calls=2,
        max_revisions=1,
        description="Fix: evidence → Logs triage → GPT-5 create_change_plan → validate → narrate",
    ),
    Intent.PR: IntentBudget(
        max_tool_calls=6,
        max_specialist_calls=2,
        max_revisions=1,
        description="PR: same as FIX, then apply_change_plan",
    ),
    Intent.PLAN: IntentBudget(
        max_tool_calls=6,
        max_specialist_calls=1,
        max_revisions=1,
        description="Plan: upstream/downstream evidence → GPT-5 plan contract",
    ),
    Intent.EXPLAIN: IntentBudget(
        max_tool_calls=3,
        max_specialist_calls=0,
        max_revisions=0,
        description="Explain: GPT-5 only, with schema/lineage context",
    ),
}


def get_budget(intent: Intent) -> IntentBudget:
    """Get budget for an intent, defaulting to INFO if unknown."""
    return INTENT_BUDGETS.get(intent, INTENT_BUDGETS[Intent.INFO])


def build_orchestrator_prompt(
    evidence_blob: str,
    specialist_results: str,
    intent: Intent,
    mode_prompt: str,
    answer_contract: str,
    data_stack_context: str = "",
) -> str:
    """
    Build the scoped GPT-5 orchestrator prompt.

    Much shorter than the full CopilotLLM system prompt because:
    - Schema is sliced to only relevant tables
    - Evidence is bounded
    - Specialist results are pre-computed
    - GPT-5's job is ONLY to narrate + call tools if needed
    """
    stack_section = ""
    if data_stack_context:
        stack_section = f"\n{data_stack_context}\n"

    return f"""You are the orchestrator for Pallisade Scout, a data pipeline assistant.

## Your Role
- You are the FINAL narrator. Specialists have already done the heavy lifting.
- Synthesize specialist results into a clear, scannable answer for the user.
- You are ALSO the only tool-caller. If you need to execute tools (e.g., \
create_change_plan, apply_change_plan, query_warehouse, check_server_health), call them directly.
- You are the judge: if a specialist result looks wrong, note the discrepancy \
and explain what you would do differently.

## Rules
1. Never dump raw JSON. Synthesize specialist outputs into human-readable prose.
2. Use real table/column/project names — never placeholders.
3. Follow the Answer Contract below for response structure.
4. Lead with the answer, not the methodology.
5. When confirming destructive actions, the tool confirmation system will handle it.
6. Keep responses concise: 3-5 bullet points over paragraphs.
7. Use available tools proactively — if the user asks about a server, call check_server_health or analyze_server_logs.
{stack_section}
{mode_prompt}

{answer_contract}

## Evidence (pre-collected)
{evidence_blob}

## Specialist Results
{specialist_results}"""
