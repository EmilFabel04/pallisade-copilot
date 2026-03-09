"""SQL Server IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class SqlServerDriver(IntegrationDriver):
    def id(self) -> str: return "sqlserver"
    def integration_type(self) -> str: return "SQLSERVER"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.WAREHOUSE
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host") and not config.get("server"): errors.append("host is required")
        if not config.get("database"): errors.append("database is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            from scanner.adapters.factory import AdapterFactory
            adapter = AdapterFactory.get_adapter("sqlserver", config, auto_connect=True)
            try:
                ok, msg = adapter.test_connection()
                return ConnectionResult(ok=ok, message=msg or "Connected to SQL Server")
            finally:
                adapter.disconnect()
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"SQL Server connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=True, can_extract_metadata=True, can_health_check=True,
            supported_monitors=["freshness", "volume", "schema_change"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change"]
