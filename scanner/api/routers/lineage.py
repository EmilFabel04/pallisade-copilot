"""
Lineage extraction API router.

Extracts lineage from connected warehouses and returns a graph.
"""

from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


class LineageRequest(BaseModel):
    """Request to extract lineage from a warehouse."""
    integration_type: str = Field(..., description="Type: BIGQUERY, SNOWFLAKE, POSTGRES, etc.")
    config: Dict[str, Any] = Field(..., description="Integration configuration")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Lineage extraction options")
    integration_id: Optional[str] = Field(default=None, description="Pallisade integration ID for linking to pipeline nodes")


class LineageNodeResponse(BaseModel):
    """A node in the lineage graph."""
    id: str
    name: str
    fqn: str
    node_type: str
    database: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")
    platform: Optional[str] = None
    description: Optional[str] = None
    criticality: str = "medium"
    row_count: Optional[int] = None
    columns: List[Dict[str, Any]] = []
    upstream_count: int = 0
    downstream_count: int = 0

    class Config:
        populate_by_name = True


class LineageEdgeResponse(BaseModel):
    """An edge in the lineage graph."""
    id: str
    source_id: str
    target_id: str
    edge_type: str
    columns: List[Dict[str, str]] = []
    transformation: Optional[str] = None
    discovered_from: Optional[str] = None


class LineageResponse(BaseModel):
    """Lineage extraction response."""
    success: bool
    nodes: List[LineageNodeResponse] = []
    edges: List[LineageEdgeResponse] = []
    stats: Dict[str, Any] = {}
    errors: List[str] = []


def get_bigquery_client(config: Dict[str, Any]):
    """Create a BigQuery client from config."""
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
        import json
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="BigQuery client not installed. Run: pip install google-cloud-bigquery"
        )
    
    project_id = config.get('project_id') or config.get('project')
    credentials_json = config.get('credentials_json') or config.get('credentials')
    
    if not project_id:
        raise HTTPException(status_code=400, detail="Missing project_id in config")
    
    if credentials_json:
        # Parse credentials if string
        if isinstance(credentials_json, str):
            try:
                credentials_dict = json.loads(credentials_json)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid credentials_json format")
        else:
            credentials_dict = credentials_json
        
        credentials = service_account.Credentials.from_service_account_info(credentials_dict)
        client = bigquery.Client(project=project_id, credentials=credentials)
    else:
        # Use default credentials
        client = bigquery.Client(project=project_id)
    
    return client, project_id


@router.post("/lineage/extract", response_model=LineageResponse)
async def extract_lineage(request: LineageRequest):
    """
    Extract lineage from a connected warehouse.
    
    Supports:
    - BigQuery: Uses INFORMATION_SCHEMA.JOBS and view definitions
    - Snowflake: Uses ACCESS_HISTORY and OBJECT_DEPENDENCIES
    - Postgres: Uses pg_depend and view definitions
    """
    integration_type = request.integration_type.upper()
    config = request.config
    options = request.options or {}
    integration_id = request.integration_id

    try:
        if integration_type == "BIGQUERY":
            return await extract_bigquery_lineage(config, options, integration_id)
        elif integration_type == "SNOWFLAKE":
            return await extract_snowflake_lineage(config, options)
        elif integration_type == "POSTGRES":
            return await extract_postgres_lineage(config, options)
        elif integration_type in ("DBT_CLOUD", "DBT_CORE"):
            return await extract_dbt_lineage(config, options, integration_type, integration_id)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported integration type: {integration_type}"
            )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return LineageResponse(
            success=False,
            errors=[str(e)]
        )


