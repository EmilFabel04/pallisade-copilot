from __future__ import annotations
import logging
from typing import List, Optional

from scanner.discovery.ingestion.base import (
    ConnectorMatch,
    PerDriverIngestionDiscoverer,
)
from scanner.discovery.types import (
    ColumnMetadata,
    DatasetCandidate,
)

logger = logging.getLogger(__name__)


class StitchIngestionDiscoverer(PerDriverIngestionDiscoverer):
    """Path 2 adapter for Stitch.

    Constructs a StitchIntegration per-call using credentials from the cached
    tool configs (key 'STITCH') for the calling tenant. Returns [] if not
    configured.

    Column data types are always "UNKNOWN" — Stitch's API does not expose
    source-side column types; use WarehouseDiscoverer (Path 3) to resolve
    actual types from the destination warehouse.

    Internal connector dict shape (produced by _list_connectors):
    {
        "id": "<source_id>",
        "properties": {
            "host": {"value": "<source_host>"},
            ...
        },
        "target_id": "<destination_id>",
        "destination": {"type": "<snowflake|bigquery|...>"},
        "target_schema": "<destination schema>",
        "streams": [
            {"name": "<table>", "columns": [{"name": "...", "type": "UNKNOWN", "nullable": bool}]}
        ],
    }
    """

    def __init__(self, org_id: Optional[str] = None, stack_id: Optional[str] = None) -> None:
        self._org_id = org_id
        self._stack_id = stack_id

    def driver_id(self) -> str:
        return "stitch"

    def find_matching_connectors(self, host: str) -> List[ConnectorMatch]:
        matches: List[ConnectorMatch] = []
        for c in self._list_connectors():
            # Stitch nests host under properties.host.value
            host_entry = (c.get("properties") or {}).get("host")
            if isinstance(host_entry, dict):
                src_host = host_entry.get("value", "")
            else:
                src_host = host_entry or ""
            if src_host and host and src_host.lower() == host.lower():
                matches.append(ConnectorMatch(
                    driver_id=self.driver_id(),
                    connector_id=c["id"],
                    source_host=src_host,
                    raw_config=c,
                ))
        return matches

    def list_source_tables(self, match: ConnectorMatch) -> List[DatasetCandidate]:
        cfg = match.raw_config
        dest = cfg.get("destination") or {}
        wh_type = (dest.get("type") or "snowflake").lower()
        target_schema = cfg.get("target_schema") or ""
        candidates: List[DatasetCandidate] = []

        for stream in cfg.get("streams", []):
            cols = [
                ColumnMetadata(
                    name=col["name"],
                    data_type=col.get("type", "UNKNOWN"),
                    is_nullable=bool(col.get("nullable", True)),
                )
                for col in stream.get("columns", [])
            ]
            # timestamp_column is None — Stitch's API doesn't expose source-side
            # column types. Use WarehouseDiscoverer (Path 3) for timestamp detection.
            lands_in = f"{wh_type}.{target_schema}.{stream['name']}".strip(".")
            candidates.append(DatasetCandidate(
                source='ingestion',
                endpoint=None,
                json_root=None,
                timestamp_column=None,
                expected_schema=cols,
                lands_in=lands_in,
                confidence=1.0,
            ))
        return candidates

    def _list_connectors(self) -> list:
        """Fetch source configs with stream metadata from StitchIntegration.

        Looks up Stitch credentials from the lineage cache (key 'STITCH')
        for (org_id, stack_id). Returns [] if not configured.
        """
        try:
            from scanner.api.routers._lineage_cache import get_tool_configs
            from scanner.integrations.stitch import StitchIntegration

            tool_configs = get_tool_configs(self._org_id or "", self._stack_id)
            stitch_cfg = tool_configs.get("STITCH") or tool_configs.get("stitch")
            if not stitch_cfg:
                logger.debug("[StitchIngestionDiscoverer] no STITCH config cached; skipping")
                return []

            with StitchIntegration(stitch_cfg) as integration:
                return integration.list_sources_with_metadata()
        except Exception as exc:
            logger.warning("[StitchIngestionDiscoverer] _list_connectors failed: %s", exc)
            return []
