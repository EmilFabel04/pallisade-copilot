"""
Live Tableau Adapter — extracts lineage from Tableau workbooks and datasources.

Upgrades Tableau from fixture-only to live API-driven lineage. Discovers
workbooks as WORKBOOK nodes and datasources as DATASET nodes on the BI
domain, then creates edges from workbooks to datasources (TOOL level) and
from datasources to warehouse tables (TABLE level, CROSS plane).
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


class LiveTableauAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Tableau workbooks and datasources,
    and extracts lineage to warehouse tables.

    Config keys:
        namespace: Identifier for this Tableau instance (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        tableau_config: Dict with server_url, token_name, token_value, site_id
    """

    def __init__(self, adapter_id: str = "live_tableau", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_BI_EXPOSURES,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Tableau workbooks and datasources."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "tableau")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover workbooks
        try:
            workbooks = client.get_all_workbooks()
        except Exception as e:
            logger.error(f"[LiveTableau] Failed to get workbooks: {e}")
            workbooks = []

        for wb in workbooks:
            node = self._make_workbook_node(wb, namespace, integration_id, now)
            if node:
                nodes.append(node)

        # Discover datasources
        try:
            datasources = client.get_all_datasources()
        except Exception as e:
            logger.error(f"[LiveTableau] Failed to get datasources: {e}")
            datasources = []

        for ds in datasources:
            node = self._make_datasource_node(ds, namespace, integration_id, now)
            if node:
                nodes.append(node)

        logger.info(
            f"[LiveTableau] Discovered {len(nodes)} assets "
            f"({len(workbooks)} workbooks, {len(datasources)} datasources)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract workbook->datasource and datasource->warehouse table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "tableau")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Get workbooks and datasources
        try:
            workbooks = client.get_all_workbooks()
        except Exception:
            workbooks = []

        try:
            datasources = client.get_all_datasources()
        except Exception:
            datasources = []

        # Build datasource ID -> datasource lookup
        ds_lookup: Dict[str, Dict] = {}
        for ds in datasources:
            ds_id = self._get_ds_id(ds)
            if ds_id:
                ds_lookup[ds_id] = ds

        # Workbook -> Datasource edges (DATA plane, READS_FROM, TOOL level)
        for wb in workbooks:
            wb_id = self._get_wb_id(wb)
            if not wb_id:
                continue

            wb_asset_id = generate_asset_id(
                "bi", "tableau", namespace, "", f"workbook_{wb_id}",
            )

            # Get datasource IDs linked to this workbook
            datasource_ids = self._get_wb_datasource_ids(wb, client)

            for ds_id in datasource_ids:
                ds_asset_id = generate_asset_id(
                    "bi", "tableau", namespace, "", f"datasource_{ds_id}",
                )

                source_ref = f"tableau:workbook:{wb_id}:reads_datasource:{ds_id}"
                edge = self._make_edge(
                    ds_asset_id, wb_asset_id,
                    EdgeType.READS_FROM, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.DATA,
                )
                edges.append(edge)

        # Datasource -> Warehouse table edges (CROSS plane, READS_FROM, TABLE level)
        for ds in datasources:
            ds_id = self._get_ds_id(ds)
            if not ds_id:
                continue

            ds_asset_id = generate_asset_id(
                "bi", "tableau", namespace, "", f"datasource_{ds_id}",
            )

            # Extract warehouse table reference from datasource connection info
            database_name = self._get_ds_database_name(ds)
            server_name = self._get_ds_server_name(ds)
            connection_type = self._get_ds_connection_type(ds)

            if not database_name:
                continue

            # Build a table reference from the datasource connection info.
            # The database_name typically represents the database/schema the
            # datasource connects to. We create a warehouse asset for it.
            table_ref = database_name
            parts = table_ref.replace("`", "").replace('"', "").split(".")
            name = normalize_identifier(parts[-1], hint)
            schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
            db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
            container = f"{db}.{schema}" if db or schema else ""

            table_asset_id = generate_asset_id(
                "warehouse", "tableau", namespace, container, name,
            )

            source_ref = f"tableau:datasource:{ds_id}:reads:{table_ref}"
            edge = self._make_edge(
                table_asset_id, ds_asset_id,
                EdgeType.READS_FROM, LineageLevel.TABLE,
                confidence=0.8,
                source_ref=source_ref,
                now=now,
                plane=LinePlane.CROSS,
            )
            edges.append(edge)

        logger.info(f"[LiveTableau] Extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a TableauClient."""
        if config.get("client"):
            return config["client"]

        tableau_config = config.get("tableau_config", {})
        if not tableau_config.get("server_url"):
            logger.warning("[LiveTableau] No tableau_config with server_url provided")
            return None

        try:
            from scanner.integrations.tableau import TableauClient
        except ImportError:
            from integrations.tableau import TableauClient

        return TableauClient(
            server=tableau_config.get("server_url", ""),
            token_name=tableau_config.get("token_name", ""),
            token_secret=tableau_config.get("token_value", ""),
            site_id=tableau_config.get("site_id", ""),
        )

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_workbook_node(
        self, wb: Any, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Tableau workbook."""
        wb_id = self._get_wb_id(wb)
        if not wb_id:
            return None

        wb_name = self._get_wb_name(wb)
        project_name = self._get_project_name(wb)
        view_count = self._get_wb_view_count(wb)
        datasource_ids = self._get_wb_datasource_ids_static(wb)
        owner_name = self._get_wb_owner(wb)

        asset_id = generate_asset_id(
            "bi", "tableau", namespace, "", f"workbook_{wb_id}",
        )

        return LineageNode(
            id=asset_id,
            name=wb_name or f"Workbook {wb_id}",
            fqn=f"tableau.{namespace}.workbook.{wb_id}",
            node_type=NodeType.WORKBOOK,
            platform="tableau",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.WORKBOOK,
            namespace=namespace,
            owner=owner_name,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "project_name": project_name,
                "view_count": view_count,
                "datasource_ids": datasource_ids,
            },
        )

    def _make_datasource_node(
        self, ds: Any, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Tableau datasource."""
        ds_id = self._get_ds_id(ds)
        if not ds_id:
            return None

        ds_name = self._get_ds_name(ds)
        project_name = self._get_project_name(ds)
        connection_type = self._get_ds_connection_type(ds)
        server_name = self._get_ds_server_name(ds)
        database_name = self._get_ds_database_name(ds)
        has_extracts = self._get_ds_has_extracts(ds)

        asset_id = generate_asset_id(
            "bi", "tableau", namespace, "", f"datasource_{ds_id}",
        )

        return LineageNode(
            id=asset_id,
            name=ds_name or f"Datasource {ds_id}",
            fqn=f"tableau.{namespace}.datasource.{ds_id}",
            node_type=NodeType.DATASET,
            platform="tableau",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DATASET,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "connection_type": connection_type,
                "server_name": server_name,
                "database_name": database_name,
                "has_extracts": has_extracts,
            },
        )

    # ------------------------------------------------------------------
    # Data access helpers (handle both dataclass and dict formats)
    # ------------------------------------------------------------------

    def _get_wb_id(self, wb: Any) -> str:
        if isinstance(wb, dict):
            return wb.get("id", "")
        return getattr(wb, "id", "")

    def _get_wb_name(self, wb: Any) -> str:
        if isinstance(wb, dict):
            return wb.get("name", "")
        return getattr(wb, "name", "")

    def _get_wb_view_count(self, wb: Any) -> int:
        if isinstance(wb, dict):
            return wb.get("viewCount", 0) or wb.get("view_count", 0)
        return getattr(wb, "view_count", 0)

    def _get_wb_owner(self, wb: Any) -> Optional[str]:
        if isinstance(wb, dict):
            owner = wb.get("owner", {})
            if isinstance(owner, dict):
                return owner.get("name")
            return owner if owner else None
        return getattr(wb, "owner_name", None)

    def _get_wb_datasource_ids_static(self, wb: Any) -> List[str]:
        """Get datasource IDs from workbook data without API calls."""
        if isinstance(wb, dict):
            return wb.get("datasource_ids", []) or wb.get("datasourceIds", [])
        return getattr(wb, "datasource_ids", [])

    def _get_wb_datasource_ids(self, wb: Any, client: Any) -> List[str]:
        """
        Get datasource IDs for a workbook.

        Tries static data first, then falls back to API connections endpoint.
        """
        # Try from workbook data
        ids = self._get_wb_datasource_ids_static(wb)
        if ids:
            return ids

        # Fall back to connections API
        wb_id = self._get_wb_id(wb)
        if not wb_id or not client:
            return []

        try:
            connections = client.get_workbook_connections(wb_id)
            ds_ids = []
            for conn in connections:
                ds_id = conn.get("datasource", {}).get("id", "") if isinstance(conn, dict) else ""
                if ds_id:
                    ds_ids.append(ds_id)
            return ds_ids
        except Exception as e:
            logger.warning(f"[LiveTableau] Could not get connections for workbook {wb_id}: {e}")
            return []

    def _get_ds_id(self, ds: Any) -> str:
        if isinstance(ds, dict):
            return ds.get("id", "")
        return getattr(ds, "id", "")

    def _get_ds_name(self, ds: Any) -> str:
        if isinstance(ds, dict):
            return ds.get("name", "")
        return getattr(ds, "name", "")

    def _get_ds_connection_type(self, ds: Any) -> str:
        if isinstance(ds, dict):
            return ds.get("contentType", "") or ds.get("connection_type", "")
        return getattr(ds, "connection_type", "")

    def _get_ds_server_name(self, ds: Any) -> Optional[str]:
        if isinstance(ds, dict):
            return ds.get("serverName") or ds.get("server_name")
        return getattr(ds, "server_name", None)

    def _get_ds_database_name(self, ds: Any) -> Optional[str]:
        if isinstance(ds, dict):
            return ds.get("databaseName") or ds.get("database_name")
        return getattr(ds, "database_name", None)

    def _get_ds_has_extracts(self, ds: Any) -> bool:
        if isinstance(ds, dict):
            return ds.get("hasExtracts", False) or ds.get("has_extracts", False)
        return getattr(ds, "has_extracts", False)

    def _get_project_name(self, item: Any) -> str:
        if isinstance(item, dict):
            project = item.get("project", {})
            if isinstance(project, dict):
                return project.get("name", "")
            return str(project) if project else ""
        return getattr(item, "project_name", "")

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
