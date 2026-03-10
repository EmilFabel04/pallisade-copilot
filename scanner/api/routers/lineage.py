"""
Lineage extraction API router.

Extracts lineage from connected warehouses and returns a graph.
"""

from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

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
        elif integration_type == "AIRFLOW":
            return await extract_airflow_lineage(config, options, integration_id)
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
    source_mode = config.get("source_mode", "")

    # Check source_mode first — project and github modes take priority over stale manifest
    # If dbt Core with project folder upload, parse raw project files
    if source_mode == "project" and config.get("project_files"):
        project_files = config.get("project_files")
        if project_files and isinstance(project_files, dict):
            try:
                try:
                    from lineage.dbt_project_parser import parse_dbt_project
                except ImportError:
                    from scanner.lineage.dbt_project_parser import parse_dbt_project

                manifest = parse_dbt_project(
                    files=project_files,
                    project_name=config.get("project_name", ""),
                    warehouse_type=config.get("warehouse_type", "bigquery"),
                )
                if manifest and (manifest.get("nodes") or manifest.get("sources")):
                    logger.info(f"[dbt] Parsed project files: {len(manifest.get('nodes', {}))} models, {len(manifest.get('sources', {}))} sources")
                else:
                    logger.warning("[dbt] Project files contained no models or sources")
                    manifest = None
            except Exception as parse_err:
                logger.warning(f"[dbt] Project files parsing failed: {parse_err}")

    # If dbt Core with GitHub source mode, fetch raw project files from repo
    if not manifest and source_mode == "github":
        github_token = config.get("github", {}).get("token") or config.get("github_token")
        github_repo = config.get("github_repo")
        if github_token and github_repo:
            try:
                try:
                    from lineage.github_reader import fetch_dbt_project_files
                    from lineage.dbt_project_parser import parse_dbt_project
                except ImportError:
                    from scanner.lineage.github_reader import fetch_dbt_project_files
                    from scanner.lineage.dbt_project_parser import parse_dbt_project

                project_files = await fetch_dbt_project_files(
                    repo=github_repo,
                    token=github_token,
                    branch=config.get("github_branch", "main"),
                    dbt_root=config.get("dbt_project_path", ""),
                )
                if project_files:
                    manifest = parse_dbt_project(
                        files=project_files,
                        project_name=config.get("project_name", ""),
                        warehouse_type=config.get("warehouse_type", "bigquery"),
                    )
                    logger.info(f"[dbt] Parsed GitHub project: {len(manifest.get('nodes', {}))} models, {len(manifest.get('sources', {}))} sources")
                else:
                    logger.warning(f"[dbt] No project files found in GitHub repo: {github_repo}")
            except Exception as gh_err:
                logger.warning(f"[dbt] GitHub project fetch failed: {gh_err}")

    # Fallback: manifest provided directly in config (upload mode or legacy)
    if not manifest and source_mode in ("upload", ""):
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


