"""
Live Fivetran Adapter — extracts lineage from Fivetran connectors.

Maps Fivetran connectors to ingestion-plane nodes and creates edges
to the destination warehouse tables they populate. Each connector
becomes a SOURCE node on the INGESTION domain, and each synced table
becomes a TABLE node on the WAREHOUSE domain (matching existing
warehouse nodes for dedup by the resolver).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)


class LiveFivetranAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Fivetran connectors and extracts lineage
    to destination warehouse tables.

    Config keys:
        namespace: Identifier for this Fivetran account (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        fivetran_config: Dict with api_key, api_secret for FivetranIntegration
    """

    def __init__(self, adapter_id: str = "live_fivetran", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Fivetran connectors and their destination tables."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "fivetran")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        hint = self.case_hint
        nodes: List[LineageNode] = []

        try:
            connectors = client.get_connectors()
        except Exception as e:
            logger.error(f"[LiveFivetran] Failed to get connectors: {e}")
            return []

        for connector in connectors:
            # Connector node (INGESTION domain)
            connector_node = self._make_connector_node(
                connector, namespace, integration_id, hint, now,
            )
            nodes.append(connector_node)

            # Destination table nodes from connector schema
            table_nodes = self._discover_connector_tables(
                client, connector, namespace, integration_id, hint, now,
            )
            nodes.extend(table_nodes)

        logger.info(f"[LiveFivetran] Discovered {len(nodes)} assets from {len(connectors)} connectors")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract connector -> destination table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "fivetran")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        try:
            connectors = client.get_connectors()
        except Exception as e:
            logger.error(f"[LiveFivetran] Failed to get connectors: {e}")
            return []

        for connector in connectors:
            connector_id_attr = getattr(connector, "id", "")
            connector_name = getattr(connector, "name", "") or getattr(connector, "schema", "")
            service = getattr(connector, "service", "unknown")

            connector_asset_id = generate_asset_id(
                "ingestion", "fivetran", namespace, "", connector_name,
            )

            # Get schema/tables for this connector
            try:
                schemas = client.get_connector_schema(connector_id_attr)
            except Exception as e:
                logger.warning(f"[LiveFivetran] Failed to get schema for {connector_name}: {e}")
                continue

            for schema_name, schema_data in schemas.items():
                tables = schema_data.get("tables", [])
                for table in tables:
                    table_name = getattr(table, "name", "") if hasattr(table, "name") else table.get("name", "")
                    table_schema = getattr(table, "schema", schema_name) if hasattr(table, "schema") else schema_name
                    enabled = getattr(table, "enabled", True) if hasattr(table, "enabled") else table.get("enabled", True)

                    if not enabled or not table_name:
                        continue

                    # Normalize identifiers
                    norm_schema = normalize_identifier(table_schema, hint)
                    norm_table = normalize_identifier(table_name, hint)
                    container = f".{norm_schema}"

                    table_asset_id = generate_asset_id(
                        "warehouse", "fivetran", namespace, container, norm_table,
                    )

                    # Connector -> table (POPULATES, cross-plane)
                    source_ref = f"fivetran:{connector_name}:{norm_schema}.{norm_table}"
                    edge = self._make_edge(
                        connector_asset_id, table_asset_id,
                        EdgeType.POPULATES, LineageLevel.TABLE,
                        confidence=1.0,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                    edges.append(edge)

            # Source service -> connector edge (DATA plane, DERIVED_FROM)
            # Represents the external source feeding the connector
            if service and service != "unknown":
                source_service_id = generate_asset_id(
                    "ingestion", "fivetran", namespace, "", f"_source_{service}",
                )
                source_ref = f"fivetran:{connector_name}:source_service:{service}"
                edge = self._make_edge(
                    source_service_id, connector_asset_id,
                    EdgeType.DERIVED_FROM, LineageLevel.TOOL,
                    confidence=0.9,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.DATA,
                )
                edges.append(edge)

        logger.info(f"[LiveFivetran] Extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a FivetranIntegration client."""
        # If a pre-built client is passed, use it
        if config.get("client"):
            return config["client"]

        fivetran_config = config.get("fivetran_config", {})
        if not fivetran_config.get("api_key"):
            logger.warning("[LiveFivetran] No fivetran_config with api_key provided")
            return None

        try:
            from scanner.integrations.fivetran import FivetranIntegration
        except ImportError:
            from integrations.fivetran import FivetranIntegration

        return FivetranIntegration(fivetran_config)

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_connector_node(
        self, connector, namespace: str, integration_id: Optional[str],
        hint: str, now: datetime,
    ) -> LineageNode:
        """Create a node for a Fivetran connector."""
        connector_name = getattr(connector, "name", "") or getattr(connector, "schema", "")
        service = getattr(connector, "service", "unknown")
        status = getattr(connector, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status) if status else "unknown"
        sync_state = getattr(connector, "sync_state", None)
        sync_state_val = sync_state.value if hasattr(sync_state, "value") else str(sync_state) if sync_state else "unknown"
        paused = getattr(connector, "paused", False)
        sync_frequency = getattr(connector, "sync_frequency", 360)

        asset_id = generate_asset_id(
            "ingestion", "fivetran", namespace, "", connector_name,
        )

        return LineageNode(
            id=asset_id,
            name=connector_name,
            fqn=f"fivetran.{namespace}.{connector_name}",
            node_type=NodeType.SOURCE,
            platform="fivetran",
            platform_domain=PlatformDomain.INGESTION,
            asset_kind=AssetKind.STREAM,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "service": service,
                "status": status_val,
                "sync_state": sync_state_val,
                "sync_frequency": sync_frequency,
                "paused": paused,
            },
        )

    def _discover_connector_tables(
        self, client, connector, namespace: str,
        integration_id: Optional[str], hint: str, now: datetime,
    ) -> List[LineageNode]:
        """Discover destination table nodes for a connector's synced tables."""
        connector_id_attr = getattr(connector, "id", "")
        connector_name = getattr(connector, "name", "") or getattr(connector, "schema", "")
        nodes: List[LineageNode] = []

        try:
            schemas = client.get_connector_schema(connector_id_attr)
        except Exception as e:
            logger.warning(f"[LiveFivetran] Failed to get schema for {connector_name}: {e}")
            return []

        for schema_name, schema_data in schemas.items():
            tables = schema_data.get("tables", [])
            for table in tables:
                table_name = getattr(table, "name", "") if hasattr(table, "name") else table.get("name", "")
                table_schema = getattr(table, "schema", schema_name) if hasattr(table, "schema") else schema_name
                enabled = getattr(table, "enabled", True) if hasattr(table, "enabled") else table.get("enabled", True)

                if not enabled or not table_name:
                    continue

                norm_schema = normalize_identifier(table_schema, hint)
                norm_table = normalize_identifier(table_name, hint)
                container = f".{norm_schema}"
                fqn = f"{norm_schema}.{norm_table}"

                # Use WAREHOUSE domain so these dedup with warehouse table nodes
                asset_id = generate_asset_id(
                    "warehouse", "fivetran", namespace, container, norm_table,
                )

                node = LineageNode(
                    id=asset_id,
                    name=norm_table,
                    fqn=fqn,
                    node_type=NodeType.TABLE,
                    schema=norm_schema,
                    platform="fivetran",
                    platform_domain=PlatformDomain.WAREHOUSE,
                    asset_kind=AssetKind.TABLE,
                    namespace=namespace,
                    observed_at=now,
                    sources=[self._id],
                    integration_id=integration_id,
                    raw_metadata={
                        "discovered_via": "fivetran_connector",
                        "connector_name": connector_name,
                    },
                )
                nodes.append(node)

        return nodes

    # ------------------------------------------------------------------
    # Edge helpers
    # ------------------------------------------------------------------

    def _make_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        level: LineageLevel,
        confidence: float,
        source_ref: str,
        now: datetime,
        snippet: Optional[str] = None,
        plane: LinePlane = LinePlane.DATA,
    ) -> LineageEdge:
        ev = Evidence(
            adapter_id=self._id,
            source_ref=source_ref,
            observed_at=now,
            snippet=snippet[:200] if snippet else None,
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
