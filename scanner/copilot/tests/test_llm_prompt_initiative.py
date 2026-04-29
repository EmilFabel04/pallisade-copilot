"""The system prompt must forbid the LLM from asking the user for information
that is either already in the prompt context (integration config) or
retrievable via a tool call (monitor state, lineage, run history)."""
from copilot.context_builder import CopilotContext
from copilot.llm import CopilotLLM, _should_force_initial_tool


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


def test_prompt_contains_no_tenant_specific_strings():
    """Prompt is shared across tenants — it must never hardcode a specific
    user's repo name, GitHub handle, or pipeline name as an illustrative
    example. Add new tokens to BANNED if a tenant-specific reference slips in."""
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why are my dbt core monitors failing")

    BANNED = ["EmilFabel", "emilfabel", "pallisade-test", "pallisade-test-pipeline"]
    leaks = [tok for tok in BANNED if tok in prompt]
    assert not leaks, f"prompt contains tenant-specific tokens: {leaks}"


def test_force_initial_tool_triggers_on_investigative_queries():
    # Each of these should flip the LLM into "must call a tool first" mode.
    investigative = [
        "why are my dbt core monitors failing",
        "is dbt connected",
        "is bigquery working",
        "show me failing monitors",
        "which monitors are red",
        "what's wrong with my pipeline",
        "investigate the source validation error",
        "check downstream of orders table",
        "what is the status of my integrations",
    ]
    for q in investigative:
        assert _should_force_initial_tool(q), f"should force tool for: {q!r}"


def test_debug_mode_prompt_does_not_prescribe_problem_cause_fix_template():
    """DEBUG mode previously hardcoded `**Problem:** / **Cause:** / **Fix:** /
    **Impact:**` as the response template, plus a rule "No bold section headers
    other than Problem / Cause / Fix / Impact" that actively *required* the
    template. Both contradicted the no-labels rule in llm.py. This regression
    catches the old template returning."""
    from copilot.modes import DEBUG_PROMPT
    lower = DEBUG_PROMPT.lower()

    # The old prescriptive rule must be gone (the one that forced the labels).
    assert "no bold section headers other than problem" not in lower

    # The literal template body — "**Problem:** One sentence stating ..." — must be gone.
    assert "**problem:** one sentence stating" not in lower
    assert "**cause:** one sentence explaining" not in lower
    assert "**fix:** 2-4 bullet points" not in lower
    assert "**impact:** one line listing" not in lower

    # Explicit forbid-the-labels instruction must be present.
    assert ("do not use" in lower or "don't use" in lower), (
        "DEBUG prompt should explicitly forbid the labelled-section template"
    )

    # The substance the LLM still needs to produce (failure layer, evidence,
    # fix steps, downstream impact) must remain — we removed the template,
    # not the requirements.
    assert "failure layer" in lower
    assert "downstream" in lower


def test_prompt_steers_to_adjacent_path_on_empty_or_unavailable_tool_result():
    """When a primary tool returns empty or 'not available', the LLM was
    surrendering ('you don't have dbt run history') instead of trying an
    adjacent integration (Airflow logs, warehouse JOBS history). The prompt
    must explicitly steer toward adjacent-path lookup."""
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why are my dbt core monitors failing")
    lower = prompt.lower()

    # Names the failure mode explicitly.
    assert "adjacent" in lower or "fallback" in lower

    # Calls out the specific dbt run history → Airflow / JOBS path that the
    # LLM missed in production.
    assert "get_dbt_run_history" in lower or "dbt run history" in lower
    assert "airflow" in lower
    assert "information_schema.jobs" in lower

    # Calls out the empty-with-filter monitor case (re-run without filter).
    assert "without the status filter" in lower or "without the filter" in lower

    # Forbids surrendering / asking for a screenshot.
    assert "screenshot" in lower


def test_prompt_discourages_templated_problem_cause_fix_labels():
    """The LLM was emitting `Problem:` / `Cause:` / `Fix:` as literal section
    labels on every debugging answer because the prompt said 'state the problem,
    cause, and fix'. The prompt should now explicitly discourage that template."""
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why is my pipeline broken")
    lower = prompt.lower()

    # The prompt must not prescribe a 'problem, cause, and fix' template.
    assert "problem, cause, and fix" not in lower
    # The prompt must explicitly tell the LLM not to use those labels.
    assert "cause:" in lower and "fix:" in lower, (
        "prompt should reference the labels in a 'do NOT use these' context"
    )
    assert any(
        kw in lower
        for kw in ("do not template", "don't template", "do not use", "avoid label")
    ), "prompt should explicitly forbid the templated label style"


def test_force_initial_tool_skips_non_investigative_queries():
    # Greetings, thanks, and pure-explainer questions should not force a tool.
    benign = [
        "",
        "hi",
        "thanks!",
        "what is a data warehouse",
        "explain primary keys",
        "write me a sql query that finds duplicates",
    ]
    for q in benign:
        assert not _should_force_initial_tool(q), f"should NOT force tool for: {q!r}"
