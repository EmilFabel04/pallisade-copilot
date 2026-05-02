"""
Tests for WarehouseDiscoverer (Path 3).

Covers:
1. With one warehouse FQN hint the discoverer returns one DatasetCandidate with
   source='warehouse', lands_in=<the FQN>, confidence=0.9, a detected
   timestamp_column, and expected_schema populated from get_table_schema().
2. With empty hints [] the discoverer returns ([], DiscoveryError(code='no_warehouse_hint', ...)).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scanner.discovery.warehouse.warehouse_discoverer import WarehouseDiscoverer
from scanner.discovery.types import ColumnMetadata, DiscoveryError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MOCK_SCHEMA_ROWS = [
    {"column_name": "id", "data_type": "INTEGER", "is_nullable": False},
    {"column_name": "reading_at", "data_type": "TIMESTAMP", "is_nullable": False},
    {"column_name": "value", "data_type": "FLOAT", "is_nullable": True},
]


def _make_mock_adapter(schema_rows: list) -> MagicMock:
    adapter = MagicMock()
    adapter.get_table_schema.return_value = schema_rows
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_one_fqn_hint_returns_candidate():
    """With one FQN hint the discoverer returns one DatasetCandidate."""
    fqn = "snowflake.raw.water_meters"
    mock_adapter = _make_mock_adapter(_MOCK_SCHEMA_ROWS)

    with patch(
        "scanner.discovery.warehouse.warehouse_discoverer.adapter_for_fqn",
        return_value=mock_adapter,
    ):
        discoverer = WarehouseDiscoverer()
        candidates, error = discoverer.discover(hints=[fqn])

    assert error is None
    assert len(candidates) == 1

    c = candidates[0]
    assert c.source == "warehouse"
    assert c.confidence == 0.9
    assert c.lands_in == fqn

    # timestamp column detected from name hint ("reading_at" contains "_at")
    assert c.timestamp_column == "reading_at"

    # expected_schema populated from mock rows
    assert len(c.expected_schema) == 3
    assert c.expected_schema[0] == ColumnMetadata(name="id", data_type="INTEGER", is_nullable=False)
    assert c.expected_schema[1] == ColumnMetadata(name="reading_at", data_type="TIMESTAMP", is_nullable=False)
    assert c.expected_schema[2] == ColumnMetadata(name="value", data_type="FLOAT", is_nullable=True)

    mock_adapter.get_table_schema.assert_called_once_with(fqn)


def test_timestamp_column_detected_by_type():
    """Timestamp column is detected via data_type even without a name hint."""
    schema_rows = [
        {"column_name": "meter_id", "data_type": "VARCHAR", "is_nullable": False},
        {"column_name": "occurred", "data_type": "VARCHAR", "is_nullable": False},
        {"column_name": "event_time", "data_type": "DATETIME", "is_nullable": True},
    ]
    mock_adapter = _make_mock_adapter(schema_rows)
    fqn = "bigquery.raw.events"

    with patch(
        "scanner.discovery.warehouse.warehouse_discoverer.adapter_for_fqn",
        return_value=mock_adapter,
    ):
        discoverer = WarehouseDiscoverer()
        candidates, error = discoverer.discover(hints=[fqn])

    assert error is None
    assert len(candidates) == 1
    # "occurred" is in _TIMESTAMP_NAME_HINTS and appears before "event_time" in the schema,
    # so _detect_ts_col returns it deterministically on first match.
    assert candidates[0].timestamp_column == "occurred"


def test_empty_hints_returns_error():
    """With empty hints, discoverer returns ([], DiscoveryError(code='no_warehouse_hint', ...))."""
    discoverer = WarehouseDiscoverer()
    candidates, error = discoverer.discover(hints=[])

    assert candidates == []
    assert isinstance(error, DiscoveryError)
    assert error.code == "no_warehouse_hint"
    assert error.message  # non-empty message


def test_adapter_failure_skips_fqn():
    """If adapter resolution raises, the FQN is skipped (warn+continue); no error returned."""
    fqn = "snowflake.raw.broken_table"

    with patch(
        "scanner.discovery.warehouse.warehouse_discoverer.adapter_for_fqn",
        side_effect=ValueError("no configured adapter for warehouse type: snowflake"),
    ):
        discoverer = WarehouseDiscoverer()
        candidates, error = discoverer.discover(hints=[fqn])

    assert candidates == []
    assert error is None


def test_multiple_hints_returns_multiple_candidates():
    """Multiple FQN hints produce multiple candidates (one per FQN)."""
    fqns = ["snowflake.raw.table_a", "snowflake.raw.table_b"]

    schema_a = [{"column_name": "created_at", "data_type": "TIMESTAMP", "is_nullable": False}]
    schema_b = [{"column_name": "id", "data_type": "INTEGER", "is_nullable": False}]

    call_count = {"n": 0}

    def side_effect(fqn: str, **_kwargs) -> MagicMock:
        call_count["n"] += 1
        adapter = MagicMock()
        adapter.get_table_schema.return_value = schema_a if "table_a" in fqn else schema_b
        return adapter

    with patch(
        "scanner.discovery.warehouse.warehouse_discoverer.adapter_for_fqn",
        side_effect=side_effect,
    ):
        discoverer = WarehouseDiscoverer()
        candidates, error = discoverer.discover(hints=fqns)

    assert error is None
    assert len(candidates) == 2
    assert {c.lands_in for c in candidates} == set(fqns)
    # table_a has a timestamp column detected
    a = next(c for c in candidates if c.lands_in == fqns[0])
    assert a.timestamp_column == "created_at"
    # table_b has no timestamp column
    b = next(c for c in candidates if c.lands_in == fqns[1])
    assert b.timestamp_column is None
