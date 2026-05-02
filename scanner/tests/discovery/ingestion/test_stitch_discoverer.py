"""
Tests for StitchIngestionDiscoverer (Path 2).

Covers:
1. find_matching_connectors(host) returns one ConnectorMatch when a source's
   properties.host matches the input host (case-insensitive).
2. list_source_tables(match) returns one DatasetCandidate per stream with:
   - source='ingestion'
   - confidence=1.0
   - lands_in formed as '<dest_type>.<target_schema>.<stream_name>'
   - timestamp_column detected from columns whose type is in the TIMESTAMP family
   - expected_schema populated
3. No matching host → find_matching_connectors returns [].
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scanner.discovery.ingestion.stitch import StitchIngestionDiscoverer
from scanner.discovery.ingestion.base import ConnectorMatch
from scanner.discovery.types import ColumnMetadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_CONNECTORS = [
    {
        "id": "src_stitch_1",
        "properties": {
            "host": {"value": "water-api.example.com"},
            "port": {"value": "5432"},
            "database": {"value": "water_db"},
        },
        "target_id": "dest_snowflake",
        "destination": {
            "type": "snowflake",
        },
        "target_schema": "raw_water",
        "streams": [
            {
                "name": "water_meters",
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False},
                    {"name": "recorded_at", "type": "TIMESTAMP", "nullable": False},
                    {"name": "value", "type": "FLOAT", "nullable": True},
                ],
            },
        ],
    },
    {
        "id": "src_stitch_2",
        "properties": {
            "host": {"value": "other-api.example.com"},
        },
        "target_id": "dest_bq",
        "destination": {
            "type": "bigquery",
        },
        "target_schema": "other",
        "streams": [],
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_find_matching_connectors_returns_match():
    """Matching host returns exactly one ConnectorMatch."""
    discoverer = StitchIngestionDiscoverer(org_id=None, stack_id=None)

    with patch.object(discoverer, "_list_connectors", return_value=_FAKE_CONNECTORS):
        matches = discoverer.find_matching_connectors("water-api.example.com")

    assert len(matches) == 1
    m = matches[0]
    assert isinstance(m, ConnectorMatch)
    assert m.driver_id == "stitch"
    assert m.connector_id == "src_stitch_1"
    assert m.source_host == "water-api.example.com"
    assert m.raw_config is _FAKE_CONNECTORS[0]


def test_find_matching_connectors_case_insensitive():
    """Host matching is case-insensitive."""
    discoverer = StitchIngestionDiscoverer(org_id=None, stack_id=None)

    with patch.object(discoverer, "_list_connectors", return_value=_FAKE_CONNECTORS):
        matches = discoverer.find_matching_connectors("WATER-API.EXAMPLE.COM")

    assert len(matches) == 1
    assert matches[0].connector_id == "src_stitch_1"


def test_find_matching_connectors_no_match():
    """No matching host → empty list."""
    discoverer = StitchIngestionDiscoverer(org_id=None, stack_id=None)

    with patch.object(discoverer, "_list_connectors", return_value=_FAKE_CONNECTORS):
        matches = discoverer.find_matching_connectors("no-match.example.com")

    assert matches == []


def test_list_source_tables_returns_candidate():
    """list_source_tables returns one DatasetCandidate per stream."""
    discoverer = StitchIngestionDiscoverer(org_id=None, stack_id=None)
    match = ConnectorMatch(
        driver_id="stitch",
        connector_id="src_stitch_1",
        source_host="water-api.example.com",
        raw_config=_FAKE_CONNECTORS[0],
    )

    candidates = discoverer.list_source_tables(match)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.source == "ingestion"
    assert c.confidence == 1.0
    assert c.lands_in == "snowflake.raw_water.water_meters"
    assert c.timestamp_column == "recorded_at"
    assert c.endpoint is None
    assert c.json_root is None

    assert len(c.expected_schema) == 3
    assert c.expected_schema[0] == ColumnMetadata(name="id", data_type="INTEGER", is_nullable=False)
    assert c.expected_schema[1] == ColumnMetadata(name="recorded_at", data_type="TIMESTAMP", is_nullable=False)
    assert c.expected_schema[2] == ColumnMetadata(name="value", data_type="FLOAT", is_nullable=True)


def test_list_source_tables_no_timestamp():
    """When no column has a TIMESTAMP-family type, timestamp_column is None."""
    discoverer = StitchIngestionDiscoverer(org_id=None, stack_id=None)
    raw_config = {
        "id": "src_no_ts",
        "properties": {"host": {"value": "api.example.com"}},
        "target_id": "dest_bq",
        "destination": {"type": "bigquery"},
        "target_schema": "raw",
        "streams": [
            {
                "name": "readings",
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False},
                    {"name": "value", "type": "FLOAT", "nullable": True},
                ],
            },
        ],
    }
    match = ConnectorMatch(
        driver_id="stitch",
        connector_id="src_no_ts",
        source_host="api.example.com",
        raw_config=raw_config,
    )

    candidates = discoverer.list_source_tables(match)

    assert len(candidates) == 1
    assert candidates[0].timestamp_column is None
    assert candidates[0].lands_in == "bigquery.raw.readings"
