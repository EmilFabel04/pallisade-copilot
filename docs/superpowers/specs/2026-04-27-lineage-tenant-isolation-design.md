# Lineage Cache Tenant Isolation

**Date:** 2026-04-27
**Status:** Draft (pending user approval)
**Related:** `scanner/api/routers/lineage.py`, `scanner/api/routers/discovery.py`, `scanner/api/auth.py`

## Problem

`scanner/api/routers/lineage.py` keeps four in-memory caches that hold per-tenant lineage state:

- `_engine_stores: dict[str, GraphStore]` — resolved lineage graphs per stack
- `_engine_collected_results_map: dict[str, {nodes, edges, dbt_manifest, dbt_config, schema_mapping}]` — adapter outputs accumulated before resolution
- `_engine_tool_configs_map: dict[str, dict]` — cached tool configs used by SLA discovery
- `_run_registries: dict[str, RunRegistry]` — control-plane runs per stack

All four caches are keyed by `stack_id` only. Two failure modes:

### Failure 1 — Mutable process-global `_current_stack_id`

`_current_stack_id: str = "default"` (lineage.py:1050) is a module-level mutable string. `engine_clear_cache` writes to it as a side effect (lineage.py:1258-1260). Several extraction code paths read it through `_CollectedResultsProxy` (lineage.py:1061-1070) instead of taking `stack_id` explicitly. With concurrent traffic from multiple tenants:

- Org A calls `engine/clear-cache?stack_id=A` → process-wide `_current_stack_id = "A"`.
- Org B calls `extract-llm` (or any extraction route that uses the proxy) before its own clear-cache → write goes into bucket `"A"`.
- Org A's next read at `stack_id=A` returns Org B's data.

This is a process-wide race. The bug is independent of which extraction endpoint triggers it.

### Failure 2 — `stack_id` not bound to the caller's organization

Every read endpoint accepts `stack_id` as a query parameter and looks up the corresponding cache bucket without checking that the bucket belongs to the caller's organization. If two organizations happen to use the same `stack_id` value (or one organization can enumerate another's), the caches collide. Today, `stack_id` is a frontend-supplied opaque string with no server-side ownership enforcement.

## Goals

1. Eliminate cross-tenant reads and writes against the four lineage caches.
2. Keep the existing multi-pipeline-per-organization workflow (a single org can hold multiple `stack_id` values).
3. Make tenant isolation a property of the cache key, not a property of an authorization check that a future endpoint could forget to call.

## Non-goals

- Rewriting the OpenLineage push endpoints to support external machine-to-machine auth (separate PR).
- Persisting lineage caches to durable storage. Caches stay in-memory; restart still wipes them.
- Adding a `stack_id` ownership table. The compound cache key plus the authenticated `org_id` is sufficient for isolation.
- Touching the four `HIGH` severity auth-audit findings in `drift.py`, `schedule.py`, `policies.py`, `copilot.py`. Those are a separate PR.

## Approach

### Compound key derived from authenticated principal

All four cache helpers move from a single-string key to a compound `(org_id, stack_id)` key, joined as `f"{org_id}:{stack_id}"` for use in the existing `dict` maps (no schema migration needed — the maps are in-memory dicts).

- `org_id` always comes from `request.state.principal.organization_id`. It is **never** read from query params, body fields, or headers other than those set by `ActingPrincipalMiddleware`.
- `stack_id` continues to come from the existing query parameter, defaulting to `"default"` when absent. With the org prefix in front of it, two organizations using `"default"` (or any other identical value) cannot collide.

The mutable `_current_stack_id` global and the `_CollectedResultsProxy` are deleted. Every code path that touches a cache must take `org_id` and `stack_id` as explicit arguments.

### Endpoints in scope

These are the live endpoints (have a Next.js caller, internal caller, or test):

**Writers / mutators:**
- `POST /lineage/engine/clear-cache`
- `POST /lineage/engine/build`
- `POST /lineage/engine/restore`
- `POST /lineage/engine/reconcile`
- `POST /lineage/engine/reconcile/apply`
- `POST /lineage/investigate-llm`
- `POST /lineage/extract-llm`

