"""
MAAS Orchestrator — the main multi-agent orchestration loop.

Produces the same StreamEvent types as CopilotLLM.chat_stream():
text_delta, tool_call_start, tool_call_result, tool_confirmation_required,
iteration_start, done, error.

GPT-5 is the only tool-caller and final narrator.
Specialists are called via RunPod for SQL and Logs.
"""

import asyncio
import hashlib
import json
import re
import time
import logging
from typing import AsyncGenerator, Dict, List, Any, Optional, Set

from copilot.llm import StreamEvent, CopilotLLM, Message
from copilot.context_builder import CopilotContext
from copilot.tools import ToolResult
from copilot.tool_executor import ToolExecutor
from copilot.intent import Intent

from .config import MAASConfig, get_maas_config
from .evidence_store import EvidenceStore
from .client import RunPodClient, RunPodUnavailableError
from .router import route_intent, SpecialistRoute, filter_evidence_requests
from .schemas import (
    SpecialistInvocation,
    ToolCallRecord,
    MAASTrace,
)
from .specialists.sql import SQLSpecialist
from .specialists.logs import LogsSpecialist
from .specialists.base import SpecialistError
from .verifiers.sql_verifier import SQLVerifier
from .verifiers.logs_verifier import LogsVerifier
from .budgets import build_orchestrator_prompt, get_budget

logger = logging.getLogger(__name__)


def _args_hash(tool_name: str, args: Dict[str, Any]) -> str:
    """Compute a stable hash for tool call deduplication."""
    key = json.dumps({"t": tool_name, "a": args}, sort_keys=True, default=str)
    return hashlib.md5(key.encode()).hexdigest()[:12]


# Reasoning-effort ladder. Higher tiers spend more reasoning tokens for
# better quality; the orchestrator escalates one tier on verifier failure.
# This only meaningfully affects specialists (SQL, Logs) — the GPT-5.4
# narration path runs Chat Completions with tools, where reasoning_effort
# is silently dropped (see commit 3700f2b) until the /v1/responses
# migration lands.
EFFORT_LADDER = ["minimal", "low", "medium", "high"]


def _next_effort(current: Optional[str]) -> Optional[str]:
    """Return the next-higher effort tier, or None if already at the top.

    ``None``/unknown values jump to ``medium`` rather than the bottom of
    the ladder — when no effort was configured we have no signal that the
    floor is the right starting point for the retry.
    """
    if current is None or current not in EFFORT_LADDER:
        return "medium"
    idx = EFFORT_LADDER.index(current)
    return EFFORT_LADDER[idx + 1] if idx < len(EFFORT_LADDER) - 1 else None


# Words in the user's query that suggest multi-table reasoning, joins,
# comparison, or investigation — the cases where running SQL gen at two
# temperatures and picking the higher-confidence result is worth the
# doubled cost. Heuristic on NL phrasing rather than the generated SQL
# so we can decide before the first call.
_HIGH_STAKES_PATTERNS = re.compile(
    r"(?:"
    # Comparison
    r"\bcompar\w*|\bacross\b|\bbetween\b|\bvs\b|\bversus\b|"
    # Explicit join
    r"\bjoin(?:ed|s|ing)?\b|"
    # Investigation / debug
    r"\binvestigat\w*|\bwhy\s+(?:did|does|is|are|was|were)\b|"
    r"\bwhat\s+went\s+wrong\b|\broot\s+cause\b|\bdebug\w*|"
    # Delta / correlation
    r"\bdifference\b|\bdiffer\w*|\bcorrelat\w*"
    r")",
    re.IGNORECASE,
)


def _is_high_stakes(query: str) -> bool:
    """Whether the query warrants self-consistency fan-out.

    Conservative: false negatives are fine (we just spend less), but a
    false positive doubles SQL specialist cost. Trigger only on signals
    that genuinely indicate multi-table or investigative work.
    """
    if not query:
        return False
    return bool(_HIGH_STAKES_PATTERNS.search(query))


