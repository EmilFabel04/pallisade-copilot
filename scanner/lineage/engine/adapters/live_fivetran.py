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
    LineageEdge,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id

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
        super().__init__(adapter_id, **kwargs)

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

        # Internal Fivetran connectors that are not part of data lineage
        _INTERNAL_SERVICES = {"fivetran_metadata", "fivetran_log"}

        for connector in connectors:
            service = getattr(connector, "service", "unknown")
            connector_name = getattr(connector, "name", "") or getattr(connector, "schema", "")

            # Skip internal/metadata connectors — not part of data flow
            if service in _INTERNAL_SERVICES or connector_name in _INTERNAL_SERVICES:
                logger.debug(f"[LiveFivetran] Skipping internal connector: {connector_name} ({service})")
                continue

            # Discover individual synced tables from the connector schema.
            # Each enabled table becomes an INGESTION TABLE node (green).
            # We skip service-level and connector-level nodes — the user
            # wants to see only the actual tables being synced.
            connector_id_attr = getattr(connector, "id", "")
            dest_schema = getattr(connector, "schema", "") or connector_name
            try:
                schemas = client.get_connector_schema(connector_id_attr)
                synced_tables = []
                for src_schema_name, schema_data in schemas.items():
                    tables = schema_data.get("tables", [])
                    for t in tables:
                        tname = getattr(t, "name", "") if hasattr(t, "name") else t.get("name", "")
                        enabled = getattr(t, "enabled", True) if hasattr(t, "enabled") else t.get("enabled", True)
                        if tname and enabled:
                            synced_tables.append(tname.lower())
                            table_asset_id = generate_asset_id(
                                "ingestion", "fivetran", namespace,
                                f"{service}.{src_schema_name}", tname.lower(),
                            )
                            table_node = LineageNode(
                                id=table_asset_id,
                                name=tname.lower(),
                                fqn=f"{service}.{src_schema_name}.{tname}".lower(),
                                node_type=NodeType.TABLE,
                                platform="fivetran",
                                platform_domain=PlatformDomain.INGESTION,
                                asset_kind=AssetKind.TABLE,
                                database=service,
                                schema=src_schema_name.lower(),
                                namespace=namespace,
                                observed_at=now,
                                sources=[self._id],
                                integration_id=integration_id,
                                raw_metadata={
                                    "source_service": service,
                                    "source_schema": src_schema_name,
                                    "connector_name": connector_name,
                                    "dest_schema": dest_schema,
                                    "node_role": "synced_table",
                                    "synced_tables": synced_tables,
                                },
                            )
                            nodes.append(table_node)
                logger.info(
                    "[LiveFivetran] Connector %s: dest_schema=%s, synced_tables=%s",
                    connector_name, dest_schema, synced_tables,
                )
            except Exception as e:
                logger.warning("[LiveFivetran] Schema fetch failed for %s: %s", connector_name, e)

        logger.info(f"[LiveFivetran] Discovered {len(nodes)} synced table nodes")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:  # noqa: ARG002
        """Extract edges for the Fivetran ingestion flow.

        Synced table → warehouse table edges are handled by cross-tool
        synthesis (name-based matching in CrossToolLinker.synthesize_ingestion_edges)
        because Fivetran source schema names often differ from the actual
        warehouse dataset names (e.g., Postgres "public" vs BigQuery "raw").
        """
        # All Fivetran edges are created by cross-tool synthesis
        # (synced_table → warehouse_table POPULATES edges).
        return []

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
            tags=["fivetran"],
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "service": service,
                "connector_name": connector_name,
                "status": status_val,
                "sync_state": sync_state_val,
                "sync_frequency": sync_frequency,
                "paused": paused,
            },
        )


