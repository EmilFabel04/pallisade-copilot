"""
Tests for IngestionDiscoverer orchestrator (Path 2).

Covers:
1. Candidates from all matching per-driver mocks are merged.
2. If hints=['fivetran'], only the Fivetran driver runs.
3. Driver exceptions are isolated — one driver raising doesn't stop others.
4. Returns no_connectors_connected error when no driver finds matches.
5. Returns unknown error when base_url has no parseable host.
6. Returns unknown error (not no_connectors_connected) when ALL drivers crash.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scanner.discovery.ingestion.orchestrator import IngestionDiscoverer
from scanner.discovery.ingestion.base import ConnectorMatch
from scanner.discovery.types import DatasetCandidate, DiscoveryError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_driver(driver_id: str, host_to_match: str, candidates: list) -> MagicMock:
    """Build a mock PerDriverIngestionDiscoverer."""
    driver = MagicMock()
    driver.driver_id.return_value = driver_id
    match = ConnectorMatch(
        driver_id=driver_id,
        connector_id=f"{driver_id}_conn_1",
        source_host=host_to_match,
        raw_config={},
    )
    driver.find_matching_connectors.return_value = [match]
    driver.list_source_tables.return_value = candidates
    return driver


def _make_candidate(source_name: str) -> DatasetCandidate:
    return DatasetCandidate(
        source='ingestion',
        endpoint=None,
        json_root=None,
        timestamp_column=None,
        expected_schema=[],
        lands_in=f"snowflake.raw.{source_name}",
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_candidates_from_all_drivers_merged():
    """All matching drivers contribute; candidates are merged into one list."""
    fivetran_candidate = _make_candidate("water_meters_fv")
    airbyte_candidate = _make_candidate("water_meters_ab")

    fivetran_driver = _make_driver("fivetran", "water-api.example.com", [fivetran_candidate])
    airbyte_driver = _make_driver("airbyte", "water-api.example.com", [airbyte_candidate])
    stitch_driver = MagicMock()
    stitch_driver.driver_id.return_value = "stitch"
    stitch_driver.find_matching_connectors.return_value = []  # no match for this driver

    discoverer = IngestionDiscoverer(drivers=[fivetran_driver, airbyte_driver, stitch_driver])
    candidates, error = discoverer.discover("https://water-api.example.com/v1", hints=[])

    assert error is None
    assert len(candidates) == 2
    lands = {c.lands_in for c in candidates}
    assert "snowflake.raw.water_meters_fv" in lands
    assert "snowflake.raw.water_meters_ab" in lands

    fivetran_driver.find_matching_connectors.assert_called_once_with(host="water-api.example.com")
    airbyte_driver.find_matching_connectors.assert_called_once_with(host="water-api.example.com")
    stitch_driver.find_matching_connectors.assert_called_once_with(host="water-api.example.com")


def test_hints_filter_to_single_driver():
    """With hints=['fivetran'], only Fivetran driver runs."""
    fivetran_candidate = _make_candidate("water_meters_fv")

    fivetran_driver = _make_driver("fivetran", "water-api.example.com", [fivetran_candidate])
    airbyte_driver = _make_driver("airbyte", "water-api.example.com", [_make_candidate("x")])
    stitch_driver = _make_driver("stitch", "water-api.example.com", [_make_candidate("y")])

    discoverer = IngestionDiscoverer(drivers=[fivetran_driver, airbyte_driver, stitch_driver])
    candidates, error = discoverer.discover("https://water-api.example.com/v1", hints=["fivetran"])

    assert error is None
    assert len(candidates) == 1
    assert candidates[0].lands_in == "snowflake.raw.water_meters_fv"

    fivetran_driver.find_matching_connectors.assert_called_once()
    airbyte_driver.find_matching_connectors.assert_not_called()
    stitch_driver.find_matching_connectors.assert_not_called()


def test_driver_exception_isolated():
    """One driver raising does not prevent other drivers from returning results."""
    good_candidate = _make_candidate("water_meters")

    bad_driver = MagicMock()
    bad_driver.driver_id.return_value = "fivetran"
    bad_driver.find_matching_connectors.side_effect = RuntimeError("API timeout")

    good_driver = _make_driver("airbyte", "water-api.example.com", [good_candidate])

    discoverer = IngestionDiscoverer(drivers=[bad_driver, good_driver])
    candidates, error = discoverer.discover("https://water-api.example.com/v1", hints=[])

    # bad_driver raised, but good_driver contributed
    assert error is None
    assert len(candidates) == 1
    assert candidates[0].lands_in == "snowflake.raw.water_meters"


def test_table_listing_exception_isolated():
    """list_source_tables raising for one match doesn't prevent other matches."""
    good_candidate = _make_candidate("water_meters")

    match_bad = ConnectorMatch(
        driver_id="fivetran",
        connector_id="conn_bad",
        source_host="water-api.example.com",
        raw_config={},
    )
    match_good = ConnectorMatch(
        driver_id="fivetran",
        connector_id="conn_good",
        source_host="water-api.example.com",
        raw_config={},
    )

    driver = MagicMock()
    driver.driver_id.return_value = "fivetran"
    driver.find_matching_connectors.return_value = [match_bad, match_good]

    def _list_tables(m: ConnectorMatch):
        if m.connector_id == "conn_bad":
            raise RuntimeError("schema fetch failed")
        return [good_candidate]

    driver.list_source_tables.side_effect = _list_tables

    discoverer = IngestionDiscoverer(drivers=[driver])
    candidates, error = discoverer.discover("https://water-api.example.com/v1", hints=[])

    assert error is None
    assert len(candidates) == 1
    assert candidates[0].lands_in == "snowflake.raw.water_meters"


