"""
Live Metabase Adapter — extracts lineage from Metabase dashboards and cards.

Discovers dashboards as DASHBOARD nodes and saved questions as QUESTION nodes
on the BI domain, then creates edges between dashboards and their cards
(TOOL level) and from cards to warehouse tables (TABLE level) via native
SQL parsing or GUI query table_id references.
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
from ..sql_lineage import SQLLineageExtractor

logger = logging.getLogger(__name__)


class LiveMetabaseAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Metabase dashboards and saved questions,
    and extracts lineage to warehouse tables.

    Config keys:
        namespace: Identifier for this Metabase instance (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        metabase_config: Dict with host, username, password
    """

    def __init__(self, adapter_id: str = "live_metabase", **kwargs):
        super().__init__(adapter_id, **kwargs)

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
        """Discover Metabase dashboards and saved questions (cards)."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "metabase")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover dashboards
        try:
            dashboards = client.get_dashboards()
        except Exception as e:
            logger.error(f"[LiveMetabase] Failed to get dashboards: {e}")
            dashboards = []

        for dash in dashboards:
            node = self._make_dashboard_node(dash, namespace, integration_id, now)
            if node:
                nodes.append(node)

        # Discover cards (saved questions)
        try:
            cards = client.get_cards()
        except Exception as e:
            logger.error(f"[LiveMetabase] Failed to get cards: {e}")
            cards = []

        for card in cards:
            node = self._make_card_node(card, namespace, integration_id, now)
            if node:
                nodes.append(node)

        logger.info(
            f"[LiveMetabase] Discovered {len(nodes)} assets "
            f"({len(dashboards)} dashboards, {len(cards)} cards)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract dashboard→card and card→warehouse table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "metabase")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Get dashboards with their cards
        try:
            dashboards = client.get_dashboards()
        except Exception:
            dashboards = []

        # Get all cards
        try:
            cards = client.get_cards()
        except Exception:
            cards = []

        # Build card lookup by ID
        card_by_id: Dict[int, Dict] = {}
        for card in cards:
            card_id = card.get("id")
            if card_id is not None:
                card_by_id[card_id] = card

        # Dashboard → Card edges (TOOL level, DATA plane)
        for dash in dashboards:
            dash_id = dash.get("id")
            if dash_id is None:
                continue

            dash_asset_id = generate_asset_id(
                "bi", "metabase", namespace, "", f"dashboard_{dash_id}",
            )

            # Get full dashboard to see which cards it contains
            try:
                full_dash = client.get_dashboard(dash_id)
            except Exception as e:
                logger.warning(f"[LiveMetabase] Failed to get dashboard {dash_id}: {e}")
                continue

            ordered_cards = full_dash.get("ordered_cards", [])
            seen_card_ids: Set[int] = set()

            for dash_card in ordered_cards:
                card_info = dash_card.get("card", {})
                card_id = card_info.get("id")
                if card_id is None or card_id in seen_card_ids:
                    continue
                seen_card_ids.add(card_id)

                card_asset_id = generate_asset_id(
                    "bi", "metabase", namespace, "", f"card_{card_id}",
                )

                source_ref = f"metabase:dashboard:{dash_id}:contains_card:{card_id}"
                edge = self._make_edge(
                    card_asset_id, dash_asset_id,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.DATA,
                )
                edges.append(edge)

        # Card → Warehouse table edges (TABLE level, CROSS plane)
        for card in cards:
            card_id = card.get("id")
            if card_id is None:
                continue

            card_asset_id = generate_asset_id(
                "bi", "metabase", namespace, "", f"card_{card_id}",
            )

            dataset_query = card.get("dataset_query", {})
            query_type = dataset_query.get("type", "query")

            if query_type == "native":
                # Native SQL query — parse SQL to find table references
                native_query = dataset_query.get("native", {}).get("query", "")
                if not native_query:
                    continue

                table_refs = self._extract_table_refs_from_sql(native_query)
                for table_ref in table_refs:
                    parts = table_ref.split(".")
                    name = normalize_identifier(parts[-1], hint)
                    schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
                    db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
                    container = f"{db}.{schema}"

                    table_asset_id = generate_asset_id(
                        "warehouse", "metabase", namespace, container, name,
                    )

                    source_ref = f"metabase:card:{card_id}:native_query:reads:{table_ref}"
                    edge = self._make_edge(
                        table_asset_id, card_asset_id,
                        EdgeType.READS_FROM, LineageLevel.TABLE,
                        confidence=0.8,
                        source_ref=source_ref,
                        snippet=native_query[:200] if native_query else None,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                    edges.append(edge)

            elif query_type == "query":
                # GUI query — use table_id from query metadata
                table_id = dataset_query.get("query", {}).get("source-table")
                if table_id is None:
                    continue

                # Metabase table IDs are integers referencing internal metadata;
                # use a synthetic reference so the resolver can match later.
                table_name = f"metabase_table_{table_id}"
                table_asset_id = generate_asset_id(
                    "warehouse", "metabase", namespace, "", table_name,
                )

                source_ref = f"metabase:card:{card_id}:gui_query:table_id:{table_id}"
                edge = self._make_edge(
                    table_asset_id, card_asset_id,
                    EdgeType.READS_FROM, LineageLevel.TABLE,
                    confidence=0.9,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CROSS,
                )
                edges.append(edge)

        logger.info(f"[LiveMetabase] Extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a MetabaseClient."""
        if config.get("client"):
            return config["client"]

        metabase_config = config.get("metabase_config", {})
        if not metabase_config.get("host"):
            logger.warning("[LiveMetabase] No metabase_config with host provided")
            return None

        try:
            from scanner.integrations.metabase import MetabaseClient
        except ImportError:
            from integrations.metabase import MetabaseClient

        return MetabaseClient(
            host=metabase_config.get("host", ""),
            username=metabase_config.get("username", ""),
            password=metabase_config.get("password", ""),
        )

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_dashboard_node(
        self, dash: Dict, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Metabase dashboard."""
        dash_id = dash.get("id")
        name = dash.get("name", "")
        if dash_id is None:
            return None

        collection_name = dash.get("collection", {}).get("name") if isinstance(dash.get("collection"), dict) else dash.get("collection_name")
        card_count = dash.get("card_count", 0)

        asset_id = generate_asset_id(
            "bi", "metabase", namespace, "", f"dashboard_{dash_id}",
        )

        return LineageNode(
            id=asset_id,
            name=name or f"Dashboard {dash_id}",
            fqn=f"metabase.{namespace}.dashboard.{dash_id}",
            node_type=NodeType.DASHBOARD,
            platform="metabase",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DASHBOARD,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "dashboard_id": dash_id,
                "card_count": card_count,
                "collection_name": collection_name,
            },
        )

    def _make_card_node(
        self, card: Dict, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Metabase saved question (card)."""
        card_id = card.get("id")
        name = card.get("name", "")
        if card_id is None:
            return None

        dataset_query = card.get("dataset_query", {})
        query_type = dataset_query.get("type", "query")
        database_id = card.get("database_id")
        display = card.get("display", "table")

        asset_id = generate_asset_id(
            "bi", "metabase", namespace, "", f"card_{card_id}",
        )

        return LineageNode(
            id=asset_id,
            name=name or f"Card {card_id}",
            fqn=f"metabase.{namespace}.card.{card_id}",
            node_type=NodeType.QUESTION,
            platform="metabase",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.QUESTION,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "card_id": card_id,
                "query_type": query_type,
                "database_id": database_id,
                "display": display,
            },
        )

    # ------------------------------------------------------------------
    # SQL parsing helpers
    # ------------------------------------------------------------------

    _sql_extractor: Optional[SQLLineageExtractor] = None

    def _get_sql_extractor(self) -> SQLLineageExtractor:
        if self._sql_extractor is None:
            self._sql_extractor = SQLLineageExtractor(default_dialect="postgres")
        return self._sql_extractor

    def _extract_table_refs_from_sql(self, sql: str) -> List[str]:
        """
        Extract source table references from SQL using sqlglot.

        Handles all dialects and complex SQL (CTEs, subqueries, etc.).
        """
        if not sql:
            return []

        return self._get_sql_extractor().extract_source_tables(sql)

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
