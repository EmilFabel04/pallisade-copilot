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
from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.ids import generate_asset_id, generate_edge_id

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

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        """Emit one source-layer node per dataset, plus a WRITES_TO edge to
        the warehouse target when ``lands_in`` is set on the dataset."""
        platform_label = (config.get("platform_label") or "custom_source").lower()
        datasets = config.get("datasets") or []

        nodes: List[LineageNode] = []
        edges: List[LineageEdge] = []

        for ds in datasets:
            ds_id = ds.get("id", "")
            asset_id = generate_asset_id(
                "source", platform_label, "", "", ds_id,
            )
            node = LineageNode(
                id=asset_id,
                name=ds_id,
                fqn=f"{platform_label}.{ds_id}",
                node_type=NodeType.SOURCE,
                platform=platform_label,
                platform_domain=PlatformDomain.OTHER,
                asset_kind=AssetKind.DATASET,
            )
            nodes.append(node)

            lands_in = ds.get("lands_in")
            if lands_in:
                # Parse "platform.container.name" into parts so we can compute
                # a target asset_id that matches what the warehouse-side adapter
                # will produce. Anything beyond [platform, ..., name] becomes
                # the container; the resolver later merges by stable identity.
                parts = lands_in.split(".")
                if len(parts) >= 2:
                    target_platform = parts[0].lower()
                    target_name = parts[-1].lower()
                    target_container = ".".join(p.lower() for p in parts[1:-1])
                else:
                    target_platform = "warehouse"
                    target_name = lands_in.lower()
                    target_container = ""

                target_id = generate_asset_id(
                    "warehouse", target_platform, "",
                    target_container, target_name,
                )

                evidence = Evidence(
                    adapter_id=self.id(),
                    source_ref="user_config",
                    payload={"lands_in": lands_in},
                )
                edge_id = generate_edge_id(
                    asset_id, target_id,
                    EdgeType.WRITES_TO.value,
                    "table",
                    "user_config",
                )
                edge = LineageEdge(
                    id=edge_id,
                    source_id=asset_id,
                    target_id=target_id,
                    edge_type=EdgeType.WRITES_TO,
                    confidence=0.9,
                    discovered_from="user_config",
                    evidence=[evidence],
                )
                edges.append(edge)

        return nodes, edges

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
