# Clarification Layer — Plan 1: Foundation + Flow A (V1.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the end-to-end clarification loop for one kind (`timestamp_choice`) — emit on uncertain SLA discovery, ask via popup chat, persist answer, re-run discovery — proving the entire architecture before adding more kinds.

**Architecture:** A new `ClarificationEngine` module owns the new `ContextRequest`/`ContextResolution` tables. Guessers (this plan: `_pick_volume_timestamp_column`) call `engine.lookup` first, then `engine.emit` on low confidence. The copilot LLM gets a new `clarify` mode with a `record_clarification_answer` tool that writes back through the engine. Frontend gets a new `LLMBell` icon and a right-anchored popup chat panel.

**Tech Stack:** FastAPI, Prisma (Postgres), Anthropic + OpenAI SDKs, Next.js 15, React.

**Spec:** `docs/superpowers/specs/2026-04-30-clarification-context-layer-design.md`

---

## File structure

**New files:**
- `scanner/copilot/clarifications/__init__.py`
- `scanner/copilot/clarifications/config.py`
- `scanner/copilot/clarifications/engine.py`
- `scanner/copilot/clarifications/registry.py`
- `scanner/copilot/clarifications/events.py`
- `scanner/copilot/clarifications/kinds/__init__.py`
- `scanner/copilot/clarifications/kinds/timestamp_choice/__init__.py`
- `scanner/copilot/clarifications/kinds/timestamp_choice/schemas.py`
- `scanner/copilot/clarifications/kinds/timestamp_choice/parser.py`
- `scanner/copilot/clarifications/kinds/timestamp_choice/conventions.py`
- `scanner/copilot/clarifications/kinds/timestamp_choice/prompt.md`
- `scanner/copilot/clarifications/tests/__init__.py`
- `scanner/copilot/clarifications/tests/test_engine.py`
- `scanner/copilot/clarifications/tests/test_timestamp_choice.py`
- `scanner/copilot/tools/clarifications.py`
- `scanner/api/routers/context_requests.py`
- `scanner/tests/test_clarification_flow_a.py`
- `app/api/context-requests/route.ts`
- `app/api/context-requests/[id]/answer/route.ts`
- `app/api/context-requests/[id]/dismiss/route.ts`
- `components/clarifications/LLMBell.tsx`
- `components/clarifications/ClarificationPopup.tsx`
- `components/clarifications/ClarificationProvider.tsx`
- `lib/clarifications/client.ts`
- `lib/clarifications/types.ts`

**Modified files:**
- `prisma/schema.prisma` (add models, add relation field on `PipelineStack`)
- `scanner/lineage/sla_discovery.py` (lines 582–641, 820, 841–853)
- `scanner/copilot/llm.py` (add CLARIFY system prompt routing)
- `scanner/copilot/modes.py` (add `CLARIFY` enum + `MODES` entry + `/clarify` slash command)
- `scanner/copilot/context_builder.py` (load `ContextRequest` payload when `mode=clarify`)
- `scanner/copilot/tool_executor.py` (add `_execute_record_clarification_answer`)
- `scanner/api/main.py` (register the new router)
- `app/layout.tsx` (mount `ClarificationProvider`)
- `app/(dashboard)/layout.tsx` (render `LLMBell` + `ClarificationPopup` in the top bar)
- `components/lineage/SLAEditorPanel.tsx` (render tentative tag when discovery returns `tentative: true`)

---

## Conventions for this plan

- **Branch**: a worktree is created for execution; commit on the worktree's branch.
- **Tests**: Python tests live in `scanner/copilot/clarifications/tests/` and `scanner/tests/`; use existing `pytest` runner.
- **IDs**: `cuid()` (matches existing convention).
- **Commit messages**: `feat(clarifications): <subject>` (frontend uses `feat(clarifications/ui): ...`).

---

## Task 1: Add Prisma models

**Files:**
- Modify: `prisma/schema.prisma`

- [ ] **Step 1: Add `ContextRequest` and `ContextResolution` models**

In `prisma/schema.prisma`, append after the `PolicyAssignment` model:

```prisma
model ContextRequest {
  id              String   @id @default(cuid())
  pipelineStackId String
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)

  kind            String
  scopeType       String
  scopeRef        String

  payload         Json

  status          String   @default("open")
  priority        String   @default("normal")

  createdAt       DateTime @default(now())
  resolvedAt      DateTime?
  dismissedUntil  DateTime?
  resolutionId    String?  @unique
  resolution      ContextResolution?

  @@index([pipelineStackId, status])
  @@index([scopeType, scopeRef])
  @@index([pipelineStackId, kind, status])
}

model ContextResolution {
  id              String   @id @default(cuid())
  requestId       String   @unique
  request         ContextRequest @relation(fields: [requestId], references: [id], onDelete: Cascade)

  answer          Json
  transcript      Json
  conventionUpdate Json?

  answeredBy      String
  answeredAt      DateTime @default(now())
}
```

- [ ] **Step 2: Add reverse relation on `PipelineStack`**

Find the `PipelineStack` model (around line 303). Add after the existing relation fields:

```prisma
  contextRequests ContextRequest[]
```

- [ ] **Step 3: Generate Prisma client and create migration**

Run:
```bash
npx prisma migrate dev --name add_clarification_models
```

Expected: migration applied, `node_modules/@prisma/client` regenerated.

- [ ] **Step 4: Commit**

```bash
git add prisma/
git commit -m "feat(clarifications): add ContextRequest and ContextResolution models"
```

---

## Task 2: Clarification engine — config module

**Files:**
- Create: `scanner/copilot/clarifications/__init__.py`
- Create: `scanner/copilot/clarifications/config.py`

- [ ] **Step 1: Create the package**

`scanner/copilot/clarifications/__init__.py`:

```python
"""Clarification engine: detects ambiguous platform decisions, captures user
context via the copilot, and persists answers as overrides or conventions."""
```

- [ ] **Step 2: Create `config.py`**

```python
"""Configuration constants for the clarification engine."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ClarificationConfig:
    # Confidence below which a guesser must emit a ContextRequest.
    confidence_threshold: float = 0.7

    # After dismiss, suppress re-emit of the same (kind, scopeType, scopeRef)
    # for this many days unless underlying evidence changes.
    dismiss_decay_days: int = 14

    # Borderline-failure z-score band (used by Plan 2; defined here so the band
    # is configurable from one place).
    borderline_band_lower: float = 1.5

    # Max ContextRequests to fetch in a single list call.
    list_page_size: int = 50


CONFIG = ClarificationConfig()
```

- [ ] **Step 3: Commit**

```bash
git add scanner/copilot/clarifications/
git commit -m "feat(clarifications): scaffold package + config"
```

---

## Task 3: Clarification engine — kind registry

**Files:**
- Create: `scanner/copilot/clarifications/registry.py`
- Create: `scanner/copilot/clarifications/kinds/__init__.py`
- Create: `scanner/copilot/clarifications/tests/__init__.py`
- Create: `scanner/copilot/clarifications/tests/test_engine.py`

- [ ] **Step 1: Write the failing test for the registry**

