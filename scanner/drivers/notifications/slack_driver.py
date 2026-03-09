"""Slack IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class SlackDriver(IntegrationDriver):
    def id(self) -> str: return "slack"
    def integration_type(self) -> str: return "SLACK"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.NOTIFICATIONS
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("bot_token") and not config.get("botToken") and not config.get("webhook_url"):
            errors.append("bot_token or webhook_url is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            import httpx
            token = config.get("bot_token") or config.get("botToken", "")
            if token:
                resp = httpx.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    return ConnectionResult(ok=True, message="Connected to Slack")
                return ConnectionResult(ok=False, message=f"Slack auth failed: {resp.json().get('error', 'unknown')}")
            webhook = config.get("webhook_url", "")
            if webhook:
                return ConnectionResult(ok=True, message="Slack webhook URL configured")
            return ConnectionResult(ok=False, message="No token or webhook configured")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Slack connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["notification.sent", "notification.failed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
