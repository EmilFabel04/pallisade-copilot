"""
Live Databricks Adapter — extracts lineage from Databricks Unity Catalog.

Uses the Unity Catalog REST API to discover catalogs, schemas, and tables,
then extracts table-level and column-level lineage via the lineage endpoints.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    ColumnMapping,
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

# Unity Catalog table_type → engine NodeType / AssetKind
_UC_TYPE_MAP = {
    "MANAGED": (NodeType.TABLE, AssetKind.TABLE),
    "EXTERNAL": (NodeType.TABLE, AssetKind.TABLE),
    "VIEW": (NodeType.VIEW, AssetKind.VIEW),
    "MATERIALIZED_VIEW": (NodeType.MATERIALIZED_VIEW, AssetKind.VIEW),
}


class LiveDatabricksAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Databricks Unity Catalog assets and extracts
    table-level and column-level lineage via the REST API.

    Config keys:
        namespace: Workspace URL or identifier (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        databricks_config: Dict with host, token, http_path
    """

    def __init__(self, adapter_id: str = "live_databricks", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.EXTRACT_COLUMN_LINEAGE,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover catalogs, schemas, and tables from Unity Catalog."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "databricks")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        hint = self.case_hint
        nodes: List[LineageNode] = []

        # 1. List catalogs
        catalogs = self._list_catalogs(client)
        if not catalogs:
            logger.warning("[LiveDatabricks] No catalogs found")
            return []

        for catalog in catalogs:
            catalog_name = catalog.get("name", "")
            if not catalog_name:
                continue

            # 2. List schemas in this catalog
            schemas = self._list_schemas(client, catalog_name)

            for schema_info in schemas:
                schema_name = schema_info.get("name", "")
                if not schema_name:
                    continue

                # Skip internal schemas
                if schema_name.lower() in ("information_schema",):
                    continue

                # 3. List tables in this schema
                tables = self._list_tables(client, catalog_name, schema_name)

                for table in tables:
                    table_name = table.get("name", "")
                    if not table_name:
                        continue

                    table_type = table.get("table_type", "MANAGED").upper()
                    node_type, asset_kind = _UC_TYPE_MAP.get(
                        table_type, (NodeType.TABLE, AssetKind.TABLE)
                    )

                    db = normalize_identifier(catalog_name, hint)
                    schema = normalize_identifier(schema_name, hint)
                    name = normalize_identifier(table_name, hint)
                    container = f"{db}.{schema}"
                    fqn = f"{db}.{schema}.{name}"

                    asset_id = generate_asset_id(
                        "warehouse", "databricks", namespace, container, name,
                    )

                    # Extract column info from table properties if present
                    columns: List[Dict[str, Any]] = []
                    for col in table.get("columns", []):
                        columns.append({
                            "name": col.get("name", ""),
                            "type": col.get("type_text", col.get("type_name", "")),
                            "nullable": col.get("nullable", True),
                            "comment": col.get("comment"),
                        })

                    owner = table.get("owner") or catalog.get("owner")
                    comment = table.get("comment") or ""
                    storage_location = table.get("storage_location", "")
                    data_source_format = table.get("data_source_format", "")
                    created_at = table.get("created_at")
                    updated_at = table.get("updated_at")

                    node = LineageNode(
                        id=asset_id,
                        name=name,
                        fqn=fqn,
                        node_type=node_type,
                        database=db,
                        schema=schema,
                        catalog=db,
                        platform="databricks",
                        platform_domain=PlatformDomain.WAREHOUSE,
                        asset_kind=asset_kind,
                        namespace=namespace,
                        description=comment if comment else None,
                        owner=owner,
                        columns=columns,
                        observed_at=now,
                        sources=[self._id],
                        integration_id=integration_id,
                        raw_metadata={
                            "unity_catalog": {
                                "catalog": catalog_name,
                                "schema": schema_name,
                                "table_type": table_type,
                                "data_source_format": data_source_format,
                                "storage_location": storage_location,
                                "created_at": created_at,
                                "updated_at": updated_at,
                            },
                        },
                    )
                    nodes.append(node)

        logger.info(f"[LiveDatabricks] Discovered {len(nodes)} assets")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract table-level and column-level lineage from Unity Catalog API."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "databricks")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # First discover all tables so we can query lineage for each
        nodes = self.discover_assets(config)
        if not nodes:
            return []

        # Track edges we've already created to avoid duplicates
        seen_edge_keys: Set[str] = set()

        for node in nodes:
            fqn = node.fqn
            # Reconstruct the three-part name for the API
            parts = fqn.split(".")
            if len(parts) != 3:
                continue

            three_part_name = f"{parts[0]}.{parts[1]}.{parts[2]}"

            # -- Table-level lineage --
            table_lineage = self._get_table_lineage(client, three_part_name)
            if table_lineage:
                # Process upstream dependencies
                for upstream in table_lineage.get("upstreams", []):
                    upstream_table = upstream.get("table_info", {})
                    upstream_name = upstream_table.get("name", "")
                    upstream_catalog = upstream_table.get("catalog_name", "")
                    upstream_schema = upstream_table.get("schema_name", "")

                    if not upstream_name:
                        continue

                    src_db = normalize_identifier(upstream_catalog, hint)
                    src_schema = normalize_identifier(upstream_schema, hint)
                    src_name = normalize_identifier(upstream_name, hint)
                    src_container = f"{src_db}.{src_schema}"

                    source_id = generate_asset_id(
                        "warehouse", "databricks", namespace, src_container, src_name,
                    )
                    target_id = node.id

                    edge_key = f"{source_id}|{target_id}|table"
                    if edge_key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(edge_key)

                    source_ref = (
                        f"unity-catalog:table-lineage:{three_part_name}"
                        f":upstream:{src_db}.{src_schema}.{src_name}"
                    )
                    edge = self._make_edge(
                        source_id, target_id,
                        EdgeType.DEPENDS_ON, LineageLevel.TABLE,
                        confidence=0.95,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.DATA,
                    )
                    edges.append(edge)

                # Process downstream dependents
                for downstream in table_lineage.get("downstreams", []):
                    downstream_table = downstream.get("table_info", {})
                    downstream_name = downstream_table.get("name", "")
                    downstream_catalog = downstream_table.get("catalog_name", "")
                    downstream_schema = downstream_table.get("schema_name", "")

                    if not downstream_name:
                        continue

                    tgt_db = normalize_identifier(downstream_catalog, hint)
                    tgt_schema = normalize_identifier(downstream_schema, hint)
                    tgt_name = normalize_identifier(downstream_name, hint)
                    tgt_container = f"{tgt_db}.{tgt_schema}"

                    source_id = node.id
                    target_id = generate_asset_id(
                        "warehouse", "databricks", namespace, tgt_container, tgt_name,
                    )

                    edge_key = f"{source_id}|{target_id}|table"
                    if edge_key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(edge_key)

                    source_ref = (
                        f"unity-catalog:table-lineage:{three_part_name}"
                        f":downstream:{tgt_db}.{tgt_schema}.{tgt_name}"
                    )
                    edge = self._make_edge(
                        source_id, target_id,
                        EdgeType.DEPENDS_ON, LineageLevel.TABLE,
                        confidence=0.95,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.DATA,
                    )
                    edges.append(edge)

            # -- Column-level lineage --
            for col in node.columns:
                col_name = col.get("name", "")
                if not col_name:
                    continue

                column_lineage = self._get_column_lineage(
                    client, three_part_name, col_name,
                )
                if not column_lineage:
                    continue

                upstream_cols = column_lineage.get("upstream_cols", [])
                for upstream_col in upstream_cols:
                    upstream_table_name = upstream_col.get("table_name", "")
                    upstream_col_name = upstream_col.get("name", "")
                    if not upstream_table_name or not upstream_col_name:
                        continue

                    # Parse three-part upstream table name
                    up_parts = upstream_table_name.split(".")
                    if len(up_parts) == 3:
                        up_db = normalize_identifier(up_parts[0], hint)
                        up_schema = normalize_identifier(up_parts[1], hint)
                        up_name = normalize_identifier(up_parts[2], hint)
                    elif len(up_parts) == 2:
                        up_db = normalize_identifier(parts[0], hint)
                        up_schema = normalize_identifier(up_parts[0], hint)
                        up_name = normalize_identifier(up_parts[1], hint)
                    else:
                        continue

                    up_container = f"{up_db}.{up_schema}"
                    source_id = generate_asset_id(
                        "warehouse", "databricks", namespace, up_container, up_name,
                    )
                    target_id = node.id

                    from_col = normalize_identifier(upstream_col_name, hint)
                    to_col = normalize_identifier(col_name, hint)

                    edge_key = f"{source_id}|{target_id}|column|{from_col}|{to_col}"
                    if edge_key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(edge_key)

                    source_ref = (
                        f"unity-catalog:column-lineage:{three_part_name}.{col_name}"
                        f":upstream:{upstream_table_name}.{upstream_col_name}"
                    )
                    column_mapping = ColumnMapping(
                        from_column=from_col,
                        to_column=to_col,
                        confidence=0.9,
                    )

                    ev = Evidence(
                        adapter_id=self._id,
                        source_ref=source_ref,
                        observed_at=now,
                    )
                    edge_id = generate_edge_id(
                        source_id, target_id,
                        EdgeType.DEPENDS_ON.value, LineageLevel.COLUMN.value,
                        source_ref,
                    )
                    edge = LineageEdge(
                        id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                        edge_type=EdgeType.DEPENDS_ON,
                        lineage_level=LineageLevel.COLUMN,
                        confidence=0.9,
                        discovered_from=source_ref,
                        discovered_at=now,
                        evidence=[ev],
                        column_mappings=[column_mapping],
                        plane=LinePlane.DATA,
                    )
                    edges.append(edge)

        logger.info(
            f"[LiveDatabricks] Extracted {len(edges)} edges "
            f"(table + column level)"
        )
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]) -> Optional[Any]:
        """Get or create an httpx.Client for Databricks REST API calls."""
        if config.get("client"):
            return config["client"]

        databricks_config = config.get("databricks_config", {})
        host = databricks_config.get("host", "")
        token = databricks_config.get("token", "")

        if not host:
            logger.warning("[LiveDatabricks] No databricks_config with host provided")
            return None

        if not token:
            logger.warning("[LiveDatabricks] No token in databricks_config")
            return None

        # Ensure host has https:// prefix and no trailing slash
        if not host.startswith("https://") and not host.startswith("http://"):
            host = f"https://{host}"
        host = host.rstrip("/")

        try:
            import httpx
        except ImportError:
            logger.error(
                "[LiveDatabricks] httpx is required for Databricks REST API. "
                "Install with: pip install httpx"
            )
            return None

        client = httpx.Client(
            base_url=host,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        return client

    # ------------------------------------------------------------------
    # Unity Catalog REST API helpers
    # ------------------------------------------------------------------

    def _list_catalogs(self, client: Any) -> List[Dict[str, Any]]:
        """List all catalogs in the Unity Catalog metastore."""
        try:
            resp = client.get("/api/2.1/unity-catalog/catalogs")
            resp.raise_for_status()
            data = resp.json()
            catalogs = data.get("catalogs", [])
            logger.debug(f"[LiveDatabricks] Found {len(catalogs)} catalogs")
            return catalogs
        except Exception as e:
            logger.error(f"[LiveDatabricks] Failed to list catalogs: {e}")
            return []

    def _list_schemas(self, client: Any, catalog_name: str) -> List[Dict[str, Any]]:
        """List schemas in a given catalog."""
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/schemas",
                params={"catalog_name": catalog_name},
            )
            resp.raise_for_status()
            data = resp.json()
            schemas = data.get("schemas", [])
            logger.debug(
                f"[LiveDatabricks] Found {len(schemas)} schemas in {catalog_name}"
            )
            return schemas
        except Exception as e:
            logger.error(
                f"[LiveDatabricks] Failed to list schemas for {catalog_name}: {e}"
            )
            return []

    def _list_tables(
        self, client: Any, catalog_name: str, schema_name: str,
    ) -> List[Dict[str, Any]]:
        """List tables in a given catalog.schema."""
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/tables",
                params={
                    "catalog_name": catalog_name,
                    "schema_name": schema_name,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            tables = data.get("tables", [])
            logger.debug(
                f"[LiveDatabricks] Found {len(tables)} tables in "
                f"{catalog_name}.{schema_name}"
            )
            return tables
        except Exception as e:
            logger.error(
                f"[LiveDatabricks] Failed to list tables for "
                f"{catalog_name}.{schema_name}: {e}"
            )
            return []

    def _get_table_lineage(
        self, client: Any, table_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get table-level lineage from Unity Catalog.

        Args:
            client: httpx.Client
            table_name: Three-part name (catalog.schema.table)
        """
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/lineage/table-lineage",
                params={"table_name": table_name},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(
                f"[LiveDatabricks] No table lineage for {table_name}: {e}"
            )
            return None

    def _get_column_lineage(
        self, client: Any, table_name: str, column_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get column-level lineage from Unity Catalog.

        Args:
            client: httpx.Client
            table_name: Three-part name (catalog.schema.table)
            column_name: Column name to trace lineage for
        """
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/lineage/column-lineage",
                params={
                    "table_name": table_name,
                    "column_name": column_name,
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(
                f"[LiveDatabricks] No column lineage for "
                f"{table_name}.{column_name}: {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Edge helper
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
