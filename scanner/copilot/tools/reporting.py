"""Reporting tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_looker_dashboard_status",
    description="Get the status of a Looker dashboard including any broken tiles.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("dashboard_id", "string", "The dashboard ID or name"),
    ],
    required_integrations={"LOOKER"},
)
def _meta_get_looker_dashboard_status():
    pass


@register_tool(
    name="get_looker_model_info",
    description="Get information about a Looker model including explores and views.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("model_name", "string", "The LookML model name"),
    ],
    required_integrations={"LOOKER"},
)
def _meta_get_looker_model_info():
    pass


@register_tool(
    name="get_tableau_workbook_status",
    description="Get status of a Tableau workbook including refresh status, data sources, and views. Use this to check workbook health and identify broken data sources.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("workbook_name", "string", "The workbook name or ID"),
    ],
    required_integrations={"TABLEAU"},
)
def _meta_get_tableau_workbook_status():
    pass


@register_tool(
    name="get_tableau_datasource_info",
    description="Get Tableau data source details: connection type, tables used, last refresh, and extract schedule. Useful for understanding how Tableau connects to the warehouse.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("datasource_name", "string", "The data source name or ID"),
    ],
    required_integrations={"TABLEAU"},
)
def _meta_get_tableau_datasource_info():
    pass


@register_tool(
    name="get_tableau_refresh_history",
    description="Get recent extract refresh history for a Tableau datasource or workbook. Shows success/failure status, duration, and error messages.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("datasource_name", "string", "The data source name (optional, omit for all)", required=False),
        ToolParameter("limit", "integer", "Maximum results to return", required=False, default=10),
    ],
    required_integrations={"TABLEAU"},
)
def _meta_get_tableau_refresh_history():
    pass


@register_tool(
    name="get_powerbi_dataset_status",
    description="Get Power BI dataset refresh status, last refresh time, and configured data sources. Use to check dataset health and connectivity.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("dataset_name", "string", "The dataset name or ID"),
    ],
    required_integrations={"POWERBI"},
)
def _meta_get_powerbi_dataset_status():
    pass


@register_tool(
    name="get_powerbi_refresh_history",
    description="Get recent refresh history for a Power BI dataset. Shows refresh status, duration, and failure reasons.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("dataset_name", "string", "The dataset name or ID"),
        ToolParameter("limit", "integer", "Maximum results to return", required=False, default=10),
    ],
    required_integrations={"POWERBI"},
)
def _meta_get_powerbi_refresh_history():
    pass


@register_tool(
    name="get_powerbi_gateway_status",
    description="Get Power BI gateway health and status for on-premises data connections. Use to diagnose connectivity issues between Power BI and on-prem data sources.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("gateway_name", "string", "Gateway name or ID (optional, omit for all gateways)", required=False),
    ],
    required_integrations={"POWERBI"},
)
def _meta_get_powerbi_gateway_status():
    pass


@register_tool(
    name="get_metabase_dashboard_status",
    description="Get Metabase dashboard status including card count, broken cards, and last update time. Use to check dashboard health.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("dashboard_id", "integer", "The dashboard ID"),
    ],
    required_integrations={"METABASE"},
)
def _meta_get_metabase_dashboard_status():
    pass


@register_tool(
    name="get_metabase_card_info",
    description="Get Metabase card (saved question) details: query type, database, display type, performance metrics, and errors. Use to diagnose slow or broken questions.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("card_id", "integer", "The card/question ID"),
    ],
    required_integrations={"METABASE"},
)
def _meta_get_metabase_card_info():
    pass


@register_tool(
    name="get_metabase_database_status",
    description="Get Metabase database connection status including sync state, engine type, and configuration. Use to check if Metabase can reach its data sources.",
    category=ToolCategory.REPORTING,
    parameters=[
        ToolParameter("database_id", "integer", "The database ID (optional, omit for all databases)", required=False),
    ],
    required_integrations={"METABASE"},
)
def _meta_get_metabase_database_status():
    pass
