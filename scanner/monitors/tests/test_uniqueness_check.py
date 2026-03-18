"""Tests for UniquenessCheckMonitor."""

import pytest
from ..uniqueness_check import UniquenessCheckMonitor, _is_likely_key_column
from ..base import MonitorStatus


# ---------------------------------------------------------------------------
# _is_likely_key_column heuristic
# ---------------------------------------------------------------------------

class TestIsLikelyKeyColumn:
    def test_exact_match_id(self):
        assert _is_likely_key_column("id") is True

    def test_exact_match_uuid(self):
        assert _is_likely_key_column("uuid") is True

    def test_exact_match_guid(self):
        assert _is_likely_key_column("guid") is True

    def test_exact_match_pk(self):
        assert _is_likely_key_column("pk") is True

    def test_exact_match_key(self):
        assert _is_likely_key_column("key") is True

    def test_suffix_id(self):
        assert _is_likely_key_column("user_id") is True

    def test_suffix_uuid(self):
        assert _is_likely_key_column("order_uuid") is True

    def test_suffix_guid(self):
        assert _is_likely_key_column("session_guid") is True

    def test_suffix_pk(self):
        assert _is_likely_key_column("record_pk") is True

    def test_suffix_key(self):
        assert _is_likely_key_column("lookup_key") is True

    def test_case_insensitive_upper(self):
        assert _is_likely_key_column("USER_ID") is True

    def test_case_insensitive_mixed(self):
        assert _is_likely_key_column("OrderUUID") is False  # no suffix match

    def test_non_key_column(self):
        assert _is_likely_key_column("amount") is False

    def test_non_key_email(self):
        assert _is_likely_key_column("email") is False

    def test_non_key_created_at(self):
        assert _is_likely_key_column("created_at") is False

    def test_whitespace_stripped(self):
        assert _is_likely_key_column("  id  ") is True


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

