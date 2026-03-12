"""Tests for health watch aggregation."""

import pytest
from ..health import (
    MonitorSignal,
    FailureGroup,
    HealthReport,
    compute_health_score,
    health_status_from_score,
    group_failures,
    generate_summary,
    compute_health_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(
    status: str = "PASS",
    monitor_type: str = "FRESHNESS",
    depth: int = 0,
    priority: int = 2,
    name: str = "test_monitor",
    fqn: str = "proj.raw.table",
) -> MonitorSignal:
    return MonitorSignal(
        monitor_id="m1",
        monitor_name=name,
        monitor_type=monitor_type,
        target_fqn=fqn,
        status=status,
        depth=depth,
        priority=priority,
    )


# ---------------------------------------------------------------------------
# compute_health_score tests
# ---------------------------------------------------------------------------

class TestComputeHealthScore:

    def test_all_pass_returns_100(self):
        signals = [_signal("PASS"), _signal("PASS"), _signal("PASS")]
        assert compute_health_score(signals) == 100.0

    def test_empty_signals_returns_100(self):
        assert compute_health_score([]) == 100.0

    def test_all_fail_returns_0(self):
        signals = [_signal("FAIL"), _signal("FAIL")]
        assert compute_health_score(signals) == 0.0

    def test_all_warn_returns_50(self):
        signals = [_signal("WARN"), _signal("WARN")]
        assert compute_health_score(signals) == 50.0

    def test_mixed_pass_fail(self):
        # Equal weight signals: one PASS (1.0), one FAIL (0.0) = 50%
        signals = [
            _signal("PASS", depth=1, priority=2),
            _signal("FAIL", depth=1, priority=2),
        ]
        assert compute_health_score(signals) == 50.0

    def test_direct_fail_weighs_more_than_upstream(self):
        """A FAIL on the anchor (depth=0, mult=2.0) should produce a lower
        score than a FAIL at depth=2 (mult=1.0)."""
        direct_fail = [
            _signal("FAIL", depth=0, priority=1),
            _signal("PASS", depth=1, priority=2),
        ]
        upstream_fail = [
            _signal("PASS", depth=0, priority=1),
            _signal("FAIL", depth=2, priority=2),
        ]
        assert compute_health_score(direct_fail) < compute_health_score(upstream_fail)

    def test_high_priority_fail_weighs_more(self):
        """P1 FAIL should produce lower score than P3 FAIL (same depth)."""
        p1_fail = [
            _signal("FAIL", depth=0, priority=1),
            _signal("PASS", depth=0, priority=1),
        ]
        p3_fail = [
            _signal("FAIL", depth=0, priority=3),
            _signal("PASS", depth=0, priority=3),
        ]
        assert compute_health_score(p1_fail) == compute_health_score(p3_fail)
        # Same because equal mix — but let's test with asymmetric
        p1_heavy = [
            _signal("FAIL", depth=0, priority=1),
            _signal("PASS", depth=0, priority=3),
        ]
        p3_heavy = [
            _signal("FAIL", depth=0, priority=3),
            _signal("PASS", depth=0, priority=1),
        ]
        # P1 FAIL with P3 PASS: weighted toward the fail
        # P3 FAIL with P1 PASS: weighted toward the pass
        assert compute_health_score(p1_heavy) < compute_health_score(p3_heavy)

    def test_skipped_counts_as_partial(self):
        signals = [_signal("SKIPPED")]
        assert compute_health_score(signals) == 80.0


# ---------------------------------------------------------------------------
# health_status_from_score tests
# ---------------------------------------------------------------------------

class TestHealthStatusFromScore:

    def test_healthy(self):
        assert health_status_from_score(100) == "healthy"
        assert health_status_from_score(90) == "healthy"

    def test_degraded(self):
        assert health_status_from_score(89.9) == "degraded"
        assert health_status_from_score(70) == "degraded"

    def test_at_risk(self):
        assert health_status_from_score(69.9) == "at_risk"
        assert health_status_from_score(40) == "at_risk"

    def test_unhealthy(self):
        assert health_status_from_score(39.9) == "unhealthy"
        assert health_status_from_score(0) == "unhealthy"


# ---------------------------------------------------------------------------
# group_failures tests
# ---------------------------------------------------------------------------

class TestGroupFailures:

    def test_no_failures_returns_empty(self):
        signals = [_signal("PASS"), _signal("PASS")]
        assert group_failures(signals) == []

    def test_single_fail_grouped(self):
        signals = [_signal("FAIL", monitor_type="FRESHNESS")]
        groups = group_failures(signals)
        assert len(groups) == 1
        assert groups[0].category == "stale_data"
        assert groups[0].severity == "critical"
        assert groups[0].signal_count == 1

    def test_warn_severity(self):
        signals = [_signal("WARN", monitor_type="VOLUME")]
        groups = group_failures(signals)
        assert len(groups) == 1
        assert groups[0].severity == "warning"

    def test_multiple_categories(self):
        signals = [
            _signal("FAIL", monitor_type="FRESHNESS"),
            _signal("FAIL", monitor_type="SYNC_LAG"),
            _signal("WARN", monitor_type="DBT_TEST_FAILURES"),
        ]
        groups = group_failures(signals)
        categories = {g.category for g in groups}
        assert "stale_data" in categories
        assert "ingestion_lag" in categories
        assert "transform_failure" in categories

    def test_same_category_grouped(self):
        signals = [
            _signal("FAIL", monitor_type="FRESHNESS", name="m1", fqn="a.b.c"),
            _signal("FAIL", monitor_type="DBT_MODEL_FRESHNESS", name="m2", fqn="d.e.f"),
        ]
        groups = group_failures(signals)
        stale = next(g for g in groups if g.category == "stale_data")
        assert stale.signal_count == 2

    def test_critical_sorted_first(self):
        signals = [
            _signal("WARN", monitor_type="VOLUME"),
            _signal("FAIL", monitor_type="SYNC_LAG"),
        ]
        groups = group_failures(signals)
        assert groups[0].severity == "critical"

    def test_root_cause_hint_is_deepest(self):
        signals = [
            _signal("FAIL", monitor_type="FRESHNESS", depth=1, fqn="shallow.table"),
            _signal("FAIL", monitor_type="DBT_MODEL_FRESHNESS", depth=3, fqn="deep.table"),
        ]
        groups = group_failures(signals)
        stale = next(g for g in groups if g.category == "stale_data")
        assert stale.root_cause_hint == "deep.table"


# ---------------------------------------------------------------------------
# generate_summary tests
# ---------------------------------------------------------------------------

class TestGenerateSummary:

    def test_no_failures(self):
        summary = generate_summary("orders", "healthy", [])
        assert summary == "orders is healthy"

    def test_single_failure(self):
        groups = [FailureGroup("stale_data", "critical", "m1: FAIL", "a.b", 1)]
        summary = generate_summary("orders", "at_risk", groups)
        assert "orders is at_risk" in summary
        assert "stale data" in summary

    def test_multiple_signals(self):
        groups = [
            FailureGroup("stale_data", "critical", "m1: FAIL", "a.b", 2),
            FailureGroup("ingestion_lag", "warning", "m2: WARN", "c.d", 1),
        ]
        summary = generate_summary("dashboard", "degraded", groups)
        assert "3 signals" in summary


# ---------------------------------------------------------------------------
# compute_health_report integration tests
# ---------------------------------------------------------------------------

class TestComputeHealthReport:

    def test_healthy_watch(self):
        signals = [
            _signal("PASS", depth=0, priority=1),
            _signal("PASS", depth=1, priority=2),
            _signal("PASS", depth=2, priority=3),
        ]
        report = compute_health_report(signals, "orders", coverage_pct=0.85)
        assert report.health_score == 100.0
        assert report.health_status == "healthy"
        assert report.direct_status == "pass"
        assert report.upstream_status == "pass"
        assert report.coverage_pct == 0.85
        assert len(report.failure_groups) == 0
        assert "orders is healthy" in report.summary

    def test_single_fail_on_anchor(self):
        signals = [
            _signal("FAIL", depth=0, priority=1),
            _signal("PASS", depth=1, priority=2),
        ]
        report = compute_health_report(signals, "dashboard")
        assert report.health_score < 50  # Direct P1 FAIL heavily weighted
        assert report.health_status in ("at_risk", "unhealthy")
        assert report.direct_status == "fail"
        assert report.upstream_status == "pass"
        assert len(report.failure_groups) >= 1

    def test_warn_on_upstream(self):
        signals = [
            _signal("PASS", depth=0, priority=1),
            _signal("WARN", monitor_type="SYNC_LAG", depth=2, priority=3),
        ]
        report = compute_health_report(signals, "table")
        assert report.health_score > 70  # Mild degradation
        assert report.direct_status == "pass"
        assert report.upstream_status == "warn"  # Single WARN upstream = warn

    def test_to_dict_shape(self):
        signals = [_signal("PASS")]
        report = compute_health_report(signals, "orders")
        d = report.to_dict()
        assert "healthScore" in d
        assert "healthStatus" in d
        assert "summary" in d
        assert "directStatus" in d
        assert "upstreamStatus" in d
        assert "coveragePct" in d
        assert "failureGroups" in d
        assert "computedAt" in d

    def test_empty_signals(self):
        report = compute_health_report([], "empty_watch")
        assert report.health_score == 100.0
        assert report.health_status == "healthy"
        assert report.direct_status == "none"
        assert report.upstream_status == "none"
