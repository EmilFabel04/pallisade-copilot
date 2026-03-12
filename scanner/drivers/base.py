"""
IntegrationDriver — unified contract for all Pallisade tool integrations.

Every supported tool (warehouse, ingestion, transformation, BI, VCS, etc.)
implements this interface.  The central DriverRegistry maps integration_type
strings to concrete driver classes.

KEY RULE — DATA_PLANE vs CONTROL_PLANE:
  extract_lineage() is a *guarded* method.  It checks graph_domain() before
  delegating to _extract_lineage_impl().  CONTROL_PLANE drivers always return
  empty — the guard cannot be bypassed by subclasses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GraphDomain(Enum):
    """Where this integration lives in the lineage graph."""
    DATA_PLANE = "DATA_PLANE"
    CONTROL_PLANE = "CONTROL_PLANE"
    NONE = "NONE"


class IntegrationLayer(Enum):
    """Logical layer for UI grouping."""
    WAREHOUSE = "WAREHOUSE"
    INGESTION = "INGESTION"
    TRANSFORMATION = "TRANSFORMATION"
    ORCHESTRATION = "ORCHESTRATION"
    REPORTING = "REPORTING"
    OBSERVABILITY = "OBSERVABILITY"
    STORAGE = "STORAGE"
    VERSION_CONTROL = "VERSION_CONTROL"
    NOTIFICATIONS = "NOTIFICATIONS"
    TICKETING = "TICKETING"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------

@dataclass
class DriverCapabilities:
    """Feature flags declared by a driver."""
    can_query: bool = False
    can_extract_metadata: bool = False
    can_extract_lineage: bool = False
    can_fetch_logs: bool = False
    can_write: bool = False
    can_health_check: bool = False
    can_mcp: bool = False
    supported_monitors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "can_query": self.can_query,
            "can_extract_metadata": self.can_extract_metadata,
            "can_extract_lineage": self.can_extract_lineage,
            "can_fetch_logs": self.can_fetch_logs,
            "can_write": self.can_write,
            "can_health_check": self.can_health_check,
            "can_mcp": self.can_mcp,
            "supported_monitors": self.supported_monitors,
        }


@dataclass
class ConnectionResult:
    """Outcome of test_connection / health_check."""
    ok: bool
    message: str
    connected_at: Optional[datetime] = None
    latency_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "latency_ms": self.latency_ms,
        }


@dataclass
class ConfigValidation:
    """Outcome of validate_config."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


@dataclass
class AssetSummary:
    """High-level count of discovered assets."""
    asset_type: str
    count: int
    sample_names: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"asset_type": self.asset_type, "count": self.count, "sample_names": self.sample_names}


@dataclass
class LogEntry:
    """A single bounded log record."""
    timestamp: datetime
    level: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass
class ObservedCapability:
    """A capability actually observed in this tenant's platform usage.

    Part of the three-level capability model:
      - Supported capabilities: what the platform CAN do (PlatformInfo.capabilities)
      - Observed capabilities: what the platform IS doing (this struct)
      - Resolved roles: what each discovered node actually does (resolve_functional_role)

    Only capabilities with real evidence should be reported.  Do not echo
    back PlatformInfo.capabilities speculatively.
    """
    capability: str         # e.g. "warehouse", "orchestration", "transformation"
    source: str             # e.g. "api_probe", "asset_discovery", "config", "user_override"
    confidence: float = 1.0  # 0.0–1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
                            # e.g. {"api_endpoint": "/api/2.1/jobs/list", "asset_count": 42}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "source": self.source,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# IntegrationDriver ABC
# ---------------------------------------------------------------------------

class IntegrationDriver(ABC):
    """
    Unified contract every Pallisade integration must satisfy.

    Composes over existing adapters (DatabaseAdapter, BaseLineageAdapter,
    ObservabilityClient, etc.) — does NOT replace them.
    """

    # ── Identity (abstract) ────────────────────────────────────────────

    @abstractmethod
    def id(self) -> str:
        """Short lowercase identifier, e.g. 'bigquery'."""
        ...

    @abstractmethod
    def integration_type(self) -> str:
        """Matches the Prisma IntegrationType enum value, e.g. 'BIGQUERY'."""
        ...

    @abstractmethod
    def layer(self) -> IntegrationLayer:
        """Logical layer for UI grouping."""
        ...

    @abstractmethod
    def graph_domain(self) -> GraphDomain:
        """DATA_PLANE | CONTROL_PLANE | NONE."""
        ...

    # ── Lifecycle (abstract) ───────────────────────────────────────────

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        """Validate integration configuration (no network call)."""
        ...

    @abstractmethod
    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        """Test connectivity to the external service."""
        ...

    @abstractmethod
    def capabilities(self) -> DriverCapabilities:
        """Declare what this driver can do."""
        ...

    # ── Extraction (DATA_PLANE override _extract_lineage_impl) ─────────

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        """Discover assets and return high-level summaries."""
        return []

    def extract_lineage(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        """
        Return (nodes, edges) for the lineage graph.

        **GUARDED**: CONTROL_PLANE / NONE drivers always return ([], []).
        DATA_PLANE drivers should override ``_extract_lineage_impl``.
        """
        if self.graph_domain() != GraphDomain.DATA_PLANE:
            return [], []
        return self._extract_lineage_impl(config)

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        """Override in DATA_PLANE drivers to provide real lineage."""
        return [], []

    # ── Operational (sensible defaults) ────────────────────────────────

    def fetch_logs(
        self, config: Dict[str, Any], *, limit: int = 100
    ) -> List[LogEntry]:
        """Return bounded log entries from the integration."""
        return []

    def health_check(self, config: Dict[str, Any]) -> ConnectionResult:
        """Check service health.  Defaults to test_connection."""
        return self.test_connection(config)

    # ── Events & contracts ─────────────────────────────────────────────

    def events_emitted(self) -> List[str]:
        """Notification event types this integration can emit."""
        return []

    def contract_schema(self) -> Optional[Dict[str, Any]]:
        """Tool-specific contract override schema (JSON Schema)."""
        return None

    def ui_config_schema(self) -> Optional[Dict[str, Any]]:
        """Form rendering hints for the Integrations connect modal."""
        return None

    def recommended_monitors(self) -> List[str]:
        """Monitor types recommended for this integration."""
        return []

    # ── Multi-role observation ─────────────────────────────────────────

    def observed_capabilities(
        self, config: Dict[str, Any]
    ) -> List[ObservedCapability]:
        """Return capabilities actually observed in this tenant's usage.

        Called after ``test_connection`` succeeds.  Returns structured
        observations with source and confidence.  Only capabilities with
        real evidence should be returned — do NOT echo back
        PlatformInfo.capabilities speculatively.

        Default: returns the driver's primary layer as a high-confidence
        observation.  Override in multi-role drivers to probe the platform
        for active features.
        """
        return [ObservedCapability(
            capability=self.layer().value.lower(),
            source="driver_identity",
            confidence=1.0,
        )]

    # ── Serialisation helpers ──────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise driver metadata for API responses."""
        return {
            "id": self.id(),
            "integration_type": self.integration_type(),
            "layer": self.layer().value,
            "graph_domain": self.graph_domain().value,
            "capabilities": self.capabilities().to_dict(),
            "events_emitted": self.events_emitted(),
            "recommended_monitors": self.recommended_monitors(),
        }
