"""Tableau IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class TableauDriver(IntegrationDriver):
    def id(self) -> str: return "tableau"
    def integration_type(self) -> str: return "TABLEAU"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.REPORTING
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("server") and not config.get("base_url"):
            errors.append("server is required")
        if not config.get("token_name") and not config.get("tokenName"):
            errors.append("token_name is required")
        if not config.get("token_value") and not config.get("tokenValue"):
            errors.append("token_value is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Tableau connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_health_check=True, supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
