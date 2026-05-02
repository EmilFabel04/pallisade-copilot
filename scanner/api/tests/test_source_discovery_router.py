"""
Tests for the /discover endpoint.

Covers:
1. POST with valid HTTPS base_url + auth + endpoint → 200, response shape
   includes candidates_by_path.probe. Probe HTTP call is mocked.
2. POST with http:// (non-HTTPS) base_url → 400.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

_TEST_USER_ID = "user_abc123"
_TEST_ORG_ID = "org_xyz"


def _create_test_client() -> TestClient:
    """Build a minimal FastAPI app with only the source_discovery router mounted."""
    from scanner.api.routers.source_discovery import router
    from scanner.api.auth import ActingPrincipal, require_principal

    fixed_principal = ActingPrincipal(
        user_id=_TEST_USER_ID,
        organization_id=_TEST_ORG_ID,
        request_id="test-req-id",
    )

    def _fake_principal() -> ActingPrincipal:
        return fixed_principal

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_principal] = _fake_principal
    return TestClient(app)


def test_discover_valid_https_returns_200_with_probe_key():
    """POST with valid HTTPS base_url + auth + endpoint → 200, response has candidates_by_path.probe."""
    from scanner.discovery.types import DatasetCandidate, DiscoveryError, DiscoveryResult

    probe_candidate = DatasetCandidate(
        source='probe',
        endpoint='/sensors',
        json_root=None,
        timestamp_column='reading_at',
        expected_schema=[],
        lands_in=None,
        confidence=0.7,
    )
    mock_result = DiscoveryResult(
        candidates_by_path={
            'probe': [probe_candidate],
            'warehouse': [],
            'ingestion': [],
        },
        errors_by_path={
            'probe': None,
            'warehouse': DiscoveryError(code='no_warehouse_hint', message='no hints'),
            'ingestion': DiscoveryError(code='no_connectors_connected', message='not implemented'),
        },
    )

    async def _fake_discover(**kwargs):
        return mock_result

    mock_orchestrator = MagicMock()
    mock_orchestrator.discover = _fake_discover

    with patch(
        "scanner.api.routers.source_discovery._orchestrator",
        return_value=mock_orchestrator,
    ):
        client = _create_test_client()
        resp = client.post(
            "/api/v1/integrations/source/discover",
            json={
                "base_url": "https://api.example.com",
                "endpoint": "/sensors",
                "auth": {
                    "kind": "bearer",
                    "secret_ref": "my-secret-ref",
                },
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "candidates_by_path" in body
    assert "probe" in body["candidates_by_path"]
    assert len(body["candidates_by_path"]["probe"]) == 1
    assert body["candidates_by_path"]["probe"][0]["endpoint"] == "/sensors"
    assert body["candidates_by_path"]["probe"][0]["confidence"] == 0.7


def test_discover_http_base_url_returns_400():
    """POST with http:// (non-HTTPS) base_url → 400."""
    client = _create_test_client()
    resp = client.post(
        "/api/v1/integrations/source/discover",
        json={
            "base_url": "http://api.example.com",
            "endpoint": "/sensors",
            "auth": {
                "kind": "bearer",
                "secret_ref": "my-secret-ref",
            },
        },
    )

    assert resp.status_code == 400
