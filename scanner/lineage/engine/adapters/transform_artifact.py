"""
Transform Artifact Adapter

Reads a tool-agnostic manifest JSON describing logical models/sources and
their relations.  Emits table lineage + optionally column lineage when the
manifest contains compiled SQL or explicit column maps.

The manifest schema is generic — a thin translator can convert dbt, SQLMesh,
or other tool manifests into this format outside the core engine.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
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


class TransformArtifactAdapter(BaseLineageAdapter):
    """
    Adapter that reads a tool-agnostic transform manifest.

    Expected manifest JSON schema::

        {
          "metadata": {"system": "dbt", "namespace": "acme-prod", "case_hint": "lower"},
          "sources": [
            {
              "name": "raw_customers",
              "database": "warehouse",
              "schema": "raw",
              "identifier": "customers",
              "columns": [{"name": "id", "type": "integer"}, ...]
            }
          ],
          "models": [
            {
              "name": "dim_customers",
              "database": "warehouse",
              "schema": "analytics",
              "materialized": "table",
              "depends_on": ["raw_customers", "raw_orders"],
              "columns": [...],
              "compiled_sql": "SELECT ... FROM ...",
              "column_mappings": [
                {"from_column": "id", "to_column": "customer_id", "transform_expr": "CAST(id AS INT)"}
              ],
              "description": "Cleaned customer dimension",
              "owner": "analytics-team",
              "tags": ["tier1"]
            }
          ]
        }
    """

    def __init__(self, adapter_id: str, path: str = "", **kwargs):
        self._id = adapter_id
        self._path = path
        self._manifest: Dict[str, Any] = {}
        self._has_column_lineage = False

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        caps = {Capability.DISCOVER_ASSETS, Capability.EXTRACT_TABLE_LINEAGE}
        if self._has_column_lineage:
            caps.add(Capability.EXTRACT_COLUMN_LINEAGE)
        return caps

    @property
    def case_hint(self) -> str:
        return self._manifest.get("metadata", {}).get("case_hint", "lower")

    def _load_manifest(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Load manifest from path or inline data."""
        if self._manifest:
            return self._manifest

        path = config.get("path", self._path)
        if path:
            with open(path) as f:
                self._manifest = json.load(f)
        elif "manifest" in config:
            self._manifest = config["manifest"]
        else:
            raise ValueError("TransformArtifactAdapter requires 'path' or 'manifest' in config")

        # Check if any model has column lineage evidence
        for model in self._manifest.get("models", []):
            if model.get("column_mappings") or model.get("compiled_sql"):
                self._has_column_lineage = True
                break

        return self._manifest

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        manifest = self._load_manifest(config)
        meta = manifest.get("metadata", {})
        system = meta.get("system", "transform")
        namespace = meta.get("namespace", "")
        hint = self.case_hint
        nodes: List[LineageNode] = []

        # Sources
        for src in manifest.get("sources", []):
            name = normalize_identifier(src["name"], hint)
            db = normalize_identifier(src.get("database", ""), hint)
            schema = normalize_identifier(src.get("schema", ""), hint)
            identifier = normalize_identifier(src.get("identifier", name), hint)
            container = f"{db}.{schema}" if db else schema

            node_id = generate_asset_id("warehouse", system, namespace, container, identifier)
            fqn_parts = [p for p in [db, schema, identifier] if p]
            fqn = ".".join(fqn_parts)

            columns = [
                {"name": c["name"], "type": c.get("type", "unknown")}
                for c in src.get("columns", [])
            ]

            nodes.append(LineageNode(
                id=node_id,
                name=identifier,
                fqn=fqn,
                node_type=NodeType.SOURCE,
                database=db,
                schema=schema,
                platform=system,
                platform_domain=PlatformDomain.WAREHOUSE,
                asset_kind=AssetKind.TABLE,
                namespace=namespace,
                columns=columns,
                sources=[self._id],
                observed_at=datetime.utcnow(),
            ))

        # Models
        for model in manifest.get("models", []):
            name = normalize_identifier(model["name"], hint)
            db = normalize_identifier(model.get("database", ""), hint)
            schema = normalize_identifier(model.get("schema", ""), hint)
            container = f"{db}.{schema}" if db else schema
            materialized = model.get("materialized", "view")

            node_id = generate_asset_id("transform", system, namespace, container, name)
            fqn_parts = [p for p in [db, schema, name] if p]
            fqn = ".".join(fqn_parts)

            node_type = NodeType.MODEL
            asset_kind = AssetKind.MODEL
            if materialized in ("table", "incremental"):
                asset_kind = AssetKind.TABLE
            elif materialized == "view":
                asset_kind = AssetKind.VIEW

            columns = [
                {"name": c["name"], "type": c.get("type", "unknown")}
                for c in model.get("columns", [])
            ]

            nodes.append(LineageNode(
                id=node_id,
                name=name,
                fqn=fqn,
                node_type=node_type,
                database=db,
                schema=schema,
                platform=system,
                platform_domain=PlatformDomain.TRANSFORM,
                asset_kind=asset_kind,
                namespace=namespace,
                description=model.get("description"),
                owner=model.get("owner"),
                tags=model.get("tags", []),
                columns=columns,
                sources=[self._id],
                observed_at=datetime.utcnow(),
                raw_metadata={"materialized": materialized},
            ))

        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        manifest = self._load_manifest(config)
        meta = manifest.get("metadata", {})
        system = meta.get("system", "transform")
        namespace = meta.get("namespace", "")
        hint = self.case_hint
        edges: List[LineageEdge] = []
        now = datetime.utcnow()

        # Build a lookup: source/model name -> node_id
        name_to_id: Dict[str, str] = {}
        for src in manifest.get("sources", []):
            raw_name = normalize_identifier(src["name"], hint)
            identifier = normalize_identifier(src.get("identifier", raw_name), hint)
            db = normalize_identifier(src.get("database", ""), hint)
            schema = normalize_identifier(src.get("schema", ""), hint)
            container = f"{db}.{schema}" if db else schema
            name_to_id[raw_name] = generate_asset_id("warehouse", system, namespace, container, identifier)

        for model in manifest.get("models", []):
            name = normalize_identifier(model["name"], hint)
            db = normalize_identifier(model.get("database", ""), hint)
            schema = normalize_identifier(model.get("schema", ""), hint)
            container = f"{db}.{schema}" if db else schema
            name_to_id[name] = generate_asset_id("transform", system, namespace, container, name)

        # Table-level edges from depends_on
        for model in manifest.get("models", []):
            model_name = normalize_identifier(model["name"], hint)
            target_id = name_to_id.get(model_name)
            if not target_id:
                continue

            for dep_name in model.get("depends_on", []):
                dep_name_norm = normalize_identifier(dep_name, hint)
                source_id = name_to_id.get(dep_name_norm)
                if not source_id:
                    logger.debug(f"Unresolved dependency: {dep_name} for model {model_name}")
                    continue

                evidence_ref = f"manifest:{model_name}:depends_on:{dep_name_norm}"
                edge_id = generate_edge_id(source_id, target_id, "depends_on", "table", evidence_ref)

                evidence = Evidence(
                    adapter_id=self._id,
                    source_ref=evidence_ref,
                    observed_at=now,
                    snippet=f"{dep_name_norm} -> {model_name}",
                )

                edges.append(LineageEdge(
                    id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=EdgeType.DEPENDS_ON,
                    confidence=1.0,
                    discovered_from=self._id,
                    discovered_at=now,
                    lineage_level=LineageLevel.TABLE,
                    evidence=[evidence],
                ))

            # Column-level edges from explicit column_mappings
            col_maps = model.get("column_mappings", [])
            if col_maps:
                for dep_name in model.get("depends_on", []):
                    dep_name_norm = normalize_identifier(dep_name, hint)
                    source_id = name_to_id.get(dep_name_norm)
                    if not source_id:
                        continue

                    mappings = [
                        ColumnMapping(
                            from_column=normalize_identifier(m["from_column"], hint),
                            to_column=normalize_identifier(m["to_column"], hint),
                            transform_expr=m.get("transform_expr"),
                            confidence=m.get("confidence", 1.0),
                        )
                        for m in col_maps
                    ]

                    evidence_ref = f"manifest:{model_name}:column_map:{dep_name_norm}"
                    edge_id = generate_edge_id(source_id, target_id, "depends_on", "column", evidence_ref)

                    evidence = Evidence(
                        adapter_id=self._id,
                        source_ref=evidence_ref,
                        observed_at=now,
                        snippet=f"column map: {dep_name_norm} -> {model_name} ({len(mappings)} cols)",
                    )

                    edges.append(LineageEdge(
                        id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                        edge_type=EdgeType.DEPENDS_ON,
                        confidence=1.0,
                        discovered_from=self._id,
                        discovered_at=now,
                        lineage_level=LineageLevel.COLUMN,
                        evidence=[evidence],
                        column_mappings=mappings,
                    ))

        return edges
