"""Orchestration tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
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
)
def _meta_get_dag_run_history():
    pass


@register_tool(
    name="get_dagster_asset_status",
    description="Get the materialization status of a Dagster asset.",
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("asset_key", "string", "The asset key"),
    ],
    required_integrations={"DAGSTER"},
)
def _meta_get_dagster_asset_status():
    pass


@register_tool(
    name="get_dagster_run_history",
    description="Get recent Dagster job runs.",
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("job_name", "string", "The job name (optional)", required=False),
        ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
    ],
    required_integrations={"DAGSTER"},
)
def _meta_get_dagster_run_history():
    pass


@register_tool(
    name="get_prefect_flow_status",
    description="Get the status of a Prefect flow.",
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("flow_name", "string", "The flow name"),
    ],
    required_integrations={"PREFECT"},
)
def _meta_get_prefect_flow_status():
    pass


@register_tool(
    name="get_prefect_flow_runs",
    description="Get recent flow runs for a Prefect flow.",
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("flow_name", "string", "The flow name"),
        ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
    ],
    required_integrations={"PREFECT"},
)
def _meta_get_prefect_flow_runs():
    pass


@register_tool(
    name="get_n8n_workflows",
    description=(
        "List n8n workflows with their active/inactive status, node count, and tags. "
        "Use this to get an overview of all workflows in the n8n instance."
    ),
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("active_only", "boolean", "Only return active workflows", required=False, default=False),
        ToolParameter("limit", "integer", "Maximum workflows to return", required=False, default=50),
    ],
    required_integrations={"N8N"},
)
def _meta_get_n8n_workflows():
    pass


@register_tool(
    name="get_n8n_workflow_details",
    description=(
        "Get detailed information about an n8n workflow including all nodes, their types, "
        "and how they connect. Use this to understand what a workflow does step by step."
    ),
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("workflow_id", "string", "The n8n workflow ID"),
    ],
    required_integrations={"N8N"},
)
def _meta_get_n8n_workflow_details():
    pass


@register_tool(
    name="get_n8n_executions",
    description=(
        "Get recent execution history for n8n workflows. Shows status (success/error), "
        "duration, and trigger mode. Optionally filter by workflow ID or status."
    ),
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("workflow_id", "string", "Filter by workflow ID", required=False),
        ToolParameter("status", "string", "Filter by status: success, error, waiting, running", required=False),
        ToolParameter("limit", "integer", "Maximum executions to return", required=False, default=20),
    ],
    required_integrations={"N8N"},
)
def _meta_get_n8n_executions():
    pass


@register_tool(
    name="get_n8n_execution_details",
    description=(
        "Get full details of a specific n8n execution, including per-node execution results, "
        "timing, items processed, and error information. Use this to investigate why an "
        "execution failed and which specific node caused the failure."
    ),
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("execution_id", "string", "The execution ID to inspect"),
    ],
    required_integrations={"N8N"},
)
def _meta_get_n8n_execution_details():
    pass


@register_tool(
    name="get_n8n_recent_failures",
    description=(
        "Get recent failed n8n executions with error details including which node failed "
        "and the error message. Use this as a starting point to investigate n8n issues."
    ),
    category=ToolCategory.ORCHESTRATION,
    parameters=[
        ToolParameter("workflow_id", "string", "Filter to a specific workflow", required=False),
        ToolParameter("limit", "integer", "Maximum failures to return", required=False, default=10),
    ],
    required_integrations={"N8N"},
)
def _meta_get_n8n_recent_failures():
    pass