**Readers:**
- `GET /lineage/engine/stats`, `/snapshot`, `/graph`, `/search`, `/auto-anchor`, `/export`
- `GET /lineage/engine/upstream/{id}`, `/downstream/{id}`, `/blast-radius/{id}`, `/recommend-monitors/{id}`, `/explain-edge/{id}`, `/cross-links/{id}`, `/run-history/{id}`
- `GET /lineage/engine/control-plane[/{dag_id}]`, `/control-plane-overview`
- `GET /lineage/engine/views/pipeline-overview`, `/views/lane-pipeline-overview`, `/views/data-plane`, `/views/tool-details/{id}`
- `GET /lineage/engine/data-plane/neighbors/{id}`
- `GET /lineage/engine/reconcile/diagnostics`
- `GET /lineage/runs/current`, `/runs/{id}/status`, `/runs/{id}/views/{type}`, `/runs`
- `POST /api/v1/discovery/node`, `POST /api/v1/discovery/bulk` (in `scanner/api/routers/discovery.py`) — both read `_get_engine_store` and `_engine_tool_configs_map`. The other two discovery endpoints (`/discovery/direct`, `/discovery/direct-bulk`) take credentials in the request body and do not touch the lineage cache, so they are not affected by this leak.

Every active endpoint above gains `Depends(require_principal)` and uses the principal's `organization_id` as the outer cache key.

### Endpoints deleted

Routes with no Next.js caller, no internal caller, and no test coverage. Removing them shrinks the attack surface and removes paths that would otherwise need defensive isolation work without any production user.

- `POST /lineage/extract` (lineage.py:100) — superseded by `extract-llm`
- `POST /lineage/extract-tool` (lineage.py:2493) — generic adapter dispatch, never wired up
- `POST /lineage/extract-unified` (lineage.py:755)
- `POST /lineage/investigate` (lineage.py:2839) — superseded by `investigate-llm`
- `GET /lineage/node/{node_id}` (lineage.py:681)
- `GET /lineage/engine/producers` (lineage.py:1718)
- `POST /lineage/engine/watches/scope` (lineage.py:3244)
- `GET /lineage/engine/watches/infer-type/{asset_id}` (lineage.py:3288)
- `POST /lineage/engine/watches/compute-health` (lineage.py:3317)

If any of these is later needed, `git revert` of the deletion commit restores it; the revived code will have to be re-wired with the new `(org_id, stack_id)` keying.

### Endpoints deferred

- `POST /lineage/openlineage/event` (lineage.py:2391)
- `POST /lineage/openlineage/events` (lineage.py:2431)

These are intentional machine-to-machine ingress points (Airflow OL emitter, dbt-OL, Spark OL listener). They currently 400 on every caller because external producers don't carry `X-Acting-User` / `X-Acting-Org`. Their real fix is API-key or signed-token auth plus an `organization_id` derived from that key — a different design problem from the in-memory cache leak. They are left untouched in this PR and tracked as a follow-up.

### Helper changes

The four cache helpers are rewritten to take `org_id` and `stack_id` as explicit arguments and to compose the compound key internally. Callers cannot accidentally fall back to a process-wide default.

```python
def _cache_key(org_id: str, stack_id: str | None) -> str:
    return f"{org_id}:{stack_id or 'default'}"

def _get_engine_store(org_id: str, stack_id: str | None) -> GraphStore:
    key = _cache_key(org_id, stack_id)
    if key not in _engine_stores:
        _engine_stores[key] = GraphStore()
    return _engine_stores[key]

def _get_collected_results(org_id: str, stack_id: str | None) -> dict:
    key = _cache_key(org_id, stack_id)
    if key not in _engine_collected_results_map:
        _engine_collected_results_map[key] = _EMPTY_COLLECTED()
    return _engine_collected_results_map[key]

def _get_run_registry(org_id: str, stack_id: str | None) -> RunRegistry:
    key = _cache_key(org_id, stack_id)
    if key not in _run_registries:
        _run_registries[key] = RunRegistry()
    return _run_registries[key]

def _clear_engine_cache(org_id: str, stack_id: str | None) -> None:
    key = _cache_key(org_id, stack_id)
    _engine_collected_results_map[key] = _EMPTY_COLLECTED()
```

