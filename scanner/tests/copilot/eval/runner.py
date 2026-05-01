"""Eval runner: load corpus, run cases, score results.

Two modes:

* **Static** (default, no API cost): runs the offline parts of the
  copilot stack — intent classifier, mode mapping, tool-call expectations
  against a stub copilot — and reports pass/fail per case. This is the
  mode used by the unit-test suite (``test_eval_runner.py``) and by
  prompt-tuning sessions where the goal is to confirm the corpus loads
  and the static expectations hold.

* **Live** (opt-in, real LLM calls): runs each case end-to-end through
  the actual copilot, hitting OpenAI / Anthropic. Burns tokens. Gated
  by an explicit flag so unit tests never accidentally trigger it.

CLI:
    # Static (free)
    python -m scanner.tests.copilot.eval.runner

    # Live (real API calls)
    python -m scanner.tests.copilot.eval.runner --live

Output: per-case pass/fail with which expectations failed, plus
aggregate pass rate broken down by intent.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import yaml

from copilot.intent import Intent, classify_intent, intent_to_mode


CORPUS_PATH = Path(__file__).parent / "corpus.yaml"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class Expect:
    """Programmatic expectations for a single case."""
    tool_calls: List[str] = field(default_factory=list)
    forbidden_tools: List[str] = field(default_factory=list)
    sql_pattern: Optional[str] = None
    mentions: List[str] = field(default_factory=list)
    forbidden_mentions: List[str] = field(default_factory=list)
    intent_confidence: Optional[float] = None


@dataclass
class Case:
    """One corpus entry."""
    id: str
    query: str
    intent: Optional[str] = None
    mode: Optional[str] = None
    expect: Expect = field(default_factory=Expect)


@dataclass
class CheckResult:
    """One assertion result."""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    """Aggregated assertion results for a case."""
    case_id: str
    intent: Optional[str]
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def load_corpus(path: Path = CORPUS_PATH) -> List[Case]:
    """Parse ``corpus.yaml`` into ``Case`` objects.

    Raises ``ValueError`` on duplicate ids or malformed entries — the
    corpus is supposed to be hand-curated, so silent skips would hide
    real authoring bugs.
    """
    raw = yaml.safe_load(path.read_text())
    cases_raw = raw.get("cases") if isinstance(raw, dict) else None
    if not isinstance(cases_raw, list):
        raise ValueError(f"{path}: top-level 'cases' must be a list")

    seen: set = set()
    cases: List[Case] = []
    for entry in cases_raw:
        if "id" not in entry or "query" not in entry:
            raise ValueError(f"corpus entry missing id/query: {entry!r}")
        if entry["id"] in seen:
            raise ValueError(f"duplicate corpus id: {entry['id']}")
        seen.add(entry["id"])
        expect_raw = entry.get("expect") or {}
        cases.append(Case(
            id=entry["id"],
            query=entry["query"],
            intent=entry.get("intent"),
            mode=entry.get("mode"),
            expect=Expect(
                tool_calls=list(expect_raw.get("tool_calls") or []),
                forbidden_tools=list(expect_raw.get("forbidden_tools") or []),
                sql_pattern=expect_raw.get("sql_pattern"),
                mentions=list(expect_raw.get("mentions") or []),
                forbidden_mentions=list(expect_raw.get("forbidden_mentions") or []),
                intent_confidence=expect_raw.get("intent_confidence"),
            ),
        ))
    return cases


# ---------------------------------------------------------------------------
# Static checks (no LLM calls)
# ---------------------------------------------------------------------------


def run_static_checks(case: Case) -> CaseResult:
    """Run the offline assertions for a case.

    These cover the parts of behavior that don't need a live LLM:
    intent classification, mode mapping, and intent confidence floor.
    """
    classified = classify_intent(case.query)
    actual_intent = classified.primary.intent
    actual_mode = intent_to_mode(classified)

    result = CaseResult(case_id=case.id, intent=actual_intent.name)

    if case.intent is not None:
        expected = Intent[case.intent]
        result.checks.append(CheckResult(
            name="intent",
            passed=(actual_intent == expected),
            detail=f"expected {expected.name}, got {actual_intent.name}",
        ))

    if case.mode is not None:
        result.checks.append(CheckResult(
            name="mode",
            passed=(actual_mode == case.mode),
            detail=f"expected {case.mode!r}, got {actual_mode!r}",
        ))

    if case.expect.intent_confidence is not None:
        floor = case.expect.intent_confidence
        result.checks.append(CheckResult(
            name="intent_confidence",
            passed=(classified.primary.score >= floor),
            detail=f"expected >= {floor}, got {classified.primary.score:.2f}",
        ))

    return result


# ---------------------------------------------------------------------------
# Live checks (LLM-dependent — stubbed)
# ---------------------------------------------------------------------------


def check_tool_calls(case: Case, observed_tools: Sequence[str]) -> List[CheckResult]:
    """Verify expected tool calls appear in the trace and forbidden ones don't."""
    out: List[CheckResult] = []
    observed = list(observed_tools)
    for required in case.expect.tool_calls:
        out.append(CheckResult(
            name=f"tool_call:{required}",
            passed=(required in observed),
            detail=f"observed={observed}",
        ))
    for forbidden in case.expect.forbidden_tools:
        out.append(CheckResult(
            name=f"no_tool_call:{forbidden}",
            passed=(forbidden not in observed),
            detail=f"observed={observed}",
        ))
    return out


