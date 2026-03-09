"""GitHub Issues IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class GitHubIssuesDriver(IntegrationDriver):
    def id(self) -> str: return "github_issues"
    def integration_type(self) -> str: return "GITHUB_ISSUES"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.VERSION_CONTROL
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("token") and not config.get("access_token"):
            errors.append("token is required")
        if not config.get("repo") and not config.get("repository"):
            errors.append("repo is required (owner/repo format)")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            import httpx
            token = config.get("token") or config.get("access_token", "")
            repo = config.get("repo") or config.get("repository", "")
            resp = httpx.get(
                f"https://api.github.com/repos/{repo}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return ConnectionResult(ok=True, message=f"Connected to {repo}")
            return ConnectionResult(ok=False, message=f"GitHub returned HTTP {resp.status_code}")
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"GitHub Issues connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_write=True, can_health_check=True)

    def events_emitted(self) -> List[str]:
        return ["issue.created", "issue.closed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
