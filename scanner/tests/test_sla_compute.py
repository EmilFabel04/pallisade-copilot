from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scanner.lineage.sla_analysis import AnalysisPlan
from scanner.lineage.sla_discovery import compute_sla


def _plan(table_fqn: str, ts_col: str = "loaded_at") -> AnalysisPlan:
    return AnalysisPlan(
        table_fqn=table_fqn,
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={"column": ts_col, "confidence": 0.9},
        volume_timestamp_candidates=[{"column": ts_col, "data_type": "TIMESTAMP", "confidence": 0.9}],
        schema_snapshot={"columns": [{"name": ts_col, "data_type": "TIMESTAMP"}]},
        row_count=100,
        unsupported=False,
        skipped_reason=None,
    )


def _col(name: str, dtype: str = "TIMESTAMP"):
    c = MagicMock()
    c.name = name
    c.data_type = dtype
    return c


def _adapter():
    a = MagicMock()
    a.get_columns.return_value = [_col("loaded_at"), _col("alt_col")]
    a.execute_query.return_value = [
        {"day": "2026-05-13", "row_count": 100},
        {"day": "2026-05-12", "row_count": 105},
        {"day": "2026-05-11", "row_count": 98},
    ]
    a.get_row_count.return_value = 100
    return a


def test_compute_with_empty_answers_uses_plan_pick():
    plan = _plan("proj.ds.t", ts_col="loaded_at")
    result = compute_sla(plan, _adapter(), answers={})
    assert result.volume is not None
    assert result.volume.get("timeColumn") == "loaded_at"


def test_compute_with_answer_overrides_plan_pick():
    plan = _plan("proj.ds.t", ts_col="loaded_at")
    adapter = _adapter()
    answers = {"ctx_xyz": {"column": "alt_col"}}
    result = compute_sla(plan, adapter, answers=answers)
    assert result.volume.get("timeColumn") == "alt_col"


def test_compute_skips_when_plan_unsupported():
    plan = AnalysisPlan(
        table_fqn="proj.ds.t",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick=None,
        volume_timestamp_candidates=[],
        schema_snapshot={"columns": []},
        row_count=None,
        unsupported=True,
        skipped_reason="No columns visible",
    )
    result = compute_sla(plan, _adapter(), answers={})
    assert result.unsupported is True
    assert result.skipped_reason == "No columns visible"
