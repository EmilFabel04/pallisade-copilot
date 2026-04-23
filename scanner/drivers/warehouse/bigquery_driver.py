"""
BigQuery IntegrationDriver — FULL implementation.

Composes:
  - scanner.adapters.bigquery.BigQueryAdapter  (query, metadata, query history)
  - scanner.lineage.engine.adapters.live_warehouse.LiveWarehouseAdapter  (lineage)
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


class BigQueryDriver(IntegrationDriver):
    """Full-wired BigQuery driver (DATA_PLANE)."""

    # ── Identity ───────────────────────────────────────────────────────

    def id(self) -> str:
        return "bigquery"

    def integration_type(self) -> str:
        return "BIGQUERY"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.WAREHOUSE

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    # ── Lifecycle ──────────────────────────────────────────────────────

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []
        warnings: List[str] = []

        if not config.get("project_id") and not config.get("projectId"):
            errors.append("project_id is required")

        has_creds = (
            config.get("credentials")
            or config.get("credentials_json")
            or config.get("credentialsJson")
            or config.get("keyfile")
        )
        if not has_creds:
            errors.append("credentials or credentials_json is required")

        if not config.get("dataset") and not config.get("default_dataset"):
            warnings.append("No default dataset specified — all datasets will be scanned")

        return ConfigValidation(valid=not errors, errors=errors, warnings=warnings)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        start = time.time()
        try:
            from scanner.adapters.factory import AdapterFactory

            adapter = AdapterFactory.get_adapter("bigquery", config, auto_connect=True)
            try:
                ok, msg = adapter.test_connection()
                latency = int((time.time() - start) * 1000)
                return ConnectionResult(
                    ok=ok,
                    message=msg or "Connected to BigQuery",
                    connected_at=datetime.utcnow() if ok else None,
                    latency_ms=latency,
                )
            finally:
                adapter.disconnect()
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"BigQuery connection failed: {exc}",
                latency_ms=latency,
            )

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=True,
            can_extract_metadata=True,
            can_extract_lineage=True,
            can_fetch_logs=True,
            can_write=False,
            can_health_check=True,
            can_mcp=False,
            supported_monitors=["freshness", "volume", "schema_change", "anomaly"],
        )

    # ── Extraction ─────────────────────────────────────────────────────

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        try:
            from scanner.adapters.factory import AdapterFactory

            adapter = AdapterFactory.get_adapter("bigquery", config, auto_connect=True)
            try:
                tables = adapter.get_tables()
                views = [t for t in tables if "view" in t.lower()]
                regular = [t for t in tables if t not in views]
                summaries = []
                if regular:
                    summaries.append(AssetSummary(
                        asset_type="table",
                        count=len(regular),
                        sample_names=regular[:10],
                    ))
                if views:
                    summaries.append(AssetSummary(
                        asset_type="view",
                        count=len(views),
                        sample_names=views[:10],
                    ))
                return summaries
            finally:
                adapter.disconnect()
        except Exception as exc:
            logger.error("[BigQueryDriver] extract_metadata failed: %s", exc)
            return []

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        try:
            from scanner.lineage.engine.adapters.live_warehouse import LiveWarehouseAdapter

            lineage_config = {
                "platform": "bigquery",
                "connection_config": config,
            }
            adapter = LiveWarehouseAdapter(adapter_id="bigquery_lineage")
            nodes = adapter.discover_assets(lineage_config)
            edges = adapter.extract_lineage(lineage_config)
            return nodes, edges
        except Exception as exc:
            logger.error("[BigQueryDriver] extract_lineage failed: %s", exc)
            return [], []

    def fetch_logs(
        self, config: Dict[str, Any], *, limit: int = 100
    ) -> List[LogEntry]:
        try:
            from scanner.adapters.factory import AdapterFactory

            adapter = AdapterFactory.get_adapter("bigquery", config, auto_connect=True)
            try:
                entries = adapter.get_query_history(days=7, limit=limit)
                return [
                    LogEntry(
                        timestamp=e.start_time if hasattr(e, "start_time") else datetime.utcnow(),
                        level="INFO",
                        message=f"Query {getattr(e, 'query_id', 'unknown')}: "
                                f"{getattr(e, 'query_text', '')[:200]}",
                        metadata={
                            "bytes_billed": getattr(e, "bytes_billed", None),
                            "duration_ms": getattr(e, "duration_ms", None),
                            "user": getattr(e, "user_email", None),
                        },
                    )
                    for e in (entries or [])[:limit]
                ]
            finally:
                adapter.disconnect()
        except Exception as exc:
            logger.error("[BigQueryDriver] fetch_logs failed: %s", exc)
            return []

    # ── Events & contracts ─────────────────────────────────────────────

    def events_emitted(self) -> List[str]:
        return [
            "extraction.completed",
            "extraction.failed",
            "schema.changed",
            "health.connected",
            "health.disconnected",
        ]

    def contract_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "maxQueryCostUsd": {
                    "type": "number",
                    "description": "Maximum query cost in USD before alerting",
                },
                "requireDryRun": {
                    "type": "boolean",
                    "description": "Require dry-run cost estimation before execution",
                    "default": False,
                },
                "maxScanBytes": {
                    "type": "integer",
                    "description": "Maximum bytes scanned per query",
                },
            },
        }

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change", "anomaly"]
