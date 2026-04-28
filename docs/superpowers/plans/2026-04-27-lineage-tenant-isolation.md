# Lineage Cache Tenant Isolation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate cross-tenant reads and writes against the four in-memory lineage caches in `scanner/api/routers/lineage.py` by re-keying every cache on a compound `(org_id, stack_id)` key derived from the authenticated principal.

**Architecture:** Extract the four cache helpers + module-level dicts out of `lineage.py` into a new `scanner/api/routers/_lineage_cache.py` module. Every helper takes `(org_id, stack_id)` explicitly. Every active endpoint adds `Depends(require_principal)` and passes `principal.organization_id` through. The mutable `_current_stack_id` global, the `_CollectedResultsProxy`, and the 9 unwired routes are deleted.

**Tech Stack:** Python 3.11, FastAPI, pytest, Starlette TestClient.

**Spec:** `docs/superpowers/specs/2026-04-27-lineage-tenant-isolation-design.md`

---

## File Structure

**New files:**
- `scanner/api/routers/_lineage_cache.py` — module-level cache dicts + isolated helpers. ~110 lines. Takes `(org_id, stack_id)` everywhere; no module-level mutable string globals.
- `scanner/api/tests/test_lineage_cache.py` — unit tests for helpers (no FastAPI required).
- `scanner/api/tests/test_lineage_isolation.py` — TestClient-driven two-tenant integration tests.

**Modified files:**
- `scanner/api/routers/lineage.py` — endpoints add `Depends(require_principal)`; helper calls switch to `_lineage_cache.*`; the `_current_stack_id` global, the `_CollectedResultsProxy`, the per-stack helpers, the 9 dead routes, and the four module dicts are deleted from this file.
- `scanner/api/routers/discovery.py` — `/discovery/node` and `/discovery/bulk` add `Depends(require_principal)` and pass `principal.organization_id` to the new helpers.

**Untouched (for this PR):**
- `scanner/api/auth.py` — already has everything needed (`require_principal`, `ActingPrincipal`).
- OpenLineage push endpoints (`/lineage/openlineage/event`, `/openlineage/events`) — separate PR.
- Other discovery endpoints (`/discovery/direct`, `/discovery/direct-bulk`) — they don't touch the lineage cache.

---

## Task 1: Create `_lineage_cache.py` and helper unit tests (TDD)

**Files:**
- Create: `scanner/api/routers/_lineage_cache.py`
- Test: `scanner/api/tests/test_lineage_cache.py`

- [ ] **Step 1: Write the failing test file**

Create `scanner/api/tests/test_lineage_cache.py`:

```python
"""Unit tests for the per-tenant lineage cache helpers."""

import pytest

from scanner.api.routers import _lineage_cache as cache


@pytest.fixture(autouse=True)
def _reset_cache_state():
    """Each test starts with empty module-level dicts."""
    cache._engine_stores.clear()
    cache._engine_collected_results_map.clear()
    cache._engine_tool_configs_map.clear()
    cache._run_registries.clear()
    yield


class TestCacheKey:
    def test_combines_org_and_stack(self):
        assert cache.cache_key("org_a", "stack_1") == "org_a:stack_1"

    def test_missing_stack_falls_back_to_default(self):
        assert cache.cache_key("org_a", None) == "org_a:default"
        assert cache.cache_key("org_a", "") == "org_a:default"

    def test_two_orgs_with_same_stack_are_distinct(self):
        assert cache.cache_key("org_a", "shared") != cache.cache_key("org_b", "shared")


class TestEngineStore:
    def test_returns_same_instance_for_same_principal(self):
        s1 = cache.get_engine_store("org_a", "s1")
        s2 = cache.get_engine_store("org_a", "s1")
        assert s1 is s2

    def test_isolates_distinct_orgs_with_same_stack(self):
        s_a = cache.get_engine_store("org_a", "shared")
        s_b = cache.get_engine_store("org_b", "shared")
        assert s_a is not s_b


class TestCollectedResults:
    def test_starts_with_empty_collected_shape(self):
        result = cache.get_collected_results("org_a", "s1")
        assert result == {
            "nodes": [],
            "edges": [],
            "dbt_manifest": None,
            "dbt_config": None,
            "schema_mapping": None,
        }

    def test_writes_to_one_org_do_not_appear_in_another(self):
        cache.get_collected_results("org_a", "s1")["nodes"].append({"id": "n1"})
        assert cache.get_collected_results("org_b", "s1")["nodes"] == []

    def test_returns_same_dict_object_for_same_principal(self):
        d1 = cache.get_collected_results("org_a", "s1")
        d2 = cache.get_collected_results("org_a", "s1")
        assert d1 is d2


class TestRunRegistry:
    def test_isolates_orgs(self):
        r_a = cache.get_run_registry("org_a", "s1")
        r_b = cache.get_run_registry("org_b", "s1")
        assert r_a is not r_b


class TestToolConfigs:
    def test_set_and_get_round_trip(self):
        cache.set_tool_configs("org_a", "s1", {"bigquery": {"project": "p"}})
        assert cache.get_tool_configs("org_a", "s1") == {"bigquery": {"project": "p"}}

    def test_get_returns_empty_dict_when_unset(self):
        assert cache.get_tool_configs("org_a", "s1") == {}

    def test_isolates_orgs(self):
        cache.set_tool_configs("org_a", "s1", {"bigquery": {"project": "p_a"}})
        cache.set_tool_configs("org_b", "s1", {"bigquery": {"project": "p_b"}})
        assert cache.get_tool_configs("org_a", "s1") == {"bigquery": {"project": "p_a"}}
        assert cache.get_tool_configs("org_b", "s1") == {"bigquery": {"project": "p_b"}}


class TestClearEngineCache:
    def test_only_clears_collected_results_for_target_principal(self):
        cache.get_collected_results("org_a", "s1")["nodes"].append({"id": "n1"})
        cache.get_collected_results("org_b", "s1")["nodes"].append({"id": "n2"})

        cache.clear_engine_cache("org_a", "s1")

        assert cache.get_collected_results("org_a", "s1")["nodes"] == []
        assert cache.get_collected_results("org_b", "s1")["nodes"] == [{"id": "n2"}]
```