async def extract_airflow_lineage(
    config: Dict[str, Any], options: Dict[str, Any], integration_id: Optional[str] = None
) -> LineageResponse:
    """Extract lineage from Airflow (static DAG parsing or API mode)."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.engine.adapters.live_airflow import LiveAirflowAdapter
        except ImportError:
            from scanner.lineage.engine.adapters.live_airflow import LiveAirflowAdapter
    except ImportError:
        return LineageResponse(
            success=False,
            errors=["LiveAirflowAdapter not available"]
        )

    # Determine mode: API if base_url present, otherwise static (DAG file parsing)
    base_url = config.get("base_url") or config.get("host")
    dag_files: Dict[str, str] = {}

    if base_url:
        mode = "api"
    else:
        mode = "static"
        # If GitHub config is attached, fetch DAG .py files from repo
        github_config = config.get("github")
        if github_config and github_config.get("repo") and github_config.get("token"):
            dag_directory = config.get("dag_directory") or github_config.get("dag_directory", "dags")
            try:
                dag_files = await _fetch_dag_files_from_github(
                    repo=github_config["repo"],
                    token=github_config["token"],
                    branch=github_config.get("branch", "main"),
                    dag_directory=dag_directory,
                )
                logger.info(f"[Airflow] Fetched {len(dag_files)} DAG files from GitHub ({dag_directory}/)")
            except Exception as gh_err:
                logger.warning(f"[Airflow] GitHub DAG fetch failed: {gh_err}")

        # Also check for inline dag_files in config (e.g. from local upload)
        if not dag_files and config.get("dag_files"):
            dag_files = config["dag_files"]

        if not dag_files:
            return LineageResponse(
                success=False,
                errors=["No DAG files available. Connect a GitHub repo with DAG files or provide an Airflow API URL."]
            )

    namespace = config.get("namespace") or config.get("instance_name") or "airflow"
    adapter_id = f"airflow_{namespace}"

    adapter = LiveAirflowAdapter(adapter_id=adapter_id)
    adapter_config: Dict[str, Any] = {
        "mode": mode,
        "namespace": namespace,
        "integration_id": integration_id,
    }

    if mode == "api":
        adapter_config["base_url"] = base_url
        adapter_config["username"] = config.get("username") or config.get("user")
        adapter_config["password"] = config.get("password")
    else:
        adapter_config["dag_files"] = dag_files

    try:
        engine_nodes = adapter.discover_assets(adapter_config)
        engine_edges = adapter.extract_lineage(adapter_config)

        _engine_collected_results["nodes"].extend(engine_nodes)
        _engine_collected_results["edges"].extend(engine_edges)
        _rebuild_engine_from_cache()

        logger.info(
            f"[Airflow] Extracted {len(engine_nodes)} nodes, {len(engine_edges)} edges "
            f"(mode={mode}, namespace={namespace})"
        )

        # Convert to response format
        nodes_resp = []
        for node in engine_nodes:
            nodes_resp.append(LineageNodeResponse(
                id=node.id,
                name=node.name,
                fqn=node.fqn,
                node_type=node.node_type.value,
                database=node.database,
                schema=node.schema,
                platform=node.platform,
                description=node.description,
            ))

        edges_resp = []
        for edge in engine_edges:
            edges_resp.append(LineageEdgeResponse(
                id=edge.id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                edge_type=edge.edge_type.value,
                discovered_from=edge.discovered_from,
            ))

        return LineageResponse(
            success=True,
            nodes=nodes_resp,
            edges=edges_resp,
            stats={
                "node_count": len(nodes_resp),
                "edge_count": len(edges_resp),
                "mode": mode,
                "dag_files_parsed": len(dag_files) if mode == "static" else 0,
            },
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return LineageResponse(success=False, errors=[str(e)])


async def _fetch_dag_files_from_github(
    repo: str, token: str, branch: str, dag_directory: str
) -> Dict[str, str]:
    """Fetch .py DAG files from a GitHub repo directory."""
    import aiohttp
    import base64

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_base = "https://api.github.com"

    dag_files: Dict[str, str] = {}

    async with aiohttp.ClientSession() as session:
        # List files in the DAG directory
        list_url = f"{api_base}/repos/{repo}/contents/{dag_directory}?ref={branch}"
        async with session.get(list_url, headers=headers) as resp:
            if resp.status == 404:
                # Directory doesn't exist — no DAGs in this repo
                return {}
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"GitHub API error listing {dag_directory}: {resp.status} {error_text}")
            items = await resp.json()

        # Filter to .py files
        py_files = [item for item in items if item.get("name", "").endswith(".py") and item.get("type") == "file"]

        # Fetch each file's content
        for item in py_files:
            file_url = f"{api_base}/repos/{repo}/contents/{item['path']}?ref={branch}"
            async with session.get(file_url, headers=headers) as resp:
                if resp.status != 200:
                    continue
                file_data = await resp.json()
                content_b64 = file_data.get("content", "")
                content = base64.b64decode(content_b64).decode("utf-8")
                dag_files[item["name"]] = content

    return dag_files


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
    # Rich metadata for detail panel
    columns: List[Dict[str, Any]] = []
    row_count: Optional[int] = None
    tags: List[str] = []
    criticality: str = "medium"
    canonical_type: Optional[str] = None
    raw_metadata: Dict[str, Any] = {}

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
    plane: str = "data"
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
    edges_by_plane: Dict[str, int] = {}
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
        columns=node.columns or [],
        row_count=node.row_count,
        tags=node.tags or [],
        criticality=getattr(node, "criticality", "medium") or "medium",
        canonical_type=node.canonical_type,
        raw_metadata=node.raw_metadata or {},
    )


def _edge_to_engine_response(edge) -> EngineEdgeResponse:
    return EngineEdgeResponse(
        id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        edge_type=edge.edge_type.value,
        lineage_level=edge.lineage_level.value,
        confidence=edge.confidence,
        plane=edge.plane.value,
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


# Per-pipeline stores for the engine graph (keyed by stack_id)
_engine_stores: dict = {}
_run_registries: dict = {}

# Per-pipeline cached engine adapter results — nodes/edges from each extraction
_engine_collected_results_map: dict = {}

_EMPTY_COLLECTED = lambda: {"nodes": [], "edges": [], "dbt_manifest": None, "dbt_config": None, "schema_mapping": None}

# Track the "current" stack_id for extraction endpoints that accumulate results
_current_stack_id: str = "default"


def _get_collected_results(stack_id: str | None = None) -> dict:
    key = stack_id or _current_stack_id
    if key not in _engine_collected_results_map:
        _engine_collected_results_map[key] = _EMPTY_COLLECTED()
    return _engine_collected_results_map[key]


# Backwards-compatible global alias so existing extraction code can reference it
class _CollectedResultsProxy:
    """Proxy that delegates to per-stack collected results."""
    def __getitem__(self, key):
        return _get_collected_results()[key]
    def __setitem__(self, key, value):
        _get_collected_results()[key] = value
    def get(self, key, default=None):
        return _get_collected_results().get(key, default)

_engine_collected_results = _CollectedResultsProxy()


def _clear_engine_cache(stack_id: str | None = None):
    """Reset cached results for a fresh extraction run.

    Called before a batch of extractions to prevent stale data from
    previous runs accumulating and causing non-deterministic graphs.
    """
    key = stack_id or _current_stack_id
    _engine_collected_results_map[key] = _EMPTY_COLLECTED()


def _get_engine_store(stack_id: str | None = None):
    key = stack_id or "default"
    if key not in _engine_stores:
        try:
            from lineage.engine.store import GraphStore
        except ImportError:
            from scanner.lineage.engine.store import GraphStore
        _engine_stores[key] = GraphStore()
    return _engine_stores[key]


def _get_run_registry(stack_id: str | None = None):
    key = stack_id or "default"
    if key not in _run_registries:
        try:
            from lineage.engine.run_registry import RunRegistry
        except ImportError:
            from scanner.lineage.engine.run_registry import RunRegistry
        _run_registries[key] = RunRegistry()
    return _run_registries[key]


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

        store = _get_engine_store(_current_stack_id)
        pipeline = ResolverPipeline(ResolverConfig())
        store.graph = pipeline.resolve(
            list(_get_collected_results()["nodes"]),
            list(_get_collected_results()["edges"]),
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
        # Runs for ALL pipelines (not just when dbt is present) so that
        # ingestion→warehouse POPULATES edges are always synthesized.
        if store.graph:
            try:
                try:
                    from lineage.canonical import CanonicalResolver
                    from lineage.cross_tool import CrossToolEdgeSynthesizer
                except ImportError:
                    from scanner.lineage.canonical import CanonicalResolver
                    from scanner.lineage.cross_tool import CrossToolEdgeSynthesizer

                dbt_manifest = _get_collected_results().get("dbt_manifest")
                dbt_cfg = _get_collected_results().get("dbt_config") or {}
                resolver = CanonicalResolver(
                    default_warehouse=dbt_cfg.get("warehouse_type", "bigquery"),
                    project_id=dbt_cfg.get("namespace", ""),
                )
                if dbt_manifest:
                    resolver.register_dbt_sources(dbt_manifest.get("sources", {}))
                    resolver.register_dbt_model_targets(dbt_manifest.get("nodes", {}))

                # Patch dbt node schemas if GitHub-derived schema mapping is available
                schema_mapping = _get_collected_results().get("schema_mapping")
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

        # Apply canonical type mapping after all synthesis is done
        store.canonicalize()

        # --- Bridge rules: fill structural gaps (e.g. missing ingestion → raw writes) ---
        try:
            try:
                from lineage.engine.bridge import BridgeRuleEngine
            except ImportError:
                from scanner.lineage.engine.bridge import BridgeRuleEngine

            bridge_engine = BridgeRuleEngine(store.graph)
            bridge_result = bridge_engine.apply_all()
            if bridge_result.total_changes > 0:
                _logger.info(
                    f"[Engine] Bridge rules: +{len(bridge_result.added_nodes)} nodes, "
                    f"+{len(bridge_result.added_edges)} edges"
                )
                # Re-canonicalize so bridge-added nodes get canonical types
                store.canonicalize()
        except Exception as bridge_err:
            _logger.warning(f"[Engine] Bridge rules failed (non-fatal): {bridge_err}")

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
    plane: Optional[str] = None,
):
    """Parse query params into a Filters object."""
    try:
        from lineage.engine.store import Filters
        from lineage.graph import LineageLevel, LinePlane, PlatformDomain, AssetKind
    except ImportError:
        from scanner.lineage.engine.store import Filters
        from scanner.lineage.graph import LineageLevel, LinePlane, PlatformDomain, AssetKind

    filters = Filters(min_confidence=min_confidence)
    if level:
        filters.lineage_levels = {LineageLevel(l.strip()) for l in level.split(",")}
    if system:
        filters.systems = set(system.split(","))
    if domain:
        filters.platform_domains = {PlatformDomain(d.strip()) for d in domain.split(",")}
    if kind:
        filters.asset_kinds = {AssetKind(k.strip()) for k in kind.split(",")}
    if plane:
        filters.planes = {LinePlane(p.strip()) for p in plane.split(",")}
    return filters


@router.post("/lineage/engine/clear-cache")
async def engine_clear_cache(stack_id: Optional[str] = Query(None)):
    """Reset engine cache before a fresh extraction batch.

    The frontend calls this before looping over pipeline nodes so that
    stale data from a previous extraction run doesn't accumulate.
    Also clears the in-memory graph and run registry so stale views
    are never served after lineage is deleted.
    """
    import logging
    global _current_stack_id
    if stack_id:
        _current_stack_id = stack_id
    _clear_engine_cache(stack_id)

    # Clear in-memory graph
    store = _get_engine_store(stack_id)
    store.graph = None
    store.tool_nodes = []

    # Clear run registry so stale pre-computed views are not served
    registry = _get_run_registry(stack_id)
    registry._runs.clear()
    registry._current_run_id = None

    logging.getLogger(__name__).info(f"[Engine] clear-cache: Reset engine store for stack_id={stack_id or 'default'}")
    return {"success": True, "message": "Engine cache cleared"}


@router.post("/lineage/engine/build", response_model=EngineGraphResponse)
async def engine_build(request: EngineBuildRequest, stack_id: Optional[str] = Query(None)):
    """Build a lineage graph from engine config."""
    import asyncio

    store = _get_engine_store(stack_id)
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
    stack_id: Optional[str] = Query(None),
):
    """Get upstream lineage for an asset with filtering."""
    store = _get_engine_store(stack_id)
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
    stack_id: Optional[str] = Query(None),
):
    """Get downstream lineage for an asset with filtering."""
    store = _get_engine_store(stack_id)
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
    stack_id: Optional[str] = Query(None),
):
    """Compute the downstream blast radius of an asset."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence)
    return store.blast_radius(asset_id, filters=filters)


@router.get("/lineage/engine/explain-edge/{edge_id}")
async def engine_explain_edge(edge_id: str, stack_id: Optional[str] = Query(None)):
    """Show evidence and reasoning for a specific edge."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    result = store.explain_edge(edge_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/lineage/engine/graph")
async def engine_full_graph(
    plane: Optional[str] = Query(None, description="Filter edges by plane: data,control,cross"),
    stack_id: Optional[str] = Query(None),
):
    """Return the full engine graph (nodes + edges with confidence/evidence)."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return {"nodes": [], "edges": []}

    edges = store.graph.edges.values()
    if plane:
        try:
            from lineage.graph import LinePlane
        except ImportError:
            from scanner.lineage.graph import LinePlane
        allowed = {LinePlane(p.strip()) for p in plane.split(",")}
        edges = [e for e in edges if e.plane in allowed]

    return {
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in store.graph.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in edges],
    }


