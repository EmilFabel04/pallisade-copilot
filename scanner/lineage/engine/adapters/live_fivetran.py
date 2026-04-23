"""
Live Fivetran Adapter — extracts lineage from Fivetran connectors.

Maps Fivetran connectors to ingestion-plane nodes and creates
deterministic WRITES_TO edges to the destination warehouse tables.
Each connector becomes a CONNECTOR (job) node on the INGESTION domain,
and each synced table becomes a TABLE node. Edges from connector jobs
to destination tables carry API-sourced evidence.
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
from ..ids import compute_environment_scope, generate_asset_id, normalize_identifier

logger = logging.getLogger(__name__)

# Case conventions for destination warehouse platforms
_DEST_CASE_HINTS = {
    "bigquery": "lower",
    "snowflake": "upper",
    "postgres": "lower",
    "redshift": "lower",
}


class LiveFivetranAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Fivetran connectors and extracts lineage
    to destination warehouse tables.

    Config keys:
        namespace: Identifier for this Fivetran account (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        fivetran_config: Dict with api_key, api_secret for FivetranIntegration
        environment_scope: (optional) disambiguates same asset across envs
        destination_config: (optional) dict with destination warehouse details:
            platform: "bigquery" | "snowflake" | "postgres"
            project_id: (BQ) GCP project ID
            database: (SF/PG) database name
            dataset / schema: warehouse schema/dataset name override
            account, region: (SF) account details
            host, port: (PG) connection details
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
        """Discover Fivetran connectors and their destination tables.

        When ``destination_config`` is provided, also emits WAREHOUSE-domain
        destination table nodes that will merge with warehouse-discovered
        tables via the resolver's stable_id dedup.
        """
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "fivetran")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Compute environment scope: explicit > destination_config > empty
        env_scope = config.get("environment_scope", "")
        dest_cfg = config.get("destination_config", {}) or {}
        dest_platform = dest_cfg.get("platform", "")
        if not env_scope and dest_cfg:
            env_scope = compute_environment_scope(dest_platform, dest_cfg)

        try:
            connectors = client.get_connectors()
        except Exception as e:
            logger.error(f"[LiveFivetran] Failed to get connectors: {e}")
            return []

        # Internal Fivetran connectors that are not part of data lineage
        _INTERNAL_SERVICES = {"fivetran_metadata", "fivetran_log"}

        # Create Fivetran service node (one per adapter invocation)
        service_node = self._make_service_node(
            namespace, integration_id, env_scope, now,
        )
        nodes.append(service_node)

        for connector in connectors:
            service = getattr(connector, "service", "unknown")
            connector_name = getattr(connector, "name", "") or getattr(connector, "schema", "")

            # Skip internal/metadata connectors — not part of data flow
            if service in _INTERNAL_SERVICES or connector_name in _INTERNAL_SERVICES:
                logger.debug(f"[LiveFivetran] Skipping internal connector: {connector_name} ({service})")
                continue

            # Discover individual synced tables from the connector schema.
            # Each enabled table becomes an INGESTION TABLE node (green).
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
                            table_node.environment_scope = env_scope or None
                            nodes.append(table_node)

                # Create a connector JOB node for edge attribution
                connector_job_id = generate_asset_id(
                    "ingestion", "fivetran", namespace,
                    "", f"connector_{connector_id_attr}",
                )
                connector_job_node = LineageNode(
                    id=connector_job_id,
                    name=f"{connector_name} connector",
                    fqn=f"fivetran.{namespace}.connector.{connector_name}".lower(),
                    node_type=NodeType.CONNECTOR,
                    platform="fivetran",
                    platform_domain=PlatformDomain.INGESTION,
                    asset_kind=AssetKind.CONNECTOR,
                    namespace=namespace,
                    canonical_type="job",
                    observed_at=now,
                    sources=[self._id],
                    integration_id=integration_id,
                    evidence=[Evidence(
                        adapter_id=self._id,
                        source_ref=f"fivetran_api:connector:{connector_id_attr}",
                        observed_at=now,
                    )],
                    raw_metadata={
                        "service": service,
                        "connector_id": connector_id_attr,
                        "connector_name": connector_name,
                        "source_type": service,
                        "synced_tables": list(synced_tables),
                        "node_role": "connector_job",
                    },
                )
                connector_job_node.environment_scope = env_scope or None
                nodes.append(connector_job_node)

                # When destination warehouse is known, emit warehouse-domain
                # destination table nodes that merge with warehouse-discovered
                # tables via the resolver's stable_id dedup.
                if dest_platform and synced_tables:
                    dest_nodes = self._emit_destination_nodes(
                        synced_tables, dest_cfg, dest_schema,
                        connector_id_attr, connector_name, service,
                        integration_id, env_scope, now,
                    )
                    nodes.extend(dest_nodes)

                logger.info(
                    "[LiveFivetran] Connector %s: dest_schema=%s, synced_tables=%s, "
                    "dest_nodes=%d",
                    connector_name, dest_schema, synced_tables,
                    len(dest_nodes) if dest_platform and synced_tables else 0,
                )
            except Exception as e:
                logger.warning("[LiveFivetran] Schema fetch failed for %s: %s", connector_name, e)

        logger.info(f"[LiveFivetran] Discovered {len(nodes)} nodes (synced tables + connector jobs + destinations)")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract deterministic connector → destination table edges.

        Creates WRITES_TO edges from each connector JOB to each synced
        table node (created by ``discover_assets``). When ``destination_config``
        is provided, also emits direct edges to warehouse-domain destination
        tables (these merge with warehouse-discovered nodes via resolver).

        Also creates RUNS edges from the Fivetran service node to each
        connector JOB.
        """
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "fivetran")
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        dest_cfg = config.get("destination_config", {}) or {}
        dest_platform = dest_cfg.get("platform", "")

        try:
            connectors = client.get_connectors()
        except Exception as e:
            logger.error(f"[LiveFivetran] extract_lineage: Failed to get connectors: {e}")
            return []

        _INTERNAL_SERVICES = {"fivetran_metadata", "fivetran_log"}

        # Service node ID for RUNS edges (must match discover_assets)
        service_node_id = generate_asset_id(
            "ingestion", "fivetran", namespace, "", "fivetran_service",
        )

        for connector in connectors:
            service = getattr(connector, "service", "unknown")
            connector_name = getattr(connector, "name", "") or getattr(connector, "schema", "")

            if service in _INTERNAL_SERVICES or connector_name in _INTERNAL_SERVICES:
                continue

            connector_id_attr = getattr(connector, "id", "")
            dest_schema = getattr(connector, "schema", "") or connector_name

            # Connector JOB node ID (must match discover_assets)
            connector_job_id = generate_asset_id(
                "ingestion", "fivetran", namespace,
                "", f"connector_{connector_id_attr}",
            )

            # RUNS edge: service → connector job
            runs_edge = self._make_edge(
                service_node_id, connector_job_id,
                EdgeType.TRIGGERS, LineageLevel.TOOL,
                confidence=0.95,
                source_ref=f"fivetran_api:service_runs_connector:{connector_id_attr}",
                now=now,
                snippet=f"Fivetran service runs connector '{connector_name}'",
                plane=LinePlane.CONTROL,
            )
            runs_edge.canonical_edge_type = "runs"
            edges.append(runs_edge)

            try:
                schemas = client.get_connector_schema(connector_id_attr)
            except Exception as e:
                logger.warning(
                    "[LiveFivetran] extract_lineage: schema fetch failed for %s: %s",
                    connector_name, e,
                )
                continue

            for src_schema_name, schema_data in schemas.items():
                tables_data = schema_data.get("tables", [])
                for t in tables_data:
                    tname = getattr(t, "name", "") if hasattr(t, "name") else t.get("name", "")
                    enabled = getattr(t, "enabled", True) if hasattr(t, "enabled") else t.get("enabled", True)
                    if not tname or not enabled:
                        continue

                    norm_table = normalize_identifier(tname, self.case_hint)

                    # Edge 1: connector_job → synced_table (Fivetran domain)
                    # The CrossToolEdgeSynthesizer uses these as fallback when
                    # destination_config is not available.
                    container = f"{service}.{src_schema_name}"
                    table_asset_id = generate_asset_id(
                        "ingestion", "fivetran", namespace,
                        container, norm_table,
                    )

                    source_ref = (
                        f"fivetran_connector:{connector_id_attr}"
                        f":schema_mapping:{src_schema_name}.{tname}"
                    )
                    edge = self._make_edge(
                        connector_job_id, table_asset_id,
                        EdgeType.WRITES_TO, LineageLevel.TABLE,
                        confidence=0.9,
                        source_ref=source_ref,
                        now=now,
                        snippet=(
                            f"Fivetran connector '{connector_name}' syncs "
                            f"{tname} to {dest_schema}"
                        ),
                        plane=LinePlane.CROSS,
                    )
                    edge.canonical_edge_type = "writes"
                    edges.append(edge)

                    # Edge 2: connector_job → warehouse destination table
                    # Only when destination_config is known. These edges target
                    # warehouse-FQN node IDs that merge with warehouse-discovered
                    # tables via the resolver.
                    if dest_platform:
                        dest_edge = self._make_destination_edge(
                            connector_job_id, connector_id_attr, connector_name,
                            tname, dest_cfg, now,
                        )
                        if dest_edge:
                            edges.append(dest_edge)

        logger.info(f"[LiveFivetran] Extracted {len(edges)} deterministic edges")
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
    # Destination helpers
    # ------------------------------------------------------------------

    def _emit_destination_nodes(
        self,
        synced_tables: List[str],
        dest_cfg: Dict[str, Any],
        dest_schema_fallback: str,
        connector_id: str,
        connector_name: str,
        service: str,
        integration_id: Optional[str],
        env_scope: str,
        now: datetime,
    ) -> List[LineageNode]:
        """Emit warehouse-domain destination table nodes.

        These nodes use the same ID formula as the warehouse adapter so
        the resolver merges them with warehouse-discovered tables.
        """
        dest_platform = dest_cfg.get("platform", "")
        hint = _DEST_CASE_HINTS.get(dest_platform, "lower")
        dest_database = normalize_identifier(
            dest_cfg.get("project_id") or dest_cfg.get("database") or "",
            hint,
        )
        explicit_dataset = dest_cfg.get("dataset") or dest_cfg.get("schema") or ""
        if not explicit_dataset:
            # Don't fall back to Fivetran's dest_schema — it's the connector
            # name (e.g., "postgres") which doesn't reliably map to the actual
            # warehouse dataset (e.g., "raw"). Let CrossToolEdgeSynthesizer
            # handle the matching by table name instead.
            logger.debug(
                "[LiveFivetran] No explicit dataset in destination_config, "
                "skipping destination node emission (dest_schema_fallback=%s)",
                dest_schema_fallback,
            )
            return []
        dest_schema_name = normalize_identifier(explicit_dataset, hint)
        dest_scope = compute_environment_scope(dest_platform, dest_cfg)

        nodes: List[LineageNode] = []
        for tname in synced_tables:
            norm_name = normalize_identifier(tname, hint)
            container = f"{dest_database}.{dest_schema_name}"
            fqn = ".".join(p for p in [dest_database, dest_schema_name, norm_name] if p)

            dest_table_id = generate_asset_id(
                "warehouse", dest_platform, dest_database, container, norm_name,
            )
            dest_node = LineageNode(
                id=dest_table_id,
                name=norm_name,
                fqn=fqn,
                node_type=NodeType.TABLE,
                platform=dest_platform,
                platform_domain=PlatformDomain.WAREHOUSE,
                asset_kind=AssetKind.TABLE,
                database=dest_database,
                schema=dest_schema_name,
                namespace=dest_database,
                environment_scope=dest_scope or env_scope or None,
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                evidence=[Evidence(
                    adapter_id=self._id,
                    source_ref=(
                        f"fivetran_connector:{connector_id}"
                        f":destination:{dest_schema_name}.{norm_name}"
                    ),
                    observed_at=now,
                    snippet="Discovered as Fivetran sync destination",
                )],
                raw_metadata={
                    "node_role": "fivetran_destination",
                    "source_connector": connector_name,
                    "source_service": service,
                },
            )
            nodes.append(dest_node)
        return nodes

    def _make_destination_edge(
        self,
        connector_job_id: str,
        connector_id: str,
        connector_name: str,
        tname: str,
        dest_cfg: Dict[str, Any],
        now: datetime,
    ) -> Optional[LineageEdge]:
        """Create a WRITES_TO edge from connector job to warehouse destination table."""
        explicit_dataset = dest_cfg.get("dataset") or dest_cfg.get("schema") or ""
        if not explicit_dataset:
            return None
        dest_platform = dest_cfg.get("platform", "")
        hint = _DEST_CASE_HINTS.get(dest_platform, "lower")
        dest_database = normalize_identifier(
            dest_cfg.get("project_id") or dest_cfg.get("database") or "",
            hint,
        )
        dest_schema_name_norm = normalize_identifier(explicit_dataset, hint)
        norm_name = normalize_identifier(tname, hint)
        container = f"{dest_database}.{dest_schema_name_norm}"

        dest_table_id = generate_asset_id(
            "warehouse", dest_platform, dest_database, container, norm_name,
        )
        source_ref = (
            f"fivetran_connector:{connector_id}"
            f":destination_mapping:{dest_schema_name_norm}.{norm_name}"
        )
        dest_fqn = ".".join(
            p for p in [dest_database, dest_schema_name_norm, norm_name] if p
        )
        edge = self._make_edge(
            connector_job_id, dest_table_id,
            EdgeType.WRITES_TO, LineageLevel.TABLE,
            confidence=0.9,
            source_ref=source_ref,
            now=now,
            snippet=(
                f"Fivetran '{connector_name}' syncs {tname} → {dest_fqn}"
            ),
            plane=LinePlane.CROSS,
        )
        edge.canonical_edge_type = "writes"
        return edge

    def _make_service_node(
        self,
        namespace: str,
        integration_id: Optional[str],
        env_scope: str,
        now: datetime,
    ) -> LineageNode:
        """Create a SERVICE node for the Fivetran instance."""
        service_id = generate_asset_id(
            "ingestion", "fivetran", namespace, "", "fivetran_service",
        )
        return LineageNode(
            id=service_id,
            name="Fivetran",
            fqn=f"fivetran.{namespace}.service",
            node_type=NodeType.SOURCE,
            platform="fivetran",
            platform_domain=PlatformDomain.INGESTION,
            canonical_type="service",
            namespace=namespace,
            environment_scope=env_scope or None,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
        )

    # ------------------------------------------------------------------
    # Node helpers (legacy)
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


