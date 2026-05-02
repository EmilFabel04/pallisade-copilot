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
    python -m tests.copilot.eval.runner

    # Live (real API calls — costs ~$0.50 per full corpus run)
    OPENAI_API_KEY=sk-...  python -m tests.copilot.eval.runner --live
    # or
    ANTHROPIC_API_KEY=...  python -m tests.copilot.eval.runner --live

Live mode constructs a synthetic ``CopilotContext`` (one BigQuery
integration + a tiny stubbed schema for the ``orders`` and ``events``
tables) and patches ``ToolExecutor.execute`` so tool calls return
canned successes — we measure whether the LLM picks the right tool
with the right SQL shape, not whether a real warehouse responds.

Output: per-case pass/fail with which expectations failed, plus
aggregate pass rate broken down by intent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Live driver — wires the real copilot stack into the LiveDriver contract.
#
# Design notes:
#
# * **Synthetic context, real LLM.** Cases run against a fabricated
#   ``CopilotContext`` with one BigQuery integration and a tiny stubbed
#   schema (orders + events). This is enough surface for the corpus to
#   exercise tool selection and SQL shape without needing a real
#   warehouse connection. The intent classifier still runs on the raw
#   query so the orchestrator's routing matches production.
#
# * **Stub tool executor.** ``ToolExecutor.execute`` is patched for the
#   duration of each case so tool calls return canned successes.
#   We care that the LLM *chose* the right tool with the right shape of
#   arguments — not whether a real warehouse responds. Without this stub
#   most cases would fail on the first ``query_warehouse`` call.
#
# * **Stream walker.** Tool calls and SQL come from
#   ``tool_call_start`` events (which fire BEFORE execution, so the stub
#   doesn't affect them). Response text comes from ``text_delta``.
#
# Cost: ~$0.50 per full corpus run with a frontier OpenAI / Anthropic
# model. The factory checks for an API key up front so a missing key
# fails fast instead of crashing deep in the SDK.
# ---------------------------------------------------------------------------


# Tools whose first argument named ``sql`` (or that contain a SQL string in
# their args) should populate the extractor's ``sql`` field. Listed
# explicitly so tool-name typos in the corpus don't silently match.
_SQL_BEARING_TOOLS = {"query_warehouse"}


