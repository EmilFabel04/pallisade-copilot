"""GitLab IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class GitLabDriver(IntegrationDriver):
    def id(self) -> str: return "gitlab"
    def integration_type(self) -> str: return "GITLAB"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.VERSION_CONTROL
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
            base = config.get("base_url", "https://gitlab.com")
            resp = httpx.get(
                f"{base}/api/v4/user",
                headers={"PRIVATE-TOKEN": token},
                timeout=10,
            )
            if resp.status_code == 200:
                return ConnectionResult(ok=True, message="Connected to GitLab")
            return ConnectionResult(ok=False, message=f"GitLab returned HTTP {resp.status_code}")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"GitLab connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True, can_fetch_logs=True)

    def events_emitted(self) -> List[str]:
        return ["mr.created", "mr.merged", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
