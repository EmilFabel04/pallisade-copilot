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


class AirbyteIngestionDiscoverer(PerDriverIngestionDiscoverer):
    """Path 2 adapter for Airbyte.

    Constructs an AirbyteClient per-call using credentials from the cached
    tool configs (key 'AIRBYTE') for the calling tenant. Returns [] if not
    configured.

    Internal connector dict shape (produced by _list_connectors):
    {
        "id": "<connection_id>",
        "source": {
            "connectionConfiguration": {"host": "<source_host>", ...}
        },
        "destination": {
            "destinationType": "<snowflake|bigquery|...>",
            "connectionConfiguration": {...},
        },
        "namespace": "<destination namespace / schema>",
        "discovered_catalog": [
            {"name": "<stream_name>", "columns": [{"name": "...", "type": "...", "nullable": bool}]}
        ],
    }
    """

    def __init__(self, org_id: Optional[str] = None, stack_id: Optional[str] = None) -> None:
        self._org_id = org_id
        self._stack_id = stack_id

    def driver_id(self) -> str:
        return "airbyte"

    def find_matching_connectors(self, host: str) -> List[ConnectorMatch]:
        matches: List[ConnectorMatch] = []
        for c in self._list_connectors():
            src_host = (
                (c.get("source") or {})
                .get("connectionConfiguration", {})
                .get("host")
            )
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
        wh_type = (dest.get("destinationType") or "snowflake").lower()
        namespace = cfg.get("namespace") or ""
        candidates: List[DatasetCandidate] = []

        for stream in cfg.get("discovered_catalog", []):
            cols = [
                ColumnMetadata(
                    name=col["name"],
                    data_type=col.get("type", "UNKNOWN"),
                    is_nullable=bool(col.get("nullable", True)),
                )
                for col in stream.get("columns", [])
            ]
            ts = next(
                (col["name"] for col in stream.get("columns", []) if col.get("type", "").upper() in _TS_TYPES),
                None,
            )
            lands_in = f"{wh_type}.{namespace}.{stream['name']}".strip(".")
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
        """Fetch connections with source/destination config and stream catalog.

        Uses AirbyteClient from scanner.integrations.airbyte. For each connection,
        fetches the source (for host) and destination (for warehouse type), then
        fetches the discovered schema catalog for stream/column info.

        Returns [] if AIRBYTE is not in the cached tool configs or any error occurs.

        Note: Airbyte's discovered catalog streams include json_schema with
        property types. We flatten these to a uniform column list; types that
        don't map cleanly are emitted as "UNKNOWN".
        """
        try:
            from scanner.api.routers._lineage_cache import get_tool_configs
            from scanner.integrations.airbyte import AirbyteClient

            tool_configs = get_tool_configs(self._org_id or "", self._stack_id)
            airbyte_cfg = tool_configs.get("AIRBYTE") or tool_configs.get("airbyte")
            if not airbyte_cfg:
                logger.debug("[AirbyteIngestionDiscoverer] no AIRBYTE config cached; skipping")
                return []

            with AirbyteClient(
                host=airbyte_cfg.get("host") or airbyte_cfg.get("base_url") or airbyte_cfg.get("baseUrl", ""),
                client_id=airbyte_cfg.get("client_id"),
                client_secret=airbyte_cfg.get("client_secret"),
                api_key=airbyte_cfg.get("api_key"),
                username=airbyte_cfg.get("username"),
                password=airbyte_cfg.get("password"),
                workspace_id=airbyte_cfg.get("workspace_id"),
            ) as client:
                # Collect all connections across all workspaces.
                workspace_ids: List[str] = []
                if client.workspace_id:
                    workspace_ids = [client.workspace_id]
                else:
                    try:
                        workspaces = client.get_workspaces()
                        workspace_ids = [
                            ws.get("workspaceId") or ws.get("id", "")
                            for ws in workspaces
                            if ws.get("workspaceId") or ws.get("id")
                        ]
                    except Exception as exc:
                        logger.warning("[AirbyteIngestionDiscoverer] get_workspaces failed: %s", exc)

                # Build source and destination lookups.
                sources: dict = {}
                destinations: dict = {}
                for ws_id in workspace_ids:
                    try:
                        for s in client.get_sources(ws_id):
                            sid = s.get("sourceId") or s.get("id", "")
                            sources[sid] = s
                    except Exception:
                        pass
                    try:
                        for d in client.get_destinations(ws_id):
                            did = d.get("destinationId") or d.get("id", "")
                            destinations[did] = d
                    except Exception:
                        pass

                result: list = []
                for ws_id in workspace_ids:
                    try:
                        connections = client.get_connections(ws_id)
                    except Exception as exc:
                        logger.warning("[AirbyteIngestionDiscoverer] get_connections failed ws=%s: %s", ws_id, exc)
                        continue

                    for conn in connections:
                        conn_id = conn.get("connectionId") or conn.get("id", "")
                        source_id = conn.get("sourceId", "")
                        dest_id = conn.get("destinationId", "")
                        source = sources.get(source_id, {})
                        dest = destinations.get(dest_id, {})

                        # Namespace / destination schema
                        namespace = (
                            conn.get("namespaceFormat")
                            or conn.get("prefix")
                            or ""
                        ).strip("_").strip()

                        # Catalog streams → columns
                        discovered_catalog: list = []
                        try:
                            # Airbyte OSS: /connections/get returns syncCatalog.streams
                            # Airbyte Cloud: GET /connections/{id} returns streams in 'configurations'
                            conn_detail = client.get_connection(conn_id)
                            sync_catalog = (
                                conn_detail.get("syncCatalog")
                                or {"streams": conn_detail.get("configurations", {}).get("streams", [])}
                            )
                            for stream_entry in sync_catalog.get("streams", []):
                                stream = stream_entry.get("stream", stream_entry)
                                stream_name = stream.get("name", "")
                                json_schema = stream.get("jsonSchema", {})
                                properties = json_schema.get("properties", {})
                                columns = [
                                    {
                                        "name": prop_name,
                                        "type": _airbyte_type_to_str(prop_info),
                                        "nullable": True,
                                    }
                                    for prop_name, prop_info in properties.items()
                                ]
                                discovered_catalog.append({"name": stream_name, "columns": columns})
                        except Exception as exc:
                            logger.warning(
                                "[AirbyteIngestionDiscoverer] catalog fetch failed conn=%s: %s", conn_id, exc
                            )

                        dest_type = (
                            dest.get("destinationType")
                            or dest.get("destinationName")
                            or "snowflake"
                        )

                        result.append({
                            "id": conn_id,
                            "source": {
                                "connectionConfiguration": source.get("connectionConfiguration", {})
                            },
                            "destination": {
                                "destinationType": dest_type,
                                "connectionConfiguration": dest.get("connectionConfiguration", {}),
                            },
                            "namespace": namespace,
                            "discovered_catalog": discovered_catalog,
                        })

                return result
        except Exception as exc:
            logger.warning("[AirbyteIngestionDiscoverer] _list_connectors failed: %s", exc)
            return []


def _airbyte_type_to_str(prop_info: dict) -> str:
    """Convert an Airbyte JSON-schema property definition to a SQL type string."""
    airbyte_type = prop_info.get("airbyte_type", "")
    json_type = prop_info.get("type", "")

    if airbyte_type == "big_integer":
        return "BIGINT"
    if airbyte_type == "big_number":
        return "NUMERIC"
    if airbyte_type == "timestamp_with_timezone":
        return "TIMESTAMPTZ"
    if airbyte_type == "timestamp_without_timezone":
        return "TIMESTAMP"
    if airbyte_type in ("date", "time_with_timezone", "time_without_timezone"):
        return airbyte_type.upper()

    if isinstance(json_type, list):
        non_null = [t for t in json_type if t != "null"]
        json_type = non_null[0] if non_null else ""

    _MAP = {
        "string": "VARCHAR",
        "integer": "INTEGER",
        "number": "FLOAT",
        "boolean": "BOOLEAN",
        "object": "VARIANT",
        "array": "ARRAY",
    }
    return _MAP.get(json_type, "UNKNOWN")
