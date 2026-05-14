from __future__ import annotations

from unittest.mock import MagicMock, patch

from scanner.lineage.sla_analysis import (
    AnalysisPlan,
    AnalyzeResult,
    analyze_sla,
    plan_from_dict,
    plan_to_dict,
)


def _example_plan() -> AnalysisPlan:
    return AnalysisPlan(
        table_fqn="acme-484520.analytics.daily_revenue",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={
            "column": "date",
            "confidence": "weak",
            "score": 0.35,
            "rationale": "no canonical loaded_at column",
        },
        volume_timestamp_candidates=[
            {"column": "date", "data_type": "DATE", "score": 0.35},
            {"column": "created_at", "data_type": "TIMESTAMP", "score": 0.25},
        ],
        schema_snapshot={"columns": [{"name": "date", "data_type": "DATE"}]},
        row_count=59,
        unsupported=False,
        skipped_reason=None,
    )


def test_plan_roundtrips_through_dict():
    plan = _example_plan()
    restored = plan_from_dict(plan_to_dict(plan))
    assert restored == plan


def test_analyze_result_ready_has_no_clarifications():
    plan = _example_plan()
    result = AnalyzeResult(
        table_fqn=plan.table_fqn,
        plan=plan,
        status="ready",
        clarification_ids=[],
    )
    assert result.status == "ready"
    assert result.clarification_ids == []


def test_analyze_result_awaiting_has_clarifications():
    plan = _example_plan()
    result = AnalyzeResult(
        table_fqn=plan.table_fqn,
        plan=plan,
        status="awaiting_clarifications",
        clarification_ids=["cuid_abc"],
    )
    assert result.status == "awaiting_clarifications"
    assert result.clarification_ids == ["cuid_abc"]


def test_plan_roundtrips_when_unsupported():
    plan = AnalysisPlan(
        table_fqn="proj.ds.empty",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick=None,
        volume_timestamp_candidates=[],
        schema_snapshot={"columns": []},
        row_count=None,
        unsupported=True,
        skipped_reason="No columns visible to the adapter.",
    )
    restored = plan_from_dict(plan_to_dict(plan))
    assert restored == plan
    assert restored.unsupported is True
    assert restored.skipped_reason == "No columns visible to the adapter."


# ---------------------------------------------------------------------------
# analyze_sla tests (Task 2)
# ---------------------------------------------------------------------------


def _col(name: str, dtype: str = "TIMESTAMP") -> MagicMock:
    c = MagicMock()
    c.name = name
    c.data_type = dtype
    return c


def _adapter_with(columns):
    a = MagicMock()
    a.get_columns.return_value = columns
    a.get_row_count.return_value = 100
    return a


def test_analyze_returns_ready_when_pick_is_strong():
    # loaded_at scores 0.9, above the 0.85 threshold — no clarification emitted.
    adapter = _adapter_with([_col("loaded_at", "TIMESTAMP"), _col("id", "INT64")])
    with patch(
        "scanner.lineage.sla_analysis._call_nextjs_create_context_request"
    ) as mock_emit, patch(
        "scanner.lineage.sla_analysis._get_confidence_threshold", return_value=0.85
    ):
        result = analyze_sla(
            table_fqn="proj.ds.t",
            adapter=adapter,
            pipeline_stack_id="stack_1",
            organization_id="org_1",
        )
    assert result.status == "ready"
    assert result.clarification_ids == []
    assert mock_emit.call_count == 0
    assert result.plan.volume_timestamp_pick["column"] == "loaded_at"


def test_analyze_returns_awaiting_when_pick_is_weak():
    # Two ambiguous-named timestamp columns — picker scores 0.5, below 0.85 threshold.
    adapter = _adapter_with([_col("ts", "TIMESTAMP"), _col("event_time", "TIMESTAMP")])
    with patch(
        "scanner.lineage.sla_analysis._call_nextjs_create_context_request",
        return_value={"context_request_id": "ctx_123"},
    ) as mock_emit, patch(
        "scanner.lineage.sla_analysis._get_confidence_threshold", return_value=0.85
    ):
        result = analyze_sla(
            table_fqn="proj.ds.t",
            adapter=adapter,
            pipeline_stack_id="stack_1",
            organization_id="org_1",
        )
    assert result.status == "awaiting_clarifications"
    assert result.clarification_ids == ["ctx_123"]
    assert mock_emit.call_count == 1


def test_analyze_with_no_pipeline_scope_does_not_emit():
    # Without pipeline_stack_id, clarification path is skipped entirely.
    adapter = _adapter_with([_col("ts", "TIMESTAMP"), _col("event_time", "TIMESTAMP")])
    with patch(
        "scanner.lineage.sla_analysis._call_nextjs_create_context_request"
    ) as mock_emit:
        result = analyze_sla(
            table_fqn="proj.ds.t",
            adapter=adapter,
            pipeline_stack_id=None,
            organization_id=None,
        )
    assert result.status == "ready"
    assert mock_emit.call_count == 0


def test_analyze_skips_when_no_columns():
    adapter = MagicMock()
    adapter.get_columns.return_value = []
    adapter.get_row_count.return_value = 0
    result = analyze_sla(
        table_fqn="proj.ds.t",
        adapter=adapter,
        pipeline_stack_id="stack_1",
        organization_id="org_1",
    )
    assert result.plan.unsupported is True
    assert result.plan.skipped_reason