`scanner/copilot/clarifications/tests/test_engine.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: FAIL with `ModuleNotFoundError: copilot.clarifications.registry`.

- [ ] **Step 3: Implement the registry**

`scanner/copilot/clarifications/registry.py`:

```python
"""Per-kind handler registry.

Each kind plugs in a handler with: payload validator, answer validator,
prompt loader, and on_resolve hook (which writes conventions/overrides).
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass
class KindHandler:
    kind: str
    validate_payload: Callable[[Dict[str, Any]], None]
    validate_answer: Callable[[Dict[str, Any]], None]
    load_prompt: Callable[[Dict[str, Any]], str]
    on_resolve: Callable[[Any, Dict[str, Any], Any], None]


KIND_REGISTRY: Dict[str, KindHandler] = {}


def register_kind(handler: KindHandler) -> None:
    if handler.kind in KIND_REGISTRY:
        raise ValueError(f"Kind {handler.kind!r} already registered")
    KIND_REGISTRY[handler.kind] = handler


def get_kind_handler(kind: str) -> KindHandler:
    if kind not in KIND_REGISTRY:
        raise KeyError(f"Unknown clarification kind: {kind!r}")
    return KIND_REGISTRY[kind]
```

- [ ] **Step 4: Create the kinds package init**

`scanner/copilot/clarifications/kinds/__init__.py`:

```python
"""Per-kind handlers. Importing this package registers all kinds."""
from . import timestamp_choice  # noqa: F401  (registration side effect)
```

(`timestamp_choice` will be created in Task 6; this import will fail until then. Mark this file with a comment so executors don't worry.)

`scanner/copilot/clarifications/tests/__init__.py`: empty file.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/clarifications/
git commit -m "feat(clarifications): kind handler registry"
```

---

## Task 4: Clarification engine — events bus

**Files:**
- Create: `scanner/copilot/clarifications/events.py`

- [ ] **Step 1: Write the failing test**

Append to `scanner/copilot/clarifications/tests/test_engine.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: 2 new tests fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the bus**

`scanner/copilot/clarifications/events.py`:

```python
"""Tiny in-process pub/sub for clarification lifecycle events.

Used so guessers (sla_discovery, monitor evaluation) can react to
context_resolved without import cycles.
"""
from collections import defaultdict
from typing import Any, Callable, Dict, List


class EventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        self._subs[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        if handler in self._subs[event]:
            self._subs[event].remove(handler)

    def emit(self, event: str, payload: Any) -> None:
        for h in list(self._subs[event]):
            h(payload)


BUS = EventBus()
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/clarifications/
git commit -m "feat(clarifications): in-process event bus"
```

---

## Task 5: Clarification engine — core

**Files:**
- Create: `scanner/copilot/clarifications/engine.py`
- Modify: `scanner/copilot/clarifications/tests/test_engine.py`

- [ ] **Step 1: Write the failing tests**

Append to `scanner/copilot/clarifications/tests/test_engine.py`:

```python
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
        self.conventions = {}  # pipelineStackId -> conventionsContext dict
        self.overrides = {}    # (assignment_key) -> overrides dict

    def emit_record(self, req: _FakeRequest):
        self.requests.append(req)


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
    assert req.id == "req1"  # returned existing
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
    assert req is None  # suppressed
    assert len(db.requests) == 1  # no new row added


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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: 4 new tests fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the engine**

`scanner/copilot/clarifications/engine.py`:

```python
"""ClarificationEngine: the only module that touches ContextRequest /
ContextResolution. Guessers call emit/lookup; the LLM tool calls resolve."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

        # Dedupe: if there's an open request for the same (kind, scope), return it.
        existing = self._find_open(pipeline_stack_id, kind, scope_type, scope_ref)
        if existing is not None:
            return existing

        # Suppress: if a recent dismiss is still in its decay window, don't re-emit.
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
        """Return an existing answer for this scope, honouring precedence:
        node override → dataset convention → pipeline convention → None.

        Precedence resolution lives in each kind's `lookup_existing` helper
        when needed; the engine just exposes the conventions blob.
        """
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
        from datetime import timedelta
        request.status = "dismissed"
        request.dismissedUntil = datetime.now(timezone.utc) + timedelta(days=days)

    # --- DB façade methods (overridable by fakes) -----------------------------

    def _find_open(self, ps_id, kind, st, sr):
        for r in self.db.requests:
            if (r.pipelineStackId == ps_id and r.kind == kind
                    and r.scopeType == st and r.scopeRef == sr
                    and r.status == "open"):
                return r
        return None

    def _is_suppressed(self, ps_id, kind, st, sr) -> bool:
        now = datetime.now(timezone.utc)
        for r in self.db.requests:
            if (r.pipelineStackId == ps_id and r.kind == kind
                    and r.scopeType == st and r.scopeRef == sr
                    and r.status == "dismissed"
                    and r.dismissedUntil and r.dismissedUntil > now):
                return True
        return False

    def _create_request(self, **kwargs):
        # Fake DB path used in unit tests; the production path overrides this
        # with a real Prisma create.
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
        self.db.resolutions.append(resolution)

    def _read_conventions(self, ps_id: str) -> Dict[str, Any]:
        return self.db.conventions.get(ps_id, {})
```

- [ ] **Step 4: Run tests**

```bash
pytest scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/clarifications/
git commit -m "feat(clarifications): ClarificationEngine with emit/lookup/resolve/dismiss"
```

---

## Task 6: timestamp_choice kind — schemas and parser

**Files:**
- Create: `scanner/copilot/clarifications/kinds/timestamp_choice/__init__.py`
- Create: `scanner/copilot/clarifications/kinds/timestamp_choice/schemas.py`
- Create: `scanner/copilot/clarifications/kinds/timestamp_choice/parser.py`
- Create: `scanner/copilot/clarifications/kinds/timestamp_choice/conventions.py`
- Create: `scanner/copilot/clarifications/kinds/timestamp_choice/prompt.md`
- Create: `scanner/copilot/clarifications/tests/test_timestamp_choice.py`

- [ ] **Step 1: Write failing tests**

`scanner/copilot/clarifications/tests/test_timestamp_choice.py`:

```python
import pytest
from copilot.clarifications.kinds.timestamp_choice.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.timestamp_choice.parser import parse_reply


def test_payload_requires_candidates_and_table_fqn():
    with pytest.raises(ValueError):
        validate_payload({})
    with pytest.raises(ValueError):
        validate_payload({"candidates": []})
    validate_payload({
        "table_fqn": "raw.orders",
        "candidates": ["loaded_at", "created_at"],
        "evidence": {},
    })


def test_answer_requires_column():
    with pytest.raises(ValueError):
        validate_answer({})
    validate_answer({"column": "loaded_at"})


def test_parse_reply_picks_named_column():
    candidates = ["loaded_at", "created_at", "updated_at"]
    assert parse_reply("use loaded_at please", candidates) == {"column": "loaded_at"}
    assert parse_reply("definitely created_at", candidates) == {"column": "created_at"}


def test_parse_reply_returns_none_when_unparseable():
    assert parse_reply("idk", ["a", "b"]) is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest scanner/copilot/clarifications/tests/test_timestamp_choice.py -v
```

Expected: 4 fails with ModuleNotFoundError.

- [ ] **Step 3: Implement schemas**

`scanner/copilot/clarifications/kinds/timestamp_choice/schemas.py`:

```python
"""Payload + answer schemas for timestamp_choice."""
from typing import Any, Dict


