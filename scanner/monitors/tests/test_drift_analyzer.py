"""Tests for drift_analyzer statistical helpers."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from scanner.monitors.drift_analyzer import (
    compute_freshness_stats,
    compute_volume_stats,
    compute_quality_stats,
    compute_uniqueness_stats,
    compute_schema_stats,
    compute_anomaly_stats,
)


def _make_run(value: float, status: str = "PASS", ts_offset_days: int = 0, details: dict | None = None) -> dict:
    return {
        "value": value,
        "status": status,
        "completedAt": datetime.now(timezone.utc) - timedelta(days=ts_offset_days),
        "details": details or {},
    }


class TestComputeFreshnessStats:
    def test_basic_stats(self):
        runs = [_make_run(1.0, ts_offset_days=i) for i in range(10)]
        stats = compute_freshness_stats(runs)
        assert stats["mean"] == pytest.approx(1.0)
        assert stats["p95"] == pytest.approx(1.0)
        assert stats["count"] == 10

    def test_empty_runs(self):
        stats = compute_freshness_stats([])
        assert stats["count"] == 0
        assert stats["mean"] is None

    def test_trend_detection(self):
        runs = [_make_run(float(i), ts_offset_days=9 - i) for i in range(10)]
        stats = compute_freshness_stats(runs)
        assert stats["trend_slope"] > 0


class TestComputeVolumeStats:
    def test_stable_volume(self):
        runs = [_make_run(1000.0, ts_offset_days=i) for i in range(10)]
        stats = compute_volume_stats(runs)
        assert stats["mean"] == pytest.approx(1000.0)
        assert stats["growth_rate"] == pytest.approx(0.0, abs=0.01)

    def test_growing_volume(self):
        runs = [_make_run(1000.0 + i * 100, ts_offset_days=9 - i) for i in range(10)]
        stats = compute_volume_stats(runs)
        assert stats["trend_slope"] > 0


class TestComputeQualityStats:
    def test_stable_null_rate(self):
        runs = [_make_run(0.02, ts_offset_days=i, details={"null_rate": 0.02}) for i in range(10)]
        stats = compute_quality_stats(runs)
        assert stats["mean_null_rate"] == pytest.approx(0.02)

    def test_sudden_shift(self):
        runs = [_make_run(0.01, ts_offset_days=19 - i, details={"null_rate": 0.01}) for i in range(18)]
        runs += [_make_run(0.20, ts_offset_days=1, details={"null_rate": 0.20})]
        runs += [_make_run(0.20, ts_offset_days=0, details={"null_rate": 0.20})]
        stats = compute_quality_stats(runs)
        assert stats["shift_detected"] is True


class TestComputeUniquenessStats:
    def test_stable_duplicate_rate(self):
        runs = [_make_run(0.005, ts_offset_days=i, details={"duplicate_rate": 0.005}) for i in range(10)]
        stats = compute_uniqueness_stats(runs)
        assert stats["mean_duplicate_rate"] == pytest.approx(0.005)

    def test_empty_runs(self):
        stats = compute_uniqueness_stats([])
        assert stats["count"] == 0


class TestComputeSchemaStats:
    def test_no_changes(self):
        runs = [_make_run(0, status="PASS", ts_offset_days=i) for i in range(10)]
        stats = compute_schema_stats(runs)
        assert stats["change_count"] == 0

    def test_with_changes(self):
        runs = [_make_run(0, status="PASS", ts_offset_days=i) for i in range(8)]
        runs += [_make_run(1, status="FAIL", ts_offset_days=1, details={"columns_added": ["new_col"]})]
        runs += [_make_run(1, status="FAIL", ts_offset_days=0, details={"columns_added": ["another"]})]
        stats = compute_schema_stats(runs)
        assert stats["change_count"] == 2


class TestComputeAnomalyStats:
    def test_no_false_positives(self):
        runs = [_make_run(1.0, status="FAIL", details={"raw_status": "FAIL", "adjusted_status": "FAIL"}) for _ in range(5)]
        stats = compute_anomaly_stats(runs)
        assert stats["false_positive_rate"] == pytest.approx(0.0)

    def test_all_false_positives(self):
        runs = [_make_run(1.0, status="WARN", details={"raw_status": "FAIL", "adjusted_status": "PASS"}) for _ in range(5)]
        stats = compute_anomaly_stats(runs)
        assert stats["false_positive_rate"] == pytest.approx(1.0)