class TestUniquenessCheckMonitorConfig:
    def test_default_max_duplicate_rate(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        assert m.max_duplicate_rate == 0.01

    def test_custom_max_duplicate_rate(self):
        m = UniquenessCheckMonitor({"columns": ["id"], "max_duplicate_rate": 0.05})
        assert m.max_duplicate_rate == 0.05

    def test_max_duplicate_rate_none(self):
        m = UniquenessCheckMonitor({"columns": ["id"], "max_duplicate_rate": None})
        assert m.max_duplicate_rate is None

    def test_default_lookback_days(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        assert m.lookback_days == 30

    def test_default_anomaly_threshold(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        assert m.anomaly_threshold == 3.0

    def test_default_detection_method(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        assert m.detection_method == "auto"

    def test_single_string_column_normalized_to_list(self):
        m = UniquenessCheckMonitor({"column": "user_id"})
        assert m.columns == ["user_id"]

    def test_columns_list(self):
        m = UniquenessCheckMonitor({"columns": ["a", "b"]})
        assert m.columns == ["a", "b"]

    def test_empty_config(self):
        m = UniquenessCheckMonitor()
        assert m.columns == []
        assert m.max_duplicate_rate == 0.01


# ---------------------------------------------------------------------------
# build_query
# ---------------------------------------------------------------------------

class TestUniquenessCheckBuildQuery:
    def test_build_query_postgres_single_column(self):
        m = UniquenessCheckMonitor({"columns": ["user_id"]})
        sql = m.build_query("mydb", "public", "users", dialect="postgres")
        assert "distinct_user_id" in sql
        assert "total_rows" in sql
        assert "users" in sql

    def test_build_query_postgres_fqn(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        sql = m.build_query("mydb", "public", "orders", dialect="postgres")
        assert "mydb.public.orders" in sql

    def test_build_query_bigquery(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        sql = m.build_query("project", "dataset", "events", dialect="bigquery")
        assert "project.dataset.events" in sql
        assert "distinct_id" in sql
        assert "total_rows" in sql

    def test_build_query_multiple_columns(self):
        m = UniquenessCheckMonitor({"columns": ["id", "email"]})
        sql = m.build_query("db", "schema", "users", dialect="postgres")
        assert "distinct_id" in sql
        assert "distinct_email" in sql
        assert "total_rows" in sql

    def test_build_query_no_columns_raises(self):
        m = UniquenessCheckMonitor({"columns": []})
        with pytest.raises(ValueError, match="at least one column"):
            m.build_query("db", "schema", "table")

    def test_build_query_no_timestamp_column_no_group_by(self):
        m = UniquenessCheckMonitor({"columns": ["id"]})
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "GROUP BY" not in sql

    def test_build_query_with_timestamp_column_has_group_by(self):
        m = UniquenessCheckMonitor({
            "columns": ["id"],
            "timestamp_column": "created_at",
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "GROUP BY" in sql
        assert "bucket_date" in sql

    def test_build_query_bigquery_timeseries_uses_date_sub(self):
        m = UniquenessCheckMonitor({
            "columns": ["id"],
            "timestamp_column": "ts",
            "lookback_days": 7,
        })
        sql = m.build_query("p", "d", "t", dialect="bigquery")
        assert "DATE_SUB" in sql
        assert "INTERVAL 7 DAY" in sql

    def test_build_query_postgres_timeseries_uses_interval(self):
        m = UniquenessCheckMonitor({
            "columns": ["id"],
            "timestamp_column": "ts",
            "lookback_days": 14,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "INTERVAL" in sql
        assert "14" in sql


# ---------------------------------------------------------------------------
# evaluate — snapshot mode
# ---------------------------------------------------------------------------

class TestUniquenessCheckEvaluateSnapshot:
    def _make_monitor(self, columns=None, max_duplicate_rate=0.01):
        return UniquenessCheckMonitor({
            "columns": columns or ["user_id"],
            "max_duplicate_rate": max_duplicate_rate,
        })

    def test_empty_results_returns_error(self):
        m = self._make_monitor()
        result = m.evaluate([], "db.schema.users")
        assert result.status == MonitorStatus.ERROR

    def test_empty_table_returns_pass(self):
        m = self._make_monitor()
        result = m.evaluate([{"distinct_user_id": 0, "total_rows": 0}], "db.s.t")
        assert result.status == MonitorStatus.PASS
        assert "empty" in result.message.lower()

    def test_no_duplicates_returns_pass(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"distinct_user_id": 1000, "total_rows": 1000}], "db.s.users"
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 0.0

    def test_duplicates_below_threshold_returns_pass(self):
        # 0.5% duplicate rate, threshold is 1%
        m = self._make_monitor(max_duplicate_rate=0.01)
        result = m.evaluate(
            [{"distinct_user_id": 995, "total_rows": 1000}], "db.s.users"
        )
        assert result.status == MonitorStatus.PASS
        assert result.details["columns"][0]["duplicate_rate"] == pytest.approx(0.005)

    def test_duplicates_at_threshold_returns_pass(self):
        # Just below threshold — 0.9% duplicate rate, threshold 1%
        m = self._make_monitor(max_duplicate_rate=0.01)
        result = m.evaluate(
            [{"distinct_user_id": 991, "total_rows": 1000}], "db.s.users"
        )
        assert result.status == MonitorStatus.PASS

    def test_duplicates_exceeding_threshold_returns_fail(self):
        # 5% duplicate rate, threshold is 1%
        m = self._make_monitor(max_duplicate_rate=0.01)
        result = m.evaluate(
            [{"distinct_user_id": 950, "total_rows": 1000}], "db.s.users"
        )
        assert result.status == MonitorStatus.FAIL
        assert result.value == pytest.approx(0.05)

    def test_fail_message_includes_column_and_rate(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"distinct_user_id": 800, "total_rows": 1000}], "db.s.users"
        )
        assert result.status == MonitorStatus.FAIL
        assert "user_id" in result.message
        assert "20.00%" in result.message

    def test_multiple_columns_all_pass(self):
        m = self._make_monitor(columns=["id", "email"])
        result = m.evaluate(
            [{"distinct_id": 500, "distinct_email": 500, "total_rows": 500}],
            "db.s.users",
        )
        assert result.status == MonitorStatus.PASS
        assert len(result.details["columns"]) == 2

    def test_multiple_columns_one_fails(self):
        m = self._make_monitor(columns=["id", "email"], max_duplicate_rate=0.01)
        result = m.evaluate(
            [{"distinct_id": 1000, "distinct_email": 800, "total_rows": 1000}],
            "db.s.users",
        )
        assert result.status == MonitorStatus.FAIL
        failing = [c for c in result.details["columns"] if c["status"] == "fail"]
        assert len(failing) == 1
        assert failing[0]["column"] == "email"

    def test_worst_column_tracked(self):
        m = self._make_monitor(columns=["id", "code"], max_duplicate_rate=0.01)
        result = m.evaluate(
            [{"distinct_id": 900, "distinct_code": 700, "total_rows": 1000}],
            "db.s.t",
        )
        assert result.details["worst_column"] == "code"
        assert result.details["worst_duplicate_rate"] == pytest.approx(0.3)

    def test_duplicate_count_in_details(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"distinct_user_id": 800, "total_rows": 1000}], "db.s.t"
        )
        col = result.details["columns"][0]
        assert col["duplicate_count"] == 200

    def test_threshold_reported_in_details(self):
        m = self._make_monitor(max_duplicate_rate=0.02)
        result = m.evaluate(
            [{"distinct_user_id": 1000, "total_rows": 1000}], "db.s.t"
        )
        assert result.details["columns"][0]["threshold"] == 0.02

    def test_no_columns_after_evaluation_returns_pass(self):
        m = UniquenessCheckMonitor({"columns": ["x"]})
        # Missing key in result row
        result = m.evaluate([{"total_rows": 100}], "db.s.t")
        assert result.status == MonitorStatus.PASS
        assert "No columns" in result.message

    def test_monitor_type(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"distinct_user_id": 1000, "total_rows": 1000}], "db.s.users"
        )
        assert result.monitor_type == "uniqueness_check"