@router.get("/lineage/engine/snapshot")
async def engine_snapshot(stack_id: Optional[str] = Query(None)):
    """Return the engine graph serialized for persistence (to store in DB).

    The response includes the full graph dict (nodes + edges with all metadata
    including raw_metadata / dbt_resource_type) so the frontend can save it
    to LineageSnapshot.graphData and restore on server restart.
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"has_graph": False, "graph_data": None}
    graph_data = store.graph.to_dict()
    graph_data["tool_nodes"] = store.tool_nodes or []
    return {"has_graph": True, "graph_data": graph_data}


class EngineRestoreRequest(BaseModel):
    """Request to restore the engine graph from a persisted snapshot."""
    graph_data: Dict[str, Any] = Field(..., description="Serialized graph dict from LineageGraph.to_dict()")


@router.post("/lineage/engine/restore")
async def engine_restore(request: EngineRestoreRequest, stack_id: Optional[str] = Query(None)):
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
        store = _get_engine_store(stack_id)
        store.graph = graph
        store.tool_nodes = request.graph_data.get("tool_nodes", [])
        _logger.info(
            f"[Engine] Restored graph from snapshot: {len(graph.nodes)} nodes, "
            f"{len(graph.edges)} edges, {len(store.tool_nodes)} tool_nodes"
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


@router.get("/lineage/engine/control-plane/{dag_id}")
async def engine_control_plane(dag_id: str, stack_id: Optional[str] = Query(None)):
    """Return the control-plane subgraph for a specific DAG.

    Returns the DAG node, its tasks, internal dependency edges, and
    cross-link edges to data-plane assets.
    """
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    sub = store.get_control_plane_subgraph(dag_id)
    if not sub.nodes:
        raise HTTPException(status_code=404, detail=f"DAG '{dag_id}' not found in graph.")

    return {
        "dag_id": dag_id,
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in sub.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in sub.edges.values()],
        "stats": {
            "total_nodes": len(sub.nodes),
            "total_edges": len(sub.edges),
            "task_count": sum(1 for n in sub.nodes.values() if n.node_type.value == "task"),
            "cross_link_count": sum(1 for e in sub.edges.values() if e.plane.value == "cross"),
        },
    }


@router.get("/lineage/engine/control-plane")
async def engine_control_plane_all(stack_id: Optional[str] = Query(None)):
    """Return the full control-plane subgraph (all DAGs and tasks)."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return {"nodes": [], "edges": [], "stats": {}}

    sub = store.get_control_plane_subgraph()
    return {
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in sub.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in sub.edges.values()],
        "stats": {
            "total_nodes": len(sub.nodes),
            "total_edges": len(sub.edges),
        },
    }


@router.get("/lineage/engine/cross-links/{asset_id}")
async def engine_cross_links(asset_id: str, stack_id: Optional[str] = Query(None)):
    """Return cross-plane edges for a data asset (links to orchestration)."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    cross_edges = store.get_cross_links(asset_id)
    # Also return the connected orchestration nodes
    connected_nodes = {}
    for edge in cross_edges:
        other_id = edge.target_id if edge.source_id == asset_id else edge.source_id
        if other_id in store.graph.nodes:
            connected_nodes[other_id] = store.graph.nodes[other_id]

    return {
        "asset_id": asset_id,
        "cross_links": [_edge_to_engine_response(e).dict() for e in cross_edges],
        "connected_nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in connected_nodes.values()],
    }


@router.get("/lineage/engine/run-history/{dag_id}")
async def engine_run_history(
    dag_id: str,
    limit: int = Query(10, ge=1, le=100),
    stack_id: Optional[str] = Query(None),
):
    """Get recent run history for an Airflow DAG.

    Delegates to AirflowIntegration if an adapter is available. Otherwise
    returns whatever run_summary data is stored on the DAG node.
    """
    store = _get_engine_store(stack_id)

    # Try to find run_summary from the DAG node's raw_metadata
    dag_node = None
    if store.graph:
        for node in store.graph.nodes.values():
            if node.node_type.value == "dag" and node.name == dag_id:
                dag_node = node
                break

    run_summary = dag_node.raw_metadata.get("run_summary") if dag_node else None

    return {
        "dag_id": dag_id,
        "run_summary": run_summary,
        "dag_found": dag_node is not None,
    }


@router.get("/lineage/engine/stats", response_model=CoverageStatsResponse)
async def engine_stats(stack_id: Optional[str] = Query(None)):
    """Get coverage statistics for the built lineage graph."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return CoverageStatsResponse()

    coverage = store.get_stats()
    return CoverageStatsResponse(**coverage.to_dict())


@router.get("/lineage/engine/producers")
async def engine_producers(
    dataset_id: Optional[str] = Query(None, description="Filter to a specific dataset"),
    stack_id: Optional[str] = Query(None),
):
    """Return the producer index: for each dataset, which jobs write to it
    and which services run those jobs.

    Reads from the current run's artifacts.  Returns empty dict if no
    run has completed or no producer index was computed.
    """
    registry = _get_run_registry(stack_id)
    if not registry.current_run_id:
        return {"producers": {}, "totalDatasets": 0, "totalProducers": 0}

    record = registry.get_run(registry.current_run_id)
    if not record or not record.artifacts.producer_index:
        return {"producers": {}, "totalDatasets": 0, "totalProducers": 0}

    index = record.artifacts.producer_index

    if dataset_id:
        producers = index.get(dataset_id, [])
        return {
            "producers": {dataset_id: producers} if producers else {},
            "totalDatasets": 1 if producers else 0,
            "totalProducers": len(producers),
        }

    return {
        "producers": index,
        "totalDatasets": len(index),
        "totalProducers": sum(len(v) for v in index.values()),
    }


@router.get("/lineage/engine/export")
async def engine_export(
    fmt: str = Query("json", description="Format: json, graphml, dot"),
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    stack_id: Optional[str] = Query(None),
):
    """Export the lineage graph in various formats."""
    store = _get_engine_store(stack_id)
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


# ==========================================
# CONTROL PLANE OVERVIEW (tool-sequence graph)
# ==========================================


