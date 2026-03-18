"""Artifact types for agentic copilot write actions."""
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Tools that require user confirmation before execution (server-side guard).
# run_watch is excluded — it's tier "none" (read-only execution).
WRITE_TOOLS = frozenset({
    "create_watch",
    "update_watch",
    "delete_watch",
    "create_monitoring_plan",
    "update_node_metadata",
    "assign_policy",
    "configure_alerts",
})


def generate_artifact_id() -> str:
    """Generate a unique artifact ID."""
    return f"art_{uuid.uuid4().hex[:12]}"


@dataclass
class ToolArtifactResult:
    """Result from a write tool that needs user confirmation before execution.

    Instead of executing immediately, this result is converted to a ui_artifact
    SSE event. The LLM receives a synthetic tool result string and the frontend
    renders an interactive card.
    """
    artifact_type: str
    action: str  # "create", "update", "delete"
    data: dict
    editable_fields: list
    confirmation_tier: str  # "none", "inline", "modal"
    artifact_id: str = field(default_factory=generate_artifact_id)
    tool_name: str = ""  # The tool that generated this artifact (for confirmation routing)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the ui_artifact SSE event payload."""
        return {
            "artifact_id": self.artifact_id,
            "type": self.artifact_type,
            "action": self.action,
            "status": "proposed",
            "data": self.data,
            "confirmation_tier": self.confirmation_tier,
            "editable_fields": self.editable_fields,
            "tool_name": self.tool_name,
        }

    def to_synthetic_tool_result(self) -> str:
        """Generate the synthetic result string fed back to the LLM.

        This tells the LLM that an artifact was emitted and it should wait
        for user confirmation before proceeding with write actions.
        """
        return (
            f"[Artifact emitted: {self.artifact_type} for {self.action}. "
            f"Awaiting user confirmation. Do not proceed with write actions "
            f"until you receive __action:confirm.]"
        )
