"""Jira IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class JiraDriver(IntegrationDriver):
    def id(self) -> str: return "jira"
    def integration_type(self) -> str: return "JIRA"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.TICKETING
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("base_url") and not config.get("baseUrl") and not config.get("host"):
            errors.append("base_url is required")
        if not config.get("email"): errors.append("email is required")
        if not config.get("api_token") and not config.get("apiToken"):
            errors.append("api_token is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            import httpx
            base = (config.get("base_url") or config.get("baseUrl") or config.get("host", "")).rstrip("/")
            email = config.get("email", "")
            token = config.get("api_token") or config.get("apiToken", "")
            resp = httpx.get(
                f"{base}/rest/api/3/myself",
                auth=(email, token),
                timeout=10,
            )
            if resp.status_code == 200:
                return ConnectionResult(ok=True, message="Connected to Jira")
            return ConnectionResult(ok=False, message=f"Jira returned HTTP {resp.status_code}")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Jira connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["ticket.created", "ticket.updated", "ticket.resolved", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