async def extract_bigquery_lineage(config: Dict[str, Any], options: Dict[str, Any], integration_id: Optional[str] = None) -> LineageResponse:
    """Extract lineage from BigQuery."""
    import asyncio
    
    client, project_id = get_bigquery_client(config)
    
    # Get datasets from config
    datasets = config.get('datasets', [])
    if isinstance(datasets, str):
        datasets = [datasets]
    
    # Import the BigQuery parser
    try:
        from lineage.parsers.bigquery import BigQueryParser
    except ImportError:
        from scanner.lineage.parsers.bigquery import BigQueryParser
    
    # Run parser in thread pool (it's synchronous)
    def run_parser():
        parser = BigQueryParser(
            client=client,
            project_id=project_id,
            region=options.get('region', 'auto'),
            days_back=options.get('days_back', 30),
            enable_data_catalog=options.get('enable_data_catalog', False),
            selected_datasets=datasets if datasets else None,
        )
        return parser.parse()
    
    graph = await asyncio.to_thread(run_parser)

    # Convert already-parsed graph to engine format (no re-run of BQ parser)
    try:
        try:
            from lineage.engine.adapters.live_warehouse import LiveWarehouseAdapter
        except ImportError:
            from scanner.lineage.engine.adapters.live_warehouse import LiveWarehouseAdapter

        adapter = LiveWarehouseAdapter(adapter_id=f"bq_{project_id}", platform="bigquery")
        engine_config = {"platform": "bigquery", "connection_config": config, "parser_options": options, "integration_id": integration_id}
        engine_nodes = adapter._convert_nodes(graph, engine_config)
        engine_edges = adapter._convert_edges(graph, engine_config)
        _engine_collected_results["nodes"].extend(engine_nodes)
        _engine_collected_results["edges"].extend(engine_edges)
        _rebuild_engine_from_cache()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Engine] Failed to convert BQ graph to engine format: {e}")

    # Convert to response format
    nodes = []
    for node in graph.nodes.values():
        nodes.append(LineageNodeResponse(
            id=node.id,
            name=node.name,
            fqn=node.fqn,
            node_type=node.node_type.value,
            database=node.database,
            schema=node.schema,
            platform=node.platform,
            description=node.description,
            criticality=node.criticality,
            row_count=node.row_count,
            columns=node.columns,
            upstream_count=node.upstream_count,
            downstream_count=node.downstream_count,
        ))
    
    edges = []
    for edge in graph.edges.values():
        edges.append(LineageEdgeResponse(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            edge_type=edge.edge_type.value,
            columns=edge.columns,
            transformation=edge.transformation[:500] if edge.transformation else None,
            discovered_from=edge.discovered_from,
        ))
    
    return LineageResponse(
        success=True,
        nodes=nodes,
        edges=edges,
        stats={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "root_count": len(graph.get_roots()),
            "leaf_count": len(graph.get_leaves()),
            "source_counts": graph.source_counts,
        },
        errors=[]
    )


async def extract_snowflake_lineage(config: Dict[str, Any], options: Dict[str, Any]) -> LineageResponse:
    """Extract lineage from Snowflake."""
    # TODO: Implement Snowflake lineage extraction
    return LineageResponse(
        success=False,
        errors=["Snowflake lineage extraction not yet implemented"]
    )


async def extract_postgres_lineage(config: Dict[str, Any], options: Dict[str, Any]) -> LineageResponse:
    """Extract lineage from PostgreSQL."""
    # TODO: Implement Postgres lineage extraction
    return LineageResponse(
        success=False,
        errors=["PostgreSQL lineage extraction not yet implemented"]
    )


