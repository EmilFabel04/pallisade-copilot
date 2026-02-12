"""
Co-Pilot API Router

API endpoints for the data pipeline co-pilot.
"""

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from copilot.context_builder import CopilotContextBuilder, CopilotContext
from copilot.tools import get_tool_registry
from copilot.llm import CopilotLLM, Message, CopilotResponse
from copilot.openlineage_consumer import OpenLineageConsumer
from copilot.modes import get_mode_config, detect_mode, parse_slash_command, get_available_modes

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
    model: str = Field("gpt-4o", description="Model to use: gpt-4o, gpt-4o-mini, gpt-4-turbo, o3-mini, claude-sonnet, claude-opus")
    mode: str = Field("ask", description="Interaction mode: ask, debug, plan, create, bundle, explain, suggest")
    integrations: Optional[List[IntegrationData]] = Field(None, description="User's pipeline integrations")
    lineage: Optional[LineageData] = Field(None, description="Pre-fetched lineage data from database")


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
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
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

        slash_mode, remaining_message = parse_slash_command(message)
        if slash_mode:
            mode = slash_mode.value
            message = remaining_message
            logger.info(f"Parsed slash command: mode={mode}")

        # Auto-detect mode if still using default 'ask'
        if mode == "ask":
            detected = detect_mode(message)
            if detected:
                mode = detected.value
                logger.info(f"Auto-detected mode: {mode}")

        # Get mode configuration
        mode_config = get_mode_config(mode)
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
            logger.info(f"Received integrations: {[{'type': i['type'], 'status': i['status']} for i in integration_data]}")
        else:
            logger.warning("No integrations received in chat request")

        # Try to use the in-process engine graph (richer: deduped, confidence,
        # dbt_resource_type) instead of the basic Prisma lineage data.
        # Both live in the same FastAPI process — no HTTP round-trip needed.
        engine_graph = None
        try:
            from api.routers.lineage import _get_engine_store
            _store = _get_engine_store()
            if _store and _store.graph and _store.graph.nodes:
                engine_graph = _store.graph
                logger.info(f"[Copilot] Using in-process engine graph: {len(engine_graph.nodes)} nodes, {len(engine_graph.edges)} edges")
        except Exception as e:
            logger.debug(f"[Copilot] Engine store not available: {e}")

        # Build context with mode
        context_builder = CopilotContextBuilder()
        context = await context_builder.build_context(
            org_id=x_organization_id,
            query=message,
            pipeline_stack_id=request.pipeline_stack_id,
            node_ids=request.node_ids,
            integrations_data=integration_data,
            mode=mode,
            mode_config=mode_config,
            lineage_data=request.lineage.model_dump() if request.lineage else None,
            engine_graph=engine_graph,
        )
        
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


@router.get("/context", response_model=ContextResponse)
async def get_context(
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
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
            org_id=x_organization_id,
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
            org_id=x_organization_id,
            integrations=integrations,
            available_tools=context.available_tools,
            lineage_stats=lineage_stats,
        )
        
    except Exception as e:
        logger.exception("Error getting context")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools", response_model=ToolsResponse)
async def get_available_tools(
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
):
    """
    Get tools available for the user's integrations.
    
    Tools are dynamically filtered based on what integrations
    are connected.
    """
    try:
        # Get user's integrations
        context_builder = CopilotContextBuilder()
        context = await context_builder.build_context(org_id=x_organization_id)
        
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
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
):
    """
    Receive OpenLineage events from Airflow, Dagster, Spark, etc.
    
    These events are used to build real-time lineage.
    """
    try:
        consumer = OpenLineageConsumer()
        success = await consumer.process_event(
            event_data=event.dict(),
            org_id=x_organization_id,
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
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
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
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
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
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
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
