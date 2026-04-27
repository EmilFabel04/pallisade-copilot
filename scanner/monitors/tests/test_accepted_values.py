"""Tests for AcceptedValuesMonitor."""

import pytest
from ..accepted_values import AcceptedValuesMonitor
from ..base import MonitorStatus


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

class TestAcceptedValuesConfig:
    def test_default_case_sensitive_false(self):
        m = AcceptedValuesMonitor({"column": "status", "allowed_values": ["active"]})
        assert m.case_sensitive is False

    def test_default_max_violation_pct(self):
        m = AcceptedValuesMonitor({"column": "status", "allowed_values": ["active"]})
        assert m.max_violation_pct == 0.0

    def test_default_warn_violation_pct(self):
        m = AcceptedValuesMonitor({"column": "status", "allowed_values": ["active"]})
        assert m.warn_violation_pct == 0.0

    def test_default_allow_null(self):
        m = AcceptedValuesMonitor({"column": "status", "allowed_values": ["active"]})
        assert m.allow_null is True

    def test_custom_case_sensitive(self):
        m = AcceptedValuesMonitor({
            "column": "status", "allowed_values": ["Active"],
            "case_sensitive": True,
        })
        assert m.case_sensitive is True

    def test_monitor_type(self):
        m = AcceptedValuesMonitor({"column": "x", "allowed_values": ["a"]})
        assert m.monitor_type == "accepted_values"

    def test_allowed_values_stored(self):
        vals = ["pending", "active", "closed"]
        m = AcceptedValuesMonitor({"column": "status", "allowed_values": vals})
        assert m.allowed_values == vals


# ---------------------------------------------------------------------------
# build_query
# ---------------------------------------------------------------------------

