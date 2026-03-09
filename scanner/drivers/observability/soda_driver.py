"""Soda IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class SodaDriver(IntegrationDriver):
    def id(self) -> str: return "soda"
    def integration_type(self) -> str: return "SODA"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.OBSERVABILITY
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("api_key") and not config.get("apiKey"):
            errors.append("api_key is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Soda connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_health_check=True,
            supported_monitors=["freshness", "volume"],
        )

    def events_emitted(self) -> List[str]:
        return ["check.passed", "check.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume"]
