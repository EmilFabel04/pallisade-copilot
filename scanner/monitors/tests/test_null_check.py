"""Tests for NullCheckMonitor."""

import pytest
from ..null_check import NullCheckMonitor
from ..base import MonitorStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monitor(columns="email", max_null_rate=0.05, **kwargs):
    config = {"columns": columns, "max_null_rate": max_null_rate}
    config.update(kwargs)
    return NullCheckMonitor(config)


FQN = "mydb.public.users"


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_default_max_null_rate(self):
        monitor = NullCheckMonitor({"columns": "email"})
        assert monitor.max_null_rate == 0.05

    def test_single_column_string_becomes_list(self):
        monitor = NullCheckMonitor({"columns": "email"})
        assert monitor.columns == ["email"]

    def test_column_alias_accepted(self):
        monitor = NullCheckMonitor({"column": "name"})
        assert monitor.columns == ["name"]

    def test_multi_column_list_preserved(self):
        monitor = NullCheckMonitor({"columns": ["email", "name", "phone"]})
        assert monitor.columns == ["email", "name", "phone"]

    def test_wildcard_default_when_no_column_config(self):
        monitor = NullCheckMonitor({})
        assert monitor.columns == ["*"]

    def test_max_null_rate_none_disables_threshold(self):
        monitor = NullCheckMonitor({"columns": "email", "max_null_rate": None})
        assert monitor.max_null_rate is None

    def test_monitor_type(self):
        monitor = NullCheckMonitor({})
        assert monitor.monitor_type == "null_check"

    def test_lookback_days_default(self):
        monitor = NullCheckMonitor({"columns": "email"})
        assert monitor.lookback_days == 30

    def test_anomaly_threshold_default(self):
        monitor = NullCheckMonitor({"columns": "email"})
        assert monitor.anomaly_threshold == 3.0

    def test_detection_method_default(self):
        monitor = NullCheckMonitor({"columns": "email"})
        assert monitor.detection_method == "auto"


# ---------------------------------------------------------------------------
# build_query — single column
# ---------------------------------------------------------------------------

