"""Tests that the system prompt contains the guidance added to prevent
the two specific hallucinations observed: misreporting Fivetran staleness
from per-row metadata, and presenting ad-hoc run_coverage_monitor errors
as if they were saved-monitor failures."""
from copilot.context_builder import CopilotContext
from copilot.llm import CopilotLLM


def _llm() -> CopilotLLM:
    return CopilotLLM.__new__(CopilotLLM)


def test_prompt_explains_fivetran_synced_is_per_row_not_per_run():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why is dbt failing")

    assert "_fivetran_synced" in prompt
    # Should explicitly call out that staleness != broken connector
    assert "row" in prompt.lower()
    # Should redirect to the dedicated tool for connector health
    assert "get_fivetran_sync_logs" in prompt


def test_prompt_warns_against_misreporting_run_coverage_monitor_errors():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why is dbt failing")

    assert "run_coverage_monitor" in prompt
    # Should clarify that errors there are about the tool call, not user monitors
    assert "ad-hoc" in prompt.lower() or "one-off" in prompt.lower()
