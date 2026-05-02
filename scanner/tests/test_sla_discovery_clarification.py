"""Smoke tests for the confidence-aware timestamp picker + clarification emit.

Covers:
  * ``_pick_volume_timestamp_column`` returning a populated ``TimestampPick``
    with the expected confidence tiers.
  * ``_try_emit_timestamp_clarification`` short-circuiting cleanly when a
    pipeline scope is missing or confidence is high enough.
  * ``_compute_volume`` marking the result tentative + carrying a context
    request id when the picker scored low and Next.js returned an id.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scanner.lineage.sla_discovery import (
    TimestampPick,
    _compute_volume,
    _pick_volume_timestamp_column,
    _try_emit_timestamp_clarification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name: str, dtype: str = "TIMESTAMP") -> MagicMock:
    c = MagicMock()
    c.name = name
    c.data_type = dtype
    return c


def _adapter_with(columns):
    a = MagicMock()
    a.get_columns.return_value = columns
    return a


# ---------------------------------------------------------------------------
# _pick_volume_timestamp_column
# ---------------------------------------------------------------------------

def test_pick_returns_strong_confidence_for_loaded_at():
    adapter = _adapter_with([
        _col("loaded_at", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert isinstance(pick, TimestampPick)
    assert pick.column == "loaded_at"
    assert "loaded_at" in pick.candidates
    assert pick.confidence >= 0.85


def test_pick_returns_strong_confidence_for_ingested_at():
    adapter = _adapter_with([
        _col("ingested_at", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert pick.column == "ingested_at"
    assert pick.confidence >= 0.85


def test_pick_returns_medium_confidence_for_updated_at():
    adapter = _adapter_with([
        _col("updated_at", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert pick.column == "updated_at"
    assert 0.6 <= pick.confidence < 0.85


def test_pick_returns_low_confidence_when_no_preferred_match():
    adapter = _adapter_with([
        _col("weird_ts", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert pick.column == "weird_ts"
    assert "weird_ts" in pick.candidates
    assert pick.confidence < 0.7  # below default threshold (0.7) → triggers clarification


def test_pick_returns_none_when_no_timestamp_columns():
    adapter = _adapter_with([
        _col("id", "INT64"),
        _col("name", "STRING"),
    ])
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert pick.column is None
    assert pick.candidates == []
    assert pick.confidence == 0.0


def test_pick_prefers_strong_over_medium_when_both_present():
    # If a table has both loaded_at AND updated_at, the picker should pick
    # the strong-confidence one.
    adapter = _adapter_with([
        _col("updated_at", "TIMESTAMP"),
        _col("loaded_at", "TIMESTAMP"),
    ])
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert pick.column == "loaded_at"
    assert pick.confidence >= 0.85
    # Both should appear in candidates regardless of ranking.
    assert set(pick.candidates) == {"updated_at", "loaded_at"}


def test_pick_handles_get_columns_failure_gracefully():
    adapter = MagicMock()
    adapter.get_columns.side_effect = RuntimeError("boom")
    pick = _pick_volume_timestamp_column(adapter, "raw.orders")
    assert pick.column is None
    assert pick.candidates == []
    assert pick.confidence == 0.0


# ---------------------------------------------------------------------------
# _try_emit_timestamp_clarification
# ---------------------------------------------------------------------------

def test_emit_skipped_without_pipeline_stack():
    pick = TimestampPick(column="weird_ts", candidates=["weird_ts"], confidence=0.5)
    # No pipeline stack → no emit, returns None — even with low confidence.
    out = _try_emit_timestamp_clarification(
        table_fqn="raw.orders",
        pick=pick,
        pipeline_stack_id=None,
        organization_id="org_1",
    )
    assert out is None


def test_emit_skipped_when_confidence_high_enough():
    pick = TimestampPick(column="loaded_at", candidates=["loaded_at"], confidence=0.9)
    out = _try_emit_timestamp_clarification(
        table_fqn="raw.orders",
        pick=pick,
        pipeline_stack_id="ps_1",
        organization_id="org_1",
    )
    assert out is None


def test_emit_skipped_when_no_candidates():
    # Nothing to disambiguate between → no emit.
    pick = TimestampPick(column=None, candidates=[], confidence=0.0)
    out = _try_emit_timestamp_clarification(
        table_fqn="raw.orders",
        pick=pick,
        pipeline_stack_id="ps_1",
        organization_id="org_1",
    )
    assert out is None


def test_emit_calls_nextjs_when_low_confidence():
    pick = TimestampPick(column="weird_ts", candidates=["weird_ts", "other_ts"], confidence=0.5)
    with patch("scanner.lineage.sla_discovery._call_nextjs_create_context_request") as mock_call:
        mock_call.return_value = {"context_request_id": "cr_123", "suppressed": False}
        out = _try_emit_timestamp_clarification(
            table_fqn="raw.orders",
            pick=pick,
            pipeline_stack_id="ps_1",
            organization_id="org_1",
        )
    assert out == {"context_request_id": "cr_123", "suppressed": False}
    mock_call.assert_called_once()
    kwargs = mock_call.call_args.kwargs
    assert kwargs["pipeline_stack_id"] == "ps_1"
    assert kwargs["organization_id"] == "org_1"
    assert kwargs["kind"] == "timestamp_choice"
    assert kwargs["scope_type"] == "node"
    assert kwargs["scope_ref"] == "raw.orders"
    assert kwargs["payload"]["candidates"] == ["weird_ts", "other_ts"]
    assert kwargs["payload"]["confidence"] == 0.5
    assert kwargs["payload"]["table_fqn"] == "raw.orders"


# ---------------------------------------------------------------------------
# _compute_volume marks tentative on low-confidence emit
# ---------------------------------------------------------------------------

def test_compute_volume_marks_tentative_when_clarification_emitted():
    adapter = _adapter_with([
        _col("weird_ts", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    metadata = {"row_count": 1000}
    with patch(
        "scanner.lineage.sla_discovery._call_nextjs_create_context_request"
    ) as mock_call:
        mock_call.return_value = {"context_request_id": "cr_42", "suppressed": False}
        result = _compute_volume(
            adapter,
            "raw.orders",
            metadata=metadata,
            pipeline_stack_id="ps_1",
            organization_id="org_1",
        )
    assert result is not None
    assert result.get("tentative") is True
    assert result.get("context_request_id") == "cr_42"
    assert result["currentRows"] == 1000


def test_compute_volume_not_tentative_when_no_pipeline_stack():
    adapter = _adapter_with([
        _col("weird_ts", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    metadata = {"row_count": 1000}
    with patch(
        "scanner.lineage.sla_discovery._call_nextjs_create_context_request"
    ) as mock_call:
        # No pipeline_stack_id → emit is short-circuited and Next.js not called.
        result = _compute_volume(
            adapter,
            "raw.orders",
            metadata=metadata,
            pipeline_stack_id=None,
            organization_id=None,
        )
    assert result is not None
    assert "tentative" not in result
    assert "context_request_id" not in result
    mock_call.assert_not_called()


def test_compute_volume_not_tentative_when_suppressed():
    adapter = _adapter_with([
        _col("weird_ts", "TIMESTAMP"),
        _col("id", "INT64"),
    ])
    metadata = {"row_count": 1000}
    with patch(
        "scanner.lineage.sla_discovery._call_nextjs_create_context_request"
    ) as mock_call:
        # Next.js says "suppressed" because the user recently dismissed.
        mock_call.return_value = {"context_request_id": None, "suppressed": True}
        result = _compute_volume(
            adapter,
            "raw.orders",
            metadata=metadata,
            pipeline_stack_id="ps_1",
            organization_id="org_1",
        )
    assert result is not None
    # Suppressed → don't surface tentative; respect the dismissal cooldown.
    assert "tentative" not in result
    assert "context_request_id" not in result
