"""
Co-Pilot Tool Registry

Defines all tools available to the AI co-pilot.
Tools are conditionally available based on user's integrations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Set
from enum import Enum
import json


class ToolCategory(Enum):
    """Categories of tools."""
    LINEAGE = "lineage"
    WAREHOUSE = "warehouse"
    DBT = "dbt"
    ORCHESTRATION = "orchestration"
    INGESTION = "ingestion"
    REPORTING = "reporting"


@dataclass
class ToolParameter:
    """A parameter for a tool."""
    name: str
    type: str  # string, integer, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class Tool:
    """
    Definition of a tool available to the co-pilot.
    
    Tools map to specific functionality in the integration adapters.
    """
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)
    
    # Which integrations are required for this tool
    required_integrations: Set[str] = field(default_factory=set)
    
    # Alternative integrations (any one of these works)
    alternative_integrations: Set[str] = field(default_factory=set)
    
    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Convert to Anthropic tool format."""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    
    def to_openai_tool(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }
    
    def is_available(self, user_integrations: Set[str]) -> bool:
        """Check if this tool is available for the user's integrations."""
        # Check required integrations (all must be present)
        if self.required_integrations:
            if not self.required_integrations.issubset(user_integrations):
                return False
        
        # Check alternative integrations (at least one must be present)
        if self.alternative_integrations:
            if not self.alternative_integrations & user_integrations:
                return False
        
        return True


