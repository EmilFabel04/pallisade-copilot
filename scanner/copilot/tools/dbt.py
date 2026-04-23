"""dbt tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_dbt_model",
    description="Get details about a dbt model including its SQL, dependencies, tests, and documentation.",
    category=ToolCategory.DBT,
    parameters=[
        ToolParameter("model_name", "string", "The name of the dbt model"),
    ],
    alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
)
def _meta_get_dbt_model():
    pass


@register_tool(
    name="get_dbt_run_history",
    description="Get recent dbt run history for a model or the entire project.",
    category=ToolCategory.DBT,
    parameters=[
        ToolParameter("model_name", "string", "The model name (optional, omit for all models)", required=False),
        ToolParameter("limit", "integer", "Maximum runs to return", required=False, default=10),
    ],
    alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
)
def _meta_get_dbt_run_history():
    pass


@register_tool(
    name="get_dbt_test_results",
    description="Get test results for a dbt model or source.",
    category=ToolCategory.DBT,
    parameters=[
        ToolParameter("model_name", "string", "The model or source name"),
        ToolParameter("include_passing", "boolean", "Include passing tests", required=False, default=False),
    ],
    alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
)
def _meta_get_dbt_test_results():
    pass


@register_tool(
    name="get_dbt_lineage",
    description="Get the dbt-specific lineage for a model showing parent and child models.",
    category=ToolCategory.DBT,
    parameters=[
        ToolParameter("model_name", "string", "The model name"),
    ],
    alternative_integrations={"DBT_CLOUD", "DBT_CORE"},
)
def _meta_get_dbt_lineage():
    pass
