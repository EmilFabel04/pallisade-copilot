"""Linear IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class LinearDriver(IntegrationDriver):
    def id(self) -> str: return "linear"
    def integration_type(self) -> str: return "LINEAR"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.TICKETING
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("api_key") and not config.get("apiKey"):
            errors.append("api_key is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            import httpx
            token = config.get("api_key") or config.get("apiKey", "")
            resp = httpx.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": token, "Content-Type": "application/json"},
                json={"query": "{ viewer { id name } }"},
                timeout=10,
            )
            if resp.status_code == 200 and resp.json().get("data", {}).get("viewer"):
                return ConnectionResult(ok=True, message="Connected to Linear")
            return ConnectionResult(ok=False, message=f"Linear returned HTTP {resp.status_code}")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Linear connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["issue.created", "issue.completed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
