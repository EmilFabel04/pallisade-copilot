"""Airbyte IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class AirbyteDriver(IntegrationDriver):
    def id(self) -> str: return "airbyte"
    def integration_type(self) -> str: return "AIRBYTE"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.INGESTION
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host") and not config.get("base_url") and not config.get("baseUrl"):
            errors.append("host or base_url is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        # TODO: implement Airbyte API health check
        return ConnectionResult(ok=False, message="Airbyte connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_fetch_logs=True, can_health_check=True,
            supported_monitors=["freshness", "volume"],
        )

    def events_emitted(self) -> List[str]:
        return ["sync.completed", "sync.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume"]
