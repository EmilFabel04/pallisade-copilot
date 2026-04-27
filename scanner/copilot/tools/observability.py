"""Observability tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_active_incidents",
    description="Get currently active data incidents across all monitored assets. Shows severity, affected assets, and time since detection.",
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("severity", "string", "Filter by severity level", required=False,
                     enum=["critical", "high", "medium", "low", "all"],
                     default="all"),
        ToolParameter("limit", "integer", "Maximum incidents to return", required=False, default=20),
    ],
)
def _meta_get_active_incidents():
    pass


@register_tool(
    name="get_asset_quality",
    description="Get quality metrics for a specific data asset including freshness, volume trends, schema stability, and null rates.",
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("asset_name", "string", "The fully qualified name of the data asset"),
    ],
)
def _meta_get_asset_quality():
    pass


@register_tool(
    name="trace_incident_root_cause",
    description="Trace the root cause of a data incident by walking upstream through the lineage graph. Identifies the earliest point of failure.",
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("incident_id", "string", "The incident ID to trace"),
    ],
)
def _meta_trace_incident_root_cause():
    pass


@register_tool(
    name="get_quality_checks",
    description="Get quality check results for a data asset. Shows pass/fail status, check types, and historical trends.",
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("asset_name", "string", "The fully qualified name of the data asset"),
        ToolParameter("check_type", "string", "Filter by check type", required=False,
                     enum=["freshness", "volume", "schema", "null_rate", "uniqueness", "all"],
                     default="all"),
    ],
)
def _meta_get_quality_checks():
    pass


@register_tool(
    name="get_incident_details",
    description="Get detailed information about a specific data incident including timeline, affected assets, and resolution status.",
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("incident_id", "string", "The incident ID"),
    ],
)
def _meta_get_incident_details():
    pass


@register_tool(
    name="list_configured_monitors",
    description=(
        "List the user's saved monitors with their current state. "
        "Use this whenever the user asks about THEIR monitors (e.g. 'why are "
        "my dbt monitors failing', 'show me failing monitors', 'what monitors "
        "are on the orders table'). This returns saved configuration — NOT "
        "ad-hoc results. Always call this BEFORE attempting run_coverage_monitor "
        "when the question is about saved monitors."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter(
            "monitor_type", "string",
            "Filter by monitor type. Pass a single value or comma-separated list. "
            "Examples: 'FRESHNESS', 'DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY'. "
            "Case-insensitive. Common values: FRESHNESS, VOLUME, NULL_CHECK, "
            "SCHEMA_CHANGE, ANOMALY, UNIQUENESS_CHECK, DBT_TEST_FAILURES, "
            "DBT_CORE_SOURCE_VALIDATION, DBT_CORE_REF_INTEGRITY, DAG_LAST_RUN, "
            "TASK_FAILURE_RATE, SYNC_LAG, FAILED_SYNCS.",
            required=False,
        ),
        ToolParameter(
            "status", "string",
            "Filter by last-run status. Pass a single value or comma-separated list. "
            "Values: PASS, WARN, FAIL, ERROR, SKIPPED, RUNNING.",
            required=False,
        ),
        ToolParameter(
            "target_fqn", "string",
            "Restrict to monitors whose target is exactly this FQN (e.g. 'analytics.orders').",
            required=False,
        ),
        ToolParameter(
            "enabled", "boolean",
            "Restrict to enabled (true) or disabled (false) monitors. Omit to include both.",
            required=False,
        ),
        ToolParameter(
            "limit", "integer",
            "Maximum number of monitors to return (default 50, max 200).",
            required=False,
            default=50,
        ),
    ],
)
def _meta_list_configured_monitors():
    pass


@register_tool(
    name="get_monitor_run_history",
    description=(
        "Get recent run history for a specific saved monitor — including the "
        "actual error message, SQL executed, and timing for each run. "
        "Use this AFTER list_configured_monitors when you've identified a "
        "specific failing monitor and want to see why it failed."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter(
            "monitor_id", "string",
            "The saved monitor's id (from list_configured_monitors).",
        ),
        ToolParameter(
            "limit", "integer",
            "Number of recent runs to return (default 10, max 50).",
            required=False,
            default=10,
        ),
    ],
)
def _meta_get_monitor_run_history():
    pass