@router.get("/lineage/engine/control-plane-overview")
async def engine_control_plane_overview(stack_id: Optional[str] = Query(None)):
    """
    Return the derived control plane graph showing tool/integration sequence.

    This is different from the per-DAG control plane — it shows the entire
    pipeline architecture: which tools feed into which, in what order.

    Example: Fivetran → Snowflake → dbt → Snowflake → Looker
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"nodes": [], "edges": [], "stats": {"tool_count": 0, "flow_count": 0}}

    try:
        try:
            from lineage.engine.control_plane import build_control_plane_graph
        except ImportError:
            from scanner.lineage.engine.control_plane import build_control_plane_graph

        cp_graph = build_control_plane_graph(store.graph)
        return cp_graph.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Control plane overview failed: {e}")
        return {"nodes": [], "edges": [], "stats": {"tool_count": 0, "flow_count": 0}, "error": str(e)}


# ==========================================
# RENDERED VIEWS (v2 — canonical + deterministic layout)
# ==========================================


class ViewNodeResponse(BaseModel):
    """A node in a rendered view."""
    id: str
    name: str
    canonicalType: str
    originalType: str
    platform: Optional[str] = None
    platformDomain: str = "other"
    layer: str = "WAREHOUSE"
    clusterId: Optional[str] = None
    x: float = 0
    y: float = 0
    inferred: bool = False
    needsMapping: bool = False
    metadata: Dict[str, Any] = {}


class ViewEdgeResponse(BaseModel):
    """An edge in a rendered view."""
    id: str
    sourceId: str
    targetId: str
    canonicalType: str
    originalType: str
    confidence: float = 1.0
    inferred: bool = False
    evidenceCount: int = 0


class ViewClusterResponse(BaseModel):
    """A visual cluster in a rendered view."""
    id: str
    label: str
    platform: Optional[str] = None
    layer: str = "WAREHOUSE"
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    nodeCount: int = 0


class RenderedViewResponse(BaseModel):
    """Full rendered view response."""
    viewType: str
    nodes: List[ViewNodeResponse] = []
    edges: List[ViewEdgeResponse] = []
    clusters: List[ViewClusterResponse] = []
    unmappedNodes: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {}


@router.get("/lineage/engine/views/pipeline-overview")
async def view_pipeline_overview(stack_id: Optional[str] = Query(None)):
    """
    Return the pre-rendered Pipeline Overview view.

    Shows tool/integration instances as service nodes with inter-tool
    data flow edges. Deterministic layout with canonical types.

    Serves from pre-computed run artifacts when available,
    falls back to on-demand computation.
    """
    # Try pre-computed view from run registry
    registry = _get_run_registry(stack_id)
    if registry.current_run_id:
        record = registry.get_run(registry.current_run_id)
        if record and "pipeline_overview" in record.artifacts.views:
            return record.artifacts.views["pipeline_overview"]

    # Fallback: compute on-demand
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return RenderedViewResponse(
            viewType="pipeline_overview",
            stats={"serviceCount": 0, "flowCount": 0, "totalAssets": 0},
        ).dict()

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_pipeline_overview()
        return view.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Pipeline overview view failed: {e}")
        return RenderedViewResponse(
            viewType="pipeline_overview",
            stats={"error": str(e)},
        ).dict()


@router.get("/lineage/engine/views/lane-pipeline-overview")
async def view_lane_pipeline_overview(stack_id: Optional[str] = Query(None)):
    """
    Return the lane-based Pipeline Overview view.

    Renders nodes in fixed lanes:
      ingestion → warehouse_raw → transformation → warehouse_analytics → reporting

    Serves from pre-computed run artifacts when available,
    falls back to on-demand computation.
    """
    # Always compute on-demand to pick up latest code changes and tool_nodes.
    # Pre-computed views from run registry can become stale when tool_nodes
    # are enriched or edge aggregation logic changes.
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.info("[Engine] lane-pipeline-overview: computing on-demand (v2 — evidence-based edges)")
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        _log.info("[Engine] lane-pipeline-overview: empty graph, returning empty response")
        return RenderedViewResponse(
            viewType="lane_pipeline_overview",
            stats={"totalNodes": 0, "totalEdges": 0},
        ).dict()

    _log.info(
        "[Engine] lane-pipeline-overview: graph has %d nodes, %d edges, %d tool_nodes",
        len(store.graph.nodes), len(store.graph.edges), len(store.tool_nodes or []),
    )

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_lane_pipeline_overview()
        _log.info(
            "[Engine] lane-pipeline-overview: result has %d nodes, %d edges",
            len(view.nodes), len(view.edges),
        )
        return view.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Lane pipeline overview failed: {e}")
        import traceback
        traceback.print_exc()
        return RenderedViewResponse(
            viewType="lane_pipeline_overview",
            stats={"error": str(e)},
        ).dict()


@router.get("/lineage/engine/views/tool-details/{tool_view_id:path}")
async def view_tool_details(
    tool_view_id: str,
    stack_id: Optional[str] = Query(None),
):
    """
    Return detailed inspection data for a single tool in the Pipeline Overview.

    The tool_view_id is the ViewNode.id from the lane-pipeline-overview response
    (e.g. "tool:bigquery" or "tool:fivetran:abc123").
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"error": "No graph loaded", "toolId": tool_view_id}

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        return builder.build_tool_details(tool_view_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Tool details failed: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "toolId": tool_view_id}


@router.get("/lineage/engine/views/data-plane")
async def view_data_plane(stack_id: Optional[str] = Query(None)):
    """
    Return the pre-rendered Data Plane view.

    Shows dataset-to-dataset derivation chains with deterministic
    layered layout, canonical types, and cluster grouping.

    Serves from pre-computed run artifacts when available,
    falls back to on-demand computation.
    """
    # Try pre-computed view from run registry
    registry = _get_run_registry(stack_id)
    if registry.current_run_id:
        record = registry.get_run(registry.current_run_id)
        if record and "data_plane" in record.artifacts.views:
            return record.artifacts.views["data_plane"]

    # Fallback: compute on-demand
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return RenderedViewResponse(
            viewType="data_plane",
            stats={"datasetCount": 0, "edgeCount": 0},
        ).dict()

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_data_plane()
        return view.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Data plane view failed: {e}")
        return RenderedViewResponse(
            viewType="data_plane",
            stats={"error": str(e)},
        ).dict()


# ==========================================
# DATA-PLANE NEIGHBOR LOOKUP
# ==========================================


@router.get("/lineage/engine/data-plane/neighbors/{node_id}")
async def data_plane_neighbors(
    node_id: str,
    direction: str = Query("upstream", pattern="^(upstream|downstream)$"),
    depth: int = Query(3, ge=1, le=5),
    limit: int = Query(50, ge=1, le=200),
    stack_id: Optional[str] = Query(None),
):
    """
    Get neighbors of a node in the pre-computed data_plane view.

    Uses the current run's data_plane view edges for adjacency,
    ensuring the detail panel shows the same topology as the
    rendered visualization.

    Falls back to on-demand view build if no pre-computed view exists.
    """
    try:
        from scanner.lineage.engine.views import compute_neighbors_from_view
    except ImportError:
        from lineage.engine.views import compute_neighbors_from_view

    # 1) Try pre-computed data_plane view from current run
    registry = _get_run_registry(stack_id)
    if registry.current_run_id:
        record = registry.get_run(registry.current_run_id)
        if record and "data_plane" in record.artifacts.views:
            view_dict = record.artifacts.views["data_plane"]
            return compute_neighbors_from_view(
                view_dict, node_id, direction, depth, limit,
            )

    # 2) Fallback: compute data_plane view on-demand from engine graph
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {
            "nodeId": node_id,
            "direction": direction,
            "depth": depth,
            "neighbors": [],
            "totalCount": 0,
            "source": "none",
        }

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_data_plane()
        view_dict = view.to_dict()
        result = compute_neighbors_from_view(
            view_dict, node_id, direction, depth, limit,
        )
        result["source"] = "engine_fallback"
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"[Engine] Data-plane neighbors fallback failed: {e}"
        )
        return {
            "nodeId": node_id,
            "direction": direction,
            "depth": depth,
            "neighbors": [],
            "totalCount": 0,
            "source": "error",
        }


# ==========================================
# RUN VERSIONING
# ==========================================


@router.get("/lineage/runs/current")
async def get_current_run(stack_id: Optional[str] = Query(None)):
    """Return the current (published) run_id and its status."""
    registry = _get_run_registry(stack_id)
    if not registry.current_run_id:
        return {"current_run_id": None, "status": None}
    record = registry.get_run(registry.current_run_id)
    if not record:
        return {"current_run_id": None, "status": None}
    return record.to_dict()


@router.get("/lineage/runs/{run_id}/status")
async def get_run_status(run_id: str, stack_id: Optional[str] = Query(None)):
    """Lightweight status for polling a specific run."""
    registry = _get_run_registry(stack_id)
    status = registry.get_run_status(run_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return status


@router.get("/lineage/runs/{run_id}/views/{view_type}")
async def get_run_view(run_id: str, view_type: str, stack_id: Optional[str] = Query(None)):
    """Return a pre-computed view from a specific run."""
    registry = _get_run_registry(stack_id)
    record = registry.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    view = record.artifacts.views.get(view_type)
    if not view:
        raise HTTPException(
            status_code=404,
            detail=f"View '{view_type}' not found for run {run_id}. "
                   f"Available: {list(record.artifacts.views.keys())}",
        )
    return view


@router.get("/lineage/runs")
async def list_runs(limit: int = Query(5, ge=1, le=20), stack_id: Optional[str] = Query(None)):
    """Return recent extraction runs."""
    registry = _get_run_registry(stack_id)
    return {
        "runs": registry.list_runs(limit),
        "current_run_id": registry.current_run_id,
    }


# ==========================================
# RECONCILIATION (LLM-powered graph patching)
# ==========================================


class ReconcileRequest(BaseModel):
    """Request to run LLM reconciliation on the engine graph."""
    provider: str = Field("anthropic", description="LLM provider: anthropic or openai")
    model: Optional[str] = Field(None, description="Model override")
    dry_run: bool = Field(True, description="If true, return patch without applying")


class ReconcilePatchResponse(BaseModel):
    """The reconciliation patch for review."""
    patch_version: str = "1.0"
    merge_suggestions: List[Dict[str, Any]] = []
    add_nodes: List[Dict[str, Any]] = []
    add_edges: List[Dict[str, Any]] = []
    layer_assignments: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, Any]] = []


