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
