"""Change plan (actions) tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="create_change_plan",
    description=(
        "Create a structured change plan with patches for fixing data pipeline issues. "
        "The plan includes file patches, rationale, impact analysis, and rollback steps. "
        "After creation, the plan can be validated and applied via GitHub PR."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[
        ToolParameter(
            "title", "string",
            "Short title for the fix (e.g., 'Fix null values in customer_id')",
        ),
        ToolParameter(
            "root_cause", "string",
            "Root cause analysis explaining why the issue occurred",
        ),
        ToolParameter(
            "patches", "array",
            "List of file patches to apply",
            items={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to modify"},
                    "patch_type": {"type": "string", "enum": ["sql_model", "yaml_config", "python_script", "orchestration", "text_file"], "description": "Type of file: sql_model (.sql), yaml_config (.yml/.yaml), python_script (.py), orchestration (Airflow DAG .py), text_file (.md, .txt, .gitignore, .cfg, requirements.txt, Dockerfile, etc.)"},
                    "new_content": {"type": "string", "description": "The new content for the file"},
                    "rationale": {"type": "string", "description": "Why this change fixes the issue"},
                    "original_content": {"type": "string", "description": "Original file content (optional)"},
                    "rollback_steps": {"type": "array", "items": {"type": "string"}, "description": "Steps to undo this change"},
                },
                "required": ["file_path", "patch_type", "new_content", "rationale"],
            },
        ),
        ToolParameter(
            "impact_analysis", "object",
            "Impact analysis: {affected_tables?, downstream_dependencies?, risk_level?, expected_data_changes?}",
            required=False,
        ),
        ToolParameter(
            "description", "string",
            "Detailed description of the fix",
            required=False,
        ),
    ],
)
def _meta_create_change_plan():
    pass


@register_tool(
    name="validate_change_plan",
    description=(
        "Run validation checks on a change plan. Validates syntax, compiles dbt models, "
        "and optionally runs sandbox tests. Call this after create_change_plan."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[
        ToolParameter(
            "plan_id", "string",
            "The ID of the change plan to validate",
        ),
        ToolParameter(
            "level", "string",
            "Validation level: 'static' (syntax/lint), 'ci' (compile/tests), 'sandbox' (shadow run)",
            enum=["static", "ci", "sandbox"],
        ),
    ],
)
def _meta_validate_change_plan():
    pass


@register_tool(
    name="get_change_plan",
    description=(
        "Retrieve a change plan by ID. Returns the plan with patches, validation status, and current state."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[
        ToolParameter(
            "plan_id", "string",
            "The ID of the change plan to retrieve",
        ),
    ],
)
def _meta_get_change_plan():
    pass


@register_tool(
    name="apply_change_plan",
    description=(
        "Apply a validated change plan by creating a GitHub Pull Request. "
        "The plan must have passed at least static validation. "
        "If repo_owner/repo_name are not provided, will auto-detect from connected GitHub integration. "
        "Returns the PR URL on success."
    ),
    category=ToolCategory.CHANGE_PLAN,
    requires_confirmation=True,
    alternative_integrations={"GITHUB"},
    parameters=[
        ToolParameter(
            "plan_id", "string",
            "The ID of the validated change plan to apply",
        ),
        ToolParameter(
            "repo_owner", "string",
            "GitHub repository owner (username or organization). Auto-detected if not provided.",
            required=False,
        ),
        ToolParameter(
            "repo_name", "string",
            "GitHub repository name. Auto-detected if not provided.",
            required=False,
        ),
        ToolParameter(
            "base_branch", "string",
            "Branch to base the PR on",
            required=False,
            default="main",
        ),
    ],
)
def _meta_apply_change_plan():
    pass


@register_tool(
    name="list_change_plans",
    description=(
        "List all change plans in the current session. "
        "Shows plan IDs, titles, status, and validation state."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[],
)
def _meta_list_change_plans():
    pass
