"""The system prompt must instruct the LLM to use list_configured_monitors
when asked about the user's saved monitors, instead of immediately reaching
for run_coverage_monitor."""
from copilot.context_builder import CopilotContext
from copilot.llm import CopilotLLM


def _llm() -> CopilotLLM:
    return CopilotLLM.__new__(CopilotLLM)


def test_prompt_directs_llm_to_list_configured_monitors_first():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why are my dbt core monitors failing")

    assert "list_configured_monitors" in prompt
    assert "get_monitor_run_history" in prompt
    # Must explicitly forbid the wandering pattern that produced the bug.
    assert "before" in prompt.lower() and "run_coverage_monitor" in prompt


def test_prompt_explains_what_dbt_core_monitors_are():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="x")
    assert "DBT_CORE_SOURCE_VALIDATION" in prompt
    assert "DBT_CORE_REF_INTEGRITY" in prompt
