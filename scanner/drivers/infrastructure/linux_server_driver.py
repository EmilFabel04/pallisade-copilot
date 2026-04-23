"""Linux Server IntegrationDriver — scaffold (CONTROL_PLANE)."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class LinuxServerDriver(IntegrationDriver):
    def id(self) -> str: return "linux_server"
    def integration_type(self) -> str: return "LINUX_SERVER"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.INFRASTRUCTURE
    def graph_domain(self) -> GraphDomain: return GraphDomain.CONTROL_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host"): errors.append("host is required")
        if not config.get("username") and not config.get("user"): errors.append("username is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Linux server connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(can_health_check=True, can_fetch_logs=True)

    def events_emitted(self) -> List[str]:
        return ["server.healthy", "server.unhealthy", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return []