def test_no_connectors_found_returns_error():
    """All drivers return no matches → no_connectors_connected error."""
    driver_a = MagicMock()
    driver_a.driver_id.return_value = "fivetran"
    driver_a.find_matching_connectors.return_value = []

    driver_b = MagicMock()
    driver_b.driver_id.return_value = "airbyte"
    driver_b.find_matching_connectors.return_value = []

    discoverer = IngestionDiscoverer(drivers=[driver_a, driver_b])
    candidates, error = discoverer.discover("https://no-match.example.com/v1", hints=[])

    assert candidates == []
    assert isinstance(error, DiscoveryError)
    assert error.code == "no_connectors_connected"
    assert "no-match.example.com" in error.message


def test_unparseable_host_returns_unknown_error():
    """If base_url yields no hostname, returns ([], DiscoveryError(code='unknown', ...))."""
    discoverer = IngestionDiscoverer(drivers=[])
    candidates, error = discoverer.discover("not-a-url", hints=[])

    assert candidates == []
    assert isinstance(error, DiscoveryError)
    assert error.code == "unknown"


def test_all_drivers_crash_returns_unknown_error():
    """All three drivers raise on find_matching_connectors → code='unknown', not 'no_connectors_connected'."""
    driver_a = MagicMock()
    driver_a.driver_id.return_value = "fivetran"
    driver_a.find_matching_connectors.side_effect = RuntimeError("fivetran API down")

    driver_b = MagicMock()
    driver_b.driver_id.return_value = "airbyte"
    driver_b.find_matching_connectors.side_effect = RuntimeError("airbyte API down")

    driver_c = MagicMock()
    driver_c.driver_id.return_value = "stitch"
    driver_c.find_matching_connectors.side_effect = RuntimeError("stitch API down")

    discoverer = IngestionDiscoverer(drivers=[driver_a, driver_b, driver_c])
    candidates, error = discoverer.discover("https://water-api.example.com/v1", hints=[])

    assert candidates == []
    assert isinstance(error, DiscoveryError)
    assert error.code == "unknown"
    assert "all ingestion drivers failed" in error.message
