"""Tests for RangeValidationMonitor."""

import pytest
from ..range_validation import RangeValidationMonitor
from ..base import MonitorStatus


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

class TestRangeValidationConfig:
    def test_default_max_violation_pct(self):
        m = RangeValidationMonitor({"column": "price", "min_value": 0})
        assert m.max_violation_pct == 0.0

    def test_default_warn_violation_pct(self):
        m = RangeValidationMonitor({"column": "price", "min_value": 0})
        assert m.warn_violation_pct == 0.0

    def test_default_allow_null(self):
        m = RangeValidationMonitor({"column": "age", "min_value": 0})
        assert m.allow_null is True

    def test_custom_allow_null_false(self):
        m = RangeValidationMonitor({"column": "age", "min_value": 0, "allow_null": False})
        assert m.allow_null is False

    def test_min_and_max_stored(self):
        m = RangeValidationMonitor({"column": "score", "min_value": 0.0, "max_value": 100.0})
        assert m.min_value == 0.0
        assert m.max_value == 100.0

    def test_monitor_type(self):
        m = RangeValidationMonitor({"column": "x", "min_value": 0})
        assert m.monitor_type == "range_validation"


# ---------------------------------------------------------------------------
# build_query
# ---------------------------------------------------------------------------

class TestRangeValidationBuildQuery:
    def test_no_column_raises(self):
        m = RangeValidationMonitor({"min_value": 0})
        with pytest.raises(ValueError, match="'column'"):
            m.build_query("db", "s", "t")

    def test_no_bounds_raises(self):
        m = RangeValidationMonitor({"column": "price"})
        with pytest.raises(ValueError, match="min_value.*max_value"):
            m.build_query("db", "s", "t")

    def test_build_query_postgres_min_only(self):
        m = RangeValidationMonitor({"column": "age", "min_value": 0})
        sql = m.build_query("db", "public", "users", dialect="postgres")
        assert '"db"."public"."users"' in sql
        assert "total_rows" in sql
        assert "violation_count" in sql
        assert "0" in sql  # min_value appears in SQL
        assert "< 0" in sql or "< 0.0" in sql

    def test_build_query_postgres_max_only(self):
        m = RangeValidationMonitor({"column": "score", "max_value": 100})
        sql = m.build_query("db", "public", "scores", dialect="postgres")
        assert "> 100" in sql or "> 100.0" in sql

    def test_build_query_postgres_min_and_max(self):
        m = RangeValidationMonitor({"column": "price", "min_value": 0, "max_value": 9999})
        sql = m.build_query("db", "s", "products", dialect="postgres")
        assert "< 0" in sql or "< 0.0" in sql
        assert "> 9999" in sql or "> 9999.0" in sql

    def test_build_query_bigquery_uses_float64(self):
        m = RangeValidationMonitor({"column": "amount", "min_value": 0})
        sql = m.build_query("project", "dataset", "sales", dialect="bigquery")
        assert "FLOAT64" in sql
        assert "FLOAT)" not in sql

    def test_build_query_bigquery_fqn(self):
        m = RangeValidationMonitor({"column": "amount", "min_value": 0})
        sql = m.build_query("myproject", "analytics", "events", dialect="bigquery")
        assert "`myproject`.`analytics`.`events`" in sql

    def test_build_query_includes_actual_min_max(self):
        m = RangeValidationMonitor({"column": "val", "min_value": 1})
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "actual_min" in sql
        assert "actual_max" in sql

    def test_build_query_allow_null_false_includes_null_check(self):
        m = RangeValidationMonitor({
            "column": "val", "min_value": 0, "allow_null": False
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "IS NULL" in sql

    def test_build_query_allow_null_true_no_null_check(self):
        m = RangeValidationMonitor({
            "column": "val", "min_value": 0, "allow_null": True
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "IS NULL" not in sql


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

class TestRangeValidationEvaluate:
    def _make_monitor(self, min_value=None, max_value=None,
                      max_violation_pct=0.0, warn_violation_pct=0.0,
                      allow_null=True):
        cfg = {"column": "price"}
        if min_value is not None:
            cfg["min_value"] = min_value
        if max_value is not None:
            cfg["max_value"] = max_value
        cfg["max_violation_pct"] = max_violation_pct
        cfg["warn_violation_pct"] = warn_violation_pct
        cfg["allow_null"] = allow_null
        return RangeValidationMonitor(cfg)

    def test_empty_results_returns_error(self):
        m = self._make_monitor(min_value=0)
        result = m.evaluate([], "db.s.t")
        assert result.status == MonitorStatus.ERROR

    def test_empty_table_returns_pass(self):
        m = self._make_monitor(min_value=0)
        result = m.evaluate(
            [{"total_rows": 0, "violation_count": 0, "actual_min": None, "actual_max": None}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.PASS
        assert "empty" in result.message.lower()

    def test_zero_violations_returns_pass(self):
        m = self._make_monitor(min_value=0, max_value=100)
        result = m.evaluate(
            [{"total_rows": 500, "violation_count": 0, "actual_min": 5.0, "actual_max": 95.0}],
            "db.s.products",
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 0.0

    def test_pass_message_contains_bounds(self):
        m = self._make_monitor(min_value=0, max_value=100)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 0, "actual_min": 10.0, "actual_max": 90.0}],
            "db.s.t",
        )
        assert ">= 0" in result.message
        assert "<= 100" in result.message

    def test_violations_above_threshold_returns_fail(self):
        # 10% violation rate, zero tolerance
        m = self._make_monitor(min_value=0, max_violation_pct=0.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 10, "actual_min": -5.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.FAIL
        assert result.value == pytest.approx(10.0)

    def test_violations_within_tolerance_returns_pass(self):
        # 2% violation rate, warn at 3%, fail at 5%
        m = self._make_monitor(min_value=0, max_violation_pct=5.0, warn_violation_pct=3.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 2, "actual_min": -1.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.PASS

    def test_violations_trigger_warn_threshold(self):
        # 3% violation rate, warn at 2%, fail at 10%
        m = self._make_monitor(min_value=0, max_violation_pct=10.0, warn_violation_pct=2.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 3, "actual_min": -2.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.WARN

    def test_violations_exceed_warn_and_fail(self):
        # 15% violation rate, warn at 2%, fail at 10%
        m = self._make_monitor(min_value=0, max_violation_pct=10.0, warn_violation_pct=2.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 15, "actual_min": -10.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.FAIL

    def test_details_include_actual_min_max(self):
        m = self._make_monitor(min_value=0, max_value=100)
        result = m.evaluate(
            [{"total_rows": 200, "violation_count": 5, "actual_min": -3.0, "actual_max": 110.0}],
            "db.s.t",
        )
        assert result.details["actual_min"] == pytest.approx(-3.0)
        assert result.details["actual_max"] == pytest.approx(110.0)

    def test_details_include_violation_pct(self):
        m = self._make_monitor(min_value=0)
        result = m.evaluate(
            [{"total_rows": 200, "violation_count": 4, "actual_min": -1.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.details["violation_pct"] == pytest.approx(2.0)

    def test_null_handling_not_allowed(self):
        m = self._make_monitor(min_value=0, allow_null=False)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 5, "actual_min": 0.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.details["allow_null"] is False
        assert result.status == MonitorStatus.FAIL

    def test_null_handling_allowed(self):
        m = self._make_monitor(min_value=0, allow_null=True)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 0, "actual_min": None, "actual_max": None}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.PASS

    def test_threshold_stored_in_result(self):
        m = self._make_monitor(min_value=0, max_violation_pct=5.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 10, "actual_min": -1.0, "actual_max": 50.0}],
            "db.s.t",
        )
        assert result.threshold == pytest.approx(5.0)

    def test_monitor_type_field(self):
        m = self._make_monitor(min_value=0)
        result = m.evaluate(
            [{"total_rows": 50, "violation_count": 0, "actual_min": 1.0, "actual_max": 10.0}],
            "db.s.t",
        )
        assert result.monitor_type == "range_validation"
