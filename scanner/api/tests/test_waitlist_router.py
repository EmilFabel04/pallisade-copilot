"""
Tests for the waitlist router — the source-connector waitlist endpoint
that lets users request early access to coming-soon connectors.

Covers:
1. POST with valid connector_id 'salesforce' → 201, response contains
   connector_id and requested_at.
2. POST with unknown connector_id → 400.
3. POST same connector twice for same user → first call 201, second
   call 200 (idempotent — already on waitlist).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Sentinel user_id injected via X-Acting-User in all test requests.
_TEST_USER_ID = "user_abc123"
_TEST_ORG_ID = "org_xyz"


def _create_test_client() -> TestClient:
    """Build a FastAPI app with only the waitlist router mounted.

    Mirrors the pattern in test_integrations_router.py: by mounting the
    router directly we sidestep the InternalAuth/ActingPrincipal
    middlewares.  We override require_principal with a no-arg callable
    that returns a fixed ActingPrincipal so tests don't need the
    middleware chain.
    """
    from scanner.api.routers.waitlist import router
    from scanner.api.auth import ActingPrincipal, require_principal

    fixed_principal = ActingPrincipal(
        user_id=_TEST_USER_ID,
        organization_id=_TEST_ORG_ID,
        request_id="test-req-id",
    )

    def _fake_principal() -> ActingPrincipal:
        return fixed_principal

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # Override the dependency using the same object the router imported.
    app.dependency_overrides[require_principal] = _fake_principal
    return TestClient(app)


def _make_fake_conn() -> tuple[MagicMock, MagicMock]:
    """Build a MagicMock psycopg2 connection."""
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.rowcount = 1
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn, fake_cursor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_join_waitlist_valid_connector_returns_201():
    """POST with connector_id='salesforce' → 201 with connector_id + requested_at."""
    now_iso = datetime.now(timezone.utc).isoformat()
    fake_conn, fake_cursor = _make_fake_conn()
    # First fetchone (SELECT) → None (no existing row).
    # Second fetchone (INSERT RETURNING) → new row.
    fake_cursor.fetchone.side_effect = [
        None,
        ("salesforce", now_iso),
    ]

    with patch(
        "scanner.api.routers.waitlist._get_connection",
        return_value=fake_conn,
    ):
        client = _create_test_client()
        resp = client.post(
            "/api/v1/waitlist/source-connector",
            json={"connector_id": "salesforce"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["connector_id"] == "salesforce"
    assert "requested_at" in body


def test_join_waitlist_unknown_connector_returns_400():
    """POST with an unknown connector_id → 400."""
    fake_conn, _ = _make_fake_conn()

    with patch(
        "scanner.api.routers.waitlist._get_connection",
        return_value=fake_conn,
    ):
        client = _create_test_client()
        resp = client.post(
            "/api/v1/waitlist/source-connector",
            json={"connector_id": "oracle"},
        )

    assert resp.status_code == 400
    assert "oracle" in resp.json()["detail"]


def test_join_waitlist_idempotent_second_call_returns_200():
    """Second POST for same connector → 200 (already on waitlist)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    fake_conn, fake_cursor = _make_fake_conn()
    # SELECT returns an existing row.
    existing_row = ("salesforce", now_iso)
    fake_cursor.fetchone.return_value = existing_row

    with patch(
        "scanner.api.routers.waitlist._get_connection",
        return_value=fake_conn,
    ):
        client = _create_test_client()
        resp = client.post(
            "/api/v1/waitlist/source-connector",
            json={"connector_id": "salesforce"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connector_id"] == "salesforce"
    assert "requested_at" in body
