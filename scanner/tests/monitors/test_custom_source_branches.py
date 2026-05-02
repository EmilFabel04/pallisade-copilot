"""Unit tests for the CUSTOM_SOURCE branches in each monitor type."""
from datetime import datetime, timedelta, timezone


def test_freshness_returns_alert_when_stale(monkeypatch):
    from scanner.monitors.freshness import _run_freshness_for_custom_source

    fake_run = {
        "latest_timestamp": datetime.now(timezone.utc) - timedelta(hours=48),
    }
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: fake_run,
    )
    result = _run_freshness_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "max_hours_since_update": 24},
    })
    assert result["status"] == "ALERT"


def test_freshness_returns_ok_when_fresh(monkeypatch):
    from scanner.monitors.freshness import _run_freshness_for_custom_source

    fake_run = {
        "latest_timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: fake_run,
    )
    result = _run_freshness_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "max_hours_since_update": 24},
    })
    assert result["status"] == "OK"


def test_volume_alerts_when_below_min(monkeypatch):
    from scanner.monitors.volume import _run_volume_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 5},
    )
    result = _run_volume_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "min_rows": 10},
    })
    assert result["status"] == "ALERT"
    assert result["value"] == 5.0


def test_volume_ok_within_range(monkeypatch):
    from scanner.monitors.volume import _run_volume_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 50},
    )
    result = _run_volume_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "min_rows": 10, "max_rows": 100},
    })
    assert result["status"] == "OK"


def test_null_check_alerts_when_rate_exceeds_threshold(monkeypatch):
    from scanner.monitors.null_check import _run_null_check_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 10, "null_counts": {"sensor": 3}},
    )
    result = _run_null_check_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "column": "sensor", "max_null_rate": 0.1},
    })
    assert result["status"] == "ALERT"
    assert result["value"] == 0.3


def test_null_check_ok_when_no_nulls(monkeypatch):
    from scanner.monitors.null_check import _run_null_check_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 10, "null_counts": {"sensor": 0}},
    )
    result = _run_null_check_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "column": "sensor", "max_null_rate": 0.05},
    })
    assert result["status"] == "OK"


def test_schema_alerts_on_added_column(monkeypatch):
    from scanner.monitors.schema import _run_schema_for_custom_source

    latest = {"column_schema": [
        {"name": "id", "data_type": "integer"},
        {"name": "new_col", "data_type": "string"},
    ]}
    previous = {"column_schema": [
        {"name": "id", "data_type": "integer"},
    ]}
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: latest,
    )
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.previous_probe_run_for",
        lambda i, d: previous,
    )
    result = _run_schema_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    })
    assert result["status"] == "ALERT"
    assert "new_col" in result["details"]["added"]


def test_schema_ok_when_baseline_only(monkeypatch):
    from scanner.monitors.schema import _run_schema_for_custom_source

    latest = {"column_schema": [{"name": "id", "data_type": "integer"}]}
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: latest,
    )
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.previous_probe_run_for",
        lambda i, d: None,
    )
    result = _run_schema_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    })
    assert result["status"] == "OK"