async def extract_dbt_lineage(
    config: Dict[str, Any], options: Dict[str, Any], integration_type: str, integration_id: Optional[str] = None
) -> LineageResponse:
    """Extract lineage from dbt (Cloud or Core)."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    try:
        from lineage.parsers.dbt import DbtManifestParser
    except ImportError:
        from scanner.lineage.parsers.dbt import DbtManifestParser

    manifest = None

    # Try to get manifest from config directly
    if config.get("manifest"):
        manifest = config["manifest"]
        # dbt_core stores manifest as a JSON string — parse it
        if isinstance(manifest, str):
            import json
            try:
                manifest = json.loads(manifest)
            except json.JSONDecodeError as e:
                logger.error(f"[dbt] Failed to parse manifest JSON string: {e}")
                manifest = None
    elif config.get("manifest_path"):
        import json
        with open(config["manifest_path"]) as f:
            manifest = json.load(f)

    # If dbt Cloud, try to fetch manifest from API
    if not manifest and integration_type == "DBT_CLOUD":
        api_token = config.get("api_token") or config.get("access_token")
        account_id = config.get("account_id")

        if api_token and account_id:
            try:
                from integrations.dbt import DbtCloudClient
            except ImportError:
                try:
                    from scanner.integrations.dbt import DbtCloudClient
                except ImportError:
                    DbtCloudClient = None

            if DbtCloudClient:
                try:
                    client = DbtCloudClient(api_token=api_token, account_id=account_id)
                    jobs = client.get_jobs()
                    for job in (jobs or []):
                        runs = client.get_runs(job["id"], limit=1)
                        if runs and runs[0].get("status") == "Success":
                            manifest = client.get_run_artifact(runs[0]["id"], "manifest.json")
                            if manifest:
                                break
                except Exception as e:
                    logger.warning(f"[dbt] Failed to fetch manifest from dbt Cloud: {e}")

    if not manifest:
        return LineageResponse(
            success=False,
            errors=["No dbt manifest available. Provide manifest in config or ensure dbt Cloud API is accessible."]
        )

    # Parse manifest with DbtManifestParser (for Prisma storage + response format)
    target_dialect = config.get("target_dialect") or config.get("adapter_type") or "bigquery"

    def run_parser():
        parser = DbtManifestParser(
            manifest_data=manifest,
            target_dialect=target_dialect,
        )
        return parser.parse()

    graph = await asyncio.to_thread(run_parser)

    # Read dbt project from GitHub repo for schema mapping (if GitHub config provided)
    github_config = config.get("github")
    if github_config and github_config.get("repo") and github_config.get("token"):
        try:
            try:
                from lineage.github_reader import read_dbt_project_config, build_schema_mapping
            except ImportError:
                from scanner.lineage.github_reader import read_dbt_project_config, build_schema_mapping

            project_config = await read_dbt_project_config(
                repo=github_config["repo"],
                token=github_config["token"],
                branch=github_config.get("branch", "main"),
                dbt_root=github_config.get("dbt_root", ""),
            )
            schema_mapping = build_schema_mapping(manifest, project_config, target_dialect)
            _engine_collected_results["schema_mapping"] = schema_mapping
            logger.info(f"[dbt] Schema mapping from GitHub: {len(schema_mapping)} models mapped")
        except Exception as gh_err:
            logger.warning(f"[dbt] GitHub schema mapping failed (non-fatal): {gh_err}")

    # Convert manifest to engine format using LiveDbtAdapter directly (no re-parse)
    try:
        try:
            from lineage.engine.adapters.live_dbt import LiveDbtAdapter
        except ImportError:
            from scanner.lineage.engine.adapters.live_dbt import LiveDbtAdapter

        dbt_adapter = LiveDbtAdapter(
            adapter_id=f"dbt_{config.get('project_name', 'default')}",
            warehouse_type=target_dialect,
        )
        # Extract warehouse namespace from manifest database field so dbt nodes
        # get the same stable_id as warehouse nodes (enables resolver dedup)
        dbt_namespace = config.get("project_name", "")
        try:
            # Sources have the physical warehouse database (e.g., BQ project_id)
            for _src in (manifest.get("sources") or {}).values():
                if _src.get("database"):
                    dbt_namespace = _src["database"]
                    break
            # Fall back to model database if no sources
            if not dbt_namespace:
                for _nd in (manifest.get("nodes") or {}).values():
                    if _nd.get("database"):
                        dbt_namespace = _nd["database"]
                        break
        except Exception:
            pass  # Keep original namespace on any error
        logger.info(f"[dbt] Using namespace '{dbt_namespace}' for engine dedup")

        dbt_config = {
            "manifest": manifest,
            "namespace": dbt_namespace,
            "warehouse_type": target_dialect,
            "integration_id": integration_id,
        }
        engine_nodes = dbt_adapter.discover_assets(dbt_config)
        engine_edges = dbt_adapter.extract_lineage(dbt_config)
        _engine_collected_results["nodes"].extend(engine_nodes)
        _engine_collected_results["edges"].extend(engine_edges)
        # Cache manifest + config for cross-tool synthesis
        _engine_collected_results["dbt_manifest"] = manifest
        _engine_collected_results["dbt_config"] = {
            "namespace": dbt_namespace,
            "warehouse_type": target_dialect,
        }
        _rebuild_engine_from_cache()
    except Exception as e:
        logger.warning(f"[Engine] Failed to convert dbt graph to engine format: {e}")

    # Convert to response format (same as warehouse extraction)
    nodes = []
    for node in graph.nodes.values():
        nodes.append(LineageNodeResponse(
            id=node.id,
            name=node.name,
            fqn=node.fqn,
            node_type=node.node_type.value,
            database=node.database,
            schema=node.schema,
            platform=node.platform,
            description=node.description,
            criticality=node.criticality,
            row_count=node.row_count,
            columns=node.columns,
            upstream_count=node.upstream_count,
            downstream_count=node.downstream_count,
        ))

    edges = []
    for edge in graph.edges.values():
        edges.append(LineageEdgeResponse(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            edge_type=edge.edge_type.value,
            columns=edge.columns,
            transformation=edge.transformation[:500] if edge.transformation else None,
            discovered_from=edge.discovered_from,
        ))

    return LineageResponse(
        success=True,
        nodes=nodes,
        edges=edges,
        stats={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "root_count": len(graph.get_roots()),
            "leaf_count": len(graph.get_leaves()),
        },
        errors=[]
    )


@router.get("/lineage/node/{node_id}")
async def get_node_lineage(
    node_id: str,
    upstream_depth: int = 2,
    downstream_depth: int = 2
):
    """
    Get lineage for a specific node.

    Returns the subgraph centered on the specified node.
    """
    # This endpoint would query stored lineage from database
    # For now, return a placeholder
    return {
        "node_id": node_id,
        "upstream_depth": upstream_depth,
        "downstream_depth": downstream_depth,
        "message": "Query stored lineage - implement database lookup"
    }


# ==========================================
# UNIFIED CROSS-TOOL LINEAGE EXTRACTION
# ==========================================

class IntegrationConfig(BaseModel):
    """Configuration for a single integration."""
    id: str
    type: str
    status: str = "ACTIVE"
    config: Dict[str, Any] = {}


class UnifiedLineageRequest(BaseModel):
    """Request to extract cross-tool lineage from all integrations."""
    organization_id: str = Field(..., description="Organization ID")
    integrations: List[IntegrationConfig] = Field(..., description="List of integrations to extract from")
    dbt_manifest: Optional[Dict[str, Any]] = Field(default=None, description="Optional pre-loaded dbt manifest")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Extraction options")


class SynthesisStatsResponse(BaseModel):
    """Statistics from cross-tool edge synthesis."""
    dbt_source_edges: int = 0
    dbt_model_edges: int = 0
    bi_warehouse_edges: int = 0
    view_base_edges: int = 0
    orchestrator_edges: int = 0
    nodes_merged: int = 0
    total_edges_created: int = 0


class ExtractionResultResponse(BaseModel):
    """Result from extracting lineage from a single tool."""
    integration_id: str
    integration_type: str
    success: bool
    error: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0
    duration_ms: int = 0


class UnifiedLineageResponse(BaseModel):
    """Response from unified cross-tool lineage extraction."""
    success: bool
    nodes: List[LineageNodeResponse] = []
    edges: List[LineageEdgeResponse] = []
    extraction_results: List[ExtractionResultResponse] = []
    synthesis_stats: Optional[SynthesisStatsResponse] = None
    stats: Dict[str, Any] = {}
    errors: List[str] = []


@router.post("/lineage/extract-unified", response_model=UnifiedLineageResponse)
async def extract_unified_lineage(request: UnifiedLineageRequest):
    """
    Extract cross-tool lineage from all connected integrations.

    This endpoint:
    1. Extracts lineage from each tool in parallel (warehouse, dbt, BI)
    2. Merges all graphs into a unified view
    3. Deduplicates nodes (same table from different tools = one node)
    4. Synthesizes cross-tool edges (dbt source -> warehouse table, etc.)
    5. Returns complete cross-tool lineage graph

    Supports:
    - Warehouses: BigQuery, Snowflake, Postgres, Redshift
    - Transformation: dbt Cloud, dbt Core
    - Orchestration: Airflow (via OpenLineage)
    - BI: Looker, Tableau, Power BI
    """
    try:
        from lineage.orchestrator import CrossToolLineageOrchestrator
    except ImportError:
        try:
            from scanner.lineage.orchestrator import CrossToolLineageOrchestrator
        except ImportError:
            return UnifiedLineageResponse(
                success=False,
                errors=["Cross-tool lineage orchestrator not available"]
            )

    # Convert request integrations to dict format
    integrations = [
        {
            "id": i.id,
            "type": i.type,
            "status": i.status,
            "config": i.config,
        }
        for i in request.integrations
    ]

    # Run the orchestrator
    orchestrator = CrossToolLineageOrchestrator(
        organization_id=request.organization_id,
        integrations=integrations,
        dbt_manifest=request.dbt_manifest,
    )

    result = await orchestrator.extract_all()

    # Convert graph to response format
    nodes = []
    for node in result.graph.nodes.values():
        nodes.append(LineageNodeResponse(
            id=node.id,
            name=node.name,
            fqn=node.fqn,
            node_type=node.node_type.value,
            database=node.database,
            schema=node.schema,
            platform=node.platform,
            description=node.description,
            criticality=node.criticality,
            row_count=node.row_count,
            columns=node.columns,
            upstream_count=node.upstream_count,
            downstream_count=node.downstream_count,
        ))

    edges = []
    for edge in result.graph.edges.values():
        edges.append(LineageEdgeResponse(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            edge_type=edge.edge_type.value,
            columns=edge.columns,
            transformation=edge.transformation[:500] if edge.transformation else None,
            discovered_from=edge.discovered_from,
        ))

    # Convert extraction results
    extraction_results = [
        ExtractionResultResponse(
            integration_id=r.integration_id,
            integration_type=r.integration_type,
            success=r.success,
            error=r.error,
            node_count=r.node_count,
            edge_count=r.edge_count,
            duration_ms=r.duration_ms,
        )
        for r in result.extraction_results
    ]

    # Convert synthesis stats
    synthesis_stats = None
    if result.synthesis_stats:
        synthesis_stats = SynthesisStatsResponse(
            dbt_source_edges=result.synthesis_stats.dbt_source_edges,
            dbt_model_edges=result.synthesis_stats.dbt_model_edges,
            bi_warehouse_edges=result.synthesis_stats.bi_warehouse_edges,
            view_base_edges=result.synthesis_stats.view_base_edges,
            orchestrator_edges=result.synthesis_stats.orchestrator_edges,
            nodes_merged=result.synthesis_stats.nodes_merged,
            total_edges_created=result.synthesis_stats.total_edges_created,
        )

    return UnifiedLineageResponse(
        success=result.success,
        nodes=nodes,
        edges=edges,
        extraction_results=extraction_results,
        synthesis_stats=synthesis_stats,
        stats={
            "total_nodes": result.total_nodes,
            "total_edges": result.total_edges,
            "duration_ms": result.duration_ms,
            "integrations_processed": len(extraction_results),
        },
        errors=result.errors,
    )


# ==========================================
# LINEAGE ENGINE API (vendor-agnostic)
# ==========================================

class EngineEvidenceResponse(BaseModel):
    """Evidence for a lineage edge."""
    adapter_id: str
    source_ref: str
    observed_at: Optional[str] = None
    snippet: Optional[str] = None


class EngineColumnMappingResponse(BaseModel):
    """Column-level mapping."""
    from_column: str
    to_column: str
    transform_expr: Optional[str] = None
    confidence: float = 1.0


class EngineNodeResponse(BaseModel):
    """Extended node response with engine fields."""
    id: str
    name: str
    fqn: str
    node_type: str
    database: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")
    platform: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    platform_domain: str = "other"
    asset_kind: str = "unknown"
    namespace: Optional[str] = None
    sources: List[str] = []
    integration_id: Optional[str] = None
    dbt_resource_type: Optional[str] = None
    upstream_count: int = 0
    downstream_count: int = 0

    class Config:
        populate_by_name = True


class EngineEdgeResponse(BaseModel):
    """Extended edge response with engine fields."""
    id: str
    source_id: str
    target_id: str
    edge_type: str
    lineage_level: str = "table"
    confidence: float = 1.0
    discovered_from: Optional[str] = None
    evidence: List[EngineEvidenceResponse] = []
    column_mappings: List[EngineColumnMappingResponse] = []


class EngineGraphResponse(BaseModel):
    """Full engine graph response."""
    success: bool
    nodes: List[EngineNodeResponse] = []
    edges: List[EngineEdgeResponse] = []
    stats: Dict[str, Any] = {}
    errors: List[str] = []


class EngineBuildRequest(BaseModel):
    """Request to build a lineage graph from config."""
    config: Dict[str, Any] = Field(..., description="Engine config with adapters, resolver, sql_parser sections")


class CoverageStatsResponse(BaseModel):
    """Coverage statistics."""
    total_nodes: int = 0
    total_edges: int = 0
    edges_by_level: Dict[str, int] = {}
    edges_by_system: Dict[str, int] = {}
    nodes_by_domain: Dict[str, int] = {}
    nodes_by_kind: Dict[str, int] = {}
    high_confidence_pct: float = 0.0
    medium_confidence_pct: float = 0.0
    low_confidence_pct: float = 0.0
    coverage_table: float = 0.0
    coverage_column: float = 0.0
    coverage_tool: float = 0.0


def _node_to_engine_response(node) -> EngineNodeResponse:
    return EngineNodeResponse(
        id=node.id,
        name=node.name,
        fqn=node.fqn,
        node_type=node.node_type.value,
        database=node.database,
        schema=node.schema,
        platform=node.platform,
        description=node.description,
        owner=node.owner,
        platform_domain=node.platform_domain.value,
        asset_kind=node.asset_kind.value,
        namespace=node.namespace,
        sources=node.sources,
        integration_id=node.integration_id,
        dbt_resource_type=node.raw_metadata.get("dbt_resource_type"),
        upstream_count=node.upstream_count,
        downstream_count=node.downstream_count,
    )


def _edge_to_engine_response(edge) -> EngineEdgeResponse:
    return EngineEdgeResponse(
        id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        edge_type=edge.edge_type.value,
        lineage_level=edge.lineage_level.value,
        confidence=edge.confidence,
        discovered_from=edge.discovered_from,
        evidence=[
            EngineEvidenceResponse(
                adapter_id=e.adapter_id,
                source_ref=e.source_ref,
                observed_at=e.observed_at.isoformat() if e.observed_at else None,
                snippet=e.snippet,
            )
            for e in edge.evidence
        ],
        column_mappings=[
            EngineColumnMappingResponse(
                from_column=m.from_column,
                to_column=m.to_column,
                transform_expr=m.transform_expr,
                confidence=m.confidence,
            )
            for m in edge.column_mappings
        ],
    )


# Singleton store for the engine graph (in-memory for now)
_engine_store = None

# Cached engine adapter results — nodes/edges from each extraction, fed to resolver
_engine_collected_results: dict = {"nodes": [], "edges": [], "dbt_manifest": None, "dbt_config": None, "schema_mapping": None}


def _clear_engine_cache():
    """Reset cached results for a fresh extraction run.

    Called before a batch of extractions to prevent stale data from
    previous runs accumulating and causing non-deterministic graphs.
    """
    global _engine_collected_results
    _engine_collected_results = {"nodes": [], "edges": [], "dbt_manifest": None, "dbt_config": None, "schema_mapping": None}


def _get_engine_store():
    global _engine_store
    if _engine_store is None:
        try:
            from lineage.engine.store import GraphStore
        except ImportError:
            from scanner.lineage.engine.store import GraphStore
        _engine_store = GraphStore()
    return _engine_store


def _rebuild_engine_from_cache() -> None:
    """
    Run the resolver pipeline on cached adapter results (no re-parsing).

    Instead of re-running adapters (which re-run parsers and make network calls),
    this takes the already-converted engine nodes/edges and runs only the resolver
    (normalize, deduplicate, merge evidence, weight confidence).
    """
    import logging
    from datetime import datetime
    _logger = logging.getLogger(__name__)
    try:
        try:
            from lineage.engine.resolver import ResolverPipeline, ResolverConfig
        except ImportError:
            from scanner.lineage.engine.resolver import ResolverPipeline, ResolverConfig

        store = _get_engine_store()
        pipeline = ResolverPipeline(ResolverConfig())
        store.graph = pipeline.resolve(
            list(_engine_collected_results["nodes"]),
            list(_engine_collected_results["edges"]),
        )
        store.resolution_stats = pipeline.stats
        store.graph.built_at = datetime.utcnow()

        _logger.info(
            f"[Engine] Built graph: {len(store.graph.nodes)} nodes, "
            f"{len(store.graph.edges)} edges"
        )
        if store.resolution_stats:
            _logger.info(
                f"[Engine] Resolver: {store.resolution_stats.nodes_before} → "
                f"{store.resolution_stats.nodes_after} nodes, "
                f"{store.resolution_stats.edges_before} → "
                f"{store.resolution_stats.edges_after} edges, "
                f"{store.resolution_stats.nodes_deduplicated} deduplicated, "
                f"{store.resolution_stats.edges_merged} merged"
            )

        # --- Cross-tool edge synthesis ---
        dbt_manifest = _engine_collected_results.get("dbt_manifest")
        if dbt_manifest and store.graph:
            try:
                try:
                    from lineage.canonical import CanonicalResolver
                    from lineage.cross_tool import CrossToolEdgeSynthesizer
                except ImportError:
                    from scanner.lineage.canonical import CanonicalResolver
                    from scanner.lineage.cross_tool import CrossToolEdgeSynthesizer

                dbt_cfg = _engine_collected_results.get("dbt_config") or {}
                resolver = CanonicalResolver(
                    default_warehouse=dbt_cfg.get("warehouse_type", "bigquery"),
                    project_id=dbt_cfg.get("namespace", ""),
                )
                resolver.register_dbt_sources(dbt_manifest.get("sources", {}))
                resolver.register_dbt_model_targets(dbt_manifest.get("nodes", {}))

                # Patch dbt node schemas if GitHub-derived schema mapping is available
                schema_mapping = _engine_collected_results.get("schema_mapping")
                if schema_mapping:
                    for node in store.graph.nodes.values():
                        if node.platform == "dbt" and node.name in schema_mapping:
                            corrected = schema_mapping[node.name]
                            if corrected and corrected != node.schema:
                                _logger.debug(f"[Engine] Schema fix: {node.name} {node.schema} → {corrected}")
                                node.schema = corrected

                synthesizer = CrossToolEdgeSynthesizer(
                    graph=store.graph,
                    resolver=resolver,
                    dbt_manifest=dbt_manifest,
                )
                synthesis_stats = synthesizer.synthesize_all()
                _logger.info(
                    f"[Engine] Cross-tool synthesis: {synthesis_stats.total_edges_created} edges, "
                    f"{synthesis_stats.nodes_merged} nodes merged"
                )
            except Exception as synth_err:
                _logger.warning(f"[Engine] Cross-tool synthesis failed (non-fatal): {synth_err}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        _logger.warning(f"[Engine] Failed to build engine graph: {e}")


def _parse_filters(
    level: Optional[str] = None,
    system: Optional[str] = None,
    domain: Optional[str] = None,
    kind: Optional[str] = None,
    min_confidence: float = 0.0,
):
    """Parse query params into a Filters object."""
    try:
        from lineage.engine.store import Filters
        from lineage.graph import LineageLevel, PlatformDomain, AssetKind
    except ImportError:
        from scanner.lineage.engine.store import Filters
        from scanner.lineage.graph import LineageLevel, PlatformDomain, AssetKind

    filters = Filters(min_confidence=min_confidence)
    if level:
        filters.lineage_levels = {LineageLevel(l.strip()) for l in level.split(",")}
    if system:
        filters.systems = set(system.split(","))
    if domain:
        filters.platform_domains = {PlatformDomain(d.strip()) for d in domain.split(",")}
    if kind:
        filters.asset_kinds = {AssetKind(k.strip()) for k in kind.split(",")}
    return filters


@router.post("/lineage/engine/clear-cache")
async def engine_clear_cache():
    """Reset engine cache before a fresh extraction batch.

    The frontend calls this before looping over pipeline nodes so that
    stale data from a previous extraction run doesn't accumulate.
    """
    import logging
    _clear_engine_cache()
    logging.getLogger(__name__).info("[Engine] clear-cache: Reset engine collected results")
    return {"success": True, "message": "Engine cache cleared"}


@router.post("/lineage/engine/build", response_model=EngineGraphResponse)
async def engine_build(request: EngineBuildRequest):
    """Build a lineage graph from engine config."""
    import asyncio

    store = _get_engine_store()
    try:
        graph = await asyncio.to_thread(store.build_graph, request.config)
        coverage = store.get_stats()

        return EngineGraphResponse(
            success=True,
            nodes=[_node_to_engine_response(n) for n in graph.nodes.values()],
            edges=[_edge_to_engine_response(e) for e in graph.edges.values()],
            stats=coverage.to_dict(),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return EngineGraphResponse(success=False, errors=[str(e)])


@router.get("/lineage/engine/upstream/{asset_id}")
async def engine_upstream(
    asset_id: str,
    depth: int = Query(3, ge=1, le=50),
    level: Optional[str] = Query(None, description="Filter: tool,table,column"),
    system: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Get upstream lineage for an asset with filtering."""
    store = _get_engine_store()
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence)
    nodes = store.get_upstream(asset_id, depth=depth, filters=filters)
    return {"asset_id": asset_id, "upstream": [_node_to_engine_response(n).dict() for n in nodes]}


