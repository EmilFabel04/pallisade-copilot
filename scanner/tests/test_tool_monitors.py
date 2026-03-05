"""Tests for tool monitors (Fivetran, Airflow, dbt Cloud)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scanner.monitors.base import MonitorStatus
from scanner.monitors.tools import (
    SyncLagMonitor,
    FailedSyncsMonitor,
    DagLastRunMonitor,
    DagScheduleLagMonitor,
    TaskFailureRateMonitor,
    DbtTestFailuresMonitor,
    DbtModelFreshnessMonitor,
    TOOL_MONITOR_TYPES,
    TOOL_MONITOR_REGISTRY,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestToolMonitorRegistry:
    def test_all_types_in_registry(self):
        for t in TOOL_MONITOR_TYPES:
            assert t in TOOL_MONITOR_REGISTRY, f"{t} missing from registry"

    def test_registry_has_correct_classes(self):
        assert TOOL_MONITOR_REGISTRY["sync_lag"] is SyncLagMonitor
        assert TOOL_MONITOR_REGISTRY["dag_last_run"] is DagLastRunMonitor
        assert TOOL_MONITOR_REGISTRY["dbt_test_failures"] is DbtTestFailuresMonitor


# ---------------------------------------------------------------------------
# SyncLagMonitor
# ---------------------------------------------------------------------------


def _make_connector(
    *,
    name="test-conn",
    service="postgres",
    status=None,
    paused=False,
    hours_since_success=0.5,
    sync_frequency=360,
    succeeded_at=None,
    failed_at=None,
):
    from scanner.integrations.fivetran import ConnectorStatus

    conn = MagicMock()
    conn.name = name
    conn.service = service
    conn.status = status or ConnectorStatus.CONNECTED
    conn.paused = paused
    conn.hours_since_success = hours_since_success
    conn.sync_frequency = sync_frequency
    conn.succeeded_at = succeeded_at or datetime.now(timezone.utc)
    conn.failed_at = failed_at
    return conn


class TestSyncLagMonitor:
    def test_pass_healthy_connector(self):
        integration = MagicMock()
        integration.get_connector.return_value = _make_connector(
            hours_since_success=0.5, sync_frequency=360
        )

        monitor = SyncLagMonitor({"connector_id": "abc123"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.PASS
        assert "30" in result.message  # 0.5h = 30 min

    def test_fail_broken_connector(self):
        from scanner.integrations.fivetran import ConnectorStatus

        integration = MagicMock()
        integration.get_connector.return_value = _make_connector(
            status=ConnectorStatus.BROKEN
        )

        monitor = SyncLagMonitor({"connector_id": "abc123"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.FAIL
        assert "BROKEN" in result.message

    def test_fail_paused_connector(self):
        integration = MagicMock()
        integration.get_connector.return_value = _make_connector(paused=True)

        monitor = SyncLagMonitor({"connector_id": "abc123"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.FAIL
        assert "PAUSED" in result.message

    def test_warn_slightly_stale(self):
        # sync_frequency=60 min, warn_multiplier=1.5 → warn at 90 min
        # 2h = 120 min → above warn (90) but below fail (180)
        integration = MagicMock()
        integration.get_connector.return_value = _make_connector(
            hours_since_success=2.0, sync_frequency=60
        )

        monitor = SyncLagMonitor({"connector_id": "abc123"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.WARN

    def test_fail_very_stale(self):
        # sync_frequency=60 min, fail_multiplier=3.0 → fail at 180 min
        # 4h = 240 min → above fail threshold
        integration = MagicMock()
        integration.get_connector.return_value = _make_connector(
            hours_since_success=4.0, sync_frequency=60
        )

        monitor = SyncLagMonitor({"connector_id": "abc123"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.FAIL

    def test_error_missing_connector_id(self):
        integration = MagicMock()
        monitor = SyncLagMonitor({})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.ERROR
        assert "connector_id" in result.message

    def test_error_connector_not_found(self):
        integration = MagicMock()
        integration.get_connector.return_value = None

        monitor = SyncLagMonitor({"connector_id": "missing"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.ERROR

    def test_custom_max_lag(self):
        integration = MagicMock()
        integration.get_connector.return_value = _make_connector(
            hours_since_success=1.0, sync_frequency=360
        )

        # 1h = 60 min, max_lag_minutes=30 → fail_threshold=60 → exactly at threshold
        monitor = SyncLagMonitor({"connector_id": "abc", "max_lag_minutes": 30})
        result = monitor.execute(integration)

        # 60 min > 30 min warn threshold
        assert result.status in (MonitorStatus.WARN, MonitorStatus.FAIL)


# ---------------------------------------------------------------------------
# DagLastRunMonitor
# ---------------------------------------------------------------------------


def _make_dag_run(state, run_id="run1", execution_date=None, end_date=None, start_date=None):
    run = MagicMock()
    run.state = state
    run.run_id = run_id
    run.execution_date = execution_date or datetime.now(timezone.utc)
    run.end_date = end_date
    run.start_date = start_date or datetime.now(timezone.utc)
    return run


class TestDagLastRunMonitor:
    def test_pass_successful_run(self):
        from scanner.integrations.airflow import DAGState

        integration = MagicMock()
        integration.get_dag_runs.return_value = [
            _make_dag_run(DAGState.SUCCESS, end_date=datetime.now(timezone.utc))
        ]

        monitor = DagLastRunMonitor({"dag_id": "my_dag"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.PASS

    def test_fail_failed_run(self):
        from scanner.integrations.airflow import DAGState

        integration = MagicMock()
        integration.get_dag_runs.return_value = [_make_dag_run(DAGState.FAILED)]
        integration.get_task_instances.return_value = []

        monitor = DagLastRunMonitor({"dag_id": "my_dag"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.FAIL
        assert "FAILED" in result.message

    def test_warn_no_runs(self):
        integration = MagicMock()
        integration.get_dag_runs.return_value = []

        monitor = DagLastRunMonitor({"dag_id": "my_dag"})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.WARN

    def test_warn_stale_run(self):
        from scanner.integrations.airflow import DAGState

        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        integration = MagicMock()
        integration.get_dag_runs.return_value = [
            _make_dag_run(DAGState.SUCCESS, end_date=old_time)
        ]

        monitor = DagLastRunMonitor({"dag_id": "my_dag", "max_stale_hours": 24})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.WARN
        assert "48" in result.message or "ago" in result.message

    def test_error_missing_dag_id(self):
        integration = MagicMock()
        monitor = DagLastRunMonitor({})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.ERROR


# ---------------------------------------------------------------------------
# DagScheduleLagMonitor
# ---------------------------------------------------------------------------


class TestDagScheduleLagMonitor:
    def test_pass_on_schedule(self):
        from scanner.integrations.airflow import DAGState

        now = datetime.now(timezone.utc)
        integration = MagicMock()
        run = _make_dag_run(DAGState.SUCCESS)
        run.execution_date = now - timedelta(minutes=5)
        run.start_date = now
        integration.get_dag_runs.return_value = [run]

        monitor = DagScheduleLagMonitor({"dag_id": "my_dag", "max_lag_minutes": 30})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.PASS

    def test_fail_behind_schedule(self):
        from scanner.integrations.airflow import DAGState

        now = datetime.now(timezone.utc)
        integration = MagicMock()
        run = _make_dag_run(DAGState.SUCCESS)
        run.execution_date = now - timedelta(minutes=60)
        run.start_date = now
        integration.get_dag_runs.return_value = [run]

        monitor = DagScheduleLagMonitor({"dag_id": "my_dag", "max_lag_minutes": 30})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.FAIL


# ---------------------------------------------------------------------------
# TaskFailureRateMonitor
# ---------------------------------------------------------------------------


class TestTaskFailureRateMonitor:
    def test_pass_no_failures(self):
        from scanner.integrations.airflow import DAGState

        now = datetime.now(timezone.utc)
        integration = MagicMock()
        runs = [_make_dag_run(DAGState.SUCCESS, start_date=now) for _ in range(5)]
        integration.get_dag_runs.return_value = runs

        monitor = TaskFailureRateMonitor({"dag_id": "d", "lookback_hours": 24})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.PASS
        assert result.details["failure_rate_pct"] == 0.0

    def test_fail_high_rate(self):
        from scanner.integrations.airflow import DAGState

        now = datetime.now(timezone.utc)
        integration = MagicMock()
        runs = [
            _make_dag_run(DAGState.FAILED, start_date=now),
            _make_dag_run(DAGState.FAILED, start_date=now),
            _make_dag_run(DAGState.SUCCESS, start_date=now),
        ]
        integration.get_dag_runs.return_value = runs

        monitor = TaskFailureRateMonitor({"dag_id": "d", "max_failure_pct": 10})
        result = monitor.execute(integration)

        assert result.status == MonitorStatus.FAIL
        assert result.details["failure_rate_pct"] > 60


# ---------------------------------------------------------------------------
# DbtTestFailuresMonitor
# ---------------------------------------------------------------------------


class TestDbtTestFailuresMonitor:
    def test_pass_all_tests_pass(self):
        client = MagicMock()
        client.get_job_runs.return_value = [
            {"id": 100, "status": 10, "status_humanized": "Success", "started_at": "2025-01-01", "finished_at": "2025-01-01"}
        ]
        client.get_test_results.return_value = {
            "total_tests": 10, "passed": 10, "failed": 0, "warned": 0, "skipped": 0, "tests": []
        }

        monitor = DbtTestFailuresMonitor({"job_id": 42})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.PASS
        assert "10" in result.message

    def test_fail_tests_failed(self):
        client = MagicMock()
        client.get_job_runs.return_value = [
            {"id": 100, "status": 10, "status_humanized": "Success", "started_at": "2025-01-01", "finished_at": "2025-01-01"}
        ]
        client.get_test_results.return_value = {
            "total_tests": 10, "passed": 8, "failed": 2, "warned": 0, "skipped": 0,
            "tests": [
                {"name": "test_not_null_id", "status": "fail"},
                {"name": "test_unique_email", "status": "fail"},
            ],
        }

        monitor = DbtTestFailuresMonitor({"job_id": 42})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.FAIL
        assert result.value == 2.0
        assert "test_not_null_id" in result.message

    def test_fail_run_errored(self):
        client = MagicMock()
        client.get_job_runs.return_value = [
            {"id": 100, "status": 20, "status_humanized": "Error", "status_message": "git error"}
        ]

        monitor = DbtTestFailuresMonitor({"job_id": 42})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.FAIL
        assert "failed" in result.message.lower() or "Error" in result.message

    def test_warn_no_runs(self):
        client = MagicMock()
        client.get_job_runs.return_value = []

        monitor = DbtTestFailuresMonitor({"job_id": 42})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.WARN

    def test_warn_include_warnings(self):
        client = MagicMock()
        client.get_job_runs.return_value = [
            {"id": 100, "status": 10, "status_humanized": "Success", "started_at": "2025-01-01", "finished_at": "2025-01-01"}
        ]
        client.get_test_results.return_value = {
            "total_tests": 5, "passed": 3, "failed": 0, "warned": 2, "skipped": 0, "tests": []
        }

        monitor = DbtTestFailuresMonitor({"job_id": 42, "include_warnings": True})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.WARN

    def test_error_missing_job_id(self):
        client = MagicMock()
        monitor = DbtTestFailuresMonitor({})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.ERROR


# ---------------------------------------------------------------------------
# DbtModelFreshnessMonitor
# ---------------------------------------------------------------------------


class TestDbtModelFreshnessMonitor:
    def test_pass_fresh(self):
        client = MagicMock()
        finished = datetime.now(timezone.utc).isoformat()
        client.get_job_runs.return_value = [
            {"id": 1, "finished_at": finished}
        ]

        monitor = DbtModelFreshnessMonitor({"job_id": 42, "max_hours": 24})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.PASS

    def test_fail_stale(self):
        client = MagicMock()
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        client.get_job_runs.return_value = [
            {"id": 1, "finished_at": old}
        ]

        monitor = DbtModelFreshnessMonitor({"job_id": 42, "max_hours": 24})
        result = monitor.execute(client)

        assert result.status == MonitorStatus.FAIL
