"""Metabase IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class MetabaseDriver(IntegrationDriver):
    def id(self) -> str: return "metabase"
    def integration_type(self) -> str: return "METABASE"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.REPORTING
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host") and not config.get("base_url"):
            errors.append("host or base_url is required")
        if not config.get("api_key"):
            errors.append("api_key is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            from scanner.integrations.metabase import MetabaseClient
            client = MetabaseClient(
                host=config.get("host", config.get("base_url", "")),
                api_key=config.get("api_key"),
            )
            ok, msg = client.test_connection()
            return ConnectionResult(ok=ok, message=msg)
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Metabase connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_health_check=True, supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
