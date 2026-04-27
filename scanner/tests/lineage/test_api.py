"""
Tests for the FastAPI lineage engine endpoints.
"""

import os
import pytest
from unittest.mock import patch

# Try importing FastAPI test client
try:
    from fastapi.testclient import TestClient
    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def client():
    """Create a FastAPI test client with the lineage router.

    Overrides require_principal to return a fixed test principal so
    the tests can exercise endpoint logic without standing up
    InternalAuthMiddleware + ActingPrincipalMiddleware.
    """
    if not HAS_TESTCLIENT:
        pytest.skip("fastapi[testclient] not available")

    from fastapi import FastAPI
    from scanner.api.auth import ActingPrincipal, require_principal
    from scanner.api.routers.lineage import router
    from scanner.api.routers import _lineage_cache

    # Reset cache between tests so a previous test's bucket doesn't
    # contaminate the next one.
    _lineage_cache._engine_stores.clear()
    _lineage_cache._engine_collected_results_map.clear()
    _lineage_cache._engine_tool_configs_map.clear()
    _lineage_cache._run_registries.clear()

    app = FastAPI()
    app.include_router(router)

    # Tests don't go through ActingPrincipalMiddleware, so stub the
    # principal dependency directly.
    app.dependency_overrides[require_principal] = lambda: ActingPrincipal(
        user_id="test_user",
        organization_id="test_org",
        request_id="test_req",
    )

    return TestClient(app)


@pytest.fixture
def built_client(client):
    """Client with a pre-built graph."""
    config = {
        "adapters": [
            {"id": "wh", "type": "warehouse_catalog", "params": {"path": os.path.join(FIXTURES_DIR, "warehouse_catalog.json")}},
            {"id": "tr", "type": "transform_artifact", "params": {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}},
            {"id": "bi", "type": "bi_query", "params": {"path": os.path.join(FIXTURES_DIR, "bi_export.json")}},
        ],
        "resolver": {"fuzzy_resolution": False},
    }
    resp = client.post("/lineage/engine/build", json={"config": config})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    return client, data


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="fastapi testclient not available")
class TestEngineBuildEndpoint:
    def test_build_success(self, built_client):
        client, data = built_client
        assert data["success"] is True
        assert len(data["nodes"]) > 0
        assert len(data["edges"]) >= 0

    def test_build_returns_stats(self, built_client):
        _, data = built_client
        assert "stats" in data
        assert "total_nodes" in data["stats"]


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="fastapi testclient not available")
class TestEngineQueryEndpoints:
    def test_upstream(self, built_client):
        client, data = built_client
        if not data["nodes"]:
            pytest.skip("No nodes")
        node_id = data["nodes"][0]["id"]
        resp = client.get(f"/lineage/engine/upstream/{node_id}?depth=2")
        assert resp.status_code == 200
        assert "upstream" in resp.json()

    def test_downstream(self, built_client):
        client, data = built_client
        if not data["nodes"]:
            pytest.skip("No nodes")
        node_id = data["nodes"][0]["id"]
        resp = client.get(f"/lineage/engine/downstream/{node_id}?depth=2")
        assert resp.status_code == 200
        assert "downstream" in resp.json()

    def test_blast_radius(self, built_client):
        client, data = built_client
        if not data["nodes"]:
            pytest.skip("No nodes")
        node_id = data["nodes"][0]["id"]
        resp = client.get(f"/lineage/engine/blast-radius/{node_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_downstream" in body

    def test_explain_edge(self, built_client):
        client, data = built_client
        if not data["edges"]:
            pytest.skip("No edges")
        edge_id = data["edges"][0]["id"]
        resp = client.get(f"/lineage/engine/explain-edge/{edge_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "confidence" in body

    def test_explain_nonexistent_edge(self, built_client):
        client, _ = built_client
        resp = client.get("/lineage/engine/explain-edge/nonexistent")
        assert resp.status_code == 404

    def test_stats(self, built_client):
        client, _ = built_client
        resp = client.get("/lineage/engine/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_nodes" in body
        assert "coverage_table" in body

    def test_export_json(self, built_client):
        client, _ = built_client
        resp = client.get("/lineage/engine/export?fmt=json")
        assert resp.status_code == 200
        assert resp.json()["format"] == "json"

    def test_export_graphml(self, built_client):
        client, _ = built_client
        resp = client.get("/lineage/engine/export?fmt=graphml")
        assert resp.status_code == 200
        assert resp.json()["format"] == "graphml"

    def test_export_dot(self, built_client):
        client, _ = built_client
        resp = client.get("/lineage/engine/export?fmt=dot")
        assert resp.status_code == 200
        assert resp.json()["format"] == "dot"


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="fastapi testclient not available")
class TestFilterQueryParams:
    def test_filter_by_level(self, built_client):
        client, data = built_client
        if not data["nodes"]:
            pytest.skip("No nodes")
        node_id = data["nodes"][0]["id"]
        resp = client.get(f"/lineage/engine/upstream/{node_id}?level=table")
        assert resp.status_code == 200

    def test_filter_by_confidence(self, built_client):
        client, data = built_client
        if not data["nodes"]:
            pytest.skip("No nodes")
        node_id = data["nodes"][0]["id"]
        resp = client.get(f"/lineage/engine/upstream/{node_id}?min_confidence=0.8")
        assert resp.status_code == 200

    def test_no_graph_returns_empty_stats(self, client):
        """Querying before building should return empty stats (not 404)."""
        # The client fixture already resets the per-tenant cache buckets,
        # so no graph exists for test_org at this point.
        resp = client.get("/lineage/engine/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
