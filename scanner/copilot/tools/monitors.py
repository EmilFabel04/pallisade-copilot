"""Monitor write tools.

Each tool emits a MONITOR artefact via the executor's auto-emit hook
(see _emit_for_tool in tool_executor.py). Tool handlers live in
tool_executor.py as _execute_create_monitor / _execute_update_monitor /
_execute_delete_monitor.
"""

from .registry import register_tool
from .base import ToolCategory, ToolParameter, RiskLevel
from ..artifacts.models import ArtifactSpec


_MONITOR_KINDS = [
    "FRESHNESS", "VOLUME", "ANOMALY", "SCHEMA", "CUSTOM_SQL",
    "NULL_CHECK", "UNIQUENESS_CHECK",
]


@register_tool(
    name="create_monitor",
    description=(
        "Create a single data-quality monitor on a target asset. "
        "Wraps the unified scheduling pipeline used for monitor groups. "
        "Returns the new monitor id; the artefact captures the config diff."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("target_fqn", "string",
                      "Fully-qualified name of the target asset (e.g. 'snowflake.analytics.orders')."),
        ToolParameter("monitor_kind", "string",
                      "Monitor kind.", enum=_MONITOR_KINDS),
        ToolParameter("config", "object",
                      "Monitor-kind-specific config (e.g. {'maxHours': 6} for FRESHNESS).",
                      required=False),
        ToolParameter("name", "string",
                      "Optional human-readable plan name.", required=False),
        ToolParameter("schedule", "string",
                      "Cron expression. Defaults to '0 * * * *'.", required=False),
    ],
    requires_confirmation=True,
    risk_level=RiskLevel.LOW,
    artifact_spec=ArtifactSpec(
        kind="MONITOR",
        status_on_propose="proposed",
        status_on_success="applied",
    ),
)
def _meta_create_monitor():
    pass


@register_tool(
    name="update_monitor",
    description=(
        "Update an existing monitor's config. Pass a full or partial config map; "
        "fields not provided are left unchanged. Captures before/after diff on the artefact."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("monitor_id", "string", "Monitor row id."),
        ToolParameter("config", "object",
                      "Partial or full config map to merge into the monitor."),
        ToolParameter("policy_overrides", "array",
                      "Optional list of policy-override keys.",
                      items={"type": "string"}, required=False),
    ],
    requires_confirmation=True,
    risk_level=RiskLevel.LOW,
    artifact_spec=ArtifactSpec(
        kind="MONITOR",
        status_on_propose="proposed",
        status_on_success="applied",
    ),
)
def _meta_update_monitor():
    pass


@register_tool(
    name="delete_monitor",
    description=(
        "Delete a monitor. Destructive — always requires confirmation. "
        "Captures the deleted monitor's kind+target on the artefact for audit."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("monitor_id", "string", "Monitor row id."),
    ],
    requires_confirmation=True,
    risk_level=RiskLevel.MEDIUM,
    artifact_spec=ArtifactSpec(
        kind="MONITOR",
        status_on_propose="proposed",
        status_on_success="applied",
    ),
)
def _meta_delete_monitor():
    pass
