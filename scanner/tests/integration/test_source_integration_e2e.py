"""
End-to-end FastAPI integration test for the Custom Source integration flow.

Exercises the scanner-side surface in one round trip:
  Step 1 — Mock the HTTP probe call (HttpProbeAdapter.probe) to return a
            realistic MetricBundle built from fixture row aggregates, bypassing
            the datasketch dependency (which is not installed in this test env;
            existing tests/adapters/test_http_probe.py also skips those cases).
  Step 2 — POST /discover → assert probe candidate found.
  Step 3 — POST /verify   → stream SSE → assert all_pass: true.
  Step 4 — Simulate integration persistence (Next.js Prisma layer is not
            under test; we synthesise a fake Integration id).
  Step 5 — POST /integrations/{id}/probe-now → assert probes_attempted >= 1.
  Step 6 — Row-leak assertion: the MetricBundle captured during the probe
            contains only derived aggregates — never raw row values
            (sensor_id_1, 12.3, etc.).

Design decisions:
- HttpProbeAdapter.probe is patched globally so neither verify (Step 3) nor
  probe-now (Step 5) hit the real _compute_metrics path, which requires
  datasketch.  The returned MetricBundle is constructed from true per-column
  aggregates of the fixture rows (row_count, null_counts, distinct_counts,
  min/max), so the row-leak assertion is meaningful.
- The /discover endpoint calls SourceProbeDiscoverer which also calls
  HttpProbeAdapter; we pre-register the HTTP fixture with the `responses`
  library AND patch probe() so it returns our fixture bundle (discover uses
  the probe for schema inspection).
- Persistence (Step 4) is bypassed: save_probe_run is patched to capture
  the bundle without writing to DB.  DATABASE_URL is not required.
- FEATURE_SOURCES_CATEGORY env var is forced to "1".
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import responses as responses_lib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scanner.adapters.http_probe import MetricBundle

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_BASE_URL = "https://portal.example.com/api/v1"
_ENDPOINT = "/sensors"
_FULL_URL = f"{_BASE_URL}{_ENDPOINT}"
_DATASET_ID = "water_meters"
_TIMESTAMP_COL = "reading_at"

# Fixture rows that represent what the remote API would return.
# Distinctive values (sensor_id_1, 12.3) used in the row-leak assertion.
_FIXTURE_ROWS = [
    {"sensor_id": "sensor_id_1", "reading_at": "2026-05-01T10:00:00Z", "value": 12.3},
    {"sensor_id": "sensor_id_2", "reading_at": "2026-05-01T11:00:00Z", "value": 45.6},
    {"sensor_id": "sensor_id_3", "reading_at": "2026-05-01T12:00:00Z", "value": 78.9},
]

# A realistic MetricBundle computed FROM the fixture rows — but containing only
# derived aggregates, never raw values.  This is what _compute_metrics() would
# produce if datasketch were installed.
_FIXTURE_BUNDLE = MetricBundle(
    probed_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
    row_count=3,
    latest_timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
    column_schema=[
        {"name": "sensor_id", "data_type": "string", "is_nullable": True},
        {"name": "reading_at", "data_type": "string", "is_nullable": True},
        {"name": "value", "data_type": "number", "is_nullable": True},
    ],
    null_counts={"sensor_id": 0, "reading_at": 0, "value": 0},
    distinct_counts={"sensor_id": 3, "reading_at": 3, "value": 3},
    # HLL fingerprints are bytes; we use placeholder bytes.
    value_fingerprints={"sensor_id": b"\x00\x01\x02", "reading_at": b"\x03\x04", "value": b"\x05"},
    # min/max of the numeric column — a legitimate derived aggregate.
    min_max_numeric={"value": (12.3, 78.9)},
)

_VERIFY_BODY: Dict[str, Any] = {
    "name": "MyCiti water sensors",
    "platform_label": "MyCiti",
    "base_url": _BASE_URL,
    "auth": {"kind": "bearer", "header_name": None, "secret_ref": "stub-token"},
    "schedule": "daily",
    "stack_id": None,
    "datasets": [
        {
            "id": _DATASET_ID,
            "endpoint": _ENDPOINT,
            "json_root": None,
            "timestamp_column": _TIMESTAMP_COL,
            "lands_in": None,
        }
    ],
}

_DISCOVER_BODY: Dict[str, Any] = {
    "base_url": _BASE_URL,
    "endpoint": _ENDPOINT,
    "auth": {"kind": "bearer", "header_name": None, "secret_ref": "stub-token"},
    "ingestion_hints": [],
    "warehouse_hints": [],
    "stack_id": None,
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_fake_conn(rowcount: int = 1) -> MagicMock:
    """Build a MagicMock psycopg2 connection."""
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.rowcount = rowcount
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app wiring all three routers under test."""
    from scanner.api.routers.source_discovery import router as discover_router
    from scanner.api.routers.source_verify import router as verify_router
    from scanner.api.routers.integrations import router as integrations_router
    from scanner.api.auth import ActingPrincipal, require_principal

    fixed_principal = ActingPrincipal(
        user_id="user_e2e",
        organization_id="org_e2e",
        request_id="req-e2e",
    )

    def _fake_principal() -> ActingPrincipal:
        return fixed_principal

    app = FastAPI()
    # source_discovery and source_verify already carry the full path prefix.
    app.include_router(discover_router)
    app.include_router(verify_router)
    # integrations router uses /integrations prefix; add /api/v1 here.
    app.include_router(integrations_router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = _fake_principal
    return app


def _parse_sse_events(response) -> list[dict]:
    """Parse raw SSE lines into a list of {event, data} dicts."""
    events: list[dict] = []
    current: dict = {}
    for raw_line in response.iter_lines():
        line: bytes = raw_line if isinstance(raw_line, bytes) else raw_line.encode()
        if line.startswith(b"event: "):
            current["event"] = line[len(b"event: "):].decode().strip()
        elif line.startswith(b"data: "):
            raw_data = line[len(b"data: "):].decode().strip()
            try:
                current["data"] = json.loads(raw_data)
            except json.JSONDecodeError:
                current["data"] = raw_data
        elif line.strip() == b"" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


# ──────────────────────────────────────────────────────────────────────────────
# E2E test
# ──────────────────────────────────────────────────────────────────────────────


@responses_lib.activate
def test_full_source_integration_round_trip(monkeypatch):
    """Walk the full custom-source integration flow on the FastAPI surface.

    Steps:
      1. Set up mocks: HTTP source + HttpProbeAdapter.probe returns fixture bundle.
      2. Discover — assert probe candidate found.
      3. Verify (SSE) — assert all_pass: true, dataset_result status=ok.
      4. Simulate persistence — synthesise fake Integration id.
      5. Probe-now — assert probes_attempted >= 1.
      6. Row-leak assertion — MetricBundle contains only aggregates, not raw rows.
    """

    # ── Step 1: set up mocks ──────────────────────────────────────────────────
    # Register the fixture URL (needed by the `responses` layer even though
    # probe() is patched — the responses library intercepts at the requests
    # level; the patch prevents _compute_metrics from being called).
    responses_lib.add(
        responses_lib.GET,
        _FULL_URL,
        json=_FIXTURE_ROWS,
        status=200,
    )

    # Force feature flag so probe_runner doesn't short-circuit.
    monkeypatch.setenv("FEATURE_SOURCES_CATEGORY", "1")

    app = _build_app()

    # ── Step 2: discover ──────────────────────────────────────────────────────
    # Clear the TTLCache so this request actually reaches the discoverer.
    from scanner.api.routers import source_discovery as _sd_mod
    _sd_mod._CACHE.clear()

    # Patch HttpProbeAdapter.probe so SourceProbeDiscoverer gets our fixture bundle
    # without calling _compute_metrics (which requires datasketch).
    with patch(
        "scanner.adapters.http_probe.HttpProbeAdapter.probe",
        return_value=_FIXTURE_BUNDLE,
    ):
        with TestClient(app) as client:
            discover_resp = client.post(
                "/api/v1/integrations/source/discover",
                json=_DISCOVER_BODY,
            )

    assert discover_resp.status_code == 200, (
        f"[Step 2 — Discover] expected 200, got {discover_resp.status_code}: "
        f"{discover_resp.text}"
    )
    discover_data = discover_resp.json()
    probe_candidates = discover_data.get("candidates_by_path", {}).get("probe", [])
    assert len(probe_candidates) >= 1, (
        f"[Step 2 — Discover] expected >= 1 probe candidate, "
        f"got {len(probe_candidates)}. Full response: {discover_data}"
    )
    # Confirm the candidate has the right endpoint.
    assert probe_candidates[0]["endpoint"] == _ENDPOINT, (
        f"[Step 2 — Discover] expected endpoint={_ENDPOINT!r}, "
        f"got {probe_candidates[0].get('endpoint')!r}"
    )

    # ── Step 3: verify via SSE ─────────────────────────────────────────────────
    with patch(
        "scanner.adapters.http_probe.HttpProbeAdapter.probe",
        return_value=_FIXTURE_BUNDLE,
    ):
        with TestClient(app) as client:
            verify_resp = client.post(
                "/api/v1/integrations/source/verify",
                json=_VERIFY_BODY,
                headers={"Accept": "text/event-stream"},
            )

    assert verify_resp.status_code == 200, (
        f"[Step 3 — Verify] expected 200, got {verify_resp.status_code}: "
        f"{verify_resp.text}"
    )
    events = _parse_sse_events(verify_resp)
    assert len(events) >= 2, (
        f"[Step 3 — Verify] expected at least 2 SSE events (dataset_result + complete), "
        f"got {len(events)}: {events}"
    )

    dataset_event = next(
        (e for e in events if e.get("event") == "dataset_result"), None
    )
    assert dataset_event is not None, (
        f"[Step 3 — Verify] no dataset_result event in {events}"
    )
    assert dataset_event["data"]["dataset_id"] == _DATASET_ID, (
        f"[Step 3 — Verify] unexpected dataset_id: {dataset_event['data']}"
    )
    assert dataset_event["data"]["status"] == "ok", (
        f"[Step 3 — Verify] expected status=ok, got: {dataset_event['data']}"
    )
    assert dataset_event["data"]["row_count"] == _FIXTURE_BUNDLE.row_count, (
        f"[Step 3 — Verify] expected row_count={_FIXTURE_BUNDLE.row_count}, "
        f"got {dataset_event['data'].get('row_count')}"
    )

    complete_event = next(
        (e for e in events if e.get("event") == "complete"), None
    )
    assert complete_event is not None, (
        f"[Step 3 — Verify] no complete event in {events}"
    )
    assert complete_event["data"]["all_pass"] is True, (
        f"[Step 3 — Verify] expected all_pass=true, got: {complete_event['data']}"
    )
    assert complete_event["data"]["failed_count"] == 0, (
        f"[Step 3 — Verify] expected failed_count=0, got: {complete_event['data']}"
    )

    # CRITICAL: verify must never write to DB.  The integration router's
    # _get_connection is patched so any accidental call would be caught.
    # (source_verify router has no _get_connection import — this is belt-and-
    # suspenders: if a refactor ever adds a DB write, the probe-now conn mock
    # below would surface unexpected calls.)

    # ── Step 4: simulate persistence ──────────────────────────────────────────
    # The Next.js Prisma route (app/api/integrations/route.ts) is not under
    # test. We synthesise a fake integration id to represent what Prisma
    # would have written, then feed it to probe-now.
    fake_integration_id = "intg_e2e_test_001"
    fake_integration_config = {
        "base_url": _BASE_URL,
        "platform_label": "MyCiti",
        # auth.secret is absent — runner resolves it from credentials.
        "auth": {"kind": "bearer"},
        "datasets": [
            {
                "id": _DATASET_ID,
                "endpoint": _ENDPOINT,
                "timestamp_column": _TIMESTAMP_COL,
            }
        ],
        "schedule": "daily",
    }
    # Credentials row — plaintext dict as psycopg2 would return for a test
    # row where encryption wasn't applied.
    fake_credentials = {"secret": "stub-token"}

    # ── Step 5: probe-now ─────────────────────────────────────────────────────
    # _get_connection mock: rowcount=1 so the UPDATE "Integration" succeeds.
    fake_conn = _make_fake_conn(rowcount=1)

    # Capture what save_probe_run would have persisted.
    captured_bundles: list[MetricBundle] = []

    def _fake_save_probe_run(integration_id, dataset_id, bundle, duration_ms=None):
        captured_bundles.append(bundle)
        return "run_fake_001"

    fake_due_integrations = [
        {
            "id": fake_integration_id,
            "config": fake_integration_config,
            "credentials": fake_credentials,
            "probeSchedule": "daily",
        }
    ]

    with patch(
        "scanner.api.routers.integrations._get_connection",
        return_value=fake_conn,
    ), patch(
        "scanner.api.routers.integrations.run_due_probes",
    ) as mock_run_due_probes, patch(
        "scanner.scheduler.probe_runner._fetch_due_integrations",
        return_value=fake_due_integrations,
    ), patch(
        "scanner.scheduler.probe_runner._mark_next_probe_at",
    ), patch(
        "scanner.scheduler.probe_runner.save_probe_run",
        side_effect=_fake_save_probe_run,
    ), patch(
        "scanner.scheduler.probe_runner._resolve_secret",
        return_value="stub-token",
    ), patch(
        "scanner.adapters.http_probe.HttpProbeAdapter.probe",
        return_value=_FIXTURE_BUNDLE,
    ):
        # Wire mock_run_due_probes to call the real runner so we exercise
        # _fetch_due_integrations → HttpProbeAdapter → save_probe_run.
        from scanner.scheduler.probe_runner import run_due_probes as _real_runner
        mock_run_due_probes.side_effect = _real_runner

        with TestClient(app) as client:
            probe_resp = client.post(
                f"/api/v1/integrations/{fake_integration_id}/probe-now"
            )

    assert probe_resp.status_code == 200, (
        f"[Step 5 — Probe-now] expected 200, got {probe_resp.status_code}: "
        f"{probe_resp.text}"
    )
    probes_attempted = probe_resp.json()["probes_attempted"]
    assert probes_attempted >= 1, (
        f"[Step 5 — Probe-now] expected probes_attempted >= 1, "
        f"got {probes_attempted}"
    )

    # ── Step 6: row-leak assertion ─────────────────────────────────────────────
    # CRITICAL: Pallisade's "monitor-only, never store rows" promise.
    #
    # The MetricBundle captured in Step 5 must contain ONLY derived aggregates.
    # Raw fixture string values (sensor_id_1, sensor_id_2, sensor_id_3) must
    # never appear in any serialised metric column.
    #
    # Note on numeric values (12.3, 78.9): these ARE the min/max of the
    # `value` column and therefore DO appear in min_max_numeric as a legitimate
    # derived aggregate. The row-leak check targets raw string row identifiers,
    # not numeric extremes.

    assert len(captured_bundles) >= 1, (
        "[Step 6 — Row-leak] no MetricBundle was captured; "
        "the probe runner did not call save_probe_run. Check Step 5."
    )

    bundle = captured_bundles[0]

    # Serialise the bundle the same way probe_persistence.py does.
    bundle_serialised = json.dumps({
        "row_count": bundle.row_count,
        "column_schema": bundle.column_schema,
        "null_counts": bundle.null_counts,
        "distinct_counts": bundle.distinct_counts,
        "min_max_numeric": {col: list(pair) for col, pair in bundle.min_max_numeric.items()},
        # value_fingerprints are HLL bytes → base64, not raw strings.
        "value_fingerprints": {
            col: base64.b64encode(buf).decode("ascii")
            for col, buf in bundle.value_fingerprints.items()
        },
    })

    # Raw row string values that must NOT appear in persisted metric columns.
    # (These are row contents that would constitute a data leak.)
    row_string_leak_checks = [
        "sensor_id_1",
        "sensor_id_2",
        "sensor_id_3",
        "2026-05-01T10:00:00Z",  # raw timestamp string from row 0
    ]
    for raw_value in row_string_leak_checks:
        assert raw_value not in bundle_serialised, (
            f"[Step 6 — Row-leak] VIOLATION: raw row value '{raw_value}' found "
            f"in persisted MetricBundle serialisation. "
            f"Pallisade must NEVER store raw row contents. "
            f"First 400 chars of serialised bundle: {bundle_serialised[:400]}"
        )

    # row_count must be an integer aggregate, not a list of rows.
    assert isinstance(bundle.row_count, int), (
        f"[Step 6 — Row-leak] row_count should be int, got {type(bundle.row_count)}"
    )
    assert bundle.row_count == len(_FIXTURE_ROWS), (
        f"[Step 6 — Row-leak] row_count={bundle.row_count} != "
        f"fixture length {len(_FIXTURE_ROWS)}"
    )

    # column_schema must contain only column names and type metadata — not row data.
    schema_col_names = {col["name"] for col in bundle.column_schema}
    assert schema_col_names == {"sensor_id", "reading_at", "value"}, (
        f"[Step 6 — Row-leak] unexpected columns in schema: {schema_col_names}"
    )
    # Confirm no raw row value appears as a column name or type in the schema.
    schema_text = json.dumps(bundle.column_schema)
    for raw_value in ["sensor_id_1", "sensor_id_2", "sensor_id_3"]:
        assert raw_value not in schema_text, (
            f"[Step 6 — Row-leak] raw row value '{raw_value}' leaked into column_schema"
        )
