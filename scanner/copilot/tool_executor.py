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
        Fetch schema information from warehouses relevant to the user's query.

        Uses query-based filtering:
        1. Skip if query is clearly about non-warehouse integrations (GitHub, etc.)
        2. Detect which warehouse(s) the user is asking about from their query
        3. Only fetch schema from those specific warehouses
        4. If no warehouse detected or fetch fails, fall back to all connected warehouses

        Returns a dict of "WAREHOUSE_TYPE:dataset" -> list of TableSchema objects.
        """
        schema_info: Dict[str, List[TableSchema]] = {}

        # Step 0: Skip warehouse fetch if query is clearly about non-warehouse integrations
        if self._is_non_warehouse_query():
            logger.info("[Schema Fetch] Query is about non-warehouse integration (GitHub, etc.) - skipping schema fetch")
            return schema_info

        all_warehouse_types = ["BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT"]

        # Step 1: Detect which warehouse(s) the user is asking about
        target_warehouses = self._detect_warehouses_from_query()

        if target_warehouses:
            # Filter to only warehouses that are actually connected
            target_warehouses = [wh for wh in target_warehouses if wh in self._adapters]
            if target_warehouses:
                logger.info(f"[Schema Fetch] Query mentions warehouse(s): {target_warehouses} - fetching only from these")
            else:
                logger.info(f"[Schema Fetch] Query mentions warehouses but none are connected, will try all")
                target_warehouses = None

        # If no specific warehouse detected, use all connected warehouses
        if not target_warehouses:
            target_warehouses = [wh for wh in all_warehouse_types if wh in self._adapters]
            if len(target_warehouses) > 1:
                logger.info(f"[Schema Fetch] No specific warehouse in query, checking all connected: {target_warehouses}")

        if not target_warehouses:
            logger.warning(
                f"[Schema Fetch] No warehouse adapter found. "
                f"Available adapters: {list(self._adapters.keys())}. "
                f"Integration types: {[i.type for i in self.context.integrations]}"
            )
            return schema_info

        # Step 2: Fetch schema from target warehouses
        for wh_type in target_warehouses:
            adapter = self._adapters[wh_type]
            schema_info = await self._fetch_warehouse_schema_single(wh_type, adapter, schema_info)

        # Step 3: If we got nothing and there are other warehouses, try them as fallback
        if not schema_info:
            fallback_warehouses = [wh for wh in all_warehouse_types
                                   if wh in self._adapters and wh not in target_warehouses]
            if fallback_warehouses:
                logger.info(f"[Schema Fetch] No schema from primary sources, trying fallback: {fallback_warehouses}")
                for wh_type in fallback_warehouses:
                    adapter = self._adapters[wh_type]
                    schema_info = await self._fetch_warehouse_schema_single(wh_type, adapter, schema_info)
                    if schema_info:
                        break  # Got data, stop trying

        if schema_info:
            total_tables = sum(len(tables) for tables in schema_info.values())
            wh_names = set(k.split(':')[0] for k in schema_info.keys())
            logger.info(f"[Schema Fetch] SUCCESS - {len(schema_info)} datasets across {wh_names}, {total_tables} tables total")
        else:
            logger.error("[Schema Fetch] FAILED - no schema data fetched, LLM will not have column info")

        return schema_info

    def _detect_warehouses_from_query(self) -> List[str]:
        """
        Detect which warehouse(s) the user is asking about from their query.

        Returns list of warehouse types mentioned (e.g., ["SNOWFLAKE"]) or empty list.
        """
        query = self.context.query
        if not query:
            return []

        query_lower = query.lower()
        detected = []

        # Warehouse name patterns (name -> type)
        warehouse_patterns = {
            "SNOWFLAKE": ["snowflake", "snow flake"],
            "BIGQUERY": ["bigquery", "big query", "bq", "google bigquery"],
            "POSTGRES": ["postgres", "postgresql", "pg", "psql"],
            "REDSHIFT": ["redshift", "red shift", "aws redshift"],
        }

        for wh_type, patterns in warehouse_patterns.items():
            for pattern in patterns:
                if pattern in query_lower:
                    detected.append(wh_type)
                    break  # Found this warehouse, move to next

        return detected

    def _is_non_warehouse_query(self) -> bool:
        """
        Detect if the query is clearly about non-warehouse integrations.

        Returns True if the query is about GitHub, repos, PRs, code, etc.
        and does NOT mention data, tables, queries, or warehouse concepts.
        """
        query = self.context.query
        if not query:
            return False

        query_lower = query.lower()

        # Patterns that indicate GitHub/VCS queries
        vcs_patterns = [
            "github", "repo", "repository", "repositories",
            "pull request", "pr", "commit", "branch",
            "code", "file", "folder", "directory",
            "gitlab", "bitbucket", "git",
        ]

        # Patterns that indicate warehouse/data queries (should NOT skip)
        data_patterns = [
            "table", "column", "schema", "query", "sql",
            "data", "row", "record", "database",
            "bigquery", "snowflake", "postgres", "redshift",
            "select", "from", "where", "join",
        ]

        has_vcs_pattern = any(p in query_lower for p in vcs_patterns)
        has_data_pattern = any(p in query_lower for p in data_patterns)

        # Only skip if it's clearly VCS-related AND NOT data-related
        return has_vcs_pattern and not has_data_pattern

    async def _fetch_warehouse_schema_single(
        self,
        wh_type: str,
        adapter,
        schema_info: Dict[str, List[TableSchema]]
    ) -> Dict[str, List[TableSchema]]:
        """Fetch schema from a single warehouse adapter."""
        try:
            # Connect if needed
            if not adapter.is_connected:
                logger.info(f"[Schema Fetch] Connecting to {wh_type}...")
                connected = adapter.connect()
                if not connected:
                    logger.error(f"[Schema Fetch] Failed to connect to {wh_type}")
                    return schema_info
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
                return schema_info

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
            
            # Build TableSchema objects with project for full BigQuery path
            for row in table_rows:
                tbl_name = row['table_name']
                tables.append(TableSchema(
                    name=tbl_name,
                    dataset=dataset,
                    columns=table_columns.get(tbl_name, []),
                    project=project,
                    warehouse_type="BIGQUERY"
                ))

            logger.info(f"BigQuery schema for {project}.{dataset}: {len(tables)} tables, columns: {sum(len(t.columns) for t in tables)}")
        
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
                    columns=table_columns.get(tbl_name, []),
                    warehouse_type="SNOWFLAKE"
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
                    columns=table_columns.get(tbl_name, []),
                    warehouse_type="POSTGRES"
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
                config_keys = list(integration.config.keys()) if integration.config else []
                logger.info(f"[Snowflake] Creating adapter with config keys: {config_keys}")
                # Log presence of required fields (not values for security)
                has_account = bool(integration.config.get('account'))
                has_user = bool(integration.config.get('user'))
                has_password = bool(integration.config.get('password'))
                has_database = bool(integration.config.get('database'))
                logger.info(f"[Snowflake] Credentials check - account: {has_account}, user: {has_user}, password: {has_password}, database: {has_database}")
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

        # Validate query is read-only (SELECT or WITH...SELECT for CTEs)
        sql_upper = sql.upper()
        is_select = sql_upper.startswith("SELECT")
        is_cte = sql_upper.startswith("WITH") and "SELECT" in sql_upper

        if not (is_select or is_cte):
            return ToolResult(
                success=False,
                error="Only SELECT queries are allowed (including WITH...SELECT CTEs)"
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

    def _get_dbt_adapter_with_manifest(self) -> tuple:
        """
        Get dbt adapter and ensure manifest is loaded.

        Returns:
            Tuple of (dbt_adapter, error_result)
            - If successful: (adapter, None)
            - If failed: (None, ToolResult with error)
        """
        dbt_adapter = self._adapters.get("DBT_CLOUD") or self._adapters.get("DBT_CORE")
        if not dbt_adapter:
            return None, ToolResult(
                success=False,
                error="dbt adapter is not connected. Use search_knowledge_base with a query about this dbt topic to provide expert guidance instead."
            )

        # Ensure manifest is loaded for DbtIntegration (local dbt)
        if hasattr(dbt_adapter, 'manifest') and dbt_adapter.manifest is None:
            try:
                dbt_adapter.load_manifest()
                logger.info("[dbt] Auto-loaded manifest.json")
            except FileNotFoundError as e:
                return None, ToolResult(
                    success=False,
                    error=f"dbt manifest.json not found. Ensure dbt compile has been run. Error: {e}"
                )
            except Exception as e:
                return None, ToolResult(
                    success=False,
                    error=f"Failed to load dbt manifest: {e}"
                )

        return dbt_adapter, None

    async def _execute_get_dbt_model(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt model details."""
        model_name = args["model_name"]

        dbt_adapter, error = self._get_dbt_adapter_with_manifest()
        if error:
            return error

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

        dbt_adapter, error = self._get_dbt_adapter_with_manifest()
        if error:
            return error

        try:
            runs = dbt_adapter.get_run_history(model_name=model_name, limit=limit)
            return ToolResult(
                success=True,
                data={
                    "model_name": model_name,
                    "runs": runs,
                    **runs  # Include the full response dict (available, message, etc.)
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _execute_get_dbt_test_results(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt test results."""
        model_name = args.get("model_name")

        dbt_adapter, error = self._get_dbt_adapter_with_manifest()
        if error:
            return error

        try:
            results = dbt_adapter.get_test_results(model_name=model_name)
            return ToolResult(
                success=True,
                data={
                    "model_name": model_name,
                    "results": results
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _execute_get_dbt_lineage(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt model lineage."""
        model_name = args["model_name"]

        dbt_adapter, error = self._get_dbt_adapter_with_manifest()
        if error:
            return error

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

    # ==========================================
    # OBSERVABILITY TOOL IMPLEMENTATIONS
    # ==========================================

    def _get_observability_clients(self) -> List[Any]:
        """Get all connected observability clients."""
        try:
            from ..integrations.observability import create_observability_client, OBSERVABILITY_TYPES
        except ImportError:
            from scanner.integrations.observability import create_observability_client, OBSERVABILITY_TYPES

        clients = []
        for integration in self.context.integrations:
            if integration.type.upper() in OBSERVABILITY_TYPES:
                try:
                    client = create_observability_client(integration.type, integration.config)
                    if client and client.connect():
                        clients.append(client)
                except Exception as e:
                    logger.warning(f"Failed to create observability client for {integration.type}: {e}")

        return clients

    async def _execute_get_active_incidents(self, args: Dict[str, Any]) -> ToolResult:
        """Get active data quality incidents from observability tools."""
        try:
            from ..integrations.observability import IncidentSeverity
        except ImportError:
            from scanner.integrations.observability import IncidentSeverity

        severity_str = args.get("severity")
        asset_filter = args.get("asset")
        limit = args.get("limit", 20)

        clients = self._get_observability_clients()
        if not clients:
            return ToolResult(
                success=False,
                error="No observability tools connected. Connect Monte Carlo, Bigeye, Soda, or Elementary to use this feature."
            )

        # Parse severity filter
        severity_filter = None
        if severity_str:
            try:
                severity_filter = [IncidentSeverity(severity_str.lower())]
            except ValueError:
                pass

        all_incidents = []
        tools_queried = []

        for client in clients:
            try:
                incidents = client.get_active_incidents(
                    severity_filter=severity_filter,
                    asset_filter=asset_filter,
                    limit=limit,
                )
                all_incidents.extend(incidents)
                tools_queried.append(client.TOOL_NAME)
            except Exception as e:
                logger.error(f"Error fetching incidents from {client.TOOL_NAME}: {e}")

        # Sort by severity (critical first) and time
        severity_order = {
            IncidentSeverity.CRITICAL: 0,
            IncidentSeverity.HIGH: 1,
            IncidentSeverity.MEDIUM: 2,
            IncidentSeverity.LOW: 3,
            IncidentSeverity.INFO: 4,
        }
        all_incidents.sort(key=lambda i: (severity_order.get(i.severity, 5), -i.age_hours))

        # Format for response
        incidents_data = []
        for incident in all_incidents[:limit]:
            asset_name = incident.primary_asset.display_name if incident.primary_asset else "Unknown"
            incidents_data.append({
                "id": incident.id,
                "source": incident.source,
                "severity": incident.severity.value,
                "status": incident.status.value,
                "type": incident.incident_type.value,
                "title": incident.title,
                "description": incident.description[:200] if incident.description else "",
                "asset": asset_name,
                "detected_at": incident.detected_at.isoformat(),
                "age_hours": round(incident.age_hours, 1),
                "expected_value": incident.expected_value,
                "actual_value": incident.actual_value,
                "deviation_pct": incident.deviation_percentage,
                "url": incident.external_url,
            })

        return ToolResult(
            success=True,
            data={
                "tools_queried": tools_queried,
                "total_count": len(all_incidents),
                "returned_count": len(incidents_data),
                "incidents": incidents_data,
            }
        )

    async def _execute_get_asset_quality(self, args: Dict[str, Any]) -> ToolResult:
        """Get data quality metrics for a specific asset."""
        asset_name = args["asset_name"]

        clients = self._get_observability_clients()
        if not clients:
            return ToolResult(
                success=False,
                error="No observability tools connected. Connect Monte Carlo, Bigeye, Soda, or Elementary to use this feature."
            )

        # Try each client until we get metrics
        for client in clients:
            try:
                metrics = client.get_asset_quality_metrics(asset_name)
                if metrics:
                    return ToolResult(
                        success=True,
                        data={
                            "source": client.TOOL_NAME,
                            "asset": asset_name,
                            "health_score": metrics.health_score,
                            "health_status": metrics.health_status,
                            "active_incidents": metrics.active_incidents,
                            "total_checks": metrics.total_checks,
                            "passing_checks": metrics.passing_checks,
                            "check_pass_rate": metrics.check_pass_rate,
                            "freshness_status": metrics.freshness_status,
                            "hours_since_update": metrics.hours_since_update,
                            "expected_freshness_hours": metrics.expected_freshness_hours,
                            "volume_status": metrics.volume_status,
                            "volume_deviation_pct": metrics.volume_deviation_pct,
                            "current_row_count": metrics.current_row_count,
                            "expected_row_count": metrics.expected_row_count,
                            "schema_changes_7d": metrics.schema_changes_7d,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to get metrics from {client.TOOL_NAME}: {e}")
                continue

        return ToolResult(
            success=False,
            error=f"Asset '{asset_name}' not found in any connected observability tool. Verify the asset name format (e.g., 'database.schema.table')."
        )

    async def _execute_trace_incident_root_cause(self, args: Dict[str, Any]) -> ToolResult:
        """Trace an incident upstream through lineage to find root cause."""
        incident_id = args.get("incident_id")
        asset_name = args.get("asset_name")
        depth = args.get("depth", 3)

        if not incident_id and not asset_name:
            return ToolResult(
                success=False,
                error="Either incident_id or asset_name must be provided."
            )

        clients = self._get_observability_clients()
        if not clients:
            return ToolResult(
                success=False,
                error="No observability tools connected."
            )

        primary_incident = None
        affected_asset = asset_name

        # If incident_id provided, get the incident details first
        if incident_id:
            for client in clients:
                try:
                    incident = client.get_incident_details(incident_id)
                    if incident:
                        primary_incident = incident
                        if incident.primary_asset:
                            affected_asset = incident.primary_asset.fqn
                        break
                except Exception as e:
                    logger.warning(f"Failed to get incident {incident_id} from {client.TOOL_NAME}: {e}")

        if not affected_asset:
            return ToolResult(
                success=False,
                error="Could not determine affected asset. Please provide asset_name."
            )

        # Get upstream incidents from observability tools
        upstream_incidents = []
        for client in clients:
            try:
                upstream = client.get_upstream_incidents(affected_asset, depth=depth)
                upstream_incidents.extend(upstream)
            except Exception as e:
                logger.debug(f"No upstream incidents from {client.TOOL_NAME}: {e}")

        # Also check Pallisade lineage if available
        lineage_upstream = []
        if self.context.graph:
            try:
                upstream_nodes = self.context.graph.get_upstream(affected_asset, depth=depth)
                for node in upstream_nodes:
                    # Check each upstream node for incidents
                    for client in clients:
                        try:
                            node_incidents = client.get_incidents_for_asset(
                                node.id,
                                hours_back=168,  # 7 days
                                include_resolved=False,
                            )
                            for inc in node_incidents:
                                if inc.is_active:
                                    upstream_incidents.append(inc)
                                    lineage_upstream.append({
                                        "node": node.id,
                                        "node_type": node.node_type.value,
                                        "incident_id": inc.id,
                                        "incident_type": inc.incident_type.value,
                                    })
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Lineage lookup failed: {e}")

        # Format response
        root_causes = []
        for incident in upstream_incidents:
            asset = incident.primary_asset.display_name if incident.primary_asset else "Unknown"
            root_causes.append({
                "incident_id": incident.id,
                "source": incident.source,
                "severity": incident.severity.value,
                "type": incident.incident_type.value,
                "title": incident.title,
                "asset": asset,
                "detected_at": incident.detected_at.isoformat(),
                "url": incident.external_url,
            })

        return ToolResult(
            success=True,
            data={
                "target_asset": affected_asset,
                "primary_incident": {
                    "id": primary_incident.id,
                    "type": primary_incident.incident_type.value,
                    "title": primary_incident.title,
                } if primary_incident else None,
                "upstream_issues_found": len(root_causes),
                "root_causes": root_causes,
                "lineage_path": lineage_upstream,
                "recommendation": self._generate_root_cause_recommendation(primary_incident, root_causes),
            }
        )

    def _generate_root_cause_recommendation(
        self,
        primary_incident,
        root_causes: List[Dict],
    ) -> str:
        """Generate a recommendation based on root cause analysis."""
        if not root_causes:
            if primary_incident:
                incident_type = primary_incident.incident_type.value
                if incident_type == "freshness":
                    return "No upstream issues detected. Check the orchestrator (Airflow, dbt Cloud, etc.) for failed or delayed jobs that update this table."
                elif incident_type == "volume":
                    return "No upstream issues detected. Check the source system for changes in data volume or filtering logic."
                elif incident_type == "schema":
                    return "No upstream issues detected. This appears to be a direct schema change on this table."
            return "No upstream issues detected. Investigate the table directly."

        # Summarize root causes
        issue_types = set(rc["type"] for rc in root_causes)
        assets = set(rc["asset"] for rc in root_causes)

        if "freshness" in issue_types:
            return f"Root cause appears to be freshness issues in upstream tables: {', '.join(assets)}. Fix the upstream data pipeline first, then this table should resolve automatically."
        elif "schema" in issue_types:
            return f"Schema changes detected in upstream tables: {', '.join(assets)}. Review the schema changes and update downstream transformations accordingly."
        elif "volume" in issue_types:
            return f"Volume anomalies detected in upstream tables: {', '.join(assets)}. Investigate the source data before proceeding."
        else:
            return f"Issues found in upstream tables: {', '.join(assets)}. Fix these first before addressing the downstream problem."

    async def _execute_get_quality_checks(self, args: Dict[str, Any]) -> ToolResult:
        """Get data quality checks configured for an asset."""
        asset_name = args["asset_name"]

        clients = self._get_observability_clients()
        if not clients:
            return ToolResult(
                success=False,
                error="No observability tools connected."
            )

        all_checks = []
        tools_queried = []

        for client in clients:
            try:
                checks = client.get_checks_for_asset(asset_name)
                all_checks.extend(checks)
                tools_queried.append(client.TOOL_NAME)
            except Exception as e:
                logger.warning(f"Failed to get checks from {client.TOOL_NAME}: {e}")

        if not all_checks:
            return ToolResult(
                success=True,
                data={
                    "asset": asset_name,
                    "tools_queried": tools_queried,
                    "total_checks": 0,
                    "checks": [],
                    "message": f"No data quality checks found for '{asset_name}'."
                }
            )

        # Format checks
        checks_data = []
        for check in all_checks:
            checks_data.append({
                "id": check.id,
                "source": check.source,
                "name": check.name,
                "type": check.check_type.value,
                "is_passing": check.is_passing,
                "consecutive_failures": check.consecutive_failures,
                "threshold": check.threshold,
                "schedule": check.schedule,
                "last_run_at": check.last_run_at.isoformat() if check.last_run_at else None,
                "url": check.external_url,
            })

        passing = sum(1 for c in all_checks if c.is_passing)
        failing = len(all_checks) - passing

        return ToolResult(
            success=True,
            data={
                "asset": asset_name,
                "tools_queried": tools_queried,
                "total_checks": len(all_checks),
                "passing": passing,
                "failing": failing,
                "checks": checks_data,
            }
        )

    async def _execute_get_incident_details(self, args: Dict[str, Any]) -> ToolResult:
        """Get detailed information about a specific incident."""
        incident_id = args["incident_id"]

        clients = self._get_observability_clients()
        if not clients:
            return ToolResult(
                success=False,
                error="No observability tools connected."
            )

        for client in clients:
            try:
                incident = client.get_incident_details(incident_id)
                if incident:
                    # Format affected assets
                    assets = []
                    for asset in incident.affected_assets:
                        assets.append({
                            "id": asset.id,
                            "name": asset.name,
                            "fqn": asset.fqn,
                            "type": asset.asset_type,
                            "column": asset.column_name,
                        })

                    return ToolResult(
                        success=True,
                        data={
                            "id": incident.id,
                            "source": incident.source,
                            "severity": incident.severity.value,
                            "status": incident.status.value,
                            "type": incident.incident_type.value,
                            "title": incident.title,
                            "description": incident.description,
                            "affected_assets": assets,
                            "detected_at": incident.detected_at.isoformat(),
                            "started_at": incident.started_at.isoformat() if incident.started_at else None,
                            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
                            "expected_value": incident.expected_value,
                            "actual_value": incident.actual_value,
                            "deviation_pct": incident.deviation_percentage,
                            "threshold": incident.threshold,
                            "url": incident.external_url,
                            "tags": incident.tags,
                        }
                    )
            except Exception as e:
                logger.debug(f"Incident {incident_id} not found in {client.TOOL_NAME}: {e}")

        return ToolResult(
            success=False,
            error=f"Incident '{incident_id}' not found in any connected observability tool."
        )

    # ==========================================
    # CHANGE PLAN TOOL IMPLEMENTATIONS
    # ==========================================

    async def _execute_create_change_plan(self, args: Dict[str, Any]) -> ToolResult:
        """Create a structured change plan with patches."""
        try:
            from .change_plan import (
                ChangePlan,
                FilePatch,
                PatchType,
                ImpactAnalysis,
                get_change_plan_store,
            )
        except ImportError:
            from scanner.copilot.change_plan import (
                ChangePlan,
                FilePatch,
                PatchType,
                ImpactAnalysis,
                get_change_plan_store,
            )

        title = args.get("title", "Untitled Fix")
        root_cause = args.get("root_cause", "")
        description = args.get("description", "")
        patches_data = args.get("patches", [])
        impact_data = args.get("impact_analysis", {})

        # Parse patches
        patches = []
        for p in patches_data:
            try:
                patch_type = PatchType(p.get("patch_type", "sql_model"))
            except ValueError:
                patch_type = PatchType.SQL_MODEL

            patch = FilePatch(
                file_path=p.get("file_path", "unknown.sql"),
                patch_type=patch_type,
                new_content=p.get("new_content", ""),
                rationale=p.get("rationale", ""),
                original_content=p.get("original_content"),
                rollback_steps=p.get("rollback_steps", []),
            )
            patches.append(patch)

        # Parse impact analysis
        impact = None
        if impact_data:
            impact = ImpactAnalysis(
                affected_tables=impact_data.get("affected_tables", []),
                downstream_dependencies=impact_data.get("downstream_dependencies", []),
                stakeholders=impact_data.get("stakeholders", []),
                risk_level=impact_data.get("risk_level", "LOW"),
                expected_data_changes=impact_data.get("expected_data_changes", ""),
            )

        # Create the plan
        plan = ChangePlan.create(
            title=title,
            description=description,
            root_cause=root_cause,
            patches=patches,
            impact_analysis=impact,
            session_id=getattr(self.context, 'session_id', None),
        )

        # Store the plan
        store = get_change_plan_store()
        store.save(plan)

        return ToolResult(
            success=True,
            data={
                "plan_id": plan.id,
                "title": plan.title,
                "status": plan.status.value,
                "patches_count": len(plan.patches),
                "message": f"Change plan '{plan.id}' created with {len(plan.patches)} patch(es). Use validate_change_plan to run validation checks.",
                "plan": plan.to_dict(),
            }
        )

    async def _execute_validate_change_plan(self, args: Dict[str, Any]) -> ToolResult:
        """Run validation checks on a change plan."""
        try:
            from .change_plan import (
                ValidationLevel,
                get_validator,
                get_change_plan_store,
            )
        except ImportError:
            from scanner.copilot.change_plan import (
                ValidationLevel,
                get_validator,
                get_change_plan_store,
            )

        plan_id = args.get("plan_id")
        level_str = args.get("level", "static")

        # Get the plan
        store = get_change_plan_store()
        plan = store.get(plan_id)

        if not plan:
            return ToolResult(
                success=False,
                error=f"Change plan '{plan_id}' not found. Use create_change_plan first."
            )

        # Parse validation level
        try:
            level = ValidationLevel(level_str)
        except ValueError:
            return ToolResult(
                success=False,
                error=f"Invalid validation level: {level_str}. Use 'static', 'ci', or 'sandbox'."
            )

        # Get validator and run validation
        validator = get_validator(level, self.context)
        result = await validator.validate(plan)

        # Update plan with validation result
        plan.set_validation(result)
        store.save(plan)

        return ToolResult(
            success=result.status.value == "passed",
            data={
                "plan_id": plan.id,
                "level": result.level.value,
                "status": result.status.value,
                "duration_seconds": result.duration_seconds,
                "errors": result.errors,
                "warnings": result.warnings,
                "details": result.details,
                "plan_status": plan.status.value,
                "is_validated": plan.is_validated(),
            }
        )

    async def _execute_get_change_plan(self, args: Dict[str, Any]) -> ToolResult:
        """Retrieve a change plan by ID."""
        try:
            from .change_plan import get_change_plan_store
        except ImportError:
            from scanner.copilot.change_plan import get_change_plan_store

        plan_id = args.get("plan_id")

        store = get_change_plan_store()
        plan = store.get(plan_id)

        if not plan:
            return ToolResult(
                success=False,
                error=f"Change plan '{plan_id}' not found."
            )

        return ToolResult(
            success=True,
            data=plan.to_dict()
        )

    async def _execute_list_change_plans(self, args: Dict[str, Any]) -> ToolResult:
        """List all change plans in the current session."""
        try:
            from .change_plan import get_change_plan_store
        except ImportError:
            from scanner.copilot.change_plan import get_change_plan_store

        store = get_change_plan_store()
        plans = store.list()

        plans_data = []
        for plan in plans:
            validation_summary = {}
            for level, result in plan.validations.items():
                validation_summary[level.value] = result.status.value

            plans_data.append({
                "id": plan.id,
                "title": plan.title,
                "status": plan.status.value,
                "patches_count": len(plan.patches),
                "validations": validation_summary,
                "is_validated": plan.is_validated(),
                "created_at": plan.created_at.isoformat(),
                "pr_url": plan.pr_url,
            })

        return ToolResult(
            success=True,
            data={
                "count": len(plans_data),
                "plans": plans_data,
            }
        )

    async def _execute_apply_change_plan(self, args: Dict[str, Any]) -> ToolResult:
        """Apply a validated change plan by creating a GitHub PR."""
        try:
            from .change_plan import (
                ChangePlanApplier,
                get_change_plan_store,
            )
        except ImportError:
            from scanner.copilot.change_plan import (
                ChangePlanApplier,
                get_change_plan_store,
            )

        plan_id = args.get("plan_id")
        repo_owner = args.get("repo_owner")
        repo_name = args.get("repo_name")
        base_branch = args.get("base_branch", "main")

        # Get the plan
        store = get_change_plan_store()
        plan = store.get(plan_id)

        if not plan:
            return ToolResult(
                success=False,
                error=f"Change plan '{plan_id}' not found."
            )

        # Check if validated
        if not plan.is_validated():
            return ToolResult(
                success=False,
                error="Plan has not passed required validations. Run validate_change_plan with level='static' first."
            )

        # Get GitHub token from context
        github_token = self._get_github_token()
        if not github_token:
            return ToolResult(
                success=False,
                error="GitHub is not connected. Please connect GitHub in your integrations to apply changes."
            )

        # Auto-detect repo from context if not provided
        if not repo_owner or not repo_name:
            detected_repo = self._get_github_repo()
            if detected_repo:
                repo_owner = repo_owner or detected_repo.get("owner")
                repo_name = repo_name or detected_repo.get("name")

            if not repo_owner or not repo_name:
                # List available repos for the user
                repos = self._get_github_repos_list()
                if repos:
                    repo_list = ", ".join(repos[:5])
                    return ToolResult(
                        success=False,
                        error=f"Please specify which repository to create the PR in. Available repos: {repo_list}. "
                              f"Example: Apply change plan {plan_id} to owner/repo-name"
                    )
                return ToolResult(
                    success=False,
                    error="Could not determine target repository. Please specify repo_owner and repo_name."
                )

        # Apply the plan
        applier = ChangePlanApplier(github_token)
        try:
            result = await applier.apply(plan, repo_owner, repo_name, base_branch)

            if result.success:
                # Update stored plan
                store.save(plan)

                return ToolResult(
                    success=True,
                    data={
                        "plan_id": plan.id,
                        "pr_url": result.pr_url,
                        "pr_number": result.pr_number,
                        "branch": result.branch_name,
                        "files_changed": result.files_changed,
                        "message": f"Pull Request created: {result.pr_url}",
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.error or "Failed to create Pull Request"
                )
        finally:
            await applier.close()

    def _get_github_token(self) -> Optional[str]:
        """Get GitHub token from context integrations."""
        for integration in self.context.integrations:
            if integration.type.upper() == "GITHUB":
                config = integration.config or {}
                token = config.get("access_token") or config.get("token")
                if token:
                    logger.info(f"[GitHub] Found token in integration config (key: {'access_token' if config.get('access_token') else 'token'})")
                    return token
                else:
                    logger.warning(f"[GitHub] Found GITHUB integration but no token in config. Keys: {list(config.keys())}")
        logger.warning("[GitHub] No GITHUB integration found in context")
        return None

    def _get_github_repo(self) -> Optional[Dict[str, str]]:
        """Get the primary GitHub repo from context (e.g., from VERSION_CONTROL node or first repo)."""
        for integration in self.context.integrations:
            if integration.type.upper() == "GITHUB":
                # Check if there's a specific repo configured
                config = integration.config or {}
                if config.get("repo"):
                    # Format: "owner/repo"
                    parts = config["repo"].split("/")
                    if len(parts) == 2:
                        return {"owner": parts[0], "name": parts[1]}

                # Check metadata for repos list
                metadata = getattr(integration, 'metadata', {}) or config.get('metadata', {})
                repos = metadata.get("repos", [])
                if repos and len(repos) == 1:
                    # Only one repo connected, use it
                    full_name = repos[0].get("name", "")
                    parts = full_name.split("/")
                    if len(parts) == 2:
                        return {"owner": parts[0], "name": parts[1]}
        return None

    def _get_github_repos_list(self) -> List[str]:
        """Get list of available GitHub repo names from integrations."""
        repos = []
        for integration in self.context.integrations:
            if integration.type.upper() == "GITHUB":
                config = integration.config or {}
                metadata = getattr(integration, 'metadata', {}) or config.get('metadata', {})
                for repo in metadata.get("repos", []):
                    name = repo.get("name", "")
                    if name:
                        repos.append(name)
        return repos

    async def _execute_list_github_repos(self, args: Dict[str, Any]) -> ToolResult:
        """List available GitHub repositories."""
        import aiohttp

        token = self._get_github_token()
        if not token:
            return ToolResult(
                success=False,
                error="GitHub is not connected. Please connect GitHub in your integrations."
            )

        # Detect token type for logging
        token_type = "classic"
        if token.startswith("github_pat_"):
            token_type = "fine-grained"
        elif token.startswith("gho_"):
            token_type = "oauth"
        elif token.startswith("ghu_"):
            token_type = "user-to-server"
        logger.info(f"[GitHub] Using {token_type} token (prefix: {token[:10]}...)")

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {token}",  # Use Bearer for fine-grained PATs
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "Pallisade-Copilot/1.0",
                }

                all_repos = []

                # First, check token scopes and permissions
                async with session.get(
                    "https://api.github.com/user",
                    headers=headers
                ) as user_response:
                    if user_response.status == 200:
                        user_data = await user_response.json()
                        scopes = user_response.headers.get("X-OAuth-Scopes", "none")
                        logger.info(f"[GitHub] Authenticated as: {user_data.get('login')}, scopes: {scopes}")
                    else:
                        error_text = await user_response.text()
                        logger.warning(f"[GitHub] Auth check failed: {user_response.status} - {error_text}")

                # Try /user/repos with all visibility and affiliations
                async with session.get(
                    "https://api.github.com/user/repos",
                    headers=headers,
                    params={
                        "per_page": 100,
                        "sort": "updated",
                        "visibility": "all",  # Include private repos
                        "affiliation": "owner,collaborator,organization_member",
                    }
                ) as response:
                    if response.status == 200:
                        repos = await response.json()
                        all_repos.extend(repos)
                        logger.info(f"[GitHub] /user/repos returned {len(repos)} repos")
                    else:
                        error_text = await response.text()
                        logger.warning(f"[GitHub] /user/repos failed: {response.status} - {error_text}")

                # For fine-grained PATs, also try /installation/repositories
                # This works for GitHub App installation tokens
                if not all_repos:
                    async with session.get(
                        "https://api.github.com/installation/repositories",
                        headers=headers,
                        params={"per_page": 100}
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            repos = data.get("repositories", [])
                            all_repos.extend(repos)
                            logger.info(f"[GitHub] /installation/repositories returned {len(repos)} repos")

                if not all_repos:
                    return ToolResult(
                        success=False,
                        error=(
                            "No repositories found. This could mean:\n"
                            "1. Your PAT doesn't have 'Repository access' configured\n"
                            "2. For fine-grained PATs: Select the specific repos under 'Repository access'\n"
                            "3. Ensure the PAT has at least 'Metadata: Read-only' permission"
                        )
                    )

                # Format repo list (deduplicate by full_name)
                seen = set()
                repo_list = []
                for repo in all_repos:
                    full_name = repo["full_name"]
                    if full_name in seen:
                        continue
                    seen.add(full_name)
                    repo_list.append({
                        "full_name": full_name,
                        "name": repo["name"],
                        "owner": repo["owner"]["login"],
                        "default_branch": repo.get("default_branch", "main"),
                        "private": repo.get("private", False),
                        "description": repo.get("description", ""),
                        "language": repo.get("language"),
                        "updated_at": repo.get("updated_at"),
                    })

                # Log repo stats for debugging
                private_count = sum(1 for r in repo_list if r["private"])
                public_count = len(repo_list) - private_count
                logger.info(f"[GitHub] Found {len(repo_list)} repos: {private_count} private, {public_count} public")

                # Warn if only public repos found with fine-grained PAT
                if token_type == "fine-grained" and private_count == 0 and public_count > 0:
                    logger.warning(
                        "[GitHub] Fine-grained PAT only returned public repos. "
                        "Check that 'Repository access' includes your private repos and "
                        "'Metadata: Read-only' permission is granted."
                    )

                return ToolResult(
                    success=True,
                    data={
                        "repos": repo_list,
                        "count": len(repo_list),
                        "message": f"Found {len(repo_list)} repositories ({private_count} private, {public_count} public)"
                    }
                )
        except Exception as e:
            logger.exception("Failed to list GitHub repos")
            return ToolResult(success=False, error=str(e))

    async def _execute_get_github_tree(self, args: Dict[str, Any]) -> ToolResult:
        """Get file tree from a GitHub repository."""
        import aiohttp

        repo = args.get("repo", "")
        path = args.get("path", "")
        branch = args.get("branch", "main")

        if not repo:
            return ToolResult(success=False, error="repo is required (format: owner/repo)")

        if "/" not in repo:
            return ToolResult(success=False, error="repo must be in format 'owner/repo'")

        token = self._get_github_token()
        if not token:
            return ToolResult(
                success=False,
                error="GitHub is not connected. Please connect GitHub in your integrations."
            )

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Pallisade-Copilot/1.0",
                }

                # Get contents at path
                url = f"https://api.github.com/repos/{repo}/contents/{path}"
                params = {"ref": branch}

                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 404:
                        return ToolResult(
                            success=False,
                            error=f"Path not found: {path} in {repo} (branch: {branch})"
                        )
                    if response.status != 200:
                        error_text = await response.text()
                        return ToolResult(
                            success=False,
                            error=f"GitHub API error: {response.status} - {error_text}"
                        )

                    contents = await response.json()

                    # Handle single file vs directory
                    if isinstance(contents, dict):
                        # Single file
                        return ToolResult(
                            success=True,
                            data={
                                "type": "file",
                                "path": contents["path"],
                                "name": contents["name"],
                                "size": contents["size"],
                            }
                        )

                    # Directory listing
                    items = []
                    for item in contents:
                        items.append({
                            "name": item["name"],
                            "path": item["path"],
                            "type": item["type"],  # "file" or "dir"
                            "size": item.get("size", 0) if item["type"] == "file" else None,
                        })

                    # Sort: directories first, then files
                    items.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"]))

                    return ToolResult(
                        success=True,
                        data={
                            "repo": repo,
                            "branch": branch,
                            "path": path or "/",
                            "items": items,
                            "count": len(items),
                        }
                    )
        except Exception as e:
            logger.exception("Failed to get GitHub tree")
            return ToolResult(success=False, error=str(e))

    async def _execute_get_github_file(self, args: Dict[str, Any]) -> ToolResult:
        """Read a file from a GitHub repository."""
        import aiohttp
        import base64

        repo = args.get("repo", "")
        path = args.get("path", "")
        branch = args.get("branch", "main")

        if not repo:
            return ToolResult(success=False, error="repo is required (format: owner/repo)")
        if not path:
            return ToolResult(success=False, error="path is required")

        if "/" not in repo:
            return ToolResult(success=False, error="repo must be in format 'owner/repo'")

        token = self._get_github_token()
        if not token:
            return ToolResult(
                success=False,
                error="GitHub is not connected. Please connect GitHub in your integrations."
            )

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Pallisade-Copilot/1.0",
                }

                url = f"https://api.github.com/repos/{repo}/contents/{path}"
                params = {"ref": branch}

                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 404:
                        return ToolResult(
                            success=False,
                            error=f"File not found: {path} in {repo} (branch: {branch})"
                        )
                    if response.status != 200:
                        error_text = await response.text()
                        return ToolResult(
                            success=False,
                            error=f"GitHub API error: {response.status} - {error_text}"
                        )

                    data = await response.json()

                    if data.get("type") != "file":
                        return ToolResult(
                            success=False,
                            error=f"Path is a directory, not a file. Use get_github_tree to list contents."
                        )

                    # Decode base64 content
                    content_b64 = data.get("content", "")
                    try:
                        content = base64.b64decode(content_b64).decode("utf-8")
                    except Exception:
                        return ToolResult(
                            success=False,
                            error="File is binary and cannot be displayed as text"
                        )

                    return ToolResult(
                        success=True,
                        data={
                            "repo": repo,
                            "branch": branch,
                            "path": path,
                            "name": data["name"],
                            "size": data["size"],
                            "content": content,
                            "sha": data["sha"],
                        }
                    )
        except Exception as e:
            logger.exception("Failed to read GitHub file")
            return ToolResult(success=False, error=str(e))
