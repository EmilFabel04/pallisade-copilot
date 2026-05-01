"""
Monitor Presets API Router.

Provides endpoints for listing, previewing, and applying monitor presets
that create broad pipeline protection using the existing Health Watch substrate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import ActingPrincipal, require_principal
from .lineage import _get_engine_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class PresetPreviewRequest(BaseModel):
    """Request to preview what a preset would create."""
    preset_key: str = Field(..., description="Preset identifier")
    anchor_node_id: str = Field(..., description="User-selected anchor node ID")
    existing_fqns: Optional[List[str]] = Field(
        None, description="Existing MONITOR_KEY:fqn strings for dedup"
    )


class SmartBuildPreviewRequest(BaseModel):
    """Request to preview a smart-build analysis."""
    anchor_node_id: str = Field(..., description="User-selected anchor node ID")
    existing_fqns: Optional[List[str]] = Field(
        None, description="Existing MONITOR_KEY:fqn strings for dedup"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/presets")
async def list_presets(
    node_id: Optional[str] = Query(None, description="Node ID to check eligibility against"),
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Return all preset definitions with eligibility for a given node."""
    try:
        from scanner.monitors.presets import get_all_presets
    except ImportError:
        from monitors.presets import get_all_presets

    node = None
    if node_id:
        store = _get_engine_store(principal.organization_id, stack_id)
        if store.graph:
            node = store.graph.nodes.get(node_id)

    return {"presets": get_all_presets(node)}


@router.post("/presets/preview")
async def preview_preset(
    request: PresetPreviewRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Preview what monitors a preset would create without persisting anything."""
    try:
        from scanner.monitors.presets import preview_preset as _preview
    except ImportError:
        from monitors.presets import preview_preset as _preview

    store = _get_engine_store(principal.organization_id, stack_id)
    if not store.graph:
        raise HTTPException(
            status_code=404,
            detail="No lineage graph available. Run a scan first.",
        )

    existing_fqns = set(request.existing_fqns or [])
    result = _preview(
        graph=store.graph,
        anchor_id=request.anchor_node_id,
        preset_key=request.preset_key,
        existing_monitor_fqns=existing_fqns,
    )

    return result.to_dict()


@router.post("/presets/smart-build")
async def smart_build_preview(
    request: SmartBuildPreviewRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Auto-determine the best watches based on upstream graph shape."""
    try:
        from scanner.monitors.presets import smart_build_preview as _smart_build
    except ImportError:
        from monitors.presets import smart_build_preview as _smart_build

    store = _get_engine_store(principal.organization_id, stack_id)
    if not store.graph:
        raise HTTPException(
            status_code=404,
            detail="No lineage graph available. Run a scan first.",
        )

    existing_fqns = set(request.existing_fqns or [])
    result = _smart_build(
        graph=store.graph,
        anchor_id=request.anchor_node_id,
        existing_monitor_fqns=existing_fqns,
    )

    return result.to_dict()
