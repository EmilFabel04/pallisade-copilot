"""
Airflow IntegrationDriver — FULL implementation.

Composes:
  - scanner.integrations.airflow  (DAGs, tasks, runs)
  - scanner.lineage.engine.adapters.live_airflow.LiveAirflowAdapter  (lineage)
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


class AirflowDriver(IntegrationDriver):
    """Full-wired Airflow driver (DATA_PLANE)."""

    def id(self) -> str:
        return "airflow"

    def integration_type(self) -> str:
        return "AIRFLOW"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.ORCHESTRATION

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    # ── Lifecycle ──────────────────────────────────────────────────────

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []
        warnings: List[str] = []

        if not config.get("base_url") and not config.get("baseUrl"):
            errors.append("base_url is required")
        if not config.get("username") and not config.get("user"):
            warnings.append("No username — may fail for authenticated endpoints")

        return ConfigValidation(valid=not errors, errors=errors, warnings=warnings)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        start = time.time()
        try:
            import httpx

            base_url = (config.get("base_url") or config.get("baseUrl", "")).rstrip("/")
            username = config.get("username") or config.get("user", "")
            password = config.get("password", "")

            auth = (username, password) if username else None
            resp = httpx.get(
                f"{base_url}/api/v1/health",
                auth=auth,
                timeout=15,
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return ConnectionResult(
                    ok=True,
                    message="Connected to Airflow",
                    connected_at=datetime.utcnow(),
                    latency_ms=latency,
                )
            return ConnectionResult(
                ok=False,
                message=f"Airflow returned HTTP {resp.status_code}",
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"Airflow connection failed: {exc}",
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
            supported_monitors=["freshness"],
        )

    # ── Extraction ─────────────────────────────────────────────────────

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        try:
            import httpx

            base_url = (config.get("base_url") or config.get("baseUrl", "")).rstrip("/")
            username = config.get("username") or config.get("user", "")
            password = config.get("password", "")
            auth = (username, password) if username else None

            resp = httpx.get(
                f"{base_url}/api/v1/dags",
                auth=auth,
                params={"limit": 100},
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            dags = resp.json().get("dags", [])
            return [AssetSummary(
                asset_type="dag",
                count=len(dags),
                sample_names=[d.get("dag_id", "") for d in dags[:10]],
            )] if dags else []
        except Exception as exc:
            logger.error("[AirflowDriver] extract_metadata failed: %s", exc)
            return []

    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        try:
            from scanner.lineage.engine.adapters.live_airflow import LiveAirflowAdapter

            lineage_config = {
                "mode": "api" if config.get("base_url") or config.get("baseUrl") else "static",
                "namespace": config.get("namespace", "airflow"),
                "base_url": config.get("base_url") or config.get("baseUrl", ""),
                "username": config.get("username") or config.get("user", ""),
                "password": config.get("password", ""),
            }
            adapter = LiveAirflowAdapter(adapter_id="airflow_lineage")
            nodes = adapter.discover_assets(lineage_config)
            edges = adapter.extract_lineage(lineage_config)
            return nodes, edges
        except Exception as exc:
            logger.error("[AirflowDriver] extract_lineage failed: %s", exc)
            return [], []

    def fetch_logs(
        self, config: Dict[str, Any], *, limit: int = 100
    ) -> List[LogEntry]:
        try:
            import httpx

            base_url = (config.get("base_url") or config.get("baseUrl", "")).rstrip("/")
            username = config.get("username") or config.get("user", "")
            password = config.get("password", "")
            auth = (username, password) if username else None

            resp = httpx.get(
                f"{base_url}/api/v1/dags/~/dagRuns",
                auth=auth,
                params={"limit": min(limit, 50), "order_by": "-execution_date"},
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            runs = resp.json().get("dag_runs", [])
            return [
                LogEntry(
                    timestamp=datetime.fromisoformat(
                        r.get("execution_date", datetime.utcnow().isoformat())
                        .replace("Z", "+00:00")
                    ) if r.get("execution_date") else datetime.utcnow(),
                    level="ERROR" if r.get("state") == "failed" else "INFO",
                    message=f"DAG {r.get('dag_id', '?')} run {r.get('dag_run_id', '?')}: "
                            f"{r.get('state', 'unknown')}",
                    metadata={
                        "dag_id": r.get("dag_id"),
                        "run_id": r.get("dag_run_id"),
                        "state": r.get("state"),
                    },
                )
                for r in runs[:limit]
            ]
        except Exception as exc:
            logger.error("[AirflowDriver] fetch_logs failed: %s", exc)
            return []

    # ── Events & contracts ─────────────────────────────────────────────

    def events_emitted(self) -> List[str]:
        return [
            "dag.success",
            "dag.failure",
            "task.retry",
            "sla.missed",
            "extraction.completed",
            "extraction.failed",
        ]

    def contract_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "maxDagDurationMinutes": {
                    "type": "integer",
                    "description": "Maximum DAG run duration in minutes before SLA alert",
                },
                "requiredSuccessRate": {
                    "type": "number",
                    "description": "Minimum DAG success rate (0-1)",
                    "minimum": 0,
                    "maximum": 1,
                },
            },
        }

    def recommended_monitors(self) -> List[str]:
        return ["freshness"]
