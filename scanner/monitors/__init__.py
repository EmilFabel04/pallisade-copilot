"""
Universal Monitor Framework.

Tech-agnostic monitors for freshness, volume, schema changes,
and statistical anomaly detection. Each monitor generates SQL
that can be executed against any supported warehouse adapter.
"""

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .freshness import FreshnessMonitor
from .volume import VolumeMonitor
from .schema import SchemaMonitor
from .anomaly import AnomalyMonitor
from .executor import MonitorExecutor

__all__ = [
    "AnomalyMonitor",
    "BaseMonitor",
    "FreshnessMonitor",
    "MonitorExecutor",
    "MonitorResult",
    "MonitorStatus",
    "SchemaMonitor",
    "VolumeMonitor",
]
