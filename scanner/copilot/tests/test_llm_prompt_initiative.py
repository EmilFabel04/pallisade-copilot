"""The system prompt must forbid the LLM from asking the user for information
that is either already in the prompt context (integration config) or
retrievable via a tool call (monitor state, lineage, run history)."""
from copilot.context_builder import CopilotContext
from copilot.llm import CopilotLLM


def _llm() -> CopilotLLM:
    return CopilotLLM.__new__(CopilotLLM)


def test_prompt_forbids_asking_for_info_in_context_or_tools():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why are my dbt core monitors failing")

    # Must contain an explicit don't-ask rule.
    lower = prompt.lower()
    assert "do not ask" in lower or "don't ask" in lower or "never ask" in lower, (
        "prompt must contain an explicit instruction not to ask for info that is "
        "available in context or via tools"
    )
    # Must call out the specific category of mistake we just observed: asking
    # the user about integration config that's already in the prompt.
    assert "integration" in lower
    # Must steer toward calling tools instead.
    assert "tool" in lower


def test_prompt_lists_examples_of_what_not_to_ask():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="x")

    # The prompt should mention concrete examples so the LLM recognises the
    # pattern: integration config (repo, branch), monitor state, lineage.
    lower = prompt.lower()
    assert any(kw in lower for kw in ("github_repo", "github repo", "repo and branch", "repository"))