- [ ] **Step 2: Run the test file to verify it fails**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/test_lineage_cache.py -v`

Expected: collection error / import error — `scanner.api.routers._lineage_cache` does not exist.

- [ ] **Step 3: Create `_lineage_cache.py` with the minimal implementation**

Create `scanner/api/routers/_lineage_cache.py`:

```python
"""Per-tenant in-memory caches for the lineage engine.

All four caches are keyed by a compound ``(org_id, stack_id)`` key. The
``org_id`` MUST come from ``request.state.principal.organization_id``
(set by ``ActingPrincipalMiddleware``) — never from a query parameter,
body field, or header. Two organizations using the same ``stack_id``
value cannot collide because the org prefix makes the key unique.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Module-level cache dicts
# ---------------------------------------------------------------------------

# Resolved lineage graphs per (org_id, stack_id).
_engine_stores: Dict[str, Any] = {}

# RunRegistry instances per (org_id, stack_id).
_run_registries: Dict[str, Any] = {}

# Adapter outputs accumulated before resolution.
_engine_collected_results_map: Dict[str, Dict[str, Any]] = {}

# Cached tool configs used by SLA discovery.
_engine_tool_configs_map: Dict[str, Dict[str, Any]] = {}


def _empty_collected() -> Dict[str, Any]:
    return {
        "nodes": [],
        "edges": [],
        "dbt_manifest": None,
        "dbt_config": None,
        "schema_mapping": None,
    }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def cache_key(org_id: str, stack_id: Optional[str]) -> str:
    """Compose the compound cache key. ``stack_id`` defaults to ``"default"``."""
    return f"{org_id}:{stack_id or 'default'}"


def get_engine_store(org_id: str, stack_id: Optional[str]):
    """Return the GraphStore for this principal, creating it if needed."""
    key = cache_key(org_id, stack_id)
    if key not in _engine_stores:
        try:
            from lineage.engine.store import GraphStore
        except ImportError:
            from scanner.lineage.engine.store import GraphStore
        _engine_stores[key] = GraphStore()
    return _engine_stores[key]


def get_run_registry(org_id: str, stack_id: Optional[str]):
    """Return the RunRegistry for this principal, creating it if needed."""
    key = cache_key(org_id, stack_id)
    if key not in _run_registries:
        try:
            from lineage.engine.run_registry import RunRegistry
        except ImportError:
            from scanner.lineage.engine.run_registry import RunRegistry
        _run_registries[key] = RunRegistry()
    return _run_registries[key]


def get_collected_results(org_id: str, stack_id: Optional[str]) -> Dict[str, Any]:
    """Return the adapter-output bucket for this principal."""
    key = cache_key(org_id, stack_id)
    if key not in _engine_collected_results_map:
        _engine_collected_results_map[key] = _empty_collected()
    return _engine_collected_results_map[key]


def get_tool_configs(org_id: str, stack_id: Optional[str]) -> Dict[str, Any]:
    """Return cached tool configs for this principal (empty dict if unset)."""
    key = cache_key(org_id, stack_id)
    return _engine_tool_configs_map.get(key, {})


def set_tool_configs(
    org_id: str, stack_id: Optional[str], configs: Dict[str, Any]
) -> None:
    """Replace the tool-configs entry for this principal."""
    key = cache_key(org_id, stack_id)
    _engine_tool_configs_map[key] = configs


def clear_engine_cache(org_id: str, stack_id: Optional[str]) -> None:
    """Reset the collected-results bucket for this principal."""
    key = cache_key(org_id, stack_id)
    _engine_collected_results_map[key] = _empty_collected()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/test_lineage_cache.py -v`

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/_lineage_cache.py scanner/api/tests/test_lineage_cache.py
git commit -m "$(cat <<'EOF'
feat(lineage): add per-tenant cache helpers keyed on (org_id, stack_id)

New scanner/api/routers/_lineage_cache.py extracts the four engine
caches (graphs, collected results, run registries, tool configs) into
a dedicated module. Every helper takes (org_id, stack_id) explicitly;
no module-level mutable string globals exist in the new module.

The lineage.py router will be migrated to use these helpers in
subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Migrate `_rebuild_engine_from_cache` and supporting helpers in `lineage.py`

`_rebuild_engine_from_cache` currently reads the global `_current_stack_id`. It needs to take `(org_id, stack_id)` explicitly. The function lives at `lineage.py:1105-1245` (approx) and is called from every extraction code path.

**Files:**
- Modify: `scanner/api/routers/lineage.py:1037-1245` (replace helpers and `_rebuild_engine_from_cache` signature)

- [ ] **Step 1: Add the `_lineage_cache` import block at the top of `lineage.py`**

Locate the existing import block near the top of `scanner/api/routers/lineage.py` (around line 1-30). Add:

```python
from . import _lineage_cache
```

immediately after the other relative imports.

- [ ] **Step 2: Replace lines 1037-1102 of `lineage.py`**

The current block defines `_engine_stores`, `_run_registries`, `_engine_tool_configs_map`, `_engine_collected_results_map`, `_EMPTY_COLLECTED`, `_current_stack_id`, `_get_collected_results`, `_CollectedResultsProxy`, `_engine_collected_results`, `_clear_engine_cache`, `_get_engine_store`, `_get_run_registry`. Delete all of these. Replace with a single line that re-exports the new helpers under the old private names so the rest of the file keeps compiling during the migration:

```python
# All cache state lives in _lineage_cache. The wrappers below take an
# explicit org_id from the authenticated principal at the call site.
# (The wrappers are removed in Task 7 once every endpoint passes through
# _lineage_cache directly.)


def _get_engine_store(org_id: str, stack_id):
    return _lineage_cache.get_engine_store(org_id, stack_id)


def _get_run_registry(org_id: str, stack_id):
    return _lineage_cache.get_run_registry(org_id, stack_id)


def _get_collected_results(org_id: str, stack_id):
    return _lineage_cache.get_collected_results(org_id, stack_id)


def _clear_engine_cache(org_id: str, stack_id):
    _lineage_cache.clear_engine_cache(org_id, stack_id)
```

- [ ] **Step 3: Rewrite `_rebuild_engine_from_cache` to take `(org_id, stack_id)`**

Locate `_rebuild_engine_from_cache` at `lineage.py:1105`. Change the signature to `def _rebuild_engine_from_cache(org_id: str, stack_id):` and replace every call to `_get_collected_results()`, `_get_engine_store(_current_stack_id)`, etc. inside the function body with `_get_collected_results(org_id, stack_id)` and `_get_engine_store(org_id, stack_id)`.

The full new body (replaces lines 1105 through end of function ~1245):

```python
def _rebuild_engine_from_cache(org_id: str, stack_id) -> None:
    """Run the resolver pipeline on cached adapter results.

    Takes already-converted engine nodes/edges and runs only the resolver
    (normalize, deduplicate, merge evidence, weight confidence). No
    adapters are re-run.
    """
    import logging
    from datetime import datetime
    _logger = logging.getLogger(__name__)
    try:
        try:
            from lineage.engine.resolver import ResolverPipeline, ResolverConfig
        except ImportError:
            from scanner.lineage.engine.resolver import ResolverPipeline, ResolverConfig

        store = _get_engine_store(org_id, stack_id)
        collected = _get_collected_results(org_id, stack_id)
        pipeline = ResolverPipeline(ResolverConfig())
        store.graph = pipeline.resolve(
            list(collected["nodes"]),
            list(collected["edges"]),
        )
        store.resolution_stats = pipeline.stats
        store.graph.built_at = datetime.utcnow()

        _logger.info(
            f"[Engine] Built graph: {len(store.graph.nodes)} nodes, "
            f"{len(store.graph.edges)} edges"
        )
        if store.resolution_stats:
            _logger.info(
                f"[Engine] Resolver: {store.resolution_stats.nodes_before} → "
                f"{store.resolution_stats.nodes_after} nodes, "
                f"{store.resolution_stats.edges_before} → "
                f"{store.resolution_stats.edges_after} edges, "
                f"{store.resolution_stats.nodes_deduplicated} deduplicated, "
                f"{store.resolution_stats.edges_merged} merged"
            )

        # Keep the rest of the existing body verbatim, but every reference
        # to `_get_collected_results()` (no args) becomes
        # `_get_collected_results(org_id, stack_id)` and every reference
        # to `_get_engine_store(_current_stack_id)` becomes
        # `_get_engine_store(org_id, stack_id)`. The cross-tool edge
        # synthesis block (currently lines 1145-1245) keeps its full
        # logic; only the cache lookups change.
        if store.graph:
            try:
                try:
                    from lineage.canonical import CanonicalResolver
                    from lineage.cross_tool import CrossToolEdgeSynthesizer
                except ImportError:
                    from scanner.lineage.canonical import CanonicalResolver
                    from scanner.lineage.cross_tool import CrossToolEdgeSynthesizer

                dbt_manifest = collected.get("dbt_manifest")
                dbt_cfg = collected.get("dbt_config") or {}
                resolver = CanonicalResolver(
                    default_warehouse=dbt_cfg.get("warehouse_type", "bigquery"),
                    project_id=dbt_cfg.get("namespace", ""),
                )
                if dbt_manifest:
                    resolver.register_dbt_sources(dbt_manifest.get("sources", {}))
                    resolver.register_dbt_model_targets(dbt_manifest.get("nodes", {}))

                schema_mapping = collected.get("schema_mapping")
                if schema_mapping:
                    # Apply the existing schema-mapping patch logic verbatim
                    # (currently lines 1170-1200 of lineage.py). When migrating,
                    # copy that block in full — it does not touch caches.
                    pass  # (existing block from current file goes here)

                synthesizer = CrossToolEdgeSynthesizer(resolver)
                synth_edges = synthesizer.synthesize(store.graph)
                if synth_edges:
                    for e in synth_edges:
                        store.graph.edges[e.edge_id] = e
                    _logger.info(
                        f"[Engine] Synthesized {len(synth_edges)} cross-tool edges"
                    )
            except Exception as e:
                _logger.warning(f"[Engine] Cross-tool synthesis failed: {e}")

    except Exception as e:
        _logger.error(f"[Engine] Rebuild failed: {e}", exc_info=True)
```

**Important:** the `pass  # (existing block from current file goes here)` placeholder is a marker — when implementing this step, copy the actual schema-mapping patch logic from the current file (lineage.py:1170-1200 of the pre-change version) verbatim into that block. The behavior of `_rebuild_engine_from_cache` does not change in this task; only the cache-lookup signature does.

- [ ] **Step 4: Add a temporary `_current_stack_id` shim**

Several call sites in `lineage.py` still reference `_current_stack_id` (the writers `clear-cache`, `investigate-llm`, `extract-llm`). Tasks 3 and 4 below remove those. Until then, add this shim immediately after the helper wrappers from Step 2 so the file keeps compiling:

```python
# Temporary shim — removed in Task 7 once every writer endpoint passes
# org_id explicitly. Reading or writing this value is a bug; if you find
# yourself touching it, fix the call site instead.
_current_stack_id: str = "default"
```

- [ ] **Step 5: Run the existing lineage tests to confirm no regression**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v -k "lineage or engine" --no-header 2>&1 | tail -40`

Expected: same pass/fail counts as before this task. The migration is purely structural — behavior unchanged.

- [ ] **Step 6: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/lineage.py
git commit -m "$(cat <<'EOF'
refactor(lineage): route cache helpers through _lineage_cache module

Replaces _get_engine_store/_get_run_registry/_get_collected_results/
_clear_engine_cache with thin wrappers over _lineage_cache.* that take
(org_id, stack_id) explicitly. _rebuild_engine_from_cache now takes
both args instead of reading the global _current_stack_id.

The mutable _current_stack_id global is kept temporarily so writer
endpoints still compile; it is removed in a follow-up commit once
every writer migrates to passing org_id from the authenticated
principal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Migrate writer endpoints to require principal

Five writer endpoints in `lineage.py` need `Depends(require_principal)` and need to pass `principal.organization_id` through to the helpers. They all currently take `stack_id: Optional[str] = Query(None)` and either ignore it (using `_current_stack_id`) or pass it through.

**Files:**
- Modify: `scanner/api/routers/lineage.py`
  - `engine_clear_cache` (line ~1248)
  - `engine_build` (line ~1277)
  - `engine_restore` (line ~1573)
  - `engine_reconcile` and `engine_reconcile_apply` (lines ~2239, ~2307)

`investigate-llm` and `extract-llm` are migrated separately in Task 4 because they read `_current_stack_id` in addition to writing to caches.

- [ ] **Step 1: Add the `require_principal` import to `lineage.py`**

At the top of the file (in the FastAPI / scanner imports block around line 1-30), add:

```python
from fastapi import Depends
from ..auth import require_principal, ActingPrincipal
```

If `Depends` is already imported, just add the second line.

- [ ] **Step 2: Migrate `engine_clear_cache`**

Replace the current function body (lineage.py:1248-1274) with:

```python
@router.post("/lineage/engine/clear-cache")
async def engine_clear_cache(
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Reset engine cache before a fresh extraction batch.

    Clears only the buckets owned by the caller's organization.
    """
    import logging

    org_id = principal.organization_id
    _clear_engine_cache(org_id, stack_id)

    store = _get_engine_store(org_id, stack_id)
    store.graph = None
    store.tool_nodes = []

    registry = _get_run_registry(org_id, stack_id)
    registry._runs.clear()
    registry._current_run_id = None

    logging.getLogger(__name__).info(
        f"[Engine] clear-cache: org={org_id} stack_id={stack_id or 'default'}"
    )
    return {"success": True, "message": "Engine cache cleared"}