def validate_payload(payload: Dict[str, Any]) -> None:
    if "table_fqn" not in payload or not isinstance(payload["table_fqn"], str):
        raise ValueError("payload.table_fqn (str) is required")
    if "candidates" not in payload or not isinstance(payload["candidates"], list):
        raise ValueError("payload.candidates (list) is required")
    # candidates may be empty; the LLM will ask open-ended.


def validate_answer(answer: Dict[str, Any]) -> None:
    if "column" not in answer or not isinstance(answer["column"], str):
        raise ValueError("answer.column (str) is required")
```

- [ ] **Step 4: Implement parser**

`scanner/copilot/clarifications/kinds/timestamp_choice/parser.py`:

```python
"""Parse a free-text user reply into {"column": "<name>"}.

The LLM should already produce structured output via the
record_clarification_answer tool, but this parser is the fallback when
the LLM emits prose only — it scans for a candidate name in the reply.
"""
from typing import List, Optional, Dict


def parse_reply(reply: str, candidates: List[str]) -> Optional[Dict[str, str]]:
    text = reply.lower()
    # Prefer longer candidates first to avoid prefix collisions.
    for cand in sorted(candidates, key=len, reverse=True):
        if cand.lower() in text:
            return {"column": cand}
    return None
```

- [ ] **Step 5: Implement conventions writer**

`scanner/copilot/clarifications/kinds/timestamp_choice/conventions.py`:

```python
"""On resolve, write the answer into PolicyAssignment.overrides for the node
and (optionally) into PipelineContext.conventionsContext for the dataset prefix."""
from typing import Any, Dict


def on_resolve(request: Any, answer: Dict[str, Any], db: Any) -> None:
    """Write per-node override; optionally update dataset-level convention.

    db is the prisma client when running in production, or the test fake which
    exposes .conventions and .overrides dicts.
    """
    column = answer["column"]
    table_fqn = request.payload["table_fqn"]

    # Per-node override.
    overrides = db.overrides.setdefault((request.pipelineStackId, table_fqn), {})
    overrides.setdefault("clarifications", {})["volume_timestamp_column"] = column

    # If the FQN is "<dataset>.<table>", record a dataset preference too.
    if "." in table_fqn:
        dataset = table_fqn.rsplit(".", 1)[0]
        conv = db.conventions.setdefault(request.pipelineStackId, {})
        pref = conv.setdefault("volume_timestamp_preference", {
            "ordered": [], "scope": dataset
        })
        if column not in pref["ordered"]:
            pref["ordered"].insert(0, column)
        pref["scope"] = dataset
```

- [ ] **Step 6: Implement prompt**

`scanner/copilot/clarifications/kinds/timestamp_choice/prompt.md`:

```markdown
You are clarifying which timestamp column Pallisade should use to bucket volume monitoring on `{table_fqn}`.

Heuristic candidates: {candidates}
Heuristic confidence: {confidence}

Speak directly to the user. Phrase one focused question. If the user is uncertain, briefly explain how the column will be used: "this is the column I'll use to count rows per day so volume drops/spikes get caught."

When the user answers, call `record_clarification_answer` with:
- `request_id`: {request_id}
- `structured_answer`: {{"column": "<the column they chose>"}}
- `propose_convention`: true if the chosen name fits a clear pattern (e.g., raw.* tables) and could apply to similar tables; false otherwise.

If the user names a column not in the candidate list, accept it — they know their schema.
```

- [ ] **Step 7: Implement registration in `__init__.py`**

`scanner/copilot/clarifications/kinds/timestamp_choice/__init__.py`:

```python
"""timestamp_choice clarification kind."""
from pathlib import Path
from copilot.clarifications.registry import register_kind, KindHandler
from copilot.clarifications.kinds.timestamp_choice.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.timestamp_choice.parser import parse_reply
from copilot.clarifications.kinds.timestamp_choice.conventions import on_resolve

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def _load_prompt(payload):
    template = _PROMPT_PATH.read_text()
    return template.format(
        table_fqn=payload.get("table_fqn", "<unknown>"),
        candidates=", ".join(payload.get("candidates", [])) or "(none)",
        confidence=payload.get("confidence", "unknown"),
        request_id=payload.get("__request_id", "<unknown>"),
    )


register_kind(KindHandler(
    kind="timestamp_choice",
    validate_payload=validate_payload,
    validate_answer=validate_answer,
    load_prompt=_load_prompt,
    on_resolve=on_resolve,
))


__all__ = ["parse_reply"]
```

- [ ] **Step 8: Run tests**

```bash
pytest scanner/copilot/clarifications/tests/test_timestamp_choice.py scanner/copilot/clarifications/tests/test_engine.py -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add scanner/copilot/clarifications/
git commit -m "feat(clarifications): timestamp_choice kind (schemas, parser, prompt, conventions)"
```

---

## Task 7: Production Prisma adapter for the engine

The engine in Task 5 used a fake DB. We need the production path.

**Files:**
- Modify: `scanner/copilot/clarifications/engine.py`

- [ ] **Step 1: Add production DB methods**

Replace the `_create_request` and `_save_resolution` and `_read_conventions` methods with versions that detect a Prisma-like client:

```python
    def _create_request(self, **kwargs):
        if hasattr(self.db, "contextrequest"):
            # Prisma async client path
            import asyncio
            return asyncio.get_event_loop().run_until_complete(
                self.db.contextrequest.create(data={
                    "pipelineStackId": kwargs["pipeline_stack_id"],
                    "kind": kwargs["kind"],
                    "scopeType": kwargs["scope_type"],
                    "scopeRef": kwargs["scope_ref"],
                    "payload": kwargs["payload"],
                    "priority": kwargs["priority"],
                    "status": "open",
                })
            )
        # Fake DB path (tests)
        from copilot.clarifications.tests.test_engine import _FakeRequest
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

    def _save_resolution(self, resolution) -> None:
        if hasattr(self.db, "contextresolution"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                self.db.contextresolution.create(data={
                    "requestId": resolution.requestId,
                    "answer": resolution.answer,
                    "transcript": resolution.transcript,
                    "conventionUpdate": resolution.conventionUpdate,
                    "answeredBy": resolution.answeredBy,
                })
            )
            return
        self.db.resolutions.append(resolution)

    def _read_conventions(self, ps_id: str) -> Dict[str, Any]:
        if hasattr(self.db, "pipelinecontext"):
            import asyncio
            ctx = asyncio.get_event_loop().run_until_complete(
                self.db.pipelinecontext.find_unique(
                    where={"pipelineStackId": ps_id}
                )
            )
            return (ctx.conventionsContext if ctx else {}) or {}
        return self.db.conventions.get(ps_id, {})
```

- [ ] **Step 2: Run unit tests to verify the fake-DB path still passes**

```bash
pytest scanner/copilot/clarifications/tests/ -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add scanner/copilot/clarifications/engine.py
git commit -m "feat(clarifications): add Prisma client path to engine"
```

---

## Task 8: Wire `_pick_volume_timestamp_column` into the engine

**Files:**
- Modify: `scanner/lineage/sla_discovery.py` (lines 582–641, 820, 841–853)

- [ ] **Step 1: Read the current implementation to confirm signatures**

Run:
```bash
sed -n '580,650p' scanner/lineage/sla_discovery.py
sed -n '815,860p' scanner/lineage/sla_discovery.py
```

Note the exact signatures of `_pick_volume_timestamp_column` and `_compute_volume`.

- [ ] **Step 2: Modify `_pick_volume_timestamp_column` to return uncertainty info**

Change the return type from `Optional[str]` to a dataclass exposing the picked column AND the candidate set:

In `scanner/lineage/sla_discovery.py`, near the top of the file (with other imports/dataclasses):

```python
@dataclass
class TimestampPick:
    column: Optional[str]
    candidates: List[str]
    confidence: float  # 0.0 if no candidates, 0.6 if one weak match, 0.9 if strong preference match
