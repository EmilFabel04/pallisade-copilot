# Two-phase SLA Discovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split SLA discovery into an `analyze` phase that emits clarifications and a `compute` phase that runs after answers, so users never see SLA values computed against a guess they were never asked about.

**Architecture:** Two pure functions over a shared `AnalysisPlan` dataclass. `analyze_sla` picks timestamp candidates, emits `timestamp_choice` ContextRequests when picker confidence is below threshold, and returns a JSON-safe plan. `compute_sla` accepts the plan plus `{request_id: answer}` and runs all dimension SQL (volume, freshness, schema, quality, uniqueness). Frontend orchestrates the two phases — when analyze returns `status="ready"` it immediately fires compute; when it returns `awaiting_clarifications` it gates the SLA panel until `ClarificationProvider` reports all requests answered. No schema changes; the durable record is the existing `ContextRequest` table.

**Tech Stack:** FastAPI + Pydantic (scanner), Next.js 15 + Prisma (web), pytest (backend tests), Jest + React Testing Library (frontend tests).

**Spec reference:** `docs/superpowers/specs/2026-05-14-two-phase-sla-discovery-design.md`

---

## File Structure

**Created (backend):**
- `scanner/lineage/sla_analysis.py` — `AnalysisPlan`, `AnalyzeResult`, `analyze_sla`, `analyze_sla_profile`, `analyze_sla_bulk`. Keeps the analyze surface in its own module so `sla_discovery.py` doesn't grow further.
- `scanner/tests/test_sla_analysis.py`
- `scanner/tests/test_sla_compute.py`
- `scanner/tests/test_discovery_router_two_phase.py`

**Created (frontend):**
- `app/api/nodes/[nodeId]/sla/discover/analyze/route.ts`
- `app/api/nodes/[nodeId]/sla/discover/compute/route.ts`
- `app/api/nodes/sla/discover-bulk/analyze/route.ts`
- `app/api/nodes/sla/discover-bulk/compute/route.ts`
- `components/clarifications/useClarificationsResolved.ts`
- `components/clarifications/__tests__/useClarificationsResolved.test.tsx`
- `components/lineage/__tests__/DataAssetDetailPanel.discovery.test.tsx`

**Modified:**
- `scanner/lineage/sla_discovery.py` — `_compute_volume` becomes pure (no clarification emit); `discover_sla_direct`/`discover_sla_profile`/`discover_sla_profiles_bulk` become thin wrappers that call analyze + compute with empty answers; add `compute_sla`, `compute_sla_profile`, `compute_sla_bulk`.
- `scanner/api/routers/discovery.py` — add `/discovery/analyze`, `/discovery/compute`, `/discovery/analyze-bulk`, `/discovery/compute-bulk`.
- `app/api/nodes/[nodeId]/sla/discover/route.ts` — keep during rollout; mark deprecated and proxy to new analyze+compute path internally.
- `app/api/nodes/sla/discover-bulk/route.ts` — same.
- `components/clarifications/ClarificationProvider.tsx` — export the answered-requests map so `useClarificationsResolved` can subscribe.
- `components/lineage/DataAssetDetailPanel.tsx` — replace `handleDiscover` with `handleAnalyze` + `handleCompute`; extend state machine; add `awaiting_clarifications` view; remove `tentative` rendering.
- `scanner/tests/test_sla_discovery_clarification.py` — adapt the tentative-related tests to the new analyze-emits, compute-uses-answers model. Drop assertions about `_compute_volume` calling the emitter.

**Deleted:**
- `scanner/lineage/sla_discovery_listeners.py` — no-op listener; replaced by frontend-driven re-trigger.
- After rollout (separate deploy, not in this plan): the legacy wrapper functions and old HTTP endpoints.

---

### Task 1: Add `AnalysisPlan` + `AnalyzeResult` dataclasses with serializers

**Files:**
- Create: `scanner/lineage/sla_analysis.py`
- Test: `scanner/tests/test_sla_analysis.py`

- [ ] **Step 1: Write the failing test**

```python
# scanner/tests/test_sla_analysis.py
from __future__ import annotations

from scanner.lineage.sla_analysis import (
    AnalysisPlan,
    AnalyzeResult,
    plan_from_dict,
    plan_to_dict,
)


def _example_plan() -> AnalysisPlan:
    return AnalysisPlan(
        table_fqn="acme-484520.analytics.daily_revenue",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={
            "column": "date",
            "confidence": "weak",
            "score": 0.35,
            "rationale": "no canonical loaded_at column",
        },
        volume_timestamp_candidates=[
            {"column": "date", "data_type": "DATE", "score": 0.35},
            {"column": "created_at", "data_type": "TIMESTAMP", "score": 0.25},
        ],
        schema_snapshot={"columns": [{"name": "date", "data_type": "DATE"}]},
        row_count=59,
        unsupported=False,
        skipped_reason=None,
    )


def test_plan_roundtrips_through_dict():
    plan = _example_plan()
    restored = plan_from_dict(plan_to_dict(plan))
    assert restored == plan


def test_analyze_result_ready_has_no_clarifications():
    plan = _example_plan()
    result = AnalyzeResult(
        table_fqn=plan.table_fqn,
        plan=plan,
        status="ready",
        clarification_ids=[],
    )
    assert result.status == "ready"
    assert result.clarification_ids == []


def test_analyze_result_awaiting_has_clarifications():
    plan = _example_plan()
    result = AnalyzeResult(
        table_fqn=plan.table_fqn,
        plan=plan,
        status="awaiting_clarifications",
        clarification_ids=["cuid_abc"],
    )
    assert result.status == "awaiting_clarifications"
    assert result.clarification_ids == ["cuid_abc"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/tests/test_sla_analysis.py -v`
Expected: ImportError (module does not exist yet).

- [ ] **Step 3: Implement the dataclasses + serializers**

```python
# scanner/lineage/sla_analysis.py
"""Phase 1 of two-phase SLA discovery: analyze plan + clarifications.

Phase 2 (compute_sla) lives in sla_discovery.py and runs after the user has
answered any clarifications this phase emitted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass(frozen=True)
class AnalysisPlan:
    table_fqn: str
    warehouse_ancestor_fqn: Optional[str]
    volume_timestamp_pick: Optional[Dict[str, Any]]
    volume_timestamp_candidates: List[Dict[str, Any]]
    schema_snapshot: Dict[str, Any]
    row_count: Optional[int]
    unsupported: bool = False
    skipped_reason: Optional[str] = None


@dataclass(frozen=True)
class AnalyzeResult:
    table_fqn: str
    plan: AnalysisPlan
    status: Literal["ready", "awaiting_clarifications"]
    clarification_ids: List[str] = field(default_factory=list)


def plan_to_dict(plan: AnalysisPlan) -> Dict[str, Any]:
    return asdict(plan)


def plan_from_dict(data: Dict[str, Any]) -> AnalysisPlan:
    return AnalysisPlan(
        table_fqn=data["table_fqn"],
        warehouse_ancestor_fqn=data.get("warehouse_ancestor_fqn"),
        volume_timestamp_pick=data.get("volume_timestamp_pick"),
        volume_timestamp_candidates=list(data.get("volume_timestamp_candidates") or []),
        schema_snapshot=dict(data.get("schema_snapshot") or {}),
        row_count=data.get("row_count"),
        unsupported=bool(data.get("unsupported", False)),
        skipped_reason=data.get("skipped_reason"),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/tests/test_sla_analysis.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_analysis.py scanner/tests/test_sla_analysis.py
git commit -m "feat(scanner): add AnalysisPlan + AnalyzeResult dataclasses for two-phase SLA discovery"
```

---

### Task 2: Implement `analyze_sla` (single-table, no graph)

**Files:**
- Modify: `scanner/lineage/sla_analysis.py`
- Test: `scanner/tests/test_sla_analysis.py`

- [ ] **Step 1: Write the failing tests**

Append to `scanner/tests/test_sla_analysis.py`:

