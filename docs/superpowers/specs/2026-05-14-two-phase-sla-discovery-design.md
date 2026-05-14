# Two-phase SLA Discovery — Design

**Date:** 2026-05-14
**Status:** Draft, pending implementation plan
**Scope:** Split SLA discovery into an `analyze` phase that emits clarifications and a `compute` phase that runs after they are answered, so users never see SLA values that were computed against a guess they were never asked about.

---

## 1. Summary

When SLA discovery runs against a warehouse table whose timestamp column is ambiguous, the platform today (a) fires a `timestamp_choice` ContextRequest as a fire-and-forget side effect, (b) computes the volume SLA against its best guess anyway, and (c) returns the result to the frontend immediately. The clarification surfaces 0–15 seconds later via the polling `ClarificationProvider`. The user sees SLAs first, the clarifying question second — backwards from the intent.

This design splits discovery into two explicit phases:

- **Phase 1 — Analyze.** Fast, no warehouse-side aggregation. Picks timestamp candidates, introspects schema, emits ContextRequests for low-confidence picks, returns a plan describing what *will* be computed.
- **Phase 2 — Compute.** Slow, SQL-heavy. Takes the plan plus the user's answers (or no answers, when none were needed) and produces the final `DiscoveryResult`.

When phase 1 finds no clarifications needed, the frontend immediately fires phase 2 and the user sees no extra step. When phase 1 returns clarifications, the frontend gates the SLA results panel behind them. The user answers, the panel runs phase 2, and the result reflects their input.

No new DB models, no backend listener, no schema migration. The intermediate plan lives on the frontend (where the discovery result already lives today). The durable part — the ContextRequest itself — is already persisted by the existing clarification infrastructure.

## 2. Goals

- Clarifications must appear **before** SLA values, not alongside or after.
- SLA values that the user sees must always reflect the user's chosen inputs, not the platform's low-confidence guess.
- Zero schema changes. Reuse `ContextRequest` / `ContextResolution` as the durable record.
- Idempotent phase 1: re-clicking Discover after a page reload picks back up cleanly.
- Bulk discovery composes the same primitives without bespoke code paths.

## 3. Non-goals

- Persisting in-progress discovery runs to DB. (Deferred until `ArtifactKind.SLA_DISCOVERY` lands as part of the agentic-artefacts work.)
- Backend listener that auto-fires phase 2 when ContextResolution lands. (Frontend-driven for now; simpler, still correct because the frontend already polls.)
- New clarification types beyond `timestamp_choice`. (None exist in discovery today.)
- Cross-session resumption — if the user closes the tab mid-analysis, they re-click Discover. The clarification persists, so no work is lost; only the in-flight plan needs to be re-derived (phase 1 is fast).
- Backfill of historical tentative SLA results. There are none persisted today.

## 4. Background

### 4.1 Current control flow

1. User clicks **Discover** on `DataAssetDetailPanel` → `POST /api/nodes/{nodeId}/sla/discover`.
2. Next.js proxies to FastAPI `/api/v1/discovery/direct` (or `/discovery/node`).
3. `discover_sla_direct` → `_compute_volume` → `_pick_volume_timestamp_column` returns a `TimestampPick` with confidence.
4. `_compute_volume` then calls `_try_emit_timestamp_clarification` *unconditionally* before running the daily-count SQL. The emit is a synchronous HTTP POST to Next.js `/api/context-requests/create`. The function does not await any user answer.
5. `_compute_volume` runs `_get_daily_row_counts` using its best-guess timestamp column.
6. The volume result is marked `tentative=True` with `context_request_id` set when a clarification was emitted.
7. The full `DiscoveryResult` (freshness, volume, quality, schema, uniqueness) returns to the frontend, which renders the confirmation modal.
8. Meanwhile, `ClarificationProvider` polls `/api/context-requests` every 15s and renders the side panel with the question.

### 4.2 The gap the 2026-04-30 clarification spec did *not* close