`_engine_tool_configs_map` is read directly in `lineage.py:3067` and `discovery.py:173,252`. All three sites switch to the same `_cache_key(org_id, stack_id)` form.

`_rebuild_engine_from_cache` becomes `_rebuild_engine_from_cache(org_id, stack_id)` — no more global lookup.

### Endpoint changes

Each active endpoint adds:

```python
from ..auth import require_principal, ActingPrincipal

@router.get("/lineage/engine/upstream/{asset_id}")
async def engine_upstream(
    asset_id: str,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    store = _get_engine_store(principal.organization_id, stack_id)
    ...
```

`investigate-llm` and `extract-llm` are the two big writer paths. Inside the per-tool extraction loops, the existing `_engine_collected_results["nodes"].extend(...)` calls become `_get_collected_results(org_id, stack_id)["nodes"].extend(...)`. The proxy goes away.

`engine/clear-cache` no longer mutates a global. It clears the bucket for the caller's `(org_id, stack_id)` only.

### `discovery.py` changes

Two endpoints (`/api/v1/discovery/node`, `/api/v1/discovery/bulk`) currently import `_get_engine_store` and `_engine_tool_configs_map` and use a `cache_key = stack_id or "default"` (lines 119, 172-173, 236, 251-252) that maps to the legacy `stack_id`-only scheme. They gain `Depends(require_principal)` and pass `principal.organization_id` through the same helper changes.

The two `direct` endpoints (`/discovery/direct`, `/discovery/direct-bulk`) take credentials in the request body and never read the lineage caches, so they are unchanged by this PR.

## Data flow after the change

```
Browser → Next.js proxy
       → adds X-Acting-User, X-Acting-Org via existing scannerClient
       → FastAPI /api/v1/lineage/...
       → ActingPrincipalMiddleware sets request.state.principal
       → endpoint reads principal via Depends(require_principal)
       → cache key = f"{principal.organization_id}:{stack_id or 'default'}"
       → returns or mutates only that bucket
```

A request that arrives without principal headers is already rejected (HTTP 400) by `ActingPrincipalMiddleware` before reaching the endpoint, so cache helpers never need to defend against a missing `org_id`.

## Testing

1. **Helper unit tests** for `_cache_key`, `_get_engine_store`, `_get_collected_results`, `_get_run_registry`, `_clear_engine_cache`. Verify two distinct `org_id` values with the same `stack_id` produce isolated state.
2. **Endpoint isolation tests** — for each writer/reader pair, simulate two principals (Org A and Org B) and assert one cannot read the other's data even when supplying the same `stack_id`. The header-minting pattern from `scanner/api/tests/test_auth.py` (`X-Internal-Auth` + `X-Acting-User` + `X-Acting-Org`) is reused; the implementation plan will decide whether to extract these into a `conftest.py` fixture or keep inline.
3. **Race regression test** — interleave `engine/clear-cache` from one principal with `extract-llm` from a second principal. Assert the second principal's data lands in the second principal's bucket and the first principal's bucket remains untouched. This covers the `_current_stack_id` failure mode after the global is removed.
4. **Existing test suites** for the touched routes must still pass.

## Rollout

In-memory caches reset on process restart. Deploy is a clean cut: the new code starts with empty `_engine_stores`/etc., the next request from each tenant repopulates its own bucket. No data migration. No feature flag.

## Out of scope (acknowledged)

- Auth gaps in `drift.py`, `schedule.py`, `policies.py`, `copilot.py` — separate PR.
- OpenLineage push-endpoint auth redesign — separate PR.
- Persistence layer for the four caches — caches remain in-memory.
- Adding a `stack_id`-ownership table.

## Open questions

None at time of writing.
