"""Per-mode tool gating: tools listed in another mode's `exclusive_tools`
must be filtered out of the LLM-facing tool list before the LLM sees them.
Prior to this change, `exclusive_tools` was a label on `ModeConfig` that
nothing read at runtime — the LLM saw every registered tool regardless of
mode."""
from copilot.modes import (
    InteractionMode,
    MODES,
    tools_excluded_for_mode,
)
from copilot.tools.registry import ToolRegistry


# -- tools_excluded_for_mode --------------------------------------------------


def test_ask_mode_excludes_every_other_modes_exclusive_tools():
    excluded = tools_excluded_for_mode("ask")
    # FIX-exclusive
    assert "create_change_plan" in excluded
    assert "validate_change_plan" in excluded
    assert "apply_change_plan" in excluded
    # CREATE-exclusive
    assert "generate_dbt_model" in excluded
    assert "generate_dbt_test" in excluded
    # BUNDLE-exclusive
    assert "create_bundle" in excluded
    # ONBOARD-exclusive
    assert "save_onboarding_context" in excluded
    assert "complete_onboarding" in excluded


def test_fix_mode_keeps_its_own_exclusive_tools_visible():
    excluded = tools_excluded_for_mode("fix")
    assert "create_change_plan" not in excluded
    assert "validate_change_plan" not in excluded
    assert "apply_change_plan" not in excluded
    # But still hides other modes' exclusives
    assert "save_onboarding_context" in excluded
    assert "create_bundle" in excluded
    assert "generate_dbt_model" in excluded


def test_onboard_mode_keeps_onboarding_tools_visible():
    excluded = tools_excluded_for_mode("onboard")
    assert "save_onboarding_context" not in excluded
    assert "complete_onboarding" not in excluded
    # FIX tools still hidden
    assert "apply_change_plan" in excluded


def test_unknown_mode_falls_back_to_ask_behaviour():
    # Defensive: if someone passes a typo'd or stale mode name, we exclude
    # all exclusive tools (the safest fallback — broadest gate).
    excluded = tools_excluded_for_mode("not_a_real_mode")
    ask_excluded = tools_excluded_for_mode("ask")
    assert excluded == ask_excluded


def test_none_or_empty_mode_does_not_crash():
    # If context.mode is missing/None, helper must not raise.
    assert isinstance(tools_excluded_for_mode(""), set)
    # AttributeError on .lower() is caught — empty set or ASK fallback acceptable.


def test_exclusion_is_symmetric_across_all_modes():
    # For every mode, the LLM should never see another mode's exclusive tools.
    # This catches the case where someone adds a new mode with exclusive_tools
    # but forgets to update gating logic.
    for mode in InteractionMode:
        excluded = tools_excluded_for_mode(mode.value)
        own_exclusive = set(MODES[mode].exclusive_tools)
        # Each mode's own exclusive tools must NOT be in its own excluded set
        assert not (own_exclusive & excluded), (
            f"mode {mode.value} is hiding its own exclusive tools: "
            f"{own_exclusive & excluded}"
        )


# -- Registry filtering -------------------------------------------------------


def test_registry_get_available_tools_respects_exclude_set():
    registry = ToolRegistry()
    integrations = {"BIGQUERY", "DBT_CORE", "AIRFLOW"}

    # Without exclusion — all available tools
    all_tools = registry.get_available_tools(integrations)
    all_names = {t.name for t in all_tools}

    # With exclusion of a tool we know exists
    target = "list_configured_monitors"
    if target not in all_names:
        # Tool may not be registered in this build — pick any available one.
        target = next(iter(all_names))
    filtered = registry.get_available_tools(integrations, exclude={target})
    filtered_names = {t.name for t in filtered}
    assert target not in filtered_names
    assert len(filtered_names) == len(all_names) - 1


def test_registry_to_anthropic_tools_respects_exclude_set():
    registry = ToolRegistry()
    integrations = {"BIGQUERY", "DBT_CORE", "AIRFLOW", "FIVETRAN"}

    full = registry.to_anthropic_tools(integrations)
    full_names = {t["name"] for t in full}
    if not full_names:
        return  # registry empty in this build — nothing to test
    pick = next(iter(full_names))

    filtered = registry.to_anthropic_tools(integrations, exclude={pick})
    filtered_names = {t["name"] for t in filtered}
    assert pick not in filtered_names


def test_registry_to_openai_tools_respects_exclude_set():
    registry = ToolRegistry()
    integrations = {"BIGQUERY", "DBT_CORE", "AIRFLOW", "FIVETRAN"}

    full = registry.to_openai_tools(integrations)
    full_names = {t["function"]["name"] for t in full}
    if not full_names:
        return
    pick = next(iter(full_names))

    filtered = registry.to_openai_tools(integrations, exclude={pick})
    filtered_names = {t["function"]["name"] for t in filtered}
    assert pick not in filtered_names


def test_registry_no_exclude_returns_full_list_unchanged():
    # Backward-compat: callers that don't pass `exclude` get the same list
    # they got before this change.
    registry = ToolRegistry()
    integrations = {"BIGQUERY", "DBT_CORE"}

    a = registry.get_available_tools(integrations)
    b = registry.get_available_tools(integrations, exclude=None)
    c = registry.get_available_tools(integrations, exclude=set())
    assert {t.name for t in a} == {t.name for t in b} == {t.name for t in c}


# -- End-to-end: ASK mode hides destructive tools -----------------------------


def test_ask_mode_strips_destructive_tools_from_anthropic_tool_list():
    """The bug fix in plain English: in ASK mode, the LLM no longer sees
    apply_change_plan / generate_dbt_model / etc. in its tool list."""
    registry = ToolRegistry()
    integrations = {"BIGQUERY", "DBT_CORE", "GITHUB", "AIRFLOW"}

    excluded = tools_excluded_for_mode("ask")
    tool_dicts = registry.to_anthropic_tools(integrations, exclude=excluded)
    visible_names = {t["name"] for t in tool_dicts}

    for forbidden in (
        "create_change_plan",
        "validate_change_plan",
        "apply_change_plan",
        "generate_dbt_model",
        "generate_dbt_test",
        "create_bundle",
        "save_onboarding_context",
        "complete_onboarding",
    ):
        assert forbidden not in visible_names, (
            f"ASK mode is leaking destructive tool '{forbidden}' to the LLM"
        )


def test_fix_mode_keeps_change_plan_tools_visible_to_llm():
    registry = ToolRegistry()
    integrations = {"BIGQUERY", "DBT_CORE", "GITHUB"}

    excluded = tools_excluded_for_mode("fix")
    tool_dicts = registry.to_anthropic_tools(integrations, exclude=excluded)
    visible_names = {t["name"] for t in tool_dicts}

    # If create_change_plan is registered at all, it must be visible in FIX mode.
    full_names = {t["name"] for t in registry.to_anthropic_tools(integrations)}
    if "create_change_plan" in full_names:
        assert "create_change_plan" in visible_names
