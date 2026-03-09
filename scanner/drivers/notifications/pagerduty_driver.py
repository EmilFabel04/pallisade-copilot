"""PagerDuty IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class PagerDutyDriver(IntegrationDriver):
    def id(self) -> str: return "pagerduty"
    def integration_type(self) -> str: return "PAGERDUTY"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.NOTIFICATIONS
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("routing_key") and not config.get("routingKey") and not config.get("api_key"):
            errors.append("routing_key or api_key is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        key = config.get("routing_key") or config.get("routingKey") or config.get("api_key", "")
        if key:
            return ConnectionResult(ok=True, message="PagerDuty key configured")
        return ConnectionResult(ok=False, message="No PagerDuty key configured")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["alert.triggered", "alert.resolved", "notification.failed"]

    def recommended_monitors(self) -> List[str]:
        return []
