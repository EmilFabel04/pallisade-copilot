"""
Tests for SourceDiscoveryOrchestrator.

Covers:
1. All three paths run; orchestrator merges results from each.
2. If probe.discover raises an exception, the orchestrator catches it,
   returns [] for 'probe', errors_by_path['probe'].code == 'unknown'.
   Other paths still return their results.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scanner.discovery.source_discovery import SourceDiscoveryOrchestrator
from scanner.discovery.types import DatasetCandidate, DiscoveryError


def _make_probe_candidate() -> DatasetCandidate:
    return DatasetCandidate(
        source='probe',
        endpoint='/sensors',
        json_root=None,
        timestamp_column='reading_at',
        expected_schema=[],
        lands_in=None,
        confidence=0.7,
    )


@pytest.mark.asyncio
async def test_all_paths_merged():
    """All three paths run; orchestrator returns merged candidates_by_path and errors_by_path."""
    probe_candidate = _make_probe_candidate()

    probe = MagicMock()
    probe.discover.return_value = ([probe_candidate], None)

    warehouse = MagicMock()
    warehouse.discover.return_value = ([], DiscoveryError(code='no_warehouse_hint', message='no hints'))

    ingestion = MagicMock()
    ingestion.discover.return_value = ([], DiscoveryError(code='no_connectors_connected', message='not implemented'))

    orchestrator = SourceDiscoveryOrchestrator(
        probe_discoverer=probe,
        warehouse_discoverer=warehouse,
        ingestion_discoverer=ingestion,
    )

    result = await orchestrator.discover(
        base_url="https://api.example.com",
        endpoint="/sensors",
        auth={"kind": "bearer", "secret": "tok"},
    )

    # All three paths present
    assert set(result.candidates_by_path.keys()) == {'probe', 'warehouse', 'ingestion'}
    assert set(result.errors_by_path.keys()) == {'probe', 'warehouse', 'ingestion'}

    # Probe returned a candidate
    assert len(result.candidates_by_path['probe']) == 1
    assert result.candidates_by_path['probe'][0].endpoint == '/sensors'
    assert result.errors_by_path['probe'] is None

    # Warehouse returned empty with error
    assert result.candidates_by_path['warehouse'] == []
    assert result.errors_by_path['warehouse'] is not None
    assert result.errors_by_path['warehouse'].code == 'no_warehouse_hint'

    # Ingestion returned empty with error
    assert result.candidates_by_path['ingestion'] == []
    assert result.errors_by_path['ingestion'] is not None
    assert result.errors_by_path['ingestion'].code == 'no_connectors_connected'


@pytest.mark.asyncio
async def test_probe_exception_caught_other_paths_succeed():
    """If probe.discover raises, orchestrator catches it; errors_by_path['probe'].code == 'unknown'.
    Other paths still return their results."""
    probe = MagicMock()
    probe.discover.side_effect = RuntimeError("connection refused")

    warehouse = MagicMock()
    warehouse.discover.return_value = ([], DiscoveryError(code='no_warehouse_hint', message='no hints'))

    ingestion = MagicMock()
    ingestion.discover.return_value = ([], DiscoveryError(code='no_connectors_connected', message='not implemented'))

    orchestrator = SourceDiscoveryOrchestrator(
        probe_discoverer=probe,
        warehouse_discoverer=warehouse,
        ingestion_discoverer=ingestion,
    )

    result = await orchestrator.discover(
        base_url="https://api.example.com",
        endpoint="/sensors",
        auth={"kind": "bearer", "secret": "tok"},
    )

    # Probe path caught exception → empty candidates, error code 'unknown'
    assert result.candidates_by_path['probe'] == []
    assert result.errors_by_path['probe'] is not None
    assert result.errors_by_path['probe'].code == 'unknown'

    # Other paths still returned results
    assert result.errors_by_path['warehouse'].code == 'no_warehouse_hint'
    assert result.errors_by_path['ingestion'].code == 'no_connectors_connected'
