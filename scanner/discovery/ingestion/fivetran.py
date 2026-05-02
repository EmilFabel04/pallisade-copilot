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

_TS_TYPES = {"TIMESTAMP", "DATETIME", "TIMESTAMP_NTZ", "TIMESTAMPTZ"}


class FivetranIngestionDiscoverer(PerDriverIngestionDiscoverer):
    """Path 2 adapter for Fivetran.

    Constructs a FivetranIntegration per-call using credentials from the
    cached tool configs (keyed 'FIVETRAN') for the calling tenant. If no
    Fivetran config is cached, _list_connectors returns [] gracefully.
    """

    def __init__(self, org_id: Optional[str] = None, stack_id: Optional[str] = None) -> None:
        self._org_id = org_id
        self._stack_id = stack_id

    def driver_id(self) -> str:
        return "fivetran"

    def find_matching_connectors(self, host: str) -> List[ConnectorMatch]:
        matches: List[ConnectorMatch] = []
        for c in self._list_connectors():
            cfg_host = (c.get("config") or {}).get("host")
            if cfg_host and host and cfg_host.lower() == host.lower():
                matches.append(ConnectorMatch(
                    driver_id=self.driver_id(),
                    connector_id=c["id"],
                    source_host=cfg_host,
                    raw_config=c,
                ))
        return matches

    def list_source_tables(self, match: ConnectorMatch) -> List[DatasetCandidate]:
        cfg = match.raw_config
        wh_type = (cfg.get("destination_warehouse_type") or "snowflake").lower()
        dest_schema = cfg.get("destination_schema") or cfg.get("schema") or ""
        candidates: List[DatasetCandidate] = []

        for tbl in cfg.get("tables", []):
            cols = [
                ColumnMetadata(
                    name=col["name"],
                    data_type=col.get("type", "UNKNOWN"),
                    is_nullable=bool(col.get("nullable", True)),
                )
                for col in tbl.get("columns", [])
            ]
            ts = next(
                (col["name"] for col in tbl.get("columns", []) if col.get("type", "").upper() in _TS_TYPES),
                None,
            )
            lands_in = f"{wh_type}.{dest_schema}.{tbl['name']}".strip(".")
            candidates.append(DatasetCandidate(
                source='ingestion',
                endpoint=None,
                json_root=None,
                timestamp_column=ts,
                expected_schema=cols,
                lands_in=lands_in,
                confidence=1.0,
            ))
        return candidates

    def _list_connectors(self) -> list:
        """Fetch connector configs (with table schemas) from FivetranIntegration.

        Looks up Fivetran credentials from the lineage cache (key 'FIVETRAN')
        for (org_id, stack_id). Returns [] if not configured.

        The dict shape returned per element:
        {
            "id": "<connector_id>",
            "config": {"host": "<source_host>", ...},
            "tables": [{"name": "...", "columns": [{"name": "...", "type": "...", "nullable": bool}]}],
            "destination_schema": "...",
            "destination_warehouse_type": "...",
        }
        """
        try:
            from scanner.api.routers._lineage_cache import get_tool_configs
            from scanner.integrations.fivetran import FivetranIntegration

            tool_configs = get_tool_configs(self._org_id or "", self._stack_id)
            fivetran_cfg = tool_configs.get("FIVETRAN") or tool_configs.get("fivetran")
            if not fivetran_cfg:
                logger.debug("[FivetranIngestionDiscoverer] no FIVETRAN config cached; skipping")
                return []

            integration = FivetranIntegration(fivetran_cfg)
            return integration.list_connectors_with_schemas()
        except Exception as exc:
            logger.warning("[FivetranIngestionDiscoverer] _list_connectors failed: %s", exc)
            return []
