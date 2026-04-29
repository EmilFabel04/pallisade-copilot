"""Surgical adjacent-path steering: when a primary tool returns empty/unavailable
and an adjacent integration could answer the same question, the chat loop injects
a one-shot steering message. These tests pin the per-rule behaviour and the
loop-prevention guards so the steering can never recurse or fire spuriously."""
from copilot.llm import (
    _evaluate_adjacent_path_rule,
    _is_empty_listish,
    ADJACENT_PATH_RULES,
    MAX_ADJACENT_INJECTIONS,
)
from copilot.tools import ToolResult


# -- _is_empty_listish predicate --------------------------------------------------


def test_is_empty_listish_recognises_common_empty_shapes():
    assert _is_empty_listish(None)
    assert _is_empty_listish([])
    assert _is_empty_listish({"monitors": []})
    assert _is_empty_listish({"items": []})
    assert _is_empty_listish({"results": []})
    assert _is_empty_listish({"count": 0})
    assert _is_empty_listish({"count": "0"})


def test_is_empty_listish_recognises_non_empty():
    assert not _is_empty_listish([1])
    assert not _is_empty_listish({"monitors": [{"id": "m1"}]})
    assert not _is_empty_listish({"count": 5})
    assert not _is_empty_listish({"available": False})  # not list-shaped


# -- Rule 1: dbt run history unavailable → use Airflow ----------------------------


_DBT_UNAVAIL = ToolResult(
    success=True,
    data={"available": False, "reason": "dbt is GitHub-mode"},
)


def test_rule1_fires_when_dbt_unavailable_and_airflow_connected():
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=_DBT_UNAVAIL,
        integration_types={"AIRFLOW", "DBT_CORE", "BIGQUERY"},
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is not None
    rule_name, msg = fired
    assert rule_name == "dbt_run_history_unavailable_use_airflow"
    assert "Airflow" in msg
    assert "get_dag_run_history" in msg


def test_rule1_skips_when_airflow_not_connected():
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=_DBT_UNAVAIL,
        integration_types={"DBT_CORE", "BIGQUERY"},  # no AIRFLOW
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is None


def test_rule1_skips_when_dbt_history_actually_available():
    available_result = ToolResult(success=True, data={"available": True, "runs": []})
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=available_result,
        integration_types={"AIRFLOW"},
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is None


def test_rule1_skips_when_get_dag_run_history_already_called_this_turn():
    # If the LLM already pulled Airflow run history, no need to nag.
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=_DBT_UNAVAIL,
        integration_types={"AIRFLOW"},
        all_tool_calls=[
            {"tool": "get_dag_run_history", "input": {"dag_id": "pallisade_dbt"}, "result": {}}
        ],
        fired_rule_names=set(),
    )
    assert fired is None


# -- Rule 2: empty monitor list with filter → broaden -----------------------------


def test_rule2_fires_when_empty_monitor_list_with_status_filter():
    fired = _evaluate_adjacent_path_rule(
        tool_name="list_configured_monitors",
        tool_args={"status": "FAIL,ERROR", "monitor_type": "DBT_CORE_SOURCE_VALIDATION"},
        tool_result=ToolResult(success=True, data={"monitors": [], "count": 0}),
        integration_types={"DBT_CORE"},
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is not None
    rule_name, msg = fired
    assert rule_name == "empty_monitors_with_filter_broaden"
    assert "without those filters" in msg.lower() or "without the filter" in msg.lower() or "without those" in msg.lower()


def test_rule2_fires_when_only_monitor_type_filter_used():
    fired = _evaluate_adjacent_path_rule(
        tool_name="list_configured_monitors",
        tool_args={"monitor_type": "DBT_CORE_SOURCE_VALIDATION"},
        tool_result=ToolResult(success=True, data=[]),
        integration_types=set(),
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is not None


def test_rule2_skips_when_no_filter_applied():
    # Empty result with NO filter is the genuine answer ("you have 0 monitors").
    # The rule must not nag here.
    fired = _evaluate_adjacent_path_rule(
        tool_name="list_configured_monitors",
        tool_args={},
        tool_result=ToolResult(success=True, data={"monitors": []}),
        integration_types=set(),
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is None


def test_rule2_skips_when_monitor_list_is_non_empty():
    fired = _evaluate_adjacent_path_rule(
        tool_name="list_configured_monitors",
        tool_args={"status": "FAIL"},
        tool_result=ToolResult(success=True, data={"monitors": [{"id": "m1"}]}),
        integration_types=set(),
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is None


# -- Loop prevention guards -------------------------------------------------------


def test_each_rule_fires_at_most_once_per_turn():
    fired_set = {"dbt_run_history_unavailable_use_airflow"}
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=_DBT_UNAVAIL,
        integration_types={"AIRFLOW"},
        all_tool_calls=[],
        fired_rule_names=fired_set,
    )
    assert fired is None


def test_hard_cap_prevents_unbounded_injections():
    # Even if rules would otherwise match, hitting MAX_ADJACENT_INJECTIONS
    # makes the evaluator return None — defense in depth against a future rule
    # that mismatches the per-rule once-only guard.
    saturated = {f"placeholder_{i}" for i in range(MAX_ADJACENT_INJECTIONS)}
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=_DBT_UNAVAIL,
        integration_types={"AIRFLOW"},
        all_tool_calls=[],
        fired_rule_names=saturated,
    )
    assert fired is None


def test_failed_tool_results_dont_trigger_rules():
    # If a tool blew up (success=False), don't try to extract empty/unavailable
    # signal from it — the failure itself is the signal.
    failed = ToolResult(success=False, error="auth failed", data=None)
    fired = _evaluate_adjacent_path_rule(
        tool_name="get_dbt_run_history",
        tool_args={},
        tool_result=failed,
        integration_types={"AIRFLOW"},
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is None


def test_unrelated_tool_does_not_trigger_any_rule():
    # A tool that none of the rules trigger on returns None even with empty data.
    fired = _evaluate_adjacent_path_rule(
        tool_name="query_warehouse",
        tool_args={"sql": "select 1"},
        tool_result=ToolResult(success=True, data={"rows": []}),
        integration_types={"AIRFLOW", "BIGQUERY"},
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    assert fired is None


def test_matches_predicate_exception_is_swallowed():
    # If a rule's matches() ever raises (bad data shape, etc.), the evaluator
    # must not crash the chat loop — it should just skip the rule.
    bad_data = ToolResult(success=True, data="not-a-dict-or-list-as-expected")
    fired = _evaluate_adjacent_path_rule(
        tool_name="list_configured_monitors",
        tool_args={"status": "FAIL"},
        tool_result=bad_data,
        integration_types=set(),
        all_tool_calls=[],
        fired_rule_names=set(),
    )
    # The rule may legitimately decline, but the call must not raise.
    assert fired is None or isinstance(fired, tuple)


# -- Registry shape ---------------------------------------------------------------


def test_all_rule_names_are_unique():
    names = [r.name for r in ADJACENT_PATH_RULES]
    assert len(names) == len(set(names)), f"duplicate rule names: {names}"


def test_max_adjacent_injections_is_bounded():
    # If someone bumps this to 50, that's a footgun — keep it small.
    assert 1 <= MAX_ADJACENT_INJECTIONS <= 5
