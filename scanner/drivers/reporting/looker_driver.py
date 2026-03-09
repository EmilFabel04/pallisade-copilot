"""Looker IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class LookerDriver(IntegrationDriver):
    def id(self) -> str: return "looker"
    def integration_type(self) -> str: return "LOOKER"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.REPORTING
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("base_url") and not config.get("baseUrl"):
            errors.append("base_url is required")
        if not config.get("client_id") and not config.get("clientId"):
            errors.append("client_id is required")
        if not config.get("client_secret") and not config.get("clientSecret"):
            errors.append("client_secret is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Looker connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_health_check=True, supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
