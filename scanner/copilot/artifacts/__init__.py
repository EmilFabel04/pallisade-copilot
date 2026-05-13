"""Artefacts package — typed agent deliverables.

Re-exports the legacy ToolArtifactResult/WRITE_TOOLS for back-compat with
the existing executor + LLM streaming code (see scanner/copilot/llm.py).
New code should use `ArtifactSpec`, `emit_artifact`, and the Pydantic
payload models from this package.
"""
from .legacy import ToolArtifactResult, WRITE_TOOLS, generate_artifact_id
from .models import (
    ArtifactKind,
    ArtifactStatus,
    ArtifactRisk,
    ArtifactSpec,
    ArtifactPayload,
    PRChangePayload,
    MonitorPayload,
    SchemaChangePayload,
    DbtCoreChangePayload,
    DbtCloudChangePayload,
    DagPayload,
    IngestionConnectorPayload,
    WatchPayload,
    IncidentPayload,
    TicketPayload,
    NotificationRulePayload,
    BIAssetPayload,
    StorageObjectPayload,
    ServerActionPayload,
    DocumentPayload,
    WarehouseQueryPayload,
)

__all__ = [
    "ToolArtifactResult",
    "WRITE_TOOLS",
    "generate_artifact_id",
    "ArtifactKind",
    "ArtifactStatus",
    "ArtifactRisk",
    "ArtifactSpec",
    "ArtifactPayload",
    "PRChangePayload",
    "MonitorPayload",
    "SchemaChangePayload",
    "DbtCoreChangePayload",
    "DbtCloudChangePayload",
    "DagPayload",
    "IngestionConnectorPayload",
    "WatchPayload",
    "IncidentPayload",
    "TicketPayload",
    "NotificationRulePayload",
    "BIAssetPayload",
    "StorageObjectPayload",
    "ServerActionPayload",
    "DocumentPayload",
    "WarehouseQueryPayload",
]
