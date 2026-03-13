"""
MAAS Orchestrator — the main multi-agent orchestration loop.

Produces the same StreamEvent types as CopilotLLM.chat_stream():
text_delta, tool_call_start, tool_call_result, tool_confirmation_required,
iteration_start, done, error.

GPT-5 is the only tool-caller and final narrator.
Specialists are called via RunPod for SQL, Logs, and CodeFix.
"""

import hashlib
import json
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
from .specialists.codefix import CodeFixSpecialist
from .specialists.base import SpecialistError
from .verifiers.sql_verifier import SQLVerifier
from .verifiers.logs_verifier import LogsVerifier
from .verifiers.patch_verifier import PatchVerifier
from .budgets import build_orchestrator_prompt, get_budget

logger = logging.getLogger(__name__)


def _args_hash(tool_name: str, args: Dict[str, Any]) -> str:
    """Compute a stable hash for tool call deduplication."""
    key = json.dumps({"t": tool_name, "a": args}, sort_keys=True, default=str)
    return hashlib.md5(key.encode()).hexdigest()[:12]


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
        self.patch_verifier = PatchVerifier()

    def _init_specialists(self):
        """Initialize RunPod clients and specialist wrappers (eagerly configured, lazily invoked)."""
        if self.config.sql_endpoint:
            client = RunPodClient(
                base_url=self.config.sql_endpoint,
                api_key=self.config.sql_api_key or "",
                model_name=self.config.sql_model,
                timeout=self.config.specialist_timeout,
            )
            self._clients["sql"] = client
            self._specialists["sql"] = SQLSpecialist(client)

        if self.config.logs_endpoint:
            client = RunPodClient(
                base_url=self.config.logs_endpoint,
                api_key=self.config.logs_api_key or "",
                model_name=self.config.logs_model,
                timeout=self.config.specialist_timeout,
            )
            self._clients["logs"] = client
            self._specialists["logs"] = LogsSpecialist(client)

        if self.config.codefix_endpoint:
            client = RunPodClient(
                base_url=self.config.codefix_endpoint,
                api_key=self.config.codefix_api_key or "",
                model_name=self.config.codefix_model,
                timeout=self.config.specialist_timeout,
            )
            self._clients["codefix"] = client
            self._specialists["codefix"] = CodeFixSpecialist(client)

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

            for tool_name in route.evidence_tools:
                if tool_call_count >= route.budget.max_tool_calls:
                    break

                tool_args = self._build_evidence_tool_args(tool_name, intent_result)
                ah = _args_hash(tool_name, tool_args)

                # Deduplication check
                cached = evidence_store.get_cached_result(ah)
                if cached is not None:
                    logger.debug(f"[MAAS] Dedup: reusing cached result for {tool_name}")
                    continue

                tool_start = time.monotonic()
                yield StreamEvent("tool_call_start", {
                    "tool_use_id": f"maas_ev_{tool_call_count}",
                    "tool_name": tool_name,
                    "arguments": tool_args,
                })

                try:
                    result = await executor.execute(tool_name, tool_args)
                    success = result.success if hasattr(result, "success") else True
                except Exception as e:
                    result = ToolResult(success=False, error=str(e))
                    success = False

                tool_latency = int((time.monotonic() - tool_start) * 1000)
                result_dict = result.to_dict() if hasattr(result, "to_dict") else {"error": str(result)}
                evidence_store.add_tool_result(tool_name, result_dict)
                evidence_store.cache_result(ah, result_dict)

                trace.tool_calls.append(ToolCallRecord(
                    tool_name=tool_name,
                    args_hash=ah,
                    latency_ms=tool_latency,
                    success=success,
                ))

                yield StreamEvent("tool_call_result", {
                    "tool_use_id": f"maas_ev_{tool_call_count}",
                    "tool_name": tool_name,
                    "result": result_dict,
                })
                tool_call_count += 1

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

            for spec_name in active_specialists:
                if specialist_call_count >= route.budget.max_specialist_calls:
                    break

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

                    result = await specialist.call(
                        evidence=evidence_blob,
                        query=query,
                        max_retries=route.budget.max_revisions,
                        warehouse_type=warehouse_filter or "bigquery",
                    )
                    latency = int((time.monotonic() - start_time) * 1000)
                    sql_preview = (
                        result.sql[:200] if hasattr(result, "sql") else "n/a"
                    )
                    logger.info(
                        f"[MAAS] {spec_name} returned "
                        f"latency={latency}ms sql={sql_preview}"
                    )

                    # Verify specialist output
                    vr = await self._verify_specialist(
                        spec_name, result, context
                    )
                    trace.verifier_results[spec_name] = {
                        "passed": vr["passed"],
                        "errors": vr.get("errors", []),
                        "warnings": vr.get("warnings", []),
                    }

                    if not vr["passed"]:
                        logger.warning(
                            f"[MAAS] {spec_name} failed verification: "
                            f"{vr['errors']}, retrying"
                        )
                        # Single retry with explicit warehouse
                        result = await specialist.call(
                            evidence=evidence_blob,
                            query=query,
                            max_retries=0,
                            warehouse_type=warehouse_filter or "bigquery",
                        )
                        vr = await self._verify_specialist(
                            spec_name, result, context
                        )
                        trace.verifier_results[spec_name] = {
                            "passed": vr["passed"],
                            "errors": vr.get("errors", []),
                            "warnings": vr.get("warnings", []),
                        }

                    specialist_results[spec_name] = {
                        "result": result,
                        "verified": vr["passed"],
                    }

                    trace.specialists.append(SpecialistInvocation(
                        specialist=spec_name,
                        latency_ms=latency,
                        success=True,
                    ))

                except SpecialistError as e:
                    latency = int((time.monotonic() - start_time) * 1000)
                    logger.error(f"[MAAS] Specialist '{spec_name}' failed: {e}")

                    trace.specialists.append(SpecialistInvocation(
                        specialist=spec_name,
                        latency_ms=latency,
                        success=False,
                        error=str(e),
                    ))

                    # Required specialist failure → full fallback
                    if spec_name in route.required_specialists:
                        trace.fallback_reason = f"specialist_{spec_name}_error"
                        async for event in self._fallback_stream(
                            messages, context, confirmed_tool_ids,
                            pending_tool_call, trace
                        ):
                            yield event
                        return
                    else:
                        # Optional specialist failure → skip it
                        trace.skipped_specialists.append(spec_name)
                        continue

                specialist_call_count += 1

                # --- Execute Logs specialist next_evidence ---
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
                    for ev_tool, ev_args in evidence_calls:
                        if tool_call_count >= route.budget.max_tool_calls:
                            break
                        ah = _args_hash(ev_tool, ev_args)

                        if evidence_store.get_cached_result(ah) is not None:
                            continue

                        tool_start = time.monotonic()
                        yield StreamEvent("tool_call_start", {
                            "tool_use_id": f"maas_logs_ev_{tool_call_count}",
                            "tool_name": ev_tool,
                            "arguments": ev_args,
                        })
                        try:
                            tr = await executor.execute(ev_tool, ev_args)
                            success = tr.success if hasattr(tr, "success") else True
                        except Exception as e:
                            tr = ToolResult(success=False, error=str(e))
                            success = False

                        tool_latency = int((time.monotonic() - tool_start) * 1000)
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
                            "tool_use_id": f"maas_logs_ev_{tool_call_count}",
                            "tool_name": ev_tool,
                            "result": tr_dict,
                        })
                        tool_call_count += 1

                # --- Execute SQL from SQL specialist ---
                if spec_name == "sql" and hasattr(result, "sql") and result.sql:
                    sql = result.sql
                    wh = result.warehouse.value

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
                    event.data["maas_trace"] = trace.model_dump()
                yield event

        except Exception as e:
            logger.exception("[MAAS] Orchestration error, falling back")
            trace.fallback_reason = f"orchestration_error: {e}"
            yield StreamEvent("error", {
                "message": f"MAAS orchestration error: {e}",
            })
            async for event in self._fallback_stream(
                messages, context, confirmed_tool_ids, pending_tool_call, trace
            ):
                yield event

        finally:
            for client in self._clients.values():
                try:
                    await client.close()
                except Exception:
                    pass

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
                }

            elif spec_name == "logs":
                available = set(context.available_tools)
                vr = self.logs_verifier.verify(result, available_tools=available)
                return {
                    "passed": vr.passed,
                    "errors": vr.errors,
                    "warnings": vr.warnings,
                }

            elif spec_name == "codefix":
                vr = await self.patch_verifier.verify(result)
                return {
                    "passed": vr.passed,
                    "errors": vr.errors,
                    "warnings": vr.warnings,
                }

        except Exception as e:
            logger.warning(f"[MAAS] Verification error for {spec_name}: {e}")
            return {"passed": False, "errors": [str(e)], "warnings": []}

        return {"passed": True, "errors": [], "warnings": []}

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
    ) -> AsyncGenerator[StreamEvent, None]:
        """Fall back to standard CopilotLLM when MAAS cannot proceed."""
        logger.info(
            f"[MAAS] Falling back to standard CopilotLLM "
            f"(reason: {trace.fallback_reason if trace else 'unknown'})"
        )
        fallback_llm = CopilotLLM(model=self.config.orchestrator_model)
        async for event in fallback_llm.chat_stream(
            messages,
            context,
            confirmed_tool_ids=confirmed_tool_ids,
            pending_tool_call=pending_tool_call,
        ):
            # Inject trace into done event even on fallback
            if event.event_type == "done" and trace:
                event.data["maas_trace"] = trace.model_dump()
            yield event
