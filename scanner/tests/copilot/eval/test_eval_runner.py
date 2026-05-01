"""Tests for the eval runner.

These pin the runner's behavior against the corpus without making any
real LLM calls. They serve two purposes:

1. **Regression guard**: every static expectation in ``corpus.yaml``
   actually passes today. If a future intent-classifier change causes
   a corpus case to misclassify, the unit suite catches it.

2. **Driver contract**: when item 8 Phase B (live driver) lands, it
   only has to satisfy the contract these tests pin (return a dict
   with ``tool_calls``, ``sql``, ``response_text``).
"""

from pathlib import Path

import pytest

from tests.copilot.eval import runner


CORPUS_PATH = Path(runner.__file__).parent / "corpus.yaml"


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


class TestCorpusLoad:
    def test_corpus_loads_without_errors(self):
        cases = runner.load_corpus()
        assert len(cases) > 0

    def test_corpus_ids_are_unique(self):
        cases = runner.load_corpus()
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))

    def test_each_case_has_query(self):
        for c in runner.load_corpus():
            assert c.query, f"{c.id} has empty query"

    def test_intent_strings_are_valid(self):
        from copilot.intent import Intent

        valid = {i.name for i in Intent}
        for c in runner.load_corpus():
            if c.intent is not None:
                assert c.intent in valid, (
                    f"{c.id} declares unknown intent {c.intent!r}"
                )


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------


class TestStaticChecks:
    def test_corpus_passes_static_checks_today(self):
        """Every case in the shipped corpus must currently pass the
        static checks. If this regresses, either the corpus needs an
        update or the classifier did."""
        results = runner.run_corpus()
        failed = [r for r in results if not r.passed]
        assert not failed, (
            "static eval failures:\n"
            + "\n".join(
                f"  {r.case_id}: " + ", ".join(
                    f"{c.name}({c.detail})" for c in r.checks if not c.passed
                )
                for r in failed
            )
        )

    def test_intent_classification_failure_is_reported(self):
        case = runner.Case(
            id="bogus",
            query="how many orders are there?",  # actually classifies as INFO
            intent="DEBUG",  # wrong
            mode="ask",
        )
        result = runner.run_static_checks(case)
        assert not result.passed
        intent_check = next(c for c in result.checks if c.name == "intent")
        assert not intent_check.passed
        assert "INFO" in intent_check.detail


# ---------------------------------------------------------------------------
# Live-driver contract
# ---------------------------------------------------------------------------


class TestLiveDriverContract:
    def test_live_driver_can_satisfy_tool_call_expectations(self):
        case = runner.Case(
            id="t1",
            query="how many orders are there?",
            intent="INFO",
            mode="ask",
            expect=runner.Expect(
                tool_calls=["query_warehouse"],
                sql_pattern=r"(?i)select\s+count",
            ),
        )

        def stub_driver(query: str):
            return {
                "tool_calls": ["query_warehouse"],
                "sql": "SELECT COUNT(*) FROM orders",
                "response_text": "There are 42 orders.",
            }

        results = runner.run_corpus([case], live_driver=stub_driver)
        assert results[0].passed, [
            (c.name, c.detail) for c in results[0].checks if not c.passed
        ]

    def test_live_driver_failures_surface_in_checks(self):
        """A driver that returns the wrong tool / wrong SQL produces
        failing checks with diagnostic detail. Important: a silent pass
        on a regressed prompt would defeat the harness."""
        case = runner.Case(
            id="t2",
            query="how many orders are there?",
            intent="INFO",
            expect=runner.Expect(
                tool_calls=["query_warehouse"],
                forbidden_tools=["execute_dangerous_thing"],
                sql_pattern=r"(?i)select\s+count",
                mentions=["orders"],
                forbidden_mentions=["error"],
            ),
        )

        def bad_driver(query: str):
            return {
                "tool_calls": ["execute_dangerous_thing"],
                "sql": "DELETE FROM orders",
                "response_text": "fatal error happened",
            }

        results = runner.run_corpus([case], live_driver=bad_driver)
        result = results[0]
        assert not result.passed
        failed_names = {c.name for c in result.checks if not c.passed}
        assert "tool_call:query_warehouse" in failed_names
        assert "no_tool_call:execute_dangerous_thing" in failed_names
        assert "sql_pattern" in failed_names
        assert "mentions:orders" in failed_names
        assert "forbidden:error" in failed_names


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_summary_has_pass_rate_and_per_intent(self):
        results = [
            runner.CaseResult(case_id="a", intent="INFO", checks=[
                runner.CheckResult("intent", True),
            ]),
            runner.CaseResult(case_id="b", intent="INFO", checks=[
                runner.CheckResult("intent", False),
            ]),
            runner.CaseResult(case_id="c", intent="DEBUG", checks=[
                runner.CheckResult("intent", True),
            ]),
        ]
        summary = runner.summarize(results)
        assert summary["total"] == 3
        assert summary["passed"] == 2
        assert summary["pass_rate"] == pytest.approx(2 / 3)
        assert summary["by_intent"]["INFO"] == {"pass": 1, "fail": 1}
        assert summary["by_intent"]["DEBUG"] == {"pass": 1, "fail": 0}


# ---------------------------------------------------------------------------
# CLI safety
# ---------------------------------------------------------------------------


class TestLiveDriverDefaultsOff:
    def test_run_corpus_does_not_call_live_driver_by_default(self):
        """``run_corpus()`` with no driver MUST NOT call any LLM. This
        is what keeps unit tests free from API charges."""
        cases = [runner.Case(id="x", query="hi", intent="INFO", mode="ask")]
        # No driver — purely offline.
        results = runner.run_corpus(cases, live_driver=None)
        # Only the static intent check should have run (case has no
        # mode/intent_confidence specified beyond intent+mode).
        names = {c.name for c in results[0].checks}
        assert names == {"intent", "mode"}

    def test_build_live_driver_is_explicit(self):
        """The factory raises until a real driver is wired up — it
        must never silently no-op."""
        with pytest.raises(NotImplementedError):
            runner._build_live_driver()
