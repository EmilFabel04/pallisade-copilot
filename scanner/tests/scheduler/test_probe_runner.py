import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


def test_run_due_probes_picks_up_integrations_with_due_next_probe(monkeypatch):
    from scanner.scheduler.probe_runner import run_due_probes

    fake_integration = {
        "id": "i1",
        "config": {
            "base_url": "https://api.example.com/v1",
            "auth": {"kind": "bearer", "secret": "t"},
            "datasets": [{
                "id": "d1", "endpoint": "/r", "timestamp_column": "t",
            }],
            "platform_label": "Test",
        },
        "probeSchedule": "hourly",
    }

    fake_bundle = MagicMock()
    fake_bundle.row_count = 0

    with patch("scanner.scheduler.probe_runner._fetch_due_integrations") as fetch, \
         patch("scanner.scheduler.probe_runner._mark_next_probe_at") as mark, \
         patch("scanner.scheduler.probe_runner._resolve_secret", return_value="t"), \
         patch("scanner.scheduler.probe_runner.HttpProbeAdapter") as MockAdapter, \
         patch("scanner.scheduler.probe_runner.save_probe_run") as save:
        fetch.return_value = [fake_integration]
        MockAdapter.return_value.probe.return_value = fake_bundle

        n = run_due_probes()

        assert n == 1
        assert MockAdapter.called
        assert save.called
        assert mark.called
