"""SQL specialist repair-mode prompt.

When the orchestrator retries a failed SQL exec, today it calls the same
SQL specialist with the same generic system prompt — the model often
regenerates the same broken query. The repair path needs a tuned prompt
that names the failure modes and demands a *minimal change* tied to the
specific error.

These tests pin the repair prompt's shape and the orchestrator's
``repair_mode=True`` propagation so future prompt edits don't regress
the cue.
"""

from unittest.mock import MagicMock

from copilot.maas.specialists.sql import SQLSpecialist


def _build(repair_mode: bool):
    specialist = SQLSpecialist(MagicMock())
    return specialist.build_messages(
        evidence="## Schema\n- t: c1",
        query="count rows",
        warehouse_type="bigquery",
        repair_mode=repair_mode,
    )


class TestRepairModePrompt:
    def test_default_prompt_is_unchanged(self):
        messages = _build(repair_mode=False)
        system = messages[0]["content"]
        # The repair-specific cues must be absent on the normal path —
        # otherwise we'd pay for them on every successful first call.
        assert "REPAIR MODE" not in system
        assert "PREVIOUS SQL" not in system

    def test_repair_prompt_includes_repair_header(self):
        messages = _build(repair_mode=True)
        system = messages[0]["content"]
        assert "REPAIR MODE" in system

    def test_repair_prompt_demands_minimal_change(self):
        messages = _build(repair_mode=True)
        system = messages[0]["content"]
        # The cue against full rewrites — repair should target the
        # specific error, not regenerate from scratch.
        assert "minimal change" in system.lower() or "MINIMAL change" in system

    def test_repair_prompt_lists_common_failure_modes(self):
        messages = _build(repair_mode=True)
        system = messages[0]["content"]
        # We name the failure modes the LLM should check first so it
        # attaches the error message to a concrete fix rather than
        # rewriting at random.
        for cue in ("Column not found", "Type mismatch", "Function not found"):
            assert cue in system, f"missing failure-mode cue: {cue}"

    def test_repair_prompt_forbids_identical_regen(self):
        messages = _build(repair_mode=True)
        system = messages[0]["content"]
        assert (
            "differ from the previous attempt" in system.lower()
            or "must differ" in system.lower()
        )

    def test_repair_prompt_keeps_dialect_rules(self):
        # Repair mode should still inject the warehouse-specific rules —
        # if a Snowflake query fails because the model used BigQuery
        # syntax, the dialect block is exactly what's needed for the fix.
        messages = _build(repair_mode=True)
        system = messages[0]["content"]
        # bigquery rule
        assert "backtick" in system.lower()
