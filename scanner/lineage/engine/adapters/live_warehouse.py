"""
Live Warehouse Adapter — bridges existing BigQuery/Snowflake/Postgres parsers
to the engine adapter framework.

Instead of reading JSON fixtures, this adapter invokes the real warehouse parsers
and converts their output (old-format LineageGraph) into canonical engine nodes/edges
with full evidence provenance.
"""

import hashlib
import json
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

# Map old NodeType → new AssetKind
_NODE_TYPE_TO_ASSET_KIND = {
    NodeType.TABLE: AssetKind.TABLE,
    NodeType.VIEW: AssetKind.VIEW,
    NodeType.MATERIALIZED_VIEW: AssetKind.VIEW,
    NodeType.SOURCE: AssetKind.TABLE,
    NodeType.MODEL: AssetKind.MODEL,
    NodeType.DASHBOARD: AssetKind.DASHBOARD,
    NodeType.DATASET: AssetKind.DATASET,
    NodeType.TASK: AssetKind.TASK,
    NodeType.DAG: AssetKind.JOB,
}

# Map platform name → case hint
_PLATFORM_CASE_HINTS = {
    "bigquery": "lower",
    "snowflake": "upper",
    "postgres": "lower",
    "redshift": "lower",
    "sqlserver": "lower",
    "azure_sql": "lower",
    "azure_synapse": "lower",
}


