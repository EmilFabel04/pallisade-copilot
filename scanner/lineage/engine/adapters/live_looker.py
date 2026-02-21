"""
Live Looker Adapter — extracts lineage from Looker dashboards and models.

Upgrades Looker from fixture-only (BIQueryAdapter) to live API-driven
lineage. Discovers dashboards as DASHBOARD nodes and LookML models as
MODEL nodes on the BI domain, then creates edges to warehouse tables
via tile SQL parsing and explore metadata.
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
from ..sql_lineage import SQLLineageExtractor

logger = logging.getLogger(__name__)


class LiveLookerAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Looker dashboards and LookML models,
    and extracts lineage to warehouse tables.

    Config keys:
        namespace: Identifier for this Looker instance (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        looker_config: Dict with host, client_id, client_secret
    """

    def __init__(self, adapter_id: str = "live_looker", **kwargs):
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
        """Discover Looker dashboards and LookML models."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "looker")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover dashboards
        try:
            dashboards = client.get_all_dashboards()
        except Exception as e:
            logger.error(f"[LiveLooker] Failed to get dashboards: {e}")
            dashboards = []

        for dash in dashboards:
            node = self._make_dashboard_node(dash, namespace, integration_id, now)
            if node:
                nodes.append(node)

        # Discover LookML models
        try:
            models = client.get_all_models()
        except Exception as e:
            logger.error(f"[LiveLooker] Failed to get models: {e}")
            models = []

        for model in models:
            node = self._make_model_node(model, namespace, integration_id, now)
            if node:
                nodes.append(node)

        logger.info(
            f"[LiveLooker] Discovered {len(nodes)} assets "
            f"({len(dashboards)} dashboards, {len(models)} models)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract model->dashboard and dashboard->warehouse table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "looker")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Get dashboards with element details
        try:
            dashboards = client.get_all_dashboards()
        except Exception:
            dashboards = []

        # Get models for explore -> table edges
        try:
            models = client.get_all_models()
        except Exception:
            models = []

        # Build model name -> explores lookup
        model_explores: Dict[str, List[Dict]] = {}
        for model in models:
            model_name = model.get("name", "")
            explores = model.get("explores", [])
            if model_name:
                model_explores[model_name] = explores

        # Model -> Dashboard edges (DATA plane, READS_FROM)
        # Dashboards use model explores
        for dash in dashboards:
            dash_id = dash.get("id", "")
            dash_title = dash.get("title", "unknown")
            elements = dash.get("dashboard_elements", [])

            dash_asset_id = generate_asset_id(
                "bi", "looker", namespace, "", f"dashboard_{dash_id}",
            )

            # Track which models this dashboard uses
            models_used: Set[str] = set()
            table_refs_all: Set[str] = set()

            for element in elements:
                query = element.get("query") or {}
                result_maker = element.get("result_maker") or {}

                # Get model from query or result_maker
                model_name = (
                    query.get("model")
                    or result_maker.get("query", {}).get("model", "")
                )
                if model_name:
                    models_used.add(model_name)

                # Extract table refs from element SQL
                sql = (
                    element.get("note_text")
                    or query.get("sql")
                    or result_maker.get("query", {}).get("sql", "")
                    or ""
                )
                if sql:
                    refs = self._extract_table_refs_from_sql(sql)
                    table_refs_all.update(refs)

            # Create model -> dashboard edges
            for model_name in models_used:
                model_asset_id = generate_asset_id(
                    "bi", "looker", namespace, "", f"model_{model_name}",
                )
                source_ref = f"looker:dashboard:{dash_id}:uses_model:{model_name}"
                edge = self._make_edge(
                    model_asset_id, dash_asset_id,
                    EdgeType.READS_FROM, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.DATA,
                )
                edges.append(edge)

            # Create warehouse table -> dashboard edges (CROSS plane)
            for table_ref in table_refs_all:
                parts = table_ref.split(".")
                name = normalize_identifier(parts[-1], hint)
                schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
                db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
                container = f"{db}.{schema}"

                table_asset_id = generate_asset_id(
                    "warehouse", "looker", namespace, container, name,
                )

                source_ref = f"looker:dashboard:{dash_id}:reads:{table_ref}"
                edge = self._make_edge(
                    table_asset_id, dash_asset_id,
                    EdgeType.READS_FROM, LineageLevel.TABLE,
                    confidence=0.8,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CROSS,
                )
                edges.append(edge)

        # Explore -> warehouse table edges (from explore SQL / from clause)
        for model in models:
            model_name = model.get("name", "")
            explores = model.get("explores", [])

            model_asset_id = generate_asset_id(
                "bi", "looker", namespace, "", f"model_{model_name}",
            )

            for explore in explores:
                explore_name = explore.get("name", "") if isinstance(explore, dict) else str(explore)
                # Explore's "from" field references a warehouse table/view
                from_table = explore.get("from", "") if isinstance(explore, dict) else ""
                sql_table_name = explore.get("sql_table_name", "") if isinstance(explore, dict) else ""

                table_ref = from_table or sql_table_name
                if not table_ref:
                    continue

                parts = table_ref.replace("`", "").replace('"', "").split(".")
                name = normalize_identifier(parts[-1], hint)
                schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
                db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
                container = f"{db}.{schema}"

                table_asset_id = generate_asset_id(
                    "warehouse", "looker", namespace, container, name,
                )

                source_ref = f"looker:model:{model_name}:explore:{explore_name}:from:{table_ref}"
                edge = self._make_edge(
                    table_asset_id, model_asset_id,
                    EdgeType.READS_FROM, LineageLevel.TABLE,
                    confidence=0.9,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CROSS,
                )
                edges.append(edge)

        logger.info(f"[LiveLooker] Extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a LookerClient."""
        if config.get("client"):
            return config["client"]

        looker_config = config.get("looker_config", {})
        if not looker_config.get("host"):
            logger.warning("[LiveLooker] No looker_config with host provided")
            return None

        try:
            from scanner.integrations.looker import LookerClient
        except ImportError:
            from integrations.looker import LookerClient

        return LookerClient(
            host=looker_config.get("host", ""),
            client_id=looker_config.get("client_id", ""),
            client_secret=looker_config.get("client_secret", ""),
            verify_ssl=looker_config.get("verify_ssl", True),
        )

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_dashboard_node(
        self, dash: Dict, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Looker dashboard."""
        dash_id = dash.get("id", "")
        title = dash.get("title", "")
        if not dash_id:
            return None

        folder = dash.get("folder") or {}
        folder_name = folder.get("name") if isinstance(folder, dict) else str(folder) if folder else None
        elements = dash.get("dashboard_elements", [])
        view_count = dash.get("view_count", 0)
        favorite_count = dash.get("favorite_count", 0)
        last_viewed_at = dash.get("last_viewed_at")
        last_updated_at = dash.get("last_updated_at")
        created_by = dash.get("user_id")

        # Extract table refs from all elements for cross-tool synthesis
        table_refs = set()
        for element in elements:
            query = element.get("query") or {}
            sql = query.get("sql", "")
            if sql:
                table_refs.update(self._extract_table_refs_from_sql(sql))

        asset_id = generate_asset_id(
            "bi", "looker", namespace, "", f"dashboard_{dash_id}",
        )

        return LineageNode(
            id=asset_id,
            name=title or f"Dashboard {dash_id}",
            fqn=f"looker.{namespace}.dashboard.{dash_id}",
            node_type=NodeType.DASHBOARD,
            platform="looker",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
            namespace=namespace,
            owner=str(created_by) if created_by else None,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "dashboard_id": dash_id,
                "element_count": len(elements),
                "view_count": view_count,
                "favorite_count": favorite_count,
                "folder": folder_name,
                "last_viewed_at": last_viewed_at,
                "last_updated_at": last_updated_at,
                "table_refs": list(table_refs),
            },
        )

    def _make_model_node(
        self, model: Dict, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a LookML model."""
        model_name = model.get("name", "")
        if not model_name:
            return None

        project_name = model.get("project_name", "")
        connection_name = model.get("connection", "") or model.get("connection_name", "")
        explores = model.get("explores", [])
        explore_names = [
            e.get("name", "") if isinstance(e, dict) else str(e)
            for e in explores
        ]

        asset_id = generate_asset_id(
            "bi", "looker", namespace, "", f"model_{model_name}",
        )

        return LineageNode(
            id=asset_id,
            name=model_name,
            fqn=f"looker.{namespace}.model.{model_name}",
            node_type=NodeType.MODEL,
            platform="looker",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.MODEL,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "project_name": project_name,
                "connection_name": connection_name,
                "explores": explore_names,
            },
        )

    # ------------------------------------------------------------------
    # SQL parsing helpers
    # ------------------------------------------------------------------

    _sql_extractor: Optional[SQLLineageExtractor] = None

    def _get_sql_extractor(self) -> SQLLineageExtractor:
        if self._sql_extractor is None:
            self._sql_extractor = SQLLineageExtractor(default_dialect="bigquery")
        return self._sql_extractor

    def _extract_table_refs_from_sql(self, sql: str) -> List[str]:
        """
        Extract source table references from SQL using sqlglot.

        Handles all dialects and complex SQL (CTEs, subqueries, etc.).
        """
        if not sql:
            return []

        return self._get_sql_extractor().extract_source_tables(sql)

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
