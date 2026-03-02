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
        """Discover Airbyte sources, connections, and destination tables."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "airbyte")
        integration_id = config.get("integration_id")
        workspace_id = config.get("workspace_id") or getattr(client, "workspace_id", None)
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover sources
        sources_raw = self._safe_call(client.get_sources, workspace_id)
        source_lookup: Dict[str, Dict] = {}
        for src in sources_raw:
            source_id = src.get("sourceId") or src.get("id", "")
            name = src.get("name", "unknown")
            source_type = src.get("sourceType") or src.get("sourceName", "unknown")
            source_lookup[source_id] = src

            node = self._make_source_node(
                source_id, name, source_type, namespace, integration_id, now,
            )
            nodes.append(node)

        # Discover destinations (for metadata, not separate nodes unless needed)
        dest_lookup: Dict[str, Dict] = {}
        destinations_raw = self._safe_call(client.get_destinations, workspace_id)
        for dest in destinations_raw:
            dest_id = dest.get("destinationId") or dest.get("id", "")
            dest_lookup[dest_id] = dest

        # Discover connections
        connections_raw = self._safe_call(client.get_connections, workspace_id)
        for conn in connections_raw:
            conn_id = conn.get("connectionId") or conn.get("id", "")
            conn_name = conn.get("name", "unknown")
            source_id = conn.get("sourceId", "")
            dest_id = conn.get("destinationId", "")
            schedule_type = conn.get("scheduleType", "manual")
            status = conn.get("status", "active")

            # Count streams
            streams = conn.get("syncCatalog", {}).get("streams", [])
            stream_count = len(streams)

            # Connection node — only connector/pipeline nodes,
            # NOT destination table nodes. Warehouse tables come from the
            # warehouse adapter; cross-tool synthesis creates connector → table edges.
            conn_node = self._make_connection_node(
                conn_id, conn_name, source_id, dest_id,
                schedule_type, status, stream_count,
                namespace, integration_id, now,
            )

            # Store synced stream names on the connection for cross-tool matching
            stream_names = []
            for stream_entry in streams:
                stream_def = stream_entry.get("stream", {})
                sn = stream_def.get("name", "")
                if sn:
                    stream_names.append(sn)
            conn_node.raw_metadata["synced_streams"] = stream_names
            conn_node.raw_metadata["schema"] = conn_name

            nodes.append(conn_node)

        logger.info(
            f"[LiveAirbyte] Discovered {len(nodes)} assets "
            f"({len(sources_raw)} sources, {len(connections_raw)} connections)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract source -> connection -> table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "airbyte")
        dest_platform = config.get("destination_platform", "").lower()
        dest_namespace_cfg = config.get("destination_namespace", "")
        dest_database = config.get("destination_database", "")
        workspace_id = config.get("workspace_id") or getattr(client, "workspace_id", None)
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Use warehouse identity for destination table IDs (must match discover_assets)
        table_system = dest_platform or "airbyte"
        table_namespace = dest_namespace_cfg or namespace

        connections_raw = self._safe_call(client.get_connections, workspace_id)

        for conn in connections_raw:
            conn_name = conn.get("name", "unknown")
            source_id = conn.get("sourceId", "")
            dest_namespace_def = conn.get("namespaceDefinition", "source")
            dest_namespace_fmt = conn.get("namespaceFormat", "")
            dest_prefix = conn.get("prefix", "")

            conn_asset_id = generate_asset_id(
                "ingestion", "airbyte", namespace, "", conn_name,
            )

            # Source -> Connection (DATA plane, DERIVED_FROM)
            if source_id:
                source_asset_id = generate_asset_id(
                    "ingestion", "airbyte", namespace, "", f"source_{source_id}",
                )
                source_ref = f"airbyte:{conn_name}:source:{source_id}"
                edge = self._make_edge(
                    source_asset_id, conn_asset_id,
                    EdgeType.DERIVED_FROM, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.DATA,
                )
                edges.append(edge)

            # Connection -> destination table (CROSS plane, POPULATES)
            streams = conn.get("syncCatalog", {}).get("streams", [])
            for stream_entry in streams:
                stream_def = stream_entry.get("stream", {})
                stream_name = stream_def.get("name", "")
                stream_namespace = stream_def.get("namespace", "")

                if not stream_name:
                    continue

                if dest_namespace_def == "destination":
                    dest_schema = dest_namespace_fmt or "public"
                elif dest_namespace_def == "source" and stream_namespace:
                    dest_schema = stream_namespace
                else:
                    dest_schema = "public"

                table_name = f"{dest_prefix}{stream_name}" if dest_prefix else stream_name

                norm_schema = normalize_identifier(dest_schema, hint)
                norm_table = normalize_identifier(table_name, hint)

                # Build container matching discover_assets
                if dest_platform == "bigquery" and dest_namespace_cfg:
                    database = dest_namespace_cfg
                elif dest_database:
                    database = dest_database
                else:
                    database = ""
                container = f"{database}.{norm_schema}" if database else f".{norm_schema}"

                table_asset_id = generate_asset_id(
                    "warehouse", table_system, table_namespace, container, norm_table,
                )

                source_ref = f"airbyte:{conn_name}:stream:{norm_schema}.{norm_table}"
                edge = self._make_edge(
                    conn_asset_id, table_asset_id,
                    EdgeType.POPULATES, LineageLevel.TABLE,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CROSS,
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
