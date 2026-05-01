"""Unit tests for MonitorExecutor's CUSTOM_SOURCE dispatch."""
from unittest.mock import patch

from scanner.monitors.base import MonitorStatus
from scanner.monitors.executor import MonitorExecutor


def test_executor_dispatches_freshness_to_custom_source_helper():
    executor = MonitorExecutor()
    task = {
        "integrationType": "CUSTOM_SOURCE",
        "monitorType": "freshness",
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "max_hours_since_update": 24},
    }

    fake_helper_result = {
        "status": "OK",
        "value": 1.5,
        "threshold": 24.0,
        "message": "1.5 hours since last record",
    }

    with patch(
        "scanner.monitors.freshness._run_freshness_for_custom_source",
        return_value=fake_helper_result,
    ) as helper:
        result = executor.run_monitor(task)

    assert helper.called
    helper.assert_called_once_with(task)
    assert result is not None
    assert result.status == MonitorStatus.PASS
    assert result.value == 1.5
    assert result.threshold == 24.0
    assert result.message == "1.5 hours since last record"
    assert result.monitor_type == "freshness"


def test_executor_maps_alert_to_fail():
    executor = MonitorExecutor()
    task = {
        "integrationType": "CUSTOM_SOURCE",
        "monitorType": "volume",
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "min_rows": 10},
    }

    fake_helper_result = {
        "status": "ALERT",
        "value": 5.0,
        "threshold": 10.0,
        "message": "row count below min",
    }

    with patch(
        "scanner.monitors.volume._run_volume_for_custom_source",
        return_value=fake_helper_result,
    ):
        result = executor.run_monitor(task)

    assert result.status == MonitorStatus.FAIL
    assert result.value == 5.0


def test_executor_dispatches_null_check_to_custom_source_helper():
    executor = MonitorExecutor()
    task = {
        "integrationType": "CUSTOM_SOURCE",
        "monitorType": "null_check",
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "column": "sensor", "max_null_rate": 0.1},
    }

    fake = {"status": "OK", "value": 0.05, "threshold": 0.1, "message": "ok"}
    with patch(
        "scanner.monitors.null_check._run_null_check_for_custom_source",
        return_value=fake,
    ) as helper:
        result = executor.run_monitor(task)

    assert helper.called
    assert result.status == MonitorStatus.PASS
    assert result.monitor_type == "null_check"


def test_executor_accepts_schema_or_schema_change_alias():
    executor = MonitorExecutor()
    base_task = {
        "integrationType": "CUSTOM_SOURCE",
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    }

    fake = {"status": "OK", "value": 0.0, "message": "no schema drift"}
    for monitor_type in ("schema", "schema_change"):
        task = {**base_task, "monitorType": monitor_type}
        with patch(
            "scanner.monitors.schema._run_schema_for_custom_source",
            return_value=fake,
        ) as helper:
            result = executor.run_monitor(task)

        assert helper.called
        assert result.status == MonitorStatus.PASS


def test_executor_returns_error_for_unsupported_custom_source_monitor_type():
    executor = MonitorExecutor()
    task = {
        "integrationType": "CUSTOM_SOURCE",
        "monitorType": "anomaly",  # not in the helper map
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    }

    result = executor.run_monitor(task)

    assert result is not None
    assert result.status == MonitorStatus.ERROR
    assert "anomaly" in result.message
    assert result.monitor_type == "anomaly"


def test_executor_returns_error_when_helper_raises():
    executor = MonitorExecutor()
    task = {
        "integrationType": "CUSTOM_SOURCE",
        "monitorType": "freshness",
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    }

    def boom(_):
        raise RuntimeError("kaboom")

    with patch(
        "scanner.monitors.freshness._run_freshness_for_custom_source",
        side_effect=boom,
    ):
        result = executor.run_monitor(task)

    assert result.status == MonitorStatus.ERROR
    assert "kaboom" in result.message


def test_executor_error_result_for_unknown_integration_type_envelope():
    executor = MonitorExecutor()
    task = {
        "integrationType": "MARTIAN_DB",
        "monitorType": "freshness",
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    }

    result = executor.run_monitor(task)

    assert result.status == MonitorStatus.ERROR
    assert "MARTIAN_DB" in result.message


def test_executor_uses_target_fqn_from_task_when_provided():
    executor = MonitorExecutor()
    task = {
        "integrationType": "CUSTOM_SOURCE",
        "monitorType": "freshness",
        "integrationId": "i1",
        "targetFqn": "custom_source:i1:dataset_a",
        "config": {"dataset_id": "dataset_a", "max_hours_since_update": 24},
    }

    fake = {"status": "OK", "value": 1.0, "threshold": 24.0, "message": "ok"}
    with patch(
        "scanner.monitors.freshness._run_freshness_for_custom_source",
        return_value=fake,
    ):
        result = executor.run_monitor(task)

    assert result.target_fqn == "custom_source:i1:dataset_a"
