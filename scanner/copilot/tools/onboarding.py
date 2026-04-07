"""Onboarding tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="get_pending_questions",
    description="Get the next onboarding questions that haven't been answered yet. Returns questions sorted by priority.",
    category=ToolCategory.ONBOARDING,
    parameters=[
        ToolParameter(
            "integration_type",
            "string",
            "Optional filter to get questions for a specific integration type (e.g., 'DBT_CORE', 'BIGQUERY')",
            required=False,
        ),
        ToolParameter(
            "limit",
            "integer",
            "Maximum number of questions to return",
            required=False,
            default=3,
        ),
    ],
)
def _meta_get_pending_questions():
    pass


@register_tool(
    name="save_onboarding_context",
    description="Save the user's answer to an onboarding question. Extracts key facts and stores them for future use.",
    category=ToolCategory.ONBOARDING,
    parameters=[
        ToolParameter(
            "question_key",
            "string",
            "The unique key of the question being answered (e.g., 'dbt_deployment_method')",
        ),
        ToolParameter(
            "answer",
            "string",
            "The user's answer to the question",
        ),
        ToolParameter(
            "extracted_facts",
            "object",
            "Key-value pairs of facts extracted from the answer (e.g., {'deployment_method': 'github_actions', 'workflow_path': '.github/workflows/dbt.yml'})",
            required=False,
        ),
    ],
)
def _meta_save_onboarding_context():
    pass


@register_tool(
    name="complete_onboarding",
    description="Mark onboarding as complete for this pipeline or a specific integration.",
    category=ToolCategory.ONBOARDING,
    parameters=[
        ToolParameter(
            "integration_id",
            "string",
            "Optional: complete onboarding for a specific integration only",
            required=False,
        ),
        ToolParameter(
            "summary",
            "string",
            "Summary of what was learned during onboarding",
            required=False,
        ),
    ],
)
def _meta_complete_onboarding():
    pass