```python
from unittest.mock import MagicMock, patch

from scanner.lineage.sla_analysis import analyze_sla
from scanner.lineage.sla_discovery import TimestampPick


def _col(name: str, dtype: str = "TIMESTAMP") -> MagicMock:
    c = MagicMock()
    c.name = name
    c.data_type = dtype
    return c


def _adapter_with(columns):
    a = MagicMock()
    a.get_columns.return_value = columns
    a.get_row_count.return_value = 100
    return a


def test_analyze_returns_ready_when_pick_is_strong():
    adapter = _adapter_with([_col("loaded_at", "TIMESTAMP"), _col("id", "INT64")])
    with patch(
        "scanner.lineage.sla_analysis._call_nextjs_create_context_request"
    ) as mock_emit:
        result = analyze_sla(
            table_fqn="proj.ds.t",
            adapter=adapter,
            pipeline_stack_id="stack_1",
            organization_id="org_1",
        )
    assert result.status == "ready"
    assert result.clarification_ids == []
    assert mock_emit.call_count == 0
    assert result.plan.volume_timestamp_pick["column"] == "loaded_at"


def test_analyze_returns_awaiting_when_pick_is_weak():
    # Two ambiguous-named timestamp columns: picker has no strong signal.
    adapter = _adapter_with([_col("ts", "TIMESTAMP"), _col("event_time", "TIMESTAMP")])
    with patch(
        "scanner.lineage.sla_analysis._call_nextjs_create_context_request",
        return_value={"context_request_id": "ctx_123"},
    ) as mock_emit:
        result = analyze_sla(
            table_fqn="proj.ds.t",
            adapter=adapter,
            pipeline_stack_id="stack_1",
            organization_id="org_1",
        )
    assert result.status == "awaiting_clarifications"
    assert result.clarification_ids == ["ctx_123"]
    assert mock_emit.call_count == 1


def test_analyze_with_no_pipeline_scope_does_not_emit():
    adapter = _adapter_with([_col("ts", "TIMESTAMP"), _col("event_time", "TIMESTAMP")])
    with patch(
        "scanner.lineage.sla_analysis._call_nextjs_create_context_request"
    ) as mock_emit:
        result = analyze_sla(
            table_fqn="proj.ds.t",
            adapter=adapter,
            pipeline_stack_id=None,
            organization_id=None,
        )
    assert result.status == "ready"
    assert mock_emit.call_count == 0


def test_analyze_skips_when_no_columns():
    adapter = MagicMock()
    adapter.get_columns.return_value = []
    adapter.get_row_count.return_value = 0
    result = analyze_sla(
        table_fqn="proj.ds.t",
        adapter=adapter,
        pipeline_stack_id="stack_1",
        organization_id="org_1",
    )
    assert result.plan.unsupported is True
    assert result.plan.skipped_reason
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest scanner/tests/test_sla_analysis.py -v -k analyze`
Expected: ImportError on `analyze_sla`.

- [ ] **Step 3: Implement `analyze_sla`**

Append to `scanner/lineage/sla_analysis.py`:

```python
import logging

from scanner.lineage.sla_discovery import (
    CONFIG,
    TimestampPick,
    _pick_volume_timestamp_column,
    _call_nextjs_create_context_request,  # re-exported for test patching
)

logger = logging.getLogger(__name__)


def analyze_sla(
    table_fqn: str,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> AnalyzeResult:
    """Run phase 1: pick timestamp candidates, snapshot schema, emit clarifications.

    No warehouse-side aggregation runs here. Volume SQL, freshness probes,
    quality checks, and uniqueness checks all defer to ``compute_sla``.
    """
    columns = list(adapter.get_columns(table_fqn) or [])
    if not columns:
        plan = AnalysisPlan(
            table_fqn=table_fqn,
            warehouse_ancestor_fqn=None,
            volume_timestamp_pick=None,
            volume_timestamp_candidates=[],
            schema_snapshot={"columns": []},
            row_count=None,
            unsupported=True,
            skipped_reason="No columns visible to the adapter.",
        )
        return AnalyzeResult(table_fqn=table_fqn, plan=plan, status="ready", clarification_ids=[])

    pick: TimestampPick = _pick_volume_timestamp_column(adapter, table_fqn)
    row_count = _safe_row_count(adapter, table_fqn)

    schema_snapshot = {
        "columns": [
            {"name": c.name, "data_type": getattr(c, "data_type", None)} for c in columns
        ]
    }

    pick_dict = (
        {
            "column": pick.column,
            "confidence": pick.confidence,
            "score": pick.score,
            "rationale": pick.rationale,
        }
        if pick.column is not None
        else None
    )

    candidates = [
        {"column": cand.column, "data_type": cand.data_type, "score": cand.score}
        for cand in (pick.candidates or [])
    ]

    plan = AnalysisPlan(
        table_fqn=table_fqn,
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick=pick_dict,
        volume_timestamp_candidates=candidates,
        schema_snapshot=schema_snapshot,
        row_count=row_count,
        unsupported=False,
        skipped_reason=None,
    )

    clarification_ids: List[str] = []

    needs_clarification = (
        pipeline_stack_id is not None
        and pick.column is not None
        and pick.score is not None
        and pick.score < CONFIG.confidence_threshold
    )

    if needs_clarification:
        emitted = _call_nextjs_create_context_request(
            kind="timestamp_choice",
            scope_type="node",
            scope_ref=table_fqn,
            pipeline_stack_id=pipeline_stack_id,
            organization_id=organization_id,
            payload={
                "table_fqn": table_fqn,
                "candidates": candidates,
                "confidence": pick.confidence,
                "evidence": pick.rationale,
            },
        )
        if emitted and emitted.get("context_request_id"):
            clarification_ids.append(emitted["context_request_id"])

    status = "awaiting_clarifications" if clarification_ids else "ready"
    return AnalyzeResult(
        table_fqn=table_fqn,
        plan=plan,
        status=status,
        clarification_ids=clarification_ids,
    )


def _safe_row_count(adapter: Any, table_fqn: str) -> Optional[int]:
    try:
        rc = adapter.get_row_count(table_fqn)
        return int(rc) if rc is not None else None
    except Exception:
        logger.exception("get_row_count failed for %s", table_fqn)
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_sla_analysis.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_analysis.py scanner/tests/test_sla_analysis.py
git commit -m "feat(scanner): implement analyze_sla — phase 1 of two-phase discovery"
```

---

### Task 3: Make `_compute_volume` pure (no clarification side effects)

`_compute_volume` currently picks the timestamp column AND emits a clarification AND runs the daily-count query. After this task, it only does the SQL — caller passes the timestamp column in. This is the central refactor that makes phase 2 deterministic.

**Files:**
- Modify: `scanner/lineage/sla_discovery.py`
- Test: `scanner/tests/test_sla_discovery_clarification.py` (adapt existing tests)

- [ ] **Step 1: Update the failing tests** — adapt existing tests in `test_sla_discovery_clarification.py` so they no longer assert `_compute_volume` emits anything. Specifically, in each test that today calls `_compute_volume(...)` and asserts a `context_request_id` in the result, change it to call `_compute_volume(adapter, table_fqn, timestamp_column="...")` and assert no `tentative` / `context_request_id` keys are present.

```python
# Replace the existing test bodies in test_sla_discovery_clarification.py
def test_compute_volume_does_not_emit_clarification():
    adapter = _adapter_with([_col("ts", "TIMESTAMP")])
    adapter.execute_query.return_value = [
        {"day": "2026-05-13", "n": 100},
        {"day": "2026-05-12", "n": 105},
        {"day": "2026-05-11", "n": 98},
    ]
    with patch(
        "scanner.lineage.sla_discovery._call_nextjs_create_context_request"
    ) as mock_emit:
        result = _compute_volume(
            adapter,
            "proj.ds.t",
            metadata={"row_count": 1000},
            timestamp_column="ts",
        )
    assert mock_emit.call_count == 0
    assert "tentative" not in result
    assert "context_request_id" not in result


def test_compute_volume_uses_supplied_timestamp_column():
    adapter = _adapter_with([_col("ts", "TIMESTAMP"), _col("alt", "TIMESTAMP")])
    captured = {}

    def fake_query(sql):
        captured["sql"] = sql
        return [
            {"day": "2026-05-13", "n": 1},
            {"day": "2026-05-12", "n": 2},
            {"day": "2026-05-11", "n": 3},
        ]

    adapter.execute_query.side_effect = fake_query
    _compute_volume(adapter, "proj.ds.t", metadata=None, timestamp_column="alt")
    assert "alt" in captured["sql"]
```

Delete the old tests that asserted `_compute_volume` emits clarifications — those behaviors moved to `analyze_sla`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest scanner/tests/test_sla_discovery_clarification.py -v`
Expected: TypeError (no `timestamp_column` kwarg) or AttributeError.

- [ ] **Step 3: Refactor `_compute_volume`**

In `scanner/lineage/sla_discovery.py`:

1. Change the signature to `def _compute_volume(adapter, table_fqn, metadata=None, *, timestamp_column: Optional[str] = None, pipeline_stack_id=None, organization_id=None)`. Keep the trailing kwargs for now to avoid churn in callers we haven't touched yet.
2. Remove the `pick = _pick_volume_timestamp_column(...)` and `clarification = _try_emit_timestamp_clarification(...)` calls and the `_attach_clarification` helper.
3. If `timestamp_column is None`, fall back to `_pick_volume_timestamp_column(adapter, table_fqn).column` (for legacy callers). When `timestamp_column is None` AND no pick exists, return `{enabled: False, disabledReason: ...}` exactly as before, but without the tentative tag.
4. Otherwise use `timestamp_column` straight through into `_get_daily_row_counts`.

Show the new top of the function:

```python
def _compute_volume(
    adapter: Any,
    table_fqn: str,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    timestamp_column: Optional[str] = None,
    pipeline_stack_id: Optional[str] = None,  # kept for legacy signature compat; unused
    organization_id: Optional[str] = None,    # kept for legacy signature compat; unused
) -> Optional[Dict[str, Any]]:
    count = metadata.get("row_count") if metadata else None
    current_rows = int(count) if count is not None and count >= 0 else None

    ts_col = timestamp_column
    if ts_col is None:
        pick = _pick_volume_timestamp_column(adapter, table_fqn)
        ts_col = pick.column

    if ts_col is None:
        return {
            "enabled": False,
            "disabledReason": (
                "No timestamp/date column found — daily volume cannot be "
                "computed. Add a column like loaded_at, updated_at, or "
                "created_at, or disable volume monitoring for this table."
            ),
            **({"currentRows": current_rows} if current_rows is not None else {}),
        }
    # ... rest of function unchanged ...
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_sla_discovery_clarification.py scanner/tests/test_sla_discovery.py -v`
Expected: all pass.

- [ ] **Step 5: Verify `_try_emit_timestamp_clarification` is no longer called by `_compute_volume`**

```bash
grep -n "_try_emit_timestamp_clarification" /Users/emilfabel/pallisade-copilot/scanner/lineage/sla_discovery.py
```
Expected: only the function definition itself, no other references. Add a static test:

```python
# scanner/tests/test_sla_analysis.py — append
import scanner.lineage.sla_discovery as sd


