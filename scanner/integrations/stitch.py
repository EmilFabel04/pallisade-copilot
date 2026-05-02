"""
Stitch Integration — minimal connector for discovery.

Wraps the Stitch Connect API v4 to list sources and their destinations.
Only the subset of the API needed for ingestion-anchored discovery is
implemented; full monitoring capabilities are out of scope for this module.

API reference: https://www.stitchdata.com/docs/developers/stitch-connect/api/
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class StitchClient:
    """Minimal Stitch Connect API v4 client."""

    BASE_URL = "https://api.stitchdata.com"
    API_VERSION = "v4"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=30,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def _url(self, path: str) -> str:
        return f"{self.BASE_URL}/{self.API_VERSION}/{path.lstrip('/')}"

    def _get(self, path: str) -> Any:
        resp = self._client.get(self._url(path))
        resp.raise_for_status()
        return resp.json()

    def test_connection(self) -> Tuple[bool, str]:
        try:
            data = self._get("/sources")
            return True, f"Stitch connected ({len(data)} sources)"
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return False, "Invalid Stitch API key"
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)

    def get_sources(self) -> List[Dict[str, Any]]:
        """Return all sources for the account."""
        try:
            return self._get("/sources") or []
        except Exception as exc:
            logger.error("[StitchClient] get_sources failed: %s", exc)
            return []

    def get_destinations(self) -> List[Dict[str, Any]]:
        """Return all destinations for the account."""
        try:
            return self._get("/destinations") or []
        except Exception as exc:
            logger.error("[StitchClient] get_destinations failed: %s", exc)
            return []

    def get_streams(self, source_id: str) -> List[Dict[str, Any]]:
        """Return streams (tables) for a source with their metadata."""
        try:
            return self._get(f"/sources/{source_id}/streams") or []
        except Exception as exc:
            logger.error("[StitchClient] get_streams(%s) failed: %s", source_id, exc)
            return []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "StitchClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


class StitchIntegration:
    """Higher-level Stitch integration used by discovery and monitoring."""

    def __init__(self, config: Dict[str, Any]) -> None:
        api_key = config.get("api_key") or config.get("apiKey", "")
        self._client = StitchClient(api_key=api_key)

    def list_sources_with_metadata(self) -> List[Dict[str, Any]]:
        """Return sources enriched with destination type and stream (table) info.

        Each element has the shape consumed by StitchIngestionDiscoverer:
        {
            "id": "<stitch_source_id>",
            "properties": {"host": {"value": "<source_host>"}, ...},
            "target_id": "<destination_id>",
            "destination": {"type": "<snowflake|bigquery|...>"},
            "target_schema": "<destination schema>",
            "streams": [
                {"name": "<table>", "columns": [{"name": "...", "type": "UNKNOWN", "nullable": True}]}
            ],
        }

        Note: Stitch streams expose metadata (selected, auto-added keys) but
        not column data types from the source — types are known only at the
        destination. We emit type="UNKNOWN" for each column so callers can
        fall back to WarehouseDiscoverer for actual types.
        """
        # Build destination lookup: destination_id → type
        dest_by_id: Dict[str, str] = {}
        for dest in self._client.get_destinations():
            did = str(dest.get("id", ""))
            dest_type = (dest.get("type") or "").lower()
            dest_by_id[did] = dest_type

        result: List[Dict[str, Any]] = []
        for src in self._client.get_sources():
            src_id = str(src.get("id", ""))
            target_id = str(src.get("target_id") or src.get("destination_id") or "")
            dest_type = dest_by_id.get(target_id, "snowflake")

            # Stitch sources nest config under "properties", each value is
            # {"value": "<actual_value>", "is_required": bool, ...}
            properties = src.get("properties") or src.get("config") or {}

            # Target schema: Stitch uses the source's schema_name or target_schema field.
            target_schema = (
                src.get("schema_name")
                or src.get("target_schema")
                or ""
            )

            # Streams
            raw_streams = self._client.get_streams(src_id)
            streams: list = []
            for stream in raw_streams:
                stream_name = stream.get("stream_name") or stream.get("tap_stream_id") or ""
                # Column metadata from stream metadata — Stitch exposes column
                # names via metadata but not source-side types.
                metadata = stream.get("metadata") or []
                columns: list = []
                for entry in metadata:
                    breadcrumb = entry.get("breadcrumb", [])
                    if len(breadcrumb) == 2 and breadcrumb[0] == "properties":
                        col_name = breadcrumb[1]
                        columns.append({"name": col_name, "type": "UNKNOWN", "nullable": True})
                if stream_name:
                    streams.append({"name": stream_name, "columns": columns})

            result.append({
                "id": src_id,
                "properties": properties,
                "target_id": target_id,
                "destination": {"type": dest_type},
                "target_schema": target_schema,
                "streams": streams,
            })

        return result
