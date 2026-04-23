"""Lineage tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
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
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "DBT_CLOUD", "DBT_CORE", "TABLEAU", "POWERBI"},
)
def _meta_get_upstream():
    pass


@register_tool(
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
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "DBT_CLOUD", "DBT_CORE", "TABLEAU", "POWERBI"},
)
def _meta_get_downstream():
    pass


@register_tool(
    name="get_node_details",
    description="Get detailed information about a specific node (table, model, view, etc.) including schema, stats, and metadata.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("node_id", "string", "The fully qualified name of the node"),
    ],
)
def _meta_get_node_details():
    pass


@register_tool(
    name="search_lineage",
    description="Search for nodes in the lineage graph by name pattern or type.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("query", "string", "Search query (supports wildcards like 'stg_*' or '*_orders')"),
        ToolParameter("node_type", "string", "Filter by node type", required=False,
                     enum=["table", "view", "model", "source", "dashboard", "all"]),
        ToolParameter("limit", "integer", "Maximum results to return", required=False, default=20),
    ],
)
def _meta_search_lineage():
    pass


@register_tool(
    name="get_column_lineage",
    description="Get column-level lineage showing how a specific column flows through transformations.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("node_id", "string", "The fully qualified name of the node"),
        ToolParameter("column_name", "string", "The column to trace"),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "DATABRICKS", "DBT_CLOUD", "DBT_CORE"},
)
def _meta_get_column_lineage():
    pass


@register_tool(
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
    alternative_integrations={"BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT", "DATABRICKS", "DBT_CLOUD", "DBT_CORE"},
)
def _meta_analyze_change_impact():
    pass


@register_tool(
    name="explain_edge",
    description="Explain a lineage edge — shows evidence provenance, confidence score, source adapter, and how the relationship was discovered. Use this when the user asks WHY two assets are connected or wants to verify lineage accuracy.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("edge_id", "string", "The edge ID to explain (from upstream/downstream results)"),
    ],
)
def _meta_explain_edge():
    pass


@register_tool(
    name="get_lineage_stats",
    description="Get lineage coverage statistics: total nodes/edges, coverage by level (tool/table/column), confidence distribution, and resolution quality. Use this to assess lineage completeness.",
    category=ToolCategory.LINEAGE,
    parameters=[],
)
def _meta_get_lineage_stats():
    pass


@register_tool(
    name="get_table_dependencies",
    description="Get upstream (source) and downstream (dependent) tables for a specific table. Shows what feeds into this table and what depends on it.",
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("table_name", "string", "The fully qualified table name (dataset.table or schema.table)"),
        ToolParameter("direction", "string", "Which dependencies to get", required=False,
                     enum=["upstream", "downstream", "both"], default="both"),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "DATABRICKS"},
)
def _meta_get_table_dependencies():
    pass


@register_tool(
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
)
def _meta_get_asset_orchestration_context():
    pass
