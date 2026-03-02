"""
Live dbt Adapter — bridges dbt manifest parsing to the engine adapter framework.

Reads a dbt manifest.json (provided in config or fetched from dbt Cloud)
and converts models, sources, and their dependencies into engine-canonical
nodes and edges with full evidence provenance.
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
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)

# dbt resource type → (NodeType, AssetKind)
_DBT_TYPE_MAP = {
    "model": (NodeType.MODEL, AssetKind.MODEL),
    "source": (NodeType.SOURCE, AssetKind.TABLE),
    "seed": (NodeType.SEED, AssetKind.TABLE),
    "snapshot": (NodeType.SNAPSHOT, AssetKind.TABLE),
    "test": (NodeType.TASK, AssetKind.TASK),
}


class LiveDbtAdapter(BaseLineageAdapter):
    """
    Adapter that reads a dbt manifest.json and emits canonical engine nodes/edges.

    Config keys:
        manifest: dict — pre-parsed manifest.json content
        warehouse_type: "bigquery" | "snowflake" | "postgres" (for case hints)
        namespace: project/account identifier
    """

    def __init__(self, adapter_id: str = "live_dbt", **kwargs):
        self._id = adapter_id
        self._warehouse_type = kwargs.get("warehouse_type", "bigquery")

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.EXTRACT_COLUMN_LINEAGE,
            Capability.GET_OWNERSHIP,
        }

    @property
    def case_hint(self) -> str:
        if self._warehouse_type == "snowflake":
            return "upper"
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Extract nodes from dbt manifest."""
        manifest = config.get("manifest", {})
        if isinstance(manifest, str):
            import json
            manifest = json.loads(manifest)
        if not manifest:
            logger.warning("[LiveDbt] No manifest provided")
            return []

        namespace = config.get("namespace", "")
        if not namespace:
            namespace = self._infer_namespace(manifest)
        logger.info("[LiveDbt] Using namespace=%r for %d nodes, %d sources",
                    namespace, len(manifest.get("nodes", {})), len(manifest.get("sources", {})))
        integration_id = config.get("integration_id")
        hint = self.case_hint
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Process sources
        for key, source in manifest.get("sources", {}).items():
            node = self._source_to_node(source, namespace, hint, now, integration_id)
            if node:
                nodes.append(node)

        # Process models, seeds, snapshots
        for key, model in manifest.get("nodes", {}).items():
            resource_type = model.get("resource_type", "")
            if resource_type in ("model", "seed", "snapshot"):
                node = self._model_to_node(model, namespace, hint, now, integration_id)
                if node:
                    nodes.append(node)

        logger.info(f"[LiveDbt] Discovered {len(nodes)} assets from manifest")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract dependency edges from dbt manifest."""
        manifest = config.get("manifest", {})
        if isinstance(manifest, str):
            import json
            manifest = json.loads(manifest)
        if not manifest:
            return []

        namespace = config.get("namespace", "")
        if not namespace:
            namespace = self._infer_namespace(manifest)
        hint = self.case_hint
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        # Build name → engine id lookup for all nodes
        node_lookup = self._build_lookup(manifest, namespace, hint)

        # Process model depends_on
        for key, model in manifest.get("nodes", {}).items():
            resource_type = model.get("resource_type", "")
            if resource_type not in ("model", "seed", "snapshot"):
                continue

            target_id = self._get_engine_id(model, namespace, hint)
            if not target_id:
                continue

            depends_on = model.get("depends_on", {}).get("nodes", [])
            for dep_key in depends_on:
                source_id = node_lookup.get(dep_key)
                if not source_id:
                    continue

                source_ref = f"manifest:{key}:depends_on:{dep_key}"
                ev = Evidence(
                    adapter_id=self._id,
                    source_ref=source_ref,
                    observed_at=now,
                )

                edge_id = generate_edge_id(
                    source_id, target_id,
                    EdgeType.DEPENDS_ON.value,
                    "table",
                    source_ref,
                )

                edge = LineageEdge(
                    id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=EdgeType.DEPENDS_ON,
                    lineage_level=LineageLevel.TABLE,
                    confidence=1.0,  # Manifest is declarative — highest confidence
                    discovered_from=source_ref,
                    discovered_at=now,
                    evidence=[ev],
                )
                edges.append(edge)

        logger.info(f"[LiveDbt] Extracted {len(edges)} edges from manifest")
        return edges

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _infer_namespace(self, manifest: Dict) -> str:
        """Infer namespace from the manifest's database field.

        For BigQuery the database IS the GCP project_id, which matches
        the namespace used by the warehouse adapter.  This ensures
        cross-domain dedup can pair dbt models with their BQ counterparts.
        """
        # Check nodes first (models), then sources
        for section in ("nodes", "sources"):
            for resource in manifest.get(section, {}).values():
                db = resource.get("database", "")
                if db:
                    ns = normalize_identifier(db, self.case_hint)
                    logger.debug("[LiveDbt] Inferred namespace from manifest: %s", ns)
                    return ns
        return ""

    def _source_to_node(
        self, source: Dict, namespace: str, hint: str, now: datetime,
        integration_id: Optional[str] = None,
    ) -> Optional[LineageNode]:
        """Convert a dbt source definition to a canonical node."""
        db = normalize_identifier(source.get("database", ""), hint)
        schema = normalize_identifier(source.get("schema", ""), hint)
        name = normalize_identifier(source.get("name", "") or source.get("identifier", ""), hint)
        if not name:
            return None

        container = f"{db}.{schema}"
        fqn = ".".join(p for p in [db, schema, name] if p)

        # Sources reference warehouse tables — domain is warehouse
        asset_id = generate_asset_id("warehouse", "dbt", namespace, container, name)

        return LineageNode(
            id=asset_id,
            name=name,
            fqn=fqn,
            node_type=NodeType.SOURCE,
            database=db,
            schema=schema,
            platform="dbt",
            platform_domain=PlatformDomain.WAREHOUSE,  # physical warehouse table
            asset_kind=AssetKind.TABLE,
            namespace=namespace,
            description=source.get("description"),
            owner=source.get("meta", {}).get("owner"),
            tags=source.get("tags", []),
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={"case_hint": hint, "dbt_resource_type": "source", "warehouse_type": self._warehouse_type},
        )

    def _model_to_node(
        self, model: Dict, namespace: str, hint: str, now: datetime,
        integration_id: Optional[str] = None,
    ) -> Optional[LineageNode]:
        """Convert a dbt model/seed/snapshot to a canonical node."""
        resource_type = model.get("resource_type", "model")
        db = normalize_identifier(model.get("database", ""), hint)
        schema = normalize_identifier(model.get("schema", ""), hint)
        name = normalize_identifier(model.get("name", "") or model.get("alias", ""), hint)
        if not name:
            return None

        container = f"{db}.{schema}"
        fqn = ".".join(p for p in [db, schema, name] if p)

        node_type, asset_kind = _DBT_TYPE_MAP.get(resource_type, (NodeType.MODEL, AssetKind.MODEL))

        # Models are transformations that produce warehouse assets.
        # Using TRANSFORM domain enables the resolver's cross-domain dedup
        # to merge dbt models with their BigQuery view/table counterparts.
        asset_id = generate_asset_id("warehouse", "dbt", namespace, container, name)

        return LineageNode(
            id=asset_id,
            name=name,
            fqn=fqn,
            node_type=node_type,
            database=db,
            schema=schema,
            platform="dbt",
            platform_domain=PlatformDomain.TRANSFORM,
            asset_kind=asset_kind,
            namespace=namespace,
            description=model.get("description"),
            owner=model.get("meta", {}).get("owner"),
            tags=model.get("tags", []),
            columns=[
                {"name": c.get("name"), "type": c.get("data_type", ""), "description": c.get("description", "")}
                for c in model.get("columns", {}).values()
            ] if isinstance(model.get("columns"), dict) else [],
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "case_hint": hint,
                "dbt_resource_type": resource_type,
                "materialized": model.get("config", {}).get("materialized", "view"),
                "warehouse_type": self._warehouse_type,
            },
        )

    def _get_engine_id(self, resource: Dict, namespace: str, hint: str) -> Optional[str]:
        """Get engine asset ID for a dbt resource."""
        db = normalize_identifier(resource.get("database", ""), hint)
        schema = normalize_identifier(resource.get("schema", ""), hint)
        name = normalize_identifier(
            resource.get("name", "") or resource.get("identifier", "") or resource.get("alias", ""),
            hint,
        )
        if not name:
            return None
        container = f"{db}.{schema}"
        return generate_asset_id("warehouse", "dbt", namespace, container, name)

    def _build_lookup(
        self, manifest: Dict, namespace: str, hint: str
    ) -> Dict[str, str]:
        """Build dbt unique_id → engine asset ID lookup."""
        lookup: Dict[str, str] = {}

        for key, source in manifest.get("sources", {}).items():
            engine_id = self._get_engine_id(source, namespace, hint)
            if engine_id:
                lookup[key] = engine_id

        for key, node in manifest.get("nodes", {}).items():
            engine_id = self._get_engine_id(node, namespace, hint)
            if engine_id:
                lookup[key] = engine_id

        return lookup