```

Replace the existing `_pick_volume_timestamp_column` function body (lines 582–641) so it returns a `TimestampPick`. Keep the existing heuristic; add `confidence` based on which preference tier matched (`loaded_at`/`ingested_at` → 0.9; `updated_at`/`modified_at` → 0.7; anything else → 0.5; none → 0.0).

(Engineer: implement the dataclass mapping with the existing preference list `_VOLUME_TS_PREFERENCES`. Pull all timestamp-typed columns into `candidates`. Pick by walking the preference list in order.)

- [ ] **Step 3: Update `_compute_volume` to honor lookup + emit on uncertainty**

In `_compute_volume` (line ~820), modify the call site (line 841) and what happens immediately after:

```python
# Existing line:
# ts_col = _pick_volume_timestamp_column(adapter, table_fqn)

# Replace with:
pick = _pick_volume_timestamp_column(adapter, table_fqn)

# Honour any prior user answer for this scope.
from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.config import CONFIG
engine = ClarificationEngine(db=_get_prisma_client())
ps_id = _get_pipeline_stack_id_from_context()  # existing helper or threaded arg
override = _read_node_override(ps_id, table_fqn, "volume_timestamp_column")
if override:
    ts_col = override
    tentative = False
    context_request_id = None
elif pick.column and pick.confidence >= CONFIG.confidence_threshold:
    ts_col = pick.column
    tentative = False
    context_request_id = None
else:
    ts_col = pick.column  # may be None — discovery returns disabled in that case
    req = engine.emit(
        pipeline_stack_id=ps_id,
        kind="timestamp_choice",
        scope_type="node",
        scope_ref=table_fqn,
        payload={
            "table_fqn": table_fqn,
            "candidates": pick.candidates,
            "confidence": pick.confidence,
            "evidence": {},
        },
        priority="normal",
    )
    tentative = True
    context_request_id = req.id if req else None
```

Then thread `tentative` and `context_request_id` into the dict returned by `_compute_volume`:

```python
result = {...existing fields..., "tentative": tentative}
if context_request_id:
    result["context_request_id"] = context_request_id
return result
```

- [ ] **Step 4: Add helper `_read_node_override`**

Near the bottom of `sla_discovery.py` (or in a helpers module if one exists):

```python
def _read_node_override(
    pipeline_stack_id: str, node_fqn: str, key: str
) -> Optional[str]:
    """Look up a per-node clarification override.

    Returns the answer if a PolicyAssignment.overrides.clarifications[key] exists
    for this node and pipeline; otherwise None.
    """
    db = _get_prisma_client()
    if db is None:
        return None
    import asyncio
    pa = asyncio.get_event_loop().run_until_complete(
        db.policyassignment.find_first(where={
            "pipelineStackId": pipeline_stack_id,
            "nodeFqn": node_fqn,
        })
    )
    if not pa or not pa.overrides:
        return None
    return (pa.overrides or {}).get("clarifications", {}).get(key)
```

If `_get_prisma_client` and `_get_pipeline_stack_id_from_context` don't already exist, search the file for how the existing code accesses these — `sla_discovery.py` runs in a request scope, so the pipeline ID is usually a function arg or threaded via a context object. Pass it through if needed by adjusting the public callers (`discover_sla_profile` etc.).

- [ ] **Step 5: Subscribe to `context_resolved` to re-run discovery**

In a new module `scanner/lineage/sla_discovery_listeners.py`:

```python
"""On context_resolved, re-run any tentative SLA discovery affected."""
from copilot.clarifications.events import BUS


def _on_resolved(payload):
    # Lazy import avoids circulars during app boot.
    from scanner.lineage.sla_discovery import discover_sla_profile_for_node

    if payload.get("kind") != "timestamp_choice":
        return
    if payload.get("scope_type") != "node":
        return
    discover_sla_profile_for_node(payload["scope_ref"])  # pipeline-aware impl


def register():
    BUS.subscribe("context_resolved", _on_resolved)
```

Call `register()` in `scanner/api/main.py` after the FastAPI app is constructed (search for existing app setup). If `discover_sla_profile_for_node` doesn't exist, alias it to the closest existing single-node entry point in `sla_discovery.py`.

- [ ] **Step 6: Add a unit test that an emit happens when confidence is low**

`scanner/copilot/clarifications/tests/test_engine.py` already covers emit. Add an integration test next: `scanner/tests/test_clarification_flow_a.py` (Task 14).

- [ ] **Step 7: Run existing SLA discovery tests to verify no regression**

```bash
pytest scanner/tests/test_sla_discovery.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/lineage/sla_discovery_listeners.py
git commit -m "feat(clarifications): wire sla_discovery into ClarificationEngine"
```

---

## Task 9: Add `clarify` mode to copilot

**Files:**
- Modify: `scanner/copilot/modes.py`
- Modify: `scanner/copilot/llm.py`

- [ ] **Step 1: Add `CLARIFY` to `InteractionMode` enum**

In `scanner/copilot/modes.py:14–24`:

```python
class InteractionMode(Enum):
    ASK = "ask"
    DEBUG = "debug"
    PLAN = "plan"
    CREATE = "create"
    BUNDLE = "bundle"
    EXPLAIN = "explain"
    SUGGEST = "suggest"
    FIX = "fix"
    ONBOARD = "onboard"
    CLARIFY = "clarify"   # new
```

- [ ] **Step 2: Add CLARIFY_PROMPT constant**

After the `ONBOARD_PROMPT` definition:

```python
CLARIFY_PROMPT = """
## CLARIFY MODE ACTIVE

You are helping the user resolve a single platform-detected ambiguity. The
ContextRequest payload (kind, scope, candidates, evidence) is loaded into
your system context.

**Behaviour:**
- Phrase ONE focused question in plain language. Keep it short.
- Briefly explain how the answer will be used (e.g., "this is the column I'll
  use to bucket volume" / "this dampens future alerts on this node").
- Wait for the user's reply.
- When the user answers, call `record_clarification_answer` with:
    - `request_id`: from the loaded payload
    - `structured_answer`: matching the kind's answer schema
    - `propose_convention`: true ONLY when the answer cleanly generalises (e.g.,
      a naming pattern that applies to many tables); otherwise false.
- If the user is uncertain, offer 1–2 sentences of concrete reasoning, not a
  list of options. Do not hedge.
- If the user contradicts an existing convention, surface it: "you previously
  preferred X for raw.* — confirm overriding to Y for raw.orders only?"

**Hard rules:**
- Do NOT ask multiple questions in one turn.
- Do NOT speculate about answers — wait for the user.
- Do NOT call any tool except `record_clarification_answer`, `get_node_metadata`,
  `get_recent_rows_sample`, or `lookup_convention`.
"""
```

- [ ] **Step 3: Register CLARIFY in `MODES`**

In the `MODES` dict (around line 414), after the `ONBOARD` entry:

```python
    InteractionMode.CLARIFY: ModeConfig(
        mode=InteractionMode.CLARIFY,
        display_name="Clarify",
        description="Resolve a platform-detected ambiguity",
        icon="help-circle",
        color="amber",
        system_prompt_section=CLARIFY_PROMPT,
        preferred_tools=[
            "record_clarification_answer",
        ],
        exclusive_tools=[
            "record_clarification_answer",
        ],
        auto_detect_patterns=[],  # never auto-detected; always entered explicitly
    ),
