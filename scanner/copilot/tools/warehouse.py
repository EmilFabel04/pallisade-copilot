"""Warehouse tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="query_warehouse",
    description="Execute a read-only SQL query against the warehouse. Only SELECT statements are allowed. When multiple warehouses are connected, use the 'warehouse' parameter to specify which one to query.",
    category=ToolCategory.WAREHOUSE,
    parameters=[
        ToolParameter("sql", "string", "The SQL query to execute (SELECT only)"),
        ToolParameter("warehouse", "string", "Which warehouse to query (e.g. 'bigquery', 'snowflake', 'databricks'). Required when multiple warehouses are connected.", required=False,
                     enum=["bigquery", "snowflake", "postgres", "redshift", "databricks"]),
        ToolParameter("limit", "integer", "Maximum rows to return", required=False, default=100),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS", "SQLSERVER", "AZURE_SQL"},
)
def _meta_query_warehouse():
    pass


@register_tool(
    name="get_table_stats",
    description="Get statistics about a table including row count, size, last updated time, and column stats.",
    category=ToolCategory.WAREHOUSE,
    parameters=[
        ToolParameter("table_name", "string", "The fully qualified table name"),
    ],
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS"},
)
def _meta_get_table_stats():
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
    alternative_integrations={"SNOWFLAKE", "BIGQUERY", "DATABRICKS"},
)
def _meta_get_query_history():
    pass
