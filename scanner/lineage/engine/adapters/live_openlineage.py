"""
Live OpenLineage Adapter — pull-mode adapter for OpenLineage-compatible backends.

Fetches OpenLineage events from a backend (Marquez, custom HTTP store, or
Airflow's OpenLineage backend) and maps them to our graph format using
the OpenLineageMapper.

For push-mode (tools posting events to us), see the /openlineage/event
endpoint in the API router.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import httpx

from ...graph import (
    LineageEdge,
    LineageNode,
)
from ..adapter import BaseLineageAdapter, Capability
from ..openlineage import OpenLineageMapper

logger = logging.getLogger(__name__)


class LiveOpenLineageAdapter(BaseLineageAdapter):
    """
    Pull OpenLineage events from an OL-compatible backend (Marquez, HTTP store).

    Config keys:
        openlineage_url: Base URL of the OL backend (e.g., "http://marquez:5000")
        namespace_filter: Optional namespace to filter events (e.g., "airflow://prod")
        days_back: How many days of events to fetch (default: 7)
        namespace: Instance identifier for this adapter
        integration_id: Pallisade integration ID
    """

    def __init__(self, adapter_id: str = "live_openlineage", **kwargs):
        self._id = adapter_id
        self._mapper = OpenLineageMapper(adapter_id=adapter_id)

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.EXTRACT_COLUMN_LINEAGE,
            Capability.GET_RUNS_LOGS,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Fetch OL events and extract nodes."""
        events = self._fetch_events(config)
        nodes, _ = self._mapper.map_events(events)
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Fetch OL events and extract edges."""
        events = self._fetch_events(config)
        _, edges = self._mapper.map_events(events)
        return edges

    def fetch_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return summary of recent OL events."""
        events = self._fetch_events(config)
        return {
            "total_events": len(events),
            "event_types": self._count_by_key(events, "eventType"),
            "jobs": list(set(
                e.get("job", {}).get("name", "") for e in events if e.get("job")
            ))[:20],
        }

    # ------------------------------------------------------------------
    # Event fetching
    # ------------------------------------------------------------------

    def _fetch_events(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Fetch events from an OpenLineage-compatible backend.

        Supports:
        - Marquez API: GET /api/v1/events/lineage
        - Generic HTTP store: GET /events
        - Pre-loaded events in config (for testing)
        """
        # Allow pre-loaded events for testing
        if config.get("events"):
            return config["events"]

        base_url = config.get("openlineage_url", "")
        if not base_url:
            logger.warning("[LiveOpenLineage] No openlineage_url provided")
            return []

        namespace_filter = config.get("namespace_filter")
        days_back = config.get("days_back", 7)

        events: List[Dict[str, Any]] = []

        try:
            with httpx.Client(timeout=30) as client:
                # Try Marquez API first
                events = self._fetch_marquez_events(
                    client, base_url, namespace_filter, days_back
                )
                if not events:
                    # Fallback to generic events endpoint
                    events = self._fetch_generic_events(
                        client, base_url, namespace_filter, days_back
                    )
        except Exception as e:
            logger.error(f"[LiveOpenLineage] Failed to fetch events: {e}")

        logger.info(f"[LiveOpenLineage] Fetched {len(events)} events from {base_url}")
        return events

    def _fetch_marquez_events(
        self,
        client: httpx.Client,
        base_url: str,
        namespace_filter: Optional[str],
        days_back: int,
    ) -> List[Dict[str, Any]]:
        """Fetch from Marquez API."""
        url = f"{base_url.rstrip('/')}/api/v1/events/lineage"
        params: Dict[str, Any] = {"limit": 500}

        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            events = data if isinstance(data, list) else data.get("events", [])
        except (httpx.HTTPStatusError, httpx.ConnectError):
            return []

        if namespace_filter:
            events = [
                e for e in events
                if e.get("job", {}).get("namespace", "").startswith(namespace_filter)
            ]

        return events

    def _fetch_generic_events(
        self,
        client: httpx.Client,
        base_url: str,
        namespace_filter: Optional[str],
        days_back: int,
    ) -> List[Dict[str, Any]]:
        """Fetch from a generic /events endpoint."""
        url = f"{base_url.rstrip('/')}/events"
        params: Dict[str, Any] = {"limit": 500, "days_back": days_back}

        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            events = data if isinstance(data, list) else data.get("events", [])
        except Exception:
            return []

        if namespace_filter:
            events = [
                e for e in events
                if e.get("job", {}).get("namespace", "").startswith(namespace_filter)
            ]

        return events

    @staticmethod
    def _count_by_key(events: List[Dict], key: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in events:
            val = e.get(key, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts
