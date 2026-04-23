"""Databricks IntegrationDriver — warehouse + orchestration (multi-role)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer, ObservedCapability,
)

logger = logging.getLogger(__name__)


class DatabricksDriver(IntegrationDriver):
    def id(self) -> str: return "databricks"
    def integration_type(self) -> str: return "DATABRICKS"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.WAREHOUSE
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("host") and not config.get("server_hostname"): errors.append("host is required")
        if not config.get("token") and not config.get("access_token"): errors.append("token is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        try:
            from scanner.adapters.factory import AdapterFactory
            adapter = AdapterFactory.get_adapter("databricks", config, auto_connect=True)
            try:
                ok, msg = adapter.test_connection()
                return ConnectionResult(ok=ok, message=msg or "Connected to Databricks")
            finally:
                adapter.disconnect()
        except Exception as exc:
            return ConnectionResult(ok=False, message=f"Databricks connection failed: {exc}")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=True, can_extract_metadata=True, can_extract_lineage=True,
            can_health_check=True,
            supported_monitors=["freshness", "volume", "schema_change"],
        )

    def events_emitted(self) -> List[str]:
        return ["extraction.completed", "extraction.failed", "health.connected", "health.disconnected"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change"]

    def observed_capabilities(self, config: Dict[str, Any]) -> List[ObservedCapability]:
        """Probe Databricks workspace for active capabilities.

        Always reports warehouse (driver identity). Probes the Jobs API
        with limit=1 to check for orchestration capability — only reports
        it when the API responds successfully with job data.
        """
        caps = [ObservedCapability(
            capability="warehouse",
            source="driver_identity",
            confidence=1.0,
        )]

        host = config.get("host") or config.get("server_hostname", "")
        token = config.get("token") or config.get("access_token", "")
        if not host or not token:
            return caps

        try:
            import httpx
        except ImportError:
            return caps

        if not host.startswith("http"):
            host = f"https://{host}"
        host = host.rstrip("/")

        try:
            resp = httpx.get(
                f"{host}/api/2.1/jobs/list",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 1},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                job_count = len(data.get("jobs", []))
                has_more = data.get("has_more", False)
                caps.append(ObservedCapability(
                    capability="orchestration",
                    source="api_probe",
                    confidence=0.9,
                    metadata={
                        "api_endpoint": "/api/2.1/jobs/list",
                        "sample_count": job_count,
                        "has_more": has_more,
                    },
                ))
        except Exception:
            pass  # Jobs API not available — don't claim orchestration

        return caps
