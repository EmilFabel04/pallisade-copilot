"""
Central driver registry.

Maps integration_type strings → IntegrationDriver classes.
Provides helpers for filtering by graph domain, layer, and capabilities.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

from .base import GraphDomain, IntegrationDriver, IntegrationLayer

logger = logging.getLogger(__name__)


class DriverRegistry:
    """Singleton registry of all integration drivers."""

    _drivers: Dict[str, Type[IntegrationDriver]] = {}

    # ── Registration ───────────────────────────────────────────────────

    @classmethod
    def register(cls, integration_type: str, driver_cls: Type[IntegrationDriver]) -> None:
        """Register a driver class for the given integration type."""
        key = integration_type.upper()
        if key in cls._drivers:
            logger.warning("Overwriting driver for %s", key)
        cls._drivers[key] = driver_cls

    # ── Lookup ─────────────────────────────────────────────────────────

    @classmethod
    def get(cls, integration_type: str) -> Optional[Type[IntegrationDriver]]:
        """Return the driver class for *integration_type*, or None."""
        return cls._drivers.get(integration_type.upper())

    @classmethod
    def create(cls, integration_type: str, **kwargs: Any) -> IntegrationDriver:
        """Instantiate a driver.  Raises ValueError if unknown type."""
        driver_cls = cls.get(integration_type)
        if driver_cls is None:
            raise ValueError(
                f"Unknown integration type: {integration_type}. "
                f"Available: {sorted(cls._drivers.keys())}"
            )
        return driver_cls(**kwargs)

    # ── Queries ────────────────────────────────────────────────────────

    @classmethod
    def list_supported(cls) -> List[str]:
        """All registered integration type keys (uppercase)."""
        return sorted(cls._drivers.keys())

    @classmethod
    def list_data_plane(cls) -> List[str]:
        """Integration types whose graph_domain is DATA_PLANE."""
        return sorted(
            k for k, v in cls._drivers.items()
            if v().graph_domain() == GraphDomain.DATA_PLANE
        )

    @classmethod
    def list_control_plane(cls) -> List[str]:
        """Integration types whose graph_domain is CONTROL_PLANE."""
        return sorted(
            k for k, v in cls._drivers.items()
            if v().graph_domain() == GraphDomain.CONTROL_PLANE
        )

    @classmethod
    def for_layer(cls, layer: IntegrationLayer) -> List[str]:
        """Integration types in the given layer."""
        return sorted(
            k for k, v in cls._drivers.items()
            if v().layer() == layer
        )

    @classmethod
    def get_support_matrix(cls) -> List[Dict[str, Any]]:
        """Return a summary dict for every registered driver (for docs / API)."""
        rows: List[Dict[str, Any]] = []
        for key in sorted(cls._drivers.keys()):
            driver = cls._drivers[key]()
            caps = driver.capabilities()
            rows.append({
                "integration_type": key,
                "id": driver.id(),
                "layer": driver.layer().value,
                "graph_domain": driver.graph_domain().value,
                "can_query": caps.can_query,
                "can_extract_metadata": caps.can_extract_metadata,
                "can_extract_lineage": caps.can_extract_lineage,
                "can_fetch_logs": caps.can_fetch_logs,
                "can_write": caps.can_write,
                "can_health_check": caps.can_health_check,
                "supported_monitors": caps.supported_monitors,
                "events_emitted": driver.events_emitted(),
                "recommended_monitors": driver.recommended_monitors(),
            })
        return rows

    @classmethod
    def reset(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._drivers.clear()
