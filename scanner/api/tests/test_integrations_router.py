"""
Tests for the integrations router — specifically the manual probe-now
endpoint that marks a CUSTOM_SOURCE integration due and synchronously
runs ``run_due_probes()``.

Covers:
1. probe-now returns 404 when the integration doesn't exist
2. probe-now returns 404 for a non-CUSTOM_SOURCE integration
3. happy path — endpoint marks the row, calls the runner, and surfaces
   the runner's attempt count.
4. import sanity — the route is actually registered on the router.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_client() -> TestClient:
    """Build a FastAPI app with only the integrations router mounted.

    Mirrors the pattern in test_drivers_router.py: by mounting the
    router directly we sidestep the InternalAuth/ActingPrincipal
    middlewares, which is fine for unit tests of the router itself.
    """
    from scanner.api.routers.integrations import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _make_fake_conn(rowcount: int) -> MagicMock:
    """Build a MagicMock psycopg2 connection whose cursor (used as a
    context manager) reports the given ``rowcount`` after ``execute()``."""
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.rowcount = rowcount
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn


def test_probe_now_returns_404_for_unknown_or_non_custom_source():
    """rowcount=0 → integration row didn't match (missing OR wrong type)."""
    fake_conn = _make_fake_conn(rowcount=0)

    with patch(
        "scanner.api.routers.integrations._get_connection",
        return_value=fake_conn,
    ), patch(
        "scanner.api.routers.integrations.run_due_probes",
        return_value=0,
    ) as mock_runner:
        client = _create_test_client()
        resp = client.post("/api/v1/integrations/does-not-exist/probe-now")

    assert resp.status_code == 404
    assert "CUSTOM_SOURCE" in resp.json()["detail"]
    # Runner must NOT be called when the row didn't match.
    mock_runner.assert_not_called()
    # Connection should still be closed even when we 404.
    fake_conn.close.assert_called_once()


def test_probe_now_dispatches_to_runner_and_returns_count():
    """Happy path: row matches, commit, runner returns its count."""
    fake_conn = _make_fake_conn(rowcount=1)

    with patch(
        "scanner.api.routers.integrations._get_connection",
        return_value=fake_conn,
    ), patch(
        "scanner.api.routers.integrations.run_due_probes",
        return_value=2,
    ) as mock_runner:
        client = _create_test_client()
        resp = client.post("/api/v1/integrations/i1/probe-now")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"probes_attempted": 2}
    mock_runner.assert_called_once_with()
    fake_conn.commit.assert_called_once()
    fake_conn.close.assert_called_once()


def test_probe_now_route_is_registered():
    """Sanity check: the route is wired with the expected path/method."""
    from scanner.api.routers.integrations import router

    matches = [
        r for r in router.routes
        if "probe-now" in getattr(r, "path", "")
    ]
    assert matches, "probe-now route is not registered on the integrations router"
    route = matches[0]
    assert route.path == "/integrations/{integration_id}/probe-now"
    assert "POST" in route.methods
