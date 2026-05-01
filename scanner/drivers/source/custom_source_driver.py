"""
Custom Source IntegrationDriver — registers an arbitrary HTTP-accessible
data source as a SOURCE-layer integration. Composes over HttpProbeAdapter.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..base import (
    AssetSummary,
    ConfigValidation,
    ConnectionResult,
    DriverCapabilities,
    GraphDomain,
    IntegrationDriver,
    IntegrationLayer,
)

logger = logging.getLogger(__name__)


class CustomSourceDriver(IntegrationDriver):
    def id(self) -> str:
        return "custom_source"

    def integration_type(self) -> str:
        return "CUSTOM_SOURCE"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.SOURCE

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []

        if not config.get("base_url"):
            errors.append("base_url is required")
        else:
            if not config["base_url"].lower().startswith("https://"):
                errors.append("base_url must use https:// scheme (TLS required)")

        auth = config.get("auth") or {}
        if not auth.get("kind"):
            errors.append("auth.kind is required (bearer | api_key | basic)")
        elif auth["kind"] not in ("bearer", "api_key", "basic"):
            errors.append(f"auth.kind must be one of bearer | api_key | basic, got {auth['kind']!r}")

        datasets = config.get("datasets") or []
        if not datasets:
            errors.append("datasets: at least one dataset is required")
        for i, ds in enumerate(datasets):
            if not ds.get("id"):
                errors.append(f"datasets[{i}].id is required")
            if not ds.get("endpoint"):
                errors.append(f"datasets[{i}].endpoint is required")
            if not ds.get("timestamp_column"):
                errors.append(f"datasets[{i}].timestamp_column is required")

        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        from scanner.adapters.http_probe import HttpProbeAdapter, ProbeError
        from datetime import datetime
        import time

        datasets = config.get("datasets") or []
        if not datasets:
            return ConnectionResult(ok=False, message="no datasets configured")

        adapter = HttpProbeAdapter(
            base_url=config["base_url"],
            auth=config["auth"],
        )

        first = datasets[0]
        start = time.time()
        try:
            adapter.probe({
                "endpoint": first["endpoint"],
                "timestamp_column": first.get("timestamp_column"),
                "json_root": first.get("json_root"),
            })
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=True,
                message=f"Connected; first dataset {first['id']!r} returned data",
                connected_at=datetime.utcnow(),
                latency_ms=latency,
            )
        except ProbeError as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"connection failed ({exc.code}): {exc.message}",
                latency_ms=latency,
            )

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        datasets = config.get("datasets") or []
        return [
            AssetSummary(
                asset_type="dataset",
                count=1,
                sample_names=[ds.get("id", "<unnamed>")],
            )
            for ds in datasets
        ]

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=False,
            can_extract_metadata=True,
            can_extract_lineage=True,
            can_health_check=True,
            supported_monitors=["freshness", "volume", "null_check", "schema_change"],
        )

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "null_check", "schema_change"]
