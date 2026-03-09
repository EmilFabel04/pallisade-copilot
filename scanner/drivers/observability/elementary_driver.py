"""Elementary IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class ElementaryDriver(IntegrationDriver):
    def id(self) -> str: return "elementary"
    def integration_type(self) -> str: return "ELEMENTARY"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.OBSERVABILITY
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        # Elementary is typically configured via dbt; minimal config needed
        return ConfigValidation(valid=True)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="Elementary connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_health_check=True,
            supported_monitors=["freshness", "volume", "schema_change"],
        )

    def events_emitted(self) -> List[str]:
        return ["test.passed", "test.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change"]
