"""HTTP API for ContextRequest lifecycle.

This router is stateless: the FastAPI process has no Prisma client, so all
database reads/writes for ContextRequest, ContextResolution, PipelineContext
and PolicyAssignment live in Next.js (see app/api/context-requests/* and
app/api/clarifications/resolve/route.ts).

What lives here is the bit that *can't* run in Next.js: the Python kind
handler (`copilot.clarifications.registry.get_kind_handler`). For the answer
flow, Next.js loads the request row from Prisma, calls
`POST /api/v1/context-requests/compute-resolution` with the row + answer,
this router validates the answer with the registered handler, runs the
handler's `on_resolve` against an in-memory façade (the same shape the
unit tests use — `.conventions` and `.overrides` dicts), and returns the
populated façade so Next.js can persist conventions and overrides via
Prisma. We also emit `context_resolved` on the in-process bus so guessers
(sla_discovery, monitor evaluation) can react in this process.

The brief's GET/list/dismiss/answer endpoints are in Next.js — see the
proxies in app/api/context-requests/. This file does not duplicate them.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from copilot.clarifications.events import BUS
from copilot.clarifications.registry import get_kind_handler
# Import kinds package so handlers register themselves at module load.
from copilot.clarifications import kinds as _kinds  # noqa: F401

from scanner.api.auth import ActingPrincipal, require_principal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context-requests", tags=["clarifications"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class _RequestRow(BaseModel):
    """Mirror of a ContextRequest row, sent inline by Next.js."""

    model_config = {"populate_by_name": True}

    id: str
    pipelineStackId: str
    kind: str
    scopeType: str
    scopeRef: str
    payload: Dict[str, Any]
    status: str = "open"
    priority: str = "normal"


class ComputeResolutionBody(BaseModel):
    """Body of POST /context-requests/compute-resolution.

    Next.js loads the ContextRequest row, sends it inline alongside the
    answer; we validate + invoke the kind handler and return the populated
    façade for Next.js to persist via Prisma.
    """

    model_config = {"populate_by_name": True}

    request: _RequestRow
    answer: Dict[str, Any]
    transcript: Optional[List[Dict[str, Any]]] = None
    propose_convention: bool = Field(False, alias="proposeConvention")


class ComputeResolutionResponse(BaseModel):
    """Response shape Next.js consumes to persist conventions/overrides."""

    ok: bool
    kind: str
    scopeType: str
    scopeRef: str
    conventionUpdated: bool
    # Conventions to merge into PipelineContext.conventionsContext for the
    # given pipelineStackId. Shape is whatever the kind's on_resolve sets.
    conventions: Dict[str, Any] = Field(default_factory=dict)
    # Per-node overrides keyed by nodeFqn. Each value is a dict to merge into
    # PolicyAssignment.overrides for that node.
    overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# In-memory façade — same shape the kind handler unit tests use
# ---------------------------------------------------------------------------


class _Facade:
    """In-memory stand-in for the Prisma client.

    Mirrors the `_FakeDB` shape used in
    `scanner/copilot/clarifications/tests/test_engine.py` so the kind
    handler's `on_resolve` writes into ordinary Python dicts that we can
    return to Next.js for persistence.
    """

    def __init__(self) -> None:
        self.conventions: Dict[str, Dict[str, Any]] = {}
        self.overrides: Dict[tuple, Dict[str, Any]] = {}


class _RequestShim:
    """Object with the attributes the kind handler reads off a Prisma row."""

    def __init__(self, row: _RequestRow) -> None:
        self.id = row.id
        self.pipelineStackId = row.pipelineStackId
        self.kind = row.kind
        self.scopeType = row.scopeType
        self.scopeRef = row.scopeRef
        self.payload = dict(row.payload)
        self.status = row.status
        self.priority = row.priority


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/compute-resolution", response_model=ComputeResolutionResponse)
async def compute_resolution(
    body: ComputeResolutionBody,
    principal: ActingPrincipal = Depends(require_principal),
) -> ComputeResolutionResponse:
    """Validate an answer and compute conventions/overrides.

    Stateless: we do not touch Prisma here. Next.js calls this endpoint
    with the ContextRequest row + answer, persists the resulting
    conventions/overrides, and writes the ContextResolution + status
    update transactionally on its side.
    """
    req = body.request

    if req.status != "open":
        raise HTTPException(status_code=409, detail=f"Request is {req.status}, not open")

    try:
        handler = get_kind_handler(req.kind)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown clarification kind: {exc}")

    try:
        handler.validate_answer(body.answer)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid answer: {exc}")

    facade = _Facade()
    shim = _RequestShim(req)
    try:
        handler.on_resolve(shim, body.answer, facade)
    except Exception as exc:
        logger.exception("on_resolve raised for kind=%s request_id=%s", req.kind, req.id)
        raise HTTPException(status_code=500, detail=f"on_resolve failed: {exc}")

    # Pull the conventions for this pipeline stack — the handler writes them
    # keyed by pipelineStackId so the same façade can be reused across kinds.
    conventions_for_stack = facade.conventions.get(req.pipelineStackId, {})
    convention_updated = bool(conventions_for_stack)

    # Flatten overrides keyed by (pipelineStackId, nodeFqn) into a Next.js-
    # friendly map keyed by nodeFqn (filtered to this pipeline stack so we
    # don't leak across stacks if a future handler ever sets keys for
    # other stacks — current handlers don't, but be explicit).
    overrides_by_node: Dict[str, Dict[str, Any]] = {}
    for key, payload in (facade.overrides or {}).items():
        # Keys are (pipelineStackId, nodeFqn) tuples per the test fake's
        # contract; tolerate single-string keys defensively.
        if isinstance(key, tuple) and len(key) == 2:
            ps_id, node_fqn = key
        else:
            ps_id, node_fqn = req.pipelineStackId, str(key)
        if ps_id != req.pipelineStackId:
            continue
        overrides_by_node[node_fqn] = dict(payload or {})

    # Emit the in-process bus event so guessers running in the FastAPI
    # process (sla_discovery re-run, etc.) can react. Cross-process
    # consumers receive the event when Next.js calls back into the
    # copilot tool — that's a separate path.
    try:
        BUS.emit("context_resolved", {
            "request_id": req.id,
            "kind": req.kind,
            "scope_type": req.scopeType,
            "scope_ref": req.scopeRef,
            "answer": body.answer,
            "pipeline_stack_id": req.pipelineStackId,
        })
    except Exception:
        logger.debug("BUS.emit(context_resolved) raised", exc_info=True)

    logger.info(
        "context_request.resolved",
        extra={
            "request_id": req.id,
            "kind": req.kind,
            "scope_type": req.scopeType,
            "scope_ref": req.scopeRef,
            "convention_updated": convention_updated,
            "overrides_count": len(overrides_by_node),
            "user_id": principal.user_id,
            "org_id": principal.organization_id,
        },
    )

    return ComputeResolutionResponse(
        ok=True,
        kind=req.kind,
        scopeType=req.scopeType,
        scopeRef=req.scopeRef,
        conventionUpdated=convention_updated,
        conventions=conventions_for_stack,
        overrides=overrides_by_node,
    )
