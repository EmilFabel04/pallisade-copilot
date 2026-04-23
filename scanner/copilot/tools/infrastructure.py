"""Infrastructure tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="check_server_health",
    description=(
        "Get CPU, memory, disk usage, and load average for a connected Linux server. "
        "Returns system health metrics including hostname, OS info, and uptime."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    alternative_integrations={"linux_server"},
    parameters=[
        ToolParameter(
            "server",
            "string",
            "Name of the server integration to check (as shown in the pipeline)",
            required=True,
        ),
    ],
)
def _meta_check_server_health():
    pass


@register_tool(
    name="check_certificates",
    description=(
        "Check TLS/SSL certificate expiry and client cert presence on a server. "
        "Detects missing client certs, expired certs, and certs expiring soon. "
        "Scans common cert locations if no paths specified."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    alternative_integrations={"linux_server"},
    parameters=[
        ToolParameter(
            "server",
            "string",
            "Name of the server integration to check",
            required=True,
        ),
        ToolParameter(
            "paths",
            "array",
            "Optional: specific certificate file paths to check (auto-discovers if empty)",
            required=False,
            items={"type": "string"},
        ),
    ],
)
def _meta_check_certificates():
    pass


@register_tool(
    name="analyze_server_logs",
    description=(
        "Tail and analyze recent log entries on a server for error patterns. "
        "Searches for ERROR, FATAL, CRITICAL and other patterns in log files."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    alternative_integrations={"linux_server"},
    parameters=[
        ToolParameter(
            "server",
            "string",
            "Name of the server integration",
            required=True,
        ),
        ToolParameter(
            "log_path",
            "string",
            "Path to the log file on the server (e.g. /var/log/syslog)",
            required=True,
        ),
        ToolParameter(
            "lines",
            "integer",
            "Number of lines to tail (default: 200)",
            required=False,
        ),
    ],
)
def _meta_analyze_server_logs():
    pass


@register_tool(
    name="list_server_services",
    description=(
        "List systemd service status on a connected Linux server. "
        "Shows which services are running, stopped, or failed."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    alternative_integrations={"linux_server"},
    parameters=[
        ToolParameter(
            "server",
            "string",
            "Name of the server integration",
            required=True,
        ),
    ],
)
def _meta_list_server_services():
    pass


@register_tool(
    name="check_integration_health",
    description=(
        "Check the health / connectivity of a connected integration. "
        "Returns OK/FAIL status, latency, and last-checked timestamp."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    parameters=[
        ToolParameter(
            "integration_type", "string",
            "The integration type to check (e.g. BIGQUERY, SNOWFLAKE, FIVETRAN, SLACK)",
            required=True,
        ),
    ],
)
def _meta_check_integration_health():
    pass


@register_tool(
    name="list_integration_assets",
    description=(
        "List the data assets discovered from an integration (tables, connectors, "
        "models, dashboards, etc.) with counts and sample names."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    parameters=[
        ToolParameter(
            "integration_type", "string",
            "The integration type to list assets for (e.g. BIGQUERY, DBT_CLOUD, FIVETRAN)",
            required=True,
        ),
    ],
)
def _meta_list_integration_assets():
    pass


@register_tool(
    name="get_integration_capabilities",
    description=(
        "Get the capabilities of a connected integration — what it can do "
        "(query, extract metadata, extract lineage, fetch logs, write, etc.)."
    ),
    category=ToolCategory.INFRASTRUCTURE,
    parameters=[
        ToolParameter(
            "integration_type", "string",
            "The integration type (e.g. BIGQUERY, AIRFLOW, SLACK, JIRA)",
            required=True,
        ),
    ],
)
def _meta_get_integration_capabilities():
    pass
