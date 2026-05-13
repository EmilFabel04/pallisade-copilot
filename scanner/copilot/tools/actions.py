"""Change plan (actions) tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter, RiskLevel
from ..artifacts.models import ArtifactSpec


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
    risk_level=RiskLevel.MEDIUM,
    artifact_spec=ArtifactSpec(
        kind="PR_CHANGE",
        status_on_success="proposed",  # creation step proposes; apply step applies
    ),
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
    risk_level=RiskLevel.LOW,
    artifact_spec=ArtifactSpec(
        kind="PR_CHANGE",
        status_on_success="proposed",
    ),
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
    risk_level=RiskLevel.HIGH,
    artifact_spec=ArtifactSpec(
        kind="PR_CHANGE",
        status_on_propose="approved",
        status_on_success="applied",
    ),
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


@register_tool(
    name="begin_artefact",
    description=(
        "Begin a new typed artefact (PR_CHANGE, MONITOR, DAG, etc.). Forks a child agent "
        "session that owns the artefact's lifecycle and pre-creates the artefact row at "
        "status='draft'. Call this BEFORE any write tool that produces the named artefact "
        "kind. Returns artefact_id and agent_session_id; pass these to subsequent tool calls."
    ),
    category=ToolCategory.CHANGE_PLAN,
    parameters=[
        ToolParameter(
            "kind", "string",
            "Artefact kind to create",
            enum=[
                "PR_CHANGE", "WAREHOUSE_QUERY", "SCHEMA_CHANGE",
                "DBT_CORE_CHANGE", "DBT_CLOUD_CHANGE", "DAG",
                "INGESTION_CONNECTOR", "MONITOR", "WATCH", "INCIDENT",
                "TICKET", "NOTIFICATION_RULE", "BI_ASSET",
                "STORAGE_OBJECT", "SERVER_ACTION", "DOCUMENT",
            ],
        ),
        ToolParameter(
            "intent", "string",
            "One-sentence description of what the agent intends to build (e.g. 'Add freshness monitor on analytics.orders').",
        ),
        ToolParameter(
            "subtype", "string",
            "Optional integration-specific subtype (e.g. 'snowflake', 'airflow', 'fivetran'). Required for kinds with multiple subtypes.",
            required=False,
        ),
    ],
)
def _meta_begin_artefact():
    pass