def _extract_sql_from_args(tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """Pull a SQL string out of a tool call's arguments, if any.

    Only ``query_warehouse``-shaped tools are considered — see
    ``_SQL_BEARING_TOOLS``. We don't sniff every tool's args for "looks
    like SQL" because false positives (e.g. a description field that
    contains the word SELECT) would corrupt the eval signal.
    """
    if tool_name not in _SQL_BEARING_TOOLS:
        return None
    sql = args.get("sql") if isinstance(args, dict) else None
    return sql if isinstance(sql, str) and sql.strip() else None


async def _extract_from_stream(events: AsyncIterator[Any]) -> Dict[str, Any]:
    """Walk a StreamEvent async iterator and aggregate the eval result.

    Returns the dict shape the LiveDriver contract requires:
    ``{"tool_calls": [...], "sql": "...", "response_text": "..."}``.

    Captures the FIRST SQL-bearing tool call (subsequent ones overwrite
    only if the first didn't carry SQL) — corpus cases pin one canonical
    SQL shape per query, so the first call is the meaningful one.
    """
    tool_calls: List[str] = []
    sql: Optional[str] = None
    text_parts: List[str] = []

    async for event in events:
        et = event.event_type
        data = event.data or {}
        if et == "tool_call_start":
            name = data.get("tool_name") or ""
            tool_calls.append(name)
            if sql is None:
                candidate = _extract_sql_from_args(name, data.get("arguments") or {})
                if candidate:
                    sql = candidate
        elif et == "text_delta":
            chunk = data.get("content") or ""
            if chunk:
                text_parts.append(chunk)
        elif et == "error":
            # Errors mid-stream don't abort the eval — we still return
            # whatever we collected so the runner can report a partial
            # result rather than a hard failure with no diagnostic.
            text_parts.append(f"\n[stream error: {data.get('message', '')}]")

    return {
        "tool_calls": tool_calls,
        "sql": sql,
        "response_text": "".join(text_parts),
    }


def _build_synthetic_context(query: str):
    """Construct a ``CopilotContext`` for a single eval query.

    Pins one BigQuery integration with a tiny stubbed schema so the
    orchestrator has somewhere to route SQL-bearing intents. Intent is
    classified live (matches production routing) and the mode is mapped
    via ``intent_to_mode``.
    """
    from copilot.context_builder import (
        CopilotContext,
        IntegrationInfo,
        IntegrationLayer,
        TableSchema,
    )

    classified = classify_intent(query)
    mode = intent_to_mode(classified)

    integration = IntegrationInfo(
        id="eval_bq",
        name="Eval BigQuery",
        type="BIGQUERY",
        layer=IntegrationLayer.WAREHOUSE,
        status="ACTIVE",
        config={"project_id": "eval-project", "datasets": ["raw"]},
    )

    schema = {
        "BIGQUERY:raw": [
            TableSchema(
                name="orders",
                dataset="raw",
                project="eval-project",
                warehouse_type="BIGQUERY",
                columns=[
                    {"name": "id", "type": "STRING"},
                    {"name": "customer_id", "type": "STRING"},
                    {"name": "region", "type": "STRING"},
                    {"name": "amount", "type": "NUMERIC"},
                    {"name": "created_at", "type": "TIMESTAMP"},
                ],
                row_count=10000,
            ),
            TableSchema(
                name="events",
                dataset="raw",
                project="eval-project",
                warehouse_type="BIGQUERY",
                columns=[
                    {"name": "event_id", "type": "STRING"},
                    {"name": "event_type", "type": "STRING"},
                    {"name": "user_id", "type": "STRING"},
                    {"name": "ts", "type": "TIMESTAMP"},
                ],
                row_count=500000,
            ),
        ],
    }

    return CopilotContext(
        org_id="_eval",
        query=query,
        integrations=[integration],
        integration_types={"BIGQUERY"},
        warehouse_schema=schema,
        mode=mode,
        intent_result=classified,
    )


def _make_stub_executor_execute():
    """Build the coroutine that replaces ``ToolExecutor.execute``.

    Returns canned ``ToolResult.success=True`` payloads keyed by tool
    name. Anything not specifically mocked returns an empty success so
    the LLM keeps moving instead of branching into error narration.
    """
    from copilot.tools.base import ToolResult

    canned: Dict[str, Any] = {
        "query_warehouse": {"rows": [{"count": 42}], "row_count": 1},
        "list_tables": {"tables": ["raw.orders", "raw.events"]},
        "get_table_stats": {"row_count": 10000, "size_bytes": 1024 * 1024},
        "get_table_stats_batch": {
            "stats": [
                {"table": "raw.orders", "row_count": 10000},
                {"table": "raw.events", "row_count": 500000},
            ]
        },
        "search_knowledge_base": {"results": []},
    }

    async def _stub_execute(self, tool_name: str, arguments: Dict[str, Any]):
        data = canned.get(tool_name, {"ok": True})
        return ToolResult(success=True, data=data)

    return _stub_execute


def _check_live_credentials() -> None:
    """Fail fast with a useful message if no LLM key is configured.

    Without this, the orchestrator falls back to a path that emits an
    ``error`` stream event and the eval reports cryptic "no SQL" /
    "no tool calls" failures across every case.
    """
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
        raise RuntimeError(
            "Live eval requires OPENAI_API_KEY or ANTHROPIC_API_KEY in the "
            "environment. None found. Set one and retry, or omit --live to "
            "run static checks only."
        )


async def _run_query_live(query: str) -> Dict[str, Any]:
    """Execute one eval query against the real copilot stack."""
    from copilot.llm import Message
    from copilot.maas.orchestrator import MAASOrchestrator

    context = _build_synthetic_context(query)
    messages = [Message(role="user", content=query)]
    orchestrator = MAASOrchestrator()

    stub_execute = _make_stub_executor_execute()
    with patch(
        "copilot.tool_executor.ToolExecutor.execute",
        new=stub_execute,
    ):
        stream = orchestrator.run_stream(messages, context)
        return await _extract_from_stream(stream)


def _build_live_driver() -> LiveDriver:
    """Factory for the real-LLM driver.

    Lazy imports keep static runs from paying the heavy-module cost.
    The returned callable is sync so it slots into the existing
    ``LiveDriver`` contract; internally it drives ``asyncio.run`` once
    per case (each case gets its own event loop, matching how a
    request-per-call HTTP stack would behave).
    """
    _check_live_credentials()

    def driver(query: str) -> Dict[str, Any]:
        return asyncio.run(_run_query_live(query))

    return driver


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