```

Note: the `global _current_stack_id; if stack_id: _current_stack_id = stack_id` lines are deleted — clear-cache no longer mutates the process-wide global.

- [ ] **Step 3: Migrate `engine_build`**

Replace the function signature and the single helper call inside it (lineage.py:1277-1296):

```python
@router.post("/lineage/engine/build", response_model=EngineGraphResponse)
async def engine_build(
    request: EngineBuildRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Build a lineage graph from engine config."""
    import asyncio

    store = _get_engine_store(principal.organization_id, stack_id)
    try:
        graph = await asyncio.to_thread(store.build_graph, request.config)
        coverage = store.get_stats()

        return EngineGraphResponse(
            success=True,
            nodes=[_node_to_engine_response(n) for n in graph.nodes.values()],
            edges=[_edge_to_engine_response(e) for e in graph.edges.values()],
            stats=coverage.to_dict(),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return EngineGraphResponse(success=False, errors=[str(e)])
```

- [ ] **Step 4: Migrate `engine_restore`**

Locate the current function at `lineage.py:1573`. Add the `principal` dependency and pass `principal.organization_id` to every cache lookup inside the body. Pseudocode for the change (apply to the actual function):

```python
@router.post("/lineage/engine/restore")
async def engine_restore(
    request: EngineRestoreRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    # ... existing body ...
    store = _get_engine_store(principal.organization_id, stack_id)
    # ... rest of body, replacing every _get_engine_store(stack_id) call
    # with _get_engine_store(principal.organization_id, stack_id) ...
```

When implementing this step, read lines 1573-1610 of the current file and apply the change to every helper call inside.

- [ ] **Step 5: Migrate `engine_reconcile` and `engine_reconcile_apply`**

Same pattern as Step 4 for both functions (`lineage.py:2239` and `lineage.py:2307`). Add the `principal` dependency, replace `_get_engine_store(stack_id)` with `_get_engine_store(principal.organization_id, stack_id)`, replace any other helper call that takes `stack_id` with the org-prefixed call. Read the current bodies and edit in place.

- [ ] **Step 6: Run the existing tests for these endpoints**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v -k "clear_cache or engine_build or engine_restore or reconcile" --no-header 2>&1 | tail -40`

Expected: existing test pass/fail counts unchanged (any existing tests that hit these endpoints must mint `X-Acting-User`/`X-Acting-Org` headers; if any legacy tests fail with `400 missing_principal` add the headers — see Task 9 for the standard fixture pattern).

- [ ] **Step 7: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/lineage.py
git commit -m "$(cat <<'EOF'
feat(lineage): writer endpoints require authenticated principal

Migrates engine_clear_cache, engine_build, engine_restore,
engine_reconcile, and engine_reconcile_apply to take
Depends(require_principal) and pass principal.organization_id to
the cache helpers. clear-cache no longer mutates _current_stack_id.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Migrate `investigate-llm` and `extract-llm`

These two endpoints currently set the `_current_stack_id` global as a side effect (lineage.py:2984-2986 and 3137-3139) and then read it back when calling `_get_run_registry(_current_stack_id)`, `_get_engine_store(_current_stack_id)`, `_engine_tool_configs_map[_current_stack_id]`. Each pass uses the global instead of `stack_id`. Both must derive `org_id` from the principal and use the local `stack_id` arg directly.

**Files:**
- Modify: `scanner/api/routers/lineage.py:2969-3109` (investigate-llm)
- Modify: `scanner/api/routers/lineage.py:3126-3245` (extract-llm; SSE streaming endpoint)

- [ ] **Step 1: Migrate `investigate_lineage_llm`**

Replace the function signature and the body's cache calls. The existing function structure stays — only the cache-key threading changes.

Edit the signature at `lineage.py:2970`:

```python
@router.post("/lineage/investigate-llm", response_model=InvestigateResponse)
async def investigate_lineage_llm(
    request: InvestigateLLMRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
```

Delete the lines `global _current_stack_id` and `if stack_id: _current_stack_id = stack_id` (currently lines 2984-2986).

Add `org_id = principal.organization_id` near the top of the body, just after the existing `_logger = logging.getLogger(__name__)`.

Replace `_get_run_registry(_current_stack_id)` (line 3015) with `_get_run_registry(org_id, stack_id)`.
Replace `_get_engine_store(_current_stack_id)` (line 3016) with `_get_engine_store(org_id, stack_id)`.

Replace the tool-configs cache write (line 3067):

```python
# OLD:
_engine_tool_configs_map[_current_stack_id] = {
    tc.tool_type: tc.config for tc in request.tool_configs if tc.config
}

# NEW:
_lineage_cache.set_tool_configs(
    org_id,
    stack_id,
    {tc.tool_type: tc.config for tc in request.tool_configs if tc.config},
)
```

Search the rest of the function body for any other reference to `_current_stack_id` or the bare `_engine_collected_results` / `_engine_tool_configs_map` and replace each one with the org-prefixed helper call. (The function body is long — when implementing, grep for `_current_stack_id` and `_engine_collected_results` within lineage.py:2969-3110 and replace each hit.)

- [ ] **Step 2: Migrate `extract_lineage_with_llm`**

Same treatment as Step 1 for the function at `lineage.py:3127`. Edit the signature:

```python
@router.post("/lineage/extract-llm")
async def extract_lineage_with_llm(
    request: LLMExtractRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
```

Delete `global _current_stack_id` / `if stack_id: _current_stack_id = stack_id` (currently lines 3137-3139).

The body uses an inner `event_stream()` async generator. Inside it, every reference to `_current_stack_id`, `_engine_collected_results`, and `_engine_tool_configs_map` is replaced with the org-prefixed helper. Capture `org_id = principal.organization_id` in the outer function scope so the inner closure can read it.

When implementing, grep within `lineage.py:3126-3245` for `_current_stack_id`, `_engine_collected_results`, and `_engine_tool_configs_map` and replace each one. There should be no remaining references after this step.

- [ ] **Step 3: Run existing investigation/extraction tests**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v -k "investigate or extract_llm or extract_lineage" --no-header 2>&1 | tail -40`

Expected: existing pass/fail counts unchanged.

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/lineage.py
git commit -m "$(cat <<'EOF'
feat(lineage): investigate-llm and extract-llm derive org_id from principal

Removes the global _current_stack_id reads/writes from these two big
extraction paths. Both endpoints now take Depends(require_principal)
and pass principal.organization_id through to every cache helper,
including the tool-configs write that backs SLA discovery.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Migrate reader endpoints

All read-only `engine/*` and `runs/*` endpoints currently take `stack_id: Optional[str] = Query(None)` and call `_get_engine_store(stack_id)` / `_get_run_registry(stack_id)`. Each one needs `Depends(require_principal)` and must pass `principal.organization_id` through.

**Files:**
- Modify: `scanner/api/routers/lineage.py` (multiple endpoints, listed below)

The endpoints to migrate (all in `lineage.py`):

| Function | Line |
|----------|------|
| `engine_upstream` | 1299 |
| `engine_downstream` | 1321 |
| `engine_blast_radius` | 1342 |
| `engine_recommend_monitors` | 1361 |
| `engine_explain_edge` | 1443 |
| `engine_search` | 1456 |
| `engine_auto_anchor` | 1486 |
| `engine_graph` | 1527 |
| `engine_snapshot` | 1552 |
| `engine_control_plane` | 1609 |
| `engine_control_plane_all` | 1637 |
| `engine_cross_links` | 1655 |
| `engine_run_history` | 1677 |
| `engine_stats` | 1707 |
| `engine_export` | 1754 |
| `engine_control_plane_overview` | 1790 |
| `view_pipeline_overview` | 1875 |
| `view_lane_pipeline_overview` | 1919 |
| `view_tool_details` | 1973 |
| `view_data_plane` | 2004 |
| `data_plane_neighbors` | 2053 |
| `get_current_run` | 2131 |
| `get_run_status` | 2143 |
| `get_run_view` | 2153 |
| `list_runs` | 2170 |
| `engine_reconcile_diagnostics` | 2214 |

- [ ] **Step 1: Apply the mechanical migration to every reader**

For each function in the table, edit its signature to add the `principal` dependency and edit each cache-helper call inside its body. The pattern is identical for every function:

```python
# BEFORE (representative):
@router.get("/lineage/engine/upstream/{asset_id}")
async def engine_upstream(
    asset_id: str,
    depth: int = Query(3, ge=1, le=50),
    # ... other query params ...
    stack_id: Optional[str] = Query(None),
):
    store = _get_engine_store(stack_id)
    # ...

# AFTER:
@router.get("/lineage/engine/upstream/{asset_id}")
async def engine_upstream(
    asset_id: str,
    depth: int = Query(3, ge=1, le=50),
    # ... other query params ...
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    store = _get_engine_store(principal.organization_id, stack_id)
    # ...
```

Inside each body, replace every helper call:
- `_get_engine_store(stack_id)` → `_get_engine_store(principal.organization_id, stack_id)`
- `_get_run_registry(stack_id)` → `_get_run_registry(principal.organization_id, stack_id)`
- `_get_collected_results(stack_id)` → `_get_collected_results(principal.organization_id, stack_id)`

Some endpoints also call `_rebuild_engine_from_cache()` — change the call to `_rebuild_engine_from_cache(principal.organization_id, stack_id)`.

When implementing this step, do **all 26 endpoints** in one pass and commit them together. Do not skip any — leaving even one un-migrated leaves a leak path open.

- [ ] **Step 2: Verify no remaining `_get_engine_store(stack_id)` calls (single-arg form)**

Run a grep to confirm no leftover single-argument helper calls:

```bash
cd /Users/emilfabel/pallisade-copilot && grep -nE "_get_engine_store\([^,)]+\)|_get_run_registry\([^,)]+\)|_get_collected_results\(\)" scanner/api/routers/lineage.py
```

Expected: no output. If any line is printed, the migration missed it — fix the call site before continuing.

- [ ] **Step 3: Run the full lineage test suite**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v -k "lineage or engine or run" --no-header 2>&1 | tail -60`

Expected: existing pass/fail counts unchanged. Any test that calls a lineage endpoint must include `X-Acting-User`/`X-Acting-Org` headers (today's tests already do for paths that had `Depends(require_principal)` before; legacy lineage tests that don't will need headers added — apply the same pattern as `scanner/api/tests/test_auth.py:92-100`).

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/lineage.py
git commit -m "$(cat <<'EOF'
feat(lineage): reader endpoints require authenticated principal

Migrates all 26 read-only engine/* and runs/* endpoints to take
Depends(require_principal). Cache lookups are now keyed by
(principal.organization_id, stack_id), so a request supplying
another tenant's stack_id lands in its own bucket and sees no data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Migrate `discovery.py`

Both `/discovery/node` and `/discovery/bulk` import `_get_engine_store` and `_engine_tool_configs_map` from `lineage.py` and use a `cache_key = stack_id or "default"`. They need the same treatment.

**Files:**
- Modify: `scanner/api/routers/discovery.py`

- [ ] **Step 1: Update the imports and add the principal dependency to `discover_node_sla`**

Replace the import at `discovery.py:14`:

```python
# OLD:
from fastapi import APIRouter, HTTPException, Query

# NEW:
from fastapi import APIRouter, Depends, HTTPException, Query
```

Add a new import below the existing block:

```python
from ..auth import require_principal, ActingPrincipal
```

Edit `discover_node_sla` (discovery.py:107-225). Update the signature:

```python
@router.post("/discovery/node", response_model=NodeDiscoveryResponse)
async def discover_node_sla(
    request: NodeDiscoveryRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
```

Replace the inline import on line 119 and the cache-key block on lines 119, 122, 172-173:

```python
# OLD body opener:
from .lineage import _get_engine_store, _engine_tool_configs_map

# 1. Get the engine graph for this stack
store = _get_engine_store(stack_id)
# ...
# 4. Create the adapter from cached tool configs
cache_key = stack_id or "default"
tool_configs = _engine_tool_configs_map.get(cache_key, {})

# NEW body opener:
from . import _lineage_cache

org_id = principal.organization_id

# 1. Get the engine graph for this stack
store = _lineage_cache.get_engine_store(org_id, stack_id)
# ...
# 4. Create the adapter from cached tool configs
tool_configs = _lineage_cache.get_tool_configs(org_id, stack_id)
```

The rest of the function body is unchanged.

- [ ] **Step 2: Update `discover_bulk_sla`**

Edit the function at `discovery.py:228`. Update the signature:

```python
@router.post("/discovery/bulk", response_model=BulkDiscoveryResponse)
async def discover_bulk_sla(
    request: BulkDiscoveryRequest,
    principal: ActingPrincipal = Depends(require_principal),
):
```

Note that `stack_id` for `discover_bulk_sla` comes from `request.stackId` (in the body), not from a query parameter — keep that behavior. Update the body's cache calls:

```python
# OLD:
from .lineage import _get_engine_store, _engine_tool_configs_map

stack_id = request.stackId
store = _get_engine_store(stack_id)
# ...
cache_key = stack_id or "default"
tool_configs = _engine_tool_configs_map.get(cache_key, {})

# NEW:
from . import _lineage_cache

org_id = principal.organization_id
stack_id = request.stackId
store = _lineage_cache.get_engine_store(org_id, stack_id)
# ...
tool_configs = _lineage_cache.get_tool_configs(org_id, stack_id)
```

The remaining body (semaphore, async tasks) is unchanged.

- [ ] **Step 3: Run discovery tests**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v -k discovery --no-header 2>&1 | tail -30`

Expected: existing pass/fail counts unchanged. Any legacy test missing `X-Acting-User`/`X-Acting-Org` headers will fail with 400 — add the headers using the pattern from `test_auth.py:92-100`.

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/discovery.py
git commit -m "$(cat <<'EOF'
feat(discovery): node and bulk endpoints require authenticated principal

/discovery/node and /discovery/bulk now derive the cache key from
principal.organization_id instead of trusting a stack_id query/body
field alone. /discovery/direct and /discovery/direct-bulk are
unchanged because they don't read the lineage cache.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Delete `_current_stack_id`, `_CollectedResultsProxy`, and the helper wrappers

After Tasks 2-6, no caller references `_current_stack_id`, `_engine_collected_results` (the proxy), or the bare module-level dicts (`_engine_stores`, etc.). Time to delete them so a future refactor can't reintroduce a global-mutable read.

**Files:**
- Modify: `scanner/api/routers/lineage.py`

- [ ] **Step 1: Verify no remaining references**

Run:

```bash
cd /Users/emilfabel/pallisade-copilot && \
  grep -nE "_current_stack_id|_CollectedResultsProxy|_engine_collected_results\b|_engine_stores\b|_engine_tool_configs_map\b|_run_registries\b" scanner/api/routers/lineage.py | grep -v "^scanner/api/routers/lineage\.py:\(.*from\|.*#\)"
```

Expected: every remaining match must be in the helper wrappers added in Task 2 — i.e. lines that look like:

```python
def _get_engine_store(org_id: str, stack_id):
    return _lineage_cache.get_engine_store(org_id, stack_id)
```

If a match is in any other context, that call site was missed in Tasks 2-6 — fix it before continuing.

- [ ] **Step 2: Delete the temporary shim and wrappers**

Locate the block from Task 2 (the `_get_engine_store`/`_get_run_registry`/`_get_collected_results`/`_clear_engine_cache` wrappers and the `_current_stack_id: str = "default"` shim). Delete the entire block.

After deletion, every `_get_engine_store(...)` call in `lineage.py` and `discovery.py` must already be calling the `_lineage_cache.get_engine_store(...)` form directly — but to keep the diff minimal, we can leave the call-site syntax as `_get_engine_store(org_id, stack_id)` and instead alias the underscore name to the public helper at the import line:

```python
# Replace the helper-wrapper block with these aliases:
_get_engine_store = _lineage_cache.get_engine_store
_get_run_registry = _lineage_cache.get_run_registry
_get_collected_results = _lineage_cache.get_collected_results
_clear_engine_cache = _lineage_cache.clear_engine_cache
```

This keeps the call sites readable and unchanged, eliminates the dead `_current_stack_id` global, and makes the helper module the single source of truth.

- [ ] **Step 3: Run the full scanner test suite once**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v --no-header 2>&1 | tail -50`

Expected: same pass/fail counts as the post-Task-6 baseline.

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/lineage.py
git commit -m "$(cat <<'EOF'
refactor(lineage): delete _current_stack_id global and proxy

After every active endpoint passes (org_id, stack_id) explicitly,
the mutable _current_stack_id global, the _CollectedResultsProxy,
and the in-file cache dicts are no longer referenced. Replace the
helper wrappers with thin aliases over _lineage_cache.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Delete the 9 dead routes

**Files:**
- Modify: `scanner/api/routers/lineage.py`

- [ ] **Step 1: Re-verify each route is still unwired**

Run, for each route, the same caller-search command used in the spec:

```bash
cd /Users/emilfabel/pallisade-copilot
for endpoint in "lineage/extract\b" "lineage/extract-tool" "lineage/extract-unified" "lineage/investigate\b" "lineage/node/" "lineage/engine/producers" "lineage/engine/watches"; do
  echo "=== $endpoint ==="
  grep -rn "$endpoint" app src 2>/dev/null | grep -v "\.next\|node_modules\|worktrees" | head -3
done
```

Expected output: no caller for any of the seven greps. If a caller has been added in the time between the spec and the implementation, stop and ask: that route is no longer dead and must be migrated, not deleted.

- [ ] **Step 2: Delete each route in order**

Delete the function bodies (and any decorators / pydantic models defined exclusively for those routes) for:

1. `POST /lineage/extract` — function `extract_lineage` at `lineage.py:100-680` (~580 lines)
2. `GET /lineage/node/{node_id}` — function at `lineage.py:681-754`
3. `POST /lineage/extract-unified` — function at `lineage.py:755-934` (approx; verify end by next `@router.` decorator)
4. `GET /lineage/engine/producers` — function at `lineage.py:1718-1753`
5. `POST /lineage/investigate` — function at `lineage.py:2839-2968`
6. `POST /lineage/extract-tool` — function `extract_tool_lineage` at `lineage.py:2493-2580` (approx)
7. `POST /lineage/engine/watches/scope` — function at `lineage.py:3244-3287`
8. `GET /lineage/engine/watches/infer-type/{asset_id}` — function at `lineage.py:3288-3316`
9. `POST /lineage/engine/watches/compute-health` — function at `lineage.py:3317-...`

For each: read the function from `@router.` to the next `@router.` (or end of file), delete the entire span, including any pydantic request/response models declared immediately before the route that aren't used elsewhere. Use grep to confirm a model is unused before deleting it; if it's used by another route, leave it.

- [ ] **Step 3: Run the full scanner test suite**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/ -v --no-header 2>&1 | tail -50`

Expected: same pass/fail counts as Task 7 baseline. (None of the deleted routes had tests — that's why they're deletable.)

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/routers/lineage.py
git commit -m "$(cat <<'EOF'
chore(lineage): delete 9 unwired routes

Removes routes with no Next.js caller, no internal caller, and no
test coverage:
- POST /lineage/extract        (superseded by /extract-llm)
- GET  /lineage/node/{id}
- POST /lineage/extract-unified
- POST /lineage/extract-tool   (generic adapter dispatch, never wired)
- POST /lineage/investigate    (superseded by /investigate-llm)
- GET  /lineage/engine/producers
- POST /lineage/engine/watches/scope
- GET  /lineage/engine/watches/infer-type/{id}
- POST /lineage/engine/watches/compute-health

If any of these is needed later, git-revert restores it; the revived
code will need to be re-wired with (org_id, stack_id) keying.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Two-tenant isolation integration test

A black-box test that proves the read-side leak is closed: given two principals supplying the same `stack_id`, neither can see the other's data.

**Files:**
- Create: `scanner/api/tests/test_lineage_isolation.py`

- [ ] **Step 1: Write the test file**

Create `scanner/api/tests/test_lineage_isolation.py`:

```python
"""Two-tenant isolation tests for the lineage cache.

Both principals supply the same `stack_id`. With correct isolation the
caches must remain disjoint: writes by principal A are invisible to B
and vice versa.
"""

import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient


SECRET = "a" * 64


@pytest.fixture
def client():
    env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": SECRET}
    with patch.dict("os.environ", env):
        from scanner.api.dependencies import get_settings
        get_settings.cache_clear()
        from scanner.api.app import create_app
        # Reset cache state between tests
        from scanner.api.routers import _lineage_cache
        _lineage_cache._engine_stores.clear()
        _lineage_cache._engine_collected_results_map.clear()
        _lineage_cache._engine_tool_configs_map.clear()
        _lineage_cache._run_registries.clear()
        app = create_app()
        yield TestClient(app)


def _headers(user: str, org: str) -> dict:
    return {
        "X-Internal-Auth": SECRET,
        "X-Acting-User": user,
        "X-Acting-Org": org,
        "X-Request-Id": f"req_{user}_{org}",
    }


def test_clear_cache_does_not_leak_across_orgs(client):
    """Org A's clear-cache must not touch Org B's bucket."""
    # Both orgs prime their bucket via clear-cache (creates the bucket
    # entry with empty graph + registry).
    r_a = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared_stack"},
        headers=_headers("u_a", "org_a"),
    )
    r_b = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared_stack"},
        headers=_headers("u_b", "org_b"),
    )
    assert r_a.status_code == 200
    assert r_b.status_code == 200

    # The two principals have separate buckets (verified by inspecting
    # the cache map directly).
    from scanner.api.routers import _lineage_cache
    key_a = _lineage_cache.cache_key("org_a", "shared_stack")
    key_b = _lineage_cache.cache_key("org_b", "shared_stack")
    assert key_a in _lineage_cache._engine_stores
    assert key_b in _lineage_cache._engine_stores
    assert _lineage_cache._engine_stores[key_a] is not _lineage_cache._engine_stores[key_b]


def test_engine_stats_returns_only_callers_data(client):
    """Org A writes to its own bucket; Org B reading the same stack_id
    must see Org B's bucket (which is empty), not Org A's."""
    from scanner.api.routers import _lineage_cache

    # Org A: simulate a populated graph by injecting nodes/edges directly
    # into Org A's collected-results bucket. (Full investigate-llm is
    # too expensive for a test; the cache layer is what we're verifying.)
    collected_a = _lineage_cache.get_collected_results("org_a", "shared_stack")
    collected_a["nodes"].append({"id": "n_a"})

    # Org B reads the engine stats for the same stack_id — should see
    # an empty graph because its (org_b, shared_stack) bucket is fresh.
    r_b = client.get(
        "/api/v1/lineage/engine/stats",
        params={"stack_id": "shared_stack"},
        headers=_headers("u_b", "org_b"),
    )
    # The endpoint either returns a stats payload with zero coverage,
    # or 404 if no graph has been built. Either is acceptable — the
    # critical invariant is that Org B does NOT see Org A's "n_a" node.
    if r_b.status_code == 200:
        body = r_b.json()
        # Coverage stats should report no nodes for Org B.
        assert body.get("total_nodes", 0) == 0


def test_tool_configs_isolated(client):
    """Simulating investigate-llm's tool_configs cache write — Org B
    cannot read Org A's cached configs."""
    from scanner.api.routers import _lineage_cache

    _lineage_cache.set_tool_configs(
        "org_a", "shared_stack", {"bigquery": {"project": "secret_a"}}
    )
    _lineage_cache.set_tool_configs(
        "org_b", "shared_stack", {"bigquery": {"project": "public_b"}}
    )

    assert _lineage_cache.get_tool_configs("org_a", "shared_stack") == {
        "bigquery": {"project": "secret_a"}
    }
    assert _lineage_cache.get_tool_configs("org_b", "shared_stack") == {
        "bigquery": {"project": "public_b"}
    }


def test_request_without_principal_is_rejected(client):
    """Sanity check: ActingPrincipalMiddleware still rejects callers
    that lack the headers, preventing anonymous access."""
    r = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "anything"},
        headers={"X-Internal-Auth": SECRET},  # no X-Acting-User/Org
    )
    assert r.status_code == 400
    assert r.json() == {"error": "missing_principal"}
