"""Warehouse tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="query_warehouse",
    description="Execute a read-only SQL query against the warehouse. Only SELECT statements are allowed. When multiple warehouses are connected, use the 'warehouse' parameter to specify which one to query.",
    category=ToolCategory.WAREHOUSE,
    parameters=[
        ToolParameter("sql", "string", "The SQL query to execute (SELECT only)"),
        ToolParameter("warehouse", "string", "Which warehouse to query (e.g. 'bigquery', 'snowflake', 'databricks', 'azure_sql'). Required when multiple warehouses are connected.", required=False,
                     enum=["bigquery", "snowflake", "postgres", "redshift", "databricks", "sqlserver", "azure_sql"]),
        ToolParameter("limit", "integer", "Maximum rows to return", required=False, default=100),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "SQLSERVER", "AZURE_SQL"},
)
def _meta_query_warehouse():
    pass


@register_tool(
    name="get_table_stats",
    description="Get statistics about a single table including row count, size, last updated time, and column stats. For stats on multiple tables, prefer `get_table_stats_batch` — it's far cheaper.",
    category=ToolCategory.WAREHOUSE,
    parameters=[
        ToolParameter("table_name", "string", "The fully qualified table name"),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "SQLSERVER", "AZURE_SQL"},
)
def _meta_get_table_stats():
    pass


@register_tool(
    name="get_table_stats_batch",
    description="Get row_count, size, and last-updated time for many tables in a single round-trip. Prefer this over calling get_table_stats repeatedly. Columns are not included — use get_table_stats when column-level detail is needed.",
    category=ToolCategory.WAREHOUSE,
    parameters=[
        ToolParameter(
            "table_names",
            "array",
            "List of fully qualified table names",
            items={"type": "string"},
        ),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "SQLSERVER", "AZURE_SQL"},
)
def _meta_get_table_stats_batch():
    pass


@register_tool(
    name="get_query_history",
    description="Get recent queries that touched a specific table. Useful for understanding data access patterns.",
    category=ToolCategory.WAREHOUSE,
    parameters=[
        ToolParameter("table_name", "string", "The table to get query history for"),
        ToolParameter("hours", "integer", "How many hours back to look", required=False, default=24),
        ToolParameter("limit", "integer", "Maximum queries to return", required=False, default=20),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "SQLSERVER", "AZURE_SQL"},
)
def _meta_get_query_history():
    pass
