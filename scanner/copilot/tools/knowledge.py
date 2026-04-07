"""Knowledge base tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="search_knowledge_base",
    description=(
        "Search the Pallisade knowledge base for expert guidance on data pipeline tools, "
        "troubleshooting, best practices, and comparisons. Use this when the user asks "
        "about how tools work, how to debug or fix errors, best practices, tool differences, "
        "or migration advice. Returns curated articles with step-by-step guidance. "
        "Examples: 'how to fix a dbt test failure', 'snowflake vs bigquery', 'airflow DAG best practices'."
    ),
    category=ToolCategory.KNOWLEDGE,
    parameters=[
        ToolParameter(
            "query", "string",
            "Search query describing what the user wants to know about",
        ),
        ToolParameter(
            "category", "string",
            "Optional category filter to narrow results",
            required=False,
            enum=["troubleshooting", "best_practices", "comparison", "how_to", "architecture", "migration"],
        ),
        ToolParameter(
            "tool_filter", "string",
            "Optional comma-separated tool filter (e.g., 'dbt,snowflake')",
            required=False,
        ),
    ],
)
def _meta_search_knowledge_base():
    pass
