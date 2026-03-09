"""OpsGenie IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class OpsGenieDriver(IntegrationDriver):
    def id(self) -> str: return "opsgenie"
    def integration_type(self) -> str: return "OPSGENIE"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.NOTIFICATIONS
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("api_key") and not config.get("apiKey"):
            errors.append("api_key is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        key = config.get("api_key") or config.get("apiKey", "")
        if key:
            return ConnectionResult(ok=True, message="OpsGenie API key configured")
        return ConnectionResult(ok=False, message="No OpsGenie API key configured")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["alert.created", "alert.closed", "notification.failed"]

    def recommended_monitors(self) -> List[str]:
        return []