That spec (§4.1) explicitly declared that `sla_discovery` should "emit on guess **and** re-run on answer." The emit landed; the re-run is a logged no-op in `sla_discovery_listeners.py:31-62` with the comment "deferred to the next user-triggered refresh." There is no path that actually re-computes SLAs against the user's answer. The user has to re-click Discover after answering, and even then, the volume SQL has already run once against the wrong column.

### 4.3 Why not lean on the artefact registry instead

The agentic-artefacts design (2026-05-13) introduces a polymorphic `Artifact` model with status lifecycle and per-artefact resumable sessions. An `ArtifactKind.SLA_DISCOVERY` would be the obvious place to store an in-progress two-phase run. We chose **not** to depend on that work because:

- It is still pre-implementation; tying this fix to it means waiting weeks.
- The artefact registry is the right home for cross-session resumability, but phase 1 is fast enough (no SQL) that re-running it on tab reload is cheap. The cross-session durability that artefacts buy us isn't load-bearing here.
- When the artefact registry ships, this design's `AnalysisPlan` already fits cleanly into `Artifact.payload` for kind `SLA_DISCOVERY`. The migration is additive: introduce the kind, persist plan + answers there, remove the frontend-held state. No re-architecture.

## 5. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ DataAssetDetailPanel (Next.js)                                  │
│   state: idle → analyzing → (awaiting | computing) → confirm    │
│                                       ▲                          │
│                                       │ ClarificationProvider    │
│                                       │ emits "answered" event   │
└──────────┬──────────────────────────────────────────────────────┘
           │ POST /sla/discover/analyze              POST /sla/discover/compute
           ▼                                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Next.js API routes                                              │
│   /api/nodes/{id}/sla/discover/analyze                          │
│   /api/nodes/{id}/sla/discover/compute                          │
│   /api/nodes/sla/discover-bulk/analyze                          │
│   /api/nodes/sla/discover-bulk/compute                          │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI scanner                                                 │
│   /api/v1/discovery/analyze        ── analyze_sla()             │
│   /api/v1/discovery/compute        ── compute_sla(plan, answers)│
│   /api/v1/discovery/analyze-bulk   ── analyze_sla_bulk()        │
│   /api/v1/discovery/compute-bulk   ── compute_sla_bulk()        │
│                                                                  │
│   analyze_sla:                                                   │
│     - _pick_volume_timestamp_column (existing)                  │
│     - schema introspection (existing)                            │
│     - emit ContextRequest(s) if confidence < threshold           │
│     - build AnalysisPlan (JSON-safe)                             │
│                                                                  │
│   compute_sla:                                                   │
│     - read answers, override plan.timestamp_column if user picked│
│     - _get_daily_row_counts, freshness, quality, schema, etc.    │
│     - return DiscoveryResult                                     │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│ Postgres                                                        │
│   ContextRequest / ContextResolution  (existing, unchanged)     │
└─────────────────────────────────────────────────────────────────┘
```

### 5.1 Load-bearing idea

`analyze_sla` and `compute_sla` are pure functions over the same `AnalysisPlan`. The plan is the **only** thing carried between phases. The frontend holds it in component state; if the user reloads the tab, they re-click Discover, phase 1 re-derives an equivalent plan, and the existing ContextRequest (deduped by `(pipelineStackId, kind, scopeType, scopeRef)`) is re-attached. Phase 2 is unchanged whether the plan came from a fresh analyze or a re-derived one.

## 6. Data contracts

### 6.1 `AnalysisPlan` (new, JSON-safe dataclass)

`scanner/lineage/sla_discovery.py`:

```python
@dataclass(frozen=True)
class AnalysisPlan:
    table_fqn: str
    warehouse_ancestor_fqn: Optional[str]
    # Volume dimension
    volume_timestamp_pick: Optional[TimestampPickDict]   # picker output, serialized
    volume_timestamp_candidates: List[CandidateDict]      # for the user to choose from
    # Other dimensions' inputs as needed (schema snapshot, sample rows, etc.)
    schema_snapshot: Dict[str, Any]
    row_count: Optional[int]
    # Skipped / unsupported flags
    unsupported: bool
    skipped_reason: Optional[str]
