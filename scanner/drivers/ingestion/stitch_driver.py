"""Stitch IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class StitchDriver(IntegrationDriver):
    def id(self) -> str: return "stitch"
    def integration_type(self) -> str: return "STITCH"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.INGESTION
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("api_key") and not config.get("apiKey"):
            errors.append("api_key is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        from scanner.integrations.stitch import StitchClient
        try:
            with StitchClient(api_key=config.get("api_key") or config.get("apiKey", "")) as client:
                ok, message = client.test_connection()
            return ConnectionResult(ok=ok, message=message)
        except Exception as e:
            return ConnectionResult(ok=False, message=f"Stitch test failed: {e}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_health_check=True,
            supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["sync.completed", "sync.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
