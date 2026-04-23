"""
BI Query Adapter

Reads BI tool export JSON fixtures describing dashboards, datasets, tiles,
and SQL queries.  Emits:
- Tool-level edges: dashboard -> dataset
- Table-level edges: dataset/query -> referenced warehouse tables
- Column-level edges: ONLY when SQL AST supports safe, unambiguous mapping

Expected fixture schema::

    {
      "metadata": {"system": "looker", "namespace": "acme-prod", "case_hint": "lower"},
      "dashboards": [
        {
          "name": "Revenue Dashboard",
          "owner": "finance-team",
          "tiles": ["monthly_revenue", "daily_signups"]
        }
      ],
      "datasets": [
        {
          "name": "monthly_revenue",
          "sql": "SELECT DATE_TRUNC('month', created_at) AS month, SUM(amount) AS total FROM payments GROUP BY 1",
          "tables": ["public.payments"],
          "columns": [
            {"name": "month", "source_column": "created_at", "source_table": "public.payments"},
            {"name": "total", "source_column": "amount", "source_table": "public.payments"}
          ]
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
    ColumnMapping,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    NodeType,
    PlatformDomain,
)

logger = logging.getLogger(__name__)


class BIQueryAdapter(BaseLineageAdapter):
    """Adapter that reads BI tool export fixtures."""

    def __init__(self, adapter_id: str, path: str = "", **kwargs):
        self._id = adapter_id
        self._path = path
        self._export: Dict[str, Any] = {}

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        caps = {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
        }
        # Column lineage only if datasets have explicit column mappings
        for ds in self._export.get("datasets", []):
            if ds.get("columns"):
                caps.add(Capability.EXTRACT_COLUMN_LINEAGE)
                break
        return caps

    @property
    def case_hint(self) -> str:
        return self._export.get("metadata", {}).get("case_hint", "lower")

    def _load(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if self._export:
            return self._export
        path = config.get("path", self._path)
        if path:
            with open(path) as f:
                self._export = json.load(f)
        elif "export" in config:
            self._export = config["export"]
        else:
            raise ValueError("BIQueryAdapter requires 'path' or 'export' in config")
        return self._export

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        export = self._load(config)
        meta = export.get("metadata", {})
        system = meta.get("system", "bi")
        namespace = meta.get("namespace", "")
        hint = self.case_hint
        nodes: List[LineageNode] = []

        # Dashboards
        for dash in export.get("dashboards", []):
            name = normalize_identifier(dash["name"], hint)
            node_id = generate_asset_id("bi", system, namespace, "dashboards", name)

            nodes.append(LineageNode(
                id=node_id,
                name=name,
                fqn=f"{system}.dashboards.{name}",
                node_type=NodeType.DASHBOARD,
                platform=system,
                platform_domain=PlatformDomain.BI,
                asset_kind=AssetKind.DASHBOARD,
                namespace=namespace,
                owner=dash.get("owner"),
                tags=dash.get("tags", []),
                sources=[self._id],
                observed_at=datetime.utcnow(),
                raw_metadata={"tiles": dash.get("tiles", [])},
            ))

        # Datasets
        for ds in export.get("datasets", []):
            name = normalize_identifier(ds["name"], hint)
            node_id = generate_asset_id("bi", system, namespace, "datasets", name)

            columns = [
                {"name": c["name"], "type": c.get("type", "unknown")}
                for c in ds.get("columns", [])
            ]

            raw_meta: Dict[str, Any] = {}
            if ds.get("sql"):
                raw_meta["sql"] = ds["sql"]
            if ds.get("tables"):
                raw_meta["table_references"] = ds["tables"]

            nodes.append(LineageNode(
                id=node_id,
                name=name,
                fqn=f"{system}.datasets.{name}",
                node_type=NodeType.DATASET,
                platform=system,
                platform_domain=PlatformDomain.BI,
                asset_kind=AssetKind.DATASET,
                namespace=namespace,
                columns=columns,
                sources=[self._id],
                observed_at=datetime.utcnow(),
                raw_metadata=raw_meta,
            ))

        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        export = self._load(config)
        meta = export.get("metadata", {})
        system = meta.get("system", "bi")
        namespace = meta.get("namespace", "")
        hint = self.case_hint
        edges: List[LineageEdge] = []
        now = datetime.utcnow()

        # Build dataset name -> id lookup
        ds_name_to_id: Dict[str, str] = {}
        for ds in export.get("datasets", []):
            name = normalize_identifier(ds["name"], hint)
            ds_name_to_id[name] = generate_asset_id("bi", system, namespace, "datasets", name)

        # Tool-level: dashboard -> dataset (via tiles)
        for dash in export.get("dashboards", []):
            dash_name = normalize_identifier(dash["name"], hint)
            dash_id = generate_asset_id("bi", system, namespace, "dashboards", dash_name)

            for tile_name in dash.get("tiles", []):
                tile_norm = normalize_identifier(tile_name, hint)
                ds_id = ds_name_to_id.get(tile_norm)
                if not ds_id:
                    continue

                evidence_ref = f"dashboard:{dash_name}:tile:{tile_norm}"
                edge_id = generate_edge_id(ds_id, dash_id, "reads_from", "tool", evidence_ref)

                edges.append(LineageEdge(
                    id=edge_id,
                    source_id=ds_id,
                    target_id=dash_id,
                    edge_type=EdgeType.READS_FROM,
                    confidence=1.0,
                    discovered_from=self._id,
                    discovered_at=now,
                    lineage_level=LineageLevel.TOOL,
                    evidence=[Evidence(
                        adapter_id=self._id,
                        source_ref=evidence_ref,
                        observed_at=now,
                        snippet=f"dashboard '{dash_name}' tile '{tile_norm}'",
                    )],
                ))

        # Table-level: warehouse table -> dataset (via SQL or explicit table refs)
        for ds in export.get("datasets", []):
            ds_name = normalize_identifier(ds["name"], hint)
            ds_id = ds_name_to_id.get(ds_name)
            if not ds_id:
                continue

            table_refs: List[str] = []

            # Try SQL parsing first
            sql = ds.get("sql")
            if sql:
                try:
                    from ...parser import UniversalLineageParser
                    parser = UniversalLineageParser()
                    info = parser.parse_query(sql)
                    table_refs = info.sources
                except Exception as e:
                    logger.debug(f"SQL parse failed for dataset {ds_name}: {e}")

            # Fall back to explicit table list
            if not table_refs:
                table_refs = ds.get("tables", [])

            for tbl_ref in table_refs:
                tbl_norm = normalize_identifier(tbl_ref, hint)
                evidence_ref = f"dataset:{ds_name}:table:{tbl_norm}"
                # Use a placeholder asset_id — the resolver will match to real warehouse nodes
                tbl_parts = tbl_norm.split(".")
                if len(tbl_parts) >= 2:
                    container = ".".join(tbl_parts[:-1])
                    tbl_name = tbl_parts[-1]
                else:
                    container = ""
                    tbl_name = tbl_norm

                tbl_id = generate_asset_id("warehouse", "unknown", namespace, container, tbl_name)
                edge_id = generate_edge_id(tbl_id, ds_id, "reads_from", "table", evidence_ref)

                snippet = sql[:200] if sql else f"dataset references {tbl_norm}"
                confidence = 0.8 if sql else 0.9  # explicit list is higher confidence

                edges.append(LineageEdge(
                    id=edge_id,
                    source_id=tbl_id,
                    target_id=ds_id,
                    edge_type=EdgeType.READS_FROM,
                    confidence=confidence,
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

            # Column-level: only when explicit column mappings are available
            col_info = ds.get("columns", [])
            col_maps_by_table: Dict[str, List[ColumnMapping]] = {}
            for c in col_info:
                src_table = c.get("source_table")
                src_col = c.get("source_column")
                if not src_table or not src_col:
                    continue
                src_table_norm = normalize_identifier(src_table, hint)
                mapping = ColumnMapping(
                    from_column=normalize_identifier(src_col, hint),
                    to_column=normalize_identifier(c["name"], hint),
                    transform_expr=c.get("transform_expr"),
                    confidence=1.0,
                )
                col_maps_by_table.setdefault(src_table_norm, []).append(mapping)

            for src_table_norm, mappings in col_maps_by_table.items():
                tbl_parts = src_table_norm.split(".")
                if len(tbl_parts) >= 2:
                    container = ".".join(tbl_parts[:-1])
                    tbl_name = tbl_parts[-1]
                else:
                    container = ""
                    tbl_name = src_table_norm

                tbl_id = generate_asset_id("warehouse", "unknown", namespace, container, tbl_name)
                evidence_ref = f"dataset:{ds_name}:column_map:{src_table_norm}"
                edge_id = generate_edge_id(tbl_id, ds_id, "reads_from", "column", evidence_ref)

                edges.append(LineageEdge(
                    id=edge_id,
                    source_id=tbl_id,
                    target_id=ds_id,
                    edge_type=EdgeType.READS_FROM,
                    confidence=1.0,
                    discovered_from=self._id,
                    discovered_at=now,
                    lineage_level=LineageLevel.COLUMN,
                    evidence=[Evidence(
                        adapter_id=self._id,
                        source_ref=evidence_ref,
                        observed_at=now,
                        snippet=f"column map: {src_table_norm} -> {ds_name} ({len(mappings)} cols)",
                    )],
                    column_mappings=mappings,
                ))

        return edges