def check_sql_pattern(case: Case, observed_sql: Optional[str]) -> Optional[CheckResult]:
    """Match generated SQL against the expected regex (if any)."""
    if case.expect.sql_pattern is None:
        return None
    if observed_sql is None:
        return CheckResult(
            name="sql_pattern",
            passed=False,
            detail=f"no SQL produced; pattern={case.expect.sql_pattern!r}",
        )
    return CheckResult(
        name="sql_pattern",
        passed=bool(re.search(case.expect.sql_pattern, observed_sql)),
        detail=f"pattern={case.expect.sql_pattern!r}, sql={observed_sql[:120]!r}",
    )


def check_mentions(case: Case, response_text: str) -> List[CheckResult]:
    """Check for required and forbidden substrings in the response text."""
    out: List[CheckResult] = []
    for needle in case.expect.mentions:
        out.append(CheckResult(
            name=f"mentions:{needle}",
            passed=(needle.lower() in response_text.lower()),
        ))
    for needle in case.expect.forbidden_mentions:
        out.append(CheckResult(
            name=f"forbidden:{needle}",
            passed=(needle.lower() not in response_text.lower()),
        ))
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


# Type for a live-eval driver: takes a query, returns
# (tool_names, generated_sql, response_text). Implementations stitch the
# real copilot/MaaS stack into this contract; tests inject a stub.
LiveDriver = Callable[[str], Dict[str, Any]]


def run_corpus(
    corpus: Optional[List[Case]] = None,
    *,
    live_driver: Optional[LiveDriver] = None,
) -> List[CaseResult]:
    """Run every case and return per-case results.

    When ``live_driver`` is None, only static checks fire — safe to run
    in unit tests, no API cost. Pass a driver to additionally run the
    live tool-call / SQL / mentions checks.
    """
    cases = corpus if corpus is not None else load_corpus()
    results: List[CaseResult] = []
    for case in cases:
        cr = run_static_checks(case)
        if live_driver is not None:
            observed = live_driver(case.query) or {}
            cr.checks.extend(check_tool_calls(
                case, observed.get("tool_calls", []),
            ))
            sql_check = check_sql_pattern(case, observed.get("sql"))
            if sql_check is not None:
                cr.checks.append(sql_check)
            cr.checks.extend(check_mentions(
                case, observed.get("response_text", ""),
            ))
        results.append(cr)
    return results


def summarize(results: List[CaseResult]) -> Dict[str, Any]:
    """Aggregate stats: overall pass rate plus per-intent breakdown."""
    by_intent: Dict[str, Dict[str, int]] = {}
    total_pass = 0
    for r in results:
        bucket = by_intent.setdefault(r.intent or "_unknown", {"pass": 0, "fail": 0})
        if r.passed:
            bucket["pass"] += 1
            total_pass += 1
        else:
            bucket["fail"] += 1
    return {
        "total": len(results),
        "passed": total_pass,
        "pass_rate": (total_pass / len(results)) if results else 0.0,
        "by_intent": by_intent,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_live_driver():  # pragma: no cover — wired in when the user opts in
    """Factory for the real-LLM driver. Lazily imports the copilot stack
    so that a static run doesn't pull in heavy modules (or env)."""
    raise NotImplementedError(
        "Live mode is not wired up yet — connect this to the copilot "
        "chat path (e.g. CopilotLLM.chat or MAASOrchestrator.chat_stream) "
        "and have it return {tool_calls, sql, response_text}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the copilot eval corpus.")
    parser.add_argument("--live", action="store_true", help="Run live LLM calls (costs tokens).")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    driver = _build_live_driver() if args.live else None
    results = run_corpus(live_driver=driver)
    summary = summarize(results)

    if args.json:
        print(json.dumps({
            "summary": summary,
            "cases": [
                {
                    "id": r.case_id,
                    "intent": r.intent,
                    "passed": r.passed,
                    "checks": [
                        {"name": c.name, "passed": c.passed, "detail": c.detail}
                        for c in r.checks
                    ],
                }
                for r in results
            ],
        }, indent=2))
    else:
        for r in results:
            tag = "PASS" if r.passed else "FAIL"
            print(f"[{tag}] {r.case_id} ({r.intent})")
            if not r.passed:
                for c in r.checks:
                    if not c.passed:
                        print(f"    × {c.name}: {c.detail}")
        print()
        print(
            f"Pass rate: {summary['passed']}/{summary['total']} "
            f"({summary['pass_rate']:.0%})"
        )
        for intent, bucket in sorted(summary["by_intent"].items()):
            total = bucket["pass"] + bucket["fail"]
            print(f"  {intent}: {bucket['pass']}/{total}")

    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