@router.get("/lineage/engine/downstream/{asset_id}")
async def engine_downstream(
    asset_id: str,
    depth: int = Query(3, ge=1, le=50),
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Get downstream lineage for an asset with filtering."""
    store = _get_engine_store()
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence)
    nodes = store.get_downstream(asset_id, depth=depth, filters=filters)
    return {"asset_id": asset_id, "downstream": [_node_to_engine_response(n).dict() for n in nodes]}


@router.get("/lineage/engine/blast-radius/{asset_id}")
async def engine_blast_radius(
    asset_id: str,
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Compute the downstream blast radius of an asset."""
    store = _get_engine_store()
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence)
    return store.blast_radius(asset_id, filters=filters)


@router.get("/lineage/engine/explain-edge/{edge_id}")
async def engine_explain_edge(edge_id: str):
    """Show evidence and reasoning for a specific edge."""
    store = _get_engine_store()
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    result = store.explain_edge(edge_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/lineage/engine/graph")
async def engine_full_graph():
    """Return the full engine graph (nodes + edges with confidence/evidence)."""
    store = _get_engine_store()
    if not store.graph:
        return {"nodes": [], "edges": []}
    return {
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in store.graph.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in store.graph.edges.values()],
    }


@router.get("/lineage/engine/snapshot")
async def engine_snapshot():
    """Return the engine graph serialized for persistence (to store in DB).

    The response includes the full graph dict (nodes + edges with all metadata
    including raw_metadata / dbt_resource_type) so the frontend can save it
    to LineageSnapshot.graphData and restore on server restart.
    """
    store = _get_engine_store()
    if not store.graph or not store.graph.nodes:
        return {"has_graph": False, "graph_data": None}
    return {"has_graph": True, "graph_data": store.graph.to_dict()}


