"""Monte Carlo IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class MonteCarloDriver(IntegrationDriver):
    def id(self) -> str: return "monte_carlo"
    def integration_type(self) -> str: return "MONTE_CARLO"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.OBSERVABILITY
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("api_key_id") and not config.get("apiKeyId"):
            errors.append("api_key_id is required")
        if not config.get("api_key_token") and not config.get("apiKeyToken"):
            errors.append("api_key_token is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Monte Carlo connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_fetch_logs=True,
            can_health_check=True, supported_monitors=["freshness", "volume", "schema_change"],
        )

    def events_emitted(self) -> List[str]:
        return ["incident.created", "incident.resolved", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change"]
