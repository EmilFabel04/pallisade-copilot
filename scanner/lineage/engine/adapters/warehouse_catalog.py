"""
Warehouse Catalog Adapter

Reads INFORMATION_SCHEMA-like JSON fixtures describing tables, views,
columns, and optionally view definitions.  Emits asset nodes and
table-level lineage when view SQL can be parsed.

Expected fixture schema::

    {
      "metadata": {"system": "postgres", "namespace": "acme-prod", "case_hint": "lower"},
      "tables": [
        {
          "database": "warehouse",
          "schema": "public",
          "name": "users",
          "type": "table",
          "row_count": 50000,
          "owner": "dba",
          "columns": [
            {"name": "id", "type": "integer", "nullable": false},
            {"name": "email", "type": "varchar(255)", "nullable": true}
          ]
        },
        {
          "database": "warehouse",
          "schema": "public",
          "name": "active_users_v",
          "type": "view",
          "view_definition": "SELECT id, email FROM public.users WHERE active = true",
          "columns": [...]
        }
      ]
    }
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Set

from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id, normalize_identifier
from ...graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    NodeType,
    PlatformDomain,
)

logger = logging.getLogger(__name__)


class WarehouseCatalogAdapter(BaseLineageAdapter):
    """Adapter that reads warehouse catalog/information-schema fixtures."""

    def __init__(self, adapter_id: str, path: str = "", **kwargs):
        self._id = adapter_id
        self._path = path
        self._catalog: Dict[str, Any] = {}

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        caps = {Capability.DISCOVER_ASSETS}
        # We can extract table lineage if any view has a view_definition
        for tbl in self._catalog.get("tables", []):
            if tbl.get("view_definition"):
                caps.add(Capability.EXTRACT_TABLE_LINEAGE)
                break
        return caps

    @property
    def case_hint(self) -> str:
        return self._catalog.get("metadata", {}).get("case_hint", "lower")

    def _load(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if self._catalog:
            return self._catalog
        path = config.get("path", self._path)
        if path:
            with open(path) as f:
                self._catalog = json.load(f)
        elif "catalog" in config:
            self._catalog = config["catalog"]
        else:
            raise ValueError("WarehouseCatalogAdapter requires 'path' or 'catalog' in config")
        return self._catalog

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        catalog = self._load(config)
        meta = catalog.get("metadata", {})
        system = meta.get("system", "warehouse")
        namespace = meta.get("namespace", "")
        hint = self.case_hint
        nodes: List[LineageNode] = []

        for tbl in catalog.get("tables", []):
            db = normalize_identifier(tbl.get("database", ""), hint)
            schema = normalize_identifier(tbl.get("schema", ""), hint)
            name = normalize_identifier(tbl["name"], hint)
            container = f"{db}.{schema}" if db else schema
            tbl_type = tbl.get("type", "table").lower()

            node_id = generate_asset_id("warehouse", system, namespace, container, name)
            fqn_parts = [p for p in [db, schema, name] if p]

            if tbl_type == "view":
                node_type = NodeType.VIEW
                asset_kind = AssetKind.VIEW
            elif tbl_type == "materialized_view":
                node_type = NodeType.MATERIALIZED_VIEW
                asset_kind = AssetKind.VIEW
            else:
                node_type = NodeType.TABLE
                asset_kind = AssetKind.TABLE

            columns = [
                {
                    "name": c["name"],
                    "type": c.get("type", "unknown"),
                    "nullable": c.get("nullable", True),
                }
                for c in tbl.get("columns", [])
            ]

            raw_meta: Dict[str, Any] = {}
            if tbl.get("view_definition"):
                raw_meta["view_definition"] = tbl["view_definition"]

            nodes.append(LineageNode(
                id=node_id,
                name=name,
                fqn=".".join(fqn_parts),
                node_type=node_type,
                database=db,
                schema=schema,
                platform=system,
                platform_domain=PlatformDomain.WAREHOUSE,
                asset_kind=asset_kind,
                namespace=namespace,
                owner=tbl.get("owner"),
                row_count=tbl.get("row_count"),
                columns=columns,
                sources=[self._id],
                observed_at=datetime.utcnow(),
                raw_metadata=raw_meta,
            ))

        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        catalog = self._load(config)
        meta = catalog.get("metadata", {})
        system = meta.get("system", "warehouse")
        namespace = meta.get("namespace", "")
        hint = self.case_hint
        edges: List[LineageEdge] = []
        now = datetime.utcnow()

        # Build name->id lookup for resolution
        name_to_id: Dict[str, str] = {}
        for tbl in catalog.get("tables", []):
            db = normalize_identifier(tbl.get("database", ""), hint)
            schema = normalize_identifier(tbl.get("schema", ""), hint)
            name = normalize_identifier(tbl["name"], hint)
            container = f"{db}.{schema}" if db else schema
            node_id = generate_asset_id("warehouse", system, namespace, container, name)

            # Register multiple lookup forms
            name_to_id[name] = node_id
            if schema:
                name_to_id[f"{schema}.{name}"] = node_id
            if db and schema:
                name_to_id[f"{db}.{schema}.{name}"] = node_id

        # Parse view definitions to extract table references
        for tbl in catalog.get("tables", []):
            view_sql = tbl.get("view_definition")
            if not view_sql:
                continue

            db = normalize_identifier(tbl.get("database", ""), hint)
            schema = normalize_identifier(tbl.get("schema", ""), hint)
            name = normalize_identifier(tbl["name"], hint)
            container = f"{db}.{schema}" if db else schema
            view_id = generate_asset_id("warehouse", system, namespace, container, name)

            # Use the existing universal SQL parser
            try:
                from ...parser import UniversalLineageParser
                parser = UniversalLineageParser(default_dialect=system)
                info = parser.parse_query(view_sql, dialect=system)
                source_tables = info.sources
            except Exception as e:
                logger.debug(f"SQL parse failed for view {name}: {e}")
                source_tables = []

            for src_ref in source_tables:
                src_ref_norm = normalize_identifier(src_ref, hint)
                source_id = name_to_id.get(src_ref_norm)

                # Try with schema prefix if bare name didn't match
                if not source_id and schema:
                    source_id = name_to_id.get(f"{schema}.{src_ref_norm}")
                if not source_id and db and schema:
                    source_id = name_to_id.get(f"{db}.{schema}.{src_ref_norm}")

                if not source_id:
                    logger.debug(f"Unresolved view dependency: {src_ref} for view {name}")
                    continue

                evidence_ref = f"view_def:{name}:{src_ref_norm}"
                edge_id = generate_edge_id(source_id, view_id, "depends_on", "table", evidence_ref)

                snippet = view_sql[:200] if view_sql else ""

                edges.append(LineageEdge(
                    id=edge_id,
                    source_id=source_id,
                    target_id=view_id,
                    edge_type=EdgeType.DEPENDS_ON,
                    confidence=0.8,
                    discovered_from=self._id,
                    discovered_at=now,
                    lineage_level=LineageLevel.TABLE,
                    evidence=[Evidence(
                        adapter_id=self._id,
                        source_ref=evidence_ref,
                        observed_at=now,
                        snippet=snippet,
                    )],
                ))

        return edges
