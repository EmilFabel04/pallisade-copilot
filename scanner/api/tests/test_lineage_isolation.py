"""Two-tenant isolation tests for the lineage cache.

Both principals supply the same `stack_id`. With correct isolation the
caches must remain disjoint: writes by principal A are invisible to B
and vice versa.

Includes a regression guard for the deleted `_current_stack_id` global:
interleaved clear-cache + write calls between two principals must not
cross-contaminate buckets.
"""

import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient


SECRET = "a" * 64


@pytest.fixture
def client():
    """Build a fresh TestClient with empty cache state per test."""
    env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": SECRET}
    with patch.dict("os.environ", env):
        from scanner.api.dependencies import get_settings
        get_settings.cache_clear()
        from scanner.api.routers import _lineage_cache
        _lineage_cache._engine_stores.clear()
        _lineage_cache._engine_collected_results_map.clear()
        _lineage_cache._engine_tool_configs_map.clear()
        _lineage_cache._run_registries.clear()
        from scanner.api.app import create_app
        app = create_app()
        yield TestClient(app)


def _headers(user: str, org: str) -> dict:
    return {
        "X-Internal-Auth": SECRET,
        "X-Acting-User": user,
        "X-Acting-Org": org,
        "X-Request-Id": f"req_{user}_{org}",
    }


# ---------------------------------------------------------------------------
# Task 9: Two-tenant isolation
# ---------------------------------------------------------------------------


def test_clear_cache_does_not_leak_across_orgs(client):
    """Org A's clear-cache must not touch Org B's bucket."""
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

    from scanner.api.routers import _lineage_cache
    key_a = _lineage_cache.cache_key("org_a", "shared_stack")
    key_b = _lineage_cache.cache_key("org_b", "shared_stack")
    assert key_a in _lineage_cache._engine_stores
    assert key_b in _lineage_cache._engine_stores
    assert _lineage_cache._engine_stores[key_a] is not _lineage_cache._engine_stores[key_b]


def test_engine_stats_returns_only_callers_data(client):
    """Org A populates its own bucket directly. Org B reading the same
    stack_id must see Org B's (empty) bucket — never Org A's data."""
    from scanner.api.routers import _lineage_cache

    # Populate Org A's collected-results bucket directly. Building the
    # full graph through investigate-llm is expensive in a unit test;
    # the cache layer is what we're verifying.
    collected_a = _lineage_cache.get_collected_results("org_a", "shared_stack")
    collected_a["nodes"].append({"id": "n_a_secret"})

    # Org B reads engine stats for the same stack_id.
    r_b = client.get(
        "/api/v1/lineage/engine/stats",
        params={"stack_id": "shared_stack"},
        headers=_headers("u_b", "org_b"),
    )

    # The endpoint either returns stats with zero coverage, or 404 when
    # no graph has been built. Either is acceptable. The critical
    # invariant is that Org B does NOT receive Org A's "n_a_secret"
    # node in any payload.
    assert "n_a_secret" not in r_b.text
    if r_b.status_code == 200:
        body = r_b.json()
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


# ---------------------------------------------------------------------------
# Task 10: Race regression for deleted _current_stack_id global
# ---------------------------------------------------------------------------


def test_interleaved_clear_cache_and_writes_do_not_cross_contaminate(client):
    """Org A clears cache, Org B writes, Org A reads — Org A must see
    an empty bucket, not Org B's data. Locks in the fix for the
    deleted _current_stack_id global, which under the legacy code
    would route Org B's write to whichever bucket Org A's clear-cache
    last touched."""
    from scanner.api.routers import _lineage_cache

    # 1. Both orgs prime their buckets via the public API.
    r_a = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared"},
        headers=_headers("u_a", "org_a"),
    )
    assert r_a.status_code == 200

    r_b = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared"},
        headers=_headers("u_b", "org_b"),
    )
    assert r_b.status_code == 200

    # 2. Org B writes content into ITS OWN bucket (simulating an
    # extraction's output landing in the right place).
    collected_b = _lineage_cache.get_collected_results("org_b", "shared")
    collected_b["nodes"].append({"id": "node_from_b"})

    # 3. Org A reads its own bucket — must be empty regardless of
    # what Org B did.
    collected_a = _lineage_cache.get_collected_results("org_a", "shared")
    assert collected_a["nodes"] == []

    # 4. Org A clears its cache again. Org B's bucket must remain
    # populated.
    r_a2 = client.post(
        "/api/v1/lineage/engine/clear-cache",
        params={"stack_id": "shared"},
        headers=_headers("u_a", "org_a"),
    )
    assert r_a2.status_code == 200
    collected_b_after = _lineage_cache.get_collected_results("org_b", "shared")
    assert collected_b_after["nodes"] == [{"id": "node_from_b"}]
