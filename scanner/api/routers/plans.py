"""
Monitoring Plans API Router.

Provides endpoints for listing families, previewing monitoring plans,
and generating plan breakdowns with topology-aware partitioning.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import ActingPrincipal, require_principal
from .lineage import _get_engine_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class PlanPreviewRequest(BaseModel):
    """Request to preview a monitoring plan."""
    scope_type: str = Field(..., description="pipeline | stream | asset | tool")
    scope_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="{ anchorNodeIds, maxDepth, toolType, platform }",
    )
    mode: str = Field("recommended", description="recommended | manual")
    families: List[str] = Field(
        default_factory=list,
        description="Selected family keys (for recommended mode)",
    )
    manual_selections: Optional[Dict[str, List[str]]] = Field(
        None,
        description="Node-to-monitor-type mapping for manual mode: { nodeId: [monitorType] }",
    )
    existing_fqns: Optional[List[str]] = Field(
        None, description="Existing MONITOR_KEY:fqn strings for dedup",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/plans/families")
async def list_families(
    stack_id: Optional[str] = Query(None),
    anchor_node_id: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None),
    node_ids: Optional[str] = Query(None, description="Comma-separated node IDs for custom scope"),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Return all monitor family definitions with eligibility for scope."""
    try:
        from scanner.monitors.families import get_all_families
    except ImportError:
        from monitors.families import get_all_families

    scope_nodes = None
    if stack_id:
        store = _get_engine_store(principal.organization_id, stack_id)
        if store.graph:
            if node_ids:
                # Custom scope — use explicitly provided node IDs
                ids = [nid.strip() for nid in node_ids.split(",") if nid.strip()]
                scope_nodes = [
                    store.graph.nodes[nid]
                    for nid in ids
                    if nid in store.graph.nodes
                ]
            elif scope_type == "pipeline":
                scope_nodes = list(store.graph.nodes.values())
            elif anchor_node_id:
                # Stream scope — get upstream nodes
                upstream = store.graph.get_upstream_with_depth(
                    anchor_node_id, depth=5
                )
                scope_nodes = [n for n, _ in upstream]
                anchor = store.graph.nodes.get(anchor_node_id)
                if anchor:
                    scope_nodes.append(anchor)

    return {"families": get_all_families(scope_nodes)}


@router.post("/plans/preview")
async def preview_plan(
    request: PlanPreviewRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Preview what a monitoring plan would create without persisting anything."""
    try:
        from scanner.monitors.plan_builder import preview_monitoring_plan
    except ImportError:
        from monitors.plan_builder import preview_monitoring_plan

    store = _get_engine_store(principal.organization_id, stack_id)
    if not store.graph:
        raise HTTPException(
            status_code=404,
            detail="No lineage graph available. Run a scan first.",
        )

    existing_fqns = set(request.existing_fqns or [])
    result = preview_monitoring_plan(
        graph=store.graph,
        scope_type=request.scope_type,
        scope_config=request.scope_config,
        mode=request.mode,
        families=request.families,
        manual_selections=request.manual_selections,
        existing_monitor_fqns=existing_fqns,
    )

    return result.to_dict()
