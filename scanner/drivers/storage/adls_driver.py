"""Azure Data Lake Storage IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class AdlsDriver(IntegrationDriver):
    def id(self) -> str: return "adls"
    def integration_type(self) -> str: return "ADLS"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.STORAGE
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("account_name") and not config.get("accountName"):
            errors.append("account_name is required")
        if not config.get("container"): errors.append("container is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(ok=False, message="ADLS connection test not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_health_check=True,
            supported_monitors=["volume"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["volume"]
