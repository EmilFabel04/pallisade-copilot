"""MySQL IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class MySqlDriver(IntegrationDriver):
    def id(self) -> str: return "mysql"
    def integration_type(self) -> str: return "MYSQL"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.WAREHOUSE
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host"): errors.append("host is required")
        if not config.get("database"): errors.append("database is required")
        if not config.get("user") and not config.get("username"): errors.append("user is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        # TODO: implement MySQL adapter
        return ConnectionResult(ok=False, message="MySQL adapter not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=True, can_extract_metadata=True, can_health_check=True,
            supported_monitors=["freshness", "volume", "schema_change"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change"]
