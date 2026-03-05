"""Tests for volume monitor auto-config baseline preference."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from scanner.monitors.executor import MonitorExecutor
from scanner.monitors.volume import VolumeMonitor
from scanner.monitors.base import MonitorStatus


def _make_executor(rows_per_day: list[int], ts_col="created_at"):
    """Create a MonitorExecutor with a mocked query function.

    The query function returns daily row counts when called with the
    volume auto-config SQL, and a timestamp column from freshness discovery.
    """
    call_count = {"n": 0}

    def fake_query(sql: str):
        call_count["n"] += 1
        sql_lower = sql.lower()

        # Timestamp column discovery (freshness.discover_timestamp_column)
        if "information_schema.columns" in sql_lower:
            return [{"column_name": ts_col}]

        # Daily row counts
        if "count(*)" in sql_lower:
            return [
                {"day": f"2025-01-{i+1:02d}", "row_count": count}
                for i, count in enumerate(rows_per_day)
            ]

        return []

    return MonitorExecutor(query_func=fake_query, dialect="postgres")


class TestVolumeAutoConfigBaseline:
    def test_prefers_baseline_over_min_max(self):
        """Auto-config should set historical_mean/historical_stddev
        instead of min_rows/max_rows when stddev > 0."""
        counts = [100, 110, 105, 95, 102, 98, 107, 103, 99, 101]
        executor = _make_executor(counts)

        config = executor.auto_configure("volume", "db", "schema", "table", {})

        assert "historical_mean" in config
        assert "historical_stddev" in config
        assert config["historical_mean"] == pytest.approx(sum(counts) / len(counts), abs=0.1)
        assert config["historical_stddev"] > 0
        # Should NOT set min/max when stddev > 0
        assert "min_rows" not in config
        assert "max_rows" not in config
        assert config["_auto_configured"] is True

    def test_falls_back_to_min_max_when_constant(self):
        """When all counts are identical (stddev=0), should set min/max."""
        counts = [100] * 10
        executor = _make_executor(counts)

        config = executor.auto_configure("volume", "db", "schema", "table", {})

        assert config["historical_mean"] == 100.0
        assert config["historical_stddev"] == 0.0
        assert "min_rows" in config
        assert "max_rows" in config
        assert config["min_rows"] == 50  # mean * 0.5
        assert config["max_rows"] == 200  # mean * 2

    def test_skips_when_historical_mean_already_set(self):
        """Should not auto-configure if historical_mean is already provided."""
        executor = _make_executor([100, 200, 300])

        config = executor.auto_configure(
            "volume", "db", "schema", "table",
            {"historical_mean": 500.0}
        )

        # Should not overwrite
        assert config["historical_mean"] == 500.0

    def test_skips_when_min_rows_set(self):
        """Should not auto-configure if min_rows is already provided."""
        executor = _make_executor([100, 200, 300])

        config = executor.auto_configure(
            "volume", "db", "schema", "table",
            {"min_rows": 10}
        )

        assert config["min_rows"] == 10
        assert "historical_mean" not in config

    def test_not_enough_data(self):
        """Fewer than 3 data points → no auto-config."""
        executor = _make_executor([100, 200])

        config = executor.auto_configure("volume", "db", "schema", "table", {})

        assert "historical_mean" not in config
        assert "min_rows" not in config


class TestVolumeMonitorBaselineEvaluation:
    """Test that VolumeMonitor correctly evaluates with baseline stats."""

    def test_pass_within_range(self):
        monitor = VolumeMonitor(config={
            "historical_mean": 100.0,
            "historical_stddev": 10.0,
        })

        # Simulate query result: current count = 105 (within 1σ of mean)
        result = monitor.evaluate(
            [{"row_count": 105}],
            "db.schema.table",
        )

        assert result.status == MonitorStatus.PASS

    def test_fail_outside_range(self):
        monitor = VolumeMonitor(config={
            "historical_mean": 100.0,
            "historical_stddev": 5.0,
        })

        # Simulate query result: current count = 0 (>3σ from mean)
        result = monitor.evaluate(
            [{"row_count": 0}],
            "db.schema.table",
        )

        assert result.status in (MonitorStatus.FAIL, MonitorStatus.WARN)
