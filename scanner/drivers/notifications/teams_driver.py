"""Microsoft Teams IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class TeamsDriver(IntegrationDriver):
    def id(self) -> str: return "teams"
    def integration_type(self) -> str: return "TEAMS"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.NOTIFICATIONS
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("webhook_url") and not config.get("webhookUrl"):
            errors.append("webhook_url is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        url = config.get("webhook_url") or config.get("webhookUrl", "")
        if url:
            return ConnectionResult(ok=True, message="Teams webhook URL configured")
        return ConnectionResult(ok=False, message="No webhook URL configured")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["notification.sent", "notification.failed"]

    def recommended_monitors(self) -> List[str]:
        return []
