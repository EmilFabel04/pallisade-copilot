"""Bitbucket IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class BitbucketDriver(IntegrationDriver):
    def id(self) -> str: return "bitbucket"
    def integration_type(self) -> str: return "BITBUCKET"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.VERSION_CONTROL
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("username"): errors.append("username is required")
        if not config.get("app_password") and not config.get("appPassword"):
            errors.append("app_password is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            import httpx
            username = config.get("username", "")
            password = config.get("app_password") or config.get("appPassword", "")
            resp = httpx.get(
                "https://api.bitbucket.org/2.0/user",
                auth=(username, password),
                timeout=10,
            )
            if resp.status_code == 200:
                return ConnectionResult(ok=True, message="Connected to Bitbucket")
            return ConnectionResult(ok=False, message=f"Bitbucket returned HTTP {resp.status_code}")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Bitbucket connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["pr.created", "pr.merged", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
