import pytest
from copilot.clarifications.registry import (
    KindHandler,
    register_kind,
    get_kind_handler,
    KIND_REGISTRY,
)


def _make_handler(name: str) -> KindHandler:
    return KindHandler(
        kind=name,
        validate_payload=lambda p: None,
        validate_answer=lambda a: None,
        load_prompt=lambda payload: f"prompt for {name}",
        on_resolve=lambda req, ans, db: None,
    )


def test_register_and_lookup_kind():
    KIND_REGISTRY.clear()
    h = _make_handler("test_kind")
    register_kind(h)
    assert get_kind_handler("test_kind") is h


def test_get_unknown_kind_raises():
    KIND_REGISTRY.clear()
    with pytest.raises(KeyError):
        get_kind_handler("does_not_exist")


def test_register_duplicate_raises():
    KIND_REGISTRY.clear()
    register_kind(_make_handler("dup"))
    with pytest.raises(ValueError):
        register_kind(_make_handler("dup"))


from copilot.clarifications.events import EventBus


def test_event_bus_subscribe_and_emit():
    bus = EventBus()
    received = []
    bus.subscribe("context_resolved", lambda payload: received.append(payload))
    bus.emit("context_resolved", {"id": "abc"})
    assert received == [{"id": "abc"}]


def test_event_bus_unsubscribe():
    bus = EventBus()
    received = []
    handler = lambda p: received.append(p)
    bus.subscribe("e", handler)
    bus.unsubscribe("e", handler)
    bus.emit("e", {"x": 1})
    assert received == []


from datetime import datetime, timedelta, timezone
from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.registry import KIND_REGISTRY, register_kind, KindHandler


class _FakeRequest:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "req1")
        self.pipelineStackId = kwargs.get("pipelineStackId", "ps1")
        self.kind = kwargs.get("kind", "k")
        self.scopeType = kwargs.get("scopeType", "node")
        self.scopeRef = kwargs.get("scopeRef", "raw.orders")
        self.payload = kwargs.get("payload", {})
        self.status = kwargs.get("status", "open")
        self.priority = kwargs.get("priority", "normal")
        self.createdAt = kwargs.get("createdAt", datetime.now(timezone.utc))
        self.dismissedUntil = kwargs.get("dismissedUntil")


class _FakeDB:
    """Minimal in-memory stand-in for a Prisma client."""
    def __init__(self):
        self.requests = []
        self.resolutions = []
        self.conventions = {}
        self.overrides = {}


def _register_test_kind():
    KIND_REGISTRY.clear()
    captured = {}
    def _on_resolve(req, ans, db):
        captured["called_with"] = (req.id, ans)
    register_kind(KindHandler(
        kind="k",
        validate_payload=lambda p: None,
        validate_answer=lambda a: None,
        load_prompt=lambda p: "ask",
        on_resolve=_on_resolve,
    ))
    return captured


def test_emit_creates_request_when_none_open():
    captured = _register_test_kind()
    db = _FakeDB()
    engine = ClarificationEngine(db=db)
    req = engine.emit(
        pipeline_stack_id="ps1",
        kind="k",
        scope_type="node",
        scope_ref="raw.orders",
        payload={"candidates": ["a", "b"]},
        priority="normal",
    )
    assert req.kind == "k"
    assert len(db.requests) == 1


def test_emit_dedupes_open_request():
    _register_test_kind()
    db = _FakeDB()
    db.requests.append(_FakeRequest(kind="k", scopeType="node", scopeRef="raw.orders"))
    engine = ClarificationEngine(db=db)
    req = engine.emit(
        pipeline_stack_id="ps1", kind="k",
        scope_type="node", scope_ref="raw.orders",
        payload={}, priority="normal",
    )
    assert req.id == "req1"
    assert len(db.requests) == 1


def test_emit_suppressed_during_dismiss_window():
    _register_test_kind()
    db = _FakeDB()
    future = datetime.now(timezone.utc) + timedelta(days=5)
    db.requests.append(_FakeRequest(
        kind="k", scopeType="node", scopeRef="raw.orders",
        status="dismissed", dismissedUntil=future,
    ))
    engine = ClarificationEngine(db=db)
    req = engine.emit(
        pipeline_stack_id="ps1", kind="k",
        scope_type="node", scope_ref="raw.orders",
        payload={}, priority="normal",
    )
    assert req is None
    assert len(db.requests) == 1


def test_resolve_calls_on_resolve_and_marks_answered():
    captured = _register_test_kind()
    db = _FakeDB()
    req = _FakeRequest()
    db.requests.append(req)
    engine = ClarificationEngine(db=db)
    resolution = engine.resolve(
        request=req,
        answer={"column": "loaded_at"},
        transcript=[{"role": "user", "content": "use loaded_at"}],
        answered_by="user1",
    )
    assert req.status == "answered"
    assert resolution.answer == {"column": "loaded_at"}
    assert captured["called_with"] == ("req1", {"column": "loaded_at"})