class TestAcceptedValuesBuildQuery:
    def test_no_column_raises(self):
        m = AcceptedValuesMonitor({"allowed_values": ["a"]})
        with pytest.raises(ValueError, match="'column'"):
            m.build_query("db", "s", "t")

    def test_no_allowed_values_raises(self):
        m = AcceptedValuesMonitor({"column": "status"})
        with pytest.raises(ValueError, match="'allowed_values'"):
            m.build_query("db", "s", "t")

    def test_build_query_postgres_basic(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["active", "inactive"],
        })
        sql = m.build_query("mydb", "public", "users", dialect="postgres")
        assert '"mydb"."public"."users"' in sql
        assert "total_rows" in sql
        assert "violation_count" in sql

    def test_build_query_bigquery_basic(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["active", "inactive"],
        })
        sql = m.build_query("project", "dataset", "users", dialect="bigquery")
        assert "`project`.`dataset`.`users`" in sql
        assert "total_rows" in sql
        assert "violation_count" in sql

    def test_build_query_case_insensitive_lowercases_values(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["Active", "Inactive"],
            "case_sensitive": False,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "'active'" in sql
        assert "'inactive'" in sql

    def test_build_query_case_insensitive_postgres_uses_varchar(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["active"],
            "case_sensitive": False,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "LOWER" in sql
        assert "VARCHAR" in sql

    def test_build_query_case_insensitive_bigquery_uses_string(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["active"],
            "case_sensitive": False,
        })
        sql = m.build_query("p", "d", "t", dialect="bigquery")
        assert "LOWER" in sql
        assert "STRING" in sql

    def test_build_query_case_sensitive_uses_varchar_no_lower(self):
        m = AcceptedValuesMonitor({
            "column": "code",
            "allowed_values": ["A", "B"],
            "case_sensitive": True,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "VARCHAR" in sql
        assert "LOWER" not in sql

    def test_build_query_allow_null_false_includes_null_check(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["active"],
            "allow_null": False,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "IS NULL" in sql

    def test_build_query_allow_null_true_no_null_check_in_violation(self):
        m = AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": ["active"],
            "allow_null": True,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        # NULLs should be excluded from violations (null guard in condition)
        assert "NOT" in sql and "NULL" in sql

    def test_build_query_values_are_quoted_and_escaped(self):
        m = AcceptedValuesMonitor({
            "column": "note",
            "allowed_values": ["it's fine"],
            "case_sensitive": True,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "it''s fine" in sql


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

class TestAcceptedValuesEvaluate:
    def _make_monitor(self, allowed_values=None, max_violation_pct=0.0,
                      warn_violation_pct=0.0, case_sensitive=False, allow_null=True):
        return AcceptedValuesMonitor({
            "column": "status",
            "allowed_values": allowed_values or ["active", "inactive"],
            "max_violation_pct": max_violation_pct,
            "warn_violation_pct": warn_violation_pct,
            "case_sensitive": case_sensitive,
            "allow_null": allow_null,
        })

    def test_empty_results_returns_error(self):
        m = self._make_monitor()
        result = m.evaluate([], "db.s.t")
        assert result.status == MonitorStatus.ERROR

    def test_empty_table_returns_pass(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 0, "violation_count": 0}], "db.s.t"
        )
        assert result.status == MonitorStatus.PASS
        assert "empty" in result.message.lower()

    def test_zero_violations_returns_pass(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 200, "violation_count": 0}], "db.s.users"
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 0.0

    def test_pass_message_contains_allowed_values(self):
        m = self._make_monitor(allowed_values=["active", "inactive"])
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 0}], "db.s.t"
        )
        assert "'active'" in result.message
        assert "'inactive'" in result.message

    def test_unexpected_values_zero_tolerance_returns_fail(self):
        m = self._make_monitor(max_violation_pct=0.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 5}], "db.s.users"
        )
        assert result.status == MonitorStatus.FAIL
        assert result.value == pytest.approx(5.0)

    def test_unexpected_values_within_tolerance_returns_pass(self):
        m = self._make_monitor(max_violation_pct=10.0, warn_violation_pct=9.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 8}], "db.s.users"
        )
        assert result.status == MonitorStatus.PASS

    def test_unexpected_values_triggers_warn(self):
        m = self._make_monitor(max_violation_pct=10.0, warn_violation_pct=2.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 5}], "db.s.users"
        )
        assert result.status == MonitorStatus.WARN

    def test_unexpected_values_exceeds_fail_threshold(self):
        m = self._make_monitor(max_violation_pct=10.0, warn_violation_pct=2.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 15}], "db.s.users"
        )
        assert result.status == MonitorStatus.FAIL

    def test_fail_message_includes_column_and_count(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 10}], "db.s.users"
        )
        assert "status" in result.message  # column name
        assert "10" in result.message

    def test_details_include_case_sensitive(self):
        m = self._make_monitor(case_sensitive=True)
        result = m.evaluate(
            [{"total_rows": 50, "violation_count": 0}], "db.s.t"
        )
        assert result.details["case_sensitive"] is True

    def test_details_include_allow_null(self):
        m = self._make_monitor(allow_null=False)
        result = m.evaluate(
            [{"total_rows": 50, "violation_count": 3}], "db.s.t"
        )
        assert result.details["allow_null"] is False

    def test_details_include_allowed_values(self):
        vals = ["a", "b", "c"]
        m = self._make_monitor(allowed_values=vals)
        result = m.evaluate(
            [{"total_rows": 50, "violation_count": 0}], "db.s.t"
        )
        assert result.details["allowed_values"] == vals

    def test_details_violation_pct_calculated(self):
        m = self._make_monitor(max_violation_pct=50.0)
        result = m.evaluate(
            [{"total_rows": 200, "violation_count": 10}], "db.s.t"
        )
        assert result.details["violation_pct"] == pytest.approx(5.0)

    def test_threshold_stored_in_result(self):
        m = self._make_monitor(max_violation_pct=3.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 5}], "db.s.t"
        )
        assert result.threshold == pytest.approx(3.0)

    def test_allow_null_false_nulls_count_as_violations(self):
        # With allow_null=False, 3 nulls should be counted by the query;
        # we just verify the evaluate path treats violation_count correctly
        m = self._make_monitor(allow_null=False, max_violation_pct=0.0)
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 3}], "db.s.t"
        )
        assert result.status == MonitorStatus.FAIL

    def test_long_allowed_values_truncated_in_message(self):
        vals = [f"val_{i}" for i in range(15)]
        m = AcceptedValuesMonitor({
            "column": "category",
            "allowed_values": vals,
        })
        result = m.evaluate(
            [{"total_rows": 50, "violation_count": 0}], "db.s.t"
        )
        # First 10 shown, remainder indicated
        assert "+5 more" in result.message

    def test_monitor_type_field(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 100, "violation_count": 0}], "db.s.t"
        )
        assert result.monitor_type == "accepted_values"
