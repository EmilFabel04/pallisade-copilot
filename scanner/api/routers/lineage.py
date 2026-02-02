"""
Lineage extraction API router.

Extracts lineage from connected warehouses and returns a graph.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

router = APIRouter()


class LineageRequest(BaseModel):
    """Request to extract lineage from a warehouse."""
    integration_type: str = Field(..., description="Type: BIGQUERY, SNOWFLAKE, POSTGRES, etc.")
    config: Dict[str, Any] = Field(..., description="Integration configuration")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Lineage extraction options")


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
    
    try:
        if integration_type == "BIGQUERY":
            return await extract_bigquery_lineage(config, options)
        elif integration_type == "SNOWFLAKE":
            return await extract_snowflake_lineage(config, options)
        elif integration_type == "POSTGRES":
            return await extract_postgres_lineage(config, options)
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


async def extract_bigquery_lineage(config: Dict[str, Any], options: Dict[str, Any]) -> LineageResponse:
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
