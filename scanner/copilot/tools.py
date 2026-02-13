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
    KNOWLEDGE = "knowledge"
    OBSERVABILITY = "observability"
    CHANGE_PLAN = "change_plan"
    ONBOARDING = "onboarding"


@dataclass
class ToolParameter:
    """A parameter for a tool."""
    name: str
    type: str  # string, integer, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None
    items: Optional[Dict[str, Any]] = None  # For array types: schema of array items


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
            if param.type == "array" and param.items:
                prop["items"] = param.items
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
            if param.type == "array" and param.items:
                prop["items"] = param.items
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
            description="Get all upstream dependencies (tables/models that feed into this node). Use this to understand where data comes from. Supports optional filtering by lineage level, confidence, and system.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("node_id", "string", "The fully qualified name of the node (e.g., 'database.schema.table')"),
                ToolParameter("depth", "integer", "How many levels upstream to traverse (-1 for all)", required=False, default=-1),
                ToolParameter("level", "string", "Filter by lineage level", required=False, enum=["tool", "table", "column"]),
                ToolParameter("min_confidence", "number", "Minimum edge confidence (0.0-1.0)", required=False),
                ToolParameter("system", "string", "Filter to a specific system (e.g., 'bigquery', 'dbt', 'looker')", required=False),
            ],
            alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DBT_CLOUD", "DBT_CORE"},
        ))

        self._register(Tool(
            name="get_downstream",
            description="Get all downstream dependents (tables/models/dashboards that depend on this node). Use this to understand impact of changes. Supports optional filtering by lineage level, confidence, and system.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("node_id", "string", "The fully qualified name of the node"),
                ToolParameter("depth", "integer", "How many levels downstream to traverse (-1 for all)", required=False, default=-1),
                ToolParameter("level", "string", "Filter by lineage level", required=False, enum=["tool", "table", "column"]),
                ToolParameter("min_confidence", "number", "Minimum edge confidence (0.0-1.0)", required=False),
                ToolParameter("system", "string", "Filter to a specific system (e.g., 'bigquery', 'dbt', 'looker')", required=False),
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

        self._register(Tool(
            name="analyze_change_impact",
            description="Analyze the full impact of a proposed change. Returns upstream sources, downstream dependents, breaking changes, and required remediations. ALWAYS call this BEFORE making any code changes or plans that modify tables/models.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter(
                    "objects",
                    "array",
                    "List of tables/models being changed (fully qualified names)",
                    items={"type": "string"},
                ),
                ToolParameter(
                    "change_type",
                    "string",
                    "Type of change being made",
                    enum=["RENAME", "MOVE", "DELETE", "MODIFY_COLUMNS", "MODIFY_LOGIC"],
                ),
                ToolParameter(
                    "details",
                    "string",
                    "Specific change details (e.g., 'moving from dbt_dev to analytics dataset')",
                ),
            ],
            alternative_integrations={"BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT", "DBT_CLOUD", "DBT_CORE"},
        ))

        self._register(Tool(
            name="explain_edge",
            description="Explain a lineage edge — shows evidence provenance, confidence score, source adapter, and how the relationship was discovered. Use this when the user asks WHY two assets are connected or wants to verify lineage accuracy.",
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("edge_id", "string", "The edge ID to explain (from upstream/downstream results)"),
            ],
        ))

        self._register(Tool(
            name="get_lineage_stats",
            description="Get lineage coverage statistics: total nodes/edges, coverage by level (tool/table/column), confidence distribution, and resolution quality. Use this to assess lineage completeness.",
            category=ToolCategory.LINEAGE,
            parameters=[],
        ))

        # ==========================================
        # WAREHOUSE TOOLS
        # ==========================================
        
        self._register(Tool(
            name="query_warehouse",
            description="Execute a read-only SQL query against the warehouse. Only SELECT statements are allowed. When multiple warehouses are connected, use the 'warehouse' parameter to specify which one to query.",
            category=ToolCategory.WAREHOUSE,
            parameters=[
                ToolParameter("sql", "string", "The SQL query to execute (SELECT only)"),
                ToolParameter("warehouse", "string", "Which warehouse to query (e.g. 'bigquery', 'snowflake'). Required when multiple warehouses are connected.", required=False,
                             enum=["bigquery", "snowflake", "postgres", "redshift"]),
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

        self._register(Tool(
            name="get_airflow_dag_lineage",
            description="Get the lineage subgraph for an Airflow DAG — shows the DAG's tasks, their upstream/downstream table dependencies, and how they connect to warehouse tables. Use when the user asks about what tables a DAG reads/writes, or the data flow through an orchestration pipeline.",
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("dag_id", "string", "The DAG ID to get lineage for"),
                ToolParameter("depth", "integer", "How many hops to traverse from the DAG node", required=False, default=3),
            ],
            required_integrations={"AIRFLOW"},
        ))

        self._register(Tool(
            name="get_asset_orchestration_context",
            description=(
                "Get the orchestration context for a data asset (table, view, model). "
                "Returns producing DAG/task, last run status, success rate, and freshness. "
                "Use when the user asks 'why is my_table stale?', 'what produces this table?', "
                "or 'when did this table last update?'."
            ),
            category=ToolCategory.LINEAGE,
            parameters=[
                ToolParameter("asset_name", "string", "The fully qualified name of the data asset (e.g., 'project.dataset.table')"),
            ],
        ))

        self._register(Tool(
            name="get_dag_run_history",
            description=(
                "Get recent DAG run history with task-level details. "
                "Returns run states, durations, task success/failure breakdown. "
                "Use when the user asks about DAG run history, failure patterns, "
                "or wants to investigate a specific run."
            ),
            category=ToolCategory.ORCHESTRATION,
            parameters=[
                ToolParameter("dag_id", "string", "The DAG ID"),
                ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
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

        # ==========================================
        # KNOWLEDGE BASE TOOLS (always available)
        # ==========================================

        self._register(Tool(
            name="search_knowledge_base",
            description=(
                "Search the Pallisade knowledge base for expert guidance on data pipeline tools, "
                "troubleshooting, best practices, and comparisons. Use this when the user asks "
                "about how tools work, how to debug or fix errors, best practices, tool differences, "
                "or migration advice. Returns curated articles with step-by-step guidance. "
                "Examples: 'how to fix a dbt test failure', 'snowflake vs bigquery', 'airflow DAG best practices'."
            ),
            category=ToolCategory.KNOWLEDGE,
            parameters=[
                ToolParameter(
                    "query", "string",
                    "Search query describing what the user wants to know about",
                ),
                ToolParameter(
                    "category", "string",
                    "Optional category filter to narrow results",
                    required=False,
                    enum=["troubleshooting", "best_practices", "comparison", "how_to", "architecture", "migration"],
                ),
                ToolParameter(
                    "tool_filter", "string",
                    "Optional comma-separated tool filter (e.g., 'dbt,snowflake')",
                    required=False,
                ),
            ],
            # No required_integrations — always available
        ))

        # ==========================================
        # OBSERVABILITY TOOLS (Monte Carlo, Bigeye, Soda, Elementary)
        # ==========================================

        self._register(Tool(
            name="get_active_incidents",
            description=(
                "Get active data quality incidents from connected observability tools. "
                "Returns freshness violations, volume anomalies, schema changes, and quality issues. "
                "Use this as a first step when debugging data quality problems."
            ),
            category=ToolCategory.OBSERVABILITY,
            parameters=[
                ToolParameter(
                    "severity", "string",
                    "Filter by severity level",
                    required=False,
                    enum=["critical", "high", "medium", "low", "info"],
                ),
                ToolParameter(
                    "asset", "string",
                    "Filter by asset name pattern (e.g., 'mydb.myschema.%')",
                    required=False,
                ),
                ToolParameter(
                    "limit", "integer",
                    "Maximum incidents to return",
                    required=False,
                    default=20,
                ),
            ],
            alternative_integrations={"MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY"},
        ))

        self._register(Tool(
            name="get_asset_quality",
            description=(
                "Get data quality health status for a specific table or model. "
                "Returns health score, active incidents, check pass rate, freshness, and volume status. "
                "Use this to understand the overall quality state of an asset."
            ),
            category=ToolCategory.OBSERVABILITY,
            parameters=[
                ToolParameter(
                    "asset_name", "string",
                    "The fully qualified name of the asset (e.g., 'database.schema.table')",
                ),
            ],
            alternative_integrations={"MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY"},
        ))

        self._register(Tool(
            name="trace_incident_root_cause",
            description=(
                "Trace a data quality incident upstream through lineage to find the root cause. "
                "Checks upstream tables for related incidents that might have caused the downstream issue. "
                "Useful when a table is stale or has quality issues due to upstream problems."
            ),
            category=ToolCategory.OBSERVABILITY,
            parameters=[
                ToolParameter(
                    "incident_id", "string",
                    "The ID of the incident to trace (from get_active_incidents)",
                    required=False,
                ),
                ToolParameter(
                    "asset_name", "string",
                    "The asset to check for upstream issues (alternative to incident_id)",
                    required=False,
                ),
                ToolParameter(
                    "depth", "integer",
                    "How many levels upstream to search",
                    required=False,
                    default=3,
                ),
            ],
            alternative_integrations={"MONTE_CARLO", "BIGEYE", "ELEMENTARY"},
        ))

        self._register(Tool(
            name="get_quality_checks",
            description=(
                "Get data quality checks/monitors configured for an asset. "
                "Shows what monitoring is in place, thresholds, and current status. "
                "Useful to understand what quality gates exist for a table."
            ),
            category=ToolCategory.OBSERVABILITY,
            parameters=[
                ToolParameter(
                    "asset_name", "string",
                    "The fully qualified name of the asset",
                ),
            ],
            alternative_integrations={"MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY"},
        ))

        self._register(Tool(
            name="get_incident_details",
            description=(
                "Get detailed information about a specific data quality incident. "
                "Returns full context including expected/actual values, affected assets, and timeline."
            ),
            category=ToolCategory.OBSERVABILITY,
            parameters=[
                ToolParameter(
                    "incident_id", "string",
                    "The ID of the incident to get details for",
                ),
            ],
            alternative_integrations={"MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY"},
        ))

        # ==========================================
        # CHANGE PLAN TOOLS (Fix Mode)
        # ==========================================

        self._register(Tool(
            name="create_change_plan",
            description=(
                "Create a structured change plan with patches for fixing data pipeline issues. "
                "The plan includes file patches, rationale, impact analysis, and rollback steps. "
                "After creation, the plan can be validated and applied via GitHub PR."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[
                ToolParameter(
                    "title", "string",
                    "Short title for the fix (e.g., 'Fix null values in customer_id')",
                ),
                ToolParameter(
                    "root_cause", "string",
                    "Root cause analysis explaining why the issue occurred",
                ),
                ToolParameter(
                    "patches", "array",
                    "List of file patches to apply",
                    items={
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to the file to modify"},
                            "patch_type": {"type": "string", "enum": ["sql_model", "yaml_config", "python_script", "orchestration", "text_file"], "description": "Type of file: sql_model (.sql), yaml_config (.yml/.yaml), python_script (.py), orchestration (Airflow DAG .py), text_file (.md, .txt, .gitignore, .cfg, requirements.txt, Dockerfile, etc.)"},
                            "new_content": {"type": "string", "description": "The new content for the file"},
                            "rationale": {"type": "string", "description": "Why this change fixes the issue"},
                            "original_content": {"type": "string", "description": "Original file content (optional)"},
                            "rollback_steps": {"type": "array", "items": {"type": "string"}, "description": "Steps to undo this change"},
                        },
                        "required": ["file_path", "patch_type", "new_content", "rationale"],
                    },
                ),
                ToolParameter(
                    "impact_analysis", "object",
                    "Impact analysis: {affected_tables?, downstream_dependencies?, risk_level?, expected_data_changes?}",
                    required=False,
                ),
                ToolParameter(
                    "description", "string",
                    "Detailed description of the fix",
                    required=False,
                ),
            ],
        ))

        self._register(Tool(
            name="validate_change_plan",
            description=(
                "Run validation checks on a change plan. Validates syntax, compiles dbt models, "
                "and optionally runs sandbox tests. Call this after create_change_plan."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[
                ToolParameter(
                    "plan_id", "string",
                    "The ID of the change plan to validate",
                ),
                ToolParameter(
                    "level", "string",
                    "Validation level: 'static' (syntax/lint), 'ci' (compile/tests), 'sandbox' (shadow run)",
                    enum=["static", "ci", "sandbox"],
                ),
            ],
        ))

        self._register(Tool(
            name="get_change_plan",
            description=(
                "Retrieve a change plan by ID. Returns the plan with patches, validation status, and current state."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[
                ToolParameter(
                    "plan_id", "string",
                    "The ID of the change plan to retrieve",
                ),
            ],
        ))

        self._register(Tool(
            name="apply_change_plan",
            description=(
                "Apply a validated change plan by creating a GitHub Pull Request. "
                "The plan must have passed at least static validation. "
                "If repo_owner/repo_name are not provided, will auto-detect from connected GitHub integration. "
                "Returns the PR URL on success."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[
                ToolParameter(
                    "plan_id", "string",
                    "The ID of the validated change plan to apply",
                ),
                ToolParameter(
                    "repo_owner", "string",
                    "GitHub repository owner (username or organization). Auto-detected if not provided.",
                    required=False,
                ),
                ToolParameter(
                    "repo_name", "string",
                    "GitHub repository name. Auto-detected if not provided.",
                    required=False,
                ),
                ToolParameter(
                    "base_branch", "string",
                    "Branch to base the PR on",
                    required=False,
                    default="main",
                ),
            ],
        ))

        self._register(Tool(
            name="list_change_plans",
            description=(
                "List all change plans in the current session. "
                "Shows plan IDs, titles, status, and validation state."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[],
        ))

        # ==========================================
        # GitHub Tools
        # ==========================================

        self._register(Tool(
            name="list_github_repos",
            description=(
                "List GitHub repositories available from the connected GitHub integration. "
                "Returns repo names, default branches, and basic metadata."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[],
            alternative_integrations={"GITHUB"},
        ))

        self._register(Tool(
            name="get_github_tree",
            description=(
                "Get the file tree (directory structure) of a GitHub repository. "
                "Useful for understanding repo structure before reading files."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[
                ToolParameter(
                    "repo", "string",
                    "Repository in format 'owner/repo' (e.g., 'acme/dbt-models')",
                ),
                ToolParameter(
                    "path", "string",
                    "Path to list (e.g., 'models/' or 'models/staging'). Use '' for root.",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    "branch", "string",
                    "Branch to read from (default: main)",
                    required=False,
                    default="main",
                ),
            ],
            alternative_integrations={"GITHUB"},
        ))

        self._register(Tool(
            name="get_github_file",
            description=(
                "Read the contents of a file from a GitHub repository. "
                "Use this to examine dbt models, SQL files, YAML configs, etc."
            ),
            category=ToolCategory.CHANGE_PLAN,
            parameters=[
                ToolParameter(
                    "repo", "string",
                    "Repository in format 'owner/repo' (e.g., 'acme/dbt-models')",
                ),
                ToolParameter(
                    "path", "string",
                    "Path to the file (e.g., 'models/staging/stg_customers.sql')",
                ),
                ToolParameter(
                    "branch", "string",
                    "Branch to read from (default: main)",
                    required=False,
                    default="main",
                ),
            ],
            alternative_integrations={"GITHUB"},
        ))

        # ==========================================
        # ONBOARDING TOOLS
        # ==========================================

        self._register(Tool(
            name="get_pending_questions",
            description="Get the next onboarding questions that haven't been answered yet. Returns questions sorted by priority.",
            category=ToolCategory.ONBOARDING,
            parameters=[
                ToolParameter(
                    "integration_type",
                    "string",
                    "Optional filter to get questions for a specific integration type (e.g., 'DBT_CORE', 'BIGQUERY')",
                    required=False,
                ),
                ToolParameter(
                    "limit",
                    "integer",
                    "Maximum number of questions to return",
                    required=False,
                    default=3,
                ),
            ],
        ))

        self._register(Tool(
            name="save_onboarding_context",
            description="Save the user's answer to an onboarding question. Extracts key facts and stores them for future use.",
            category=ToolCategory.ONBOARDING,
            parameters=[
                ToolParameter(
                    "question_key",
                    "string",
                    "The unique key of the question being answered (e.g., 'dbt_deployment_method')",
                ),
                ToolParameter(
                    "answer",
                    "string",
                    "The user's answer to the question",
                ),
                ToolParameter(
                    "extracted_facts",
                    "object",
                    "Key-value pairs of facts extracted from the answer (e.g., {'deployment_method': 'github_actions', 'workflow_path': '.github/workflows/dbt.yml'})",
                    required=False,
                ),
            ],
        ))

        self._register(Tool(
            name="complete_onboarding",
            description="Mark onboarding as complete for this pipeline or a specific integration.",
            category=ToolCategory.ONBOARDING,
            parameters=[
                ToolParameter(
                    "integration_id",
                    "string",
                    "Optional: complete onboarding for a specific integration only",
                    required=False,
                ),
                ToolParameter(
                    "summary",
                    "string",
                    "Summary of what was learned during onboarding",
                    required=False,
                ),
            ],
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
