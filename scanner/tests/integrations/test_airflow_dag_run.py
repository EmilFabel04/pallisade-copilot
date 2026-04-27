"""Tests for AirflowDAGRun computed properties."""
from datetime import datetime, timezone

import pytest

from integrations.airflow import AirflowDAGRun, DAGState


def _run(start: datetime | None, end: datetime | None) -> AirflowDAGRun:
    return AirflowDAGRun(
        dag_id="my_dag",
        run_id="run_123",
        state=DAGState.SUCCESS,
        start_date=start,
        end_date=end,
    )


def test_duration_seconds_returns_seconds_between_start_and_end():
    """get_dag_run_history accesses run.duration_seconds — it must exist
    and return total seconds between start_date and end_date."""
    start = datetime(2026, 4, 27, 6, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 27, 6, 12, 30, tzinfo=timezone.utc)

    run = _run(start, end)

    assert run.duration_seconds == pytest.approx(750.0)  # 12 min 30 sec


def test_duration_seconds_none_when_run_not_finished():
    """A run that hasn't finished yet has no duration."""
    run = _run(datetime(2026, 4, 27, 6, 0, 0, tzinfo=timezone.utc), None)

    assert run.duration_seconds is None


def test_duration_seconds_none_when_run_not_started():
    run = _run(None, None)

    assert run.duration_seconds is None
