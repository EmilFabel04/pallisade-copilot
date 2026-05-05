"""
Incident diagnosis — wraps the copilot LLM tool-calling pipeline with a
scoped prompt that returns JSON {hypothesis, signature}, and runs the
deterministic owner classifier on the gathered evidence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


SYSTEM_PROMPT = """You are diagnosing a single monitor failure for an observability platform.
Use the available tools (warehouse queries, lineage lookups, dbt status, connector status) to
gather just enough evidence to form a hypothesis. Limit yourself to ~6 tool calls.

When you have enough evidence, respond ONLY with a JSON object — no prose around it:
{"hypothesis": "<at most 2 sentences explaining the most likely cause>",
 "signature": "<short kebab-case slug under 32 chars, e.g. fivetran-source-stalled, dbt-test-not-null-failed, schema-added-column>"}
"""


@dataclass
class DiagnosisRequest:
    stack_id: str
    monitor_run_id: str
    target_fqn: str
    monitor_type: str
    run_details: Dict[str, Any]


@dataclass
class DiagnosisResult:
    hypothesis: str
    signature: str
    owner_system: str
    owner_confidence: float


def _fallback_signature(monitor_type: str, breach_class: str) -> str:
    return f"{monitor_type.lower()}-{breach_class.lower()}"[:32]


def _slugify_signature(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:32] or "unknown"


def _call_copilot_llm(messages: list, tools: list, stack_id: str) -> Dict[str, Any]:
    """Thin wrapper around CopilotLLM so the test can patch this single function."""
    # Heavy imports kept inside function body to avoid lineage import at module load time.
    from copilot.llm import CopilotLLM
    from copilot.context_builder import CopilotContextBuilder
    from copilot.tool_executor import ToolExecutor

    llm = CopilotLLM()
    response = llm.chat(messages=messages, tools=tools, stack_id=stack_id, max_tool_calls=6)
    return {
        "content": response.get("content", ""),
        "tool_call_evidence": response.get("tool_call_evidence", []),
    }


def _classify_owner(evidence: list, run_details: Dict[str, Any]) -> Tuple[str, float]:
    from copilot.root_cause import resolve_fix_owner

    decision = resolve_fix_owner(tool_results=evidence)
    return decision.owner_system.value, float(decision.confidence)


def diagnose_incident(req: DiagnosisRequest) -> DiagnosisResult:
    user_message = (
        f"Monitor `{req.monitor_type}` on `{req.target_fqn}` failed. Run details: "
        f"{json.dumps(req.run_details, default=str)[:1500]}. "
        "Investigate and return the JSON object."
    )
    messages = [{"role": "user", "content": user_message}]
    tools: list = []  # populated by _call_copilot_llm in production

    response = _call_copilot_llm(messages=messages, tools=tools, stack_id=req.stack_id)
    content = response["content"] or ""
    evidence = response["tool_call_evidence"]

    hypothesis: Optional[str] = None
    signature: Optional[str] = None
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else json.loads(content)
        hypothesis = str(parsed.get("hypothesis") or "").strip() or None
        raw_sig = str(parsed.get("signature") or "").strip()
        if raw_sig:
            signature = _slugify_signature(raw_sig)
    except Exception:
        pass

    if not hypothesis:
        hypothesis = content.strip()[:500] or "Unable to generate hypothesis"
    if not signature:
        breach_class = "unknown"
        if "threshold" in req.run_details and "value" in req.run_details:
            try:
                v = float(req.run_details["value"])
                t = float(req.run_details["threshold"])
                breach_class = "over-threshold" if v > t else "under-threshold"
            except Exception:
                pass
        signature = _fallback_signature(req.monitor_type, breach_class)

    owner_system, owner_confidence = _classify_owner(evidence, req.run_details)
    return DiagnosisResult(
        hypothesis=hypothesis,
        signature=signature,
        owner_system=owner_system,
        owner_confidence=owner_confidence,
    )
