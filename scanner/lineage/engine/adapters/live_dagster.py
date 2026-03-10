"""
Live Dagster Adapter — extracts lineage from Dagster assets and jobs.

Maps Dagster assets to TASK nodes on the ORCHESTRATION domain, schedules
to PIPELINE nodes, and creates dependency edges between assets. For assets
with compute_kind hints (dbt, sql, bigquery, snowflake), cross-plane
MATERIALIZES edges are created to link orchestration to warehouse tables.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, normalize_identifier

logger = logging.getLogger(__name__)

# compute_kind values that indicate warehouse table materialization
_WAREHOUSE_COMPUTE_KINDS = {"dbt", "sql", "bigquery", "snowflake", "postgres", "redshift"}


class LiveDagsterAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Dagster assets, schedules, and sensors,
    and extracts lineage edges between them.

    Config keys:
        namespace: Identifier for this Dagster instance (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        dagster_config: Dict with base_url or deployment_name/api_token
    """

    def __init__(self, adapter_id: str = "live_dagster", **kwargs):
        super().__init__(adapter_id, **kwargs)

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_RUNS_LOGS,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Dagster assets, schedules, and sensors."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "dagster")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover assets
        try:
            assets = client.get_assets()
        except Exception as e:
            logger.error(f"[LiveDagster] Failed to get assets: {e}")
            assets = []

        for asset in assets:
            node = self._make_asset_node(asset, namespace, integration_id, now)
            nodes.append(node)

        # Discover schedules
        try:
            schedules = client.get_schedules()
        except Exception as e:
            logger.error(f"[LiveDagster] Failed to get schedules: {e}")
            schedules = []

        for schedule in schedules:
            node = self._make_schedule_node(schedule, namespace, integration_id, now)
            nodes.append(node)

        # Discover sensors (low priority but include for completeness)
        try:
            sensors = client.get_sensors()
        except Exception as e:
            logger.warning(f"[LiveDagster] Failed to get sensors: {e}")
            sensors = []

        for sensor in sensors:
            node = self._make_sensor_node(sensor, namespace, integration_id, now)
            nodes.append(node)

        # ── CP metadata: derive orchestrated_tools from compute_kind ──
        orchestrated: Set[str] = set()
        for asset in assets:
            ck = (getattr(asset, "compute_kind", None) or "").lower()
            if ck in ("dbt", "dbt_cloud"):
                orchestrated.add("dbt")
            elif ck in ("spark", "pyspark"):
                orchestrated.add("spark")
            elif ck in ("fivetran",):
                orchestrated.add("fivetran")
            elif ck in ("airbyte",):
                orchestrated.add("airbyte")

        if orchestrated:
            for node in nodes:
                if node.raw_metadata is None:
                    node.raw_metadata = {}
                node.raw_metadata["orchestrated_tools"] = sorted(orchestrated)
            logger.info("[LiveDagster] CP metadata: orchestrated_tools=%s", sorted(orchestrated))

        logger.info(
            f"[LiveDagster] Discovered {len(nodes)} assets "
            f"({len(assets)} assets, {len(schedules)} schedules, {len(sensors)} sensors)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract asset dependency and schedule edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "dagster")
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        # Asset -> Asset dependency edges (CONTROL plane)
        try:
            assets = client.get_assets()
        except Exception as e:
            logger.error(f"[LiveDagster] Failed to get assets: {e}")
            assets = []

        for asset in assets:
            asset_key = getattr(asset, "key", "")
            if not asset_key:
                continue

            asset_id = generate_asset_id(
                "orchestration", "dagster", namespace, "", asset_key,
            )

            # Dependency edges: upstream asset -> this asset
            dependencies = getattr(asset, "dependencies", [])
            for dep_key in dependencies:
                dep_id = generate_asset_id(
                    "orchestration", "dagster", namespace, "", dep_key,
                )
                source_ref = f"dagster:{asset_key}:depends_on:{dep_key}"
                edge = self._make_edge(
                    dep_id, asset_id,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CONTROL,
                )
                edges.append(edge)

            # Cross-plane MATERIALIZES edges for warehouse-bound assets
            compute_kind = (getattr(asset, "compute_kind", None) or "").lower()
            if compute_kind in _WAREHOUSE_COMPUTE_KINDS:
                # The asset key often maps to a table name
                # Use the key parts as table reference
                table_ref = asset_key.replace("/", ".")
                parts = table_ref.split(".")
                name = normalize_identifier(parts[-1], self.case_hint)
                schema = normalize_identifier(parts[-2], self.case_hint) if len(parts) > 1 else ""
                db = normalize_identifier(parts[-3], self.case_hint) if len(parts) > 2 else ""
                container = f"{db}.{schema}"

                table_asset_id = generate_asset_id(
                    "warehouse", "dagster", namespace, container, name,
                )

                source_ref = f"dagster:{asset_key}:materializes:{table_ref}"
                edge = self._make_edge(
                    asset_id, table_asset_id,
                    EdgeType.MATERIALIZES, LineageLevel.TABLE,
                    confidence=0.8,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CROSS,
                )
                edges.append(edge)

        # Schedule -> asset edges
        try:
            schedules = client.get_schedules()
        except Exception:
            schedules = []

        # Build a lookup of job_name -> schedule for linking
        for schedule in schedules:
            sched_name = getattr(schedule, "name", "")
            job_name = getattr(schedule, "job_name", "")
            if not sched_name or not job_name:
                continue

            sched_asset_id = generate_asset_id(
                "orchestration", "dagster", namespace, "", f"schedule_{sched_name}",
            )

            # Find assets that belong to this job
            # Dagster assets are materialized by jobs; link schedule to all assets
            for asset in assets:
                asset_key = getattr(asset, "key", "")
                group_name = getattr(asset, "group_name", "")
                # Heuristic: if job_name matches group or key prefix
                if job_name and (
                    job_name == group_name
                    or asset_key.startswith(job_name)
                    or job_name in asset_key
                ):
                    asset_id = generate_asset_id(
                        "orchestration", "dagster", namespace, "", asset_key,
                    )
                    source_ref = f"dagster:schedule:{sched_name}:triggers:{asset_key}"
                    edge = self._make_edge(
                        sched_asset_id, asset_id,
                        EdgeType.TRIGGERS, LineageLevel.TOOL,
                        confidence=0.7,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CONTROL,
                    )
                    edges.append(edge)

        logger.info(f"[LiveDagster] Extracted {len(edges)} edges")
        return edges

    def fetch_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch recent run information for context."""
        client = self._get_client(config)
        if not client:
            return {}

        try:
            runs = client.get_runs(limit=10)
            return {
                "recent_runs": [
                    {
                        "run_id": getattr(r, "run_id", ""),
                        "job_name": getattr(r, "job_name", ""),
                        "status": getattr(r, "status", None).value if getattr(r, "status", None) else "unknown",
                    }
                    for r in runs
                ],
            }
        except Exception as e:
            logger.warning(f"[LiveDagster] Failed to fetch context: {e}")
            return {}

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a DagsterIntegration client."""
        if config.get("client"):
            return config["client"]

        dagster_config = config.get("dagster_config", {})
        if not dagster_config.get("base_url") and not dagster_config.get("deployment_name"):
            logger.warning("[LiveDagster] No dagster_config with base_url or deployment_name")
            return None

        try:
            from scanner.integrations.dagster import DagsterIntegration
        except ImportError:
            from integrations.dagster import DagsterIntegration

        return DagsterIntegration(dagster_config)

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_asset_node(
        self, asset, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for a Dagster asset."""
        key = getattr(asset, "key", "unknown")
        group_name = getattr(asset, "group_name", None)
        description = getattr(asset, "description", None)
        compute_kind = getattr(asset, "compute_kind", None)
        owners = getattr(asset, "owners", [])
        tags = getattr(asset, "tags", {})
        is_partitioned = getattr(asset, "is_partitioned", False)
        has_checks = getattr(asset, "has_checks", False)
        dependencies = getattr(asset, "dependencies", [])

        asset_id = generate_asset_id(
            "orchestration", "dagster", namespace, "", key,
        )

        return LineageNode(
            id=asset_id,
            name=key,
            fqn=f"dagster.{namespace}.{key}",
            node_type=NodeType.TASK,
            platform="dagster",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.TASK,
            namespace=namespace,
            description=description,
            owner=owners[0] if owners else None,
            tags=list(tags.keys()) if isinstance(tags, dict) else [],
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "group_name": group_name,
                "compute_kind": compute_kind,
                "is_partitioned": is_partitioned,
                "has_checks": has_checks,
                "dependency_count": len(dependencies),
                "inputs": [],  # For cross-tool synthesis
                "outputs": [],
            },
        )

    def _make_schedule_node(
        self, schedule, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for a Dagster schedule."""
        name = getattr(schedule, "name", "unknown")
        cron = getattr(schedule, "cron_schedule", "")
        job_name = getattr(schedule, "job_name", "")
        status = getattr(schedule, "status", "STOPPED")

        asset_id = generate_asset_id(
            "orchestration", "dagster", namespace, "", f"schedule_{name}",
        )

        return LineageNode(
            id=asset_id,
            name=name,
            fqn=f"dagster.{namespace}.schedule.{name}",
            node_type=NodeType.PIPELINE,
            platform="dagster",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "cron_schedule": cron,
                "job_name": job_name,
                "status": status,
            },
        )

    def _make_sensor_node(
        self, sensor, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for a Dagster sensor."""
        name = getattr(sensor, "name", "unknown")
        job_name = getattr(sensor, "job_name", None)
        status = getattr(sensor, "status", "STOPPED")

        asset_id = generate_asset_id(
            "orchestration", "dagster", namespace, "", f"sensor_{name}",
        )

        return LineageNode(
            id=asset_id,
            name=name,
            fqn=f"dagster.{namespace}.sensor.{name}",
            node_type=NodeType.TASK,
            platform="dagster",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.TASK,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "sensor_type": "sensor",
                "job_name": job_name,
                "status": status,
            },
        )

        edge_id = generate_edge_id(
            source_id, target_id,
            edge_type.value, level.value,
            source_ref,
        )
        return LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=level,
            confidence=confidence,
            discovered_from=source_ref,
            discovered_at=now,
            evidence=[ev],
            plane=plane,
        )
