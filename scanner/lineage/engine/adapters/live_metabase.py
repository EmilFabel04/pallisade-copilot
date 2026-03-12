"""
Live Metabase Adapter — extracts lineage from Metabase dashboards.

Discovers dashboards as DASHBOARD nodes on the BI domain, then creates
cross-plane edges from dashboards to warehouse tables via the cards
(saved questions) each dashboard contains. Cards are not emitted as
separate nodes — they are intermediate and only used to trace which
tables a dashboard depends on.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

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

# Map Metabase engine names to our warehouse platform identifiers
_ENGINE_TO_PLATFORM = {
    "bigquery-cloud-sdk": "bigquery",
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "postgres": "postgres",
    "redshift": "redshift",
    "mysql": "mysql",
    "sqlserver": "sqlserver",
    "databricks": "databricks",
}


def _extract_real_db_name(db: Dict[str, Any], engine: str) -> Optional[str]:
    """
    Extract the real database/project identifier from Metabase database details.

    This is needed because Metabase's display name (e.g., "Acme") differs
    from the actual warehouse identifier (e.g., "pallisade-demo" for BigQuery).
    The warehouse adapter uses the real identifier for asset ID generation.
    """
    details = db.get("details", {})
    if not isinstance(details, dict):
        return None

    if engine in ("bigquery-cloud-sdk", "bigquery"):
        return details.get("project-id") or details.get("project_id")
    elif engine == "snowflake":
        return details.get("account") or details.get("db")
    elif engine in ("postgres", "redshift"):
        return details.get("dbname") or details.get("db")
    elif engine == "mysql":
        return details.get("dbname") or details.get("db")
    elif engine == "databricks":
        return details.get("catalog") or details.get("db")

    return None


class LiveMetabaseAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Metabase dashboards and extracts lineage
    to warehouse tables through the cards each dashboard contains.

    Config keys:
        namespace: Identifier for this Metabase instance (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        metabase_config: Dict with host and api_key
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
        """Discover Metabase dashboards only (cards are intermediate)."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "metabase")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        try:
            dashboards = client.get_dashboards()
        except Exception as e:
            logger.error(f"[LiveMetabase] Failed to get dashboards: {e}")
            dashboards = []

        for dash in dashboards:
            if dash.get("archived"):
                continue
            node = self._make_dashboard_node(dash, namespace, integration_id, now)
            if node:
                nodes.append(node)

        logger.info(f"[LiveMetabase] Discovered {len(nodes)} dashboard assets")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """
        Extract dashboard → warehouse table edges.

        For each dashboard, fetches its cards. For each card, resolves
        the underlying warehouse table(s) and creates a cross-plane edge
        from the dashboard to each table.
        """
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "metabase")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Build Metabase table_id → (platform, db, schema, table) lookup
        table_lookup = self._build_table_lookup(client, config)

        # Get dashboards
        try:
            dashboards = client.get_dashboards()
        except Exception:
            dashboards = []

        for dash in dashboards:
            dash_id = dash.get("id")
            if dash_id is None or dash.get("archived"):
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

            ordered_cards = full_dash.get("ordered_cards", full_dash.get("dashcards", []))
            logger.info(f"[LiveMetabase] Dashboard {dash_id}: {len(ordered_cards)} cards")
            seen_tables: Set[str] = set()  # Deduplicate table edges per dashboard

            seen_card_ids: Set[int] = set()
            for dash_card in ordered_cards:
                card_info = dash_card.get("card", {})
                card_id = card_info.get("id")
                if card_id is None or card_id in seen_card_ids:
                    continue
                seen_card_ids.add(card_id)

                # Dashboard endpoint often omits dataset_query from card objects.
                # Always fetch the full card to get complete dataset_query.
                try:
                    full_card = client.get_card(card_id)
                    dataset_query = full_card.get("dataset_query", {})
                    card_info = full_card  # Use full card info
                except Exception as e:
                    logger.warning(f"[LiveMetabase] Failed to fetch card {card_id}: {e}")
                    # Fall back to dashboard card info
                    dataset_query = card_info.get("dataset_query", {})

                logger.debug(
                    f"[LiveMetabase] Card {card_id} ({card_info.get('name', '?')}): "
                    f"database={dataset_query.get('database', 'N/A')}"
                )
                table_refs = self._resolve_card_tables(
                    dataset_query, table_lookup, client, hint, card_info=card_info,
                )
                logger.debug(f"[LiveMetabase] Card {card_id}: resolved {len(table_refs)} table refs")

                for platform, db_name, schema_name, table_name, confidence, source_detail in table_refs:
                    # Build the same asset ID that the warehouse adapter would generate.
                    # The warehouse adapter uses the real DB identifier (e.g., BigQuery project ID)
                    # as BOTH the namespace and part of the container.
                    container = f"{db_name}.{schema_name}"
                    wh_namespace = db_name  # e.g., "pallisade-demo" for BigQuery
                    table_asset_id = generate_asset_id(
                        "warehouse", platform, wh_namespace, container, table_name,
                    )
                    # Deduplicate: one edge per dashboard→table pair
                    edge_key = f"{dash_asset_id}:{table_asset_id}"
                    if edge_key in seen_tables:
                        continue
                    seen_tables.add(edge_key)

                    source_ref = f"metabase:dashboard:{dash_id}:card:{card_id}:{source_detail}"
                    edge = self._make_edge(
                        table_asset_id, dash_asset_id,
                        EdgeType.READS_FROM, LineageLevel.TABLE,
                        confidence=confidence,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                    edges.append(edge)

        logger.info(f"[LiveMetabase] Extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Table ID resolution
    # ------------------------------------------------------------------

    def _build_table_lookup(
        self, client: Any, config: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Tuple[str, str, str, str]]:
        """
        Build a lookup from Metabase internal table_id to
        (platform, database_name, schema_name, table_name).

        Calls /api/database for each non-sample database, then
        /api/database/:id/metadata to get all tables with their
        real names.
        """
        lookup: Dict[int, Tuple[str, str, str, str]] = {}

        try:
            databases_resp = client.get_databases()
        except Exception as e:
            logger.warning(f"[LiveMetabase] Failed to list databases: {e}")
            return lookup

        # /api/database returns {"data": [...]} or a bare list depending on version
        if isinstance(databases_resp, dict):
            databases = databases_resp.get("data", databases_resp.get("databases", []))
            # If it's a dict but has "id"/"engine" keys, it might be a single DB object
            if not databases and "id" in databases_resp:
                databases = [databases_resp]
        elif isinstance(databases_resp, list):
            databases = databases_resp
        else:
            logger.warning(f"[LiveMetabase] Unexpected databases response type: {type(databases_resp)}")
            return lookup

        logger.info(f"[LiveMetabase] Found {len(databases)} databases to scan")

        for db in databases:
            if not isinstance(db, dict):
                logger.warning(f"[LiveMetabase] Skipping non-dict database entry: {type(db)} = {db!r}")
                continue

            db_id = db.get("id")
            if db_id is None or db.get("is_sample"):
                logger.info(f"[LiveMetabase] Skipping database {db.get('name', '?')}: id={db_id}, is_sample={db.get('is_sample')}")
                continue

            engine = db.get("engine", "")
            platform = _ENGINE_TO_PLATFORM.get(engine, engine)
            display_name = db.get("name", "")

            # Use the real warehouse identifier (e.g., BigQuery project ID)
            # instead of Metabase's display name, so asset IDs match the warehouse adapter
            real_db_name = _extract_real_db_name(db, engine)
            if not real_db_name:
                # /api/database list may not include details — fetch full DB object
                try:
                    full_db = client.get_database(db_id)
                    real_db_name = _extract_real_db_name(full_db, engine)
                except Exception:
                    pass
            db_name = real_db_name or display_name

            logger.info(
                f"[LiveMetabase] Scanning database {db_id} ({display_name}): "
                f"engine={engine}, platform={platform}, real_db={real_db_name}"
            )

            try:
                metadata = client.get_database_metadata(db_id)
            except Exception as e:
                logger.warning(f"[LiveMetabase] Failed to get metadata for database {db_id}: {e}")
                continue

            # metadata response has "tables" key with list of table objects
            tables_list = metadata.get("tables", []) if isinstance(metadata, dict) else []
            logger.info(f"[LiveMetabase] Database {db_id} ({db_name}): found {len(tables_list)} tables")

            for table in tables_list:
                table_id = table.get("id")
                if table_id is None:
                    continue

                schema = table.get("schema", "")
                name = table.get("name", "")
                lookup[table_id] = (platform, db_name, schema, name)

        logger.info(f"[LiveMetabase] Built table lookup with {len(lookup)} entries (from databases)")

        # If database-based lookup found nothing, try alternative endpoints
        if not lookup:
            self._try_table_list_endpoint(client, lookup)
        if not lookup:
            self._try_search_endpoint(client, lookup)

        logger.info(f"[LiveMetabase] Final table lookup: {len(lookup)} entries")
        return lookup

    def _try_table_list_endpoint(
        self, client: Any, lookup: Dict[int, Tuple[str, str, str, str]],
    ) -> None:
        """Try /api/table to list all tables (may work when /api/database is restricted)."""
        try:
            tables_resp = client._request("GET", "/table")
            tables = tables_resp if isinstance(tables_resp, list) else []
            logger.info(f"[LiveMetabase] /api/table returned {len(tables)} tables")

            for table in tables:
                if not isinstance(table, dict):
                    continue
                table_id = table.get("id")
                if table_id is None:
                    continue

                db_info = table.get("db", {}) or {}
                if db_info.get("is_sample"):
                    continue

                engine = db_info.get("engine", "")
                platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                db_name = db_info.get("name", "")
                schema = table.get("schema", "")
                name = table.get("name", "")

                if name:
                    lookup[table_id] = (platform, db_name, schema, name)
                    logger.info(
                        f"[LiveMetabase] /api/table: mapped table_id {table_id} → "
                        f"{platform}:{db_name}.{schema}.{name}"
                    )
        except Exception as e:
            logger.info(f"[LiveMetabase] /api/table endpoint not accessible: {e}")

    def _try_search_endpoint(
        self, client: Any, lookup: Dict[int, Tuple[str, str, str, str]],
    ) -> None:
        """Try /api/search?models=table to find tables via search API."""
        try:
            search_resp = client._request("GET", "/search", params={"models": "table", "limit": 100})
            data = search_resp
            if isinstance(search_resp, dict):
                data = search_resp.get("data", search_resp.get("results", []))
            if not isinstance(data, list):
                return

            logger.info(f"[LiveMetabase] /api/search returned {len(data)} table results")

            for item in data:
                if not isinstance(item, dict) or item.get("model") != "table":
                    continue
                table_id = item.get("id")
                if table_id is None:
                    continue

                # Search results have database_id, table_schema, name
                db_id = item.get("database_id")
                engine = item.get("database_engine", "")
                db_name = item.get("database_name", "")
                platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                schema = item.get("table_schema", "")
                name = item.get("name", item.get("table_name", ""))

                if name:
                    lookup[table_id] = (platform, db_name, schema, name)
                    logger.info(
                        f"[LiveMetabase] /api/search: mapped table_id {table_id} → "
                        f"{platform}:{db_name}.{schema}.{name}"
                    )
        except Exception as e:
            logger.info(f"[LiveMetabase] /api/search endpoint not accessible: {e}")

    def _resolve_card_tables(
        self,
        dataset_query: Dict[str, Any],
        table_lookup: Dict[int, Tuple[str, str, str, str]],
        client: Any,
        hint: str,
        card_info: Optional[Dict] = None,
    ) -> List[Tuple[str, str, str, str, float, str]]:
        """
        Resolve a card's dataset_query to a list of
        (platform, db, schema, table, confidence, source_detail) tuples.

        Handles both old format (type/query) and new MBQL format (lib/type/stages).
        """
        # Detect query format: old ("type": "query"/"native") vs new MBQL ("lib/type": "mbql/query")
        query_type = dataset_query.get("type")
        lib_type = dataset_query.get("lib/type", "")
        results: List[Tuple[str, str, str, str, float, str]] = []

        # Extract source-table from either format
        source_table_id = None
        if lib_type.startswith("mbql/"):
            # New MBQL format: stages[0]["source-table"]
            stages = dataset_query.get("stages", [])
            if stages and isinstance(stages[0], dict):
                source_table_id = stages[0].get("source-table")
        elif query_type == "query":
            # Old format: query["source-table"]
            source_table_id = dataset_query.get("query", {}).get("source-table")
        elif query_type == "native":
            # Native SQL — parse to find table references
            native_query = dataset_query.get("native", {}).get("query", "")
            if not native_query:
                return results

            # Infer platform from the database ID
            db_id = dataset_query.get("database")
            inferred_platform = "unknown"
            inferred_db = ""
            if table_lookup:
                for _, (p, d, _s, _t) in table_lookup.items():
                    inferred_platform = p
                    inferred_db = d
                    break
            if inferred_platform == "unknown" and db_id and isinstance(db_id, int):
                try:
                    db_meta = client._request("GET", f"/database/{db_id}")
                    if isinstance(db_meta, dict):
                        engine = db_meta.get("engine", "")
                        inferred_platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                        inferred_db = db_meta.get("name", "")
                        logger.info(f"[LiveMetabase] Resolved database {db_id}: engine={engine}, platform={inferred_platform}, name={inferred_db}")
                except Exception:
                    pass

            table_refs = self._extract_table_refs_from_sql(native_query)
            for table_ref in table_refs:
                parts = table_ref.split(".")
                name = normalize_identifier(parts[-1], hint)
                schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
                db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else normalize_identifier(inferred_db, hint)
                results.append((inferred_platform, db, schema, name, 0.8, f"native_query:reads:{table_ref}"))
            return results

        # Fallback: try card's top-level table_id field
        if source_table_id is None and card_info:
            source_table_id = card_info.get("table_id")

        if source_table_id is None:
            logger.debug(f"[LiveMetabase] No source-table found in dataset_query")
            return results

        # Resolve the source table ID
        table_id = source_table_id
        logger.debug(f"[LiveMetabase] Resolving source-table={table_id}")

        if isinstance(table_id, int) and table_id in table_lookup:
            platform, db_name, schema, name = table_lookup[table_id]
            results.append((
                platform,
                normalize_identifier(db_name, hint),
                normalize_identifier(schema, hint),
                normalize_identifier(name, hint),
                0.9,
                f"gui_query:table_id:{table_id}",
            ))
        elif isinstance(table_id, int):
            resolved = False

            # Strategy 1: /api/table/:id (skip if previously failed)
            if table_id not in self._failed_table_ids:
                try:
                    table_meta = client.get_table(table_id)
                    db_info = table_meta.get("db", {}) or {}
                    engine = db_info.get("engine", "")
                    platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                    db_name = db_info.get("name", "")
                    schema = table_meta.get("schema", "")
                    name = table_meta.get("name", "")
                    logger.info(
                        f"[LiveMetabase] Resolved table_id {table_id} via /api/table: "
                        f"{db_name}.{schema}.{name} (engine={engine}, platform={platform})"
                    )
                    table_lookup[table_id] = (platform, db_name, schema, name)
                    results.append((
                        platform,
                        normalize_identifier(db_name, hint),
                        normalize_identifier(schema, hint),
                        normalize_identifier(name, hint),
                        0.9,
                        f"gui_query:table_id:{table_id}",
                    ))
                    resolved = True
                except Exception:
                    self._failed_table_ids.add(table_id)
                    logger.debug(f"[LiveMetabase] /api/table/{table_id} failed, trying fallbacks")

            # Strategy 2: /api/database/:id/metadata (populate lookup from the card's database)
            if not resolved:
                db_id = dataset_query.get("database")
                if db_id and isinstance(db_id, int):
                    resolved = self._populate_lookup_from_database(client, db_id, table_lookup)
                    if table_id in table_lookup:
                        platform, db_name, schema, name = table_lookup[table_id]
                        results.append((
                            platform,
                            normalize_identifier(db_name, hint),
                            normalize_identifier(schema, hint),
                            normalize_identifier(name, hint),
                            0.9,
                            f"gui_query:table_id:{table_id}",
                        ))
                        resolved = True

            # Strategy 3: try /api/field/:id for field refs in the MBQL query or result_metadata
            if not resolved:
                field_result = self._resolve_table_via_fields(dataset_query, client, hint, table_id, card_info=card_info)
                if field_result:
                    results.append(field_result)
                    resolved = True

            # Strategy 4: try /api/card/:id/query_metadata
            if not resolved and card_info:
                card_id_val = card_info.get("id")
                if card_id_val:
                    qm_result = self._resolve_table_via_query_metadata(client, card_id_val, hint, table_id)
                    if qm_result:
                        results.append(qm_result)
                        resolved = True

            # Strategy 5: extract from card's result_metadata column info
            if not resolved and card_info:
                table_name = self._infer_table_from_card(card_info, dataset_query, client)
                if table_name:
                    results.append(table_name + (0.7, f"gui_query:table_id:{table_id}:inferred"))
                    resolved = True

            if not resolved and not results:
                logger.warning(f"[LiveMetabase] Could not resolve table_id {table_id} by any method")

        # Also check joins (old format)
        joins = dataset_query.get("query", {}).get("joins", [])
        for join in joins:
            join_table_id = join.get("source-table")
            if isinstance(join_table_id, int) and join_table_id in table_lookup:
                platform, db_name, schema, name = table_lookup[join_table_id]
                results.append((
                    platform,
                    normalize_identifier(db_name, hint),
                    normalize_identifier(schema, hint),
                    normalize_identifier(name, hint),
                    0.85,
                    f"gui_query:join_table_id:{join_table_id}",
                ))

        return results

    # ------------------------------------------------------------------
    # Table resolution helpers
    # ------------------------------------------------------------------

    _probed_databases: Set[int] = set()

    def _populate_lookup_from_database(
        self,
        client: Any,
        db_id: int,
        table_lookup: Dict[int, Tuple[str, str, str, str]],
    ) -> bool:
        """Try to populate the table lookup from /api/database/:id/metadata."""
        if db_id in self._probed_databases:
            return False
        self._probed_databases.add(db_id)

        try:
            # First get database info for engine/name
            db_meta = client._request("GET", f"/database/{db_id}")
            if not isinstance(db_meta, dict):
                return False

            engine = db_meta.get("engine", "")
            platform = _ENGINE_TO_PLATFORM.get(engine, engine)
            db_name = db_meta.get("name", "")
            logger.info(f"[LiveMetabase] Database {db_id}: engine={engine}, platform={platform}, name={db_name}")

            # Now get table metadata
            metadata = client.get_database_metadata(db_id)
            tables_list = metadata.get("tables", []) if isinstance(metadata, dict) else []
            logger.info(f"[LiveMetabase] Database {db_id}: found {len(tables_list)} tables via metadata")

            for table in tables_list:
                tid = table.get("id")
                if tid is not None:
                    table_lookup[tid] = (platform, db_name, table.get("schema", ""), table.get("name", ""))

            return len(tables_list) > 0
        except Exception as e:
            logger.warning(f"[LiveMetabase] Could not fetch database {db_id} metadata: {e}")
            return False

    _failed_table_ids: Set[int] = set()
    _failed_field_ids: Set[int] = set()

    def _resolve_table_via_fields(
        self,
        dataset_query: Dict[str, Any],
        client: Any,
        hint: str,
        table_id: int,
        card_info: Optional[Dict] = None,
    ) -> Optional[Tuple[str, str, str, str, float, str]]:
        """
        Strategy 3: Extract field IDs from the MBQL query and/or result_metadata,
        then call /api/field/:id. Field metadata often includes the table name
        even when /api/table is 403.
        """
        field_ids: List[int] = []

        # Extract field refs from MBQL stages
        lib_type = dataset_query.get("lib/type", "")
        if lib_type.startswith("mbql/"):
            stages = dataset_query.get("stages", [])
            self._collect_field_ids(stages, field_ids)
        else:
            query = dataset_query.get("query", {})
            self._collect_field_ids(query, field_ids)

        # Also extract field IDs from result_metadata (each column has an "id" field)
        if card_info:
            rm = card_info.get("result_metadata", [])
            if isinstance(rm, list):
                for col in rm:
                    if isinstance(col, dict):
                        fid = col.get("id")
                        if isinstance(fid, int):
                            field_ids.append(fid)

        logger.debug(f"[LiveMetabase] Strategy 3: extracted {len(field_ids)} field IDs: {field_ids[:5]}")

        # Deduplicate and try each field
        seen: Set[int] = set()
        for fid in field_ids:
            if fid in seen or fid in self._failed_field_ids:
                continue
            seen.add(fid)

            try:
                field_meta = client._request("GET", f"/field/{fid}")
                if not isinstance(field_meta, dict):
                    continue

                tbl = field_meta.get("table", {})
                if isinstance(tbl, dict) and tbl.get("name"):
                    db_info = tbl.get("db", {}) or {}
                    engine = db_info.get("engine", "")
                    platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                    db_name = db_info.get("name", "")
                    schema = tbl.get("schema", "")
                    name = tbl.get("name", "")

                    logger.info(
                        f"[LiveMetabase] Resolved table_id {table_id} via /api/field/{fid}: "
                        f"{db_name}.{schema}.{name} (platform={platform})"
                    )
                    return (
                        platform,
                        normalize_identifier(db_name, hint),
                        normalize_identifier(schema, hint),
                        normalize_identifier(name, hint),
                        0.85,
                        f"gui_query:table_id:{table_id}:via_field:{fid}",
                    )

                # Field exists but no table info — try table_id from field
                field_table_id = field_meta.get("table_id")
                if isinstance(field_table_id, int) and field_table_id != table_id:
                    # Different table_id — might be resolvable
                    logger.debug(f"[LiveMetabase] Field {fid} points to table_id {field_table_id}")

            except Exception:
                self._failed_field_ids.add(fid)
                logger.debug(f"[LiveMetabase] /api/field/{fid} failed")

        return None

    def _collect_field_ids(self, obj: Any, field_ids: List[int]) -> None:
        """Recursively extract integer field IDs from MBQL query structures.

        Handles both formats:
          Old: ["field", <int_id>, {opts}]
          MBQL v2: ["field", {opts}, <int_id>]
        """
        if isinstance(obj, list):
            if len(obj) >= 2 and obj[0] in ("field", "Field"):
                # Old format: ["field", 304, {...}]
                if isinstance(obj[1], int):
                    field_ids.append(obj[1])
                # MBQL v2 format: ["field", {...}, 304]
                elif len(obj) >= 3 and isinstance(obj[1], dict) and isinstance(obj[2], int):
                    field_ids.append(obj[2])
            for item in obj:
                self._collect_field_ids(item, field_ids)
        elif isinstance(obj, dict):
            for v in obj.values():
                self._collect_field_ids(v, field_ids)

    def _resolve_table_via_query_metadata(
        self,
        client: Any,
        card_id: int,
        hint: str,
        table_id: int,
    ) -> Optional[Tuple[str, str, str, str, float, str]]:
        """
        Strategy 4: Use /api/card/:id/query_metadata which may return
        table info even when /api/table/:id is restricted.
        """
        try:
            qm = client.get_card_query_metadata(card_id)
            if not isinstance(qm, dict):
                return None

            tables = qm.get("tables", [])
            for tbl in tables:
                if not isinstance(tbl, dict):
                    continue
                # Match by table_id or just use first table
                tbl_id = tbl.get("id")
                if tbl_id == table_id or (not tbl_id and tbl.get("name")):
                    db_info = tbl.get("db", {}) or {}
                    engine = db_info.get("engine", "")
                    platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                    db_name = db_info.get("name", "")
                    schema = tbl.get("schema", "")
                    name = tbl.get("name", "")

                    if name:
                        logger.info(
                            f"[LiveMetabase] Resolved table_id {table_id} via /card/{card_id}/query_metadata: "
                            f"{db_name}.{schema}.{name} (platform={platform})"
                        )
                        return (
                            platform,
                            normalize_identifier(db_name, hint),
                            normalize_identifier(schema, hint),
                            normalize_identifier(name, hint),
                            0.85,
                            f"gui_query:table_id:{table_id}:via_query_metadata",
                        )
        except Exception as e:
            logger.debug(f"[LiveMetabase] /card/{card_id}/query_metadata failed: {e}")

        return None

    def _infer_table_from_card(
        self,
        card_info: Dict[str, Any],
        dataset_query: Dict[str, Any],
        client: Any,
    ) -> Optional[Tuple[str, str, str, str]]:
        """
        Last-resort: try to infer the table from card metadata.

        Checks result_metadata columns for table_name, display_name,
        field_ref, or other hints about the source table.
        """
        db_id = dataset_query.get("database") or card_info.get("database_id")

        # Try to get the database engine at least (skip if already failed)
        platform = "unknown"
        db_name = ""
        if db_id and isinstance(db_id, int) and db_id not in self._probed_databases:
            try:
                db_meta = client._request("GET", f"/database/{db_id}")
                if isinstance(db_meta, dict):
                    engine = db_meta.get("engine", "")
                    platform = _ENGINE_TO_PLATFORM.get(engine, engine)
                    db_name = db_meta.get("name", "")
            except Exception:
                pass

        # Check result_metadata for table_name hints
        result_meta = card_info.get("result_metadata", [])
        if isinstance(result_meta, list):
            for col in result_meta:
                if not isinstance(col, dict):
                    continue

                # Direct table_name field (some Metabase versions)
                table_name = col.get("table_name")
                schema_name = col.get("schema_name", "")
                if table_name:
                    logger.info(
                        f"[LiveMetabase] Inferred table from result_metadata.table_name: "
                        f"{db_name}.{schema_name}.{table_name} (platform={platform})"
                    )
                    return (platform, db_name, schema_name, table_name)

                # Check field_ref for table reference: ["field", <name>, {"base-type": ..., "source-alias": ...}]
                field_ref = col.get("field_ref")
                if isinstance(field_ref, list) and len(field_ref) >= 3:
                    opts = field_ref[2] if isinstance(field_ref[2], dict) else {}
                    source_alias = opts.get("source-alias") or opts.get("join-alias")
                    if source_alias:
                        logger.info(f"[LiveMetabase] Found source-alias in field_ref: {source_alias}")

                # Check display_name for "TABLE → COLUMN" pattern (Metabase join columns)
                display = col.get("display_name", "")
                if " → " in display:
                    table_part = display.split(" → ")[0].strip()
                    logger.info(f"[LiveMetabase] Found table hint in display_name: {table_part}")

        # Check if card has embedded table object (some Metabase versions)
        table_obj = card_info.get("table")
        if isinstance(table_obj, dict) and table_obj.get("name"):
            db_info = table_obj.get("db", {}) or {}
            engine = db_info.get("engine", "")
            if engine:
                platform = _ENGINE_TO_PLATFORM.get(engine, engine)
            db_name = db_info.get("name", "") or db_name
            schema = table_obj.get("schema", "")
            name = table_obj.get("name", "")
            logger.info(
                f"[LiveMetabase] Inferred table from card.table object: "
                f"{db_name}.{schema}.{name} (platform={platform})"
            )
            return (platform, db_name, schema, name)

        return None

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
            api_key=metabase_config.get("api_key"),
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
