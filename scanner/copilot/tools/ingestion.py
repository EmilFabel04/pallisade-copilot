"""Ingestion tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_fivetran_connector_status",
    description="Get the status of a Fivetran connector including sync health and last sync time.",
    category=ToolCategory.INGESTION,
    parameters=[
        ToolParameter("connector_id", "string", "The connector ID or name"),
    ],
    required_integrations={"FIVETRAN"},
)
def _meta_get_fivetran_connector_status():
    pass


@register_tool(
    name="get_fivetran_sync_logs",
    description="Get recent sync logs for a Fivetran connector.",
    category=ToolCategory.INGESTION,
    parameters=[
        ToolParameter("connector_id", "string", "The connector ID or name"),
        ToolParameter("limit", "integer", "Maximum syncs to return", required=False, default=10),
    ],
    required_integrations={"FIVETRAN"},
)
def _meta_get_fivetran_sync_logs():
    pass


@register_tool(
    name="get_fivetran_schema_changes",
    description="Get recent schema changes detected by Fivetran.",
    category=ToolCategory.INGESTION,
    parameters=[
        ToolParameter("connector_id", "string", "The connector ID or name"),
        ToolParameter("days", "integer", "How many days back to look", required=False, default=7),
    ],
    required_integrations={"FIVETRAN"},
)
def _meta_get_fivetran_schema_changes():
    pass


@register_tool(
    name="get_airbyte_connection_status",
    description="Get the status of an Airbyte connection.",
    category=ToolCategory.INGESTION,
    parameters=[
        ToolParameter("connection_id", "string", "The connection ID or name"),
    ],
    required_integrations={"AIRBYTE"},
)
def _meta_get_airbyte_connection_status():
    pass


@register_tool(
    name="get_airbyte_sync_history",
    description="Get sync history for an Airbyte connection.",
    category=ToolCategory.INGESTION,
    parameters=[
        ToolParameter("connection_id", "string", "The connection ID or name"),
        ToolParameter("limit", "integer", "Maximum syncs to return", required=False, default=10),
    ],
    required_integrations={"AIRBYTE"},
)
def _meta_get_airbyte_sync_history():
    pass
