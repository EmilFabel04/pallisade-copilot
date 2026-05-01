"""Test for probe persistence. Requires DATABASE_URL set to a test DB."""
import os
import pytest
from datetime import datetime, timezone

from scanner.adapters.http_probe import MetricBundle
from scanner.drivers.source.probe_persistence import save_probe_run, save_probe_failure


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping DB-dependent tests",
)


@pytest.fixture
def integration_id():
    """Create a temporary CUSTOM_SOURCE integration row, yield its id, clean up."""
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO "Integration" (id, type, name, "organizationId", config, status,
                                       "createdAt", "updatedAt")
            VALUES (gen_random_uuid()::text, 'CUSTOM_SOURCE', 'test-source',
                    (SELECT id FROM "Organization" LIMIT 1), '{}'::jsonb, 'ACTIVE',
                    NOW(), NOW())
            RETURNING id
        """)
        iid = cur.fetchone()[0]
    conn.commit()
    yield iid
    with conn.cursor() as cur:
        cur.execute('DELETE FROM "Integration" WHERE id = %s', (iid,))
    conn.commit()
    conn.close()


def test_save_probe_run_writes_metrics(integration_id):
    bundle = MetricBundle(
        probed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        row_count=10,
        latest_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        column_schema=[{"name": "id", "data_type": "integer", "is_nullable": False}],
        null_counts={"id": 0},
        distinct_counts={"id": 10},
        value_fingerprints={"id": b"\x00\x01"},
        min_max_numeric={"id": (1.0, 10.0)},
    )
    run_id = save_probe_run(integration_id, "water_meters", bundle, duration_ms=42)
    assert run_id


def test_save_probe_failure_writes_error(integration_id):
    run_id = save_probe_failure(
        integration_id, "water_meters",
        error_code="auth_failed", error_message="HTTP 401",
        duration_ms=10,
    )
    assert run_id
