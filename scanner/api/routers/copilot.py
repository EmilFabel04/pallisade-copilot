"""
Co-Pilot API Router

API endpoints for the data pipeline co-pilot.
"""

import os
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from copilot.context_builder import CopilotContextBuilder, CopilotContext
from copilot.tools import get_tool_registry
from copilot.llm import CopilotLLM, Message, CopilotResponse, StreamEvent
from copilot.openlineage_consumer import OpenLineageConsumer
from copilot.modes import get_mode_config, parse_slash_command, get_available_modes, mode_from_intent
from copilot.intent import classify_intent
from scanner.api.auth import ActingPrincipal, require_principal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot", tags=["copilot"])


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class IntegrationData(BaseModel):
    """Integration data from pipeline nodes."""
    id: str
    name: str
    type: str
    layer: str
    status: str
    config: Dict[str, Any] = {}


class LineageData(BaseModel):
    """Pre-fetched lineage data from database."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []


class ConversationMessage(BaseModel):
    """A message in the conversation history."""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")

class ChatRequest(BaseModel):
    """Request for chat endpoint."""
    message: str = Field(..., description="User's message")
    messages: Optional[List[ConversationMessage]] = Field(None, description="Full conversation history")
    session_id: Optional[str] = Field(None, description="Existing session ID")
    pipeline_stack_id: Optional[str] = Field(None, description="Pipeline stack to focus on")
    node_ids: Optional[List[str]] = Field(None, description="Specific nodes to focus on")
    referenced_entities: Optional[List[str]] = Field(None, description="@mentioned entities (e.g., 'BigQuery.analytics.customers')")
    model: str = Field("gpt-4o", description="Model to use: gpt-4o, gpt-4o-mini, gpt-4-turbo, o3-mini, claude-sonnet, claude-opus")
    mode: str = Field("ask", description="Interaction mode: ask, debug, plan, create, bundle, explain, suggest")
    integrations: Optional[List[IntegrationData]] = Field(None, description="User's pipeline integrations")
    lineage: Optional[LineageData] = Field(None, description="Pre-fetched lineage data from database")
    clarification_request_id: Optional[str] = Field(
        None,
        description="Pinned ContextRequest id when running in clarify mode (clarification layer V1.0)",
    )
    clarification_request: Optional[Dict[str, Any]] = Field(
        None,
        description="Inline ContextRequest row (id, kind, payload, scopeType, scopeRef, ...) when running in clarify mode. Next.js loads the row from Prisma and forwards it so the FastAPI process — which has no Prisma client — can render the kind-specific prompt fragment.",
    )


class PendingToolCall(BaseModel):
    """A tool call that was paused for confirmation and is now approved."""
    tool_use_id: str = Field(..., description="Original tool use ID")
    tool_name: str = Field(..., description="Tool name to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ChatStreamRequest(ChatRequest):
    """Extended request for streaming chat."""
    confirmed_tool_ids: Optional[List[str]] = Field(None, description="Tool use IDs the user has already confirmed")
    pending_tool_call: Optional[PendingToolCall] = Field(None, description="Tool call to execute directly (from confirmation)")
    confirmed_artifacts: Optional[Dict[str, Dict[str, Any]]] = Field(None, description="Artifacts confirmed by user, keyed by artifact_id")
    artifact_context: Optional[Dict[str, Any]] = Field(None, description="Context about the artifact being confirmed")


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    session_id: str
    message: str
    mode: str = "ask"
    tool_calls: List[Dict[str, Any]] = []
    input_tokens: int = 0
    output_tokens: int = 0


class ContextResponse(BaseModel):
    """Response with co-pilot context."""
    org_id: str
    integrations: List[Dict[str, Any]]
    available_tools: List[str]
    lineage_stats: Optional[Dict[str, Any]] = None


class ToolsResponse(BaseModel):
    """Response with available tools."""
    tools: List[Dict[str, Any]]
    integration_types: List[str]


class OpenLineageEventRequest(BaseModel):
    """OpenLineage event request."""
    eventType: str
    eventTime: str
    job: Dict[str, Any]
    run: Dict[str, Any]
    inputs: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []


# ============================================
# ENDPOINTS
# ============================================

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    raw_request: Request,
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Send a message to the co-pilot.
    
    The co-pilot will use tools as needed to answer the question,
    based on what integrations the user has connected.
    """
    try:
        # Parse slash command from message (e.g., "/debug why did this fail")
        message = request.message
        mode = request.mode
        intent_result = None

        slash_mode, remaining_message = parse_slash_command(message)
        if slash_mode:
            mode = slash_mode.value
            message = remaining_message
            logger.info(f"Parsed slash command: mode={mode}")
            mode_config = get_mode_config(mode)
        elif mode != "ask":
            # Frontend explicitly set a mode
            mode_config = get_mode_config(mode)
        else:
            # Multi-intent classification
            history = [
                {"role": m.role, "content": m.content}
                for m in (request.messages or [])
            ]
            intent_result = classify_intent(message, history)
            mode_config = mode_from_intent(intent_result)
            mode = mode_config.mode.value
            logger.info(
                f"Intent: primary={intent_result.primary.intent.value}"
                f"({intent_result.primary.score:.2f})"
                f"{f', secondary={intent_result.secondary.intent.value}({intent_result.secondary.score:.2f})' if intent_result.secondary else ''}"
                f"{f', target={intent_result.target_hint}' if intent_result.target_hint else ''}"
            )

        logger.info(f"Using mode: {mode} ({mode_config.display_name})")

        # Convert integrations from request to IntegrationInfo objects
        integration_data = None
        if request.integrations:
            integration_data = [
                {
                    "id": i.id,
                    "name": i.name,
                    "type": i.type,
                    "layer": i.layer,
                    "status": i.status,
                    "config": i.config,
                }
                for i in request.integrations
            ]
            logger.info(f"Received integrations: {[{'type': i['type'], 'status': i['status'], 'config_keys': list((i.get('config') or {}).keys())} for i in integration_data]}")
        else:
            logger.warning("No integrations received in chat request")

        # Try to use the in-process engine graph (richer: deduped, confidence,
        # dbt_resource_type) instead of the basic Prisma lineage data.
        # Both live in the same FastAPI process — no HTTP round-trip needed.
        engine_graph = None
        try:
            from api.routers.lineage import _get_engine_store
            _store = _get_engine_store(principal.organization_id, request.pipeline_stack_id)
            if _store and _store.graph and _store.graph.nodes:
                engine_graph = _store.graph
                logger.info(f"[Copilot] Using in-process engine graph: {len(engine_graph.nodes)} nodes, {len(engine_graph.edges)} edges")
        except Exception as e:
            logger.debug(f"[Copilot] Engine store not available: {e}")

        # Hydrate the ContextRequest payload for clarify mode. Next.js owns the
        # Prisma client and forwards the full row inline; if only the id was
        # passed (e.g. an older client), we still attach a stub so the LLM
        # tool layer can correlate the answer back to the request id.
        clarification_payload = request.clarification_request
        if clarification_payload is None and request.clarification_request_id:
            clarification_payload = {"id": request.clarification_request_id}

        # Build context with mode and intent
        context_builder = CopilotContextBuilder()
        context = await context_builder.build_context(
            org_id=principal.organization_id,
            query=message,
            pipeline_stack_id=request.pipeline_stack_id,
            node_ids=request.node_ids,
            referenced_entities=request.referenced_entities,
            integrations_data=integration_data,
            mode=mode,
            mode_config=mode_config,
            lineage_data=request.lineage.model_dump() if request.lineage else None,
            engine_graph=engine_graph,
            intent_result=intent_result,
            clarification_request=clarification_payload,
        )
        context.base_url = os.environ.get("NEXTJS_BASE_URL", "http://localhost:3000")
        context.auth_token = raw_request.headers.get("Authorization", "").replace("Bearer ", "")

        # Log the context
        logger.info(f"Built context with integration_types: {context.integration_types}")
        logger.info(f"Available tools: {context.available_tools}")
        
        # Initialize LLM with selected model
        logger.info(f"Using model: {request.model}")
        llm = CopilotLLM(model=request.model)
        logger.info(f"LLM initialized with provider: {llm.provider}, model: {llm.model}")
        
        # Build messages from conversation history or single message
        if request.messages and len(request.messages) > 0:
            messages = [
                Message(role=m.role, content=m.content) 
                for m in request.messages
            ]
            logger.info(f"Using conversation history with {len(messages)} messages")
        else:
            messages = [Message(role="user", content=request.message)]
        
        # Get response
        response = await llm.chat(messages, context)
        
        # TODO: Save to database
        session_id = request.session_id or "new_session_id"
        
        return ChatResponse(
            session_id=session_id,
            message=response.content,
            mode=mode,
            tool_calls=response.tool_calls,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        
    except Exception as e:
        logger.exception("Error in chat endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(
    request: ChatStreamRequest,
    raw_request: Request,
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Stream a chat response via Server-Sent Events (SSE).

    Returns a stream of SSE events: text_delta, tool_call_start,
    tool_call_result, tool_confirmation_required, iteration_start, done, error.
    """
    try:
        # --- Same context-building as /chat ---
        message = request.message
        mode = request.mode
        intent_result = None

        slash_mode, remaining_message = parse_slash_command(message)
        if slash_mode:
            mode = slash_mode.value
            message = remaining_message
            mode_config = get_mode_config(mode)
        elif mode != "ask":
            mode_config = get_mode_config(mode)
        else:
            history = [
                {"role": m.role, "content": m.content}
                for m in (request.messages or [])
            ]
            intent_result = classify_intent(message, history)
            mode_config = mode_from_intent(intent_result)
            mode = mode_config.mode.value
            logger.info(
                f"[Stream] Intent: primary={intent_result.primary.intent.value}"
                f"({intent_result.primary.score:.2f})"
                f"{f', secondary={intent_result.secondary.intent.value}({intent_result.secondary.score:.2f})' if intent_result.secondary else ''}"
                f"{f', target={intent_result.target_hint}' if intent_result.target_hint else ''}"
            )

        logger.info(f"[Stream] Using mode: {mode} ({mode_config.display_name})")

        integration_data = None
        if request.integrations:
            integration_data = [
                {
                    "id": i.id,
                    "name": i.name,
                    "type": i.type,
                    "layer": i.layer,
                    "status": i.status,
                    "config": i.config,
                }
                for i in request.integrations
            ]

        engine_graph = None
        try:
            from api.routers.lineage import _get_engine_store
            _store = _get_engine_store(principal.organization_id, request.pipeline_stack_id)
            if _store and _store.graph and _store.graph.nodes:
                engine_graph = _store.graph
        except Exception:
            pass

        # Hydrate the ContextRequest payload for clarify mode (see /chat above).
        clarification_payload = request.clarification_request
        if clarification_payload is None and request.clarification_request_id:
            clarification_payload = {"id": request.clarification_request_id}

        context_builder = CopilotContextBuilder()
        context = await context_builder.build_context(
            org_id=principal.organization_id,
            query=message,
            pipeline_stack_id=request.pipeline_stack_id,
            node_ids=request.node_ids,
            referenced_entities=request.referenced_entities,
            integrations_data=integration_data,
            mode=mode,
            mode_config=mode_config,
            lineage_data=request.lineage.model_dump() if request.lineage else None,
            engine_graph=engine_graph,
            intent_result=intent_result,
            clarification_request=clarification_payload,
        )
        context.base_url = os.environ.get("NEXTJS_BASE_URL", "http://localhost:3000")
        context.auth_token = raw_request.headers.get("Authorization", "").replace("Bearer ", "")

        llm = CopilotLLM(model=request.model)

        if request.messages and len(request.messages) > 0:
            messages = [
                Message(role=m.role, content=m.content)
                for m in request.messages
            ]
        else:
            messages = [Message(role="user", content=request.message)]

        confirmed_ids = set(request.confirmed_tool_ids or [])

        # If a pending tool call was provided (from confirmation flow),
        # pass it so the backend can execute it directly
        pending_tc = None
        if request.pending_tool_call:
            pending_tc = {
                "tool_use_id": request.pending_tool_call.tool_use_id,
                "tool_name": request.pending_tool_call.tool_name,
                "arguments": request.pending_tool_call.arguments,
            }

        # --- MAAS orchestration (feature-flagged) ---
        use_maas = False
        maas_orchestrator = None
        # Run intent classification for MAAS even when mode was set explicitly
        if not intent_result and mode in ("ask", "info"):
            try:
                history = [
                    {"role": m.role, "content": m.content}
                    for m in (request.messages or [])
                ]
                intent_result = classify_intent(message, history)
                context.intent_result = intent_result
                logger.info(
                    f"[Stream] Late intent classification for MAAS: "
                    f"primary={intent_result.primary.intent.value}"
                    f"({intent_result.primary.score:.2f})"
                )
            except Exception:
                pass
        # Skip MAAS for artifact confirmations — go straight to standard LLM
        if intent_result and not request.confirmed_artifacts:
            try:
                from copilot.maas.config import is_maas_enabled
                if is_maas_enabled():
                    from copilot.maas.orchestrator import MAASOrchestrator
                    maas_orchestrator = MAASOrchestrator()
                    use_maas = True
                    logger.info("[Stream] MAAS enabled — using orchestrator")
            except Exception as e:
                logger.warning(f"[Stream] MAAS init failed, falling back to standard: {e}")

        async def event_generator():
            sent_done = False
            try:
                if use_maas:
                    stream = maas_orchestrator.run_stream(
                        messages, context,
                        confirmed_tool_ids=confirmed_ids,
                        pending_tool_call=pending_tc,
                    )
                else:
                    stream = llm.chat_stream(
                        messages, context,
                        confirmed_tool_ids=confirmed_ids,
                        pending_tool_call=pending_tc,
                        confirmed_artifacts=request.confirmed_artifacts,
                    )
                async for event in stream:
                    if event.event_type == "done":
                        sent_done = True
                    yield event.to_sse()
            except Exception as e:
                logger.exception("[Stream] Error in event generator")
                yield StreamEvent("error", {"message": str(e)}).to_sse()
            finally:
                # Safety net: always send a 'done' event so the frontend
                # never gets stuck in isStreaming=true loading state.
                if not sent_done:
                    logger.warning("[Stream] Stream ended without 'done' event — injecting one")
                    yield StreamEvent("done", {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "model": request.model or "unknown",
                        "stop_reason": "stream_error",
                        "tool_calls": [],
                    }).to_sse()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        logger.exception("Error in chat stream endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context", response_model=ContextResponse)
async def get_context(
    principal: ActingPrincipal = Depends(require_principal),
    pipeline_stack_id: Optional[str] = None,
):
    """
    Get the current co-pilot context.

    Returns information about connected integrations,
    available tools, and lineage statistics.
    """
    try:
        context_builder = CopilotContextBuilder()
        context = await context_builder.build_context(
            org_id=principal.organization_id,
            pipeline_stack_id=pipeline_stack_id,
        )
        
        # Build response
        integrations = [
            {
                "id": i.id,
                "name": i.name,
                "type": i.type,
                "layer": i.layer.value,
                "status": i.status,
            }
            for i in context.integrations
        ]
        
        lineage_stats = None
        if context.graph:
            lineage_stats = {
                "node_count": len(context.graph.nodes),
                "edge_count": len(context.graph.edges),
                "root_count": len(context.graph.get_roots()),
                "leaf_count": len(context.graph.get_leaves()),
            }
        
        return ContextResponse(
            org_id=principal.organization_id,
            integrations=integrations,
            available_tools=context.available_tools,
            lineage_stats=lineage_stats,
        )
        
    except Exception as e:
        logger.exception("Error getting context")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools", response_model=ToolsResponse)
async def get_available_tools(
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Get tools available for the user's integrations.

    Tools are dynamically filtered based on what integrations
    are connected.
    """
    try:
        # Get user's integrations
        context_builder = CopilotContextBuilder()
        context = await context_builder.build_context(org_id=principal.organization_id)
        
        # Get available tools
        registry = get_tool_registry()
        available_tools = registry.get_available_tools(context.integration_types)
        
        return ToolsResponse(
            tools=[
                {
                    "name": tool.name,
                    "description": tool.description,
                    "category": tool.category.value,
                    "parameters": [
                        {
                            "name": p.name,
                            "type": p.type,
                            "description": p.description,
                            "required": p.required,
                        }
                        for p in tool.parameters
                    ],
                }
                for tool in available_tools
            ],
            integration_types=list(context.integration_types),
        )
        
    except Exception as e:
        logger.exception("Error getting tools")
        raise HTTPException(status_code=500, detail=str(e))


class ApplyPlanRequest(BaseModel):
    """Request to apply a change plan directly (no LLM round-trip)."""
    plan_id: str = Field(..., description="ID of the change plan to apply")
    repo_owner: Optional[str] = Field(None, description="GitHub repo owner")
    repo_name: Optional[str] = Field(None, description="GitHub repo name")
    base_branch: str = Field("main", description="Base branch for the PR")
    integrations: Optional[List[IntegrationData]] = Field(None, description="User's integrations (for GitHub token)")


@router.post("/apply-plan")
async def apply_plan(
    request: ApplyPlanRequest,
):
    """
    Apply a change plan by creating a GitHub PR — directly, no LLM.

    This is the fast path for "Create PR": it skips the LLM loop entirely
    and just executes the GitHub applier.
    """
    from copilot.change_plan import ChangePlanApplier, get_change_plan_store
    from copilot.change_plan.models import PatchType

    store = get_change_plan_store()
    plan = store.get(request.plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail=f"Change plan '{request.plan_id}' not found.")

    # Allow unvalidated plans when ALL patches are text files (docs, READMEs, etc.)
    is_docs_only = all(p.patch_type == PatchType.TEXT_FILE for p in plan.patches)
    if not plan.is_validated() and not is_docs_only:
        raise HTTPException(
            status_code=400,
            detail="Plan has not passed required validations. Run validation first.",
        )

    # Extract GitHub token from integrations
    github_token = None
    repo_owner = request.repo_owner
    repo_name = request.repo_name

    for integration in (request.integrations or []):
        if integration.type.upper() == "GITHUB":
            config = integration.config or {}
            github_token = config.get("access_token") or config.get("token")

            # Auto-detect repo if not explicitly provided
            if not repo_owner or not repo_name:
                # 1. Check separate owner + repo fields (from pipeline config UI)
                cfg_owner = config.get("owner")
                cfg_repo = config.get("repo")
                if cfg_owner and cfg_repo:
                    if "/" in cfg_repo:
                        parts = cfg_repo.split("/")
                        if len(parts) == 2:
                            repo_owner = repo_owner or parts[0]
                            repo_name = repo_name or parts[1]
                    else:
                        repo_owner = repo_owner or cfg_owner
                        repo_name = repo_name or cfg_repo
                elif cfg_repo and "/" in cfg_repo:
                    parts = cfg_repo.split("/")
                    if len(parts) == 2:
                        repo_owner = repo_owner or parts[0]
                        repo_name = repo_name or parts[1]

                # 2. Check metadata.repos list
                if not repo_owner or not repo_name:
                    metadata = config.get("metadata", {})
                    repos = metadata.get("repos", [])
                    if repos:
                        # Use first repo (for single-repo users this is the only one;
                        # for multi-repo users this is a reasonable default)
                        full_name = repos[0].get("name", "")
                        parts = full_name.split("/")
                        if len(parts) == 2:
                            repo_owner = repo_owner or parts[0]
                            repo_name = repo_name or parts[1]
                        if len(repos) > 1:
                            logger.info(f"[ApplyPlan] Auto-selected repo {full_name} from {len(repos)} available repos")
            break

    if not github_token:
        raise HTTPException(
            status_code=400,
            detail="GitHub is not connected. Please connect GitHub in your integrations.",
        )

    if not repo_owner or not repo_name:
        raise HTTPException(
            status_code=400,
            detail="Could not determine target repository. Please specify repo_owner and repo_name.",
        )

    # Apply the plan
    applier = ChangePlanApplier(github_token)
    try:
        result = await applier.apply(plan, repo_owner, repo_name, request.base_branch)

        if result.success:
            store.save(plan)
            return {
                "success": True,
                "plan_id": plan.id,
                "pr_url": result.pr_url,
                "pr_number": result.pr_number,
                "branch": result.branch_name,
                "files_changed": result.files_changed,
            }
        else:
            error_msg = result.error or "Failed to create Pull Request"
            # Return 401 for token issues so frontend can prompt reconnection
            if "invalid or expired" in error_msg.lower() or "reconnect" in error_msg.lower():
                raise HTTPException(status_code=401, detail=error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error applying change plan")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await applier.close()


@router.get("/modes")
async def get_modes():
    """
    Get available interaction modes.

    Returns the list of modes with their display info.
    """
    return {"modes": get_available_modes()}


@router.post("/openlineage/events")
async def receive_openlineage_event(
    event: OpenLineageEventRequest,
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Receive OpenLineage events from Airflow, Dagster, Spark, etc.

    These events are used to build real-time lineage.
    """
    try:
        consumer = OpenLineageConsumer()
        success = await consumer.process_event(
            event_data=event.dict(),
            org_id=principal.organization_id,
        )
        
        if success:
            return {"status": "accepted", "event_type": event.eventType}
        else:
            raise HTTPException(status_code=500, detail="Failed to process event")
            
    except Exception as e:
        logger.exception("Error processing OpenLineage event")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def get_sessions(
    limit: int = 20,
):
    """
    Get recent co-pilot sessions.
    """
    # TODO: Query database for sessions
    return {
        "sessions": [],
        "total": 0,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
):
    """
    Get a specific co-pilot session with messages.
    """
    # TODO: Query database for session
    return {
        "session": None,
        "messages": [],
    }


@router.post("/debug/start")
async def start_debug_session(
    issue_type: str = "pipeline_failure",
    title: str = "Debug Session",
    symptom_node_id: Optional[str] = None,
    symptom_details: Optional[Dict[str, Any]] = None,
):
    """
    Start a new debug session.
    
    Debug sessions help track investigation progress
    and calculate MTTR.
    """
    # TODO: Create debug session in database
    return {
        "debug_session_id": "new_debug_session",
        "copilot_session_id": "new_copilot_session",
        "status": "INVESTIGATING",
    }


# ============================================
# INCIDENT DIAGNOSIS
# ============================================

from copilot.incident_diagnosis import diagnose_incident, DiagnosisRequest, DiagnosisResult


class IncidentDiagnoseRequest(BaseModel):
    stackId: str
    monitorRunId: str
    targetFqn: str
    monitorType: str
    runDetails: Dict[str, Any]


class IncidentDiagnoseResponse(BaseModel):
    hypothesis: str
    signature: str
    ownerSystem: str
    ownerConfidence: float


@router.post("/incident-diagnose", response_model=IncidentDiagnoseResponse)
def post_incident_diagnose(req: IncidentDiagnoseRequest) -> IncidentDiagnoseResponse:
    result: DiagnosisResult = diagnose_incident(DiagnosisRequest(
        stack_id=req.stackId,
        monitor_run_id=req.monitorRunId,
        target_fqn=req.targetFqn,
        monitor_type=req.monitorType,
        run_details=req.runDetails,
    ))
    return IncidentDiagnoseResponse(
        hypothesis=result.hypothesis,
        signature=result.signature,
        ownerSystem=result.owner_system,
        ownerConfidence=result.owner_confidence,
    )
