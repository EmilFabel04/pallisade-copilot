"""Pydantic payload models per ArtifactKind.

Mirrors types/artifact.ts on the frontend. Each artefact's `payload` JSON
must validate against the corresponding model in this file.
"""
from __future__ import annotations

from dataclasses import dataclass as _dataclass
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ArtifactKind(str, Enum):
    PR_CHANGE = "PR_CHANGE"
    WAREHOUSE_QUERY = "WAREHOUSE_QUERY"
    SCHEMA_CHANGE = "SCHEMA_CHANGE"
    DBT_CORE_CHANGE = "DBT_CORE_CHANGE"
    DBT_CLOUD_CHANGE = "DBT_CLOUD_CHANGE"
    DAG = "DAG"
    INGESTION_CONNECTOR = "INGESTION_CONNECTOR"
    MONITOR = "MONITOR"
    WATCH = "WATCH"
    INCIDENT = "INCIDENT"
    TICKET = "TICKET"
    NOTIFICATION_RULE = "NOTIFICATION_RULE"
    BI_ASSET = "BI_ASSET"
    STORAGE_OBJECT = "STORAGE_OBJECT"
    SERVER_ACTION = "SERVER_ACTION"
    DOCUMENT = "DOCUMENT"


class ArtifactStatus(str, Enum):
    draft = "draft"
    proposed = "proposed"
    approved = "approved"
    applied = "applied"
    rejected = "rejected"
    failed = "failed"
    archived = "archived"
    open = "open"
    resolved = "resolved"


class ArtifactRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@_dataclass
class ArtifactSpec:
    """Declares how a tool's successful execution becomes an Artifact row.

    Lives here (rather than in tools/base.py) so the emitter is the single
    source of truth and tools/base.py imports from here. `kind` is an
    ArtifactKind.value string.
    """
    kind: str
    status_on_propose: Optional[str] = None  # ArtifactStatus.value
    status_on_success: str = "applied"  # ArtifactStatus.value
    title_field: str = "title"
    summary_field: Optional[str] = "summary"


class PRChangePayload(BaseModel):
    kind: Literal["PR_CHANGE"] = "PR_CHANGE"
    changePlanId: str
    filesChanged: int
    diffSummary: str
    validationResults: Dict[str, str] = Field(default_factory=dict)


class WarehouseQueryPayload(BaseModel):
    kind: Literal["WAREHOUSE_QUERY"] = "WAREHOUSE_QUERY"
    sql: str
    rowCount: Optional[int] = None
    executionMs: Optional[int] = None
    resultPreview: Optional[List[Any]] = None
    error: Optional[str] = None


class SchemaChangePayload(BaseModel):
    kind: Literal["SCHEMA_CHANGE"] = "SCHEMA_CHANGE"
    ddl: str
    affectedTables: List[str]
    reversible: bool


class DbtCoreChangePayload(BaseModel):
    kind: Literal["DBT_CORE_CHANGE"] = "DBT_CORE_CHANGE"
    modelsTouched: List[str]
    testsAdded: List[str] = Field(default_factory=list)
    changePlanId: Optional[str] = None


class DbtCloudChangePayload(BaseModel):
    kind: Literal["DBT_CLOUD_CHANGE"] = "DBT_CLOUD_CHANGE"
    projectId: str
    jobId: Optional[str] = None
    environmentId: Optional[str] = None
    operation: Literal["job_edit", "env_update", "deploy", "run_trigger"]


class DagPayload(BaseModel):
    kind: Literal["DAG"] = "DAG"
    dagId: str
    operation: Literal["create", "edit", "pause", "resume", "trigger", "clear"]
    affectedTasks: List[str] = Field(default_factory=list)


class IngestionConnectorPayload(BaseModel):
    kind: Literal["INGESTION_CONNECTOR"] = "INGESTION_CONNECTOR"
    connectorId: str
    operation: Literal["create", "edit", "pause", "resume", "trigger_sync"]
    configDiff: Optional[Dict[str, Any]] = None


class MonitorPayload(BaseModel):
    kind: Literal["MONITOR"] = "MONITOR"
    monitorId: str
    monitorKind: str
    targetFqn: Optional[str] = None
    configDiff: Optional[Dict[str, Any]] = None


class WatchPayload(BaseModel):
    kind: Literal["WATCH"] = "WATCH"
    watchId: str
    configDiff: Optional[Dict[str, Any]] = None


class IncidentPayload(BaseModel):
    kind: Literal["INCIDENT"] = "INCIDENT"
    incidentId: str
    severity: str
    affectedAssets: List[str] = Field(default_factory=list)


class TicketPayload(BaseModel):
    kind: Literal["TICKET"] = "TICKET"
    ticketKey: str
    ticketUrl: str
    title: str


class NotificationRulePayload(BaseModel):
    kind: Literal["NOTIFICATION_RULE"] = "NOTIFICATION_RULE"
    ruleId: str
    channel: str
    trigger: str


class BIAssetPayload(BaseModel):
    kind: Literal["BI_ASSET"] = "BI_ASSET"
    assetId: str
    operation: Literal["create", "edit", "refresh"]
    assetType: Literal["dashboard", "model", "dataset"]


class StorageObjectPayload(BaseModel):
    kind: Literal["STORAGE_OBJECT"] = "STORAGE_OBJECT"
    bucket: str
    key: str
    operation: Literal["write", "delete", "copy"]


class ServerActionPayload(BaseModel):
    kind: Literal["SERVER_ACTION"] = "SERVER_ACTION"
    serverId: str
    action: str
    commandPreview: Optional[str] = None


class DocumentPayload(BaseModel):
    kind: Literal["DOCUMENT"] = "DOCUMENT"
    format: Literal["md", "html", "pdf"]
    body: str


ArtifactPayload = Union[
    PRChangePayload,
    WarehouseQueryPayload,
    SchemaChangePayload,
    DbtCoreChangePayload,
    DbtCloudChangePayload,
    DagPayload,
    IngestionConnectorPayload,
    MonitorPayload,
    WatchPayload,
    IncidentPayload,
    TicketPayload,
    NotificationRulePayload,
    BIAssetPayload,
    StorageObjectPayload,
    ServerActionPayload,
    DocumentPayload,
]
