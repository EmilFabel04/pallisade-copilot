"""
Live Prefect Adapter — extracts lineage from Prefect flows and deployments.

Maps Prefect flows to FLOW nodes and deployments to PIPELINE nodes on the
ORCHESTRATION domain. Creates dependency edges between deployments and
their flows, and inspects flow metadata for cross-plane table references.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)


class LivePrefectAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Prefect flows/deployments and extracts lineage.

    Config keys:
        namespace: Identifier for this Prefect instance (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        prefect_config: Dict with api_url, api_key, account_id, workspace_id
    """

    def __init__(self, adapter_id: str = "live_prefect", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.GET_RUNS_LOGS,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Prefect flows and deployments."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "prefect")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover flows
        try:
            flows = client.get_flows()
        except Exception as e:
            logger.error(f"[LivePrefect] Failed to get flows: {e}")
            flows = []

        flow_lookup: Dict[str, Any] = {}
        for flow in flows:
            flow_id = getattr(flow, "id", "")
            flow_name = getattr(flow, "name", "unknown")
            flow_lookup[flow_id] = flow

            node = self._make_flow_node(flow, namespace, integration_id, now)
            nodes.append(node)

        # Discover deployments
        try:
            deployments = client.get_deployments()
        except Exception as e:
            logger.error(f"[LivePrefect] Failed to get deployments: {e}")
            deployments = []

        for deployment in deployments:
            node = self._make_deployment_node(deployment, namespace, integration_id, now)
            nodes.append(node)

        logger.info(
            f"[LivePrefect] Discovered {len(nodes)} assets "
            f"({len(flows)} flows, {len(deployments)} deployments)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract deployment -> flow edges and flow -> table cross-plane edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "prefect")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Get flows and deployments
        try:
            flows = client.get_flows()
        except Exception:
            flows = []

        try:
            deployments = client.get_deployments()
        except Exception:
            deployments = []

        # Build flow_id -> flow lookup
        flow_by_id: Dict[str, Any] = {}
        for flow in flows:
            fid = getattr(flow, "id", "")
            if fid:
                flow_by_id[fid] = flow

        # Deployment -> Flow edges (CONTROL plane, DEPENDS_ON)
        for deployment in deployments:
            dep_name = getattr(deployment, "name", "unknown")
            dep_flow_id = getattr(deployment, "flow_id", "")
            dep_flow_name = getattr(deployment, "flow_name", "")

            dep_asset_id = generate_asset_id(
                "orchestration", "prefect", namespace, "", f"deployment_{dep_name}",
            )

            # Link to flow
            flow = flow_by_id.get(dep_flow_id)
            if flow:
                flow_name = getattr(flow, "name", dep_flow_name)
                flow_asset_id = generate_asset_id(
                    "orchestration", "prefect", namespace, "", flow_name,
                )
                source_ref = f"prefect:deployment:{dep_name}:flow:{flow_name}"
                edge = self._make_edge(
                    dep_asset_id, flow_asset_id,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=source_ref,
                    now=now,
                    plane=LinePlane.CONTROL,
                )
                edges.append(edge)

        # Flow -> table cross-plane edges from tags and run metadata
        for flow in flows:
            flow_name = getattr(flow, "name", "unknown")
            flow_tags = getattr(flow, "tags", [])

            flow_asset_id = generate_asset_id(
                "orchestration", "prefect", namespace, "", flow_name,
            )

            # Parse tags for table references (convention: "table:schema.table_name")
            table_refs = self._extract_table_refs_from_tags(flow_tags)

            for ref_type, table_ref in table_refs:
                parts = table_ref.split(".")
                name = normalize_identifier(parts[-1], hint)
                schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
                db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
                container = f"{db}.{schema}"

                table_asset_id = generate_asset_id(
                    "warehouse", "prefect", namespace, container, name,
                )

                if ref_type == "reads":
                    source_ref = f"prefect:{flow_name}:reads:{table_ref}"
                    edge = self._make_edge(
                        table_asset_id, flow_asset_id,
                        EdgeType.READS_FROM, LineageLevel.TABLE,
                        confidence=0.6,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                else:  # writes
                    source_ref = f"prefect:{flow_name}:writes:{table_ref}"
                    edge = self._make_edge(
                        flow_asset_id, table_asset_id,
                        EdgeType.WRITES_TO, LineageLevel.TABLE,
                        confidence=0.6,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                edges.append(edge)

        # Inspect recent flow runs for task-level I/O metadata
        run_edges = self._extract_edges_from_runs(client, flows, namespace, hint, now)
        edges.extend(run_edges)

        logger.info(f"[LivePrefect] Extracted {len(edges)} edges")
        return edges

    def fetch_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch recent flow run information for context."""
        client = self._get_client(config)
        if not client:
            return {}

        try:
            runs = client.get_flow_runs(limit=10)
            return {
                "recent_runs": [
                    {
                        "run_id": getattr(r, "id", ""),
                        "flow_name": getattr(r, "flow_name", ""),
                        "state": getattr(r, "state", None).value if getattr(r, "state", None) else "unknown",
                    }
                    for r in runs
                ],
            }
        except Exception as e:
            logger.warning(f"[LivePrefect] Failed to fetch context: {e}")
            return {}

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a PrefectIntegration client."""
        if config.get("client"):
            return config["client"]

        prefect_config = config.get("prefect_config", {})
        if not prefect_config.get("api_url") and not prefect_config.get("account_id"):
            logger.warning("[LivePrefect] No prefect_config with api_url or account_id")
            return None

        try:
            from scanner.integrations.prefect import PrefectIntegration
        except ImportError:
            from integrations.prefect import PrefectIntegration

        return PrefectIntegration(prefect_config)

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_flow_node(
        self, flow, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for a Prefect flow."""
        flow_name = getattr(flow, "name", "unknown")
        flow_id = getattr(flow, "id", "")
        tags = getattr(flow, "tags", [])
        deployment_count = getattr(flow, "deployment_count", 0)
        last_run_state = getattr(flow, "last_run_state", None)
        last_run_state_val = last_run_state.value if hasattr(last_run_state, "value") else str(last_run_state) if last_run_state else None

        asset_id = generate_asset_id(
            "orchestration", "prefect", namespace, "", flow_name,
        )

        return LineageNode(
            id=asset_id,
            name=flow_name,
            fqn=f"prefect.{namespace}.{flow_name}",
            node_type=NodeType.FLOW,
            platform="prefect",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            namespace=namespace,
            tags=tags if isinstance(tags, list) else [],
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "flow_id": flow_id,
                "deployment_count": deployment_count,
                "last_run_state": last_run_state_val,
                "inputs": [],  # For cross-tool synthesis
                "outputs": [],
            },
        )

    def _make_deployment_node(
        self, deployment, namespace: str, integration_id: Optional[str], now: datetime,
    ) -> LineageNode:
        """Create a node for a Prefect deployment."""
        dep_name = getattr(deployment, "name", "unknown")
        dep_id = getattr(deployment, "id", "")
        flow_id = getattr(deployment, "flow_id", "")
        flow_name = getattr(deployment, "flow_name", "")
        schedule = getattr(deployment, "schedule", None)
        work_pool_name = getattr(deployment, "work_pool_name", None)
        is_schedule_active = getattr(deployment, "is_schedule_active", True)
        tags = getattr(deployment, "tags", [])
        status = getattr(deployment, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status) if status else "unknown"

        asset_id = generate_asset_id(
            "orchestration", "prefect", namespace, "", f"deployment_{dep_name}",
        )

        return LineageNode(
            id=asset_id,
            name=dep_name,
            fqn=f"prefect.{namespace}.deployment.{dep_name}",
            node_type=NodeType.PIPELINE,
            platform="prefect",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            namespace=namespace,
            tags=tags if isinstance(tags, list) else [],
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "deployment_id": dep_id,
                "flow_id": flow_id,
                "flow_name": flow_name,
                "schedule": schedule if isinstance(schedule, dict) else str(schedule) if schedule else None,
                "work_pool_name": work_pool_name,
                "is_schedule_active": is_schedule_active,
                "status": status_val,
            },
        )

    # ------------------------------------------------------------------
    # Table reference extraction
    # ------------------------------------------------------------------

    def _extract_table_refs_from_tags(self, tags: List[str]) -> List[tuple]:
        """
        Extract table references from flow tags.

        Conventions:
            "reads:schema.table" -> ("reads", "schema.table")
            "writes:schema.table" -> ("writes", "schema.table")
            "table:schema.table" -> ("reads", "schema.table")  # default to reads
        """
        refs = []
        for tag in tags:
            tag_lower = tag.lower().strip()
            if tag_lower.startswith("reads:"):
                refs.append(("reads", tag[6:].strip()))
            elif tag_lower.startswith("writes:"):
                refs.append(("writes", tag[7:].strip()))
            elif tag_lower.startswith("table:"):
                refs.append(("reads", tag[6:].strip()))
        return refs

    def _extract_edges_from_runs(
        self, client, flows: List, namespace: str, hint: str, now: datetime,
    ) -> List[LineageEdge]:
        """
        Inspect recent flow runs for task-level I/O metadata.

        Flows that store table references in their run metadata
        (raw_metadata inputs/outputs) get cross-plane edges.
        """
        edges: List[LineageEdge] = []

        for flow in flows:
            flow_name = getattr(flow, "name", "unknown")
            flow_id = getattr(flow, "id", "")

            if not flow_id:
                continue

            try:
                runs = client.get_flow_runs(flow_id=flow_id, limit=1)
            except Exception:
                continue

            if not runs:
                continue

            # Check the most recent run for metadata
            latest_run = runs[0]
            run_tags = getattr(latest_run, "tags", [])

            # Extract table refs from run tags too
            table_refs = self._extract_table_refs_from_tags(run_tags)
            flow_asset_id = generate_asset_id(
                "orchestration", "prefect", namespace, "", flow_name,
            )

            for ref_type, table_ref in table_refs:
                parts = table_ref.split(".")
                name = normalize_identifier(parts[-1], hint)
                schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
                db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
                container = f"{db}.{schema}"

                table_asset_id = generate_asset_id(
                    "warehouse", "prefect", namespace, container, name,
                )

                if ref_type == "reads":
                    source_ref = f"prefect:run:{flow_name}:reads:{table_ref}"
                    edge = self._make_edge(
                        table_asset_id, flow_asset_id,
                        EdgeType.READS_FROM, LineageLevel.TABLE,
                        confidence=0.5,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                else:
                    source_ref = f"prefect:run:{flow_name}:writes:{table_ref}"
                    edge = self._make_edge(
                        flow_asset_id, table_asset_id,
                        EdgeType.WRITES_TO, LineageLevel.TABLE,
                        confidence=0.5,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CROSS,
                    )
                edges.append(edge)

        return edges

    # ------------------------------------------------------------------
    # Edge helpers
    # ------------------------------------------------------------------

    def _make_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        level: LineageLevel,
        confidence: float,
        source_ref: str,
        now: datetime,
        snippet: Optional[str] = None,
        plane: LinePlane = LinePlane.DATA,
    ) -> LineageEdge:
        ev = Evidence(
            adapter_id=self._id,
            source_ref=source_ref,
            observed_at=now,
            snippet=snippet[:200] if snippet else None,
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