class ReconcileResponse(BaseModel):
    """Full reconciliation response."""
    success: bool
    patch: ReconcilePatchResponse
    diagnostics: Dict[str, Any] = {}
    applied: Dict[str, int] = {}
    unknowns: List[Dict[str, Any]] = []
    validation_errors: List[str] = []
    duration_ms: int = 0
    run_id: str = ""


@router.get("/lineage/engine/reconcile/diagnostics")
async def engine_reconcile_diagnostics(stack_id: Optional[str] = Query(None)):
    """Return graph diagnostics without calling the LLM.

    Useful for showing the user what issues exist before they
    decide to run the (potentially expensive) LLM reconciliation.
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"diagnostics": {"dataset_roots": [], "disconnected_components": [],
                                "suspected_duplicates": [], "missing_links_hints": []}}

    try:
        try:
            from lineage.engine.reconciler import DiagnosticsBuilder
        except ImportError:
            from scanner.lineage.engine.reconciler import DiagnosticsBuilder

        builder = DiagnosticsBuilder(store.graph)
        diagnostics = builder.build()
        return {"diagnostics": diagnostics.to_dict()}
    except Exception as e:
        return {"diagnostics": {}, "error": str(e)}


@router.post("/lineage/engine/reconcile", response_model=ReconcileResponse)
async def engine_reconcile(request: ReconcileRequest, stack_id: Optional[str] = Query(None)):
    """Run LLM reconciliation on the current engine graph.

    If dry_run=True (default), returns the patch for UI review without applying.
    If dry_run=False, applies the patch immediately.

    Requires a built engine graph (call /lineage/investigate or
    /lineage/engine/build first).
    """
    import logging
    _logger = logging.getLogger(__name__)

    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(404, "No graph built. Extract lineage first.")

    try:
        try:
            from lineage.engine.reconciler import ReconcilerConfig
        except ImportError:
            from scanner.lineage.engine.reconciler import ReconcilerConfig

        config = ReconcilerConfig(
            provider=request.provider,
            model=request.model or (
                "claude-sonnet-4-20250514" if request.provider == "anthropic"
                else "gpt-5.2"
            ),
            dry_run=request.dry_run,
        )

        result = await store.reconcile(config)

        _logger.info(
            f"[Reconciler] {result.run_id}: success={result.success}, "
            f"applied={result.applied}, duration={result.duration_ms}ms"
        )

        return ReconcileResponse(
            success=result.success,
            patch=ReconcilePatchResponse(**result.patch.to_dict()),
            diagnostics=result.diagnostics.to_dict(),
            applied=result.applied,
            unknowns=[
                {"entity_ref": u.entity_ref, "issue": u.issue,
                 "suggested_action": u.suggested_action,
                 "questions": u.questions}
                for u in result.unknowns
            ],
            validation_errors=result.validation_errors,
            duration_ms=result.duration_ms,
            run_id=result.run_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Reconciliation failed: {e}")


class ReconcileApplyRequest(BaseModel):
    """Request to apply a previously-generated reconciliation patch."""
    run_id: str = Field(..., description="Run ID from a previous dry-run")
    patch: Dict[str, Any] = Field(..., description="The patch dict to apply")


@router.post("/lineage/engine/reconcile/apply")
async def engine_reconcile_apply(request: ReconcileApplyRequest, stack_id: Optional[str] = Query(None)):
    """Apply a reconciliation patch that was previously generated with dry_run=True.

    This enables the 'review & confirm' flow:
    1. User triggers reconcile with dry_run=True
    2. UI shows the patch (merges, new nodes, unknowns)
    3. User reviews and clicks 'Apply'
    4. This endpoint applies the approved patch
    """
    import logging
    _logger = logging.getLogger(__name__)

    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(404, "No graph built.")

    try:
        try:
            from lineage.engine.reconciler import (
                ReconciliationPatch, PatchValidator, PatchApplier,
            )
            from lineage.engine.canonical import canonicalize_graph_in_place
        except ImportError:
            from scanner.lineage.engine.reconciler import (
                ReconciliationPatch, PatchValidator, PatchApplier,
            )
            from scanner.lineage.engine.canonical import canonicalize_graph_in_place

        patch = ReconciliationPatch.from_dict(request.patch)

        # Validate
        validator = PatchValidator(store.graph)
        if not validator.validate(patch):
            return {
                "success": False,
                "errors": validator.errors,
                "message": "Patch validation failed",
            }

        # Apply
        applier = PatchApplier(store.graph, request.run_id)
        applied = applier.apply(patch)

        # Re-canonicalize
        canonicalize_graph_in_place(store.graph.nodes, store.graph.edges)

        _logger.info(
            f"[Reconciler] Applied patch {request.run_id}: {applied}"
        )

        return {
            "success": True,
            "applied": applied,
            "total_nodes": len(store.graph.nodes),
            "total_edges": len(store.graph.edges),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ==========================================
# OPENLINEAGE EVENT INGESTION
# ==========================================


class OpenLineageEventRequest(BaseModel):
    """A single OpenLineage RunEvent."""
    eventType: str
    eventTime: str
    run: Dict[str, Any]
    job: Dict[str, Any]
    inputs: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []
    producer: Optional[str] = None


class OpenLineageBatchRequest(BaseModel):
    """Batch of OpenLineage RunEvents."""
    events: List[Dict[str, Any]]


@router.post("/lineage/openlineage/event")
async def ingest_openlineage_event(request: OpenLineageEventRequest):
    """
    Ingest a single OpenLineage RunEvent.

    Maps the event to internal LineageNode/LineageEdge format and adds
    to the engine cache, triggering an incremental graph rebuild.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.engine.openlineage import OpenLineageMapper
        except ImportError:
            from scanner.lineage.engine.openlineage import OpenLineageMapper

        mapper = OpenLineageMapper()
        event_dict = request.dict()
        nodes, edges = mapper.map_event(event_dict)

        _engine_collected_results["nodes"].extend(nodes)
        _engine_collected_results["edges"].extend(edges)
        _rebuild_engine_from_cache()

        _logger.info(
            f"[OpenLineage] Ingested event: {request.job.get('name', '?')} "
            f"({request.eventType}) → {len(nodes)} nodes, {len(edges)} edges"
        )

        return {
            "success": True,
            "nodes_added": len(nodes),
            "edges_added": len(edges),
        }
    except Exception as e:
        _logger.error(f"[OpenLineage] Event ingestion failed: {e}")
        return {"success": False, "error": str(e)}


