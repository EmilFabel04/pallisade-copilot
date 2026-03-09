"""
Snowflake IntegrationDriver — FULL implementation.

Composes:
  - scanner.adapters.snowflake.SnowflakeAdapter  (query, metadata, query history)
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


class SnowflakeDriver(IntegrationDriver):
    """Full-wired Snowflake driver (DATA_PLANE)."""

    def id(self) -> str:
        return "snowflake"

    def integration_type(self) -> str:
        return "SNOWFLAKE"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.WAREHOUSE

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    # ── Lifecycle ──────────────────────────────────────────────────────

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []
        warnings: List[str] = []

        if not config.get("account"):
            errors.append("account is required")
        if not config.get("user") and not config.get("username"):
            errors.append("user is required")
        if not (config.get("password") or config.get("private_key") or config.get("privateKey")):
            errors.append("password or private_key is required")
        if not config.get("warehouse"):
            warnings.append("No warehouse specified — queries may use account default")
        if not config.get("database"):
            warnings.append("No database specified — all databases will be scanned")

        return ConfigValidation(valid=not errors, errors=errors, warnings=warnings)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        start = time.time()
        try:
            from scanner.adapters.factory import AdapterFactory

            adapter = AdapterFactory.get_adapter("snowflake", config, auto_connect=True)
            try:
                ok, msg = adapter.test_connection()
                latency = int((time.time() - start) * 1000)
                return ConnectionResult(
                    ok=ok,
                    message=msg or "Connected to Snowflake",
                    connected_at=datetime.utcnow() if ok else None,
                    latency_ms=latency,
                )
            finally:
                adapter.disconnect()
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"Snowflake connection failed: {exc}",
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

            adapter = AdapterFactory.get_adapter("snowflake", config, auto_connect=True)
            try:
                tables = adapter.get_tables()
                return [AssetSummary(
                    asset_type="table",
                    count=len(tables),
                    sample_names=tables[:10],
                )] if tables else []
            finally:
                adapter.disconnect()
        except Exception as exc:
            logger.error("[SnowflakeDriver] extract_metadata failed: %s", exc)
            return []

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        try:
            from scanner.lineage.engine.adapters.live_warehouse import LiveWarehouseAdapter

            lineage_config = {
                "platform": "snowflake",
                "connection_config": config,
            }
            adapter = LiveWarehouseAdapter(adapter_id="snowflake_lineage")
            nodes = adapter.discover_assets(lineage_config)
            edges = adapter.extract_lineage(lineage_config)
            return nodes, edges
        except Exception as exc:
            logger.error("[SnowflakeDriver] extract_lineage failed: %s", exc)
            return [], []

    def fetch_logs(
        self, config: Dict[str, Any], *, limit: int = 100
    ) -> List[LogEntry]:
        try:
            from scanner.adapters.factory import AdapterFactory

            adapter = AdapterFactory.get_adapter("snowflake", config, auto_connect=True)
            try:
                entries = adapter.get_query_history(days=7, limit=limit)
                return [
                    LogEntry(
                        timestamp=getattr(e, "start_time", datetime.utcnow()),
                        level="INFO",
                        message=f"Query {getattr(e, 'query_id', 'unknown')}: "
                                f"{getattr(e, 'query_text', '')[:200]}",
                        metadata={
                            "credits_used": getattr(e, "credits_used", None),
                            "duration_ms": getattr(e, "duration_ms", None),
                            "user": getattr(e, "user_name", None),
                            "warehouse": getattr(e, "warehouse_name", None),
                        },
                    )
                    for e in (entries or [])[:limit]
                ]
            finally:
                adapter.disconnect()
        except Exception as exc:
            logger.error("[SnowflakeDriver] fetch_logs failed: %s", exc)
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
                "maxCreditsPerQuery": {
                    "type": "number",
                    "description": "Maximum credits consumed per query before alerting",
                },
                "requireWarehouse": {
                    "type": "boolean",
                    "description": "Require explicit warehouse specification",
                    "default": True,
                },
            },
        }

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "schema_change", "anomaly"]
