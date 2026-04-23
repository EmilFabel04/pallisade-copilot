"""Prefect IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class PrefectDriver(IntegrationDriver):
    def id(self) -> str: return "prefect"
    def integration_type(self) -> str: return "PREFECT"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.ORCHESTRATION
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("api_key") and not config.get("apiKey") and not config.get("base_url"):
            errors.append("api_key or base_url is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Prefect connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_fetch_logs=True, can_health_check=True,
            supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["flow.completed", "flow.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
