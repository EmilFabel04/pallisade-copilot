"""Tests for tool monitor enrichment: consecutive failure, recovery, SLA breach (Stage 7A-7C)."""

from datetime import datetime, timedelta, timezone

from scanner.monitors.base import MonitorResult, MonitorStatus
from scanner.monitors.tools import enrich_tool_result


def _make_result(status: str = "fail", message: str = "Some failure") -> MonitorResult:
    return MonitorResult(
        monitor_type="dag_last_run",
        target_fqn="airflow:etl_pipeline",
        status=MonitorStatus(status),
        message=message,
        details={"dag_id": "etl_pipeline"},
    )


class TestConsecutiveFailure:
    """Stage 7A: Consecutive failure escalation."""

    def test_escalation_at_threshold(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL", "FAIL", "PASS"],
            "consecutive_fail_escalate": 3,
        })
        assert "ESCALATED" in enriched.message
        assert enriched.details["escalated"] is True
        assert enriched.details["consecutive_failures"] == 4  # 3 + current

    def test_no_escalation_below_threshold(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "PASS"],
            "consecutive_fail_escalate": 3,
        })
        assert "ESCALATED" not in enriched.message
        assert enriched.details.get("escalated") is None
        assert enriched.details["failure_streak"] == 1

    def test_no_escalation_on_pass(self):
        result = _make_result("pass", "DAG succeeded")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL", "FAIL"],
            "consecutive_fail_escalate": 3,
        })
        assert "ESCALATED" not in enriched.message

    def test_custom_threshold(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL", "FAIL", "FAIL", "FAIL"],
            "consecutive_fail_escalate": 5,
        })
        assert enriched.details["escalated"] is True
        assert enriched.details["consecutive_failures"] == 6

    def test_streak_count_stops_at_first_pass(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL", "PASS", "FAIL", "FAIL"],
        })
        assert enriched.details["failure_streak"] == 2

    def test_empty_recent_statuses(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": [],
        })
        assert enriched.message == result.message  # unchanged


class TestRecovery:
    """Stage 7B: Recovery event detection."""

    def test_recovery_detected(self):
        result = _make_result("pass", "DAG succeeded")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL", "FAIL"],
        })
        assert "RECOVERED" in enriched.message
        assert enriched.details["recovery"] is True
        assert enriched.details["recovered_after"] == 3

    def test_no_recovery_when_previously_passing(self):
        result = _make_result("pass", "DAG succeeded")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["PASS", "PASS"],
        })
        assert "RECOVERED" not in enriched.message
        assert enriched.details.get("recovery") is None

    def test_recovery_after_single_failure(self):
        result = _make_result("pass", "DAG succeeded")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "PASS", "PASS"],
        })
        assert "RECOVERED" in enriched.message
        assert enriched.details["recovered_after"] == 1


class TestSLABreach:
    """Stage 7C: SLA breach duration tracking."""

    def test_breach_duration_calculated(self):
        first_fail = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL"],
            "first_failure_at": first_fail,
        })
        assert "in breach" in enriched.message
        assert abs(enriched.details["breach_hours"] - 12.0) < 0.5

    def test_no_breach_on_pass(self):
        first_fail = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        result = _make_result("pass", "DAG succeeded")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL"],
            "first_failure_at": first_fail,
        })
        assert "in breach" not in enriched.message

    def test_no_breach_without_first_failure_at(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL"],
        })
        assert "in breach" not in enriched.message

    def test_invalid_first_failure_at_ignored(self):
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL"],
            "first_failure_at": "not-a-date",
        })
        assert "in breach" not in enriched.message


class TestCombined:
    """Combined scenarios."""

    def test_escalation_with_breach(self):
        first_fail = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        result = _make_result("fail")
        enriched = enrich_tool_result(result, {
            "recent_statuses": ["FAIL", "FAIL", "FAIL", "FAIL"],
            "consecutive_fail_escalate": 3,
            "first_failure_at": first_fail,
        })
        assert "ESCALATED" in enriched.message
        assert "in breach" in enriched.message
        assert enriched.details["escalated"] is True
        assert abs(enriched.details["breach_hours"] - 24.0) < 0.5
