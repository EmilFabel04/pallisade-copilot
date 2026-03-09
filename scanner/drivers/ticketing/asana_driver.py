"""Asana IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class AsanaDriver(IntegrationDriver):
    def id(self) -> str: return "asana"
    def integration_type(self) -> str: return "ASANA"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.TICKETING
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("token") and not config.get("access_token"):
            errors.append("token is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            import httpx
            token = config.get("token") or config.get("access_token", "")
            resp = httpx.get(
                "https://app.asana.com/api/1.0/users/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return ConnectionResult(ok=True, message="Connected to Asana")
            return ConnectionResult(ok=False, message=f"Asana returned HTTP {resp.status_code}")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Asana connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["task.created", "task.completed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
