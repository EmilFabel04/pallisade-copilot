"""Tests for DateConsistencyMonitor."""

import pytest
from ..date_consistency import DateConsistencyMonitor
from ..base import MonitorStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(left, operator, right):
    return {"left_column": left, "operator": operator, "right_column": right}


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

class TestDateConsistencyConfig:
    def test_default_max_violation_pct(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")]
        })
        assert m.max_violation_pct == 0.0

    def test_default_warn_violation_pct(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")]
        })
        assert m.warn_violation_pct == 0.0

    def test_default_exclude_nulls(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")]
        })
        assert m.exclude_nulls is True

    def test_custom_exclude_nulls(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("a", "<=", "b")],
            "exclude_nulls": False,
        })
        assert m.exclude_nulls is False

    def test_monitor_type(self):
        m = DateConsistencyMonitor({"rules": [_make_rule("a", "<=", "b")]})
        assert m.monitor_type == "date_consistency"

    def test_rules_stored(self):
        rules = [_make_rule("start_date", "<=", "end_date")]
        m = DateConsistencyMonitor({"rules": rules})
        assert m.rules == rules


# ---------------------------------------------------------------------------
# build_query
# ---------------------------------------------------------------------------

class TestDateConsistencyBuildQuery:
    def test_no_rules_raises(self):
        m = DateConsistencyMonitor({"rules": []})
        with pytest.raises(ValueError, match="at least one rule"):
            m.build_query("db", "s", "t")

    def test_missing_left_column_raises(self):
        m = DateConsistencyMonitor({
            "rules": [{"operator": "<=", "right_column": "end_date"}]
        })
        with pytest.raises(ValueError, match="left_column.*right_column|Rule 0"):
            m.build_query("db", "s", "t")

    def test_missing_right_column_raises(self):
        m = DateConsistencyMonitor({
            "rules": [{"left_column": "start_date", "operator": "<="}]
        })
        with pytest.raises(ValueError, match="left_column.*right_column|Rule 0"):
            m.build_query("db", "s", "t")

    def test_invalid_operator_raises(self):
        m = DateConsistencyMonitor({
            "rules": [{"left_column": "a", "operator": "BETWEEN", "right_column": "b"}]
        })
        with pytest.raises(ValueError, match="operator.*not supported|BETWEEN"):
            m.build_query("db", "s", "t")

    def test_build_query_postgres_basic(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")]
        })
        sql = m.build_query("mydb", "public", "projects", dialect="postgres")
        assert '"mydb"."public"."projects"' in sql
        assert "total_rows" in sql
        assert "violations_rule_0" in sql

    def test_build_query_bigquery_basic(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")]
        })
        sql = m.build_query("project", "dataset", "tasks", dialect="bigquery")
        assert "`project`.`dataset`.`tasks`" in sql
        assert "violations_rule_0" in sql

    def test_build_query_violation_is_negation_of_rule(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")]
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        # Violation = NOT (start_date <= end_date)
        assert "NOT" in sql
        assert "start_date" in sql
        assert "end_date" in sql

    def test_build_query_multiple_rules_generate_multiple_violation_cols(self):
        m = DateConsistencyMonitor({
            "rules": [
                _make_rule("start_date", "<=", "end_date"),
                _make_rule("created_at", "<=", "CURRENT_DATE"),
            ]
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "violations_rule_0" in sql
        assert "violations_rule_1" in sql

    def test_build_query_current_date_dynamic_ref(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("event_date", "<=", "CURRENT_DATE")]
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "CURRENT_DATE" in sql
        # CURRENT_DATE should not be treated as a column name
        assert "event_date" in sql

    def test_build_query_current_timestamp_dynamic_ref(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("ts", "<=", "CURRENT_TIMESTAMP")]
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "CURRENT_TIMESTAMP" in sql

    def test_build_query_now_normalized_to_current_timestamp(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("ts", "<=", "NOW()")]
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "CURRENT_TIMESTAMP" in sql

    def test_build_query_exclude_nulls_true_adds_where_clause(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")],
            "exclude_nulls": True,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "WHERE" in sql
        # sqlglot may render as "NOT x IS NULL" or "x IS NOT NULL"
        assert "NULL" in sql and ("NOT" in sql or "IS NOT NULL" in sql)

    def test_build_query_exclude_nulls_false_no_where_clause(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("start_date", "<=", "end_date")],
            "exclude_nulls": False,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        assert "WHERE" not in sql

    def test_build_query_dynamic_ref_not_added_to_null_filter(self):
        m = DateConsistencyMonitor({
            "rules": [_make_rule("event_date", "<=", "CURRENT_DATE")],
            "exclude_nulls": True,
        })
        sql = m.build_query("db", "s", "t", dialect="postgres")
        # Only event_date should appear in null filter, not CURRENT_DATE
        # sqlglot may render "NOT event_date IS NULL" or "event_date IS NOT NULL"
        assert "event_date" in sql and "NULL" in sql
        assert "CURRENT_DATE IS NOT NULL" not in sql

    def test_build_query_all_valid_operators(self):
        for op in ("<", "<=", "=", ">=", ">", "!="):
            m = DateConsistencyMonitor({
                "rules": [_make_rule("a", op, "b")]
            })
            sql = m.build_query("db", "s", "t", dialect="postgres")
            # sqlglot may rewrite != to <>, so check for either
            if op == "!=":
                assert "<>" in sql or "!=" in sql
            else:
                assert op in sql


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

class TestDateConsistencyEvaluate:
    def _make_monitor(self, rules=None, max_violation_pct=0.0,
                      warn_violation_pct=0.0, exclude_nulls=True):
        return DateConsistencyMonitor({
            "rules": rules or [_make_rule("start_date", "<=", "end_date")],
            "max_violation_pct": max_violation_pct,
            "warn_violation_pct": warn_violation_pct,
            "exclude_nulls": exclude_nulls,
        })

    def test_empty_results_returns_error(self):
        m = self._make_monitor()
        result = m.evaluate([], "db.s.t")
        assert result.status == MonitorStatus.ERROR

    def test_empty_table_returns_pass(self):
        m = self._make_monitor()
        result = m.evaluate([{"total_rows": 0, "violations_rule_0": 0}], "db.s.t")
        assert result.status == MonitorStatus.PASS
        assert "empty" in result.message.lower()

    def test_no_violations_returns_pass(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 500, "violations_rule_0": 0}], "db.s.projects"
        )
        assert result.status == MonitorStatus.PASS
        assert result.value == 0.0

    def test_pass_message_includes_rule_count(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 0}], "db.s.t"
        )
        assert "1 rule" in result.message

    def test_violations_zero_tolerance_returns_fail(self):
        m = self._make_monitor(max_violation_pct=0.0)
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 5}], "db.s.projects"
        )
        assert result.status == MonitorStatus.FAIL
        assert result.value == pytest.approx(5.0)

    def test_violations_within_tolerance_returns_pass(self):
        m = self._make_monitor(max_violation_pct=10.0, warn_violation_pct=9.0)
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 8}], "db.s.projects"
        )
        assert result.status == MonitorStatus.PASS

    def test_violations_triggers_warn(self):
        m = self._make_monitor(max_violation_pct=10.0, warn_violation_pct=2.0)
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 5}], "db.s.t"
        )
        assert result.status == MonitorStatus.WARN

    def test_violations_exceeds_fail_threshold(self):
        m = self._make_monitor(max_violation_pct=10.0, warn_violation_pct=2.0)
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 15}], "db.s.t"
        )
        assert result.status == MonitorStatus.FAIL

    def test_multiple_rules_one_fails(self):
        m = self._make_monitor(
            rules=[
                _make_rule("start_date", "<=", "end_date"),
                _make_rule("created_at", "<=", "updated_at"),
            ],
            max_violation_pct=0.0,
        )
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 0, "violations_rule_1": 10}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.FAIL
        # worst_violation_pct is 10%
        assert result.value == pytest.approx(10.0)

    def test_multiple_rules_all_pass(self):
        m = self._make_monitor(
            rules=[
                _make_rule("start_date", "<=", "end_date"),
                _make_rule("created_at", "<=", "CURRENT_DATE"),
            ]
        )
        result = m.evaluate(
            [{"total_rows": 200, "violations_rule_0": 0, "violations_rule_1": 0}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.PASS

    def test_multiple_rules_fail_message_lists_violations(self):
        m = self._make_monitor(
            rules=[
                _make_rule("start_date", "<=", "end_date"),
                _make_rule("event_date", "<=", "CURRENT_DATE"),
            ],
            max_violation_pct=0.0,
        )
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 3, "violations_rule_1": 7}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.FAIL
        assert "start_date" in result.message
        assert "event_date" in result.message

    def test_details_include_rule_results(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 4}], "db.s.t"
        )
        assert "rules" in result.details
        assert len(result.details["rules"]) == 1
        rule = result.details["rules"][0]
        assert rule["violations"] == 4
        assert rule["violation_pct"] == pytest.approx(4.0)

    def test_details_include_total_violations(self):
        m = self._make_monitor(
            rules=[
                _make_rule("a", "<=", "b"),
                _make_rule("c", "<=", "d"),
            ],
            max_violation_pct=100.0,
        )
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 3, "violations_rule_1": 7}],
            "db.s.t",
        )
        assert result.details["total_violations"] == 10

    def test_details_include_worst_rule_index(self):
        m = self._make_monitor(
            rules=[
                _make_rule("a", "<=", "b"),
                _make_rule("c", "<=", "d"),
            ],
            max_violation_pct=100.0,
        )
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 2, "violations_rule_1": 8}],
            "db.s.t",
        )
        assert result.details["worst_rule_index"] == 1

    def test_current_date_rule_in_rule_desc(self):
        m = self._make_monitor(
            rules=[_make_rule("event_date", "<=", "CURRENT_DATE")],
            max_violation_pct=0.0,
        )
        result = m.evaluate(
            [{"total_rows": 50, "violations_rule_0": 2}], "db.s.t"
        )
        rule_desc = result.details["rules"][0]["rule"]
        assert "CURRENT_DATE" in rule_desc

    def test_threshold_stored_in_result(self):
        m = self._make_monitor(max_violation_pct=5.0)
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 10}], "db.s.t"
        )
        assert result.threshold == pytest.approx(5.0)

    def test_monitor_type_field(self):
        m = self._make_monitor()
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 0}], "db.s.t"
        )
        assert result.monitor_type == "date_consistency"

    def test_status_uses_worst_individual_rule_not_average(self):
        # Rule 0: 1% violation (ok), Rule 1: 15% violation (fail at 10%)
        m = self._make_monitor(
            rules=[
                _make_rule("a", "<=", "b"),
                _make_rule("c", "<=", "d"),
            ],
            max_violation_pct=10.0,
        )
        result = m.evaluate(
            [{"total_rows": 100, "violations_rule_0": 1, "violations_rule_1": 15}],
            "db.s.t",
        )
        assert result.status == MonitorStatus.FAIL
        assert result.value == pytest.approx(15.0)
