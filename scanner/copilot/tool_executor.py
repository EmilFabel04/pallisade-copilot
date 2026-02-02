"""
Co-Pilot Tool Executor

Executes tools against the appropriate integration adapters.
Routes tool calls to the correct backend based on user's integrations.
"""

from typing import Dict, List, Optional, Any, Set
import logging
import json

from .tools import Tool, ToolResult, get_tool_registry
from .context_builder import CopilotContext, IntegrationInfo

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
    
    def _create_adapter(self, integration: IntegrationInfo) -> Optional[Any]:
        """Create an adapter for an integration type."""
        # Import adapters lazily to avoid circular imports
        integration_type = integration.type.upper()
        
        if integration_type == "SNOWFLAKE":
            from ..adapters.snowflake import SnowflakeAdapter
            return SnowflakeAdapter(integration.config)
        
        elif integration_type == "BIGQUERY":
            from ..adapters.bigquery import BigQueryAdapter
            return BigQueryAdapter(integration.config)
        
        elif integration_type == "POSTGRES":
            from ..adapters.postgres import PostgresAdapter
            return PostgresAdapter(integration.config)
        
        elif integration_type in ("DBT_CLOUD", "DBT_CORE"):
            from ..integrations.dbt import DbtIntegration
            return DbtIntegration(integration.config)
        
        elif integration_type == "AIRFLOW":
            from ..integrations.airflow import AirflowIntegration
            return AirflowIntegration(integration.config)
        
        elif integration_type == "DAGSTER":
            from ..integrations.dagster import DagsterIntegration
            return DagsterIntegration(integration.config)
        
        elif integration_type == "PREFECT":
            from ..integrations.prefect import PrefectIntegration
            return PrefectIntegration(integration.config)
        
        elif integration_type == "FIVETRAN":
            from ..integrations.fivetran import FivetranIntegration
            return FivetranIntegration(integration.config)
        
        elif integration_type == "AIRBYTE":
            from ..integrations.airbyte import AirbyteClient
            return AirbyteClient(integration.config)
        
        elif integration_type == "LOOKER":
            from ..integrations.looker import LookerClient
            return LookerClient(integration.config)
        
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
                error=f"Tool '{tool_name}' requires integrations that are not connected"
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
            error=f"Tool '{tool.name}' is not yet implemented"
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
        query = args["query"].lower()
        node_type = args.get("node_type", "all")
        limit = args.get("limit", 20)
        
        if not self.context.graph:
            return ToolResult(success=False, error="No lineage graph available")
        
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
                "nodes": results
            }
        )
    
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
    
    # ==========================================
    # WAREHOUSE TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_query_warehouse(self, args: Dict[str, Any]) -> ToolResult:
        """Execute a read-only SQL query."""
        sql = args["sql"].strip()
        limit = args.get("limit", 100)
        
        # Validate query is SELECT only
        if not sql.upper().startswith("SELECT"):
            return ToolResult(
                success=False,
                error="Only SELECT queries are allowed"
            )
        
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
            # Add LIMIT if not present
            if "LIMIT" not in sql.upper():
                sql = f"{sql} LIMIT {limit}"
            
            results = await adapter.execute_query(sql)
            
            return ToolResult(
                success=True,
                data={
                    "sql": sql,
                    "row_count": len(results),
                    "rows": results[:limit]
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
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
    
    # ==========================================
    # DBT TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_get_dbt_model(self, args: Dict[str, Any]) -> ToolResult:
        """Get dbt model details."""
        model_name = args["model_name"]
        
        dbt_adapter = self._adapters.get("DBT_CLOUD") or self._adapters.get("DBT_CORE")
        if not dbt_adapter:
            return ToolResult(success=False, error="dbt not connected")
        
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
                    "materialization": model.materialization,
                    "columns": model.columns,
                    "depends_on": model.depends_on,
                    "tags": model.tags,
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
            return ToolResult(success=False, error="dbt not connected")
        
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
    
    # ==========================================
    # AIRFLOW TOOL IMPLEMENTATIONS
    # ==========================================
    
    async def _execute_get_airflow_dag_status(self, args: Dict[str, Any]) -> ToolResult:
        """Get Airflow DAG status."""
        dag_id = args["dag_id"]
        
        airflow = self._adapters.get("AIRFLOW")
        if not airflow:
            return ToolResult(success=False, error="Airflow not connected")
        
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
            return ToolResult(success=False, error="Airflow not connected")
        
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
            return ToolResult(success=False, error="Fivetran not connected")
        
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
            return ToolResult(success=False, error="Fivetran not connected")
        
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
