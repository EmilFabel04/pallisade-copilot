"""
Incident diagnosis — wraps the copilot LLM tool-calling pipeline with a
scoped prompt that returns JSON {hypothesis, signature}, and runs the
deterministic owner classifier on the gathered evidence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


SYSTEM_PROMPT = """You are diagnosing a single monitor failure for an observability platform.
Use the available tools (warehouse queries, lineage lookups, dbt status, connector status) to
gather just enough evidence to form a hypothesis. Limit yourself to ~6 tool calls.

When you have enough evidence, respond ONLY with a JSON object — no prose around it:
{"hypothesis": "<at most 2 sentences explaining the most likely cause>",
 "signature": "<short kebab-case slug under 32 chars, e.g. fivetran-source-stalled, dbt-test-not-null-failed, schema-added-column>"}
"""


@dataclass
class DiagnosisRequest:
    org_id: str
    stack_id: str
    monitor_run_id: str
    target_fqn: str
    monitor_type: str
    run_details: Dict[str, Any]
    integrations: Optional[List[Dict[str, Any]]] = None


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


async def _call_copilot_llm(
    messages: list,
    org_id: str,
    stack_id: str,
    integrations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Thin wrapper around CopilotLLM so the test can patch this single function."""
    # Heavy imports kept inside function body to avoid lineage import at module load time.
    from copilot.llm import CopilotLLM, Message
    from copilot.context_builder import CopilotContextBuilder

    engine_graph = None
    try:
        from api.routers.lineage import _get_engine_store
        store = _get_engine_store(org_id, stack_id)
        if store and store.graph and store.graph.nodes:
            engine_graph = store.graph
    except Exception:
        engine_graph = None

    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    builder = CopilotContextBuilder()
    context = await builder.build_context(
        org_id=org_id,
        query=last_user,
        pipeline_stack_id=stack_id,
        integrations_data=integrations or None,
        engine_graph=engine_graph,
        mode="debug",
    )

    typed_messages = [Message(role=m["role"], content=m["content"]) for m in messages]
    llm = CopilotLLM()
    response = await llm.chat(typed_messages, context, max_tool_iterations=6)
    return {
        "content": response.content or "",
        "tool_call_evidence": response.tool_calls or [],
    }


def _classify_owner(evidence: list, run_details: Dict[str, Any]) -> Tuple[str, float]:
    from copilot.root_cause import resolve_fix_owner

    decision = resolve_fix_owner(tool_results=evidence)
    return decision.owner_system.value, float(decision.confidence)


async def diagnose_incident(req: DiagnosisRequest) -> DiagnosisResult:
    user_message = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Monitor `{req.monitor_type}` on `{req.target_fqn}` failed. Run details: "
        f"{json.dumps(req.run_details, default=str)[:1500]}. "
        "Investigate and return the JSON object."
    )
    messages = [{"role": "user", "content": user_message}]

    response = await _call_copilot_llm(
        messages=messages,
        org_id=req.org_id,
        stack_id=req.stack_id,
        integrations=req.integrations,
    )
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
