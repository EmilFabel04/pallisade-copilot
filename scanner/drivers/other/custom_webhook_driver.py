"""Custom Webhook IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class CustomWebhookDriver(IntegrationDriver):
    def id(self) -> str: return "custom_webhook"
    def integration_type(self) -> str: return "CUSTOM_WEBHOOK"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.OTHER
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("url") and not config.get("webhook_url"):
            errors.append("url or webhook_url is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        url = config.get("url") or config.get("webhook_url", "")
        if url:
            return ConnectionResult(ok=True, message="Webhook URL configured")
        return ConnectionResult(ok=False, message="No webhook URL configured")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["webhook.sent", "webhook.failed"]

    def recommended_monitors(self) -> List[str]:
        return []
