"""GitHub tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="list_github_repos",
    description=(
        "List GitHub repositories available from the connected GitHub integration. "
        "Returns repo names, default branches, and basic metadata."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[],
    alternative_integrations={"GITHUB"},
)
def _meta_list_github_repos():
    pass


@register_tool(
    name="get_github_tree",
    description=(
        "Get the file tree (directory structure) of a GitHub repository. "
        "Useful for understanding repo structure before reading files."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[
        ToolParameter(
            "repo", "string",
            "Repository in format 'owner/repo' (e.g., 'acme/dbt-models')",
        ),
        ToolParameter(
            "path", "string",
            "Path to list (e.g., 'models/' or 'models/staging'). Use '' for root.",
            required=False,
            default="",
        ),
        ToolParameter(
            "branch", "string",
            "Branch to read from (default: main)",
            required=False,
            default="main",
        ),
    ],
    alternative_integrations={"GITHUB"},
)
def _meta_get_github_tree():
    pass


@register_tool(
    name="get_github_file",
    description=(
        "Read the contents of a file from a GitHub repository. "
        "Use this to examine dbt models, SQL files, YAML configs, etc."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[
        ToolParameter(
            "repo", "string",
            "Repository in format 'owner/repo' (e.g., 'acme/dbt-models')",
        ),
        ToolParameter(
            "path", "string",
            "Path to the file (e.g., 'models/staging/stg_customers.sql')",
        ),
        ToolParameter(
            "branch", "string",
            "Branch to read from (default: main)",
            required=False,
            default="main",
        ),
    ],
    alternative_integrations={"GITHUB"},
)
def _meta_get_github_file():
    pass
