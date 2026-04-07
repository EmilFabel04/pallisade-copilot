"""Coverage tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_coverage_report",
    description=(
        "Get a comprehensive coverage analysis for the lineage graph. "
        "Scores every data asset across 7 dimensions: freshness, volume, "
        "schema, quality, lineage, ownership, and documentation. "
        "Returns overall score, per-category breakdowns, and gap counts. "
        "Use this to understand the overall health of observability coverage."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter(
            "node_filter", "string",
            "Optional filter: 'all' (default), 'critical' (critical assets only), "
            "'uncovered' (assets with no coverage), 'tables' (TABLE nodes only).",
            required=False,
            default="all",
        ),
    ],
)
def _meta_get_coverage_report():
    pass


@register_tool(
    name="get_coverage_gaps",
    description=(
        "Identify the most impactful coverage gaps across the lineage graph. "
        "Returns gaps sorted by severity (critical first), with context about "
        "why each gap matters and what to do about it. "
        "Use this to prioritize where to add monitoring next."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter(
            "severity", "string",
            "Filter by severity: 'critical', 'high', 'medium', 'low', 'info', or 'all'.",
            required=False,
            default="all",
            enum=["all", "critical", "high", "medium", "low", "info"],
        ),
        ToolParameter(
            "category", "string",
            "Filter by category: 'freshness', 'volume', 'schema', 'quality', "
            "'lineage', 'ownership', 'documentation', or 'all'.",
            required=False,
            default="all",
            enum=[
                "all", "freshness", "volume", "schema", "quality",
                "lineage", "ownership", "documentation",
            ],
        ),
        ToolParameter(
            "limit", "integer",
            "Maximum number of gaps to return (default: 20).",
            required=False,
            default=20,
        ),
    ],
)
def _meta_get_coverage_gaps():
    pass


@register_tool(
    name="get_node_coverage",
    description=(
        "Get detailed coverage analysis for a specific data asset (node). "
        "Shows which dimensions are covered vs uncovered, with per-category "
        "scores and details about what provides each coverage point."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter(
            "node_name", "string",
            "Name or FQN of the node to analyze (e.g., 'analytics.orders').",
        ),
    ],
)
def _meta_get_node_coverage():
    pass


@register_tool(
    name="get_monitor_recommendations",
    description=(
        "Get actionable monitor recommendations to close coverage gaps. "
        "Returns tech-agnostic monitor configs with SQL templates that work "
        "across any connected warehouse (Snowflake, BigQuery, Postgres, etc.). "
        "Each recommendation includes priority, description, and default config."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter(
            "monitor_type", "string",
            "Filter by monitor type: 'freshness', 'volume', 'schema_change', "
            "'null_rate', 'distribution', 'anomaly', or 'all'.",
            required=False,
            default="all",
            enum=[
                "all", "freshness", "volume", "schema_change",
                "null_rate", "distribution", "anomaly",
            ],
        ),
        ToolParameter(
            "limit", "integer",
            "Maximum number of recommendations to return (default: 10).",
            required=False,
            default=10,
        ),
    ],
)
def _meta_get_monitor_recommendations():
    pass


@register_tool(
    name="run_coverage_monitor",
    description=(
        "Execute a specific monitor against a data asset. "
        "Generates the appropriate SQL for the connected warehouse dialect, "
        "runs it, and evaluates the result. Supports freshness, volume, "
        "schema change, and anomaly detection monitors. "
        "PREFERRED TOOL FOR ANOMALY DETECTION: When the user asks about "
        "anomalies, outliers, unusual patterns, spikes, or drops, use this "
        "with monitor_type='anomaly' instead of writing manual SQL. "
        "It provides Z-score analysis, configurable lookback windows, "
        "and seasonality support out of the box."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter(
            "monitor_type", "string",
            "Type of monitor to run: 'freshness', 'volume', 'schema_change', 'anomaly'.",
            enum=["freshness", "volume", "schema_change", "anomaly"],
        ),
        ToolParameter(
            "table_fqn", "string",
            "Fully qualified table name (database.schema.table).",
        ),
        ToolParameter(
            "config", "object",
            "Monitor-specific config. "
            "freshness: {timestamp_column, max_hours?, warn_hours?}. "
            "volume: {min_rows?, max_rows?, time_bucket_column?, lookback_days?}. "
            "anomaly (REQUIRED keys): {column, metric} where metric is one of "
            "null_rate, distinct_count, distinct_rate, min, max, avg, sum, "
            "stddev, zero_rate; optional: {timestamp_column, lookback_days, "
            "anomaly_threshold, seasonality}. "
            "schema_change: {baseline_columns?, fail_on_column_removed?, "
            "fail_on_column_added?, fail_on_type_change?}.",
            required=False,
        ),
    ],
    alternative_integrations={
        "SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "DATABRICKS",
        "SQLSERVER", "AZURE_SQL", "AZURE_SYNAPSE",
    },
)
def _meta_run_coverage_monitor():
    pass


@register_tool(
    name="create_watch",
    description=(
        "Create a monitor for a data asset. Bundles one or more checks "
        "(freshness, volume, schema_change, anomaly, etc.) with a shared "
        "schedule. Returns an interactive card for the user to review and "
        "confirm before creation. Use watch_type='pipeline_health' for "
        "warehouse tables (default). The user calls these 'monitors', not 'watches'."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter("name", "string", "Name for the monitor (e.g., 'Orders Freshness' or 'Events Volume')"),
        ToolParameter("watch_type", "string",
                      "Category — use pipeline_health for warehouse tables (default)",
                      enum=["pipeline_health", "dashboard_shield",
                            "model_quality", "data_drift", "custom_watch"]),
        ToolParameter("anchor_fqn", "string", "Fully qualified name of the anchor asset (e.g., 'analytics.public.orders')"),
        ToolParameter("monitors", "array", "Array of monitors to include",
                      items={
                          "type": "object",
                          "properties": {
                              "monitor_type": {"type": "string", "enum": [
                                  "FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "ANOMALY",
                                  "NULL_CHECK", "UNIQUENESS_CHECK", "RANGE_VALIDATION",
                                  "ACCEPTED_VALUES", "DATE_CONSISTENCY"
                              ]},
                              "target_fqn": {"type": "string", "description": "Target table FQN"},
                              "config": {"type": "object", "description": (
                                  "Monitor-specific config. "
                                  "ANOMALY requires: {column, metric} where metric is one of "
                                  "null_rate, distinct_count, min, max, avg, sum, stddev, zero_rate. "
                                  "FRESHNESS: {timestamp_column, max_hours}. "
                                  "VOLUME: {min_rows, max_rows}. "
                                  "SCHEMA_CHANGE: no required config."
                              )},
                          },
                          "required": ["monitor_type", "target_fqn"],
                      }),
        ToolParameter("schedule", "string", "Cron schedule (e.g., '0 */6 * * *' for every 6 hours)"),
        ToolParameter("timezone", "string", "Timezone for schedule (e.g., 'UTC', 'America/New_York')",
                      required=False, default="UTC"),
    ],
    requires_confirmation=False,
)
def _meta_create_watch():
    pass


@register_tool(
    name="run_watch",
    description=(
        "Run all monitors in an existing watch immediately. Returns health score, "
        "individual monitor results, and failure categories. Does not require confirmation."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter("watch_id", "string", "The ID of the watch to run"),
    ],
    requires_confirmation=False,
)
def _meta_run_watch():
    pass
