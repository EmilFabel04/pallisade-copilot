"""
Pydantic v2 models for MAAS specialist JSON contracts and observability.

Specialists MUST return JSON matching these schemas.
Orchestrator uses MAASTrace for end-to-end request tracing.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WarehouseType(str, Enum):
    BIGQUERY = "bigquery"
    SNOWFLAKE = "snowflake"
    POSTGRES = "postgres"
    REDSHIFT = "redshift"
    DATABRICKS = "databricks"


# ---------------------------------------------------------------------------
# SQL Specialist
# ---------------------------------------------------------------------------

class SQLAssumption(BaseModel):
    """An assumption the SQL specialist made about the schema or data."""
    assumption: str
    confidence: float = Field(ge=0.0, le=1.0)


class SQLValidationStep(BaseModel):
    """A validation step the orchestrator should take."""
    description: str
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None


class SQLResponse(BaseModel):
    """Response from the SQL specialist."""
    sql: str = Field(description="The SQL query to execute")
    warehouse: WarehouseType = Field(description="Target warehouse")
    assumptions: List[SQLAssumption] = Field(default_factory=list)
    validation_plan: List[SQLValidationStep] = Field(default_factory=list)
    explanation: str = Field(default="", description="Brief explanation of the query logic")


# ---------------------------------------------------------------------------
# Logs Specialist
# ---------------------------------------------------------------------------

class ErrorSignature(BaseModel):
    """Extracted error signature from log analysis."""
    failure_layer: str = Field(
        description="One of: Connection/Auth, SQL Compilation, Runtime/Data, Orchestration"
    )
    error_message: str = Field(description="The key error message extracted")
    error_code: Optional[str] = None
    system: str = Field(description="e.g. 'airflow', 'dbt', 'bigquery', 'fivetran'")


class EvidenceRequest(BaseModel):
    """A tool call the orchestrator should make to gather more evidence."""
    tool_name: str
    tool_arguments: Dict[str, Any] = Field(default_factory=dict)
    reason: str


class LogsResponse(BaseModel):
    """Response from the Logs specialist."""
    error_signature: ErrorSignature
    owner: str = Field(description="The system that owns the root cause")
    owner_confidence: float = Field(ge=0.0, le=1.0)
    next_evidence: List[EvidenceRequest] = Field(
        default_factory=list,
        description="Additional tool calls needed. Max 3.",
    )
    summary: str = Field(description="One-paragraph analysis summary")


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

class SpecialistInvocation(BaseModel):
    """Record of a single specialist call."""
    specialist: str  # "sql", "logs"
    latency_ms: int
    success: bool
    retry_count: int = 0
    error: Optional[str] = None
    # Set when the verifier-failure retry escalated reasoning_effort one
    # tier above the original. Useful for trace inspection and for
    # measuring how often escalation happens in production.
    escalated_to: Optional[str] = None
    # True when the orchestrator ran two parallel SQL calls at different
    # temperatures and picked the higher-confidence result. Records which
    # branch (A=temp 0.0, B=temp 0.7) was selected.
    self_consistency_used: bool = False
    self_consistency_picked: Optional[str] = None  # "A" or "B"


class ToolCallRecord(BaseModel):
    """Record of a tool execution within a MAAS request."""
    tool_name: str
    args_hash: str
    latency_ms: int
    success: bool


class MAASTrace(BaseModel):
    """Full request trace for observability and debugging."""
    route: str  # e.g. "INFO/sql" or "DEBUG/logs"
    specialists: List[SpecialistInvocation] = Field(default_factory=list)
    verifier_results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    fallback_reason: Optional[str] = None
    skipped_specialists: List[str] = Field(default_factory=list)
    total_latency_ms: int = 0
    selected_warehouse: Optional[str] = None
    repair_attempted: bool = False
    budget_exhausted: bool = False
    # Per-specialist health summary, populated at end of run.
    # Keys: specialist name → {calls, retries, mean_latency_ms,
    # verification_pass_rate, mean_confidence, cache_hits}.
    health: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