@router.post("/lineage/openlineage/events")
async def ingest_openlineage_events_batch(request: OpenLineageBatchRequest):
    """
    Ingest a batch of OpenLineage RunEvents.

    Processes all events, accumulates nodes/edges, then rebuilds once.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.engine.openlineage import OpenLineageMapper
        except ImportError:
            from scanner.lineage.engine.openlineage import OpenLineageMapper

        mapper = OpenLineageMapper()
        total_nodes = 0
        total_edges = 0
        errors = []

        for i, event in enumerate(request.events):
            try:
                nodes, edges = mapper.map_event(event)
                _engine_collected_results["nodes"].extend(nodes)
                _engine_collected_results["edges"].extend(edges)
                total_nodes += len(nodes)
                total_edges += len(edges)
            except Exception as e:
                errors.append(f"Event {i}: {str(e)}")

        _rebuild_engine_from_cache()

        _logger.info(
            f"[OpenLineage] Batch ingested {len(request.events)} events "
            f"→ {total_nodes} nodes, {total_edges} edges, {len(errors)} errors"
        )

        return {
            "success": len(errors) == 0,
            "events_processed": len(request.events),
            "nodes_added": total_nodes,
            "edges_added": total_edges,
            "errors": errors,
        }
    except Exception as e:
        _logger.error(f"[OpenLineage] Batch ingestion failed: {e}")
        return {"success": False, "error": str(e)}


# ==========================================
# GENERIC TOOL EXTRACTION (for new adapters)
# ==========================================


class ToolExtractionRequest(BaseModel):
    """Request to extract lineage from any tool via its adapter."""
    adapter_type: str = Field(..., description="Adapter type name (e.g., live_n8n, live_tableau)")
    config: Dict[str, Any] = Field(..., description="Adapter configuration")
    integration_id: Optional[str] = Field(default=None, description="Pallisade integration ID")


@router.post("/lineage/extract-tool")
async def extract_tool_lineage(request: ToolExtractionRequest):
    """
    Extract lineage from any registered adapter.

    Generic endpoint that routes to any adapter by type name.
    Supports all registered adapters: n8n, Tableau, Power BI, Metabase,
    Databricks, Storage, Elementary, OpenLineage, etc.
    """
    import asyncio
    import logging
    import time
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.engine.adapter import create_default_registry
        except ImportError:
            from scanner.lineage.engine.adapter import create_default_registry

        registry = create_default_registry()
        available = registry.list_types()

        if request.adapter_type not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown adapter type: {request.adapter_type}. Available: {available}",
            )

        adapter_id = f"{request.adapter_type}_{request.integration_id or 'default'}"
        adapter = registry.create(request.adapter_type, adapter_id)

        config = {**request.config}
        if request.integration_id:
            config["integration_id"] = request.integration_id

        start = time.time()

        def run():
            nodes = adapter.discover_assets(config)
            edges = adapter.extract_lineage(config)
            return nodes, edges

        nodes, edges = await asyncio.to_thread(run)

        _engine_collected_results["nodes"].extend(nodes)
        _engine_collected_results["edges"].extend(edges)
        _rebuild_engine_from_cache()

        duration_ms = int((time.time() - start) * 1000)

        _logger.info(
            f"[Engine] {request.adapter_type}: {len(nodes)} nodes, "
            f"{len(edges)} edges in {duration_ms}ms"
        )

        return {
            "success": True,
            "adapter_type": request.adapter_type,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "duration_ms": duration_ms,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ==========================================
# LINEAGE INVESTIGATOR (context-accumulating)
# ==========================================


class InvestigateToolConfig(BaseModel):
    """Configuration for a single tool in the investigation."""
    tool_type: str = Field(..., description="Tool type: bigquery, dbt_cloud, n8n, etc.")
    config: Dict[str, Any] = Field(..., description="Decrypted integration config")
    integration_id: Optional[str] = Field(default=None)
    layer: Optional[str] = Field(default=None)
    adapter_type: Optional[str] = Field(default=None)


class InvestigateRequest(BaseModel):
    """Request to run a full lineage investigation."""
    organization_id: str
    tool_configs: List[InvestigateToolConfig]
    options: Optional[Dict[str, Any]] = None


class InvestigateResponse(BaseModel):
    """Response from lineage investigation."""
    success: bool
    nodes: List[EngineNodeResponse] = []
    edges: List[EngineEdgeResponse] = []
    investigation: Dict[str, Any] = {}
    stats: Dict[str, Any] = {}
    errors: List[str] = []


async def _preprocess_dbt_configs(tool_configs, logger_instance=None) -> None:
    """Resolve dbt_core tool configs in-place: parse project files or fetch manifest.

    Shared helper used by all investigate/extract endpoints to avoid
    code duplication. Handles project-upload and GitHub source modes,
    with a manifest.json fallback when project files are empty.
    """
    import logging
    _log = logger_instance or logging.getLogger(__name__)

    try:
        from lineage.dbt_project_parser import parse_dbt_project
    except ImportError:
        from scanner.lineage.dbt_project_parser import parse_dbt_project

    try:
        from lineage.github_reader import fetch_dbt_project_files_with_fallback
    except ImportError:
        from scanner.lineage.github_reader import fetch_dbt_project_files_with_fallback

    # Extract warehouse database/project_id from sibling tool configs
    # so dbt models get the correct namespace for cross-domain dedup
    warehouse_database = ""
    for tc in tool_configs:
        tl = tc.tool_type.lower() if hasattr(tc, "tool_type") else ""
        cfg = tc.config if hasattr(tc, "config") else {}
        if tl in ("bigquery", "snowflake", "postgres", "redshift"):
            warehouse_database = cfg.get("project_id") or cfg.get("database") or ""
            if warehouse_database:
                _log.info("[dbt-preprocess] Found warehouse database=%r from %s config", warehouse_database, tl)
                break
    if not warehouse_database:
        _log.warning("[dbt-preprocess] No warehouse project_id/database found in sibling tool configs")

    for tc in tool_configs:
        if tc.tool_type.lower() != "dbt_core":
            continue

        source_mode = tc.config.get("source_mode", "")

        # Skip if manifest exists AND source_mode is upload/unset
        if tc.config.get("manifest") and source_mode in ("upload", ""):
            continue

        # Project folder upload: parse files dict
        if source_mode == "project" and tc.config.get("project_files"):
            try:
                project_files = tc.config["project_files"]
                if isinstance(project_files, dict):
                    manifest = parse_dbt_project(
                        files=project_files,
                        project_name=tc.config.get("project_name", ""),
                        default_database=warehouse_database,
                        warehouse_type=tc.config.get("warehouse_type", "bigquery"),
                    )
                    if manifest and (manifest.get("nodes") or manifest.get("sources")):
                        tc.config["manifest"] = manifest
                        _log.info(f"[dbt-preprocess] Parsed project files: {len(manifest.get('nodes', {}))} models")
            except Exception as parse_err:
                _log.warning(f"[dbt-preprocess] Project files parsing failed: {parse_err}")

        # GitHub mode: fetch project files with manifest.json fallback
        elif source_mode == "github":
            github_token = tc.config.get("github", {}).get("token") or tc.config.get("github_token")
            github_repo = tc.config.get("github_repo")
            if github_token and github_repo:
                try:
                    project_files, fallback_manifest = await fetch_dbt_project_files_with_fallback(
                        repo=github_repo,
                        token=github_token,
                        branch=tc.config.get("github_branch", "main"),
                        dbt_root=tc.config.get("dbt_project_path", ""),
                    )
                    if project_files:
                        manifest = parse_dbt_project(
                            files=project_files,
                            project_name=tc.config.get("project_name", ""),
                            default_database=warehouse_database,
                            warehouse_type=tc.config.get("warehouse_type", "bigquery"),
                        )
                        if manifest and (manifest.get("nodes") or manifest.get("sources")):
                            tc.config["manifest"] = manifest
                            _log.info(f"[dbt-preprocess] Parsed from GitHub: {github_repo} ({len(manifest.get('nodes', {}))} models)")
                    elif fallback_manifest:
                        tc.config["manifest"] = fallback_manifest
                        _log.info(f"[dbt-preprocess] Using manifest.json fallback from GitHub: {github_repo}")
                except Exception as gh_err:
                    _log.warning(f"[dbt-preprocess] GitHub fetch failed: {gh_err}")


async def _preprocess_airflow_configs(tool_configs, logger_instance=None) -> None:
    """Fetch DAG files from GitHub for Airflow configs in-place.

    When Airflow is connected via GitHub (static mode), the config contains
    github.repo / github.token but NOT the actual dag_files.  This function
    fetches the .py DAG files from the repo and injects them into the config
    so LiveAirflowAdapter receives them.
    """
    import logging
    _log = logger_instance or logging.getLogger(__name__)

    for tc in tool_configs:
        tool_type = (tc.tool_type if hasattr(tc, "tool_type") else "").lower()
        if tool_type != "airflow":
            continue

        cfg = tc.config if hasattr(tc, "config") else {}
        _log.info("[airflow-preprocess] Airflow config keys: %s", list(cfg.keys()))

        # Skip if dag_files already populated
        if cfg.get("dag_files"):
            _log.info("[airflow-preprocess] dag_files already present, skipping")
            continue

        # Determine mode: source_mode takes priority over host detection.
        # Config may have BOTH host (API) and github_repo (GitHub) keys —
        # source_mode tells us which the user actually chose.
        source_mode = (cfg.get("source_mode") or "").lower()
        base_url = cfg.get("base_url") or cfg.get("host") or cfg.get("url")

        if source_mode == "api" or (base_url and source_mode not in ("github", "static")):
            _log.info("[airflow-preprocess] API mode (source_mode=%s, base_url=%s), skipping", source_mode, base_url)
            continue  # API mode — no preprocessing needed

        # Fetch from GitHub — check multiple config shapes
        github_config = cfg.get("github") or {}
        github_repo = (
            github_config.get("repo")
            or cfg.get("github_repo")
            or cfg.get("repo")
        )
        github_token = (
            github_config.get("token")
            or cfg.get("github_token")
            or cfg.get("token")
        )

        if not github_repo or not github_token:
            _log.warning(
                "[airflow-preprocess] No GitHub credentials found. "
                "Config has github=%s, github_repo=%s, repo=%s. "
                "Airflow needs either github.repo+token, github_repo+github_token, or API mode.",
                bool(github_config), bool(cfg.get("github_repo")), bool(cfg.get("repo")),
            )
            continue

        if github_repo and github_token:
            dag_directory = (
                cfg.get("dag_directory")
                or github_config.get("dag_directory", "dags")
            )
            branch = github_config.get("branch") or cfg.get("github_branch", "main")
            try:
                dag_files = await _fetch_dag_files_from_github(
                    repo=github_repo,
                    token=github_token,
                    branch=branch,
                    dag_directory=dag_directory,
                )
                if dag_files:
                    cfg["dag_files"] = dag_files
                    _log.info(
                        "[airflow-preprocess] Fetched %d DAG files from GitHub %s/%s",
                        len(dag_files), github_repo, dag_directory,
                    )
                else:
                    _log.warning(
                        "[airflow-preprocess] No .py files found in %s/%s",
                        github_repo, dag_directory,
                    )
            except Exception as gh_err:
                _log.warning("[airflow-preprocess] GitHub DAG fetch failed: %s", gh_err)


def _derive_cp_metadata(tc_layer: str, tc_config: dict, all_tool_configs: list) -> dict:
    """Derive control-plane relationship metadata from a tool's config.

    This is a thin passthrough for config-specified values. The primary CP
    metadata is emitted by drivers directly on graph nodes. This function
    handles the remaining relational cases:
      - VCS managed_tools (injected by frontend)
      - Infrastructure host-matching (cross-tool hostname comparison)
    """
    import logging
    _enrich_log = logging.getLogger(__name__)

    raw_meta: dict = {}
    layer = (tc_layer or "").upper()

    if layer == "VERSION_CONTROL" and tc_config:
        # Frontend injects managed_tools based on which tools have GitHub
        # attachments — pass through to the driver config.
        managed = tc_config.get("managed_tools")
        if isinstance(managed, list) and managed:
            raw_meta["managed_repos"] = [t.lower() for t in managed]

    if layer == "INFRASTRUCTURE" and tc_config:
        # Pass through explicit hosted_tools from config (Linux driver also
        # reads these, but this path covers non-driver code paths).
        for key in ("hosted_tools", "hosted_platforms", "managed_services", "hosted_services"):
            vals = tc_config.get(key)
            if isinstance(vals, list) and vals:
                raw_meta["hosted_platforms"] = vals
                break
        # Fallback: cross-tool host matching
        if "hosted_platforms" not in raw_meta:
            infra_host = (tc_config.get("hostname") or tc_config.get("host") or "").lower()
            if infra_host:
                hosted = []
                for other_tc in all_tool_configs:
                    if other_tc.tool_type.lower() == tc_config.get("_self_tool_type", ""):
                        continue
                    other_cfg = other_tc.config or {}
                    other_host = (
                        other_cfg.get("host") or other_cfg.get("hostname")
                        or other_cfg.get("server") or ""
                    ).lower()
                    if other_host and (other_host == infra_host or infra_host in other_host or other_host in infra_host):
                        hosted.append(other_tc.tool_type.lower())
                if hosted:
                    raw_meta["hosted_platforms"] = hosted

    if raw_meta:
        _enrich_log.info("[CP-Enrich] layer=%s → metadata=%s", layer, raw_meta)

    return raw_meta


@router.post("/lineage/investigate", response_model=InvestigateResponse)
async def investigate_lineage(request: InvestigateRequest, stack_id: Optional[str] = Query(None)):
    """
    Run a sequential lineage investigation across all tools.

    Examines tools in data-flow order (warehouse → ingestion → transformation
    → orchestration → reporting → infrastructure → VCS), accumulating context
    at each step to enable richer cross-tool correlation.
    """
    import logging
    _logger = logging.getLogger(__name__)
    global _current_stack_id
    if stack_id:
        _current_stack_id = stack_id

    try:
        try:
            from lineage.engine.investigator import ToolConfig
        except ImportError:
            from scanner.lineage.engine.investigator import ToolConfig

        # Pre-process tool configs that need GitHub/remote file fetching
        await _preprocess_dbt_configs(request.tool_configs, _logger)
        await _preprocess_airflow_configs(request.tool_configs, _logger)

        tool_configs = [
            ToolConfig(
                tool_type=tc.tool_type,
                config=tc.config,
                integration_id=tc.integration_id,
                layer=tc.layer,
                adapter_type=tc.adapter_type,
            )
            for tc in request.tool_configs
        ]

        # Run the full extraction pipeline (canonicalize → bridge → views → publish)
        try:
            from lineage.engine.pipeline import run_extraction_pipeline, ExtractionPipelineConfig
        except ImportError:
            from scanner.lineage.engine.pipeline import run_extraction_pipeline, ExtractionPipelineConfig

        registry = _get_run_registry(_current_stack_id)
        store = _get_engine_store(_current_stack_id)

        # Build tool_nodes list so Pipeline Overview shows ALL integrated tools
        _VCS_TOOL_TYPES = {"github", "gitlab", "bitbucket"}
        _tool_nodes = []
        for tc in request.tool_configs:
            tn: dict = {
                "tool_type": tc.tool_type,
                "integration_id": tc.integration_id or "",
                "name": tc.tool_type.replace("_", " ").title(),
                "layer": tc.layer or "",
            }
            # Include safe metadata for VCS/control-plane tools (no secrets)
            if tc.tool_type.lower() in _VCS_TOOL_TYPES and tc.config:
                tn["config"] = {
                    "owner": tc.config.get("owner") or tc.config.get("org", ""),
                    "repo": tc.config.get("repo", ""),
                    "repos": tc.config.get("repos") or tc.config.get("repositories", []),
                    "org": tc.config.get("owner") or tc.config.get("org", ""),
                }

            # Derive relationship metadata from config (evidence for CP edges)
            cfg_for_meta = dict(tc.config or {})
            cfg_for_meta["_self_tool_type"] = tc.tool_type.lower()
            raw_meta = _derive_cp_metadata(tc.layer or "", cfg_for_meta, request.tool_configs)
            if raw_meta:
                tn["raw_metadata"] = raw_meta

            _tool_nodes.append(tn)

        pipeline_config = ExtractionPipelineConfig(tool_nodes=_tool_nodes)

        run_id = await run_extraction_pipeline(tool_configs, registry, store, pipeline_config)
        store.tool_nodes = _tool_nodes

        # Build response from run record
        record = registry.get_run(run_id)
        if not record or record.status.value == "failed":
            return InvestigateResponse(
                success=False,
                errors=record.errors if record else ["Pipeline failed"],
            )

        # Convert to response (backward compatible)
        nodes_resp = []
        edges_resp = []
        if store.graph:
            nodes_resp = [_node_to_engine_response(n) for n in store.graph.nodes.values()]
            edges_resp = [_edge_to_engine_response(e) for e in store.graph.edges.values()]

        stats = {**record.artifacts.stats}
        stats["run_id"] = run_id

        _logger.info(
            f"[Investigator] Complete: run_id={run_id}, "
            f"{len(nodes_resp)} nodes, {len(edges_resp)} edges, "
            f"{record.duration_ms}ms"
        )

        return InvestigateResponse(
            success=True,
            nodes=nodes_resp,
            edges=edges_resp,
            investigation=stats,
            stats=stats,
            errors=record.errors,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return InvestigateResponse(
            success=False,
            errors=[str(e)],
        )


class InvestigateLLMRequest(BaseModel):
    """Request to run LLM-enhanced investigation."""
    tool_configs: List[InvestigateToolConfig]
    use_llm_planner: bool = True
    use_llm_reconciler: bool = True
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    pipeline_edges: Optional[List[Dict[str, Any]]] = None


@router.post("/lineage/investigate-llm", response_model=InvestigateResponse)
async def investigate_lineage_llm(request: InvestigateLLMRequest, stack_id: Optional[str] = Query(None)):
    """
    Run LLM-enhanced lineage investigation.

    Extends the standard investigation with:
    1. LLM planner determines optimal adapter execution order
    2. Deterministic bridge rules fix structural gaps (raw tables as sources)
    3. LLM reconciler reviews and patches the graph

    Falls back to heuristic ordering and deterministic bridge rules
    if LLM calls fail.
    """
    import logging
    _logger = logging.getLogger(__name__)
    global _current_stack_id
    if stack_id:
        _current_stack_id = stack_id

    try:
        try:
            from lineage.engine.investigator import ToolConfig
        except ImportError:
            from scanner.lineage.engine.investigator import ToolConfig

        # Pre-process tool configs that need GitHub/remote file fetching
        await _preprocess_dbt_configs(request.tool_configs, _logger)
        await _preprocess_airflow_configs(request.tool_configs, _logger)

        tool_configs = [
            ToolConfig(
                tool_type=tc.tool_type,
                config=tc.config,
                integration_id=tc.integration_id,
                layer=tc.layer,
                adapter_type=tc.adapter_type,
            )
            for tc in request.tool_configs
        ]

        # Run the full extraction pipeline with LLM planner + reconciler
        try:
            from lineage.engine.pipeline import run_extraction_pipeline, ExtractionPipelineConfig
        except ImportError:
            from scanner.lineage.engine.pipeline import run_extraction_pipeline, ExtractionPipelineConfig

        registry = _get_run_registry(_current_stack_id)
        store = _get_engine_store(_current_stack_id)

        # Build tool_nodes list so Pipeline Overview shows ALL integrated tools
        _VCS_TOOL_TYPES_LLM = {"github", "gitlab", "bitbucket"}
        _tool_nodes = []
        for tc in request.tool_configs:
            tn: dict = {
                "tool_type": tc.tool_type,
                "integration_id": tc.integration_id or "",
                "name": tc.tool_type.replace("_", " ").title(),
                "layer": tc.layer or "",
            }
            # Include safe metadata for VCS/control-plane tools (no secrets)
            if tc.tool_type.lower() in _VCS_TOOL_TYPES_LLM and tc.config:
                tn["config"] = {
                    "owner": tc.config.get("owner") or tc.config.get("org", ""),
                    "repo": tc.config.get("repo", ""),
                    "repos": tc.config.get("repos") or tc.config.get("repositories", []),
                    "org": tc.config.get("owner") or tc.config.get("org", ""),
                }

            # Derive relationship metadata from config (evidence for CP edges)
            cfg_for_meta = dict(tc.config or {})
            cfg_for_meta["_self_tool_type"] = tc.tool_type.lower()
            raw_meta = _derive_cp_metadata(tc.layer or "", cfg_for_meta, request.tool_configs)
            if raw_meta:
                tn["raw_metadata"] = raw_meta

            _tool_nodes.append(tn)

        # Resolve LLM API key from environment based on provider
        import os
        _llm_key = os.environ.get(
            "OPENAI_API_KEY" if request.llm_provider == "openai" else "ANTHROPIC_API_KEY"
        )
        _pipeline_edges = request.pipeline_edges or []
        pipeline_config = ExtractionPipelineConfig(
            use_llm_planner=request.use_llm_planner,
            use_llm_reconciler=request.use_llm_reconciler,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            llm_api_key=_llm_key,
            tool_nodes=_tool_nodes,
            pipeline_edges=_pipeline_edges,
        )

        run_id = await run_extraction_pipeline(tool_configs, registry, store, pipeline_config)
        store.tool_nodes = _tool_nodes
        store.pipeline_edges = _pipeline_edges

        # Build response from run record
        record = registry.get_run(run_id)
        if not record or record.status.value == "failed":
            return InvestigateResponse(
                success=False,
                errors=record.errors if record else ["Pipeline failed"],
            )

        nodes_resp = []
        edges_resp = []
        if store.graph:
            nodes_resp = [_node_to_engine_response(n) for n in store.graph.nodes.values()]
            edges_resp = [_edge_to_engine_response(e) for e in store.graph.edges.values()]

        stats = {**record.artifacts.stats}
        stats["run_id"] = run_id

        _logger.info(
            f"[Investigator-LLM] Complete: run_id={run_id}, "
            f"{len(nodes_resp)} nodes, {len(edges_resp)} edges, "
            f"{record.duration_ms}ms"
        )

        return InvestigateResponse(
            success=True,
            nodes=nodes_resp,
            edges=edges_resp,
            investigation=stats,
            stats=stats,
            errors=record.errors,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return InvestigateResponse(
            success=False,
            errors=[str(e)],
        )


# ---------------------------------------------------------------------------
# LLM-Powered Extraction (SSE streaming)
# ---------------------------------------------------------------------------


class LLMExtractRequest(BaseModel):
    """Request for LLM-powered lineage extraction."""
    tool_configs: List[InvestigateToolConfig]
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    tool_nodes: Optional[List[Dict[str, Any]]] = None
    pipeline_edges: Optional[List[Dict[str, Any]]] = None


@router.post("/lineage/extract-llm")
async def extract_lineage_with_llm(request: LLMExtractRequest, stack_id: Optional[str] = Query(None)):
    """
    LLM-powered lineage extraction with SSE streaming progress.

    The LLM acts as an agent that queries each integration via tools,
    reasons about data flow, and builds the lineage graph itself.
    Returns a stream of SSE events showing real-time progress.
    """
    import logging
    _logger = logging.getLogger(__name__)
    global _current_stack_id
    if stack_id:
        _current_stack_id = stack_id

    async def event_stream():
        try:
            try:
                from lineage.engine.investigator import ToolConfig
                from lineage.engine.llm_extractor import LLMExtractorConfig, LLMLineageExtractor
            except ImportError:
                from scanner.lineage.engine.investigator import ToolConfig
                from scanner.lineage.engine.llm_extractor import LLMExtractorConfig, LLMLineageExtractor

            # Pre-process tool configs that need GitHub/remote file fetching
            await _preprocess_dbt_configs(request.tool_configs, _logger)
            await _preprocess_airflow_configs(request.tool_configs, _logger)

            # Build ToolConfig list
            tool_configs = [
                ToolConfig(
                    tool_type=tc.tool_type,
                    config=tc.config,
                    integration_id=tc.integration_id,
                    layer=tc.layer,
                    adapter_type=tc.adapter_type,
                )
                for tc in request.tool_configs
            ]

            # Create extractor
            extractor_config = LLMExtractorConfig(
                provider=request.llm_provider,
                model=request.llm_model,
            )
            extractor = LLMLineageExtractor(extractor_config)

            # Stream extraction events
            graph = None
            views = None
            async for event in extractor.extract(tool_configs, request.tool_nodes or []):
                yield event.to_sse()

                # Capture final graph/views from complete event
                if event.event_type == "complete":
                    graph = event.data.get("graph")
                    views = event.data.get("views")

            # After extraction, persist to registry + store
            if graph:
                try:
                    from scanner.lineage.engine.run_registry import RunArtifacts
                except ImportError:
                    from lineage.engine.run_registry import RunArtifacts

                registry = _get_run_registry(_current_stack_id)
                store = _get_engine_store(_current_stack_id)

                run_id = registry.start_run(
                    [tc.tool_type for tc in request.tool_configs]
                )
                artifacts = RunArtifacts(
                    graph_dict=graph,
                    views=views or {},
                    stats={
                        "total_nodes": graph.get("stats", {}).get("node_count", 0),
                        "total_edges": graph.get("stats", {}).get("edge_count", 0),
                        "extraction_mode": "llm",
                        "run_id": run_id,
                        "views_built": list((views or {}).keys()),
                    },
                )
                registry.complete_run(run_id, artifacts)

                # Update store for backward compat
                try:
                    from scanner.lineage.graph import LineageGraph
                except ImportError:
                    from lineage.graph import LineageGraph
                store.graph = LineageGraph.from_dict(graph)
                store.tool_nodes = request.tool_nodes or []
                store.pipeline_edges = request.pipeline_edges or []

                import json
                yield f"data: {json.dumps({'type': 'persisted', 'data': {'run_id': run_id}})}\n\n"

                _logger.info(f"[LLM-Extract] Persisted run_id={run_id}")

        except Exception as e:
            import json
            import traceback
            traceback.print_exc()
            _logger.error(f"[LLM-Extract] Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