```

- [ ] **Step 4: Register `/clarify` slash command**

In `parse_slash_command` (around line 698), add to `slash_commands`:

```python
        "/clarify": InteractionMode.CLARIFY,
```

- [ ] **Step 5: Run modes tests if any exist**

```bash
pytest scanner/copilot/ -k "mode" -v 2>/dev/null || echo "no mode tests; manual verification needed"
```

Then verify manually by importing:
```bash
python -c "from copilot.modes import MODES, InteractionMode; print(MODES[InteractionMode.CLARIFY].display_name)"
```

Expected: `Clarify`.

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/modes.py
git commit -m "feat(clarifications): add CLARIFY interaction mode"
```

---

## Task 10: `record_clarification_answer` tool

**Files:**
- Create: `scanner/copilot/tools/clarifications.py`
- Modify: `scanner/copilot/tool_executor.py` (add `_execute_record_clarification_answer`)

- [ ] **Step 1: Create the tool definition**

`scanner/copilot/tools/clarifications.py`:

```python
"""Clarification-related tools."""
from copilot.tools.registry import register_tool


register_tool(
    name="record_clarification_answer",
    description=(
        "Record a structured answer to a clarification ContextRequest. "
        "Validates against the kind's answer_schema and writes a "
        "ContextResolution + (optionally) updates conventions."
    ),
    category="clarifications",
    parameters=[
        {
            "name": "request_id",
            "type": "string",
            "required": True,
            "description": "ContextRequest.id from the loaded payload.",
        },
        {
            "name": "structured_answer",
            "type": "object",
            "required": True,
            "description": (
                "Object matching the kind's answer_schema, e.g. "
                "{'column': 'loaded_at'} for kind=timestamp_choice."
            ),
        },
        {
            "name": "propose_convention",
            "type": "boolean",
            "required": False,
            "description": (
                "If true, the engine will also write a generalising convention "
                "to PipelineContext.conventionsContext."
            ),
        },
    ],
    required_integrations=[],
)
```

- [ ] **Step 2: Add executor**

In `scanner/copilot/tool_executor.py`, near other `_execute_*` methods, add:

```python
    async def _execute_record_clarification_answer(self, params: dict) -> dict:
        from copilot.clarifications.engine import ClarificationEngine
        from copilot.clarifications.registry import get_kind_handler

        request_id = params["request_id"]
        answer = params["structured_answer"]

        db = self._prisma  # existing attribute on ToolExecutor
        req = await db.contextrequest.find_unique(where={"id": request_id})
        if not req:
            return {"error": f"ContextRequest {request_id} not found"}
        if req.status != "open":
            return {"error": f"Request already {req.status}"}

        engine = ClarificationEngine(db=db)
        try:
            engine.resolve(
                request=req,
                answer=answer,
                transcript=self._current_transcript(),  # existing helper
                answered_by=self._user_id,              # existing attribute
            )
        except ValueError as exc:
            return {"error": f"Invalid answer: {exc}"}

        return {
            "ok": True,
            "request_id": request_id,
            "kind": req.kind,
            "applied_to": {"scope_type": req.scopeType, "scope_ref": req.scopeRef},
        }
```

If `self._prisma`, `self._current_transcript`, or `self._user_id` don't exist by these exact names, search `tool_executor.py` for the existing equivalents (DB client, message history, current user) and use those.

- [ ] **Step 3: Ensure tools package imports the new module**

In `scanner/copilot/tools/__init__.py`, add:

```python
from . import clarifications  # noqa: F401
```

- [ ] **Step 4: Verify the tool registers**

```bash
python -c "from copilot.tools import registry, clarifications; print('record_clarification_answer' in registry._GLOBAL_REGISTRY)"
```

Expected: `True`.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tools/ scanner/copilot/tool_executor.py
git commit -m "feat(clarifications): record_clarification_answer tool"
```

---

## Task 11: Load ContextRequest into copilot context for `clarify` mode

**Files:**
- Modify: `scanner/copilot/context_builder.py`

- [ ] **Step 1: Add a `clarification_request` field to `CopilotContext`**

In `scanner/copilot/context_builder.py:204–275`:

```python
@dataclass
class CopilotContext:
    # ... existing fields ...
    clarification_request: Optional[Dict[str, Any]] = None  # populated when mode=clarify
```

- [ ] **Step 2: Modify `build_context` to load the ContextRequest**

In `build_context` (around line 750), before returning:

```python
    if mode == "clarify":
        request_id = (mode_config.metadata or {}).get("clarification_request_id") if hasattr(mode_config, "metadata") else None
        if not request_id:
            # Caller forgot to pass it. Stay silent — chat will tell the user there's no active request.
            ctx.clarification_request = None
        else:
            req = await self._prisma.contextrequest.find_unique(where={"id": request_id})
            if req:
                ctx.clarification_request = {
                    "id": req.id,
                    "kind": req.kind,
                    "scope_type": req.scopeType,
                    "scope_ref": req.scopeRef,
                    "payload": {**(req.payload or {}), "__request_id": req.id},
                    "priority": req.priority,
                }
```

- [ ] **Step 3: Inject the prompt fragment into the system prompt**

In whichever method assembles the final system prompt (search for the `mode_config.system_prompt_section` consumer), append a per-request fragment when `ctx.clarification_request` is set:

```python
    if ctx.clarification_request:
        from copilot.clarifications.registry import get_kind_handler
        handler = get_kind_handler(ctx.clarification_request["kind"])
        prompt_fragment = handler.load_prompt(ctx.clarification_request["payload"])
        system_prompt += "\n\n---\n\n" + prompt_fragment
