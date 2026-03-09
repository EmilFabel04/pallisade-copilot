"""
dbt Cloud IntegrationDriver — FULL implementation.

Composes:
  - scanner.integrations.dbt  (manifest parsing, models, sources)
  - scanner.lineage.engine.adapters.live_dbt.LiveDbtAdapter  (lineage)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from ..base import (
    AssetSummary,
    ConfigValidation,
    ConnectionResult,
    DriverCapabilities,
    GraphDomain,
    IntegrationDriver,
    IntegrationLayer,
    LogEntry,
)

logger = logging.getLogger(__name__)


class DbtCloudDriver(IntegrationDriver):
    """Full-wired dbt Cloud driver (DATA_PLANE)."""

    def id(self) -> str:
        return "dbt_cloud"

    def integration_type(self) -> str:
        return "DBT_CLOUD"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.TRANSFORMATION

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    # ── Lifecycle ──────────────────────────────────────────────────────

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []
        warnings: List[str] = []

        if not config.get("api_token") and not config.get("apiToken"):
            errors.append("api_token is required")
        if not config.get("account_id") and not config.get("accountId"):
            errors.append("account_id is required")
        if not config.get("project_id") and not config.get("projectId"):
            warnings.append("No project_id — will attempt to discover projects")

        return ConfigValidation(valid=not errors, errors=errors, warnings=warnings)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        start = time.time()
        try:
            import httpx

            token = config.get("api_token") or config.get("apiToken", "")
            account_id = config.get("account_id") or config.get("accountId", "")
            base_url = config.get("base_url", "https://cloud.getdbt.com")

            resp = httpx.get(
                f"{base_url}/api/v2/accounts/{account_id}/",
                headers={"Authorization": f"Token {token}"},
                timeout=15,
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return ConnectionResult(
                    ok=True,
                    message="Connected to dbt Cloud",
                    connected_at=datetime.utcnow(),
                    latency_ms=latency,
                )
            return ConnectionResult(
                ok=False,
                message=f"dbt Cloud returned HTTP {resp.status_code}",
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"dbt Cloud connection failed: {exc}",
                latency_ms=latency,
            )

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=False,
            can_extract_metadata=True,
            can_extract_lineage=True,
            can_fetch_logs=True,
            can_write=False,
            can_health_check=True,
            can_mcp=False,
            supported_monitors=["freshness", "schema_change"],
        )

    # ── Extraction ─────────────────────────────────────────────────────

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        try:
            manifest = config.get("manifest")
            if not manifest:
                return []

            nodes = manifest.get("nodes", {})
            sources = manifest.get("sources", {})

            models = [k for k, v in nodes.items() if v.get("resource_type") == "model"]
            tests = [k for k, v in nodes.items() if v.get("resource_type") == "test"]
            seeds = [k for k, v in nodes.items() if v.get("resource_type") == "seed"]
            snapshots = [k for k, v in nodes.items() if v.get("resource_type") == "snapshot"]

            summaries = []
            if models:
                summaries.append(AssetSummary(
                    asset_type="model",
                    count=len(models),
                    sample_names=[nodes[k].get("name", k) for k in models[:10]],
                ))
            if sources:
                summaries.append(AssetSummary(
                    asset_type="source",
                    count=len(sources),
                    sample_names=[v.get("name", k) for k, v in list(sources.items())[:10]],
                ))
            if tests:
                summaries.append(AssetSummary(asset_type="test", count=len(tests), sample_names=[]))
            if seeds:
                summaries.append(AssetSummary(asset_type="seed", count=len(seeds), sample_names=[]))
            if snapshots:
                summaries.append(AssetSummary(asset_type="snapshot", count=len(snapshots), sample_names=[]))
            return summaries
        except Exception as exc:
            logger.error("[DbtCloudDriver] extract_metadata failed: %s", exc)
            return []

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        try:
            from scanner.lineage.engine.adapters.live_dbt import LiveDbtAdapter

            lineage_config = {
                "manifest": config.get("manifest", {}),
                "warehouse_type": config.get("warehouse_type", "bigquery"),
                "namespace": config.get("account_id") or config.get("accountId", "dbt"),
            }
            adapter = LiveDbtAdapter(adapter_id="dbt_cloud_lineage")
            nodes = adapter.discover_assets(lineage_config)
            edges = adapter.extract_lineage(lineage_config)
            return nodes, edges
        except Exception as exc:
            logger.error("[DbtCloudDriver] extract_lineage failed: %s", exc)
            return [], []

    def fetch_logs(
        self, config: Dict[str, Any], *, limit: int = 100
    ) -> List[LogEntry]:
        try:
            import httpx

            token = config.get("api_token") or config.get("apiToken", "")
            account_id = config.get("account_id") or config.get("accountId", "")
            base_url = config.get("base_url", "https://cloud.getdbt.com")

            resp = httpx.get(
                f"{base_url}/api/v2/accounts/{account_id}/runs/",
                headers={"Authorization": f"Token {token}"},
                params={"limit": min(limit, 50), "order_by": "-finished_at"},
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            runs = resp.json().get("data", [])
            return [
                LogEntry(
                    timestamp=datetime.fromisoformat(
                        r.get("finished_at", r.get("created_at", datetime.utcnow().isoformat()))
                        .replace("Z", "+00:00")
                    ) if r.get("finished_at") or r.get("created_at") else datetime.utcnow(),
                    level="ERROR" if r.get("status") in (20, 30) else "INFO",
                    message=f"Run #{r.get('id')}: {r.get('status_humanized', 'unknown')} "
                            f"({r.get('duration_humanized', '?')})",
                    metadata={
                        "run_id": r.get("id"),
                        "job_id": r.get("job_id"),
                        "status": r.get("status"),
                        "git_sha": r.get("git_sha"),
                    },
                )
                for r in runs[:limit]
            ]
        except Exception as exc:
            logger.error("[DbtCloudDriver] fetch_logs failed: %s", exc)
            return []

    # ── Events & contracts ─────────────────────────────────────────────

    def events_emitted(self) -> List[str]:
        return [
            "run.completed",
            "run.failed",
            "test.failed",
            "model.changed",
            "extraction.completed",
            "extraction.failed",
        ]

    def contract_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "requiredTestCoverage": {
                    "type": "number",
                    "description": "Minimum test coverage percentage (0-100)",
                    "minimum": 0,
                    "maximum": 100,
                },
                "requiredDocCoverage": {
                    "type": "number",
                    "description": "Minimum documentation coverage percentage (0-100)",
                    "minimum": 0,
                    "maximum": 100,
                },
                "blockOnTestFailure": {
                    "type": "boolean",
                    "description": "Block deployment on test failures",
                    "default": True,
                },
            },
        }

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "schema_change"]