def test_compute_volume_does_not_reference_emit():
    import inspect
    source = inspect.getsource(sd._compute_volume)
    assert "_try_emit_timestamp_clarification" not in source
```

Run: `pytest scanner/tests/test_sla_analysis.py::test_compute_volume_does_not_reference_emit -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/tests/test_sla_discovery_clarification.py scanner/tests/test_sla_analysis.py
git commit -m "refactor(scanner): make _compute_volume pure — no clarification side effects"
```

---

### Task 4: Implement `compute_sla` (single-table)

**Files:**
- Modify: `scanner/lineage/sla_discovery.py`
- Test: `scanner/tests/test_sla_compute.py`

- [ ] **Step 1: Write the failing tests**

```python
# scanner/tests/test_sla_compute.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scanner.lineage.sla_analysis import AnalysisPlan
from scanner.lineage.sla_discovery import compute_sla


def _plan(table_fqn: str, ts_col: str = "loaded_at") -> AnalysisPlan:
    return AnalysisPlan(
        table_fqn=table_fqn,
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={"column": ts_col, "confidence": "strong", "score": 0.9, "rationale": ""},
        volume_timestamp_candidates=[{"column": ts_col, "data_type": "TIMESTAMP", "score": 0.9}],
        schema_snapshot={"columns": [{"name": ts_col, "data_type": "TIMESTAMP"}]},
        row_count=100,
        unsupported=False,
        skipped_reason=None,
    )


def _adapter():
    a = MagicMock()
    a.get_columns.return_value = [MagicMock(name="loaded_at", data_type="TIMESTAMP")]
    a.execute_query.return_value = [
        {"day": "2026-05-13", "n": 100},
        {"day": "2026-05-12", "n": 105},
        {"day": "2026-05-11", "n": 98},
    ]
    a.get_row_count.return_value = 100
    return a


def test_compute_with_empty_answers_uses_plan_pick():
    plan = _plan("proj.ds.t", ts_col="loaded_at")
    result = compute_sla(plan, _adapter(), answers={})
    assert result.volume is not None
    assert result.volume.get("timeColumn") == "loaded_at"


def test_compute_with_answer_overrides_plan_pick():
    plan = _plan("proj.ds.t", ts_col="loaded_at")
    adapter = _adapter()
    answers = {"ctx_xyz": {"column": "alt_col"}}
    result = compute_sla(plan, adapter, answers=answers)
    assert result.volume.get("timeColumn") == "alt_col"


def test_compute_rejects_unsupported_plan():
    plan = AnalysisPlan(
        table_fqn="proj.ds.t",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick=None,
        volume_timestamp_candidates=[],
        schema_snapshot={"columns": []},
        row_count=None,
        unsupported=True,
        skipped_reason="No columns visible",
    )
    result = compute_sla(plan, _adapter(), answers={})
    assert result.unsupported is True
    assert result.skipped_reason == "No columns visible"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest scanner/tests/test_sla_compute.py -v`
Expected: ImportError on `compute_sla`.

- [ ] **Step 3: Implement `compute_sla`**

Add to `scanner/lineage/sla_discovery.py` (near the existing `discover_sla_direct`):

```python
from scanner.lineage.sla_analysis import AnalysisPlan, AnalyzeResult, analyze_sla  # noqa: E402


