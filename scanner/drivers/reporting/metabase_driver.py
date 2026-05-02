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
        # On failure, classify the error and record a structured
        # snapshot in the default HealthStore so the copilot can
        # answer "why is Metabase down?" with a real reason
        # (BILLING / AUTH / NETWORK / etc.) instead of a raw
        # exception string. The snapshot survives between requests
        # so the LLM doesn't re-probe a degraded endpoint.
        from datetime import datetime, timezone
        from scanner.integrations.health import (
            IntegrationHealth,
            build_failure_snapshot,
            get_default_store,
        )

        try:
            from scanner.integrations.metabase import MetabaseClient
            client = MetabaseClient(
                host=config.get("host", config.get("base_url", "")),
                api_key=config.get("api_key"),
            )
            ok, msg = client.test_connection()
            if ok:
                get_default_store().record(IntegrationHealth(
                    integration_type="METABASE",
                    status="OK",
                    reason=msg,
                    observed_at=datetime.now(timezone.utc),
                ))
                return ConnectionResult(ok=True, message=msg)
            snap = build_failure_snapshot(
                integration_type="METABASE",
                message=msg,
            )
            get_default_store().record(snap)
            return ConnectionResult(ok=False, message=snap.reason)
        except Exception as exc:
            # Pull structured signal off the exception when present.
            # httpx HTTPStatusError carries .response with status_code
            # + body; bare exceptions only have a string.
            status_code = None
            response_body = None
            response = getattr(exc, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", None)
                try:
                    response_body = response.text[:2000]
                except Exception:
                    response_body = None
            snap = build_failure_snapshot(
                integration_type="METABASE",
                status_code=status_code,
                message=f"Metabase connection failed: {exc}",
                response_body=response_body,
            )
            get_default_store().record(snap)
            return ConnectionResult(ok=False, message=snap.reason)

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_health_check=True, supported_monitors=["freshness"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
