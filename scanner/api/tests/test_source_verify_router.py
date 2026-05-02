"""
Tests for the /api/v1/integrations/source/verify endpoint.

Covers:
1. POST with a config containing one valid dataset + stash ref → SSE response
   with one `dataset_result` event (status=ok, row_count populated) and a
   `complete` event with `all_pass: true` and a `verify_token`.
2. POST with a config that triggers ProbeError → SSE response with one
   `dataset_result` event with status=error, and a `complete` event with
   `all_pass: false` (no verify_token). CRITICAL: asserts no Integration row
   was persisted.
3. POST with empty datasets → 422.
4. POST with invalid/expired secret_ref → 400.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scanner.secret_stash.stash import stash_secret, _STASH

_TEST_USER_ID = "user_abc123"
_TEST_ORG_ID = "org_xyz"


def _create_test_client() -> TestClient:
    """Build a minimal FastAPI app with only the source_verify router mounted."""
    from scanner.api.routers.source_verify import router
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


def _make_stash_ref(secret: str = "stub-api-key") -> str:
    """Stash a secret for _TEST_USER_ID and return the opaque ref."""
    _STASH.clear()
    return stash_secret(secret, owner_id=_TEST_USER_ID)


def _verify_body(secret_ref: str | None = None) -> dict:
    if secret_ref is None:
        secret_ref = _make_stash_ref()
    return {
        "name": "MyCiti — water sensors",
        "platform_label": "MyCiti",
        "base_url": "https://portal.example.com/api/v1",
        "auth": {"kind": "api_key", "header_name": "X-API-Key", "secret_ref": secret_ref},
        "schedule": "daily",
        "stack_id": None,
        "datasets": [
            {
                "id": "water_meters",
                "endpoint": "/sensors",
                "json_root": None,
                "timestamp_column": "reading_at",
                "lands_in": None,
            },
        ],
    }


def _parse_sse_events(response) -> list[dict]:
    """Parse SSE events from a streaming TestClient response.

    Returns a list of dicts: {"event": <name>, "data": <parsed json>}.
    Lines starting with b"data: " carry the JSON payload;
    lines starting with b"event: " carry the event type.
    """
    events = []
    current_event: dict = {}
    for raw_line in response.iter_lines():
        line: bytes = raw_line if isinstance(raw_line, bytes) else raw_line.encode()
        if line.startswith(b"event: "):
            current_event["event"] = line[len(b"event: "):].decode().strip()
        elif line.startswith(b"data: "):
            raw_data = line[len(b"data: "):].decode().strip()
            current_event["data"] = json.loads(raw_data)
        elif line.strip() == b"" and current_event:
            # blank line = end of event block
            events.append(current_event)
            current_event = {}
    # flush any trailing event (no trailing blank line)
    if current_event:
        events.append(current_event)
    return events


def _make_db_mock() -> tuple[MagicMock, MagicMock]:
    """Build a MagicMock psycopg2 connection.

    Used only to stand in for the patched _get_connection so we can assert
    that it was never called.  source_verify must not reach any DB write path.
    """
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.rowcount = 0
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn, fake_cursor


# ---------------------------------------------------------------------------
# Test 1: valid probe → ok result
# ---------------------------------------------------------------------------


def test_verify_valid_dataset_streams_ok_then_complete():
    """POST with one valid dataset + stash ref → dataset_result(status=ok) + complete(all_pass=true, verify_token set).

    The key DB-no-write assertion is the mock_get_conn.call_count == 0 check:
    it proves that the integrations _get_connection helper (the only module that
    persists Integration rows) was never called by source_verify.  In a unit-test
    context with a mocked DB the call-count check is the truthful equivalent of
    "no Integration row was persisted" — a SELECT COUNT(*) on a mock always returns
    the fixed stub value and cannot detect real writes.
    """
    from scanner.adapters.http_probe import MetricBundle

    fake_bundle = MetricBundle(
        probed_at=datetime.now(timezone.utc),
        row_count=42,
        latest_timestamp=datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
        column_schema=[{"name": "reading_at", "data_type": "string", "is_nullable": True}],
        null_counts={"reading_at": 0},
        distinct_counts={"reading_at": 42},
        value_fingerprints={},
        min_max_numeric={},
    )

    fake_conn, _fake_cursor = _make_db_mock()

    with patch(
        "scanner.adapters.http_probe.HttpProbeAdapter.probe",
        return_value=fake_bundle,
    ), patch(
        "scanner.api.routers.integrations._get_connection",
        return_value=fake_conn,
    ) as mock_get_conn:
        client = _create_test_client()
        resp = client.post(
            "/api/v1/integrations/source/verify",
            json=_verify_body(),
            headers={"Accept": "text/event-stream"},
        )

    assert resp.status_code == 200, resp.text

    # CRITICAL: mock-patched _get_connection is never called — proves the verify
    # endpoint cannot transitively reach a DB write path.
    assert mock_get_conn.call_count == 0, (
        f"source_verify must NEVER call _get_connection — it must not persist "
        f"Integration rows, but _get_connection was called {mock_get_conn.call_count} time(s)"
    )

    events = _parse_sse_events(resp)

    # Expect exactly 2 events: dataset_result + complete
    assert len(events) == 2, f"expected 2 events, got {len(events)}: {events}"

    dr = events[0]
    assert dr.get("event") == "dataset_result"
    assert dr["data"]["dataset_id"] == "water_meters"
    assert dr["data"]["status"] == "ok"
    assert dr["data"]["row_count"] == 42
    assert dr["data"]["schema_match"] is True

    comp = events[1]
    assert comp.get("event") == "complete"
    assert comp["data"]["all_pass"] is True
    assert comp["data"]["failed_count"] == 0
    # CRITICAL: all_pass=true must include a verify_token for the server-side gate.
    assert "verify_token" in comp["data"], (
        "complete event with all_pass=true must include verify_token"
    )
    assert isinstance(comp["data"]["verify_token"], str)
    assert "." in comp["data"]["verify_token"], "verify_token must be dot-separated"


# ---------------------------------------------------------------------------
# Test 2: ProbeError → error result, no Integration row persisted
# ---------------------------------------------------------------------------


def test_verify_probe_error_streams_error_and_no_row_persisted():
    """POST with a config that triggers ProbeError → error event + all_pass=false.

    CRITICAL: also asserts that NO Integration row was written to the DB.
    The guard is mock_get_conn.call_count == 0: it proves that _get_connection
    (the shared helper used by the integrations router to persist Integration rows)
    was never called by source_verify, confirming it has no DB write path at all.

    In a unit-test context with a mocked DB, the call-count check is the truthful
    equivalent of "no Integration row was persisted" — a SELECT COUNT(*) on a mock
    always returns the fixed stub value and cannot detect real writes.
    """
    from scanner.adapters.http_probe import ProbeError

    fake_conn, _fake_cursor = _make_db_mock()

    with (
        patch(
            "scanner.adapters.http_probe.HttpProbeAdapter.probe",
            side_effect=ProbeError("auth_failed", "HTTP 401"),
        ),
        patch(
            "scanner.api.routers.integrations._get_connection",
            return_value=fake_conn,
        ) as mock_get_conn,
    ):
        client = _create_test_client()
        resp = client.post(
            "/api/v1/integrations/source/verify",
            json=_verify_body(),
            headers={"Accept": "text/event-stream"},
        )


    assert resp.status_code == 200, resp.text

    events = _parse_sse_events(resp)
    assert len(events) == 2, f"expected 2 events, got {len(events)}: {events}"

    dr = events[0]
    assert dr.get("event") == "dataset_result"
    assert dr["data"]["dataset_id"] == "water_meters"
    assert dr["data"]["status"] == "error"
    assert dr["data"]["code"] == "auth_failed"
    assert "401" in dr["data"]["message"]

    comp = events[1]
    assert comp.get("event") == "complete"
    assert comp["data"]["all_pass"] is False
    assert comp["data"]["failed_count"] == 1
    # CRITICAL: no verify_token should be present when all_pass=false.
    assert "verify_token" not in comp["data"], (
        "complete event with all_pass=false must NOT include a verify_token"
    )

    # CRITICAL: mock-patched _get_connection is never called — proves the verify
    # endpoint cannot transitively reach a DB write path.
    assert mock_get_conn.call_count == 0, (
        f"source_verify must NEVER call _get_connection — it must not persist Integration rows, "
        f"but _get_connection was called {mock_get_conn.call_count} time(s)"
    )


# ---------------------------------------------------------------------------
# Test 4: invalid secret_ref → 400
# ---------------------------------------------------------------------------


def test_verify_invalid_secret_ref_returns_400():
    """POST with an expired/unknown secret_ref must be rejected with 400."""
    _STASH.clear()  # ensure no stash refs exist

    body = _verify_body(secret_ref="stash_does_not_exist")
    client = _create_test_client()
    resp = client.post(
        "/api/v1/integrations/source/verify",
        json=body,
        headers={"Accept": "text/event-stream"},
    )

    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail", "")
    assert "secret_ref" in detail.lower()


# ---------------------------------------------------------------------------
# Test 3: empty datasets → 422
# ---------------------------------------------------------------------------


def test_verify_empty_datasets_returns_422():
    """POST with datasets=[] must be rejected with HTTP 422."""
    body = _verify_body()
    body["datasets"] = []

    client = _create_test_client()
    resp = client.post(
        "/api/v1/integrations/source/verify",
        json=body,
        headers={"Accept": "text/event-stream"},
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "datasets" in detail.lower() or "non-empty" in detail.lower()
