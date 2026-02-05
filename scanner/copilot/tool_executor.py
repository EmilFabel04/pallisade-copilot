"""
Co-Pilot Tool Executor

Executes tools against the appropriate integration adapters.
Routes tool calls to the correct backend based on user's integrations.
"""

from typing import Dict, List, Optional, Any, Set
import logging
import json
import asyncio

from .tools import Tool, ToolResult, get_tool_registry
from .context_builder import CopilotContext, IntegrationInfo, TableSchema

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tools against integration adapters.
    
    This class routes tool calls to the appropriate integration
    adapter based on what the user has connected.
    """
    
    def __init__(self, context: CopilotContext):
        """
        Initialize with user context.
        
        Args:
            context: The user's co-pilot context with integrations
        """
        self.context = context
        self._adapters: Dict[str, Any] = {}
        self._initialize_adapters()
    
    def _initialize_adapters(self):
        """Initialize adapters for connected integrations."""
        for integration in self.context.integrations:
            if not integration.is_active:
                continue
            
            try:
                adapter = self._create_adapter(integration)
                if adapter:
                    self._adapters[integration.type] = adapter
            except Exception as e:
                logger.warning(f"Failed to initialize adapter for {integration.type}: {e}")
    
    async def fetch_warehouse_schema(self) -> Dict[str, List[TableSchema]]:
        """
        Fetch schema information from ALL connected warehouses.

        Returns a dict of "WAREHOUSE_TYPE:dataset" -> list of TableSchema objects.
        Uses compound keys so schemas from multiple warehouses don't collide.
        This info is included in the system prompt so models don't need
        to query INFORMATION_SCHEMA themselves.
        """
        schema_info: Dict[str, List[TableSchema]] = {}

        warehouse_types = ["BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT"]
        found_any = False

        for wh_type in warehouse_types:
            if wh_type not in self._adapters:
                continue

            found_any = True
            adapter = self._adapters[wh_type]

            try:
                # Connect if needed
                if not adapter.is_connected:
                    logger.info(f"[Schema Fetch] Connecting to {wh_type}...")
                    connected = adapter.connect()
                    if not connected:
                        logger.error(f"[Schema Fetch] Failed to connect to {wh_type}")
                        continue
                    logger.info(f"[Schema Fetch] Connected to {wh_type}")

                # Resolve datasets — prioritize config, then query hint, then discover
                datasets = self._resolve_datasets(adapter, wh_type)

                # If no datasets configured, try to narrow from user query first
                if not datasets:
                    query_datasets = self._extract_datasets_from_query()
                    if query_datasets:
                        datasets = query_datasets
                        logger.info(f"[Schema Fetch] Extracted dataset from user query for {wh_type}: {datasets}")

                # Last resort: auto-discover from warehouse
                if not datasets:
                    discovered = await self._discover_datasets(adapter, wh_type)
                    # If user query mentions a dataset name, filter to just that one
                    if discovered and self.context.query:
                        query_lower = self.context.query.lower()
                        matched = [d for d in discovered if d.lower() in query_lower]
                        if matched:
                            datasets = matched
                            logger.info(f"[Schema Fetch] Filtered discovered datasets by query for {wh_type}: {datasets}")
                        else:
                            # No match — use first discovered dataset only to avoid timeout
                            datasets = discovered[:1]
                            logger.info(f"[Schema Fetch] No query match for {wh_type}, using first discovered: {datasets}")
                    elif discovered:
                        datasets = discovered[:1]

                if not datasets:
                    logger.error(
                        f"[Schema Fetch] No datasets found for {wh_type}. "
                        f"Config keys tried: datasets, dataset, schema, default_dataset, datasetId. "
                        f"Auto-discovery also returned empty."
                    )
                    continue

                logger.info(f"[Schema Fetch] Fetching schema for {wh_type} datasets: {datasets}")

                # Fetch schema for each dataset (limit to 3 per warehouse to avoid timeout)
                for dataset in datasets[:3]:
                    try:
                        tables = await self._fetch_dataset_schema(adapter, wh_type, dataset)
                        if tables:
                            # Use compound key: "WAREHOUSE_TYPE:dataset"
                            key = f"{wh_type}:{dataset}"
                            schema_info[key] = tables
                            total_cols = sum(len(t.columns) for t in tables)
                            logger.info(f"[Schema Fetch] {wh_type}.{dataset}: {len(tables)} tables, {total_cols} columns")
                        else:
                            logger.warning(f"[Schema Fetch] {wh_type}.{dataset}: no tables found")
                    except Exception as e:
                        logger.error(f"[Schema Fetch] Failed to fetch schema for {wh_type}.{dataset}: {e}")

            except Exception as e:
                logger.error(f"[Schema Fetch] Unexpected error for {wh_type}: {e}", exc_info=True)

        if not found_any:
            logger.warning(
                f"[Schema Fetch] No warehouse adapter found. "
                f"Available adapters: {list(self._adapters.keys())}. "
                f"Integration types: {[i.type for i in self.context.integrations]}"
            )

        if schema_info:
            total_tables = sum(len(tables) for tables in schema_info.values())
            wh_names = set(k.split(':')[0] for k in schema_info.keys())
            logger.info(f"[Schema Fetch] SUCCESS - {len(schema_info)} datasets across {wh_names}, {total_tables} tables total")
        else:
            logger.error("[Schema Fetch] FAILED - no schema data fetched, LLM will not have column info")

        return schema_info

    def _resolve_datasets(self, adapter, adapter_type: str) -> List[str]:
        """
        Resolve dataset names from integration config and adapter attributes.
        Tries multiple config key conventions.
        """
        datasets = []

        # 1. Try from integration config (multiple key conventions)
        for integration in self.context.integrations:
            if integration.type.upper() == adapter_type:
                config = integration.config
                logger.info(f"[Schema Fetch] Config keys for {adapter_type}: {list(config.keys())}")

                # Try 'datasets' (array)
                ds = config.get('datasets', [])
                if ds:
                    datasets = ds if isinstance(ds, list) else [ds]
                    break
                # Try 'dataset' (single string)
                if config.get('dataset'):
                    datasets = [config['dataset']]
                    break
                # Try 'schema' (Snowflake/Postgres convention)
                if config.get('schema'):
                    datasets = [config['schema']]
                    break
                # Try 'default_dataset' (BigQuery alternative)
                if config.get('default_dataset'):
                    datasets = [config['default_dataset']]
                    break
                # Try 'datasetId'
                if config.get('datasetId'):
                    datasets = [config['datasetId']]
                    break
                break

        # 2. Fallback to adapter's own dataset attribute
        if not datasets:
            adapter_dataset = getattr(adapter, 'dataset', None)
            if adapter_dataset:
                logger.info(f"[Schema Fetch] Using adapter.dataset: {adapter_dataset}")
                datasets = [adapter_dataset]

        # 3. For Snowflake, also try adapter's database + schema
        if not datasets and adapter_type == "SNOWFLAKE":
            adapter_schema = getattr(adapter, 'schema', None)
            if adapter_schema:
                datasets = [adapter_schema]

        return datasets

    def _extract_datasets_from_query(self) -> List[str]:
        """
        Try to extract a dataset/schema name from the user's query.

        If the user says "my raw dataset" or "in the analytics schema",
        we can scope the schema fetch to just that dataset.
        """
        query = self.context.query
        if not query:
            return []

        import re
        query_lower = query.lower()

        # Common patterns: "in my raw dataset", "from the analytics schema",
        # "raw data set", "in raw", "the raw dataset"
        patterns = [
            r'\b(?:in|from|the|my)\s+(\w+)\s+(?:dataset|schema|data\s*set)\b',
            r'\b(?:dataset|schema)\s+(\w+)\b',
            r'\b(\w+)\s+(?:dataset|schema)\b',
        ]

        candidates = []
        for pattern in patterns:
            for match in re.finditer(pattern, query_lower):
                candidate = match.group(1)
                # Filter out common words that aren't dataset names
                if candidate not in {'my', 'the', 'a', 'this', 'that', 'each', 'any', 'our', 'your', 'their', 'all', 'default', 'new', 'old', 'entire', 'whole', 'full', 'big', 'small'}:
                    candidates.append(candidate)

        return candidates

    async def _discover_datasets(self, adapter, adapter_type: str) -> List[str]:
        """
        Auto-discover datasets/schemas from the warehouse when none are configured.
        """
        project = getattr(adapter, 'project', None)

        if adapter_type == "BIGQUERY" and project:
            logger.info(f"[Schema Fetch] Auto-discovering datasets from BigQuery project: {project}")
            try:
                discover_query = f"""
                    SELECT schema_name
                    FROM `{project}.INFORMATION_SCHEMA.SCHEMATA`
                    WHERE schema_name NOT LIKE '%INFORMATION_SCHEMA%'
                    LIMIT 10
                """
                result = await asyncio.to_thread(adapter.execute_query, discover_query)
                datasets = [row['schema_name'] for row in result]
                logger.info(f"[Schema Fetch] Discovered BigQuery datasets: {datasets}")
                return datasets
            except Exception as e:
                logger.error(f"[Schema Fetch] BigQuery dataset discovery failed: {e}")

                # Fallback: try listing datasets via the client directly
                try:
                    client = getattr(adapter, '_client', None)
                    if client:
                        bq_datasets = list(client.list_datasets(project=project, max_results=10))
                        datasets = [ds.dataset_id for ds in bq_datasets]
                        logger.info(f"[Schema Fetch] Discovered via client.list_datasets: {datasets}")
                        return datasets
                except Exception as e2:
                    logger.error(f"[Schema Fetch] BigQuery client.list_datasets also failed: {e2}")

        elif adapter_type == "SNOWFLAKE":
            logger.info("[Schema Fetch] Auto-discovering Snowflake schemas")
            try:
                result = await asyncio.to_thread(
                    adapter.execute_query,
                    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME != 'INFORMATION_SCHEMA' LIMIT 10"
                )
                return [row['SCHEMA_NAME'] for row in result]
            except Exception as e:
                logger.error(f"[Schema Fetch] Snowflake schema discovery failed: {e}")

        elif adapter_type in ("POSTGRES", "REDSHIFT"):
            logger.info("[Schema Fetch] Auto-discovering PostgreSQL schemas")
            try:
                result = await asyncio.to_thread(
                    adapter.execute_query,
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast') LIMIT 10"
                )
                return [row['schema_name'] for row in result]
            except Exception as e:
                logger.error(f"[Schema Fetch] PostgreSQL schema discovery failed: {e}")

        return []
    
    async def _fetch_dataset_schema(
        self, 
        adapter, 
        adapter_type: str, 
        dataset: str
    ) -> List[TableSchema]:
        """Fetch table schemas for a single dataset."""
        tables = []
        
        if adapter_type == "BIGQUERY":
            project = getattr(adapter, 'project', None)
            
            # Get list of tables
            tables_query = f"""
                SELECT table_name, table_type
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES`
                WHERE table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY table_name
                LIMIT 50
            """
            table_rows = await asyncio.to_thread(adapter.execute_query, tables_query)
            
            # Get columns for all tables in one query (BigQuery doesn't have description in COLUMNS)
            columns_query = f"""
                SELECT table_name, column_name, data_type
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
                ORDER BY table_name, ordinal_position
            """
            column_rows = await asyncio.to_thread(adapter.execute_query, columns_query)
            
            # Group columns by table
            table_columns: Dict[str, List[Dict]] = {}
            for row in column_rows:
                tbl = row['table_name']
                if tbl not in table_columns:
                    table_columns[tbl] = []
                table_columns[tbl].append({
                    'name': row['column_name'],
                    'type': row['data_type']
                })
            
            # Build TableSchema objects
            for row in table_rows:
                tbl_name = row['table_name']
                tables.append(TableSchema(
                    name=tbl_name,
                    dataset=dataset,
                    columns=table_columns.get(tbl_name, [])
                ))
            
            logger.info(f"BigQuery schema for {dataset}: {len(tables)} tables, columns: {sum(len(t.columns) for t in tables)}")
        
        elif adapter_type == "SNOWFLAKE":
            # Get tables
            tables_query = f"""
                SELECT TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = '{dataset.upper()}'
                ORDER BY TABLE_NAME
                LIMIT 50
            """
            table_rows = await asyncio.to_thread(adapter.execute_query, tables_query)
            
            # Get columns
            columns_query = f"""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COMMENT
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = '{dataset.upper()}'
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """
            column_rows = await asyncio.to_thread(adapter.execute_query, columns_query)
            
            # Group columns by table
            table_columns: Dict[str, List[Dict]] = {}
            for row in column_rows:
                tbl = row['TABLE_NAME']
                if tbl not in table_columns:
                    table_columns[tbl] = []
                table_columns[tbl].append({
                    'name': row['COLUMN_NAME'],
                    'type': row['DATA_TYPE'],
                    'description': row.get('COMMENT', '')
                })
            
            for row in table_rows:
                tbl_name = row['TABLE_NAME']
                tables.append(TableSchema(
                    name=tbl_name,
                    dataset=dataset,
                    columns=table_columns.get(tbl_name, [])
                ))
        
        elif adapter_type == "POSTGRES":
            # Get tables
            tables_query = f"""
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = '{dataset}'
                ORDER BY table_name
                LIMIT 50
            """
            table_rows = await asyncio.to_thread(adapter.execute_query, tables_query)
            
            # Get columns
            columns_query = f"""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = '{dataset}'
                ORDER BY table_name, ordinal_position
            """
            column_rows = await asyncio.to_thread(adapter.execute_query, columns_query)
            
            # Group columns by table
            table_columns: Dict[str, List[Dict]] = {}
            for row in column_rows:
                tbl = row['table_name']
                if tbl not in table_columns:
                    table_columns[tbl] = []
                table_columns[tbl].append({
                    'name': row['column_name'],
                    'type': row['data_type'],
                    'description': ''
                })
            
            for row in table_rows:
                tbl_name = row['table_name']
                tables.append(TableSchema(
                    name=tbl_name,
                    dataset=dataset,
                    columns=table_columns.get(tbl_name, [])
                ))
        
        return tables
    
    def _create_adapter(self, integration: IntegrationInfo) -> Optional[Any]:
        """Create an adapter for an integration type."""
        # Import adapters lazily to avoid circular imports
        integration_type = integration.type.upper()
        
        # Try absolute imports first (for when running from parent dir)
        # Fall back to relative imports (for when running from scanner dir)
        try:
            if integration_type == "SNOWFLAKE":
                try:
                    from adapters.snowflake import SnowflakeAdapter
                except ImportError:
                    from scanner.adapters.snowflake import SnowflakeAdapter
                return SnowflakeAdapter(integration.config)
            
            elif integration_type == "BIGQUERY":
                try:
                    from adapters.bigquery import BigQueryAdapter
                except ImportError:
                    from scanner.adapters.bigquery import BigQueryAdapter
                logger.info(f"Creating BigQuery adapter with config keys: {list(integration.config.keys())}")
                adapter = BigQueryAdapter(integration.config)
                logger.info(f"BigQuery adapter created - project: {adapter.project}, dataset: {adapter.dataset}")
                return adapter
            
            elif integration_type == "POSTGRES":
                try:
                    from adapters.postgres import PostgresAdapter
                except ImportError:
                    from scanner.adapters.postgres import PostgresAdapter
                return PostgresAdapter(integration.config)
            
            elif integration_type in ("DBT_CLOUD", "DBT_CORE"):
                try:
                    from integrations.dbt import DbtIntegration
                except ImportError:
                    from scanner.integrations.dbt import DbtIntegration
                return DbtIntegration(integration.config)
            
            elif integration_type == "AIRFLOW":
                try:
                    from integrations.airflow import AirflowIntegration
                except ImportError:
                    from scanner.integrations.airflow import AirflowIntegration
                return AirflowIntegration(integration.config)
            
            elif integration_type == "DAGSTER":
                try:
                    from integrations.dagster import DagsterIntegration
                except ImportError:
                    from scanner.integrations.dagster import DagsterIntegration
                return DagsterIntegration(integration.config)
            
            elif integration_type == "PREFECT":
                try:
                    from integrations.prefect import PrefectIntegration
                except ImportError:
                    from scanner.integrations.prefect import PrefectIntegration
                return PrefectIntegration(integration.config)
            
            elif integration_type == "FIVETRAN":
                try:
                    from integrations.fivetran import FivetranIntegration
                except ImportError:
                    from scanner.integrations.fivetran import FivetranIntegration
                return FivetranIntegration(integration.config)
            
            elif integration_type == "AIRBYTE":
                try:
                    from integrations.airbyte import AirbyteClient
                except ImportError:
                    from scanner.integrations.airbyte import AirbyteClient
                return AirbyteClient(integration.config)
            
            elif integration_type == "LOOKER":
                try:
                    from integrations.looker import LookerClient
                except ImportError:
                    from scanner.integrations.looker import LookerClient
                return LookerClient(integration.config)
        except Exception as e:
            logger.error(f"Import error for {integration_type}: {e}")
            raise
        
        return None
    
    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """
        Execute a tool with the given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments for the tool
            
        Returns:
            ToolResult with the result or error
        """
        registry = get_tool_registry()
        tool = registry.get_tool(tool_name)
        
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}"
            )
        
        if not tool.is_available(self.context.integration_types):
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' requires integrations that are not connected. Use search_knowledge_base to find expert guidance on this topic instead."
            )
        
        try:
            result = await self._execute_tool(tool, arguments)
            return result
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}")
            return ToolResult(
                success=False,
                error=str(e)
            )
    
    async def _execute_tool(self, tool: Tool, args: Dict[str, Any]) -> ToolResult:
        """Execute a specific tool."""
        
        # Route to appropriate handler
        handler = getattr(self, f"_execute_{tool.name}", None)
        if handler:
            return await handler(args)
        
        # Fallback for unimplemented tools
        return ToolResult(
            success=False,
            error=f"Tool '{tool.name}' is not yet implemented. Use search_knowledge_base to find expert guidance on this topic instead."
        )
    
    # ==========================================
    # LINEAGE TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_get_upstream(self, args: Dict[str, Any]) -> ToolResult:
        """Get upstream dependencies."""
        node_id = args["node_id"]
        depth = args.get("depth", -1)
        
        if not self.context.graph:
            return ToolResult(success=False, error="No lineage graph available")
        
        upstream = self.context.graph.get_upstream(node_id, depth=depth)
        
        return ToolResult(
            success=True,
            data={
                "node_id": node_id,
                "upstream_count": len(upstream),
                "upstream_nodes": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "type": node.node_type.value,
                        "platform": node.platform,
                        "depth": node.depth,
                    }
                    for node in upstream
                ]
            }
        )
    
    async def _execute_get_downstream(self, args: Dict[str, Any]) -> ToolResult:
        """Get downstream dependents."""
        node_id = args["node_id"]
        depth = args.get("depth", -1)
        
        if not self.context.graph:
            return ToolResult(success=False, error="No lineage graph available")
        
        downstream = self.context.graph.get_downstream(node_id, depth=depth)
        
        return ToolResult(
            success=True,
            data={
                "node_id": node_id,
                "downstream_count": len(downstream),
                "downstream_nodes": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "type": node.node_type.value,
                        "platform": node.platform,
                        "depth": node.depth,
                    }
                    for node in downstream
                ]
            }
        )
    
    async def _execute_get_node_details(self, args: Dict[str, Any]) -> ToolResult:
        """Get detailed node information."""
        node_id = args["node_id"]
        
        if not self.context.graph:
            return ToolResult(success=False, error="No lineage graph available")
        
        node = self.context.graph.nodes.get(node_id)
        if not node:
            return ToolResult(success=False, error=f"Node not found: {node_id}")
        
        return ToolResult(
            success=True,
            data=node.to_dict()
        )
    
    async def _execute_search_lineage(self, args: Dict[str, Any]) -> ToolResult:
        """Search for nodes in lineage."""
        import asyncio
        
        query = args["query"].lower()
        node_type = args.get("node_type", "all")
        limit = args.get("limit", 20)
        
        # If we have an in-memory graph, use it
        if self.context.graph and len(self.context.graph.nodes) > 0:
            results = []
            for node in self.context.graph.nodes.values():
                # Filter by type
                if node_type != "all" and node.node_type.value != node_type:
                    continue
                
                # Match query (simple pattern matching)
                if self._matches_pattern(node.name.lower(), query):
                    results.append({
                        "id": node.id,
                        "name": node.name,
                        "type": node.node_type.value,
                        "platform": node.platform,
                        "upstream_count": node.upstream_count,
                        "downstream_count": node.downstream_count,
                    })
                
                if len(results) >= limit:
                    break
            
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "count": len(results),
                    "nodes": results,
                    "source": "lineage_graph"
                }
            )
        
        # No in-memory graph - try to search warehouse metadata directly
        if self._adapters:
            # Use the first available warehouse adapter
            adapter = next(iter(self._adapters.values()), None)
            if adapter:
                try:
                    # Build warehouse-specific lineage query
                    lineage_query = self._build_lineage_search_query(query, adapter, limit)
                    if lineage_query:
                        results = await asyncio.to_thread(adapter.execute_query, lineage_query)
                        serialized = self._serialize_query_results(results[:limit])
                        
                        return ToolResult(
                            success=True,
                            data={
                                "query": query,
                                "count": len(serialized),
                                "nodes": serialized,
                                "source": "warehouse_metadata"
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed to search warehouse for lineage: {e}")
        
        # Fallback: explain that lineage needs to be extracted first
        return ToolResult(
            success=False,
            error="No lineage data available. Use query_warehouse with INFORMATION_SCHEMA to discover table dependencies, or extract lineage first."
        )
    
    def _build_lineage_search_query(self, query: str, adapter, limit: int) -> Optional[str]:
        """Build a warehouse-specific query to search for table dependencies."""
        adapter_type = type(adapter).__name__.upper()
        
        # Clean up the query pattern
        search_pattern = query.replace("*", "%")
        if "%" not in search_pattern:
            search_pattern = f"%{search_pattern}%"
        
        if "BIGQUERY" in adapter_type:
            # For BigQuery, search views and their referenced tables
            project = getattr(adapter, 'project', None)
            dataset = getattr(adapter, 'dataset', None)
            
            if project and dataset:
                return f"""
                    SELECT 
                        table_name,
                        table_type,
                        COALESCE(ddl, '') as definition
                    FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES`
                    WHERE LOWER(table_name) LIKE '{search_pattern}'
                    LIMIT {limit}
                """
        
        elif "SNOWFLAKE" in adapter_type:
            return f"""
                SELECT 
                    TABLE_NAME as table_name,
                    TABLE_TYPE as table_type,
                    ROW_COUNT as row_count
                FROM INFORMATION_SCHEMA.TABLES
                WHERE LOWER(TABLE_NAME) LIKE '{search_pattern}'
                LIMIT {limit}
            """
        
        elif "POSTGRES" in adapter_type:
            return f"""
                SELECT 
                    table_name,
                    table_type,
                    (SELECT reltuples::bigint FROM pg_class WHERE relname = t.table_name) as row_count
                FROM information_schema.tables t
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                AND LOWER(table_name) LIKE '{search_pattern}'
                LIMIT {limit}
            """
        
        return None
    
    def _matches_pattern(self, text: str, pattern: str) -> bool:
        """Simple wildcard pattern matching."""
        if "*" not in pattern:
            return pattern in text
        
        parts = pattern.split("*")
        if not parts[0] and not parts[-1]:
            # *pattern*
            return any(p in text for p in parts if p)
        elif not parts[0]:
            # *pattern
            return text.endswith(parts[-1])
        elif not parts[-1]:
            # pattern*
            return text.startswith(parts[0])
        else:
            # pattern*pattern
            return text.startswith(parts[0]) and text.endswith(parts[-1])
    
    def _serialize_query_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Serialize query results to handle datetime and other non-JSON types."""
        from datetime import datetime, date
        from decimal import Decimal
        
        def serialize_value(val):
            if val is None:
                return None
            elif isinstance(val, (datetime, date)):
                return val.isoformat()
            elif isinstance(val, Decimal):
                return float(val)
            elif isinstance(val, bytes):
                return val.decode('utf-8', errors='replace')
            elif isinstance(val, dict):
                return {k: serialize_value(v) for k, v in val.items()}
            elif isinstance(val, (list, tuple)):
                return [serialize_value(v) for v in val]
            else:
                return val
        
        return [
            {k: serialize_value(v) for k, v in row.items()}
            for row in results
        ]
    
    # ==========================================
    # WAREHOUSE TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_query_warehouse(self, args: Dict[str, Any]) -> ToolResult:
        """Execute a read-only SQL query with column validation."""
        import asyncio

        sql = args["sql"].strip()
        limit = args.get("limit", 100)
        target_warehouse = args.get("warehouse", "").upper().strip()

        # Validate query is SELECT only
        if not sql.upper().startswith("SELECT"):
            return ToolResult(
                success=False,
                error="Only SELECT queries are allowed"
            )

        # Find warehouse adapter — use specified warehouse or infer
        warehouse_types = ["BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT"]
        adapter = None
        adapter_type = None

        if target_warehouse and target_warehouse in self._adapters:
            # User specified which warehouse to query
            adapter = self._adapters[target_warehouse]
            adapter_type = target_warehouse
            logger.info(f"Using specified warehouse: {adapter_type}")
        else:
            # Try to infer from SQL syntax
            inferred = self._infer_warehouse_from_sql(sql)
            if inferred and inferred in self._adapters:
                adapter = self._adapters[inferred]
                adapter_type = inferred
                logger.info(f"Inferred warehouse from SQL: {adapter_type}")
            else:
                # Fallback: use first available
                for wh_type in warehouse_types:
                    if wh_type in self._adapters:
                        adapter = self._adapters[wh_type]
                        adapter_type = wh_type
                        break

        if not adapter:
            logger.warning(f"No warehouse adapter found. Available adapters: {list(self._adapters.keys())}")
            return ToolResult(success=False, error="No warehouse connected. Please ensure your data warehouse is configured in the Pipeline Builder.")

        # Pre-execution column validation against known schema
        validation_warning = self._validate_query_columns(sql)

        try:
            # Connect if not already connected
            if not adapter.is_connected:
                logger.info(f"Connecting to {adapter_type}...")
                connected = adapter.connect()
                if not connected:
                    return ToolResult(success=False, error=f"Failed to connect to {adapter_type}")

            # Add LIMIT if not present
            if "LIMIT" not in sql.upper():
                sql = f"{sql} LIMIT {limit}"

            logger.info(f"Executing query on {adapter_type}: {sql[:100]}...")

            # Execute synchronous adapter method in thread pool
            results = await asyncio.to_thread(adapter.execute_query, sql)

            # Serialize results to handle datetime and other non-JSON types
            serialized_results = self._serialize_query_results(results[:limit])

            logger.info(f"Query returned {len(results)} rows")

            return ToolResult(
                success=True,
                data={
                    "sql": sql,
                    "row_count": len(results),
                    "rows": serialized_results
                }
            )
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            error_msg = str(e)

            # Enrich error with schema hints to help the LLM self-correct
            hint = self._build_column_error_hint(sql, error_msg)
            if hint:
                error_msg = f"{error_msg}\n\n{hint}"
            elif validation_warning:
                error_msg = f"{error_msg}\n\n{validation_warning}"

            return ToolResult(success=False, error=error_msg)

    def _infer_warehouse_from_sql(self, sql: str) -> Optional[str]:
        """
        Try to infer which warehouse the SQL targets from syntax patterns.
        Returns warehouse type string or None.
        """
        sql_upper = sql.strip().upper()

        # BigQuery: backtick-quoted identifiers like `project.dataset.table`
        if '`' in sql:
            return "BIGQUERY"

        # Snowflake: all-uppercase identifiers, or Snowflake-specific functions
        snowflake_hints = ["FLATTEN(", "TRY_TO_", "PARSE_JSON(", "OBJECT_CONSTRUCT("]
        if any(hint in sql_upper for hint in snowflake_hints):
            return "SNOWFLAKE"

        # PostgreSQL: double-quoted lowercase, or pg-specific functions
        pg_hints = ["::TEXT", "::INT", "::TIMESTAMP", "JSONB", "ARRAY_AGG"]
        if any(hint in sql_upper for hint in pg_hints):
            return "POSTGRES"

        return None

    def _validate_query_columns(self, sql: str) -> Optional[str]:
        """
        Validate that columns referenced in the SQL exist in the known schema.

        Returns a warning string if suspicious columns are found, or None if OK.
        This is a best-effort check — it won't catch everything but catches
        obvious hallucinated column names before they hit the warehouse.
        """
        if not self.context.warehouse_schema:
            return None

        import re

        # Build a set of all known column names (lowercased)
        known_columns: Set[str] = set()
        known_tables: Dict[str, Set[str]] = {}  # table_name -> set of column names
        for _schema_key, tables in self.context.warehouse_schema.items():
            for table in tables:
                table_cols = {c['name'].lower() for c in table.columns}
                known_columns.update(table_cols)
                known_tables[table.name.lower()] = table_cols
                # Also index by dataset.table (using table's own dataset, not the compound key)
                known_tables[f"{table.dataset.lower()}.{table.name.lower()}"] = table_cols

        # Extract table names referenced in FROM/JOIN clauses
        from_join_pattern = re.compile(
            r'(?:FROM|JOIN)\s+[`"\[]*([a-zA-Z0-9_.]+)[`"\]]*',
            re.IGNORECASE
        )
        referenced_tables = []
        for match in from_join_pattern.finditer(sql):
            raw_table = match.group(1).lower()
            # Strip project prefix for BigQuery (project.dataset.table -> dataset.table or table)
            parts = raw_table.replace('`', '').split('.')
            referenced_tables.append(parts[-1])  # table name
            if len(parts) >= 2:
                referenced_tables.append(f"{parts[-2]}.{parts[-1]}")  # dataset.table

        if not referenced_tables:
            return None

        # Find which known table(s) are being queried
        target_table_cols: Set[str] = set()
        for ref in referenced_tables:
            if ref in known_tables:
                target_table_cols.update(known_tables[ref])

        if not target_table_cols:
            return None

        # Extract column-like identifiers from SELECT, WHERE, GROUP BY, ORDER BY
        # Remove string literals and comments first
        cleaned_sql = re.sub(r"'[^']*'", '', sql)
        cleaned_sql = re.sub(r'"[^"]*"', '', cleaned_sql)
        # Extract identifiers (word characters, possibly with dots)
        identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', cleaned_sql)

        # SQL keywords to ignore
        sql_keywords = {
            'select', 'from', 'where', 'and', 'or', 'not', 'in', 'is',
            'null', 'as', 'on', 'join', 'left', 'right', 'inner', 'outer',
            'full', 'cross', 'group', 'by', 'order', 'having', 'limit',
            'offset', 'union', 'all', 'distinct', 'case', 'when', 'then',
            'else', 'end', 'asc', 'desc', 'true', 'false', 'between',
            'like', 'ilike', 'exists', 'count', 'sum', 'avg', 'min', 'max',
            'cast', 'coalesce', 'nullif', 'extract', 'date', 'timestamp',
            'interval', 'with', 'recursive', 'insert', 'update', 'delete',
            'create', 'drop', 'alter', 'table', 'view', 'index', 'into',
            'values', 'set', 'top', 'over', 'partition', 'row_number',
            'rank', 'dense_rank', 'lag', 'lead', 'first_value', 'last_value',
            'format', 'concat', 'substring', 'trim', 'lower', 'upper',
            'replace', 'length', 'round', 'floor', 'ceil', 'abs',
            'safe_divide', 'if', 'ifnull', 'string_agg', 'array_agg',
        }

        suspicious = []
        for ident in identifiers:
            ident_lower = ident.lower()
            if ident_lower in sql_keywords:
                continue
            # Skip table/dataset names, aliases, and numeric-looking tokens
            if ident_lower in {t.split('.')[-1] for t in referenced_tables}:
                continue
            # Check if this looks like a column that doesn't exist in the target table
            if (ident_lower not in target_table_cols and
                    ident_lower in known_columns):
                # It exists in another table but not the one being queried
                # Find where it actually exists
                correct_tables = [
                    tbl for tbl, cols in known_tables.items()
                    if ident_lower in cols and '.' not in tbl
                ]
                if correct_tables:
                    suspicious.append(
                        f"Column `{ident}` was not found in the queried table but exists in: {', '.join(correct_tables)}"
                    )

        if suspicious:
            return "SCHEMA WARNING: " + "; ".join(suspicious[:3])

        return None

    def _build_column_error_hint(self, sql: str, error_msg: str) -> Optional[str]:
        """
        When a query fails, try to suggest the correct column names
        from the known schema to help the LLM self-correct.
        """
        if not self.context.warehouse_schema:
            return None

        import re
        error_lower = error_msg.lower()

        # Check for common column-not-found error patterns
        not_found_patterns = [
            r"(?:column|field)\s+[`'\"]?(\w+)[`'\"]?\s+(?:not found|does not exist|unknown)",
            r"unrecognized name:\s+[`'\"]?(\w+)[`'\"]?",
            r"no such column:\s+[`'\"]?(\w+)[`'\"]?",
        ]

        bad_column = None
        for pattern in not_found_patterns:
            match = re.search(pattern, error_lower)
            if match:
                bad_column = match.group(1)
                break

        if not bad_column:
            return None

        # Find which table is being queried and suggest similar column names
        from_pattern = re.compile(
            r'(?:FROM|JOIN)\s+[`"\[]*([a-zA-Z0-9_.]+)[`"\]]*',
            re.IGNORECASE
        )
        for match in from_pattern.finditer(sql):
            raw_table = match.group(1).lower().replace('`', '')
            parts = raw_table.split('.')
            table_name = parts[-1]
            dataset_key = f"{parts[-2]}.{parts[-1]}" if len(parts) >= 2 else None

            # Find this table in schema
            for _schema_key, tables in self.context.warehouse_schema.items():
                for table in tables:
                    if (table.name.lower() == table_name or
                            (dataset_key and f"{table.dataset.lower()}.{table.name.lower()}" == dataset_key)):
                        col_names = [c['name'] for c in table.columns]
                        return (
                            f"HINT: Column `{bad_column}` does not exist in `{table.dataset}.{table.name}`. "
                            f"Available columns are: {', '.join(col_names)}. "
                            f"Please re-run with the correct column name."
                        )

        return None
    
    async def _execute_get_table_stats(self, args: Dict[str, Any]) -> ToolResult:
        """Get table statistics."""
        table_name = args["table_name"]
        
        # Find warehouse adapter
        warehouse_types = ["SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT"]
        adapter = None
        for wh_type in warehouse_types:
            if wh_type in self._adapters:
                adapter = self._adapters[wh_type]
                break
        
        if not adapter:
            return ToolResult(success=False, error="No warehouse connected")
        
        try:
            stats = await adapter.get_table_stats(table_name)
            return ToolResult(success=True, data=stats)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    async def _execute_get_table_dependencies(self, args: Dict[str, Any]) -> ToolResult:
        """Get upstream and downstream dependencies for a table."""
        import asyncio
        
        table_name = args["table_name"]
        direction = args.get("direction", "both")
        
        # Find warehouse adapter
        warehouse_types = ["BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT"]
        adapter = None
        adapter_type = None
        for wh_type in warehouse_types:
            if wh_type in self._adapters:
                adapter = self._adapters[wh_type]
                adapter_type = wh_type
                break
        
        if not adapter:
            return ToolResult(success=False, error="No warehouse connected")
        
        try:
            # Connect if not already connected
            if not adapter.is_connected:
                connected = adapter.connect()
                if not connected:
                    return ToolResult(success=False, error=f"Failed to connect to {adapter_type}")
            
            dependencies = {"upstream": [], "downstream": [], "table": table_name}
            
            if adapter_type == "BIGQUERY":
                dependencies = await self._get_bigquery_dependencies(adapter, table_name, direction)
            elif adapter_type == "SNOWFLAKE":
                dependencies = await self._get_snowflake_dependencies(adapter, table_name, direction)
            elif adapter_type == "POSTGRES":
                dependencies = await self._get_postgres_dependencies(adapter, table_name, direction)
            else:
                return ToolResult(
                    success=False,
                    error=f"Dependency tracking not yet implemented for {adapter_type}"
                )
            
            return ToolResult(success=True, data=dependencies)
            
        except Exception as e:
            logger.error(f"Failed to get table dependencies: {e}")
            return ToolResult(success=False, error=str(e))
    
    async def _get_bigquery_dependencies(self, adapter, table_name: str, direction: str) -> Dict:
        """Get BigQuery table dependencies using INFORMATION_SCHEMA."""
        import asyncio
        
        project = getattr(adapter, 'project', None)
        dataset = getattr(adapter, 'dataset', None)
        
        # Parse table name
        parts = table_name.split('.')
        if len(parts) == 2:
            target_dataset, target_table = parts
        elif len(parts) == 3:
            _, target_dataset, target_table = parts
        else:
            target_dataset = dataset
            target_table = table_name
        
        dependencies = {"upstream": [], "downstream": [], "table": table_name}
        
        # Get views/tables that reference this table (downstream = things that depend on this)
        if direction in ("downstream", "both"):
            try:
                # Query views that reference this table
                downstream_query = f"""
                    SELECT 
                        v.table_name as dependent_name,
                        v.table_type as dependent_type,
                        'view_definition' as source
                    FROM `{project}.{target_dataset}.INFORMATION_SCHEMA.TABLES` v
                    WHERE v.table_type IN ('VIEW', 'MATERIALIZED VIEW')
                    AND v.ddl LIKE '%{target_table}%'
                    AND v.table_name != '{target_table}'
                """
                results = await asyncio.to_thread(adapter.execute_query, downstream_query)
                for row in results:
                    dependencies["downstream"].append({
                        "name": f"{target_dataset}.{row['dependent_name']}",
                        "type": row.get('dependent_type', 'VIEW'),
                        "relationship": "depends_on"
                    })
            except Exception as e:
                logger.warning(f"Failed to get downstream dependencies: {e}")
        
        # For upstream, we need to parse the view definition
        if direction in ("upstream", "both"):
            try:
                # Check if target table is a view
                view_query = f"""
                    SELECT ddl, table_type
                    FROM `{project}.{target_dataset}.INFORMATION_SCHEMA.TABLES`
                    WHERE table_name = '{target_table}'
                """
                results = await asyncio.to_thread(adapter.execute_query, view_query)
                
                if results and results[0].get('table_type') in ('VIEW', 'MATERIALIZED VIEW'):
                    ddl = results[0].get('ddl', '')
                    # Simple extraction of referenced tables from the view DDL
                    # Look for patterns like `dataset.table` or FROM/JOIN clauses
                    import re
                    table_refs = re.findall(r'`([^`]+\.[^`]+)`', ddl)
                    for ref in table_refs:
                        ref_parts = ref.split('.')
                        ref_table = ref_parts[-1] if ref_parts else ref
                        if ref_table != target_table:
                            dependencies["upstream"].append({
                                "name": ref,
                                "type": "TABLE",
                                "relationship": "source"
                            })
            except Exception as e:
                logger.warning(f"Failed to get upstream dependencies: {e}")
        
        return dependencies
    
    async def _get_snowflake_dependencies(self, adapter, table_name: str, direction: str) -> Dict:
        """Get Snowflake table dependencies using OBJECT_DEPENDENCIES."""
        import asyncio
        
        dependencies = {"upstream": [], "downstream": [], "table": table_name}
        
        # Parse table name
        parts = table_name.upper().split('.')
        if len(parts) >= 2:
            schema = parts[-2]
            table = parts[-1]
        else:
            table = table_name.upper()
            schema = None
        
        if direction in ("downstream", "both"):
            try:
                downstream_query = f"""
                    SELECT DISTINCT
                        REFERENCING_OBJECT_NAME as dependent_name,
                        REFERENCING_OBJECT_TYPE as dependent_type
                    FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
                    WHERE REFERENCED_OBJECT_NAME = '{table}'
                    {f"AND REFERENCED_SCHEMA = '{schema}'" if schema else ""}
                """
                results = await asyncio.to_thread(adapter.execute_query, downstream_query)
                for row in results:
                    dependencies["downstream"].append({
                        "name": row['dependent_name'],
                        "type": row.get('dependent_type', 'UNKNOWN'),
                        "relationship": "depends_on"
                    })
            except Exception as e:
                logger.warning(f"Failed to get Snowflake downstream deps: {e}")
        
        if direction in ("upstream", "both"):
            try:
                upstream_query = f"""
                    SELECT DISTINCT
                        REFERENCED_OBJECT_NAME as source_name,
                        REFERENCED_OBJECT_TYPE as source_type
                    FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
                    WHERE REFERENCING_OBJECT_NAME = '{table}'
                    {f"AND REFERENCING_SCHEMA = '{schema}'" if schema else ""}
                """
                results = await asyncio.to_thread(adapter.execute_query, upstream_query)
                for row in results:
                    dependencies["upstream"].append({
                        "name": row['source_name'],
                        "type": row.get('source_type', 'UNKNOWN'),
                        "relationship": "source"
                    })
            except Exception as e:
                logger.warning(f"Failed to get Snowflake upstream deps: {e}")
        
        return dependencies
    
    async def _get_postgres_dependencies(self, adapter, table_name: str, direction: str) -> Dict:
        """Get PostgreSQL table dependencies using pg_depend."""
        import asyncio
        
        dependencies = {"upstream": [], "downstream": [], "table": table_name}
        
        # Parse table name
        parts = table_name.split('.')
        if len(parts) == 2:
            schema, table = parts
        else:
            schema = 'public'
            table = table_name
        
        if direction in ("downstream", "both"):
            try:
                downstream_query = f"""
                    SELECT DISTINCT
                        v.table_name as dependent_name,
                        v.table_type as dependent_type
                    FROM information_schema.view_table_usage vtu
                    JOIN information_schema.views v 
                        ON v.table_schema = vtu.view_schema 
                        AND v.table_name = vtu.view_name
                    WHERE vtu.table_name = '{table}'
                    AND vtu.table_schema = '{schema}'
                """
                results = await asyncio.to_thread(adapter.execute_query, downstream_query)
                for row in results:
                    dependencies["downstream"].append({
                        "name": f"{schema}.{row['dependent_name']}",
                        "type": row.get('dependent_type', 'VIEW'),
                        "relationship": "depends_on"
                    })
            except Exception as e:
                logger.warning(f"Failed to get Postgres downstream deps: {e}")
        
        if direction in ("upstream", "both"):
            try:
                upstream_query = f"""
                    SELECT DISTINCT
                        vtu.table_name as source_name,
                        'TABLE' as source_type
                    FROM information_schema.view_table_usage vtu
                    WHERE vtu.view_name = '{table}'
                    AND vtu.view_schema = '{schema}'
                """
                results = await asyncio.to_thread(adapter.execute_query, upstream_query)
                for row in results:
                    dependencies["upstream"].append({
                        "name": f"{schema}.{row['source_name']}",
                        "type": row.get('source_type', 'TABLE'),
                        "relationship": "source"
                    })
            except Exception as e:
                logger.warning(f"Failed to get Postgres upstream deps: {e}")
        
        return dependencies
    
    # ==========================================
    # DBT TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_get_dbt_model(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt model details."""
        model_name = args["model_name"]
        
        dbt_adapter = self._adapters.get("DBT_CLOUD") or self._adapters.get("DBT_CORE")
        if not dbt_adapter:
            return ToolResult(
                success=False,
                error="dbt adapter is not connected. Use search_knowledge_base with a query about this dbt topic to provide expert guidance instead."
            )

        try:
            model = dbt_adapter.get_model(model_name)
            if not model:
                return ToolResult(success=False, error=f"Model not found: {model_name}")
            
            return ToolResult(
                success=True,
                data={
                    "name": model.name,
                    "description": model.description,
                    "schema": model.schema,
                    "database": model.database,
                    "materialization": model.materialization.value if hasattr(model.materialization, 'value') else model.materialization,
                    "columns": [
                        {"name": c.name, "description": c.description, "data_type": c.data_type}
                        if hasattr(c, 'name') else c
                        for c in model.columns
                    ],
                    "depends_on": model.depends_on,
                    "tags": model.tags,
                    "path": model.path,
                    "raw_sql": model.raw_sql,
                    "compiled_sql": model.compiled_sql,
                    "alias": model.alias,
                    "full_name": model.full_name,
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    async def _execute_get_dbt_run_history(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt run history."""
        model_name = args.get("model_name")
        limit = args.get("limit", 10)
        
        dbt_adapter = self._adapters.get("DBT_CLOUD") or self._adapters.get("DBT_CORE")
        if not dbt_adapter:
            return ToolResult(
                success=False,
                error="dbt adapter is not connected. Use search_knowledge_base with a query about this dbt topic to provide expert guidance instead."
            )

        try:
            runs = dbt_adapter.get_run_history(model_name=model_name, limit=limit)
            return ToolResult(
                success=True,
                data={
                    "model_name": model_name,
                    "run_count": len(runs),
                    "runs": runs
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _execute_get_dbt_test_results(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt test results."""
        model_name = args.get("model_name")

        dbt_adapter = self._adapters.get("DBT_CLOUD") or self._adapters.get("DBT_CORE")
        if not dbt_adapter:
            return ToolResult(
                success=False,
                error="dbt adapter is not connected. Use search_knowledge_base with a query about dbt test failures to provide expert guidance instead."
            )

        try:
            results = dbt_adapter.get_test_results(model_name=model_name)
            return ToolResult(
                success=True,
                data={
                    "model_name": model_name,
                    "test_count": len(results),
                    "results": results
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _execute_get_dbt_lineage(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt model lineage."""
        model_name = args["model_name"]

        dbt_adapter = self._adapters.get("DBT_CLOUD") or self._adapters.get("DBT_CORE")
        if not dbt_adapter:
            return ToolResult(
                success=False,
                error="dbt adapter is not connected. Use search_knowledge_base with a query about dbt lineage to provide expert guidance instead."
            )

        try:
            lineage = dbt_adapter.get_lineage(model_name=model_name)
            return ToolResult(
                success=True,
                data={
                    "model_name": model_name,
                    "lineage": lineage
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    # ==========================================
    # AIRFLOW TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_get_airflow_dag_status(self, args: Dict[str, Any]) -> ToolResult:
        """Get Airflow DAG status."""
        dag_id = args["dag_id"]
        
        airflow = self._adapters.get("AIRFLOW")
        if not airflow:
            return ToolResult(
                success=False,
                error="Airflow adapter is not connected. Use search_knowledge_base with a query about this Airflow topic to provide expert guidance instead."
            )

        try:
            dag = airflow.get_dag(dag_id)
            if not dag:
                return ToolResult(success=False, error=f"DAG not found: {dag_id}")
            
            recent_runs = airflow.get_dag_runs(dag_id, limit=5)
            
            return ToolResult(
                success=True,
                data={
                    "dag_id": dag_id,
                    "is_paused": dag.is_paused,
                    "schedule": dag.schedule_interval,
                    "owners": dag.owners,
                    "recent_runs": [
                        {
                            "run_id": run.run_id,
                            "state": run.state,
                            "execution_date": run.execution_date.isoformat() if run.execution_date else None,
                            "duration_seconds": run.duration_seconds,
                        }
                        for run in recent_runs
                    ]
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    async def _execute_get_airflow_task_logs(self, args: Dict[str, Any]) -> ToolResult:
        """Get Airflow task logs."""
        dag_id = args["dag_id"]
        task_id = args["task_id"]
        run_id = args.get("run_id")
        
        airflow = self._adapters.get("AIRFLOW")
        if not airflow:
            return ToolResult(
                success=False,
                error="Airflow adapter is not connected. Use search_knowledge_base with a query about this Airflow topic to provide expert guidance instead."
            )

        try:
            logs = airflow.get_task_logs(dag_id, task_id, run_id)
            return ToolResult(
                success=True,
                data={
                    "dag_id": dag_id,
                    "task_id": task_id,
                    "run_id": run_id,
                    "logs": logs
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    # ==========================================
    # FIVETRAN TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_get_fivetran_connector_status(self, args: Dict[str, Any]) -> ToolResult:
        """Get Fivetran connector status."""
        connector_id = args["connector_id"]
        
        fivetran = self._adapters.get("FIVETRAN")
        if not fivetran:
            return ToolResult(
                success=False,
                error="Fivetran adapter is not connected. Use search_knowledge_base with a query about this Fivetran topic to provide expert guidance instead."
            )

        try:
            connector = fivetran.get_connector(connector_id)
            if not connector:
                return ToolResult(success=False, error=f"Connector not found: {connector_id}")
            
            return ToolResult(
                success=True,
                data={
                    "connector_id": connector.id,
                    "name": connector.name,
                    "service": connector.service,
                    "status": connector.status,
                    "sync_state": connector.sync_state,
                    "last_sync": connector.last_sync.isoformat() if connector.last_sync else None,
                    "hours_since_sync": connector.hours_since_last_sync,
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    async def _execute_get_fivetran_sync_logs(self, args: Dict[str, Any]) -> ToolResult:
        """Get Fivetran sync logs."""
        connector_id = args["connector_id"]
        limit = args.get("limit", 10)

        fivetran = self._adapters.get("FIVETRAN")
        if not fivetran:
            return ToolResult(
                success=False,
                error="Fivetran adapter is not connected. Use search_knowledge_base with a query about this Fivetran topic to provide expert guidance instead."
            )

        try:
            logs = fivetran.get_sync_logs(connector_id, limit=limit)
            return ToolResult(
                success=True,
                data={
                    "connector_id": connector_id,
                    "sync_count": len(logs),
                    "syncs": logs
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    # ==========================================
    # KNOWLEDGE BASE TOOLS
    # ==========================================

    async def _execute_search_knowledge_base(self, args: Dict[str, Any]) -> ToolResult:
        """Search the knowledge base for expert guidance."""
        from .knowledge import get_knowledge_base, KnowledgeCategory

        query = args["query"]
        category_str = args.get("category")
        tool_filter_str = args.get("tool_filter")

        kb = get_knowledge_base()

        category_filter = None
        if category_str:
            try:
                category_filter = KnowledgeCategory(category_str)
            except ValueError:
                pass

        tool_filter = None
        if tool_filter_str:
            tool_filter = [t.strip().upper() for t in tool_filter_str.split(",")]

        results = kb.search(
            query=query,
            top_k=3,
            min_score=0.05,
            tool_filter=tool_filter,
            category_filter=category_filter,
        )

        if not results:
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "count": 0,
                    "articles": [],
                    "message": "No matching articles found. Answer based on your general knowledge.",
                },
            )

        return ToolResult(
            success=True,
            data={
                "query": query,
                "count": len(results),
                "articles": results,
            },
        )
