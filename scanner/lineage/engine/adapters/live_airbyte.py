"""
Live Airbyte Adapter — extracts lineage from Airbyte connections.

Maps Airbyte connections, sources, and destinations into the lineage graph.
Each connection becomes a PIPELINE node on the INGESTION domain, sources
become SOURCE nodes, and synced streams become TABLE nodes on the WAREHOUSE
domain (matching existing warehouse nodes for dedup by the resolver).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, normalize_identifier

logger = logging.getLogger(__name__)


class LiveAirbyteAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Airbyte connections and extracts lineage
    from sources through connections to destination tables.

    Config keys:
        namespace: Identifier for this Airbyte workspace (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        airbyte_config: Dict with host, api_key, workspace_id, etc.
    """

    def __init__(self, adapter_id: str = "live_airbyte", **kwargs):
        super().__init__(adapter_id, **kwargs)

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_RUNS_LOGS,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Airbyte sources, connections, and per-stream table nodes."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "airbyte")
        integration_id = config.get("integration_id")
        workspace_id = config.get("workspace_id") or getattr(client, "workspace_id", None)
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover sources (for lookup metadata, not creating nodes per-source)
        sources_raw = self._safe_call(client.get_sources, workspace_id)
        source_lookup: Dict[str, Dict] = {}
        for src in sources_raw:
            source_id = src.get("sourceId") or src.get("id", "")
            source_lookup[source_id] = src

        # Discover destinations (for metadata)
        dest_lookup: Dict[str, Dict] = {}
        destinations_raw = self._safe_call(client.get_destinations, workspace_id)
        for dest in destinations_raw:
            dest_id = dest.get("destinationId") or dest.get("id", "")
            dest_lookup[dest_id] = dest

        # Discover connections and create per-stream ingestion TABLE nodes
        connections_raw = self._safe_call(client.get_connections, workspace_id)
        stream_node_count = 0
        for conn in connections_raw:
            conn_id = conn.get("connectionId") or conn.get("id", "")
            conn_name = conn.get("name", "unknown")
            source_id = conn.get("sourceId", "")
            dest_id = conn.get("destinationId", "")
            schedule_type = conn.get("scheduleType", "manual")
            status = conn.get("status", "active")

            # Resolve source info for labeling
            src_info = source_lookup.get(source_id, {})
            src_name = src_info.get("name", "unknown")
            src_type = (
                src_info.get("sourceType")
                or src_info.get("sourceName", "unknown")
            ).lower()

            # Parse streams — handle both Cloud API and OSS API formats
            cloud_streams = conn.get("configurations", {}).get("streams", [])
            oss_streams = conn.get("syncCatalog", {}).get("streams", [])

            # Normalize to [(stream_name, sync_mode)] pairs
            stream_infos: List[tuple] = []
            if cloud_streams:
                for entry in cloud_streams:
                    sn = entry.get("name", "")
                    sm = entry.get("syncMode", "")
                    if sn:
                        stream_infos.append((sn.lower(), sm))
            else:
                for entry in oss_streams:
                    sd = entry.get("stream", {})
                    sn = sd.get("name", "")
                    sm = entry.get("config", {}).get("syncMode", "")
                    if sn:
                        stream_infos.append((sn.lower(), sm))

            # Connection (PIPELINE) node — the connector itself
            conn_node = self._make_connection_node(
                conn_id, conn_name, source_id, dest_id,
                schedule_type, status, len(stream_infos),
                namespace, integration_id, now,
            )
            stream_names = [s[0] for s in stream_infos]
            conn_node.raw_metadata["synced_tables"] = stream_names
            conn_node.raw_metadata["synced_streams"] = stream_names

            # Destination info
            dest_namespace_def = conn.get("namespaceDefinition", "source")
            dest_namespace_fmt = conn.get("namespaceFormat", "")
            dest_info_obj = dest_lookup.get(dest_id, {})
            dest_type = (
                dest_info_obj.get("destinationType")
                or dest_info_obj.get("destinationName", "")
            ).lower()
            conn_node.raw_metadata["destination_type"] = dest_type
            if dest_namespace_def == "destination" and dest_namespace_fmt:
                conn_node.raw_metadata["dest_schema"] = dest_namespace_fmt
            elif dest_namespace_def == "customformat" and dest_namespace_fmt:
                conn_node.raw_metadata["dest_schema"] = dest_namespace_fmt
            nodes.append(conn_node)

            # Per-stream TABLE nodes — these are the individual ingestion tables
            # that appear in the data lineage view as upstream of warehouse tables.
            for stream_name, sync_mode in stream_infos:
                stream_asset_id = generate_asset_id(
                    "ingestion", "airbyte", namespace,
                    conn_name, stream_name,
                )
                stream_node = LineageNode(
                    id=stream_asset_id,
                    name=stream_name,
                    fqn=f"airbyte.{namespace}.{conn_name}.{stream_name}",
                    node_type=NodeType.TABLE,
                    platform="airbyte",
                    platform_domain=PlatformDomain.INGESTION,
                    asset_kind=AssetKind.TABLE,
                    namespace=namespace,
                    observed_at=now,
                    sources=[self._id],
                    integration_id=integration_id,
                    raw_metadata={
                        "connection_id": conn_id,
                        "connection_name": conn_name,
                        "source_id": source_id,
                        "source_name": src_name,
                        "source_type": src_type,
                        "sync_mode": sync_mode,
                        "node_role": "synced_table",
                        "discovered_via": "airbyte_connection",
                        "ingestion_connector": conn_name,
                    },
                )
                nodes.append(stream_node)
                stream_node_count += 1

            logger.info(
                "[LiveAirbyte] Connection '%s': %d streams: %s",
                conn_name, len(stream_infos), stream_names[:10],
            )

        logger.info(
            "[LiveAirbyte] Discovered %d assets (%d connections, %d stream tables)",
            len(nodes), len(connections_raw), stream_node_count,
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract stream_table -> warehouse_table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "airbyte")
        workspace_id = config.get("workspace_id") or getattr(client, "workspace_id", None)
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        connections_raw = self._safe_call(client.get_connections, workspace_id)

        for conn in connections_raw:
            conn_name = conn.get("name", "unknown")

            # Parse streams — handle both Cloud API and OSS API formats
            cloud_streams = conn.get("configurations", {}).get("streams", [])
            oss_streams = conn.get("syncCatalog", {}).get("streams", [])

            stream_pairs: List[tuple] = []
            if cloud_streams:
                for entry in cloud_streams:
                    stream_pairs.append((entry.get("name", ""), ""))
            else:
                for entry in oss_streams:
                    sd = entry.get("stream", {})
                    stream_pairs.append((sd.get("name", ""), sd.get("namespace", "")))

            # For each stream, create an edge from the per-stream ingestion
            # node to the connection node (stream_table → connection).
            # Cross-tool synthesis will handle connection → warehouse_table
            # matching via synced_tables metadata.
            conn_asset_id = generate_asset_id(
                "ingestion", "airbyte", namespace, "", conn_name,
            )

            for stream_name, _stream_namespace in stream_pairs:
                if not stream_name:
                    continue
                norm_name = stream_name.lower()

                # Stream table → Connection (DATA plane)
                stream_asset_id = generate_asset_id(
                    "ingestion", "airbyte", namespace,
                    conn_name, norm_name,
                )
                source_ref = f"airbyte:{conn_name}:stream:{norm_name}"
                edge = self._make_edge(
                    stream_asset_id, conn_asset_id,
                    EdgeType.DERIVED_FROM, LineageLevel.TABLE,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.DATA,
                )
                edges.append(edge)

        logger.info(f"[LiveAirbyte] Extracted {len(edges)} edges")
        return edges

    def fetch_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch recent job information for context."""
        client = self._get_client(config)
        if not client:
            return {}

        try:
            jobs = client.get_jobs(limit=10)
            return {
                "recent_jobs": [
                    {
                        "job_id": j.get("jobId") or j.get("id", ""),
                        "status": j.get("status", "unknown"),
                        "connection_id": j.get("connectionId", ""),
                    }
                    for j in jobs
                ],
            }
        except Exception as e:
            logger.warning(f"[LiveAirbyte] Failed to fetch context: {e}")
            return {}

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create an AirbyteClient."""
        if config.get("client"):
            return config["client"]

        airbyte_config = config.get("airbyte_config", {})
        if not airbyte_config.get("host"):
            logger.warning("[LiveAirbyte] No airbyte_config with host provided")
            return None

        try:
            from scanner.integrations.airbyte import AirbyteClient
        except ImportError:
            from integrations.airbyte import AirbyteClient

        return AirbyteClient(
            host=airbyte_config.get("host", ""),
            client_id=airbyte_config.get("client_id"),
            client_secret=airbyte_config.get("client_secret"),
            api_key=airbyte_config.get("api_key"),
            username=airbyte_config.get("username"),
            password=airbyte_config.get("password"),
            workspace_id=airbyte_config.get("workspace_id"),
        )

    def _safe_call(self, method, *args) -> List:
        """Call an API method safely, returning empty list on failure."""
        try:
            result = method(*args) if args else method()
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning(f"[LiveAirbyte] API call failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_source_node(
        self, source_id: str, name: str, source_type: str,
        namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for an Airbyte source."""
        asset_id = generate_asset_id(
            "ingestion", "airbyte", namespace, "", f"source_{source_id}",
        )
        return LineageNode(
            id=asset_id,
            name=name,
            fqn=f"airbyte.{namespace}.source.{name}",
            node_type=NodeType.SOURCE,
            platform="airbyte",
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.UNKNOWN,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "source_id": source_id,
                "source_type": source_type,
            },
        )

    def _make_connection_node(
        self, conn_id: str, name: str, source_id: str, dest_id: str,
        schedule_type: str, status: str, stream_count: int,
        namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for an Airbyte connection."""
        asset_id = generate_asset_id(
            "ingestion", "airbyte", namespace, "", name,
        )
        return LineageNode(
            id=asset_id,
            name=name,
            fqn=f"airbyte.{namespace}.{name}",
            node_type=NodeType.PIPELINE,
            platform="airbyte",
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.STREAM,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "connection_id": conn_id,
                "source_id": source_id,
                "destination_id": dest_id,
                "schedule_type": schedule_type,
                "status": status,
                "stream_count": stream_count,
            },
        )

        edge_id = generate_edge_id(
            source_id, target_id,
            edge_type.value, level.value,
            source_ref,
        )
        return LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=level,
            confidence=confidence,
            discovered_from=source_ref,
            discovered_at=now,
            evidence=[ev],
            plane=plane,
        )