```

`TimestampPickDict` and `CandidateDict` are TypedDicts derived from the existing `TimestampPick` dataclass — same data, JSON-safe.

The plan is the full set of decisions phase 1 made (or deferred). Anything phase 2 needs from phase 1 lives here. No hidden state.

### 6.2 `AnalyzeResult` (new)

```python
@dataclass(frozen=True)
class AnalyzeResult:
    table_fqn: str
    plan: AnalysisPlan
    status: Literal["ready", "awaiting_clarifications"]
    clarification_ids: List[str]   # ContextRequest ids; empty when status="ready"
```

Serialized to the analyze endpoint response as JSON.

### 6.3 `compute_sla` signature

```python
def compute_sla(
    plan: AnalysisPlan,
    adapter: Any,
    *,
    answers: Dict[str, Any],                # {context_request_id: resolution.answer}
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult: ...
```

`answers` may be empty (when `status="ready"` came back from analyze). When non-empty, the function checks each known clarification kind and overrides plan fields accordingly. For `timestamp_choice`, the answer is `{column: "<chosen_column>"}`, which replaces `plan.volume_timestamp_pick.column` before `_get_daily_row_counts` runs.

### 6.4 HTTP contracts

**`POST /api/nodes/{nodeId}/sla/discover/analyze`** — body `{}`. Response:
```json
{
  "status": "awaiting_clarifications" | "ready",
  "table_fqn": "...",
  "plan": { ... AnalysisPlan ... },
  "clarification_ids": ["cuid1", "cuid2"]
}
```

**`POST /api/nodes/{nodeId}/sla/discover/compute`** — body:
```json
{ "plan": { ... }, "answers": { "cuid1": { "column": "loaded_at" } } }
```
Response: existing `DiscoveryResult` shape.

**`POST /api/nodes/sla/discover-bulk/analyze`** — body `{ node_ids: [...] }`. Response: array of `AnalyzeResult` per node.

**`POST /api/nodes/sla/discover-bulk/compute`** — body: array of `{plan, answers}` items. Response: array of `DiscoveryResult` per node.

FastAPI side mirrors the contracts at `/api/v1/discovery/analyze`, `/compute`, `/analyze-bulk`, `/compute-bulk`.

## 7. Frontend state machine

`DataAssetDetailPanel` `discoveryState` enum changes from `'idle' | 'loading' | 'confirm' | 'unsupported'` to:

```
'idle'
  → user clicks Discover →
'analyzing'
  → analyze response →
    if status === 'ready'   → 'computing' (auto-fire compute) → 'confirm'
    if status === 'awaiting' → 'awaiting_clarifications'
'awaiting_clarifications'
  → ClarificationProvider notifies all plan.clarification_ids answered →
'computing' (fire compute with answers) → 'confirm'
'unsupported'
  → terminal
```

While in `awaiting_clarifications` the panel shows a small "Need your input · N question(s)" callout that opens the clarification popup at the relevant request. The SLA results panel is **not rendered at all** in this state — there is no tentative preview. Showing partial SLAs (e.g. freshness/schema, which don't depend on clarifications) is tempting but creates the exact "partial answer first, full answer later" UX we are removing; defer until users ask.

### 7.1 Wiring the "all answered" trigger

`ClarificationProvider` already polls every 15s. We extend it to expose, in addition to the current `requests` array, a `useClarificationsResolved(ids: string[])` hook that fires a callback when all `ids` are in `status="answered"`. `DataAssetDetailPanel` uses this hook with `plan.clarification_ids` while in `awaiting_clarifications` state. When it fires, the panel fetches the answers for those ids and transitions to `computing`.

Latency: up to 15s in the worst case. Acceptable for v1; can be reduced later by having `POST /api/context-requests/[id]/resolve` push a `BroadcastChannel` event the provider listens to without waiting for the next poll tick.

## 8. Backend changes (Python)

### 8.1 `scanner/lineage/sla_discovery.py`

- Add `analyze_sla(table_fqn, adapter, ...)` and `analyze_sla_profile(node, graph, adapter, ...)`. They run schema introspection, `_pick_volume_timestamp_column`, and call a new `_try_emit_timestamp_clarification` only when `pick.confidence < CONFIG.confidence_threshold`. Build and return `AnalyzeResult`.
- Move clarification emission out of `_compute_volume` entirely. Volume computation no longer touches `ContextRequest`.
- Add `compute_sla(plan, adapter, *, answers, ...)` and `compute_sla_profile(plan, graph, adapter, ...)`. They consume the plan, apply answers, then run the existing dimension computations (`_compute_volume`, `_compute_freshness`, etc.) against the resolved inputs.
- `_compute_volume` becomes a pure function over `(adapter, table_fqn, timestamp_column)` — no clarification side effects, no `tentative` flag.
- Add `analyze_sla_bulk` and `compute_sla_bulk` mirroring the existing `discover_sla_profiles_bulk` semaphore-controlled concurrency.
- `discover_sla_direct`, `discover_sla_profile`, `discover_sla_profiles_bulk` stay during the rollout window (see §10) as thin wrappers that call `analyze_sla` then `compute_sla` with empty answers — so any unaudited caller doesn't break. They are deleted in the follow-up cleanup deploy.

### 8.2 `scanner/api/routers/discovery.py`

- Replace the existing `/discovery/direct`, `/discovery/node`, `/discovery/direct-bulk`, `/discovery/bulk` endpoints with `/discovery/analyze`, `/discovery/compute`, `/discovery/analyze-bulk`, `/discovery/compute-bulk`.
- The compute endpoints accept `plan` and `answers` in the request body. Validation: `plan.table_fqn` must match the URL nodeId's resolved FQN; reject mismatched plans (defence against tampering or stale frontend state).

### 8.3 `scanner/lineage/sla_discovery_listeners.py`

- Delete the file. The `context_resolved` listener is no longer needed — phase 2 is frontend-driven.

### 8.4 `scanner/copilot/clarifications/emit.py`

- No changes needed. The function is still the right boundary for "create a ContextRequest from the scanner side." Only its caller moves.

## 9. Frontend changes (TypeScript)

### 9.1 Routes

- `app/api/nodes/[nodeId]/sla/discover/route.ts` → split into `analyze/route.ts` and `compute/route.ts` under the same `[nodeId]/sla/discover/` path.
- `app/api/nodes/sla/discover-bulk/route.ts` → split into `analyze/route.ts` and `compute/route.ts` under `discover-bulk/`.
- Each route proxies to its FastAPI counterpart with the existing auth + tenant scoping.

### 9.2 `components/lineage/DataAssetDetailPanel.tsx`

- Replace the single `handleDiscover` with `handleAnalyze` (fires phase 1) and `handleCompute` (fires phase 2). The state machine in §7 drives transitions.
- Remove all references to `discoveryResult.volume.tentative` and `discoveryResult.volume.context_request_id`. They cannot occur after this change.
- Add the `awaiting_clarifications` view: a compact card showing "Pallisade needs your input on N column choice(s)" with a button that opens the clarification popup pre-scrolled to the first relevant request.

### 9.3 `components/clarifications/ClarificationProvider.tsx`

- Add `useClarificationsResolved(ids: string[], onAllResolved: (answers) => void)` hook.
- Internal: the provider already has the requests + their statuses. The hook is a thin filter + effect.

### 9.4 Bulk discovery UI

- The existing bulk discovery affordance fires `analyze-bulk` first. Nodes that come back `ready` start computing in parallel. Nodes that come back `awaiting_clarifications` queue into a "N nodes need input" banner the user works through. As each node's clarifications resolve, its `compute` fires.
- Show progress: "Computing 8 of 21 · 3 awaiting input · 10 ready."

## 10. Migration

No DB migration. Code change only.

Deployment order matters: if FastAPI ships the new endpoints first but Next.js still calls the old paths, discovery breaks. Sequence: FastAPI keeps the old endpoints alongside the new ones for one deploy, Next.js cuts over, then the old endpoints are deleted in the next release. Mark old endpoints `@deprecated` with logs to confirm zero hits before deletion.

The frontend `tentative` rendering code is removed in the same PR as the route swap — it becomes unreachable since the new compute response never sets `tentative`.

## 11. Testing

### 11.1 Backend unit tests (pytest)

`scanner/tests/lineage/test_sla_discovery.py`:

- `analyze_sla` returns `status="ready"` and empty `clarification_ids` when timestamp picker confidence ≥ threshold.
- `analyze_sla` returns `status="awaiting_clarifications"` with one id when picker confidence < threshold; verify the ContextRequest was created (via mocked emit or test double).
- `analyze_sla` produces the same plan for the same input table (determinism, supports re-click idempotency).
- `compute_sla` with empty `answers` uses `plan.volume_timestamp_pick.column`.
- `compute_sla` with `answers={request_id: {column: "alt_col"}}` uses `alt_col` over the picker's choice.
- `compute_sla` rejects an `answers` key that doesn't correspond to a clarification in the plan (treat as misuse; raise).
- `_compute_volume` no longer imports or calls `_try_emit_timestamp_clarification` — verified by a static grep test in the suite (or absence of the import statement at module load).

### 11.2 Backend integration tests

`scanner/tests/api/test_discovery_router.py` (per project memory: use `app.dependency_overrides`):

- End-to-end happy path with a confident pick: POST `/analyze` → status ready → POST `/compute` → DiscoveryResult complete.
- End-to-end with ambiguity: POST `/analyze` → status awaiting + 1 clarification → resolve the ContextRequest via the existing endpoint → POST `/compute` with answers → DiscoveryResult uses the user's column.
- Bulk: 3 nodes, 2 confident + 1 ambiguous; analyze-bulk returns mixed statuses; compute the confident two, resolve clarification, compute the third.
- Plan tampering: compute with a plan whose `table_fqn` doesn't match the URL is rejected (400).

### 11.3 Frontend tests

`components/lineage/__tests__/DataAssetDetailPanel.test.tsx`:

- State machine transitions cover idle → analyzing → computing → confirm (happy path).
- idle → analyzing → awaiting_clarifications → (mock ClarificationProvider firing) → computing → confirm.
- `awaiting_clarifications` view does not render any SLA result fields.
- Bulk panel: mixed-status banner renders correct counts.

## 12. Open questions

(None require resolution before implementation. Items below are flagged for future passes.)

- Should `compute_sla` results be persisted before the user clicks Apply, so closing the panel does not lose them? Today they aren't; that question is independent of two-phase. Defer to the artefact-registry work, where `ArtifactKind.SLA_DISCOVERY` naturally provides this.
- Should `analyze_sla` emit clarifications for other dimensions (e.g. ambiguous primary key for uniqueness) the way it does for volume's timestamp column? Out of scope for v1 — only `timestamp_choice` exists today. The phase split makes adding more emissions trivial later: they all go in `analyze`, all answers flow through `compute`.

## 13. Rollout

- Feature flag: none. The change is a strict improvement and the new endpoint set is the only path after the cutover.
- Observability: keep the `[Clarifications]` logger calls in `analyze_sla`. Add `[Discovery] phase=analyze` / `phase=compute` log lines with table FQN + clarification count, so the analyze→compute correspondence is auditable.
- Failure mode: if `compute` is called with a plan whose ContextRequests have been deleted (rare; manual DB ops), the answers map is empty for those ids and `compute_sla` falls back to `plan.volume_timestamp_pick.column`. The user sees the picker's guess — same as today, but at least no false claim of "you confirmed this."
