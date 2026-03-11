"""
Universal Monitor Framework.

Tech-agnostic monitors for freshness, volume, schema changes,
statistical anomaly detection, and referential integrity. Each monitor
generates SQL that can be executed against any supported warehouse adapter.

The StatEngine provides shared statistical primitives (z-score, MAD,
confidence scoring, adaptive thresholds) used across all monitors.
"""

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .freshness import FreshnessMonitor
from .volume import VolumeMonitor
from .schema import SchemaMonitor
from .anomaly import AnomalyMonitor
from .referential import ReferentialIntegrityMonitor
from .executor import MonitorExecutor
from .explainer import enrich_result

__all__ = [
    "AnomalyMonitor",
    "BaseMonitor",
    "FreshnessMonitor",
    "MonitorExecutor",
    "MonitorResult",
    "MonitorStatus",
    "ReferentialIntegrityMonitor",
    "SchemaMonitor",
    "VolumeMonitor",
    "enrich_result",
]
