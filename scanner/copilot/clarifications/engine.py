"""ClarificationEngine: the only module that touches ContextRequest /
ContextResolution. Guessers call emit/lookup; the LLM tool calls resolve."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from copilot.clarifications.config import CONFIG
from copilot.clarifications.events import BUS
from copilot.clarifications.registry import get_kind_handler


@dataclass
class _Resolution:
    id: str
    requestId: str
    answer: Dict[str, Any]
    transcript: List[Dict[str, Any]]
    conventionUpdate: Optional[Dict[str, Any]] = None
    answeredBy: str = ""
    answeredAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _is_prisma_client(db: Any) -> bool:
    return hasattr(db, "contextrequest") or hasattr(db, "context_request")


class ClarificationEngine:
    """Façade over the Prisma client (or a fake in tests)."""

    def __init__(self, db: Any):
        self.db = db

    def emit(
        self,
        *,
        pipeline_stack_id: str,
        kind: str,
        scope_type: str,
        scope_ref: str,
        payload: Dict[str, Any],
        priority: str = "normal",
    ):
        handler = get_kind_handler(kind)
        handler.validate_payload(payload)

        existing = self._find_open(pipeline_stack_id, kind, scope_type, scope_ref)
        if existing is not None:
            return existing

        if self._is_suppressed(pipeline_stack_id, kind, scope_type, scope_ref):
            return None

        return self._create_request(
            pipeline_stack_id=pipeline_stack_id,
            kind=kind,
            scope_type=scope_type,
            scope_ref=scope_ref,
            payload=payload,
            priority=priority,
        )

    def lookup(
        self,
        *,
        pipeline_stack_id: str,
        kind: str,
        scope_type: str,
        scope_ref: str,
    ) -> Optional[Dict[str, Any]]:
        return self._read_conventions(pipeline_stack_id).get(kind)

    def resolve(
        self,
        *,
        request,
        answer: Dict[str, Any],
        transcript: List[Dict[str, Any]],
        answered_by: str,
    ) -> _Resolution:
        handler = get_kind_handler(request.kind)
        handler.validate_answer(answer)
        handler.on_resolve(request, answer, self.db)

        request.status = "answered"
        request.resolvedAt = datetime.now(timezone.utc)

        resolution = _Resolution(
            id=f"res-{request.id}",
            requestId=request.id,
            answer=answer,
            transcript=transcript,
            answeredBy=answered_by,
        )
        self._save_resolution(resolution)
        BUS.emit("context_resolved", {
            "request_id": request.id,
            "kind": request.kind,
            "scope_type": request.scopeType,
            "scope_ref": request.scopeRef,
            "answer": answer,
        })
        return resolution

    def dismiss(self, *, request, days: int = CONFIG.dismiss_decay_days) -> None:
        request.status = "dismissed"
        request.dismissedUntil = datetime.now(timezone.utc) + timedelta(days=days)

    # --- Storage façade methods (overridable, dual-path) ----------------------

    def _find_open(self, ps_id, kind, st, sr):
        if _is_prisma_client(self.db):
            return None  # production path uses dedupe at the API layer
        for r in self.db.requests:
            if (r.pipelineStackId == ps_id and r.kind == kind
                    and r.scopeType == st and r.scopeRef == sr
                    and r.status == "open"):
                return r
        return None

    def _is_suppressed(self, ps_id, kind, st, sr) -> bool:
        if _is_prisma_client(self.db):
            return False
        now = datetime.now(timezone.utc)
        for r in self.db.requests:
            if (r.pipelineStackId == ps_id and r.kind == kind
                    and r.scopeType == st and r.scopeRef == sr
                    and r.status == "dismissed"
                    and r.dismissedUntil and r.dismissedUntil > now):
                return True
        return False

    def _create_request(self, **kwargs):
        if _is_prisma_client(self.db):
            # Real Prisma path: caller (API/router) is async, so we can't run async here.
            # The router will create the row and pass the model to resolve; emit's prod path
            # is invoked via a sync helper that the API wraps. For now, raise to signal
            # the API layer must handle creation directly when using a Prisma client.
            raise NotImplementedError(
                "Prisma create must be called from the async API layer; engine.emit is "
                "for the in-memory fake DB path used in unit tests."
            )
        # Fake DB path
        from copilot.clarifications.tests.test_engine import _FakeRequest  # type: ignore
        req = _FakeRequest(
            id=f"req{len(self.db.requests) + 1}",
            pipelineStackId=kwargs["pipeline_stack_id"],
            kind=kwargs["kind"],
            scopeType=kwargs["scope_type"],
            scopeRef=kwargs["scope_ref"],
            payload=kwargs["payload"],
            status="open",
            priority=kwargs["priority"],
        )
        self.db.requests.append(req)
        return req

    def _save_resolution(self, resolution: _Resolution) -> None:
        if _is_prisma_client(self.db):
            # API layer handles persistence; this is a no-op in production.
            return
        self.db.resolutions.append(resolution)

    def _read_conventions(self, ps_id: str) -> Dict[str, Any]:
        if _is_prisma_client(self.db):
            return {}  # API layer reads conventions; engine.lookup falls through
        return self.db.conventions.get(ps_id, {})