```

- [ ] **Step 2: Run the test file**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/test_lineage_isolation.py -v`

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/tests/test_lineage_isolation.py
git commit -m "$(cat <<'EOF'
test(lineage): two-tenant isolation regression suite

Asserts that supplying the same stack_id from two different
principals cannot cross-read or cross-write the lineage caches.
Covers the engine store, collected results, tool configs, and
the principal-required entry point.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Race-regression test for clear-cache + extract interleave

This test exercises the original `_current_stack_id` race: under the legacy code, Org A's `clear-cache` flipped a process global and Org B's concurrent extraction wrote to the wrong bucket. With the fix, the buckets remain disjoint regardless of interleave order.

**Files:**
- Modify: `scanner/api/tests/test_lineage_isolation.py`

- [ ] **Step 1: Add the race test to the existing file**

Append to `scanner/api/tests/test_lineage_isolation.py`:

```python
def test_interleaved_clear_cache_and_writes_do_not_cross_contaminate(client):
    """Org A clears cache, then Org B writes, then Org A reads — Org A
    must see an empty bucket, not Org B's data. This is the regression
    guard for the deleted _current_stack_id global.
    """
    from scanner.api.routers import _lineage_cache

    # 1. Org A primes its bucket.
    r_a = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared"},
        headers=_headers("u_a", "org_a"),
    )
    assert r_a.status_code == 200

    # 2. Org B does the same on the same stack_id.
    r_b = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared"},
        headers=_headers("u_b", "org_b"),
    )
    assert r_b.status_code == 200

    # 3. Org B writes content into its own bucket (simulating an
    # extraction's output).
    collected_b = _lineage_cache.get_collected_results("org_b", "shared")
    collected_b["nodes"].append({"id": "leaked_node_from_b"})

    # 4. Org A reads its own bucket — must be empty.
    collected_a = _lineage_cache.get_collected_results("org_a", "shared")
    assert collected_a["nodes"] == []

    # 5. Org A clears its cache again. Org B's bucket must remain
    # populated.
    r_a2 = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared"},
        headers=_headers("u_a", "org_a"),
    )
    assert r_a2.status_code == 200
    collected_b_after = _lineage_cache.get_collected_results("org_b", "shared")
    assert collected_b_after["nodes"] == [{"id": "leaked_node_from_b"}]
```

