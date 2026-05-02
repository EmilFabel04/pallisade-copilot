"""
Tests for AirbyteIngestionDiscoverer (Path 2).

Covers:
1. find_matching_connectors(host) returns one ConnectorMatch when a connection's
   source.connectionConfiguration.host matches (case-insensitive).
2. list_source_tables(match) returns one DatasetCandidate per table in the
   discovered_catalog with:
   - source='ingestion'
   - confidence=1.0
   - lands_in formed as '<dest_wh_type>.<namespace>.<stream_name>'
   - timestamp_column detected from columns whose type is in the TIMESTAMP family
   - expected_schema populated from stream columns
3. No matching host → find_matching_connectors returns [].
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scanner.discovery.ingestion.airbyte import AirbyteIngestionDiscoverer, _airbyte_type_to_str
from scanner.discovery.ingestion.base import ConnectorMatch
from scanner.discovery.types import ColumnMetadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_CONNECTORS = [
    {
        "id": "conn_airbyte_1",
        "source": {
            "connectionConfiguration": {
                "host": "water-api.example.com",
                "port": 5432,
                "database": "water_db",
            }
        },
        "destination": {
            "destinationType": "snowflake",
            "connectionConfiguration": {},
        },
        "namespace": "raw_water",
        "discovered_catalog": [
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
        "id": "conn_airbyte_2",
        "source": {
            "connectionConfiguration": {
                "host": "other-api.example.com",
            }
        },
        "destination": {
            "destinationType": "bigquery",
            "connectionConfiguration": {},
        },
        "namespace": "other",
        "discovered_catalog": [],
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_find_matching_connectors_returns_match():
    """Matching host returns exactly one ConnectorMatch."""
    discoverer = AirbyteIngestionDiscoverer(org_id=None, stack_id=None)

    with patch.object(discoverer, "_list_connectors", return_value=_FAKE_CONNECTORS):
        matches = discoverer.find_matching_connectors("water-api.example.com")

    assert len(matches) == 1
    m = matches[0]
    assert isinstance(m, ConnectorMatch)
    assert m.driver_id == "airbyte"
    assert m.connector_id == "conn_airbyte_1"
    assert m.source_host == "water-api.example.com"
    assert m.raw_config is _FAKE_CONNECTORS[0]


def test_find_matching_connectors_case_insensitive():
    """Host matching is case-insensitive."""
    discoverer = AirbyteIngestionDiscoverer(org_id=None, stack_id=None)

    with patch.object(discoverer, "_list_connectors", return_value=_FAKE_CONNECTORS):
        matches = discoverer.find_matching_connectors("WATER-API.EXAMPLE.COM")

    assert len(matches) == 1
    assert matches[0].connector_id == "conn_airbyte_1"


def test_find_matching_connectors_no_match():
    """No matching host → empty list."""
    discoverer = AirbyteIngestionDiscoverer(org_id=None, stack_id=None)

    with patch.object(discoverer, "_list_connectors", return_value=_FAKE_CONNECTORS):
        matches = discoverer.find_matching_connectors("no-match.example.com")

    assert matches == []


def test_list_source_tables_returns_candidate():
    """list_source_tables returns one DatasetCandidate per table in discovered_catalog."""
    discoverer = AirbyteIngestionDiscoverer(org_id=None, stack_id=None)
    match = ConnectorMatch(
        driver_id="airbyte",
        connector_id="conn_airbyte_1",
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
    discoverer = AirbyteIngestionDiscoverer(org_id=None, stack_id=None)
    raw_config = {
        "id": "conn_no_ts",
        "source": {"connectionConfiguration": {"host": "api.example.com"}},
        "destination": {"destinationType": "bigquery", "connectionConfiguration": {}},
        "namespace": "raw",
        "discovered_catalog": [
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
        driver_id="airbyte",
        connector_id="conn_no_ts",
        source_host="api.example.com",
        raw_config=raw_config,
    )

    candidates = discoverer.list_source_tables(match)

    assert len(candidates) == 1
    assert candidates[0].timestamp_column is None
    assert candidates[0].lands_in == "bigquery.raw.readings"


# ---------------------------------------------------------------------------
# _airbyte_type_to_str unit tests
# ---------------------------------------------------------------------------


def test_airbyte_type_to_str_big_integer():
    """big_integer airbyte_type maps to BIGINT."""
    assert _airbyte_type_to_str({"airbyte_type": "big_integer"}) == "BIGINT"


def test_airbyte_type_to_str_big_number():
    """big_number airbyte_type maps to NUMERIC."""
    assert _airbyte_type_to_str({"airbyte_type": "big_number"}) == "NUMERIC"


def test_airbyte_type_to_str_timestamp_with_timezone():
    assert _airbyte_type_to_str({"airbyte_type": "timestamp_with_timezone"}) == "TIMESTAMPTZ"


def test_airbyte_type_to_str_timestamp_without_timezone():
    assert _airbyte_type_to_str({"airbyte_type": "timestamp_without_timezone"}) == "TIMESTAMP"


def test_airbyte_type_to_str_json_integer():
    assert _airbyte_type_to_str({"type": "integer"}) == "INTEGER"


def test_airbyte_type_to_str_json_string():
    assert _airbyte_type_to_str({"type": "string"}) == "VARCHAR"


def test_airbyte_type_to_str_unknown_falls_through():
    assert _airbyte_type_to_str({"type": "unknown_type"}) == "UNKNOWN"
