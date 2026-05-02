"""Clarification tool definitions.

Exposes `record_clarification_answer` so the LLM (in CLARIFY mode) can
persist a structured answer to a ContextRequest. The executor validates
the answer against the kind's schema, hands persistence off to the
Next.js API layer, and emits the `context_resolved` bus event so
downstream guessers (sla_discovery, monitor evaluation) can react.
"""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="record_clarification_answer",
    description=(
        "Record a structured answer to a clarification ContextRequest. "
        "Validates against the kind's answer_schema and writes a "
        "ContextResolution + (optionally) updates conventions."
    ),
    category=ToolCategory.ONBOARDING,
    parameters=[
        ToolParameter(
            "request_id",
            "string",
            "ID of the ContextRequest being answered (loaded into the system "
            "prompt as `__request_id` on the clarification payload).",
            required=True,
        ),
        ToolParameter(
            "structured_answer",
            "object",
            "Answer object matching the kind's answer schema "
            "(e.g. for timestamp_choice: {'column': 'created_at'}).",
            required=True,
        ),
        ToolParameter(
            "propose_convention",
            "boolean",
            "True only when the answer cleanly generalises (e.g. a naming "
            "pattern that applies to many tables). Default false.",
            required=False,
            default=False,
        ),
    ],
)
def _meta_record_clarification_answer():
    pass