class LiveWarehouseAdapter(BaseLineageAdapter):
    """
    Adapter that wraps existing warehouse parsers (BigQuery, Snowflake, Postgres)
    and converts their output to the engine's canonical format.

    Config keys:
        platform: "bigquery" | "snowflake" | "postgres" | "redshift"
        connection_config: dict passed to the parser constructor
        parser_options: optional dict (region, days_back, etc.)
    """

    def __init__(self, adapter_id: str = "live_warehouse", **kwargs):
        self._id = adapter_id
        self._platform = kwargs.get("platform", "bigquery")
        self._case = _PLATFORM_CASE_HINTS.get(self._platform, "lower")
        self._parser_cache: Dict[str, Any] = {}  # config_hash → parsed graph

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_QUERY_HISTORY,
        }

    @property
    def case_hint(self) -> str:
        return self._case

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Run the live parser and extract nodes."""
        graph = self._run_parser(config)
        if graph is None:
            return []
        return self._convert_nodes(graph, config)

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Run the live parser and extract edges with evidence."""
        graph = self._run_parser(config)
        if graph is None:
            return []
        return self._convert_edges(graph, config)

    # ------------------------------------------------------------------
    # Internal: run the appropriate parser
    # ------------------------------------------------------------------

    def _run_parser(self, config: Dict[str, Any]):
        """Instantiate and run the platform-specific parser, return old-format LineageGraph.

        Results are cached so that discover_assets() and extract_lineage()
        don't re-run the same expensive queries (INFORMATION_SCHEMA, job history, etc.).
        """
        cache_key = self._make_cache_key(config)
        if cache_key in self._parser_cache:
            logger.info(f"[LiveWarehouse] Using cached parse for {self._platform}")
            return self._parser_cache[cache_key]

        graph = self._parse_fresh(config)
        if graph is not None:
            self._parser_cache[cache_key] = graph
        return graph

    def _make_cache_key(self, config: Dict[str, Any]) -> str:
        """Deterministic hash of config values that affect parsing."""
        platform = config.get("platform", self._platform)
        conn = config.get("connection_config", {})
        opts = config.get("parser_options", {})
        key_data = json.dumps({
            "platform": platform,
            "project_id": conn.get("project_id", "") or conn.get("project", ""),
            "account": conn.get("account", ""),
            "database": conn.get("database", ""),
            "datasets": sorted(conn.get("datasets", []) if isinstance(conn.get("datasets"), list) else []),
            "region": opts.get("region", "auto"),
            "days_back": opts.get("days_back", 30),
        }, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _parse_fresh(self, config: Dict[str, Any]):
        """Run the platform-specific parser without caching."""
        platform = config.get("platform", self._platform)
        conn_config = config.get("connection_config", {})
        options = config.get("parser_options", {})

        try:
            if platform == "bigquery":
                return self._run_bigquery(conn_config, options)
            elif platform == "snowflake":
                return self._run_snowflake(conn_config, options)
            elif platform in ("postgres", "redshift"):
                return self._run_postgres(conn_config, options)
            else:
                logger.error(f"[LiveWarehouse] Unsupported platform: {platform}")
                return None
        except Exception as e:
            logger.error(f"[LiveWarehouse] Parser failed for {platform}: {e}")
            return None

    def _run_bigquery(self, conn_config: Dict, options: Dict):
        from google.cloud import bigquery
        from google.oauth2 import service_account
        import json

        from ...parsers.bigquery import BigQueryParser

        project_id = conn_config.get("project_id") or conn_config.get("project")
        creds_json = conn_config.get("credentials_json") or conn_config.get("credentials")

        if creds_json:
            if isinstance(creds_json, str):
                creds_json = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(creds_json)
            client = bigquery.Client(project=project_id, credentials=credentials)
        else:
            client = bigquery.Client(project=project_id)

        datasets = conn_config.get("datasets", [])
        if isinstance(datasets, str):
            datasets = [datasets]

        parser = BigQueryParser(
            client=client,
            project_id=project_id,
            region=options.get("region", "auto"),
            days_back=options.get("days_back", 30),
            enable_data_catalog=options.get("enable_data_catalog", False),
            selected_datasets=datasets if datasets else None,
        )
        return parser.parse()

    def _run_snowflake(self, conn_config: Dict, options: Dict):
        import snowflake.connector

        from ...parsers.snowflake import SnowflakeQueryParser

        account = conn_config.get("account", "")
        user = conn_config.get("user") or conn_config.get("username", "")
        password = conn_config.get("password", "")
        warehouse = conn_config.get("warehouse", "")
        database = conn_config.get("database", "")
        schema = conn_config.get("schema", "")
        role = conn_config.get("role", "")

        connect_kwargs: Dict[str, Any] = {
            "account": account,
            "user": user,
            "password": password,
        }
        if warehouse:
            connect_kwargs["warehouse"] = warehouse
        if database:
            connect_kwargs["database"] = database
        if schema:
            connect_kwargs["schema"] = schema
        if role:
            connect_kwargs["role"] = role

        conn = snowflake.connector.connect(**connect_kwargs)
        try:
            parser = SnowflakeQueryParser(
                connection=conn,
                days_back=options.get("days_back", 30),
                use_access_history=options.get("use_access_history", True),
            )
            return parser.parse()
        finally:
            conn.close()

    def _run_postgres(self, conn_config: Dict, options: Dict):
        # Postgres parser not yet implemented in parsers/
        logger.warning("[LiveWarehouse] Postgres parser not yet available")
        return None

    # ------------------------------------------------------------------
    # Convert old-format graph → engine canonical nodes/edges
    # ------------------------------------------------------------------

    def _convert_nodes(self, graph, config: Dict[str, Any]) -> List[LineageNode]:
        """Convert old-format LineageGraph nodes to engine-canonical nodes."""
        from ..ids import compute_environment_scope
        platform = config.get("platform", self._platform)
        namespace = config.get("connection_config", {}).get("project_id", "")
        integration_id = config.get("integration_id")
        env_scope = compute_environment_scope(
            platform, config.get("connection_config", {}),
        )
        hint = self._case
        now = datetime.utcnow()

        nodes: List[LineageNode] = []
        for old_node in graph.nodes.values():
            db = normalize_identifier(old_node.database or "", hint)
            schema = normalize_identifier(old_node.schema or "", hint)
            name = normalize_identifier(old_node.name or "", hint)
            container = f"{db}.{schema}"
            fqn = ".".join(p for p in [db, schema, name] if p)

            asset_id = generate_asset_id(
                "warehouse", platform, namespace, container, name
            )

            asset_kind = _NODE_TYPE_TO_ASSET_KIND.get(old_node.node_type, AssetKind.UNKNOWN)

            node = LineageNode(
                id=asset_id,
                name=name,
                fqn=fqn,
                node_type=old_node.node_type,
                database=db,
                schema=schema,
                platform=platform,
                platform_domain=PlatformDomain.WAREHOUSE,
                asset_kind=asset_kind,
                namespace=namespace,
                environment_scope=env_scope or None,
                description=old_node.description,
                owner=old_node.owner,
                tags=old_node.tags,
                columns=old_node.columns,
                row_count=old_node.row_count,
                criticality=old_node.criticality,
                upstream_count=old_node.upstream_count,
                downstream_count=old_node.downstream_count,
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                raw_metadata={
                    "case_hint": hint,
                    "old_id": old_node.id,
                },
            )
            nodes.append(node)

        logger.info(f"[LiveWarehouse] Converted {len(nodes)} nodes from {platform}")
        return nodes

    def _convert_edges(self, graph, config: Dict[str, Any]) -> List[LineageEdge]:
        """Convert old-format LineageGraph edges to engine-canonical edges with evidence."""
        platform = config.get("platform", self._platform)
        namespace = config.get("connection_config", {}).get("project_id", "")
        hint = self._case
        now = datetime.utcnow()

        # Build lookup: old node id → new engine asset id
        old_to_new: Dict[str, str] = {}
        for old_node in graph.nodes.values():
            db = normalize_identifier(old_node.database or "", hint)
            schema = normalize_identifier(old_node.schema or "", hint)
            name = normalize_identifier(old_node.name or "", hint)
            container = f"{db}.{schema}"
            new_id = generate_asset_id("warehouse", platform, namespace, container, name)
            old_to_new[old_node.id] = new_id

        edges: List[LineageEdge] = []
        for old_edge in graph.edges.values():
            src = old_to_new.get(old_edge.source_id)
            tgt = old_to_new.get(old_edge.target_id)
            if not src or not tgt:
                continue

            # Determine evidence source type
            source_ref = old_edge.discovered_from or f"{platform}_lineage"
            confidence = old_edge.confidence

            # Classify confidence from discovery method
            if "view" in source_ref.lower():
                confidence = max(confidence, 0.9)
            elif "job" in source_ref.lower() or "query" in source_ref.lower():
                confidence = max(confidence, 0.7)

            ev = Evidence(
                adapter_id=self._id,
                source_ref=source_ref,
                observed_at=now,
                snippet=(old_edge.transformation or "")[:200] or None,
            )

            edge_id = generate_edge_id(
                src, tgt,
                old_edge.edge_type.value,
                "table",
                source_ref,
            )

            edge = LineageEdge(
                id=edge_id,
                source_id=src,
                target_id=tgt,
                edge_type=old_edge.edge_type,
                lineage_level=LineageLevel.TABLE,
                confidence=confidence,
                discovered_from=source_ref,
                discovered_at=now,
                evidence=[ev],
                columns=old_edge.columns,
                transformation=old_edge.transformation,
            )
            edges.append(edge)

        logger.info(f"[LiveWarehouse] Converted {len(edges)} edges from {platform}")
        return edges