class EngineRestoreRequest(BaseModel):
    """Request to restore the engine graph from a persisted snapshot."""
    graph_data: Dict[str, Any] = Field(..., description="Serialized graph dict from LineageGraph.to_dict()")


@router.post("/lineage/engine/restore")
async def engine_restore(request: EngineRestoreRequest):
    """Restore the engine graph from a previously persisted snapshot.

    Called by the frontend when the in-memory engine graph is empty (after
    server restart) but a snapshot exists in the database.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.graph import LineageGraph
        except ImportError:
            from scanner.lineage.graph import LineageGraph

        graph = LineageGraph.from_dict(request.graph_data)
        store = _get_engine_store()
        store.graph = graph
        _logger.info(
            f"[Engine] Restored graph from snapshot: {len(graph.nodes)} nodes, "
            f"{len(graph.edges)} edges"
        )
        return {
            "success": True,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        _logger.error(f"[Engine] Failed to restore graph: {e}")
        return {"success": False, "error": str(e)}


@router.get("/lineage/engine/stats", response_model=CoverageStatsResponse)
async def engine_stats():
    """Get coverage statistics for the built lineage graph."""
    store = _get_engine_store()
    if not store.graph:
        return CoverageStatsResponse()

    coverage = store.get_stats()
    return CoverageStatsResponse(**coverage.to_dict())


@router.get("/lineage/engine/export")
async def engine_export(
    fmt: str = Query("json", description="Format: json, graphml, dot"),
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Export the lineage graph in various formats."""
    store = _get_engine_store()
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    try:
        from lineage.engine.export import export_json, export_graphml, export_dot
    except ImportError:
        from scanner.lineage.engine.export import export_json, export_graphml, export_dot

    filters = _parse_filters(level, system, min_confidence=min_confidence)

    if fmt == "graphml":
        content = export_graphml(store.graph, filters)
        return {"format": "graphml", "content": content}
    elif fmt == "dot":
        content = export_dot(store.graph, filters)
        return {"format": "dot", "content": content}
    else:
        content = export_json(store.graph, filters)
        return {"format": "json", "content": content}
