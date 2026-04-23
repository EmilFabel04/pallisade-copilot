"""
Fivetran IntegrationDriver — FULL implementation.

Composes:
  - scanner.integrations.fivetran.FivetranIntegration  (connectors, sync status)
  - scanner.lineage.engine.adapters.live_fivetran.LiveFivetranAdapter  (lineage)
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


class FivetranDriver(IntegrationDriver):
    """Full-wired Fivetran driver (DATA_PLANE)."""

    def id(self) -> str:
        return "fivetran"

    def integration_type(self) -> str:
        return "FIVETRAN"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.INGESTION

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    # ── Lifecycle ──────────────────────────────────────────────────────

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []
        warnings: List[str] = []

        if not config.get("api_key") and not config.get("apiKey"):
            errors.append("api_key is required")
        if not config.get("api_secret") and not config.get("apiSecret"):
            errors.append("api_secret is required")

        return ConfigValidation(valid=not errors, errors=errors, warnings=warnings)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        start = time.time()
        try:
            import httpx
            import base64

            api_key = config.get("api_key") or config.get("apiKey", "")
            api_secret = config.get("api_secret") or config.get("apiSecret", "")
            auth_str = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()

            resp = httpx.get(
                "https://api.fivetran.com/v1/groups",
                headers={"Authorization": f"Basic {auth_str}"},
                timeout=15,
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return ConnectionResult(
                    ok=True,
                    message="Connected to Fivetran",
                    connected_at=datetime.utcnow(),
                    latency_ms=latency,
                )
            return ConnectionResult(
                ok=False,
                message=f"Fivetran returned HTTP {resp.status_code}",
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"Fivetran connection failed: {exc}",
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
            supported_monitors=["freshness", "volume"],
        )

    # ── Extraction ─────────────────────────────────────────────────────

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        try:
            import httpx
            import base64

            api_key = config.get("api_key") or config.get("apiKey", "")
            api_secret = config.get("api_secret") or config.get("apiSecret", "")
            auth_str = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
            headers = {"Authorization": f"Basic {auth_str}"}

            resp = httpx.get(
                "https://api.fivetran.com/v1/groups",
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            groups = resp.json().get("data", {}).get("items", [])
            total_connectors = 0
            connector_names: List[str] = []

            for group in groups[:5]:
                gid = group.get("id", "")
                c_resp = httpx.get(
                    f"https://api.fivetran.com/v1/groups/{gid}/connectors",
                    headers=headers,
                    timeout=15,
                )
                if c_resp.status_code == 200:
                    connectors = c_resp.json().get("data", {}).get("items", [])
                    total_connectors += len(connectors)
                    connector_names.extend(
                        c.get("schema", c.get("id", "")) for c in connectors[:5]
                    )

            return [AssetSummary(
                asset_type="connector",
                count=total_connectors,
                sample_names=connector_names[:10],
            )] if total_connectors else []
        except Exception as exc:
            logger.error("[FivetranDriver] extract_metadata failed: %s", exc)
            return []

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        try:
            from scanner.lineage.engine.adapters.live_fivetran import LiveFivetranAdapter

            lineage_config = {
                "namespace": config.get("namespace", "fivetran"),
                "fivetran_config": config,
            }
            adapter = LiveFivetranAdapter(adapter_id="fivetran_lineage")
            nodes = adapter.discover_assets(lineage_config)
            edges = adapter.extract_lineage(lineage_config)
            return nodes, edges
        except Exception as exc:
            logger.error("[FivetranDriver] extract_lineage failed: %s", exc)
            return [], []

    def fetch_logs(
        self, config: Dict[str, Any], *, limit: int = 100
    ) -> List[LogEntry]:
        try:
            import httpx
            import base64

            api_key = config.get("api_key") or config.get("apiKey", "")
            api_secret = config.get("api_secret") or config.get("apiSecret", "")
            auth_str = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
            headers = {"Authorization": f"Basic {auth_str}"}

            # Get first group's connectors for sync logs
            g_resp = httpx.get(
                "https://api.fivetran.com/v1/groups",
                headers=headers,
                timeout=15,
            )
            if g_resp.status_code != 200:
                return []

            groups = g_resp.json().get("data", {}).get("items", [])
            logs: List[LogEntry] = []
            for group in groups[:3]:
                gid = group.get("id", "")
                c_resp = httpx.get(
                    f"https://api.fivetran.com/v1/groups/{gid}/connectors",
                    headers=headers,
                    timeout=15,
                )
                if c_resp.status_code != 200:
                    continue
                connectors = c_resp.json().get("data", {}).get("items", [])
                for conn in connectors[:5]:
                    status = conn.get("status", {})
                    sync_state = status.get("sync_state", "unknown")
                    update_state = status.get("update_state", "unknown")
                    logs.append(LogEntry(
                        timestamp=datetime.utcnow(),
                        level="ERROR" if sync_state == "broken" else "INFO",
                        message=f"Connector {conn.get('schema', conn.get('id', '?'))}: "
                                f"sync={sync_state}, update={update_state}",
                        metadata={
                            "connector_id": conn.get("id"),
                            "service": conn.get("service"),
                            "sync_state": sync_state,
                        },
                    ))
                    if len(logs) >= limit:
                        break
                if len(logs) >= limit:
                    break

            return logs[:limit]
        except Exception as exc:
            logger.error("[FivetranDriver] fetch_logs failed: %s", exc)
            return []

    # ── Events & contracts ─────────────────────────────────────────────

    def events_emitted(self) -> List[str]:
        return [
            "sync.completed",
            "sync.failed",
            "schema.change",
            "connector.paused",
            "connector.broken",
            "extraction.completed",
            "extraction.failed",
        ]

    def contract_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "maxSyncLagMinutes": {
                    "type": "integer",
                    "description": "Maximum minutes since last successful sync",
                },
                "requireSchemaChangeApproval": {
                    "type": "boolean",
                    "description": "Require approval for schema changes",
                    "default": False,
                },
            },
        }

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume"]
