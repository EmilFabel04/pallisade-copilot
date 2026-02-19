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

    def test_skipped_empty_table(self):
        """Empty table with no timestamp_column → SKIPPED (not ERROR)."""
        monitor = FreshnessMonitor()
        result = monitor.evaluate(
            [{"hours_since_update": None, "last_value": None, "total_rows": 0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.SKIPPED

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
        assert result.details["anomaly_ready"] is False
        assert "not ready yet" in result.message
        # Without timestamp_column, message should suggest providing one
        assert "timestamp_column" in result.message

    def test_insufficient_data_with_timestamp(self):
        """With < 3 data points but timestamp_column set, hint about needing more history."""
        monitor = AnomalyMonitor({
            "column": "x", "metric": "avg",
            "timestamp_column": "created_at",
        })
        result = monitor.evaluate(
            [{"bucket_date": "2025-01-01", "metric_value": 42.0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS
        assert result.details["has_timestamp_column"] is True
        assert "automatically" in result.message

    def test_insufficient_data_no_value(self):
        """With < 3 data points and no extractable value, fall back to SKIPPED."""
        monitor = AnomalyMonitor({"column": "x", "metric": "avg"})
        result = monitor.evaluate(
            [{"metric_value": None}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.SKIPPED
        assert result.details["anomaly_ready"] is False


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


# ---------------------------------------------------------------------------
# Edge Case Tests — Monitor Semantics Fixes
# ---------------------------------------------------------------------------


class TestFreshnessEdgeCases:
    def test_empty_table_skipped(self):
        """Empty table (total_rows=0, hours=None) should return SKIPPED."""
        monitor = FreshnessMonitor({"timestamp_column": "created_at"})
        result = monitor.evaluate(
            [{"hours_since_update": None, "last_value": None, "total_rows": 0}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.SKIPPED
        assert "empty" in result.message.lower()

    def test_null_ts_user_specified_error(self):
        """User-specified column with all NULLs should ERROR."""
        monitor = FreshnessMonitor({"timestamp_column": "my_col"})
        result = monitor.evaluate(
            [{"hours_since_update": None, "last_value": None, "total_rows": 100}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.ERROR
        assert "my_col" in result.message

    def test_null_ts_auto_detected_skipped(self):
        """Auto-detected column with all NULLs should SKIP (not ERROR)."""
        monitor = FreshnessMonitor({})  # no timestamp_column → auto-detected
        monitor.timestamp_column = "updated_at"  # simulate auto-detection
        result = monitor.evaluate(
            [{"hours_since_update": None, "last_value": None, "total_rows": 100}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.SKIPPED
        assert "auto-detected" in result.message.lower()


class TestVolumeEdgeCases:
    def test_constant_volume_small_delta_pass(self):
        """When stddev=0 and delta is below both thresholds, should PASS."""
        monitor = VolumeMonitor({"time_bucket_column": "ts", "min_abs_delta": 10})
        rows = [
            {"bucket_date": f"2025-01-{d:02d}", "row_count": 100}
            for d in range(1, 6)
        ]
        rows.append({"bucket_date": "2025-01-06", "row_count": 105})
        result = monitor.evaluate(rows, "db.schema.table")
        assert result.status == MonitorStatus.PASS

    def test_constant_volume_big_delta_warn(self):
        """When stddev=0 and delta exceeds thresholds, should WARN."""
        monitor = VolumeMonitor({"time_bucket_column": "ts", "min_abs_delta": 10})
        rows = [
            {"bucket_date": f"2025-01-{d:02d}", "row_count": 100}
            for d in range(1, 6)
        ]
        rows.append({"bucket_date": "2025-01-06", "row_count": 200})
        result = monitor.evaluate(rows, "db.schema.table")
        assert result.status == MonitorStatus.WARN

    def test_max_scan_days_clamps_lookback(self):
        """lookback_days should be clamped to max_scan_days."""
        monitor = VolumeMonitor({
            "time_bucket_column": "ts",
            "lookback_days": 365,
            "max_scan_days": 90,
        })
        assert monitor.lookback_days == 90


class TestSchemaEdgeCases:
    def test_cross_dialect_type_normalization_int64(self):
        """INT64 (BigQuery) vs integer (Postgres) should NOT alert."""
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "id", "data_type": "INT64"},
            ],
            "fail_on_type_change": True,
        })
        result = monitor.evaluate(
            [{"column_name": "id", "data_type": "integer", "is_nullable": "NO", "ordinal_position": 1}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS

    def test_cross_dialect_type_normalization_string_text(self):
        """STRING (BigQuery) vs text (Postgres) should NOT alert."""
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "name", "data_type": "STRING"},
            ],
            "fail_on_type_change": True,
        })
        result = monitor.evaluate(
            [{"column_name": "name", "data_type": "text", "is_nullable": "YES", "ordinal_position": 1}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS

    def test_cross_dialect_varchar_with_length(self):
        """character varying (Postgres) vs varchar(255) should NOT alert."""
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "email", "data_type": "character varying"},
            ],
            "fail_on_type_change": True,
        })
        result = monitor.evaluate(
            [{"column_name": "email", "data_type": "varchar(255)", "is_nullable": "YES", "ordinal_position": 1}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.PASS

    def test_real_type_change_still_detected(self):
        """A genuine type change (numeric → varchar) should still FAIL."""
        monitor = SchemaMonitor({
            "baseline_columns": [
                {"column_name": "price", "data_type": "numeric"},
            ],
            "fail_on_type_change": True,
        })
        result = monitor.evaluate(
            [{"column_name": "price", "data_type": "varchar", "is_nullable": "YES", "ordinal_position": 1}],
            "db.schema.table",
        )
        assert result.status == MonitorStatus.FAIL


class TestAnomalyEdgeCases:
    def test_metric_category_constants(self):
        """Verify ALL_COLUMN_METRICS and NUMERIC_ONLY_METRICS are correct."""
        assert "null_rate" in AnomalyMonitor.ALL_COLUMN_METRICS
        assert "distinct_rate" in AnomalyMonitor.ALL_COLUMN_METRICS
        assert "distinct_count" in AnomalyMonitor.ALL_COLUMN_METRICS
        assert "avg" not in AnomalyMonitor.ALL_COLUMN_METRICS
        assert "avg" in AnomalyMonitor.NUMERIC_ONLY_METRICS
        assert "sum" in AnomalyMonitor.NUMERIC_ONLY_METRICS
        assert "null_rate" not in AnomalyMonitor.NUMERIC_ONLY_METRICS


class TestExecutorEdgeCases:
    def test_adaptive_lookback_no_unbounded(self):
        """Adaptive lookback should never try lookback_days=0 (all data)."""
        monitor = AnomalyMonitor({
            "column": "x",
            "metric": "avg",
            "timestamp_column": "ts",
            "lookback_days": 30,
        })
        lookbacks_tried = []
        original_build = monitor.build_query

        def tracking_build(database, schema, table, dialect):
            lookbacks_tried.append(monitor.lookback_days)
            return original_build(database, schema, table, dialect)

        monitor.build_query = tracking_build

        def mock_query(sql):
            return [{"bucket_date": "2025-01-01", "metric_value": 42.0}]

        executor = MonitorExecutor(query_func=mock_query, dialect="postgres")
        executor.run_monitor(monitor, "db", "schema", "table")
        assert 0 not in lookbacks_tried

    def test_max_multi_columns_constant(self):
        """MAX_MULTI_COLUMNS should be defined."""
        from scanner.monitors.executor import MAX_MULTI_COLUMNS
        assert MAX_MULTI_COLUMNS == 50

    def test_monitor_result_raw_status(self):
        """MonitorResult should support raw_status field."""
        from scanner.monitors.base import MonitorResult
        r = MonitorResult(
            monitor_type="test",
            target_fqn="t",
            status=MonitorStatus.FAIL,
        )
        r.raw_status = MonitorStatus.FAIL
        d = r.to_dict()
        assert d["raw_status"] == "fail"

    def test_monitor_result_raw_status_none(self):
        """raw_status should default to None in to_dict."""
        from scanner.monitors.base import MonitorResult
        r = MonitorResult(
            monitor_type="test",
            target_fqn="t",
            status=MonitorStatus.PASS,
        )
        d = r.to_dict()
        assert d["raw_status"] is None