class MAASOrchestrator:
    """
    Multi-Agent Architecture System orchestrator.

    Produces the same StreamEvent types as CopilotLLM.chat_stream(),
    making it a drop-in replacement when the feature flag is on.
    """

    def __init__(self, config: Optional[MAASConfig] = None):
        self.config = config or get_maas_config()
        self._clients: Dict[str, RunPodClient] = {}
        self._specialists: Dict[str, Any] = {}
        self._init_specialists()

        # Verifiers
        self.sql_verifier = SQLVerifier()
        self.logs_verifier = LogsVerifier()

    def _init_specialists(self):
        """Initialize specialist HTTP clients (eagerly configured, lazily invoked).

        The same client is used whether the endpoint is RunPod-hosted vLLM,
        OpenAI's API, or any other OpenAI-compatible provider. For GPT-5 /
        o-series specialists, reasoning_effort is set per the config so we
        don't pay for unnecessary internal reasoning on narrow JSON tasks.
        """
        if self.config.sql_endpoint:
            client = RunPodClient(
                base_url=self.config.sql_endpoint,
                api_key=self.config.sql_api_key or "",
                model_name=self.config.sql_model,
                timeout=self.config.specialist_timeout,
                reasoning_effort=self.config.sql_reasoning_effort,
            )
            self._clients["sql"] = client
            self._specialists["sql"] = SQLSpecialist(client)

        if self.config.logs_endpoint:
            client = RunPodClient(
                base_url=self.config.logs_endpoint,
                api_key=self.config.logs_api_key or "",
                model_name=self.config.logs_model,
                timeout=self.config.specialist_timeout,
                reasoning_effort=self.config.logs_reasoning_effort,
            )
            self._clients["logs"] = client
            self._specialists["logs"] = LogsSpecialist(client)

    def _resolve_target_warehouse(self, context: CopilotContext) -> Optional[str]:
        """Deterministic warehouse resolution — no inference from SQL syntax."""
        if not context.warehouse_schema:
            return None

        wh_types = list({
            k.split(":")[0].lower()
            for k in context.warehouse_schema.keys()
        })

        # Single warehouse — use it
        if len(wh_types) == 1:
            return wh_types[0]

        # Multiple — check user query for explicit mentions
        query_lower = context.query.lower()
        _WAREHOUSE_ALIASES = {
            "bigquery": ["bigquery", "bq", "big query"],
            "databricks": ["databricks", "spark", "delta lake"],
            "snowflake": ["snowflake"],
            "postgres": ["postgres", "postgresql", "pg"],
            "redshift": ["redshift"],
        }
        for wh_type, aliases in _WAREHOUSE_ALIASES.items():
            if wh_type in wh_types:
                if any(alias in query_lower for alias in aliases):
                    return wh_type

        # Fallback: first active warehouse
        return wh_types[0] if wh_types else None

    async def run_stream(
        self,
        messages: List[Message],
        context: CopilotContext,
        confirmed_tool_ids: Optional[Set[str]] = None,
        pending_tool_call: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Main MAAS orchestration loop producing SSE events.

        Falls back to CopilotLLM.chat_stream() if specialists are unavailable
        or on any orchestration error.
        """
        request_start = time.monotonic()
        trace = MAASTrace(route="unknown")

        intent_result = context.intent_result
        logger.info(
            f"[MAAS] Entering orchestration "
            f"intent={intent_result.primary.intent.value if intent_result else 'none'} "
            f"mode=maas"
        )

        if not intent_result:
            logger.info("[MAAS] No intent result, falling back to standard LLM")
            trace.fallback_reason = "no_intent_result"
            async for event in self._fallback_stream(
                messages, context, confirmed_tool_ids, pending_tool_call, trace
            ):
                yield event
            return

        try:
            route = route_intent(intent_result, context)
            trace.route = self._format_route(route)

            # Check required specialists are available
            for spec_name in route.required_specialists:
                if spec_name not in self._specialists:
                    logger.warning(
                        f"[MAAS] Required specialist '{spec_name}' not configured, "
                        f"falling back"
                    )
                    trace.fallback_reason = f"required_specialist_{spec_name}_unavailable"
                    async for event in self._fallback_stream(
                        messages, context, confirmed_tool_ids, pending_tool_call, trace
                    ):
                        yield event
                    return

            # Determine which optional specialists to skip
            skip_specialists: List[str] = []
            active_specialists = []
            for spec_name in route.specialists:
                if spec_name in self._specialists:
                    active_specialists.append(spec_name)
                elif spec_name in route.optional_specialists:
                    skip_specialists.append(spec_name)
                    trace.skipped_specialists.append(spec_name)
                    logger.info(
                        f"[MAAS] Optional specialist '{spec_name}' unavailable, skipping"
                    )
                # Required ones already checked above
            # === Phase 1: Evidence Gathering ===
            yield StreamEvent("iteration_start", {
                "iteration": 1, "reason": "evidence_gathering",
            })

            executor = ToolExecutor(context)

            # Pre-fetch schema if needed
            if not context.warehouse_schema and context.has_warehouse():
                try:
                    context.warehouse_schema = await executor.fetch_warehouse_schema()
                except Exception as e:
                    logger.error(f"[MAAS] Schema fetch failed: {e}")

            evidence_store = EvidenceStore(context=context)
            tool_call_count = 0

            # --- Phase 1: parallel evidence-tool gathering ---
            # Tools in route.evidence_tools are independent reads (warehouse
            # schema, lineage, etc). Sequential previously cost N×latency;
            # gather() collapses to ~max(latencies). Dedup, budget, and
            # streaming-event order are still honored.
            phase1_plan: List[tuple] = []
            for tool_name in route.evidence_tools:
                if len(phase1_plan) + tool_call_count >= route.budget.max_tool_calls:
                    break
                tool_args = self._build_evidence_tool_args(tool_name, intent_result)
                ah = _args_hash(tool_name, tool_args)
                cached = evidence_store.get_cached_result(ah)
                if cached is not None:
                    logger.debug(f"[MAAS] Dedup: reusing cached result for {tool_name}")
                    continue
                phase1_plan.append((tool_name, tool_args, ah))

            async def _exec_one(idx: int, name: str, args: Dict[str, Any]):
                start = time.monotonic()
                try:
                    res = await executor.execute(name, args)
                    ok = res.success if hasattr(res, "success") else True
                except Exception as e:
                    res = ToolResult(success=False, error=str(e))
                    ok = False
                lat = int((time.monotonic() - start) * 1000)
                return idx, res, ok, lat

            # Emit start events in order so the UI sees them in plan order.
            for i, (name, args, _ah) in enumerate(phase1_plan):
                yield StreamEvent("tool_call_start", {
                    "tool_use_id": f"maas_ev_{tool_call_count + i}",
                    "tool_name": name,
                    "arguments": args,
                })

            phase1_outcomes = await asyncio.gather(*[
                _exec_one(i, name, args) for i, (name, args, _ah) in enumerate(phase1_plan)
            ]) if phase1_plan else []

            # Emit results in plan order.
            for idx, result, success, tool_latency in phase1_outcomes:
                name, _args, ah = phase1_plan[idx]
                result_dict = result.to_dict() if hasattr(result, "to_dict") else {"error": str(result)}
                evidence_store.add_tool_result(name, result_dict)
                evidence_store.cache_result(ah, result_dict)
                trace.tool_calls.append(ToolCallRecord(
                    tool_name=name,
                    args_hash=ah,
                    latency_ms=tool_latency,
                    success=success,
                ))
                yield StreamEvent("tool_call_result", {
                    "tool_use_id": f"maas_ev_{tool_call_count + idx}",
                    "tool_name": name,
                    "result": result_dict,
                })
            tool_call_count += len(phase1_plan)

            # === Phase 2: Specialist Calls ===
            yield StreamEvent("iteration_start", {
                "iteration": 2, "reason": "specialist_analysis",
            })

            specialist_results: Dict[str, Dict[str, Any]] = {}
            specialist_call_count = 0
            query = context.query

            # Determine target warehouse (deterministic, no inference)
            warehouse_filter = self._resolve_target_warehouse(context)
            trace.selected_warehouse = warehouse_filter
            logger.info(f"[MAAS] Target warehouse: {warehouse_filter}")

            # --- Phase 2 LLM phase: run all specialists in parallel ---
            # Each specialist's call+verify+retry is independent. With one
            # specialist routed (today's common case) gather() collapses to
            # a single await; with two, it halves wall-clock latency.
            spec_plan: List[str] = []
            for n in active_specialists:
                if len(spec_plan) >= route.budget.max_specialist_calls:
                    break
                spec_plan.append(n)

            # Pre-compute the list of warehouses the user actually has
            # connected so the SQL specialist doesn't target a missing one.
            # Compound schema keys are "WAREHOUSE_TYPE:dataset".
            available_warehouses = sorted({
                k.split(":")[0].lower()
                for k in (context.warehouse_schema or {}).keys()
                if ":" in k
            })

            async def _call_and_verify(spec_name: str):
                specialist = self._specialists[spec_name]
                evidence_blob = evidence_store.for_specialist(
                    spec_name, query, warehouse_filter=warehouse_filter
                )
                start_time = time.monotonic()
                try:
                    if spec_name in self._clients:
                        c = self._clients[spec_name]
                        logger.info(
                            f"[MAAS] Calling {spec_name} "
                            f"endpoint={c.base_url} model={c.model_name}"
                        )
                    common_kwargs = dict(
                        evidence=evidence_blob,
                        query=query,
                        max_retries=route.budget.max_revisions,
                        warehouse_type=warehouse_filter or "bigquery",
                        available_tools=context.available_tools,
                        available_warehouses=available_warehouses,
                        pipeline_id=context.pipeline_stack_id,
                    )

                    self_consistency_used = False
                    self_consistency_picked: Optional[str] = None

                    if spec_name == "sql" and _is_high_stakes(query):
                        # Self-consistency: same prompt, two temperatures.
                        # Doubles SQL specialist cost so it's gated by the
                        # high-stakes heuristic. Pick the result that
                        # passes the verifier with higher confidence; on
                        # ties, prefer A (the deterministic temp=0.0
                        # result) to keep behavior reproducible.
                        logger.info(
                            f"[MAAS] {spec_name} high-stakes — running "
                            f"self-consistency fan-out (temp=0.0 || 0.7)"
                        )
                        result_a, result_b = await asyncio.gather(
                            specialist.call(temperature=0.0, **common_kwargs),
                            specialist.call(temperature=0.7, **common_kwargs),
                        )
                        vr_a, vr_b = await asyncio.gather(
                            self._verify_specialist(spec_name, result_a, context),
                            self._verify_specialist(spec_name, result_b, context),
                        )
                        conf_a = vr_a.get("confidence", 1.0 if vr_a["passed"] else 0.0)
                        conf_b = vr_b.get("confidence", 1.0 if vr_b["passed"] else 0.0)
                        # Strictly higher → B; otherwise A (stable default).
                        if conf_b > conf_a:
                            result, vr, self_consistency_picked = result_b, vr_b, "B"
                        else:
                            result, vr, self_consistency_picked = result_a, vr_a, "A"
                        self_consistency_used = True
                        logger.info(
                            f"[MAAS] {spec_name} self-consistency picked "
                            f"{self_consistency_picked} "
                            f"(conf_a={conf_a:.2f}, conf_b={conf_b:.2f})"
                        )
                    else:
                        result = await specialist.call(**common_kwargs)
                        vr = await self._verify_specialist(spec_name, result, context)
                    latency = int((time.monotonic() - start_time) * 1000)
                    sql_preview = (
                        result.sql[:200] if hasattr(result, "sql") else "n/a"
                    )
                    logger.info(
                        f"[MAAS] {spec_name} returned "
                        f"latency={latency}ms sql={sql_preview}"
                    )
                    escalated_to: Optional[str] = None
                    if not vr["passed"]:
                        # Escalate reasoning_effort one tier for the retry.
                        # Specialists run JSON-only, no tools, so the
                        # effort param actually flows through (unlike the
                        # narration path on Chat Completions). At-most-one
                        # escalation per call keeps cost bounded.
                        current_effort = (
                            self._clients[spec_name].reasoning_effort
                            if spec_name in self._clients
                            else None
                        )
                        escalated_to = _next_effort(current_effort)
                        logger.warning(
                            f"[MAAS] {spec_name} failed verification: "
                            f"{vr['errors']}, retrying"
                            + (
                                f" with reasoning_effort={escalated_to}"
                                if escalated_to else ""
                            )
                        )
                        result = await specialist.call(
                            evidence=evidence_blob,
                            query=query,
                            max_retries=0,
                            warehouse_type=warehouse_filter or "bigquery",
                            available_tools=context.available_tools,
                            available_warehouses=available_warehouses,
                            pipeline_id=context.pipeline_stack_id,
                            reasoning_effort=escalated_to,
                        )
                        vr = await self._verify_specialist(spec_name, result, context)
                    return {
                        "spec_name": spec_name,
                        "specialist": specialist,
                        "evidence_blob": evidence_blob,
                        "result": result,
                        "vr": vr,
                        "latency": latency,
                        "error": None,
                        "escalated_to": escalated_to,
                        "self_consistency_used": self_consistency_used,
                        "self_consistency_picked": self_consistency_picked,
                    }
                except SpecialistError as e:
                    latency = int((time.monotonic() - start_time) * 1000)
                    logger.error(f"[MAAS] Specialist '{spec_name}' failed: {e}")
                    return {
                        "spec_name": spec_name,
                        "specialist": None,
                        "evidence_blob": None,
                        "result": None,
                        "vr": None,
                        "latency": latency,
                        "error": e,
                    }

            outcomes = await asyncio.gather(*[
                _call_and_verify(n) for n in spec_plan
            ]) if spec_plan else []

            # --- Sequential post-processing in plan order ---
            for outcome in outcomes:
                spec_name = outcome["spec_name"]
                error = outcome["error"]
                latency = outcome["latency"]

                if error is not None:
                    trace.specialists.append(SpecialistInvocation(
                        specialist=spec_name,
                        latency_ms=latency,
                        success=False,
                        error=str(error),
                    ))
                    if spec_name in route.required_specialists:
                        trace.fallback_reason = f"specialist_{spec_name}_error"
                        async for event in self._fallback_stream(
                            messages, context, confirmed_tool_ids,
                            pending_tool_call, trace,
                            evidence_store=evidence_store, query=query,
                        ):
                            yield event
                        return
                    else:
                        trace.skipped_specialists.append(spec_name)
                        continue

                specialist = outcome["specialist"]
                evidence_blob = outcome["evidence_blob"]
                result = outcome["result"]
                vr = outcome["vr"]

                trace.verifier_results[spec_name] = {
                    "passed": vr["passed"],
                    "errors": vr.get("errors", []),
                    "warnings": vr.get("warnings", []),
                    "confidence": vr.get("confidence", 1.0 if vr["passed"] else 0.0),
                }
                # Surface a warning when confidence is low but we're still
                # accepting the result — useful signal in the trace and the
                # log file for tuning thresholds later.
                conf = vr.get("confidence", 1.0)
                if vr["passed"] and conf < 0.7:
                    logger.info(
                        f"[MAAS] {spec_name} verified with low confidence "
                        f"({conf:.2f}); warnings={vr.get('warnings', [])}"
                    )

                escalated_to = outcome.get("escalated_to")
                sc_used = outcome.get("self_consistency_used", False)
                sc_picked = outcome.get("self_consistency_picked")
                if vr["passed"]:
                    specialist_results[spec_name] = {
                        "result": result,
                        "verified": True,
                    }
                    trace.specialists.append(SpecialistInvocation(
                        specialist=spec_name,
                        latency_ms=latency,
                        success=True,
                        escalated_to=escalated_to,
                        self_consistency_used=sc_used,
                        self_consistency_picked=sc_picked,
                    ))
                else:
                    # Both attempts failed verification. Drop the result and
                    # SKIP downstream side-effects (next_evidence tool calls,
                    # SQL execution) — running unverified specialist output
                    # against the warehouse is unsafe.
                    logger.warning(
                        f"[MAAS] {spec_name} dropped after second verification failure: "
                        f"{vr.get('errors', [])}"
                    )
                    trace.specialists.append(SpecialistInvocation(
                        specialist=spec_name,
                        latency_ms=latency,
                        success=False,
                        error=f"verification failed: {vr.get('errors', [])}",
                        escalated_to=escalated_to,
                        self_consistency_used=sc_used,
                        self_consistency_picked=sc_picked,
                    ))
                    continue

                specialist_call_count += 1

                # --- Execute Logs specialist next_evidence (parallel) ---
                if spec_name == "logs" and hasattr(result, "next_evidence"):
                    available = set(context.available_tools)
                    # Build (filtered_name, args) pairs with proper arg transformation
                    evidence_calls = []
                    for r in result.next_evidence[:3]:
                        orig_name = r.tool_name
                        orig_args = r.tool_arguments or {}
                        if orig_name in available:
                            evidence_calls.append((orig_name, dict(orig_args)))
                        elif any(k in orig_name for k in ("lineage", "upstream", "downstream")):
                            if "search_lineage" in available:
                                # Transform args: use node_id/dag_id as query
                                search_query = orig_args.get("node_id", orig_args.get("dag_id", query))
                                evidence_calls.append(("search_lineage", {"query": search_query}))
                        else:
                            logger.warning(f"[MAAS/Router] Filtered out unavailable tool '{orig_name}'")

                    # Plan + dedup + budget pass before launching anything.
                    next_plan: List[tuple] = []
                    for ev_tool, ev_args in evidence_calls:
                        if len(next_plan) + tool_call_count >= route.budget.max_tool_calls:
                            break
                        ah = _args_hash(ev_tool, ev_args)
                        if evidence_store.get_cached_result(ah) is not None:
                            continue
                        next_plan.append((ev_tool, ev_args, ah))

                    async def _exec_next(idx: int, name: str, args: Dict[str, Any]):
                        start = time.monotonic()
                        try:
                            r2 = await executor.execute(name, args)
                            ok = r2.success if hasattr(r2, "success") else True
                        except Exception as e:
                            r2 = ToolResult(success=False, error=str(e))
                            ok = False
                        return idx, r2, ok, int((time.monotonic() - start) * 1000)

                    # Emit start events in plan order so the UI renders predictably.
                    for i, (name, args, _ah) in enumerate(next_plan):
                        yield StreamEvent("tool_call_start", {
                            "tool_use_id": f"maas_logs_ev_{tool_call_count + i}",
                            "tool_name": name,
                            "arguments": args,
                        })

                    next_outcomes = await asyncio.gather(*[
                        _exec_next(i, name, args) for i, (name, args, _ah) in enumerate(next_plan)
                    ]) if next_plan else []

                    for idx, tr, success, tool_latency in next_outcomes:
                        ev_tool, _ev_args, ah = next_plan[idx]
                        tr_dict = tr.to_dict() if hasattr(tr, "to_dict") else {"error": str(tr)}
                        evidence_store.add_tool_result(ev_tool, tr_dict)
                        evidence_store.cache_result(ah, tr_dict)
                        trace.tool_calls.append(ToolCallRecord(
                            tool_name=ev_tool,
                            args_hash=ah,
                            latency_ms=tool_latency,
                            success=success,
                        ))
                        yield StreamEvent("tool_call_result", {
                            "tool_use_id": f"maas_logs_ev_{tool_call_count + idx}",
                            "tool_name": ev_tool,
                            "result": tr_dict,
                        })
                    tool_call_count += len(next_plan)

                # --- Execute SQL from SQL specialist ---
                if spec_name == "sql" and hasattr(result, "sql") and result.sql:
                    sql = result.sql
                    wh = result.warehouse.value

                    # Hard budget gate: previously the SQL exec + repair
                    # could over-spend the tool budget silently.
                    if tool_call_count >= route.budget.max_tool_calls:
                        trace.budget_exhausted = True
                        logger.warning(
                            f"[MAAS] Budget exhausted before SQL exec "
                            f"({tool_call_count}/{route.budget.max_tool_calls}); "
                            f"skipping execution"
                        )
                        continue

                    logger.info(
                        f"[MAAS] Executing query_warehouse warehouse={wh}"
                    )
                    tool_start = time.monotonic()
                    yield StreamEvent("tool_call_start", {
                        "tool_use_id": "maas_sql_exec",
                        "tool_name": "query_warehouse",
                        "arguments": {"sql": sql, "warehouse": wh},
                    })
                    try:
                        sql_result = await executor.execute(
                            "query_warehouse", {"sql": sql, "warehouse": wh}
                        )
                        success = sql_result.success if hasattr(sql_result, "success") else True
                    except Exception as e:
                        sql_result = ToolResult(success=False, error=str(e))
                        success = False

                    tool_latency = int((time.monotonic() - tool_start) * 1000)
                    logger.info(
                        f"[MAAS] query_warehouse completed "
                        f"latency={tool_latency}ms success={success}"
                    )
                    sql_dict = sql_result.to_dict() if hasattr(sql_result, "to_dict") else {"error": str(sql_result)}
                    evidence_store.add_tool_result(
                        "query_warehouse", sql_dict, warehouse=wh
                    )

                    trace.tool_calls.append(ToolCallRecord(
                        tool_name="query_warehouse",
                        args_hash=_args_hash("query_warehouse", {"sql": sql}),
                        latency_ms=tool_latency,
                        success=success,
                    ))

                    yield StreamEvent("tool_call_result", {
                        "tool_use_id": "maas_sql_exec",
                        "tool_name": "query_warehouse",
                        "result": sql_dict,
                    })
                    tool_call_count += 1

                    # --- Repair loop: one retry on execution failure ---
                    if not success:
                        error_text = sql_dict.get("error", "Unknown execution error")
                        # Repair = 1 specialist call + 1 tool call. Budget-gate it.
                        if tool_call_count >= route.budget.max_tool_calls:
                            trace.budget_exhausted = True
                            logger.warning(
                                f"[MAAS] Budget exhausted, skipping SQL repair "
                                f"({tool_call_count}/{route.budget.max_tool_calls})"
                            )
                            trace.fallback_reason = "budget_exhausted"
                            async for event in self._fallback_stream(
                                messages, context, confirmed_tool_ids,
                                pending_tool_call, trace,
                                evidence_store=evidence_store, query=query,
                            ):
                                yield event
                            return
                        logger.warning(
                            f"[MAAS] SQL execution failed, attempting repair: "
                            f"{str(error_text)[:200]}"
                        )
                        trace.repair_attempted = True

                        repair_evidence = (
                            f"{evidence_blob}\n\n"
                            f"## Previous SQL (FAILED)\n```sql\n{sql}\n```\n\n"
                            f"## Execution Error\n{error_text}"
                        )
                        try:
                            repaired = await specialist.call(
                                evidence=repair_evidence,
                                query=query,
                                max_retries=0,
                                warehouse_type=warehouse_filter or "bigquery",
                                pipeline_id=context.pipeline_stack_id,
                                repair_mode=True,
                            )
                            vr = await self._verify_specialist(
                                "sql", repaired, context
                            )
                            if vr["passed"] and repaired.sql:
                                repair_sql = repaired.sql
                                repair_wh = repaired.warehouse.value

                                logger.info(
                                    f"[MAAS] Executing repaired SQL "
                                    f"warehouse={repair_wh}"
                                )
                                tool_start = time.monotonic()
                                yield StreamEvent("tool_call_start", {
                                    "tool_use_id": "maas_sql_repair",
                                    "tool_name": "query_warehouse",
                                    "arguments": {
                                        "sql": repair_sql,
                                        "warehouse": repair_wh,
                                    },
                                })
                                try:
                                    sql_result = await executor.execute(
                                        "query_warehouse",
                                        {"sql": repair_sql, "warehouse": repair_wh},
                                    )
                                    success = (
                                        sql_result.success
                                        if hasattr(sql_result, "success")
                                        else True
                                    )
                                except Exception as e:
                                    sql_result = ToolResult(
                                        success=False, error=str(e)
                                    )
                                    success = False

                                tool_latency = int(
                                    (time.monotonic() - tool_start) * 1000
                                )
                                logger.info(
                                    f"[MAAS] Repair query_warehouse completed "
                                    f"latency={tool_latency}ms success={success}"
                                )
                                sql_dict = (
                                    sql_result.to_dict()
                                    if hasattr(sql_result, "to_dict")
                                    else {"error": str(sql_result)}
                                )
                                evidence_store.add_tool_result(
                                    "query_warehouse", sql_dict,
                                    warehouse=repair_wh,
                                )
                                trace.tool_calls.append(ToolCallRecord(
                                    tool_name="query_warehouse",
                                    args_hash=_args_hash(
                                        "query_warehouse",
                                        {"sql": repair_sql},
                                    ),
                                    latency_ms=tool_latency,
                                    success=success,
                                ))
                                yield StreamEvent("tool_call_result", {
                                    "tool_use_id": "maas_sql_repair",
                                    "tool_name": "query_warehouse",
                                    "result": sql_dict,
                                })
                                tool_call_count += 1

                                # Update specialist results with repaired SQL
                                specialist_results["sql"]["result"] = repaired
                            else:
                                success = False

                        except SpecialistError as e:
                            logger.warning(
                                f"[MAAS] Repair specialist call failed: {e}"
                            )
                            success = False

                        if not success:
                            logger.warning(
                                "[MAAS] Repair loop failed, falling back"
                            )
                            trace.fallback_reason = "sql_repair_failed"
                            async for event in self._fallback_stream(
                                messages, context, confirmed_tool_ids,
                                pending_tool_call, trace,
                                evidence_store=evidence_store, query=query,
                            ):
                                yield event
                            return

            # === Phase 3: GPT-5 Narration ===
            yield StreamEvent("iteration_start", {
                "iteration": 3, "reason": "synthesis",
            })

            specialist_summary = self._format_specialist_results(specialist_results)
            evidence_blob = evidence_store.for_specialist("orchestrator", query)

            from copilot.response_builder import build_answer_contract
            from copilot.modes import mode_from_intent

            mode_config = mode_from_intent(intent_result)
            answer_contract = build_answer_contract(intent_result)

            # Include user's data stack context so the orchestrator knows
            # what integrations are connected (servers, warehouses, etc.)
            data_stack_context = context.to_system_prompt_context(query=query)

            orchestrator_prompt = build_orchestrator_prompt(
                evidence_blob=evidence_blob,
                specialist_results=specialist_summary,
                intent=intent_result.primary.intent,
                mode_prompt=mode_config.system_prompt_section,
                answer_contract=answer_contract,
                data_stack_context=data_stack_context,
            )

            # Create GPT-5 LLM for narration
            orchestrator_llm = CopilotLLM(model=self.config.orchestrator_model)

            remaining_tools = max(
                0, route.budget.max_tool_calls - tool_call_count
            )

            async for event in orchestrator_llm.chat_stream(
                list(messages),
                context,
                max_tool_iterations=remaining_tools,
                confirmed_tool_ids=confirmed_tool_ids,
                pending_tool_call=pending_tool_call,
                system_prompt_override=orchestrator_prompt,
            ):
                # Inject maas_trace into done event
                if event.event_type == "done":
                    trace.total_latency_ms = int(
                        (time.monotonic() - request_start) * 1000
                    )
                    trace.health = self._compute_health(trace)
                    event.data["maas_trace"] = trace.model_dump()
                yield event

        except Exception as e:
            logger.exception("[MAAS] Orchestration error, falling back")
            trace.fallback_reason = f"orchestration_error: {e}"
            yield StreamEvent("error", {
                "message": f"MAAS orchestration error: {e}",
            })
            # Forward whatever evidence we managed to gather before crashing
            # — variables may not be bound if the error fired early.
            ev_store_local = locals().get("evidence_store")
            ev_query_local = locals().get("query") or ""
            async for event in self._fallback_stream(
                messages, context, confirmed_tool_ids, pending_tool_call, trace,
                evidence_store=ev_store_local, query=ev_query_local,
            ):
                yield event

        finally:
            for client in self._clients.values():
                try:
                    await client.close()
                except Exception:
                    pass

    @staticmethod
    def _compute_health(trace: MAASTrace) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate per-specialist health stats from the trace. Surfaces the
        information that's expensive to compute from raw events ad-hoc:
        call count, retry count, mean latency, verification pass rate,
        mean confidence. Lives on the trace so any consumer (UI, logs,
        metrics pipeline) can ingest one structured payload.
        """
        by_name: Dict[str, Dict[str, Any]] = {}
        for inv in trace.specialists:
            entry = by_name.setdefault(inv.specialist, {
                "calls": 0,
                "retries": 0,
                "successes": 0,
                "latencies": [],
            })
            entry["calls"] += 1
            entry["retries"] += inv.retry_count
            if inv.success:
                entry["successes"] += 1
            entry["latencies"].append(inv.latency_ms)

        # Merge in verifier confidence
        for spec_name, vr in trace.verifier_results.items():
            entry = by_name.setdefault(spec_name, {
                "calls": 0, "retries": 0, "successes": 0, "latencies": [],
            })
            entry["last_confidence"] = vr.get("confidence", 1.0)
            entry["last_passed"] = vr.get("passed", False)

        out: Dict[str, Dict[str, Any]] = {}
        for name, e in by_name.items():
            latencies = e["latencies"]
            mean_lat = int(sum(latencies) / len(latencies)) if latencies else 0
            out[name] = {
                "calls": e["calls"],
                "retries": e["retries"],
                "verification_pass_rate": (
                    round(e["successes"] / e["calls"], 2)
                    if e["calls"] else 0.0
                ),
                "mean_latency_ms": mean_lat,
                "last_confidence": e.get("last_confidence", 1.0),
                "last_passed": e.get("last_passed", False),
            }
        return out

    async def _verify_specialist(
        self,
        spec_name: str,
        result: Any,
        context: CopilotContext,
    ) -> Dict[str, Any]:
        """Run the appropriate verifier on specialist output."""
        try:
            if spec_name == "sql":
                schema_columns: Dict[str, Set[str]] = {}
                for key, tables in context.warehouse_schema.items():
                    for table in tables:
                        fqn = f"{table.dataset}.{table.name}"
                        schema_columns[fqn] = {
                            c["name"] for c in table.columns if "name" in c
                        }
                connected = list({
                    k.split(":")[0].upper()
                    for k in context.warehouse_schema.keys()
                })
                vr = self.sql_verifier.verify(
                    result, schema_columns, connected_warehouses=connected
                )
                return {
                    "passed": vr.passed,
                    "errors": vr.errors,
                    "warnings": vr.warnings,
                    "confidence": vr.confidence,
                }

            elif spec_name == "logs":
                available = set(context.available_tools)
                vr = self.logs_verifier.verify(result, available_tools=available)
                return {
                    "passed": vr.passed,
                    "errors": vr.errors,
                    "warnings": vr.warnings,
                    "confidence": vr.confidence,
                }

        except Exception as e:
            logger.warning(f"[MAAS] Verification error for {spec_name}: {e}")
            return {"passed": False, "errors": [str(e)], "warnings": [], "confidence": 0.0}

        return {"passed": True, "errors": [], "warnings": [], "confidence": 1.0}

    def _build_evidence_tool_args(
        self,
        tool_name: str,
        intent_result: Any,
    ) -> Dict[str, Any]:
        """Build arguments for evidence-gathering tool calls."""
        args: Dict[str, Any] = {}
        entities = intent_result.target_entities or []

        if tool_name in ("get_upstream", "get_downstream") and entities:
            args["node_id"] = entities[0]
        elif tool_name == "get_dag_run_history" and entities:
            args["dag_id"] = entities[0]
        elif tool_name in ("get_dbt_run_history", "get_dbt_test_results"):
            if entities:
                args["model_name"] = entities[0]

        return args

    def _format_specialist_results(
        self, results: Dict[str, Dict[str, Any]]
    ) -> str:
        """Format specialist results for the GPT-5 prompt."""
        if not results:
            return "No specialist results available."

        parts = []
        for spec_name, data in results.items():
            result = data["result"]
            verified = data["verified"]
            status = "VERIFIED" if verified else "UNVERIFIED"
            parts.append(f"### {spec_name.upper()} Specialist [{status}]")
            parts.append(result.model_dump_json(indent=2))
        return "\n\n".join(parts)

    def _format_route(self, route: SpecialistRoute) -> str:
        """Format route for trace logging."""
        if not route.specialists:
            return "GPT5_ONLY"
        return "/".join(route.specialists)

    async def _fallback_stream(
        self,
        messages: List[Message],
        context: CopilotContext,
        confirmed_tool_ids: Optional[Set[str]] = None,
        pending_tool_call: Optional[Dict[str, Any]] = None,
        trace: Optional[MAASTrace] = None,
        evidence_store: Optional["EvidenceStore"] = None,
        query: str = "",
    ) -> AsyncGenerator[StreamEvent, None]:
        """Fall back to standard CopilotLLM when MAAS cannot proceed."""
        logger.info(
            f"[MAAS] Falling back to standard CopilotLLM "
            f"(reason: {trace.fallback_reason if trace else 'unknown'})"
        )
        # If Phase-1 evidence was already gathered, forward it as a synthetic
        # user-role note so the fallback LLM doesn't redo the work. Without
        # this, every tool call executed before the failure was wasted.
        forwarded_messages = list(messages)
        if evidence_store is not None:
            try:
                evidence_blob = evidence_store.for_specialist("orchestrator", query)
            except Exception as e:
                logger.debug(f"[MAAS] Evidence forwarding skipped: {e}")
                evidence_blob = ""
            if evidence_blob.strip():
                forwarded_messages.append(Message(
                    role="user",
                    content=(
                        "[system note — pre-gathered evidence from prior MAAS phase]\n"
                        f"{evidence_blob}"
                    ),
                ))

        fallback_llm = CopilotLLM(model=self.config.orchestrator_model)
        async for event in fallback_llm.chat_stream(
            forwarded_messages,
            context,
            confirmed_tool_ids=confirmed_tool_ids,
            pending_tool_call=pending_tool_call,
        ):
            # Inject trace into done event even on fallback
            if event.event_type == "done" and trace:
                event.data["maas_trace"] = trace.model_dump()
            yield event
