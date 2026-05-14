from __future__ import annotations

from scanner.lineage.sla_analysis import (
    AnalysisPlan,
    AnalyzeResult,
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
