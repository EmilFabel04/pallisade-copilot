"""
Tests for the drivers router — specifically the test-connection endpoint
that delegates to DriverRegistry.

Covers:
1. CUSTOM_SOURCE flows through the registry to CustomSourceDriver.test_connection
2. Unknown integration_type → 404
"""

import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_client() -> TestClient:
    """Build a FastAPI app with the drivers router mounted at /api/v1.

    Drivers are loaded eagerly so the registry is populated.
    """
    from scanner.drivers.loader import register_all_drivers
    from scanner.api.routers.drivers import router

    register_all_drivers()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


@responses.activate
def test_test_connection_custom_source_ok():
    """CUSTOM_SOURCE goes through the registry-based test-connection path."""
    responses.add(
        responses.GET,
        "https://api.example.com/v1/x",
        json=[{"id": 1}],
        status=200,
    )

    client = _create_test_client()
    resp = client.post(
        "/api/v1/drivers/CUSTOM_SOURCE/test-connection",
        json={
            "config": {
                "base_url": "https://api.example.com/v1",
                "auth": {"kind": "bearer", "secret": "t"},
                "datasets": [
                    {"id": "d", "endpoint": "/x", "timestamp_column": "id"},
                ],
            },
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert "d" in body["message"]
    assert body["latency_ms"] is not None


@responses.activate
def test_test_connection_custom_source_failure_propagates():
    """A 401 from the upstream propagates as ok=False with a useful message."""
    responses.add(
        responses.GET,
        "https://api.example.com/v1/x",
        status=401,
    )

    client = _create_test_client()
    resp = client.post(
        "/api/v1/drivers/CUSTOM_SOURCE/test-connection",
        json={
            "config": {
                "base_url": "https://api.example.com/v1",
                "auth": {"kind": "bearer", "secret": "bad"},
                "datasets": [
                    {"id": "d", "endpoint": "/x", "timestamp_column": "id"},
                ],
            },
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["message"]


def test_test_connection_unknown_type_returns_404():
    client = _create_test_client()
    resp = client.post(
        "/api/v1/drivers/NOT_A_REAL_TYPE/test-connection",
        json={"config": {}},
    )
    assert resp.status_code == 404