```

- [ ] **Step 4: Commit**

```bash
git add scanner/copilot/context_builder.py
git commit -m "feat(clarifications): inject ContextRequest payload into clarify-mode prompt"
```

---

## Task 12: FastAPI router `/api/v1/context-requests`

**Files:**
- Create: `scanner/api/routers/context_requests.py`
- Modify: `scanner/api/main.py` (register router + listener registration)

- [ ] **Step 1: Implement the router**

`scanner/api/routers/context_requests.py`:

```python
"""HTTP API for ContextRequest lifecycle."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_principal, get_prisma  # adjust to existing module
from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.config import CONFIG


router = APIRouter(prefix="/context-requests", tags=["clarifications"])


class AnswerBody(BaseModel):
    answer: dict
    transcript: Optional[list] = None


@router.get("")
async def list_requests(
    pipeline_stack_id: str,
    status: str = "open",
    limit: int = CONFIG.list_page_size,
    principal=Depends(require_principal),
    db=Depends(get_prisma),
):
    rows = await db.contextrequest.find_many(
        where={"pipelineStackId": pipeline_stack_id, "status": status},
        order_by=[{"priority": "asc"}, {"createdAt": "desc"}],
        take=limit,
    )
    return {"items": [_serialize(r) for r in rows]}


@router.get("/{request_id}")
async def get_request(
    request_id: str,
    principal=Depends(require_principal),
    db=Depends(get_prisma),
):
    req = await db.contextrequest.find_unique(where={"id": request_id})
    if not req:
        raise HTTPException(404, "Not found")
    return _serialize(req)


@router.post("/{request_id}/answer")
async def answer(
    request_id: str,
    body: AnswerBody,
    principal=Depends(require_principal),
    db=Depends(get_prisma),
):
    req = await db.contextrequest.find_unique(where={"id": request_id})
    if not req:
        raise HTTPException(404, "Not found")
    if req.status != "open":
        raise HTTPException(409, f"Already {req.status}")
    engine = ClarificationEngine(db=db)
    try:
        engine.resolve(
            request=req,
            answer=body.answer,
            transcript=body.transcript or [],
            answered_by=principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.post("/{request_id}/dismiss")
async def dismiss(
    request_id: str,
    principal=Depends(require_principal),
    db=Depends(get_prisma),
):
    req = await db.contextrequest.find_unique(where={"id": request_id})
    if not req:
        raise HTTPException(404, "Not found")
    engine = ClarificationEngine(db=db)
    engine.dismiss(request=req)
    return {"ok": True, "dismissed_until": req.dismissedUntil.isoformat()}


def _serialize(r) -> dict:
    return {
        "id": r.id,
        "kind": r.kind,
        "scope_type": r.scopeType,
        "scope_ref": r.scopeRef,
        "payload": r.payload,
        "status": r.status,
        "priority": r.priority,
        "created_at": r.createdAt.isoformat(),
        "dismissed_until": r.dismissedUntil.isoformat() if r.dismissedUntil else None,
    }
```

If `api.deps` exposes different names for the auth/db dependencies, adjust to match the names already used in `scanner/api/routers/copilot.py`.

- [ ] **Step 2: Register the router**

In `scanner/api/main.py`, add to the existing `app.include_router(...)` block:

```python
from api.routers.context_requests import router as context_requests_router
app.include_router(context_requests_router, prefix="/api/v1")
```

Also add (near the other startup hooks):

```python
from scanner.lineage.sla_discovery_listeners import register as _register_clarif_listeners
_register_clarif_listeners()
```

- [ ] **Step 3: Smoke test**

```bash
uvicorn scanner.api.main:app --port 8001 &
sleep 2
curl -s "http://localhost:8001/api/v1/context-requests?pipeline_stack_id=nonexistent" | head -c 200
kill %1
```

Expected: empty list response (200) — auth may require a header; that's OK as long as the route is registered.

- [ ] **Step 4: Commit**

```bash
git add scanner/api/
git commit -m "feat(clarifications): /api/v1/context-requests router + listener wiring"
```

---

## Task 13: Frontend API proxy

**Files:**
- Create: `lib/clarifications/types.ts`
- Create: `lib/clarifications/client.ts`
- Create: `app/api/context-requests/route.ts`
- Create: `app/api/context-requests/[id]/answer/route.ts`
- Create: `app/api/context-requests/[id]/dismiss/route.ts`

- [ ] **Step 1: Types**

`lib/clarifications/types.ts`:

```ts
export type ContextRequestStatus = 'open' | 'answered' | 'dismissed' | 'superseded' | 'expired';
export type ContextRequestPriority = 'critical' | 'high' | 'normal' | 'low';

export interface ContextRequest {
  id: string;
  kind: string;
  scope_type: 'node' | 'dataset' | 'integration' | 'pipeline';
  scope_ref: string;
  payload: Record<string, unknown>;
  status: ContextRequestStatus;
  priority: ContextRequestPriority;
  created_at: string;
  dismissed_until: string | null;
}

export interface AnswerBody {
  answer: Record<string, unknown>;
  transcript?: Array<{ role: string; content: string }>;
}
```

- [ ] **Step 2: Client**

`lib/clarifications/client.ts`:

```ts
import type { ContextRequest, AnswerBody } from './types';

export async function listContextRequests(pipelineId: string): Promise<ContextRequest[]> {
  const res = await fetch(`/api/context-requests?pipeline_stack_id=${encodeURIComponent(pipelineId)}`);
  if (!res.ok) throw new Error(`list failed: ${res.status}`);
  const json = await res.json();
  return json.items;
}

export async function answerContextRequest(id: string, body: AnswerBody): Promise<void> {
  const res = await fetch(`/api/context-requests/${id}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`answer failed: ${res.status}`);
}

export async function dismissContextRequest(id: string): Promise<void> {
  const res = await fetch(`/api/context-requests/${id}/dismiss`, { method: 'POST' });
  if (!res.ok) throw new Error(`dismiss failed: ${res.status}`);
}
```

- [ ] **Step 3: List proxy**

`app/api/context-requests/route.ts`:

```ts
import { auth } from '@/auth';
import { NextResponse } from 'next/server';

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL || 'http://localhost:8000';

export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  const url = new URL(request.url);
  const ps = url.searchParams.get('pipeline_stack_id');
  if (!ps) return NextResponse.json({ error: 'pipeline_stack_id required' }, { status: 400 });
  const upstream = `${FASTAPI_BASE}/api/v1/context-requests?pipeline_stack_id=${encodeURIComponent(ps)}`;
  const res = await fetch(upstream, {
    headers: { 'X-User-Id': session.user.id ?? '', 'X-User-Email': session.user.email ?? '' },
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

- [ ] **Step 4: Answer proxy**

`app/api/context-requests/[id]/answer/route.ts`:

```ts
import { auth } from '@/auth';
import { NextResponse } from 'next/server';

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL || 'http://localhost:8000';

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  const { id } = await params;
  const body = await request.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/context-requests/${id}/answer`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': session.user.id ?? '',
      'X-User-Email': session.user.email ?? '',
    },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

- [ ] **Step 5: Dismiss proxy**

`app/api/context-requests/[id]/dismiss/route.ts`:

```ts
import { auth } from '@/auth';
import { NextResponse } from 'next/server';

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL || 'http://localhost:8000';

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  const { id } = await params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/context-requests/${id}/dismiss`, {
    method: 'POST',
    headers: { 'X-User-Id': session.user.id ?? '', 'X-User-Email': session.user.email ?? '' },
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

- [ ] **Step 6: Commit**

```bash
git add app/api/context-requests/ lib/clarifications/
git commit -m "feat(clarifications/ui): API proxy + typed client"
```

---

## Task 14: Frontend — `LLMBell` and `ClarificationProvider`

**Files:**
- Create: `components/clarifications/ClarificationProvider.tsx`
- Create: `components/clarifications/LLMBell.tsx`

- [ ] **Step 1: Provider with polling**

`components/clarifications/ClarificationProvider.tsx`:

```tsx
'use client';
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';
import { listContextRequests } from '@/lib/clarifications/client';
import type { ContextRequest } from '@/lib/clarifications/types';

interface Ctx {
  requests: ContextRequest[];
  refresh: () => Promise<void>;
  popupOpen: boolean;
  openPopup: (focusId?: string) => void;
  closePopup: () => void;
  focusedId: string | null;
}

const ClarificationCtx = createContext<Ctx | null>(null);

export function ClarificationProvider({ children }: { children: React.ReactNode }) {
  const { selectedPipelineId } = usePipeline();
  const [requests, setRequests] = useState<ContextRequest[]>([]);
  const [popupOpen, setPopupOpen] = useState(false);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const refresh = async () => {
    if (!selectedPipelineId) { setRequests([]); return; }
    try {
      const items = await listContextRequests(selectedPipelineId);
      setRequests(items);
    } catch { /* swallow polling errors */ }
  };

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, 15_000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPipelineId]);

  const value = useMemo<Ctx>(() => ({
    requests,
    refresh,
    popupOpen,
    openPopup: (focusId?: string) => {
      if (focusId) setFocusedId(focusId);
      else if (!focusedId && requests.length) setFocusedId(requests[0].id);
      setPopupOpen(true);
    },
    closePopup: () => setPopupOpen(false),
    focusedId,
  }), [requests, popupOpen, focusedId]);

  return <ClarificationCtx.Provider value={value}>{children}</ClarificationCtx.Provider>;
}

export function useClarifications() {
  const ctx = useContext(ClarificationCtx);
  if (!ctx) throw new Error('useClarifications must be used inside ClarificationProvider');
  return ctx;
}
```

- [ ] **Step 2: LLMBell**

`components/clarifications/LLMBell.tsx`:

```tsx
'use client';
import { Lightbulb } from 'lucide-react';
import { useClarifications } from './ClarificationProvider';

export function LLMBell() {
  const { requests, openPopup } = useClarifications();
  const open = requests.filter((r) => r.status === 'open');
  const count = open.length;
  const critical = open.some((r) => r.priority === 'critical');

  return (
    <button
      type="button"
      onClick={() => openPopup()}
      className="relative p-2 rounded-md hover:bg-muted"
      aria-label={`${count} pending clarifications`}
    >
      <Lightbulb className={`h-5 w-5 ${count ? 'text-amber-500' : 'text-muted-foreground'}`} />
      {count > 0 && (
        <span
          className={`absolute -top-1 -right-1 text-[10px] font-medium rounded-full px-1 min-w-[16px] text-center
            ${critical ? 'bg-red-500 text-white animate-pulse' : 'bg-amber-500 text-white'}`}
        >
          {count > 9 ? '9+' : count}
        </span>
      )}
    </button>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add components/clarifications/
git commit -m "feat(clarifications/ui): LLMBell + provider with 15s polling"
```

---

## Task 15: Frontend — `ClarificationPopup`

**Files:**
- Create: `components/clarifications/ClarificationPopup.tsx`

- [ ] **Step 1: Implement the popup chat panel**

`components/clarifications/ClarificationPopup.tsx`:

```tsx
'use client';
import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, X, Send } from 'lucide-react';
import { useClarifications } from './ClarificationProvider';

interface ChatMsg { role: 'user' | 'assistant'; content: string; }

export function ClarificationPopup() {
  const { popupOpen, closePopup, requests, focusedId, refresh } = useClarifications();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const open = requests.filter((r) => r.status === 'open');
  const focusIdx = focusedId ? open.findIndex((r) => r.id === focusedId) : 0;
  const focused = open[Math.max(0, focusIdx)] ?? null;

  useEffect(() => {
    if (!focused) { setMessages([]); return; }
    // Initial assistant message: prime with the kind's prompt rendered server-side via the chat endpoint.
    setMessages([{
      role: 'assistant',
      content: `I need a quick clarification about ${focused.scope_ref}. Loading…`,
    }]);
    // Kick off a clarify-mode chat that loads the request payload.
    fetch('/api/copilot/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: '',
        mode: 'clarify',
        clarification_request_id: focused.id,
      }),
    }).then((r) => r.json()).then((data) => {
      setMessages([{ role: 'assistant', content: data.reply ?? '...' }]);
    }).catch(() => {});
  }, [focused?.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  if (!popupOpen) return null;

  const send = async () => {
    if (!input.trim() || !focused || sending) return;
    const userMsg: ChatMsg = { role: 'user', content: input };
    setMessages((m) => [...m, userMsg]);
    setInput('');
    setSending(true);
    try {
      const res = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input,
          mode: 'clarify',
          clarification_request_id: focused.id,
          history: [...messages, userMsg],
        }),
      });
      const data = await res.json();
      setMessages((m) => [...m, { role: 'assistant', content: data.reply ?? '(no response)' }]);
      if (data.resolved) {
        await refresh();
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <aside className="fixed top-0 right-0 h-full w-[420px] bg-background border-l shadow-lg z-50 flex flex-col">
      <header className="flex items-center justify-between px-4 py-3 border-b">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Clarification</div>
          <div className="text-sm font-medium truncate max-w-[280px]">
            {focused ? `${focused.kind} · ${focused.scope_ref}` : 'No pending requests'}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button className="p-1 rounded hover:bg-muted" disabled={focusIdx <= 0}><ChevronLeft className="h-4 w-4" /></button>
          <button className="p-1 rounded hover:bg-muted" disabled={focusIdx >= open.length - 1}><ChevronRight className="h-4 w-4" /></button>
          <button className="p-1 rounded hover:bg-muted" onClick={closePopup}><X className="h-4 w-4" /></button>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <div className={`inline-block px-3 py-2 rounded-lg text-sm max-w-[85%] ${
              m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}>{m.content}</div>
          </div>
        ))}
        {sending && <div className="text-xs text-muted-foreground">thinking…</div>}
      </div>

      <footer className="border-t p-3">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Type your answer…"
            className="flex-1 px-3 py-2 border rounded-md text-sm"
            disabled={!focused || sending}
          />
          <button
            type="button"
            onClick={send}
            disabled={!focused || sending || !input.trim()}
            className="px-3 py-2 rounded-md bg-primary text-primary-foreground disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </footer>
    </aside>
  );
}
```

- [ ] **Step 2: Verify the existing `/api/copilot/chat` accepts `mode` and `clarification_request_id`**

Check `app/api/copilot/chat/route.ts`. It already accepts `mode`. Add `clarification_request_id` pass-through if it isn't there:

In that file, when forwarding to FastAPI, ensure the body includes `clarification_request_id` if present in the incoming JSON. If it doesn't, edit it to thread the field through verbatim.

- [ ] **Step 3: Commit**

```bash
git add components/clarifications/ClarificationPopup.tsx app/api/copilot/chat/route.ts
git commit -m "feat(clarifications/ui): popup chat panel + clarify mode plumbing"
```

---

## Task 16: Mount the provider, bell, and popup in the dashboard layout

**Files:**
- Modify: `app/layout.tsx` (or `app/(dashboard)/layout.tsx` — wherever `PipelineProvider` lives)

- [ ] **Step 1: Wrap the app**

In whichever layout currently wraps children with `PipelineProvider`, add `ClarificationProvider` as a nested child:

```tsx
import { ClarificationProvider } from '@/components/clarifications/ClarificationProvider';
import { ClarificationPopup } from '@/components/clarifications/ClarificationPopup';

// inside the JSX:
<PipelineProvider>
  <ClarificationProvider>
    {children}
    <ClarificationPopup />
  </ClarificationProvider>
</PipelineProvider>
```

- [ ] **Step 2: Add LLMBell next to the existing alerts bell**

Find the top-bar component that renders the alerts bell (likely in `app/(dashboard)/layout.tsx` or a `TopBar` component). Add `<LLMBell />` next to it:

```tsx
import { LLMBell } from '@/components/clarifications/LLMBell';

// in the top-bar JSX:
<NotificationBell />
<LLMBell />
```

- [ ] **Step 3: Smoke test the UI**

```bash
pnpm dev
# in another terminal:
curl -s http://localhost:3000/dashboard/lineage > /dev/null
```

Open `http://localhost:3000/dashboard/lineage` in the browser. Verify the lightbulb icon appears next to the bell.

- [ ] **Step 4: Commit**

```bash
git add app/
git commit -m "feat(clarifications/ui): mount provider + bell + popup"
```

---

## Task 17: SLAEditorPanel — render tentative tag

**Files:**
- Modify: `components/lineage/SLAEditorPanel.tsx`

- [ ] **Step 1: Read the current panel to find where volume fields render**

```bash
grep -n "volume\|timestamp" components/lineage/SLAEditorPanel.tsx | head -20
```

- [ ] **Step 2: When the discovery result has `tentative: true`, render a tag**

Near the volume section, where the "discovered" values render:

```tsx
{discovery.volume?.tentative && (
  <button
    type="button"
    onClick={() => openPopup(discovery.volume.context_request_id)}
    className="ml-2 inline-flex items-center gap-1 text-xs text-amber-600 underline-offset-2 underline decoration-dotted"
  >
    🔍 awaiting clarification
  </button>
)}
```

`openPopup` comes from `useClarifications()`. Import it at the top of the file.

- [ ] **Step 3: Apply dotted underline to the column-name display**

For the rendered timestamp column name, add `className="border-b border-dashed border-amber-400"` when `tentative`.

- [ ] **Step 4: Commit**

```bash
git add components/lineage/SLAEditorPanel.tsx
git commit -m "feat(clarifications/ui): tentative discovery tag in SLA editor"
```

---

## Task 18: End-to-end integration test for Flow A

**Files:**
- Create: `scanner/tests/test_clarification_flow_a.py`

- [ ] **Step 1: Write the test**

```python
"""Flow A: tentative discovery → ContextRequest emitted → user answers →
discovery re-runs → tentative tag drops."""
import pytest
from unittest.mock import patch, MagicMock

from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.events import BUS
from copilot.clarifications.kinds import timestamp_choice  # ensure registration


class _DB:
    def __init__(self):
        self.requests = []
        self.resolutions = []
        self.conventions = {}
        self.overrides = {}


def _patch_pipeline_id(stack_id="ps_test"):
    return patch(
        "scanner.lineage.sla_discovery._get_pipeline_stack_id_from_context",
        return_value=stack_id,
    )


def _patch_prisma(db):
    return patch(
        "scanner.lineage.sla_discovery._get_prisma_client",
        return_value=db,
    )


def test_flow_a_emit_resolve_rerun(monkeypatch):
    """Discovery on a node with ambiguous columns emits, user answers, re-runs."""
    db = _DB()
    re_runs = []

    # Subscribe to verify the listener fires the re-run.
    BUS.subscribe(
        "context_resolved",
        lambda payload: re_runs.append(payload["scope_ref"]),
    )

    # 1. First discovery: low confidence → tentative.
    fake_adapter = MagicMock()
    fake_adapter.list_columns.return_value = [
        {"name": "col_a", "type": "TIMESTAMP"},
        {"name": "col_b", "type": "TIMESTAMP"},
    ]

    with _patch_pipeline_id(), _patch_prisma(db):
        from scanner.lineage.sla_discovery import _compute_volume
        result = _compute_volume(fake_adapter, "raw.orders")
    assert result["tentative"] is True
    assert "context_request_id" in result
    assert len(db.requests) == 1
    req = db.requests[0]
    assert req.kind == "timestamp_choice"

    # 2. User answers via the engine.
    engine = ClarificationEngine(db=db)
    engine.resolve(
        request=req,
        answer={"column": "col_b"},
        transcript=[{"role": "user", "content": "use col_b"}],
        answered_by="user_test",
    )

    assert req.status == "answered"
    assert "raw.orders" in re_runs

    # 3. Second discovery: convention now applies → no popup.
    db.requests = []  # the engine wrote conventions; we'd reuse them
    # The override write put the answer into db.overrides.
    with _patch_pipeline_id(), _patch_prisma(db):
        from scanner.lineage.sla_discovery import _compute_volume
        result = _compute_volume(fake_adapter, "raw.orders")
    assert result["tentative"] is False
    assert len(db.requests) == 0
```

- [ ] **Step 2: Run**

```bash
pytest scanner/tests/test_clarification_flow_a.py -v
```

Expected: pass. If the test reveals that `_get_pipeline_stack_id_from_context` or `_get_prisma_client` need to be threaded as args (not module-level helpers), refactor in `sla_discovery.py` and add the patches accordingly — the test is the spec for the integration shape.

- [ ] **Step 3: Run the full clarifications + sla discovery suites to confirm no regressions**

```bash
pytest scanner/copilot/clarifications/ scanner/tests/test_sla_discovery.py scanner/tests/test_clarification_flow_a.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add scanner/tests/test_clarification_flow_a.py
git commit -m "test(clarifications): end-to-end Flow A integration test"
```

---

## Task 19: Manual smoke test + final verification

- [ ] **Step 1: Start backend + frontend**

```bash
# terminal 1
uvicorn scanner.api.main:app --reload --port 8000
# terminal 2
pnpm dev
```

- [ ] **Step 2: Reproduce the loop**

1. Open `http://localhost:3000/dashboard/lineage`.
2. Pick a node whose timestamp columns are ambiguous (or seed one in the dev DB).
3. Click "Discover from data".
4. Observe: result shows the dotted "🔍 awaiting clarification" tag; the LLMBell shows a `1` badge.
5. Click the LLMBell. Popup opens with the LLM's question.
6. Type a column name (e.g., `loaded_at`). LLM confirms and calls `record_clarification_answer`.
7. Tag clears; bell badge drops to 0.
8. Click "Discover from data" again — runs without popup.

- [ ] **Step 3: Run all tests**

```bash
pytest scanner/ -v
pnpm test --if-present
```

Expected: all pass.

- [ ] **Step 4: Final commit / nothing to commit**

If anything was changed during smoke test, commit it. Otherwise this task closes the plan.

---

## Plan-1 self-review

- **Spec coverage**: §4 architecture (Tasks 2–7, 9–12), §5 data model (Task 1), §6.1 Flow A (Tasks 8, 18), §7 UI bell + popup + tentative tag (Tasks 14–17), §8 LLM integration (Tasks 9–11), §9 error handling (covered in engine emit dedupe + dismiss decay + Task 12 409 handling). §6.2 sweep, §6.3 borderline, §6.4 ad-hoc, §6.5 completeness — out of scope for V1.0 (Plans 2–4).
- **Placeholder scan**: no TBDs/TODOs. Each step has actual code. Tasks 8 and 11 reference helpers like `_get_prisma_client` / `_get_pipeline_stack_id_from_context` that may need to be discovered or threaded; Task 8 step 4 spells out the search path explicitly so the executor knows what to do.
- **Type consistency**: `ContextRequest` shape, `KindHandler` fields, and `TimestampPick` dataclass match across tasks. `record_clarification_answer` parameter names match between tool definition (Task 10) and prompt template (Task 6). API endpoint paths match between FastAPI router (Task 12) and frontend client (Task 13).