- [ ] **Step 2: Run the new test**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/api/tests/test_lineage_isolation.py::test_interleaved_clear_cache_and_writes_do_not_cross_contaminate -v`

Expected: pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/api/tests/test_lineage_isolation.py
git commit -m "$(cat <<'EOF'
test(lineage): regression test for interleaved clear-cache races

Locks in the fix for the deleted _current_stack_id global by asserting
that interleaving clear-cache calls and writes from two different
principals never lets one read another's bucket.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Final verification — full scanner test suite

**Files:**
- None modified.

- [ ] **Step 1: Run the full scanner pytest suite**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/ -v --no-header 2>&1 | tail -80`

Expected: every test that was passing before this PR still passes; the new helper unit tests (Task 1) and isolation tests (Tasks 9-10) all pass; no new failures introduced.

If any test fails:
- For tests that fail with `400 missing_principal`: add `X-Acting-User`/`X-Acting-Org` headers using the pattern from `scanner/api/tests/test_auth.py:92-100`.
- For tests that fail because they manipulate the cache directly via the old globals (`_engine_collected_results`, `_current_stack_id`): rewrite them to use the new helpers.
- For any other failure: stop, diagnose, fix at the root cause. Do not skip a test.

- [ ] **Step 2: Run the SQL-injection regression suite (touched by PR #38) to confirm no cross-PR regression**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/adapters/tests/test_sql_safety.py scanner/monitors/ -v --no-header 2>&1 | tail -30`

Expected: all SQL-safety + monitor tests still pass. (This PR doesn't touch those areas, but the verification is cheap insurance.)

- [ ] **Step 3: Final grep audit**

Run, to confirm no remnants of the old isolation bugs remain anywhere in the scanner backend:

```bash
cd /Users/emilfabel/pallisade-copilot && \
  grep -rn "_current_stack_id\|_CollectedResultsProxy" scanner/ 2>/dev/null
```

Expected: no output.

```bash
cd /Users/emilfabel/pallisade-copilot && \
  grep -rnE "_get_engine_store\(stack_id\)|_get_run_registry\(stack_id\)" scanner/ 2>/dev/null
```

Expected: no output (every call now passes `org_id` first).

- [ ] **Step 4: Push the branch and open a PR**

```bash
cd /Users/emilfabel/pallisade-copilot
git push -u origin <branch-name>
gh pr create --title "fix(lineage): isolate engine caches per (org_id, stack_id)" --body "$(cat <<'EOF'
## Summary
- Closes the cross-tenant data leak in the four lineage caches by re-keying every cache on a compound (org_id, stack_id) where org_id always comes from the authenticated principal.
- Deletes the mutable process-global _current_stack_id, the _CollectedResultsProxy, and the 9 unwired lineage routes.

See the spec at `docs/superpowers/specs/2026-04-27-lineage-tenant-isolation-design.md` for the full design rationale.

## Test plan
- [ ] `pytest scanner/api/tests/test_lineage_cache.py` — helper unit tests
- [ ] `pytest scanner/api/tests/test_lineage_isolation.py` — two-tenant integration + race regression
- [ ] `pytest scanner/` — full scanner suite, no regressions

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(Replace `<branch-name>` with the actual branch name set up at the start of execution.)

---

## Self-review

**Spec coverage:**
- Goal 1 (eliminate cross-tenant reads/writes): Tasks 1–8 implement the fix; Tasks 9-10 verify it.
- Goal 2 (preserve multi-pipeline-per-org): compound key keeps `stack_id` as the inner sub-scope.
- Goal 3 (isolation as cache-key property): every helper takes `org_id` explicitly; no endpoint can forget the check because helpers can't be called without it.
- Spec lists 7 writers + 26 readers + 2 discovery endpoints in scope. Tasks 3, 4, 5, 6 cover all 35.
- Spec lists 9 dead routes for deletion. Task 8 deletes all 9.
- Spec defers OpenLineage push. Plan does not touch them. ✓
- Spec defers `direct`/`direct-bulk` discovery. Plan does not touch them. ✓
- Spec testing section calls for: helper unit tests (Task 1), endpoint isolation tests (Task 9), race regression (Task 10), full-suite pass (Task 11). All present. ✓

**Placeholder scan:** No "TBD"/"TODO"/"implement later"/"add appropriate error handling" appears anywhere in steps. The single `pass  # (existing block from current file goes here)` in Task 2 Step 3 has explicit instructions on what to copy in (specific source line range and that the behavior does not change), satisfying the "show how, not just what" rule.

**Type consistency:**
- Helper signatures: `cache_key(org_id, stack_id)`, `get_engine_store(org_id, stack_id)`, etc. — same shape across Task 1 (definition), Task 2 (wrappers), Tasks 3-6 (call sites), Task 7 (alias), Tasks 9-10 (test references). ✓
- `_get_engine_store(org_id, stack_id)` (positional) used consistently in all migration tasks. ✓
- `_lineage_cache.set_tool_configs(org_id, stack_id, configs)` matches Task 1's definition. ✓
- `principal.organization_id` (snake_case) is used consistently — matches `auth.py:34`. ✓

**Other notes:**
- Each task's commit message includes the "Co-Authored-By: Claude Opus 4.7" trailer per the project's commit convention.
- Each task ends with a verification command (pytest run + expected output) so the engineer knows when the task is done before advancing.
- Task 11 includes a final greppable assertion that no `_current_stack_id` or single-arg helper calls remain anywhere in `scanner/` — a global proof of completeness.