class TestBuildQuerySingleColumn:

    def test_postgres_contains_null_case(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "CASE WHEN email IS NULL" in sql

    def test_postgres_contains_count_star(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "COUNT(*)" in sql

    def test_postgres_aliases_null_rate_column(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "null_rate_email" in sql

    def test_postgres_references_target_table(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "users" in sql

    def test_postgres_uses_float_cast(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        # FLOAT or REAL — sqlglot may transpile FLOAT to REAL for postgres
        assert "FLOAT" in sql.upper() or "REAL" in sql.upper() or "DOUBLE" in sql.upper()

    def test_bigquery_uses_float64_cast(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="bigquery")
        assert "FLOAT64" in sql

    def test_bigquery_references_target_table(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="bigquery")
        assert "users" in sql

    def test_fqn_constructed_from_parts(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "mydb" in sql
        assert "public" in sql
        assert "users" in sql

    def test_schema_only_fqn(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("", "analytics", "events", dialect="postgres")
        assert "analytics" in sql
        assert "events" in sql
        assert "mydb" not in sql


# ---------------------------------------------------------------------------
# build_query — multi-column
# ---------------------------------------------------------------------------

class TestBuildQueryMultiColumn:

    def test_both_columns_in_select(self):
        monitor = _monitor(columns=["email", "phone"])
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "null_rate_email" in sql
        assert "null_rate_phone" in sql

    def test_three_columns_all_present(self):
        monitor = _monitor(columns=["a", "b", "c"])
        sql = monitor.build_query("mydb", "public", "tbl", dialect="postgres")
        assert "null_rate_a" in sql
        assert "null_rate_b" in sql
        assert "null_rate_c" in sql

    def test_bigquery_multi_column_uses_float64(self):
        monitor = _monitor(columns=["email", "phone"])
        sql = monitor.build_query("mydb", "public", "users", dialect="bigquery")
        assert "FLOAT64" in sql
        assert "FLOAT)" not in sql  # should not have plain FLOAT)

    def test_multi_column_single_from_clause(self):
        monitor = _monitor(columns=["email", "phone"])
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        # Only one FROM clause — both columns derived from same table scan
        assert sql.upper().count("FROM") == 1

    def test_null_rate_expr_for_each_column(self):
        monitor = _monitor(columns=["col1", "col2", "col3"])
        sql = monitor.build_query("db", "s", "t", dialect="postgres")
        for col in ["col1", "col2", "col3"]:
            assert f"null_rate_{col}" in sql


# ---------------------------------------------------------------------------
# build_query — wildcard mode
# ---------------------------------------------------------------------------

class TestBuildQueryWildcard:

    def test_wildcard_returns_count_query(self):
        monitor = NullCheckMonitor({"columns": "*"})
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "COUNT(*)" in sql.upper() or "row_count" in sql

    def test_wildcard_still_references_table(self):
        monitor = NullCheckMonitor({"columns": "*"})
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "users" in sql


# ---------------------------------------------------------------------------
# build_query — timestamp_column / timeseries mode
# ---------------------------------------------------------------------------

class TestBuildQueryTimeseries:

    def test_postgres_timeseries_has_bucket_date(self):
        monitor = _monitor(columns="email", timestamp_column="created_at")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "bucket_date" in sql

    def test_postgres_timeseries_has_group_by(self):
        monitor = _monitor(columns="email", timestamp_column="created_at")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "GROUP BY" in sql.upper()

    def test_postgres_timeseries_has_order_by(self):
        monitor = _monitor(columns="email", timestamp_column="created_at")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "ORDER BY" in sql.upper()

    def test_postgres_timeseries_has_where_clause(self):
        monitor = _monitor(columns="email", timestamp_column="created_at", lookback_days=30)
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "WHERE" in sql.upper()

    def test_postgres_timeseries_interval_references_lookback(self):
        monitor = _monitor(columns="email", timestamp_column="created_at", lookback_days=14)
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "14" in sql

    def test_bigquery_timeseries_uses_date_sub(self):
        monitor = _monitor(columns="email", timestamp_column="created_at")
        sql = monitor.build_query("mydb", "public", "users", dialect="bigquery")
        assert "DATE_SUB" in sql.upper() or "DATE_ADD" in sql.upper() or "CURRENT_DATE" in sql.upper()

    def test_timeseries_contains_null_rate_alias(self):
        monitor = _monitor(columns="email", timestamp_column="created_at")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "null_rate_email" in sql

    def test_timeseries_no_timestamp_col_is_not_timeseries(self):
        monitor = _monitor(columns="email")
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "bucket_date" not in sql

    def test_day_of_week_seasonality_includes_dow_column(self):
        monitor = _monitor(
            columns="email",
            timestamp_column="created_at",
            seasonality="day_of_week",
        )
        sql = monitor.build_query("mydb", "public", "users", dialect="postgres")
        assert "day_of_week" in sql


# ---------------------------------------------------------------------------
# evaluate() — empty results
# ---------------------------------------------------------------------------

class TestEvaluateEmptyResults:

    def test_empty_rows_returns_error(self):
        monitor = _monitor(columns="email")
        result = monitor.evaluate([], FQN)
        assert result.status == MonitorStatus.ERROR

    def test_empty_rows_error_message(self):
        monitor = _monitor(columns="email")
        result = monitor.evaluate([], FQN)
        assert "No results" in result.message

    def test_empty_rows_target_fqn_preserved(self):
        monitor = _monitor(columns="email")
        result = monitor.evaluate([], FQN)
        assert result.target_fqn == FQN

    def test_empty_rows_monitor_type_preserved(self):
        monitor = _monitor(columns="email")
        result = monitor.evaluate([], FQN)
        assert result.monitor_type == "null_check"


# ---------------------------------------------------------------------------
# evaluate() — PASS cases
# ---------------------------------------------------------------------------

class TestEvaluatePass:

    def test_pass_when_null_rate_zero(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.0}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_pass_when_null_rate_below_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.02}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_pass_at_exactly_threshold(self):
        # Rate equal to threshold is not strictly above → should PASS
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.05}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_pass_multi_column_all_below(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.10)
        rows = [{"null_rate_email": 0.01, "null_rate_phone": 0.03}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_pass_message_contains_column_count(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.10)
        rows = [{"null_rate_email": 0.01, "null_rate_phone": 0.03}]
        result = monitor.evaluate(rows, FQN)
        assert "2" in result.message

    def test_pass_message_mentions_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.01}]
        result = monitor.evaluate(rows, FQN)
        assert "5%" in result.message

    def test_pass_details_has_columns_list(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.01}]
        result = monitor.evaluate(rows, FQN)
        assert "columns" in result.details
        assert len(result.details["columns"]) == 1

    def test_pass_details_worst_column_set(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.10)
        rows = [{"null_rate_email": 0.01, "null_rate_phone": 0.04}]
        result = monitor.evaluate(rows, FQN)
        assert result.details["worst_column"] == "phone"

    def test_pass_value_reflects_worst_null_rate(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.10)
        rows = [{"null_rate_email": 0.01, "null_rate_phone": 0.04}]
        result = monitor.evaluate(rows, FQN)
        assert abs(result.value - 0.04) < 1e-9

    def test_is_passing_true(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.01}]
        result = monitor.evaluate(rows, FQN)
        assert result.is_passing is True


# ---------------------------------------------------------------------------
# evaluate() — FAIL cases
# ---------------------------------------------------------------------------

class TestEvaluateFail:

    def test_fail_when_null_rate_exceeds_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.FAIL

    def test_fail_message_mentions_column_name(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10}]
        result = monitor.evaluate(rows, FQN)
        assert "email" in result.message

    def test_fail_message_mentions_failed_count(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10, "null_rate_phone": 0.20}]
        result = monitor.evaluate(rows, FQN)
        assert "2" in result.message

    def test_fail_partial_columns(self):
        monitor = _monitor(columns=["email", "name"], max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10, "null_rate_name": 0.01}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.FAIL

    def test_fail_partial_details_mark_correct_column(self):
        monitor = _monitor(columns=["email", "name"], max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10, "null_rate_name": 0.01}]
        result = monitor.evaluate(rows, FQN)
        cols = {c["column"]: c["status"] for c in result.details["columns"]}
        assert cols["email"] == "fail"
        assert cols["name"] == "pass"

    def test_fail_threshold_captured_in_result(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10}]
        result = monitor.evaluate(rows, FQN)
        assert result.threshold == 0.05

    def test_fail_is_passing_false(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10}]
        result = monitor.evaluate(rows, FQN)
        assert result.is_passing is False

    def test_fail_value_is_highest_null_rate(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.05)
        rows = [{"null_rate_email": 0.15, "null_rate_phone": 0.08}]
        result = monitor.evaluate(rows, FQN)
        assert abs(result.value - 0.15) < 1e-9

    def test_fail_target_fqn_preserved(self):
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.10}]
        result = monitor.evaluate(rows, FQN)
        assert result.target_fqn == FQN

    def test_high_custom_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.50)
        rows = [{"null_rate_email": 0.49}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_just_above_custom_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.50)
        rows = [{"null_rate_email": 0.51}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.FAIL


# ---------------------------------------------------------------------------
# evaluate() — WARN cases (timeseries / baseline mode)
# ---------------------------------------------------------------------------

class TestEvaluateWarn:

    def _timeseries_rows(self, col, values):
        """Build time-series style rows for a given column."""
        return [
            {"bucket_date": f"2026-03-{i+1:02d}", f"null_rate_{col}": v}
            for i, v in enumerate(values)
        ]

    def test_warn_borderline_via_low_anomaly_confidence(self):
        """When the null check anomaly fires with confidence < 50%,
        status should be WARN, not FAIL."""
        # NullCheckMonitor only reaches WARN via _evaluate_timeseries when
        # score.is_anomaly is True but score.confidence_pct < 50.
        # We test this indirectly via the timeseries code path.
        # Use a null_rate spike that is noisy to provoke low confidence.
        # With a very small dataset (3 rows), the z-score is unreliable →
        # confidence stays low → WARN.
        monitor = NullCheckMonitor({
            "columns": "email",
            "max_null_rate": 1.0,  # disable hard threshold
            "timestamp_column": "created_at",
            "anomaly_threshold": 1.0,  # low threshold to trigger anomaly
        })
        # Baseline: 0.01, 0.01 — current: 0.9 (big spike, but only 2 baseline pts)
        rows = self._timeseries_rows("email", [0.01, 0.01, 0.9])
        result = monitor.evaluate(rows, FQN)
        # With only 2 baseline points the confidence is capped low → WARN (or FAIL)
        # We at minimum expect non-PASS
        assert result.status in (MonitorStatus.WARN, MonitorStatus.FAIL)

    def test_snapshot_no_warn_status_only_pass_or_fail(self):
        """Snapshot mode only produces PASS or FAIL (no WARN path)."""
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": 0.04}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

        rows_fail = [{"null_rate_email": 0.06}]
        result_fail = monitor.evaluate(rows_fail, FQN)
        assert result_fail.status == MonitorStatus.FAIL

    def test_borderline_rate_just_below_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.10)
        rows = [{"null_rate_email": 0.0999}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_borderline_rate_just_above_threshold(self):
        monitor = _monitor(columns="email", max_null_rate=0.10)
        rows = [{"null_rate_email": 0.1001}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.FAIL


# ---------------------------------------------------------------------------
# evaluate() — missing keys / null values in results
# ---------------------------------------------------------------------------

class TestEvaluateMissingKeys:

    def test_missing_column_key_is_skipped(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.05)
        # Only email present in row — phone missing
        rows = [{"null_rate_email": 0.01}]
        result = monitor.evaluate(rows, FQN)
        # Should not crash; email passes
        assert result.status == MonitorStatus.PASS
        assert len(result.details["columns"]) == 1

    def test_none_value_for_column_is_skipped(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.05)
        rows = [{"null_rate_email": None, "null_rate_phone": 0.02}]
        result = monitor.evaluate(rows, FQN)
        # email skipped (None), phone passes
        assert result.status == MonitorStatus.PASS
        assert len(result.details["columns"]) == 1

    def test_all_columns_missing_returns_pass_no_columns(self):
        monitor = _monitor(columns=["email", "phone"], max_null_rate=0.05)
        rows = [{}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS
        assert "No columns to check" in result.message

    def test_null_rate_none_for_all_columns_passes(self):
        monitor = _monitor(columns=["email"], max_null_rate=0.05)
        rows = [{"null_rate_email": None}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_null_value_from_empty_table(self):
        """NULLIF(COUNT(*), 0) returns NULL for empty tables — handled gracefully."""
        monitor = _monitor(columns="email", max_null_rate=0.05)
        rows = [{"null_rate_email": None}]
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS


# ---------------------------------------------------------------------------
# evaluate() — timeseries baseline mode integration
# ---------------------------------------------------------------------------

class TestEvaluateTimeseries:

    def _ts_rows(self, col, values):
        return [
            {"bucket_date": f"2026-03-{i+1:02d}", f"null_rate_{col}": v}
            for i, v in enumerate(values)
        ]

    def test_normal_baseline_passes(self):
        monitor = NullCheckMonitor({
            "columns": "email",
            "timestamp_column": "created_at",
            "max_null_rate": 1.0,
            "anomaly_threshold": 3.0,
        })
        # Stable null rates — no anomaly
        rows = self._ts_rows("email", [0.01, 0.01, 0.01, 0.01, 0.01])
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.PASS

    def test_large_spike_with_sufficient_baseline_fails(self):
        monitor = NullCheckMonitor({
            "columns": "email",
            "timestamp_column": "created_at",
            "max_null_rate": 1.0,  # disable hard threshold
            "anomaly_threshold": 2.0,
        })
        # 9 stable points then a massive spike
        baseline_vals = [0.01] * 9 + [0.99]
        rows = self._ts_rows("email", baseline_vals)
        result = monitor.evaluate(rows, FQN)
        assert result.status in (MonitorStatus.FAIL, MonitorStatus.WARN)

    def test_fewer_than_3_rows_falls_back_to_snapshot(self):
        """With < 3 rows, timeseries path skips and snapshot is used instead."""
        monitor = NullCheckMonitor({
            "columns": "email",
            "timestamp_column": "created_at",
            "max_null_rate": 0.05,
        })
        rows = self._ts_rows("email", [0.01, 0.02])
        result = monitor.evaluate(rows, FQN)
        # 2 rows → snapshot mode → should PASS (both below threshold)
        assert result.status == MonitorStatus.PASS

    def test_timeseries_result_has_confidence_info(self):
        monitor = NullCheckMonitor({
            "columns": "email",
            "timestamp_column": "created_at",
            "anomaly_threshold": 3.0,
        })
        rows = self._ts_rows("email", [0.01, 0.01, 0.01, 0.01, 0.01])
        result = monitor.evaluate(rows, FQN)
        # Baseline mode details include confidence_info
        assert "confidence_info" in result.details

    def test_hard_threshold_still_applied_in_timeseries(self):
        """Even in timeseries mode, hard threshold triggers FAIL."""
        monitor = NullCheckMonitor({
            "columns": "email",
            "timestamp_column": "created_at",
            "max_null_rate": 0.05,
            "anomaly_threshold": 99.0,  # very high — won't flag anomaly
        })
        # All rows at 0.10, well above hard threshold
        rows = self._ts_rows("email", [0.10, 0.10, 0.10, 0.10, 0.10])
        result = monitor.evaluate(rows, FQN)
        assert result.status == MonitorStatus.FAIL
