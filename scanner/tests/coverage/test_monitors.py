"""
Tests for the Universal Monitor Framework.
"""

import pytest

from scanner.monitors.freshness import FreshnessMonitor
from scanner.monitors.volume import VolumeMonitor
from scanner.monitors.schema import SchemaMonitor
from scanner.monitors.anomaly import AnomalyMonitor
from scanner.monitors.base import MonitorStatus
from scanner.monitors.executor import MonitorExecutor


# ---------------------------------------------------------------------------
# Freshness Monitor Tests
# ---------------------------------------------------------------------------


class TestFreshnessMonitor:
    def test_pass_within_sla(self):
        monitor = FreshnessMonitor({"max_hours": 24})
        result = monitor.evaluate(
            [{"hours_since_update": 6.0, "last_value": "2025-01-01T18:00:00", "total_rows": 1000}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 6.0

    def test_fail_exceeds_sla(self):
        monitor = FreshnessMonitor({"max_hours": 24})
        result = monitor.evaluate(
            [{"hours_since_update": 48.0, "last_value": "2025-01-01", "total_rows": 1000}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL
        assert result.value == 48.0

    def test_warn_approaching_sla(self):
        monitor = FreshnessMonitor({"max_hours": 24, "warn_hours": 18})
        result = monitor.evaluate(
            [{"hours_since_update": 20.0, "last_value": "2025-01-01", "total_rows": 1000}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.WARN

    def test_error_no_results(self):
        monitor = FreshnessMonitor()
        result = monitor.evaluate([], "db.schema.table")
        assert result.status == MonitorStatus.ERROR

    def test_error_null_column(self):
        monitor = FreshnessMonitor()
        result = monitor.evaluate(
            [{"hours_since_update": None, "last_value": None, "total_rows": 0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.ERROR

    def test_build_query(self):
        monitor = FreshnessMonitor({"timestamp_column": "created_at"})
        sql = monitor.build_query("mydb", "public", "orders", "postgres")
        assert "created_at" in sql
        assert "mydb" in sql or "public" in sql


# ---------------------------------------------------------------------------
# Volume Monitor Tests
# ---------------------------------------------------------------------------


class TestVolumeMonitor:
    def test_pass_no_thresholds(self):
        monitor = VolumeMonitor()
        result = monitor.evaluate(
            [{"row_count": 1000}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 1000.0

    def test_fail_below_min(self):
        monitor = VolumeMonitor({"min_rows": 500})
        result = monitor.evaluate(
            [{"row_count": 100}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL

    def test_fail_above_max(self):
        monitor = VolumeMonitor({"max_rows": 10000})
        result = monitor.evaluate(
            [{"row_count": 50000}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL

    def test_zscore_anomaly(self):
        monitor = VolumeMonitor({
            "historical_mean": 1000,
            "historical_stddev": 50,
            "anomaly_threshold": 3.0,
        })
        # 1200 is 4 stddevs above mean.
        result = monitor.evaluate(
            [{"row_count": 1200}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL
        assert "anomalous" in result.message.lower()

    def test_zscore_normal(self):
        monitor = VolumeMonitor({
            "historical_mean": 1000,
            "historical_stddev": 50,
            "anomaly_threshold": 3.0,
        })
        result = monitor.evaluate(
            [{"row_count": 1050}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS

    def test_time_series_anomaly(self):
        monitor = VolumeMonitor({"time_bucket_column": "created_at"})
        # Varied baseline so stddev > 0, then a large spike.
        rows = [
            {"bucket_date": f"2025-01-{d:02d}", "row_count": 95 + d}
            for d in range(1, 11)
        ]
        # Spike on last day — well beyond 3 stddevs.
        rows.append({"bucket_date": "2025-01-11", "row_count": 10000})
        result = monitor.evaluate(rows, "db.schema.table")
        assert result.status == MonitorStatus.FAIL

    def test_time_series_insufficient_data(self):
        monitor = VolumeMonitor({"time_bucket_column": "created_at"})
        result = monitor.evaluate(
            [{"bucket_date": "2025-01-01", "row_count": 100}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.SKIPPED


# ---------------------------------------------------------------------------
# Schema Monitor Tests
# ---------------------------------------------------------------------------


class TestSchemaMonitor:
    def test_pass_matches_baseline(self):
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "id", "data_type": "integer"},
                {"column_name": "name", "data_type": "varchar"},
            ],
        })
        result = monitor.evaluate(
            [
                {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "ordinal_position": 1},
                {"column_name": "name", "data_type": "varchar", "is_nullable": "YES", "ordinal_position": 2},
            ],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS

    def test_fail_column_removed(self):
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "id", "data_type": "integer"},
                {"column_name": "name", "data_type": "varchar"},
                {"column_name": "email", "data_type": "varchar"},
            ],
            "fail_on_column_removed": True,
        })
        result = monitor.evaluate(
            [
                {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "ordinal_position": 1},
                {"column_name": "name", "data_type": "varchar", "is_nullable": "YES", "ordinal_position": 2},
            ],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL
        assert "removed" in result.message.lower()

    def test_warn_column_added(self):
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "id", "data_type": "integer"},
            ],
            "fail_on_column_added": False,
        })
        result = monitor.evaluate(
            [
                {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "ordinal_position": 1},
                {"column_name": "new_col", "data_type": "text", "is_nullable": "YES", "ordinal_position": 2},
            ],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.WARN

    def test_fail_type_changed(self):
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "price", "data_type": "numeric"},
            ],
            "fail_on_type_change": True,
        })
        result = monitor.evaluate(
            [
                {"column_name": "price", "data_type": "varchar", "is_nullable": "YES", "ordinal_position": 1},
            ],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL
        assert "type change" in result.message.lower()

    def test_baseline_run(self):
        monitor = SchemaMonitor()  # No baseline.
        result = monitor.evaluate(
            [
                {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "ordinal_position": 1},
            ],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS
        assert result.details.get("is_baseline_run") is True


# ---------------------------------------------------------------------------
# Anomaly Monitor Tests
# ---------------------------------------------------------------------------


class TestAnomalyMonitor:
    def test_zscore_pass(self):
        monitor = AnomalyMonitor({
            "column": "revenue",
            "metric": "avg",
            "historical_values": [100, 102, 98, 101, 99, 103, 97, 100],
        })
        result = monitor.evaluate(
            [{"metric_value": 101.0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS

    def test_zscore_fail(self):
        monitor = AnomalyMonitor({
            "column": "revenue",
            "metric": "avg",
            "anomaly_threshold": 3.0,
            "historical_values": [100, 102, 98, 101, 99, 103, 97, 100],
        })
        result = monitor.evaluate(
            [{"metric_value": 200.0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL

    def test_inline_time_series(self):
        monitor = AnomalyMonitor({
            "column": "count",
            "metric": "distinct_count",
            "timestamp_column": "created_at",
        })
        # Varied baseline with natural fluctuation so stddev > 0.
        rows = [
            {"bucket_date": f"2025-01-{d:02d}", "metric_value": 95.0 + d * 1.0}
            for d in range(1, 11)
        ]
        # Normal value on last day — within the baseline range.
        rows.append({"bucket_date": "2025-01-11", "metric_value": 102.0})
        result = monitor.evaluate(rows, "db.schema.table")
        assert result.status == MonitorStatus.PASS

    def test_inline_time_series_anomaly(self):
        monitor = AnomalyMonitor({
            "column": "count",
            "metric": "distinct_count",
            "timestamp_column": "created_at",
        })
        rows = [
            {"bucket_date": f"2025-01-{d:02d}", "metric_value": 100.0}
            for d in range(1, 11)
        ]
        rows.append({"bucket_date": "2025-01-11", "metric_value": 500.0})
        result = monitor.evaluate(rows, "db.schema.table")
        assert result.status == MonitorStatus.FAIL

    def test_insufficient_data_with_value(self):
        """With < 3 data points but a valid value, report as PASS baseline observation."""
        monitor = AnomalyMonitor({"column": "x", "metric": "avg"})
        result = monitor.evaluate(
            [{"metric_value": 42.0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 42.0
        assert result.details["baseline_observation"] is True
        assert "baseline observation" in result.message

    def test_insufficient_data_no_value(self):
        """With < 3 data points and no extractable value, fall back to SKIPPED."""
        monitor = AnomalyMonitor({"column": "x", "metric": "avg"})
        result = monitor.evaluate(
            [{"metric_value": None}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.SKIPPED


# ---------------------------------------------------------------------------
# Monitor Executor Tests
# ---------------------------------------------------------------------------


class TestMonitorExecutor:
    def test_create_monitor(self):
        m = MonitorExecutor.create_monitor("freshness", {"max_hours": 12})
        assert m is not None
        assert m.monitor_type == "freshness"

    def test_create_unknown_monitor(self):
        m = MonitorExecutor.create_monitor("unknown_type")
        assert m is None

    def test_run_monitor_with_mock_query(self):
        def mock_query(sql):
            return [{"hours_since_update": 2.0, "last_value": "2025-01-01", "total_rows": 100}]

        executor = MonitorExecutor(query_func=mock_query, dialect="postgres")
        monitor = FreshnessMonitor({"max_hours": 24})
        result = executor.run_monitor(monitor, "mydb", "public", "orders")
        assert result.status == MonitorStatus.PASS
        assert result.duration_ms is not None
        assert result.executed_at is not None

    def test_run_monitor_handles_error(self):
        def failing_query(sql):
            raise RuntimeError("Connection failed")

        executor = MonitorExecutor(query_func=failing_query)
        monitor = FreshnessMonitor()
        result = executor.run_monitor(monitor, "db", "schema", "table")
        assert result.status == MonitorStatus.ERROR
        assert "Connection failed" in result.message

    def test_run_suite(self):
        call_count = 0

        def mock_query(sql):
            nonlocal call_count
            call_count += 1
            if "COUNT" in sql:
                return [{"row_count": 1000}]
            return [{"hours_since_update": 5.0, "last_value": "2025-01-01", "total_rows": 1000}]

        executor = MonitorExecutor(query_func=mock_query)
        results = executor.run_suite(
            tables=[{"database": "db", "schema": "pub", "table": "t"}],
            monitor_configs=[
                {"type": "freshness", "config": {"max_hours": 24}},
                {"type": "volume"},
            ],
        )
        assert "db.pub.t" in results
        assert len(results["db.pub.t"]) == 2
        assert call_count == 2