def compute_sla(
    plan: AnalysisPlan,
    adapter: Any,
    *,
    answers: Optional[Dict[str, Any]] = None,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """Phase 2: run dimension SQL using the analyzed plan + user answers."""
    if plan.unsupported:
        return DiscoveryResult(
            node_fqn=plan.table_fqn,
            warehouse_ancestor_fqn=plan.warehouse_ancestor_fqn,
            unsupported=True,
            skipped_reason=plan.skipped_reason,
        )

    chosen_ts = _resolve_volume_timestamp(plan, answers or {})

    metadata = {"row_count": plan.row_count} if plan.row_count is not None else None
    volume = _compute_volume(
        adapter,
        plan.table_fqn,
        metadata=metadata,
        timestamp_column=chosen_ts,
    )
    freshness = _compute_freshness(adapter, plan.table_fqn, timestamp_column=chosen_ts)
    schema = _compute_schema(adapter, plan.table_fqn)
    quality = _compute_quality(adapter, plan.table_fqn)
    uniqueness = _compute_uniqueness(adapter, plan.table_fqn)

    return DiscoveryResult(
        node_fqn=plan.table_fqn,
        warehouse_ancestor_fqn=plan.warehouse_ancestor_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
        uniqueness=uniqueness,
    )


def _resolve_volume_timestamp(plan: AnalysisPlan, answers: Dict[str, Any]) -> Optional[str]:
    """Pick the timestamp column for volume computation.

    Precedence: any answer whose payload carries a 'column' key, else
    plan.volume_timestamp_pick.column, else None.
    """
    for value in answers.values():
        if isinstance(value, dict) and value.get("column"):
            return value["column"]
    pick = plan.volume_timestamp_pick or {}
    return pick.get("column")
```

If `_compute_freshness` does not exist with a `timestamp_column` kwarg today, leave it without the kwarg — the test above only asserts on `volume.timeColumn`. Wire the freshness column threading in a follow-up if needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_sla_compute.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/tests/test_sla_compute.py
git commit -m "feat(scanner): implement compute_sla — phase 2 of two-phase discovery"
```

---

### Task 5: Add `analyze_sla_profile` and `compute_sla_profile` (graph-based variants)

These mirror the existing `discover_sla_profile(node, graph, adapter, ...)` which resolves the warehouse ancestor before discovering.

**Files:**
- Modify: `scanner/lineage/sla_analysis.py`, `scanner/lineage/sla_discovery.py`
- Test: `scanner/tests/test_sla_analysis.py`, `scanner/tests/test_sla_compute.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to scanner/tests/test_sla_analysis.py
from scanner.lineage.sla_analysis import analyze_sla_profile


def test_analyze_profile_resolves_warehouse_ancestor():
    node = MagicMock()
    node.fqn = "stg.events"
    graph = MagicMock()
    adapter = _adapter_with([_col("loaded_at")])
    # Stub the ancestor-finder by patching the helper in sla_discovery.
    with patch(
        "scanner.lineage.sla_analysis._find_warehouse_ancestor",
        return_value=("acme.analytics.events", None),
    ):
        result = analyze_sla_profile(node, graph, adapter, pipeline_stack_id="s", organization_id="o")
    assert result.plan.table_fqn == "acme.analytics.events"
    assert result.plan.warehouse_ancestor_fqn == "acme.analytics.events"
```

```python
# Append to scanner/tests/test_sla_compute.py
from scanner.lineage.sla_discovery import compute_sla_profile


def test_compute_profile_uses_warehouse_ancestor_from_plan():
    plan = AnalysisPlan(
        table_fqn="acme.analytics.events",
        warehouse_ancestor_fqn="acme.analytics.events",
        volume_timestamp_pick={"column": "loaded_at", "confidence": "strong", "score": 0.9, "rationale": ""},
        volume_timestamp_candidates=[{"column": "loaded_at", "data_type": "TIMESTAMP", "score": 0.9}],
        schema_snapshot={"columns": [{"name": "loaded_at"}]},
        row_count=100,
        unsupported=False,
        skipped_reason=None,
    )
    result = compute_sla_profile(plan, MagicMock(), _adapter(), answers={})
    assert result.warehouse_ancestor_fqn == "acme.analytics.events"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py -v -k profile`

- [ ] **Step 3: Implement `analyze_sla_profile`**

In `scanner/lineage/sla_analysis.py`:

```python
from scanner.lineage.sla_discovery import _find_warehouse_ancestor


def analyze_sla_profile(
    node: Any,
    graph: Any,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> AnalyzeResult:
    """Graph-aware analyze: resolves the warehouse ancestor first, then analyzes."""
    warehouse_fqn, _hint = _find_warehouse_ancestor(node, graph)
    target_fqn = warehouse_fqn or getattr(node, "fqn", None)
    if not target_fqn:
        plan = AnalysisPlan(
            table_fqn=getattr(node, "fqn", "<unknown>"),
            warehouse_ancestor_fqn=None,
            volume_timestamp_pick=None,
            volume_timestamp_candidates=[],
            schema_snapshot={"columns": []},
            row_count=None,
            unsupported=True,
            skipped_reason="No warehouse ancestor found.",
        )
        return AnalyzeResult(table_fqn=plan.table_fqn, plan=plan, status="ready")

    inner = analyze_sla(
        table_fqn=target_fqn,
        adapter=adapter,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    plan = AnalysisPlan(
        **{**asdict(inner.plan), "warehouse_ancestor_fqn": warehouse_fqn},
    )
    return AnalyzeResult(
        table_fqn=plan.table_fqn,
        plan=plan,
        status=inner.status,
        clarification_ids=inner.clarification_ids,
    )
```

- [ ] **Step 4: Implement `compute_sla_profile`**

In `scanner/lineage/sla_discovery.py`:

```python
def compute_sla_profile(
    plan: AnalysisPlan,
    graph: Any,
    adapter: Any,
    *,
    answers: Optional[Dict[str, Any]] = None,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """Graph variant — `graph` accepted for symmetry; warehouse ancestor is on plan."""
    return compute_sla(
        plan,
        adapter,
        answers=answers,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py -v -k profile`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add scanner/lineage/sla_analysis.py scanner/lineage/sla_discovery.py scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py
git commit -m "feat(scanner): add graph-aware analyze_sla_profile + compute_sla_profile"
```

---

### Task 6: Add bulk variants `analyze_sla_bulk` + `compute_sla_bulk`

**Files:**
- Modify: `scanner/lineage/sla_analysis.py`, `scanner/lineage/sla_discovery.py`
- Test: `scanner/tests/test_sla_analysis.py`, `scanner/tests/test_sla_compute.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to scanner/tests/test_sla_analysis.py
from scanner.lineage.sla_analysis import analyze_sla_bulk


def test_analyze_bulk_returns_one_result_per_table():
    adapters = {
        "bigquery": _adapter_with([_col("loaded_at", "TIMESTAMP")]),
    }
    nodes = [
        ("proj.ds.a", "bigquery"),
        ("proj.ds.b", "bigquery"),
    ]
    results = analyze_sla_bulk(nodes, adapters, pipeline_stack_id="s", organization_id="o")
    assert len(results) == 2
    assert {r.table_fqn for r in results} == {"proj.ds.a", "proj.ds.b"}
```

```python
# Append to scanner/tests/test_sla_compute.py
from scanner.lineage.sla_discovery import compute_sla_bulk


def test_compute_bulk_returns_one_result_per_plan():
    adapters = {"bigquery": _adapter()}
    plans = [
        (_plan("proj.ds.a"), "bigquery", {}),
        (_plan("proj.ds.b"), "bigquery", {}),
    ]
    results = compute_sla_bulk(plans, adapters)
    assert len(results) == 2
    assert {r.node_fqn for r in results} == {"proj.ds.a", "proj.ds.b"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py -v -k bulk`

- [ ] **Step 3: Implement the bulk variants**

```python
# scanner/lineage/sla_analysis.py
def analyze_sla_bulk(
    nodes: List[tuple[str, str]],   # (table_fqn, platform_key)
    adapters: Dict[str, Any],
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> List[AnalyzeResult]:
    results: List[AnalyzeResult] = []
    for table_fqn, platform in nodes:
        adapter = adapters.get(platform)
        if adapter is None:
            plan = AnalysisPlan(
                table_fqn=table_fqn,
                warehouse_ancestor_fqn=None,
                volume_timestamp_pick=None,
                volume_timestamp_candidates=[],
                schema_snapshot={"columns": []},
                row_count=None,
                unsupported=True,
                skipped_reason=f"No adapter for platform '{platform}'.",
            )
            results.append(AnalyzeResult(table_fqn=table_fqn, plan=plan, status="ready"))
            continue
        results.append(
            analyze_sla(
                table_fqn=table_fqn,
                adapter=adapter,
                pipeline_stack_id=pipeline_stack_id,
                organization_id=organization_id,
            )
        )
    return results
```

```python
# scanner/lineage/sla_discovery.py
def compute_sla_bulk(
    plans: List[tuple[AnalysisPlan, str, Dict[str, Any]]],  # (plan, platform, answers)
    adapters: Dict[str, Any],
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> List[DiscoveryResult]:
    results: List[DiscoveryResult] = []
    for plan, platform, answers in plans:
        adapter = adapters.get(platform)
        if adapter is None:
            results.append(
                DiscoveryResult(
                    node_fqn=plan.table_fqn,
                    warehouse_ancestor_fqn=plan.warehouse_ancestor_fqn,
                    unsupported=True,
                    skipped_reason=f"No adapter for platform '{platform}'.",
                )
            )
            continue
        results.append(
            compute_sla(
                plan,
                adapter,
                answers=answers,
                pipeline_stack_id=pipeline_stack_id,
                organization_id=organization_id,
            )
        )
    return results
```

(Note: synchronous loop on purpose. The existing `direct-bulk` FastAPI endpoint already runs its own concurrency at the router layer with a semaphore; we move that there in Task 7.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_analysis.py scanner/lineage/sla_discovery.py scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py
git commit -m "feat(scanner): add analyze_sla_bulk + compute_sla_bulk"
```

---

### Task 7: Add FastAPI routes `/discovery/analyze` + `/discovery/compute`

**Files:**
- Modify: `scanner/api/routers/discovery.py`
- Test: `scanner/tests/test_discovery_router_two_phase.py`

- [ ] **Step 1: Write the failing tests**

```python
# scanner/tests/test_discovery_router_two_phase.py
from __future__ import annotations

from fastapi.testclient import TestClient

from scanner.api.server import app
from scanner.api.auth import require_principal


def _override_principal():
    class P:
        organization_id = "org_1"
        pipeline_stack_id = "stack_1"
    return P()


def setup_module(_mod):
    app.dependency_overrides[require_principal] = _override_principal


def teardown_module(_mod):
    app.dependency_overrides.clear()


def test_analyze_route_returns_ready_for_confident_pick(monkeypatch):
    from scanner.api.routers import discovery as router_mod
    from scanner.lineage.sla_analysis import AnalysisPlan, AnalyzeResult

    plan = AnalysisPlan(
        table_fqn="proj.ds.t",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={"column": "loaded_at", "confidence": "strong", "score": 0.9, "rationale": ""},
        volume_timestamp_candidates=[],
        schema_snapshot={"columns": []},
        row_count=100,
        unsupported=False,
        skipped_reason=None,
    )
    monkeypatch.setattr(
        router_mod, "analyze_sla", lambda **kw: AnalyzeResult("proj.ds.t", plan, "ready", [])
    )
    monkeypatch.setattr(router_mod, "_adapter_for_fqn", lambda fqn: object())

    client = TestClient(app)
    r = client.post("/api/v1/discovery/analyze", json={"table_fqn": "proj.ds.t"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["clarification_ids"] == []
    assert body["plan"]["table_fqn"] == "proj.ds.t"


def test_compute_route_rejects_mismatched_plan(monkeypatch):
    client = TestClient(app)
    body = {
        "table_fqn": "proj.ds.t",
        "plan": {"table_fqn": "proj.ds.other", "warehouse_ancestor_fqn": None,
                 "volume_timestamp_pick": None, "volume_timestamp_candidates": [],
                 "schema_snapshot": {}, "row_count": None,
                 "unsupported": False, "skipped_reason": None},
        "answers": {},
    }
    r = client.post("/api/v1/discovery/compute", json=body)
    assert r.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest scanner/tests/test_discovery_router_two_phase.py -v`
Expected: 404 for the analyze route (doesn't exist yet).

- [ ] **Step 3: Add the routes**

In `scanner/api/routers/discovery.py`:

```python
from pydantic import BaseModel
from scanner.lineage.sla_analysis import (
    AnalysisPlan,
    analyze_sla,
    analyze_sla_bulk,
    plan_from_dict,
    plan_to_dict,
)
from scanner.lineage.sla_discovery import compute_sla, compute_sla_bulk


class AnalyzeRequest(BaseModel):
    table_fqn: str


class ComputeRequest(BaseModel):
    table_fqn: str
    plan: dict
    answers: dict = {}


@router.post("/discovery/analyze")
def analyze_endpoint(req: AnalyzeRequest, principal=Depends(require_principal)):
    adapter = _adapter_for_fqn(req.table_fqn)
    result = analyze_sla(
        table_fqn=req.table_fqn,
        adapter=adapter,
        pipeline_stack_id=principal.pipeline_stack_id,
        organization_id=principal.organization_id,
    )
    return {
        "status": result.status,
        "table_fqn": result.table_fqn,
        "plan": plan_to_dict(result.plan),
        "clarification_ids": result.clarification_ids,
    }


@router.post("/discovery/compute")
def compute_endpoint(req: ComputeRequest, principal=Depends(require_principal)):
    plan = plan_from_dict(req.plan)
    if plan.table_fqn != req.table_fqn:
        raise HTTPException(status_code=400, detail="plan.table_fqn does not match request table_fqn")
    adapter = _adapter_for_fqn(req.table_fqn)
    result = compute_sla(
        plan,
        adapter,
        answers=req.answers,
        pipeline_stack_id=principal.pipeline_stack_id,
        organization_id=principal.organization_id,
    )
    return result.as_dict() if hasattr(result, "as_dict") else _discovery_to_dict(result)
```

If `_adapter_for_fqn` does not exist in the router today, extract it from the existing `/discovery/direct` body (it currently selects an adapter by platform inferred from the FQN). Reuse, do not duplicate.

If `_discovery_to_dict` does not exist, use the existing serializer the current `/discovery/direct` route uses; locate it by reading lines 385-440 of `scanner/api/routers/discovery.py` and reuse.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_discovery_router_two_phase.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scanner/api/routers/discovery.py scanner/tests/test_discovery_router_two_phase.py
git commit -m "feat(scanner): add /discovery/analyze + /discovery/compute FastAPI routes"
```

---

### Task 8: Add FastAPI bulk routes `/discovery/analyze-bulk` + `/discovery/compute-bulk`

**Files:**
- Modify: `scanner/api/routers/discovery.py`
- Test: `scanner/tests/test_discovery_router_two_phase.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to scanner/tests/test_discovery_router_two_phase.py
def test_analyze_bulk_route(monkeypatch):
    from scanner.api.routers import discovery as router_mod
    from scanner.lineage.sla_analysis import AnalysisPlan, AnalyzeResult

    def fake_bulk(nodes, adapters, **kw):
        return [
            AnalyzeResult(
                table_fqn=fqn,
                plan=AnalysisPlan(fqn, None, None, [], {"columns": []}, None),
                status="ready",
                clarification_ids=[],
            )
            for fqn, _platform in nodes
        ]

    monkeypatch.setattr(router_mod, "analyze_sla_bulk", fake_bulk)
    monkeypatch.setattr(router_mod, "_adapters_for_nodes", lambda nodes: {"bigquery": object()})

    client = TestClient(app)
    r = client.post("/api/v1/discovery/analyze-bulk", json={
        "nodes": [{"table_fqn": "p.d.a", "platform": "bigquery"},
                  {"table_fqn": "p.d.b", "platform": "bigquery"}],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    assert all(item["status"] == "ready" for item in body["results"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest scanner/tests/test_discovery_router_two_phase.py::test_analyze_bulk_route -v`

- [ ] **Step 3: Implement the bulk routes**

```python
# scanner/api/routers/discovery.py
class BulkNode(BaseModel):
    table_fqn: str
    platform: str


class AnalyzeBulkRequest(BaseModel):
    nodes: List[BulkNode]


class ComputeBulkItem(BaseModel):
    table_fqn: str
    platform: str
    plan: dict
    answers: dict = {}


class ComputeBulkRequest(BaseModel):
    items: List[ComputeBulkItem]


@router.post("/discovery/analyze-bulk")
def analyze_bulk_endpoint(req: AnalyzeBulkRequest, principal=Depends(require_principal)):
    nodes = [(n.table_fqn, n.platform) for n in req.nodes]
    adapters = _adapters_for_nodes(nodes)
    results = analyze_sla_bulk(
        nodes,
        adapters,
        pipeline_stack_id=principal.pipeline_stack_id,
        organization_id=principal.organization_id,
    )
    return {
        "results": [
            {
                "table_fqn": r.table_fqn,
                "status": r.status,
                "plan": plan_to_dict(r.plan),
                "clarification_ids": r.clarification_ids,
            }
            for r in results
        ]
    }


@router.post("/discovery/compute-bulk")
def compute_bulk_endpoint(req: ComputeBulkRequest, principal=Depends(require_principal)):
    nodes = [(i.table_fqn, i.platform) for i in req.items]
    adapters = _adapters_for_nodes(nodes)
    plans = []
    for item in req.items:
        plan = plan_from_dict(item.plan)
        if plan.table_fqn != item.table_fqn:
            raise HTTPException(status_code=400, detail=f"plan mismatch for {item.table_fqn}")
        plans.append((plan, item.platform, item.answers))
    results = compute_sla_bulk(
        plans,
        adapters,
        pipeline_stack_id=principal.pipeline_stack_id,
        organization_id=principal.organization_id,
    )
    return {"results": [_discovery_to_dict(r) for r in results]}
```

Add a helper `_adapters_for_nodes(nodes)` that mirrors how the existing `/discovery/direct-bulk` builds its per-platform adapter map. Read lines 449-520 of `scanner/api/routers/discovery.py` and extract that logic.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest scanner/tests/test_discovery_router_two_phase.py -v`
Expected: 3 passed total.

- [ ] **Step 5: Commit**

```bash
git add scanner/api/routers/discovery.py scanner/tests/test_discovery_router_two_phase.py
git commit -m "feat(scanner): add /discovery/analyze-bulk + /discovery/compute-bulk FastAPI routes"
```

---

### Task 9: Convert legacy `discover_sla_*` functions into wrappers; delete listener stub

**Files:**
- Modify: `scanner/lineage/sla_discovery.py`
- Delete: `scanner/lineage/sla_discovery_listeners.py`

- [ ] **Step 1: Wrap the legacy single-table function**

Replace the body of `discover_sla_direct` with:

```python
def discover_sla_direct(
    table_fqn: str,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """DEPRECATED — calls analyze + compute with empty answers.

    Kept during rollout so any caller we haven't migrated still works. Will
    be removed in the cleanup deploy.
    """
    analysis = analyze_sla(
        table_fqn=table_fqn,
        adapter=adapter,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    return compute_sla(
        analysis.plan,
        adapter,
        answers={},
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
```

- [ ] **Step 2: Wrap the legacy graph + bulk variants**

```python
def discover_sla_profile(node, graph, adapter, *, pipeline_stack_id=None, organization_id=None):
    analysis = analyze_sla_profile(
        node, graph, adapter,
        pipeline_stack_id=pipeline_stack_id, organization_id=organization_id,
    )
    return compute_sla_profile(
        analysis.plan, graph, adapter, answers={},
        pipeline_stack_id=pipeline_stack_id, organization_id=organization_id,
    )


def discover_sla_profiles_bulk(nodes, graph, adapters, *, pipeline_stack_id=None, organization_id=None):
    # Existing implementation already loops per-node. Replace inner discover call
    # with analyze_sla_profile + compute_sla_profile to share the new code path.
    results = []
    for node in nodes:
        platform = _platform_for_node(node)
        adapter = adapters.get(platform)
        if adapter is None:
            continue
        results.append(
            discover_sla_profile(
                node, graph, adapter,
                pipeline_stack_id=pipeline_stack_id, organization_id=organization_id,
            )
        )
    return results
```

- [ ] **Step 3: Delete the listener stub**

```bash
git rm scanner/lineage/sla_discovery_listeners.py
```

If the file is imported anywhere, grep first and remove the import sites:

```bash
grep -rn "sla_discovery_listeners" /Users/emilfabel/pallisade-copilot/scanner --include="*.py"
```

Remove each import line; tests must still pass after.

- [ ] **Step 4: Run the full discovery test suite to verify no regressions**

Run: `pytest scanner/tests/test_sla_discovery.py scanner/tests/test_sla_discovery_clarification.py scanner/tests/test_sla_analysis.py scanner/tests/test_sla_compute.py scanner/tests/test_discovery_router_two_phase.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_discovery.py
git commit -m "refactor(scanner): legacy discover_sla_* become thin wrappers around analyze+compute; drop listener stub"
```

---

### Task 10: Add Next.js analyze route `/api/nodes/[nodeId]/sla/discover/analyze`

**Files:**
- Create: `app/api/nodes/[nodeId]/sla/discover/analyze/route.ts`

- [ ] **Step 1: Inspect the existing route to match auth + proxy patterns**

Read `app/api/nodes/[nodeId]/sla/discover/route.ts`. Copy its auth check, tenant lookup, and FastAPI proxy plumbing.

- [ ] **Step 2: Write the new route**

```ts
// app/api/nodes/[nodeId]/sla/discover/analyze/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { requireSessionUser } from '@/lib/auth/session';
import { proxyToFastApi } from '@/lib/fastapi/proxy';
import { resolveNodeContext } from '@/lib/lineage/node-context';

export async function POST(req: NextRequest, { params }: { params: { nodeId: string } }) {
  const user = await requireSessionUser(req);
  if (!user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });

  const ctx = await resolveNodeContext(params.nodeId, user.organizationId);
  if (!ctx) return NextResponse.json({ error: 'node not found' }, { status: 404 });

  const res = await proxyToFastApi('/api/v1/discovery/analyze', {
    method: 'POST',
    body: JSON.stringify({ table_fqn: ctx.tableFqn }),
    headers: { 'Content-Type': 'application/json' },
    organizationId: user.organizationId,
    pipelineStackId: ctx.pipelineStackId,
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

Names like `requireSessionUser`, `proxyToFastApi`, `resolveNodeContext` mirror the existing `discover/route.ts` — use whatever the existing route imports. If a helper has a different name in this codebase, reuse it as-is; do not introduce a new helper.

- [ ] **Step 3: Smoke-check the route via curl (dev)**

```bash
curl -X POST -H "Content-Type: application/json" -b cookie.txt \
  http://localhost:3000/api/nodes/<some-node-id>/sla/discover/analyze
```
Expected: 200 with `{status: "ready" | "awaiting_clarifications", plan, clarification_ids}`.

- [ ] **Step 4: Commit**

```bash
git add app/api/nodes/\[nodeId\]/sla/discover/analyze/route.ts
git commit -m "feat(api): add /sla/discover/analyze route"
```

---

### Task 11: Add Next.js compute route `/api/nodes/[nodeId]/sla/discover/compute`

**Files:**
- Create: `app/api/nodes/[nodeId]/sla/discover/compute/route.ts`

- [ ] **Step 1: Write the route**

```ts
// app/api/nodes/[nodeId]/sla/discover/compute/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { requireSessionUser } from '@/lib/auth/session';
import { proxyToFastApi } from '@/lib/fastapi/proxy';
import { resolveNodeContext } from '@/lib/lineage/node-context';

export async function POST(req: NextRequest, { params }: { params: { nodeId: string } }) {
  const user = await requireSessionUser(req);
  if (!user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });

  const ctx = await resolveNodeContext(params.nodeId, user.organizationId);
  if (!ctx) return NextResponse.json({ error: 'node not found' }, { status: 404 });

  const body = await req.json().catch(() => ({}));
  if (!body?.plan || body.plan.table_fqn !== ctx.tableFqn) {
    return NextResponse.json({ error: 'plan mismatch' }, { status: 400 });
  }

  const res = await proxyToFastApi('/api/v1/discovery/compute', {
    method: 'POST',
    body: JSON.stringify({
      table_fqn: ctx.tableFqn,
      plan: body.plan,
      answers: body.answers ?? {},
    }),
    headers: { 'Content-Type': 'application/json' },
    organizationId: user.organizationId,
    pipelineStackId: ctx.pipelineStackId,
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

- [ ] **Step 2: Smoke-check via curl**

```bash
curl -X POST -H "Content-Type: application/json" -b cookie.txt \
  -d '{"plan": {"table_fqn":"proj.ds.t", "warehouse_ancestor_fqn":null, "volume_timestamp_pick":{"column":"loaded_at","confidence":"strong","score":0.9,"rationale":""}, "volume_timestamp_candidates":[], "schema_snapshot":{"columns":[]}, "row_count":100, "unsupported":false, "skipped_reason":null}, "answers": {}}' \
  http://localhost:3000/api/nodes/<some-node-id>/sla/discover/compute
```
Expected: 200 with the full DiscoveryResult shape.

- [ ] **Step 3: Commit**

```bash
git add app/api/nodes/\[nodeId\]/sla/discover/compute/route.ts
git commit -m "feat(api): add /sla/discover/compute route"
```

---

### Task 12: Add Next.js bulk routes `discover-bulk/analyze` + `discover-bulk/compute`

**Files:**
- Create: `app/api/nodes/sla/discover-bulk/analyze/route.ts`
- Create: `app/api/nodes/sla/discover-bulk/compute/route.ts`

- [ ] **Step 1: Write the analyze-bulk route**

```ts
// app/api/nodes/sla/discover-bulk/analyze/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { requireSessionUser } from '@/lib/auth/session';
import { proxyToFastApi } from '@/lib/fastapi/proxy';
import { resolveBulkNodeContext } from '@/lib/lineage/node-context';

export async function POST(req: NextRequest) {
  const user = await requireSessionUser(req);
  if (!user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const nodeIds: string[] = body?.node_ids ?? [];
  if (nodeIds.length === 0) return NextResponse.json({ results: [] });

  const ctx = await resolveBulkNodeContext(nodeIds, user.organizationId);
  const res = await proxyToFastApi('/api/v1/discovery/analyze-bulk', {
    method: 'POST',
    body: JSON.stringify({
      nodes: ctx.map((c) => ({ table_fqn: c.tableFqn, platform: c.platform })),
    }),
    headers: { 'Content-Type': 'application/json' },
    organizationId: user.organizationId,
    pipelineStackId: ctx[0]?.pipelineStackId,
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

- [ ] **Step 2: Write the compute-bulk route**

```ts
// app/api/nodes/sla/discover-bulk/compute/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { requireSessionUser } from '@/lib/auth/session';
import { proxyToFastApi } from '@/lib/fastapi/proxy';

export async function POST(req: NextRequest) {
  const user = await requireSessionUser(req);
  if (!user) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const items = body?.items ?? [];

  const res = await proxyToFastApi('/api/v1/discovery/compute-bulk', {
    method: 'POST',
    body: JSON.stringify({ items }),
    headers: { 'Content-Type': 'application/json' },
    organizationId: user.organizationId,
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

(If `resolveBulkNodeContext` does not exist, write a thin wrapper that maps `nodeIds → [{tableFqn, platform, pipelineStackId}]` reusing the same Prisma query the single-node version uses.)

- [ ] **Step 3: Commit**

```bash
git add app/api/nodes/sla/discover-bulk/analyze/route.ts app/api/nodes/sla/discover-bulk/compute/route.ts
git commit -m "feat(api): add /sla/discover-bulk/analyze + /compute bulk routes"
```

---

### Task 13: Add `useClarificationsResolved` hook to `ClarificationProvider`

**Files:**
- Create: `components/clarifications/useClarificationsResolved.ts`
- Create: `components/clarifications/__tests__/useClarificationsResolved.test.tsx`
- Modify: `components/clarifications/ClarificationProvider.tsx` (expose `requestsById` if not already)

- [ ] **Step 1: Write the failing test**

```tsx
// components/clarifications/__tests__/useClarificationsResolved.test.tsx
import { render, act } from '@testing-library/react';
import { ClarificationContext } from '@/components/clarifications/ClarificationProvider';
import { useClarificationsResolved } from '@/components/clarifications/useClarificationsResolved';

function Harness({ ids, onAllResolved }: { ids: string[]; onAllResolved: (a: Record<string, unknown>) => void }) {
  useClarificationsResolved(ids, onAllResolved);
  return null;
}

function withCtx(requestsById: Record<string, { status: string; answer?: unknown }>) {
  return ({ children }: { children: React.ReactNode }) => (
    <ClarificationContext.Provider value={{ requestsById, /* other fields stubbed */ } as any}>
      {children}
    </ClarificationContext.Provider>
  );
}

test('fires when every id is answered', () => {
  const cb = jest.fn();
  const initial = {
    a: { status: 'open' },
    b: { status: 'open' },
  };
  const Wrapper = withCtx(initial);
  const { rerender } = render(<Wrapper><Harness ids={['a','b']} onAllResolved={cb} /></Wrapper>);
  expect(cb).not.toHaveBeenCalled();

  const resolved = {
    a: { status: 'answered', answer: { column: 'loaded_at' } },
    b: { status: 'answered', answer: { column: 'date' } },
  };
  rerender(<>{(withCtx(resolved))({ children: <Harness ids={['a','b']} onAllResolved={cb} /> })}</>);
  expect(cb).toHaveBeenCalledWith({ a: { column: 'loaded_at' }, b: { column: 'date' } });
});

test('does not fire when ids array is empty', () => {
  const cb = jest.fn();
  const Wrapper = withCtx({});
  render(<Wrapper><Harness ids={[]} onAllResolved={cb} /></Wrapper>);
  expect(cb).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/emilfabel/pallisade-copilot && npm test -- useClarificationsResolved`
Expected: import error.

- [ ] **Step 3: Implement the hook**

```tsx
// components/clarifications/useClarificationsResolved.ts
import { useContext, useEffect, useRef } from 'react';
import { ClarificationContext } from './ClarificationProvider';

export function useClarificationsResolved(
  ids: string[],
  onAllResolved: (answers: Record<string, unknown>) => void,
) {
  const ctx = useContext(ClarificationContext);
  const firedRef = useRef(false);

  useEffect(() => {
    if (ids.length === 0) {
      firedRef.current = false;
      return;
    }
    const requestsById = ctx?.requestsById ?? {};
    const allAnswered = ids.every((id) => requestsById[id]?.status === 'answered');
    if (allAnswered && !firedRef.current) {
      const answers: Record<string, unknown> = {};
      for (const id of ids) answers[id] = requestsById[id]?.answer;
      firedRef.current = true;
      onAllResolved(answers);
    }
    if (!allAnswered) firedRef.current = false;
  }, [ids, ctx?.requestsById, onAllResolved]);
}
```

- [ ] **Step 4: Expose `requestsById` from `ClarificationProvider`**

Open `components/clarifications/ClarificationProvider.tsx`. The provider already polls and stores `requests: ContextRequest[]`. Add a derived `requestsById` map:

```tsx
const requestsById = useMemo(() => {
  const m: Record<string, ContextRequest> = {};
  for (const r of requests) m[r.id] = r;
  return m;
}, [requests]);
```

Add `requestsById` to the value passed via `ClarificationContext.Provider`. Update the context type accordingly.

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- useClarificationsResolved`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add components/clarifications/useClarificationsResolved.ts \
        components/clarifications/__tests__/useClarificationsResolved.test.tsx \
        components/clarifications/ClarificationProvider.tsx
git commit -m "feat(clarifications): add useClarificationsResolved hook"
```

---

### Task 14: Extend `DataAssetDetailPanel` state machine for two-phase discovery

**Files:**
- Modify: `components/lineage/DataAssetDetailPanel.tsx`
- Test: `components/lineage/__tests__/DataAssetDetailPanel.discovery.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// components/lineage/__tests__/DataAssetDetailPanel.discovery.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DataAssetDetailPanel } from '@/components/lineage/DataAssetDetailPanel';
import { ClarificationContext } from '@/components/clarifications/ClarificationProvider';

const fetchMock = jest.fn();
global.fetch = fetchMock as any;

const baseProps = { node: { id: 'n1', fqn: 'proj.ds.t' }, onClose: () => {} };

beforeEach(() => fetchMock.mockReset());

function withClarifications(requestsById: Record<string, any>) {
  return ({ children }: { children: React.ReactNode }) => (
    <ClarificationContext.Provider value={{ requestsById, requests: Object.values(requestsById) } as any}>
      {children}
    </ClarificationContext.Provider>
  );
}

test('confident analyze auto-fires compute and shows confirm', async () => {
  fetchMock
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ready',
        table_fqn: 'proj.ds.t',
        plan: { table_fqn: 'proj.ds.t' },
        clarification_ids: [],
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ volume: { enabled: true, expectedDaily: { min: 50, max: 150 } } }),
    });

  const Wrapper = withClarifications({});
  render(<Wrapper><DataAssetDetailPanel {...baseProps} /></Wrapper>);
  await userEvent.click(screen.getByRole('button', { name: /discover/i }));
  await waitFor(() => screen.getByText(/expected daily/i));
});

test('ambiguous analyze shows awaiting view, no SLA values', async () => {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      status: 'awaiting_clarifications',
      table_fqn: 'proj.ds.t',
      plan: { table_fqn: 'proj.ds.t' },
      clarification_ids: ['ctx_1'],
    }),
  });

  const Wrapper = withClarifications({ ctx_1: { id: 'ctx_1', status: 'open' } });
  render(<Wrapper><DataAssetDetailPanel {...baseProps} /></Wrapper>);
  await userEvent.click(screen.getByRole('button', { name: /discover/i }));
  await waitFor(() => screen.getByText(/need your input/i));
  expect(screen.queryByText(/expected daily/i)).toBeNull();
});

test('answering all clarifications fires compute', async () => {
  fetchMock
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'awaiting_clarifications',
        table_fqn: 'proj.ds.t',
        plan: { table_fqn: 'proj.ds.t' },
        clarification_ids: ['ctx_1'],
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ volume: { enabled: true, expectedDaily: { min: 50, max: 150 } } }),
    });

  let setRequests: (r: Record<string, any>) => void;
  function CtxWithSetter({ children }: { children: React.ReactNode }) {
    const [requestsById, setR] = React.useState<Record<string, any>>({ ctx_1: { id: 'ctx_1', status: 'open' } });
    setRequests = setR;
    return (
      <ClarificationContext.Provider value={{ requestsById, requests: Object.values(requestsById) } as any}>
        {children}
      </ClarificationContext.Provider>
    );
  }

  render(<CtxWithSetter><DataAssetDetailPanel {...baseProps} /></CtxWithSetter>);
  await userEvent.click(screen.getByRole('button', { name: /discover/i }));
  await waitFor(() => screen.getByText(/need your input/i));
  act(() => setRequests!({ ctx_1: { id: 'ctx_1', status: 'answered', answer: { column: 'loaded_at' } } }));
  await waitFor(() => screen.getByText(/expected daily/i));
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- DataAssetDetailPanel.discovery`

- [ ] **Step 3: Refactor `DataAssetDetailPanel`**

In `components/lineage/DataAssetDetailPanel.tsx`:

1. Replace `discoveryState: 'idle' | 'loading' | 'confirm' | 'unsupported'` with `'idle' | 'analyzing' | 'awaiting_clarifications' | 'computing' | 'confirm' | 'unsupported'`.
2. Add state: `plan: AnalysisPlanDto | null` and `clarificationIds: string[]`.
3. Replace `handleDiscover` with:
   ```tsx
   const handleDiscover = async () => {
     setDiscoveryState('analyzing');
     const r = await fetch(`/api/nodes/${node.id}/sla/discover/analyze`, { method: 'POST' });
     const body = await r.json();
     setPlan(body.plan);
     setClarificationIds(body.clarification_ids);
     if (body.status === 'ready') {
       await fireCompute(body.plan, {});
     } else {
       setDiscoveryState('awaiting_clarifications');
     }
   };

   const fireCompute = async (plan: AnalysisPlanDto, answers: Record<string, unknown>) => {
     setDiscoveryState('computing');
     const r = await fetch(`/api/nodes/${node.id}/sla/discover/compute`, {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({ plan, answers }),
     });
     const body = await r.json();
     setDiscoveryResult(body);
     setDiscoveryState('confirm');
   };
   ```
4. Wire `useClarificationsResolved`:
   ```tsx
   useClarificationsResolved(
     discoveryState === 'awaiting_clarifications' ? clarificationIds : [],
     (answers) => {
       if (plan) void fireCompute(plan, answers);
     },
   );
   ```
5. Remove every reference to `discoveryResult?.volume?.tentative` and `discoveryResult?.volume?.context_request_id`. Search the file for `tentative` and `context_request_id` and delete those branches.
6. Add the `awaiting_clarifications` view (next task wires its visuals).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- DataAssetDetailPanel.discovery`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add components/lineage/DataAssetDetailPanel.tsx components/lineage/__tests__/DataAssetDetailPanel.discovery.test.tsx
git commit -m "feat(lineage): two-phase discovery state machine in DataAssetDetailPanel"
```

---

### Task 15: Render the `awaiting_clarifications` view

**Files:**
- Modify: `components/lineage/DataAssetDetailPanel.tsx`

- [ ] **Step 1: Add the view JSX**

Inside the conditional render where `discoveryState === 'analyzing' || discoveryState === 'computing'` currently shows a spinner, branch on `awaiting_clarifications`:

```tsx
{discoveryState === 'awaiting_clarifications' && (
  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
    <div className="font-medium">Need your input</div>
    <div className="mt-1 text-amber-800">
      Pallisade needs you to confirm {clarificationIds.length} column choice
      {clarificationIds.length === 1 ? '' : 's'} before computing SLAs.
    </div>
    <button
      type="button"
      onClick={() => openClarificationPopup(clarificationIds[0])}
      className="mt-2 inline-flex items-center text-amber-900 underline"
    >
      Answer now →
    </button>
  </div>
)}
```

`openClarificationPopup` should come from the existing clarification popup context — if there's no programmatic open API today, add one to `ClarificationProvider` exposing `openRequest(id: string): void` that sets the popup's active request. Wire it where the existing popup decides which request to display.

- [ ] **Step 2: Smoke-check in the dev server**

Start the app, click Discover on a table with an ambiguous timestamp column. Verify the panel shows "Need your input" and no SLA fields. Click "Answer now", answer the clarification, verify SLA values appear within ~15 seconds.

- [ ] **Step 3: Commit**

```bash
git add components/lineage/DataAssetDetailPanel.tsx components/clarifications/ClarificationProvider.tsx
git commit -m "feat(lineage): render awaiting-clarifications view; expose openRequest from ClarificationProvider"
```

---

### Task 16: Bulk discovery — analyze-first banner + parallel compute

**Files:**
- Modify: whichever component triggers bulk discovery from "Data SLA Mode" (locate via `grep -n "discover-bulk" components/`)

- [ ] **Step 1: Locate the bulk trigger**

```bash
grep -rn "discover-bulk" /Users/emilfabel/pallisade-copilot/components/ /Users/emilfabel/pallisade-copilot/app/
```
Expected: one or two call sites, likely in a lineage page or a bulk-discovery hook.

- [ ] **Step 2: Refactor the trigger**

Replace the single POST to `/api/nodes/sla/discover-bulk` with:

1. POST `/api/nodes/sla/discover-bulk/analyze` with `node_ids`.
2. From the result, split into `ready` and `awaiting_clarifications` buckets.
3. For `ready` items, immediately POST `/api/nodes/sla/discover-bulk/compute` with `items: [{table_fqn, platform, plan, answers: {}}]`.
4. For `awaiting_clarifications` items, store `plan` and `clarification_ids` in component state; show a banner "N nodes need input." When each node's clarifications resolve (use `useClarificationsResolved` per node), POST `/compute-bulk` with just that item, or accumulate and batch.

State shape:

```tsx
type BulkSlot =
  | { nodeId: string; status: 'analyzing' | 'computing' }
  | { nodeId: string; status: 'awaiting'; plan: AnalysisPlanDto; clarificationIds: string[] }
  | { nodeId: string; status: 'ready'; result: DiscoveryResult }
  | { nodeId: string; status: 'error'; message: string };
```

Banner copy:

```
Computing 8 of 21 · 3 awaiting input · 10 ready
```

- [ ] **Step 3: Manual verification**

Trigger "Data SLA Mode" on a pipeline with ≥1 ambiguous-timestamp table. Verify ready nodes compute immediately; ambiguous nodes wait. Verify the banner counts are right.

- [ ] **Step 4: Commit**

```bash
git add <the modified files>
git commit -m "feat(lineage): bulk discovery uses analyze-first + per-node compute"
```

---

### Task 17: Remove dead `tentative` rendering paths

**Files:**
- Search and modify across `components/`, `app/`, `lib/`.

- [ ] **Step 1: Find all references**

```bash
grep -rn "tentative\|context_request_id" /Users/emilfabel/pallisade-copilot/components /Users/emilfabel/pallisade-copilot/app /Users/emilfabel/pallisade-copilot/lib --include="*.ts" --include="*.tsx"
```

For each hit:
- If it's reading from a `DiscoveryResult` shape, the field can never be present after the refactor — delete the branch.
- If it's reading from a `ContextRequest` shape, leave it (that's the durable record and is unchanged).

- [ ] **Step 2: Delete the dead branches**

Make the edits one file at a time. Run `npm test` between batches to catch breakage.

- [ ] **Step 3: Verify no references remain in discovery code**

```bash
grep -rn "tentative" /Users/emilfabel/pallisade-copilot/components/lineage /Users/emilfabel/pallisade-copilot/components/clarifications --include="*.tsx"
```
Expected: no hits in lineage; clarifications hits are about ContextRequest, which is fine.

- [ ] **Step 4: Commit**

```bash
git add -u components/ app/ lib/
git commit -m "refactor(lineage): remove tentative SLA rendering — superseded by two-phase flow"
```

---

### Task 18: End-to-end integration test

**Files:**
- Modify: `scanner/tests/test_discovery_router_two_phase.py`

- [ ] **Step 1: Write the integration test**

```python
# Append to scanner/tests/test_discovery_router_two_phase.py
def test_end_to_end_ambiguous_pick_user_overrides(monkeypatch):
    """analyze emits clarification → answer it → compute uses the answer."""
    from scanner.api.routers import discovery as router_mod

    captured_compute_ts = {}

    def fake_compute(plan, adapter, *, answers, **kw):
        from scanner.lineage.sla_discovery import _resolve_volume_timestamp
        captured_compute_ts["col"] = _resolve_volume_timestamp(plan, answers)
        from scanner.lineage.sla_discovery import DiscoveryResult
        return DiscoveryResult(
            node_fqn=plan.table_fqn,
            warehouse_ancestor_fqn=None,
            volume={"enabled": True, "timeColumn": captured_compute_ts["col"]},
        )

    monkeypatch.setattr(router_mod, "compute_sla", fake_compute)
    monkeypatch.setattr(router_mod, "_adapter_for_fqn", lambda fqn: object())

    client = TestClient(app)

    # 1. analyze returns awaiting (we simulate via patching the emit path).
    from scanner.lineage.sla_analysis import AnalysisPlan, AnalyzeResult
    plan = AnalysisPlan(
        table_fqn="proj.ds.t",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={"column": "ts", "confidence": "weak", "score": 0.3, "rationale": ""},
        volume_timestamp_candidates=[
            {"column": "ts", "data_type": "TIMESTAMP", "score": 0.3},
            {"column": "loaded_at", "data_type": "TIMESTAMP", "score": 0.25},
        ],
        schema_snapshot={"columns": [{"name": "ts"}, {"name": "loaded_at"}]},
        row_count=100,
    )
    monkeypatch.setattr(
        router_mod,
        "analyze_sla",
        lambda **kw: AnalyzeResult("proj.ds.t", plan, "awaiting_clarifications", ["ctx_1"]),
    )
    r = client.post("/api/v1/discovery/analyze", json={"table_fqn": "proj.ds.t"})
    body = r.json()
    assert body["status"] == "awaiting_clarifications"

    # 2. compute with the user's answer overriding the picker.
    compute_body = {
        "table_fqn": "proj.ds.t",
        "plan": body["plan"],
        "answers": {"ctx_1": {"column": "loaded_at"}},
    }
    r = client.post("/api/v1/discovery/compute", json=compute_body)
    assert r.status_code == 200
    assert captured_compute_ts["col"] == "loaded_at"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pytest scanner/tests/test_discovery_router_two_phase.py -v -k end_to_end`

- [ ] **Step 3: Commit**

```bash
git add scanner/tests/test_discovery_router_two_phase.py
git commit -m "test(scanner): end-to-end two-phase analyze → resolve → compute uses user's answer"
```

---

### Task 19: Smoke-check the full flow in dev and tag the deprecated endpoints

**Files:**
- Modify: `app/api/nodes/[nodeId]/sla/discover/route.ts` (old route)
- Modify: `app/api/nodes/sla/discover-bulk/route.ts` (old route)
- Modify: `scanner/api/routers/discovery.py` (old endpoints)

- [ ] **Step 1: Mark the old paths as deprecated with logs**

In each old route, add at the top:
```ts
console.warn('[deprecated] /api/nodes/.../sla/discover called — use /analyze + /compute');
```
In each old FastAPI endpoint:
```python
logger.warning("DEPRECATED endpoint /discovery/direct used — migrate to /analyze + /compute")
```

The legacy wrappers from Task 9 keep the behavior alive; this just logs so we can confirm zero hits before deletion.

- [ ] **Step 2: Run the dev server and exercise both single + bulk discovery end-to-end**

Manual checklist:
- [ ] Single-table discovery with confident pick → SLA values appear without any intermediate state visible.
- [ ] Single-table discovery with ambiguous pick → "Need your input" appears immediately, no SLA values shown; answering the clarification produces the SLA values, computed against the chosen column.
- [ ] Bulk discovery on a pipeline with mixed tables → ready ones compute immediately, ambiguous ones queue with a banner, answering each transitions it to computed.
- [ ] Refresh the page mid-flow → re-click Discover; flow picks up cleanly (existing ContextRequest is reused via dedup).

- [ ] **Step 3: Commit**

```bash
git add app/api/nodes/\[nodeId\]/sla/discover/route.ts app/api/nodes/sla/discover-bulk/route.ts scanner/api/routers/discovery.py
git commit -m "chore: mark legacy /discover endpoints deprecated with warning logs"
```

---

## Self-Review Checklist (after writing)

- [x] Spec §5 (architecture) → Tasks 1-12 (analyze + compute + bulk + routes).
- [x] Spec §6 (data contracts) → Task 1 (dataclasses) + Task 2 (analyze) + Task 4 (compute).
- [x] Spec §7 (frontend state machine) → Tasks 13-15.
- [x] Spec §8 (backend changes) → Tasks 2-9.
- [x] Spec §9 (frontend changes) → Tasks 10-17.
- [x] Spec §10 (migration / deployment order) → Task 9 (legacy wrappers) + Task 19 (deprecated logs).
- [x] Spec §11 (testing) → Tasks 1, 2, 3, 4, 5, 6, 7, 8, 13, 14, 18.
- [x] Spec §13 (rollout / observability) → Task 19.
- No placeholders, no "TBD". Every code step shows actual code.
- Type names consistent: `AnalysisPlan`, `AnalyzeResult`, `analyze_sla`, `compute_sla` used identically across backend tasks; `AnalysisPlanDto` on frontend (TS mirror of the Python dataclass — same field names, lowercase_snake to match JSON).
- One known mismatch left intentionally: tasks reference `_compute_freshness`, `_compute_schema`, `_compute_quality`, `_compute_uniqueness` without specifying their signatures. Those helpers exist in `sla_discovery.py` today and are used by `discover_sla_direct`; we reuse them as-is in `compute_sla`. If during implementation one of them needs a `timestamp_column` kwarg (likely `_compute_freshness`), add that kwarg in the same task that needs it and update its caller.

---

## Out-of-scope follow-ups (separate plans)

- Migrate the in-progress plan + answers into an `ArtifactKind.SLA_DISCOVERY` row once the agentic-artefacts work ships. Today the plan lives only in frontend state.
- Push `ContextRequest` resolution to subscribed pages via a `BroadcastChannel` event so the worst-case 15-second poll latency drops to <1s.
- Delete the legacy `/discover` + `/discover-bulk` endpoints (single cleanup deploy after Task 19 confirms zero hits in production logs for ≥1 week).