@dataclass
class ToolResult:
    """Result of executing a tool."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }


class ToolRegistry:
    """
    Registry of all available tools.
    
    Tools are organized by category and filtered based on
    what integrations the user has connected.
    """
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._register_all_tools()
    
    def _register_all_tools(self):
        """Register all available tools."""
        
        # ==========================================
        # LINEAGE TOOLS (always available)
        # ==========================================
        
        self._register(Tool(
            name="get_upstream",
            description="Get all upstream dependencies (tables/models that feed into this node). Use this to understand where data comes from.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("node_id", "string", "The fully qualified name of the node (e.g., 'database.schema.table')"),
                ToolParameter("depth", "integer", "How many levels upstream to traverse (-1 for all)", required=False, default=-1),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DBT_CLOUD", "DBT_CORE"},
        ))
        
        self._register(Tool(
            name="get_downstream",
            description="Get all downstream dependents (tables/models/dashboards that depend on this node). Use this to understand impact of changes.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("node_id", "string", "The fully qualified name of the node"),
                ToolParameter("depth", "integer", "How many levels downstream to traverse (-1 for all)", required=False, default=-1),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DBT_CLOUD", "DBT_CORE"},
        ))
        
        self._register(Tool(
            name="get_node_details",
            description="Get detailed information about a specific node (table, model, view, etc.) including schema, stats, and metadata.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("node_id", "string", "The fully qualified name of the node"),
            ],
        ))
        
        self._register(Tool(
            name="search_lineage",
            description="Search for nodes in the lineage graph by name pattern or type.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("query", "string", "Search query (supports wildcards like 'stg_*' or '*_orders')"),
                ToolParameter("node_type", "string", "Filter by node type", required=False, 
                             enum=["table", "view", "model", "source", "dashboard", "all"]),
                ToolParameter("limit", "integer", "Maximum results to return", required=False, default=20),
            ],
        ))
        
        self._register(Tool(
            name="get_column_lineage",
            description="Get column-level lineage showing how a specific column flows through transformations.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("node_id", "string", "The fully qualified name of the node"),
                ToolParameter("column_name", "string", "The column to trace"),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "DBT_CLOUD", "DBT_CORE"},
        ))
        
        # ==========================================
        # WAREHOUSE TOOLS
        # ==========================================
        
        self._register(Tool(
            name="query_warehouse",
            description="Execute a read-only SQL query against the warehouse. Only SELECT statements are allowed.",
            category=ToolCategory.WAREHOUSE,
            parameters=[
                ToolParameter("sql", "string", "The SQL query to execute (SELECT only)"),
                ToolParameter("limit", "integer", "Maximum rows to return", required=False, default=100),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "SQLSERVER", "AZURE_SQL"},
        ))
        
        self._register(Tool(
            name="get_table_stats",
            description="Get statistics about a table including row count, size, last updated time, and column stats.",
            category=ToolCategory.WAREHOUSE,
            parameters=[
                ToolParameter("table_name", "string", "The fully qualified table name"),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT"},
        ))
        
        self._register(Tool(
            name="get_query_history",
            description="Get recent queries that touched a specific table. Useful for understanding data access patterns.",
            category=ToolCategory.WAREHOUSE,
            parameters=[
                ToolParameter("table_name", "string", "The table to get query history for"),
                ToolParameter("hours", "integer", "How many hours back to look", required=False, default=24),
                ToolParameter("limit", "integer", "Maximum queries to return", required=False, default=20),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY"},
        ))
        
        self._register(Tool(
            name="get_table_dependencies",
            description="Get upstream (source) and downstream (dependent) tables for a specific table. Shows what feeds into this table and what depends on it.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("table_name", "string", "The fully qualified table name (dataset.table or schema.table)"),
                ToolParameter("direction", "string", "Which dependencies to get", required=False, 
                             enum=["upstream", "downstream", "both"], default="both"),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES"},
        ))
        
        # ==========================================
        # DBT TOOLS
        # ==========================================
        
        self._register(Tool(
            name="get_dbt_model",
            description="Get details about a dbt model including its SQL, dependencies, tests, and documentation.",
            category=ToolCategory.DBT,
            parameters=[
                ToolParameter("model_name", "string", "The name of the dbt model"),
            ],
            alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
        ))
        
        self._register(Tool(
            name="get_dbt_run_history",
            description="Get recent dbt run history for a model or the entire project.",
            category=ToolCategory.DBT,
            parameters=[
                ToolParameter("model_name", "string", "The model name (optional, omit for all models)", required=False),
                ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
            ],
            alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
        ))
        
        self._register(Tool(
            name="get_dbt_test_results",
            description="Get test results for a dbt model or source.",
            category=ToolCategory.DBT,
            parameters=[
                ToolParameter("model_name", "string", "The model or source name"),
                ToolParameter("include_passing", "boolean", "Include passing tests", required=False, default=False),
            ],
            alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
        ))
        
        self._register(Tool(
            name="get_dbt_lineage",
            description="Get the dbt-specific lineage for a model showing parent and child models.",
            category=ToolCategory.DBT,
            parameters=[
                ToolParameter("model_name", "string", "The model name"),
            ],
            alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
        ))
        
        # ==========================================
        # ORCHESTRATION TOOLS (Airflow)
        # ==========================================
        
        self._register(Tool(
            name="get_airflow_dag_status",
            description="Get the status of an Airflow DAG including recent runs and current state.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("dag_id", "string", "The DAG ID"),
            ],
            required_integrations={"AIRFLOW"},
        ))
        
        self._register(Tool(
            name="get_airflow_task_logs",
            description="Get logs for a specific Airflow task execution.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("dag_id", "string", "The DAG ID"),
                ToolParameter("task_id", "string", "The task ID"),
                ToolParameter("run_id", "string", "The run ID (execution date)", required=False),
            ],
            required_integrations={"AIRFLOW"},
        ))
        
        self._register(Tool(
            name="get_airflow_recent_failures",
            description="Get recent task failures for a DAG or all DAGs.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("dag_id", "string", "The DAG ID (optional)", required=False),
                ToolParameter("hours", "integer", "How many hours back to look", required=False, default=24),
                ToolParameter("limit", "integer", "Maximum failures to return", required=False, default=20),
            ],
            required_integrations={"AIRFLOW"},
        ))
        
        # ==========================================
        # ORCHESTRATION TOOLS (Dagster)
        # ==========================================
        
        self._register(Tool(
            name="get_dagster_asset_status",
            description="Get the materialization status of a Dagster asset.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("asset_key", "string", "The asset key"),
            ],
            required_integrations={"DAGSTER"},
        ))
        
        self._register(Tool(
            name="get_dagster_run_history",
            description="Get recent Dagster job runs.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("job_name", "string", "The job name (optional)", required=False),
                ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
            ],
            required_integrations={"DAGSTER"},
        ))
        
        # ==========================================
        # ORCHESTRATION TOOLS (Prefect)
        # ==========================================
        
        self._register(Tool(
            name="get_prefect_flow_status",
            description="Get the status of a Prefect flow.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("flow_name", "string", "The flow name"),
            ],
            required_integrations={"PREFECT"},
        ))
        
        self._register(Tool(
            name="get_prefect_flow_runs",
            description="Get recent flow runs for a Prefect flow.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("flow_name", "string", "The flow name"),
                ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
            ],
            required_integrations={"PREFECT"},
        ))
        
        # ==========================================
        # INGESTION TOOLS (Fivetran)
        # ==========================================
        
        self._register(Tool(
            name="get_fivetran_connector_status",
            description="Get the status of a Fivetran connector including sync health and last sync time.",
            category=ToolCategory.INGESTION,
            parameters=[
                ToolParameter("connector_id", "string", "The connector ID or name"),
            ],
            required_integrations={"FIVETRAN"},
        ))
        
        self._register(Tool(
            name="get_fivetran_sync_logs",
            description="Get recent sync logs for a Fivetran connector.",
            category=ToolCategory.INGESTION,
            parameters=[
                ToolParameter("connector_id", "string", "The connector ID or name"),
                ToolParameter("limit", "integer", "Maximum syncs to return", required=False, default=10),
            ],
            required_integrations={"FIVETRAN"},
        ))
        
        self._register(Tool(
            name="get_fivetran_schema_changes",
            description="Get recent schema changes detected by Fivetran.",
            category=ToolCategory.INGESTION,
            parameters=[
                ToolParameter("connector_id", "string", "The connector ID or name"),
                ToolParameter("days", "integer", "How many days back to look", required=False, default=7),
            ],
            required_integrations={"FIVETRAN"},
        ))
        
        # ==========================================
        # INGESTION TOOLS (Airbyte)
        # ==========================================
        
        self._register(Tool(
            name="get_airbyte_connection_status",
            description="Get the status of an Airbyte connection.",
            category=ToolCategory.INGESTION,
            parameters=[
                ToolParameter("connection_id", "string", "The connection ID or name"),
            ],
            required_integrations={"AIRBYTE"},
        ))
        
        self._register(Tool(
            name="get_airbyte_sync_history",
            description="Get sync history for an Airbyte connection.",
            category=ToolCategory.INGESTION,
            parameters=[
                ToolParameter("connection_id", "string", "The connection ID or name"),
                ToolParameter("limit", "integer", "Maximum syncs to return", required=False, default=10),
            ],
            required_integrations={"AIRBYTE"},
        ))
        
        # ==========================================
        # REPORTING TOOLS
        # ==========================================
        
        self._register(Tool(
            name="get_looker_dashboard_status",
            description="Get the status of a Looker dashboard including any broken tiles.",
            category=ToolCategory.REPORTING,
            parameters=[
                ToolParameter("dashboard_id", "string", "The dashboard ID or name"),
            ],
            required_integrations={"LOOKER"},
        ))
        
        self._register(Tool(
            name="get_looker_model_info",
            description="Get information about a Looker model including explores and views.",
            category=ToolCategory.REPORTING,
            parameters=[
                ToolParameter("model_name", "string", "The LookML model name"),
            ],
            required_integrations={"LOOKER"},
        ))
    
    def _register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())
    
    def get_available_tools(self, user_integrations: Set[str]) -> List[Tool]:
        """
        Get tools available for the user's integrations.
        
        This is the key function - it filters tools based on
        what the user has actually connected.
        """
        return [
            tool for tool in self._tools.values()
            if tool.is_available(user_integrations)
        ]
    
    def get_tools_by_category(self, category: ToolCategory) -> List[Tool]:
        """Get all tools in a category."""
        return [
            tool for tool in self._tools.values()
            if tool.category == category
        ]
    
    def to_anthropic_tools(self, user_integrations: Set[str]) -> List[Dict[str, Any]]:
        """
        Convert available tools to Anthropic format.
        
        Only includes tools that are available for the user's integrations.
        """
        available = self.get_available_tools(user_integrations)
        return [tool.to_anthropic_tool() for tool in available]
    
    def to_openai_tools(self, user_integrations: Set[str]) -> List[Dict[str, Any]]:
        """
        Convert available tools to OpenAI format.
        
        Only includes tools that are available for the user's integrations.
        """
        available = self.get_available_tools(user_integrations)
        return [tool.to_openai_tool() for tool in available]


# Global registry instance
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _registry
