"""
Pallisade Integration Drivers — unified contract for all tool integrations.

Usage::

    from scanner.drivers import DriverRegistry, IntegrationDriver, GraphDomain

    driver_cls = DriverRegistry.get("BIGQUERY")
    driver = driver_cls()
    result = driver.test_connection(config)
"""

from .base import (
    AssetSummary,
    ConfigValidation,
    ConnectionResult,
    DriverCapabilities,
    GraphDomain,
    IntegrationDriver,
    IntegrationLayer,
    LogEntry,
)
from .registry import DriverRegistry

__all__ = [
    "AssetSummary",
    "ConfigValidation",
    "ConnectionResult",
    "DriverCapabilities",
    "DriverRegistry",
    "GraphDomain",
    "IntegrationDriver",
    "IntegrationLayer",
    "LogEntry",
]
