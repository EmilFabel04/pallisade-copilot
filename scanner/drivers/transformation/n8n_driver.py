"""n8n IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class N8nDriver(IntegrationDriver):
    def id(self) -> str: return "n8n"
    def integration_type(self) -> str: return "N8N"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.ORCHESTRATION
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host") and not config.get("base_url") and not config.get("baseUrl"):
            errors.append("host or base_url is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="n8n connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_health_check=True,
            supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["workflow.completed", "workflow.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
