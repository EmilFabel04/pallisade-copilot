"""Flow A: tentative discovery -> ContextRequest emitted -> resolve writes
conventions -> next discovery uses convention.

This test exercises the in-process slice of the loop. It does NOT exercise
the Next.js HTTP layer; that's covered by manual smoke testing in Task 19.
"""
from datetime import datetime, timezone

import pytest

from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.events import BUS
from copilot.clarifications.registry import KIND_REGISTRY


@pytest.fixture(autouse=True)
def _ensure_timestamp_choice_registered():
    """Other tests in the suite call KIND_REGISTRY.clear(), which wipes the
    self-registration that happens at module import. Force re-registration
    before each test in this file so we don't depend on test ordering."""
    if "timestamp_choice" not in KIND_REGISTRY:
        # Re-running the kind module's body re-registers it. We import lazily
        # so this fixture also handles the cold-start case.
        import importlib

        from copilot.clarifications.kinds import timestamp_choice as _tc
        importlib.reload(_tc)
    yield


class _FakeRequest:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "req1")
        self.pipelineStackId = kwargs.get("pipelineStackId", "ps1")
        self.kind = kwargs.get("kind", "timestamp_choice")
        self.scopeType = kwargs.get("scopeType", "node")
        self.scopeRef = kwargs.get("scopeRef", "raw.orders")
        self.payload = kwargs.get("payload", {})
        self.status = kwargs.get("status", "open")
        self.priority = kwargs.get("priority", "normal")
        self.createdAt = kwargs.get("createdAt", datetime.now(timezone.utc))
        self.dismissedUntil = kwargs.get("dismissedUntil")
        self.resolvedAt = None


class _FakeDB:
    def __init__(self):
        self.requests = []
        self.resolutions = []
        self.conventions = {}
        self.overrides = {}


def test_emit_dedupes_and_resolve_writes_conventions():
    """End-to-end engine slice: emit creates request, dedupe returns same row,
    resolve calls the kind handler which populates conventions + overrides."""
    db = _FakeDB()
    engine = ClarificationEngine(db=db)

    payload = {
        "table_fqn": "raw.orders",
        "candidates": ["loaded_at", "created_at", "updated_at"],
        "confidence": 0.5,
        "evidence": {},
    }

    # First emit creates a row.
    req = engine.emit(
        pipeline_stack_id="ps1",
        kind="timestamp_choice",
        scope_type="node",
        scope_ref="raw.orders",
        payload=payload,
        priority="normal",
    )
    assert req is not None
    assert req.kind == "timestamp_choice"
    assert len(db.requests) == 1

    # Dedupe: a second emit with the same scope returns the same row.
    same = engine.emit(
        pipeline_stack_id="ps1",
        kind="timestamp_choice",
        scope_type="node",
        scope_ref="raw.orders",
        payload=payload,
        priority="normal",
    )
    assert same is req
    assert len(db.requests) == 1

    # Resolve writes per-node override and dataset convention.
    received = []
    BUS.subscribe("context_resolved", lambda p: received.append(p))

    engine.resolve(
        request=req,
        answer={"column": "loaded_at"},
        transcript=[{"role": "user", "content": "use loaded_at"}],
        answered_by="user_test",
    )

    assert req.status == "answered"
    # Per-node override populated:
    assert ("ps1", "raw.orders") in db.overrides
    assert db.overrides[("ps1", "raw.orders")]["clarifications"]["volume_timestamp_column"] == "loaded_at"
    # Dataset-level convention populated:
    assert "volume_timestamp_preference" in db.conventions["ps1"]
    assert "loaded_at" in db.conventions["ps1"]["volume_timestamp_preference"]["ordered"]
    # Event fired:
    assert any(p.get("scope_ref") == "raw.orders" for p in received)


def test_dismiss_suppresses_subsequent_emit():
    """A dismissed request blocks re-emit until dismissedUntil expires."""
    db = _FakeDB()
    engine = ClarificationEngine(db=db)
    payload = {"table_fqn": "raw.orders", "candidates": ["loaded_at"], "confidence": 0.4}

    req = engine.emit(
        pipeline_stack_id="ps1",
        kind="timestamp_choice",
        scope_type="node",
        scope_ref="raw.orders",
        payload=payload,
        priority="normal",
    )
    engine.dismiss(request=req)
    assert req.status == "dismissed"
    assert req.dismissedUntil is not None

    # Re-emit while dismissed -> suppressed (engine returns None).
    again = engine.emit(
        pipeline_stack_id="ps1",
        kind="timestamp_choice",
        scope_type="node",
        scope_ref="raw.orders",
        payload=payload,
        priority="normal",
    )
    assert again is None
    # Same request count (still 1, the dismissed one).
    assert len(db.requests) == 1
