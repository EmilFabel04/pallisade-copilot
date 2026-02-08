"""
Observability Integrations Package

Provides unified access to data observability tools for the copilot.
Supported tools:
- Monte Carlo (GraphQL API)
- Bigeye (REST API)
- Soda (REST API)
- Elementary (warehouse queries)
"""

from .models import (
    IncidentSeverity,
    IncidentStatus,
    CheckType,
    AffectedAsset,
    DataIncident,
    DataQualityCheck,
    DataQualityMetrics,
    ObservabilityContext,
)

from .base import ObservabilityClient

from .factory import (
    create_observability_client,
    is_observability_type,
    OBSERVABILITY_TYPES,
)

__all__ = [
    # Models
    "IncidentSeverity",
    "IncidentStatus",
    "CheckType",
    "AffectedAsset",
    "DataIncident",
    "DataQualityCheck",
    "DataQualityMetrics",
    "ObservabilityContext",
    # Base
    "ObservabilityClient",
    # Factory
    "create_observability_client",
    "is_observability_type",
    "OBSERVABILITY_TYPES",
]
