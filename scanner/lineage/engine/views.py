"""
Rendered View Builder

Produces pre-computed, deterministic views from the engine's LineageGraph.
Each view is a curated projection with:
  - Canonical node/edge types
  - Deterministic x,y positions (no client-side layout needed)
  - Visual clustering by platform/integration
  - Inferred/needs-mapping metadata

Three views are supported:
  1. PipelineOverview — tool-sequence view (Fivetran → Snowflake → dbt → Looker)
  2. DataPlane — dataset-to-dataset derivation chains
  3. LanePipelineOverview — lane-based curated view with fixed lanes:
       ingestion → warehouse_raw → transformation → warehouse_analytics → reporting
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..graph import (
    LineageEdge,
    LineageGraph,
    LineageNode,
    LinePlane,
    PlatformDomain,
)
from .canonical import (
    CanonicalEdgeType,
    CanonicalNodeType,
    DOMAIN_TO_LAYER,
    LAYER_ORDER,
    get_layer,
    get_layer_order,
    is_needs_mapping,
    map_node_type,
)
from .zones import (
    ActorCapability,
    DatasetZone,
    PipelineLane,
    LANE_ORDER,
    INFRA_PLATFORMS,
    INGESTION_PLATFORMS,
    ORCHESTRATION_PLATFORMS,
    REPORTING_PLATFORMS,
    TRANSFORM_PLATFORMS,
    WAREHOUSE_PLATFORMS,
    assign_lane,
    classify_actor_capability,
    classify_data_plane_layer,
    classify_dataset_zone,
)

logger = logging.getLogger(__name__)


@dataclass
class _BypassInfo:
    """Metadata for a bypass edge that replaces a dataset→job→dataset path."""
    upstream_id: str
    downstream_id: str
    upstream_edge_id: str
    downstream_edge_id: str
    min_confidence: float
    total_evidence: int


# Layout constants
LAYER_SPACING_X = 300  # px between layers (left-to-right)
NODE_SPACING_Y = 130   # px between nodes within a layer
CLUSTER_PADDING = 40    # px padding around cluster contents
PIPELINE_NODE_SPACING_X = 350  # px between pipeline overview nodes


# ---------------------------------------------------------------------------
# View data structures
# ---------------------------------------------------------------------------

@dataclass
class ViewNode:
    """A node in a rendered view, ready for frontend consumption."""
    id: str
    name: str
    canonical_type: str
    original_type: str
    platform: Optional[str]
    platform_domain: str
    layer: str
    cluster_id: Optional[str]
    x: float
    y: float
    inferred: bool
    needs_mapping: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "canonicalType": self.canonical_type,
            "originalType": self.original_type,
            "platform": self.platform,
            "platformDomain": self.platform_domain,
            "layer": self.layer,
            "clusterId": self.cluster_id,
            "x": self.x,
            "y": self.y,
            "inferred": self.inferred,
            "needsMapping": self.needs_mapping,
            "metadata": self.metadata,
        }


@dataclass
class ViewEdge:
    """An edge in a rendered view."""
    id: str
    source_id: str
    target_id: str
    canonical_type: str
    original_type: str
    confidence: float
    inferred: bool
    evidence_count: int
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "sourceId": self.source_id,
            "targetId": self.target_id,
            "canonicalType": self.canonical_type,
            "originalType": self.original_type,
            "confidence": self.confidence,
            "inferred": self.inferred,
            "evidenceCount": self.evidence_count,
        }
        if self.evidence_refs:
            d["evidenceRefs"] = self.evidence_refs
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ViewCluster:
    """A visual cluster grouping related nodes."""
    id: str
    label: str
    platform: Optional[str]
    layer: str
    x: float
    y: float
    width: float
    height: float
    node_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "platform": self.platform,
            "layer": self.layer,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "nodeCount": self.node_count,
        }


@dataclass
class LaneMeta:
    """Metadata for a pipeline lane."""
    name: str
    label: str
    order: int
    x: float  # fixed x position for this lane
    node_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "order": self.order,
            "x": self.x,
            "nodeCount": self.node_count,
        }


@dataclass
class OrchestratorOverlay:
    """Orchestrator shown as a control-plane overlay (not in data-plane lanes)."""
    id: str
    name: str
    platform: str
    integration_id: Optional[str]
    x: float
    y: float
    runs_job_ids: List[str]  # job nodes this orchestrator runs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "integrationId": self.integration_id,
            "x": self.x,
            "y": self.y,
            "runsJobIds": self.runs_job_ids,
        }


@dataclass
class RenderedView:
    """A complete rendered view ready for frontend consumption."""
    view_type: str
    nodes: List[ViewNode]
    edges: List[ViewEdge]
    clusters: List[ViewCluster]
    unmapped_nodes: List[Dict[str, Any]]
    stats: Dict[str, Any] = field(default_factory=dict)
    lanes: List[LaneMeta] = field(default_factory=list)
    orchestrators: List[OrchestratorOverlay] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "viewType": self.view_type,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "clusters": [c.to_dict() for c in self.clusters],
            "unmappedNodes": self.unmapped_nodes,
            "stats": self.stats,
        }
        if self.lanes:
            result["lanes"] = [l.to_dict() for l in self.lanes]
        if self.orchestrators:
            result["orchestrators"] = [o.to_dict() for o in self.orchestrators]
        return result


# ---------------------------------------------------------------------------
# Semantic edge type helpers (for Pipeline Overview)
# ---------------------------------------------------------------------------

def _derive_semantic_type(src_lane: str, tgt_lane: str) -> Tuple[str, str]:
    """Derive a semantic edge type and display label from source/target lanes."""
    _LANE_PAIR_MAP = {
        ("ingestion", "warehouse_raw"): ("ingests", "Ingests"),
        ("ingestion", "warehouse_analytics"): ("ingests", "Ingests"),
        ("warehouse_raw", "transformation"): ("feeds", "Feeds"),
        ("transformation", "warehouse_analytics"): ("transforms", "Builds"),
        ("transformation", "warehouse_raw"): ("transforms", "Builds"),
        ("warehouse_analytics", "reporting"): ("serves", "Serves"),
        ("warehouse_raw", "reporting"): ("serves", "Serves"),
    }
    result = _LANE_PAIR_MAP.get((src_lane, tgt_lane))
    if result:
        return result
    # Fallback heuristics
    if src_lane == "transformation" or tgt_lane == "transformation":
        return ("orchestrates", "Orchestrates") if tgt_lane == "transformation" else ("builds", "Builds")
    return ("data_flow", "Data Flow")


# ---------------------------------------------------------------------------
# ViewBuilder
# ---------------------------------------------------------------------------

class ViewBuilder:
    """
    Produces curated, deterministically-laid-out views from the canonical graph.
    """

    def __init__(
        self,
        graph: LineageGraph,
        tool_nodes: Optional[List[Dict[str, Any]]] = None,
    ):
        self.graph = graph
        self.tool_nodes = tool_nodes or []

    def build_pipeline_overview(self) -> RenderedView:
        """
        Build the Pipeline Overview view.

        Shows tool/integration instances as clusters with inter-tool edges.
        Analogous to control_plane.py but with deterministic layout and
        canonical types.

        Algorithm:
        1. Group graph nodes by (platform, integration_id) → service clusters
        2. Also include pipeline tool_nodes not in the engine graph
        3. Create inter-cluster edges from cross-platform data edges
        4. Assign layers by platform domain
        5. Compute deterministic positions
        """
        # Step 1: Group engine nodes by tool identity
        tool_key_to_nodes: Dict[str, List[LineageNode]] = defaultdict(list)
        tool_key_to_info: Dict[str, Dict[str, Any]] = {}

        for node in self.graph.nodes.values():
            platform = node.platform or "unknown"
            int_id = node.integration_id
            tool_key = f"{platform}:{int_id}" if int_id else platform

            tool_key_to_nodes[tool_key].append(node)

            if tool_key not in tool_key_to_info:
                tool_key_to_info[tool_key] = {
                    "platform": platform,
                    "platform_domain": node.platform_domain.value,
                    "integration_id": int_id,
                    "namespace": node.namespace,
                }

        # Step 2: Include tool_nodes from pipeline stack that aren't covered
        covered_integrations = {
            info.get("integration_id")
            for info in tool_key_to_info.values()
            if info.get("integration_id")
        }
        for tn in self.tool_nodes:
            int_id = tn.get("integrationId") or tn.get("integration_id")
            if int_id and int_id not in covered_integrations:
                tool_key = f"{tn.get('toolType', 'unknown')}:{int_id}"
                tool_key_to_info[tool_key] = {
                    "platform": tn.get("toolType", "unknown"),
                    "platform_domain": (tn.get("layer", "WAREHOUSE")).lower(),
                    "integration_id": int_id,
                    "namespace": None,
                }
                tool_key_to_nodes[tool_key] = []  # no engine nodes

        # Step 3: Build service-level ViewNodes
        view_nodes: List[ViewNode] = []
        for tool_key, info in sorted(tool_key_to_info.items()):
            platform = info["platform"]
            domain = info["platform_domain"]
            namespace = info.get("namespace", "")
            node_list = tool_key_to_nodes.get(tool_key, [])

            display_name = platform.title()
            if namespace:
                display_name += f" ({namespace})"

            layer = DOMAIN_TO_LAYER.get(
                PlatformDomain(domain) if domain in [d.value for d in PlatformDomain] else PlatformDomain.OTHER,
                "WAREHOUSE",
            )

            # Aggregate health
            health_summary = {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0}
            for n in node_list:
                status = n.health_status.value
                if status in health_summary:
                    health_summary[status] += 1
                else:
                    health_summary["unknown"] += 1

            view_nodes.append(ViewNode(
                id=tool_key,
                name=display_name,
                canonical_type=CanonicalNodeType.SERVICE.value,
                original_type="service",
                platform=platform,
                platform_domain=domain,
                layer=layer,
                cluster_id=None,
                x=0, y=0,  # computed below
                inferred=False,
                needs_mapping=False,
                metadata={
                    "assetCount": len(node_list),
                    "healthSummary": health_summary,
                    "integrationId": info.get("integration_id"),
                },
            ))

        # Step 4: Build inter-service edges
        node_to_tool: Dict[str, str] = {}
        for tool_key, nodes in tool_key_to_nodes.items():
            for n in nodes:
                node_to_tool[n.id] = tool_key

        edge_counts: Dict[str, int] = defaultdict(int)
        edge_samples: Dict[str, List[str]] = defaultdict(list)

        for edge in self.graph.edges.values():
            if edge.plane == LinePlane.CONTROL:
                continue
            src_tool = node_to_tool.get(edge.source_id)
            tgt_tool = node_to_tool.get(edge.target_id)
            if not src_tool or not tgt_tool or src_tool == tgt_tool:
                continue
            pair = f"{src_tool}→{tgt_tool}"
            edge_counts[pair] += 1
            if len(edge_samples[pair]) < 3:
                src_node = self.graph.nodes.get(edge.source_id)
                if src_node:
                    edge_samples[pair].append(src_node.name)

        view_edges: List[ViewEdge] = []
        for pair, count in edge_counts.items():
            src_tool, tgt_tool = pair.split("→")
            view_edges.append(ViewEdge(
                id=f"po-{pair}",
                source_id=src_tool,
                target_id=tgt_tool,
                canonical_type=CanonicalEdgeType.DERIVES.value,
                original_type="data_flow",
                confidence=1.0,
                inferred=False,
                evidence_count=count,
            ))

        # Step 5: Refine positions to ensure src < tgt ordering
        _refine_service_positions(view_nodes, view_edges)

        # Step 6: Compute deterministic positions
        _assign_positions(view_nodes, PIPELINE_NODE_SPACING_X, NODE_SPACING_Y)

        # Unmapped: none for pipeline overview
        unmapped: List[Dict[str, Any]] = []

        return RenderedView(
            view_type="pipeline_overview",
            nodes=view_nodes,
            edges=view_edges,
            clusters=[],
            unmapped_nodes=unmapped,
            stats={
                "serviceCount": len(view_nodes),
                "flowCount": len(view_edges),
                "totalAssets": sum(
                    n.metadata.get("assetCount", 0) for n in view_nodes
                ),
            },
        )

    def build_lane_pipeline_overview(self) -> RenderedView:
        """
        Build a tool-level lane-based Pipeline Overview.

        Shows ONE box per tool/integration per lane — not individual
        dataset/table nodes.  Orchestrators appear as regular tool nodes
        in the Transformation lane.  Empty lanes are omitted and positions
        are compacted.

        Layout:  Linux + n8n  →  BigQuery (Raw)  →  dbt + Airflow  →  BigQuery (Analytics)

        Algorithm:
        1. Walk graph nodes to discover which tools exist in which lanes
        2. Merge tool_nodes from the pipeline stack (for tools not in graph)
        3. Group by lane, one ViewNode per tool per lane
        4. Build tool-to-tool flow edges (cross-lane data flows)
        5. Skip empty lanes, assign compact x/y positions
        """
        LANE_X_SPACING = 300.0
        TOOL_Y_SPACING = 80.0

        # ── Step 1: Discover tools per lane from engine graph ──────────
        # Key: (lane, tool_identity)  →  { platform, display_name, integration_id, asset_count }
        tool_info: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Track which node.id maps to which tool_key (for edge aggregation)
        node_to_tool: Dict[str, Tuple[str, str]] = {}

        # Also collect graph nodes per tool key for enrichment
        tool_key_to_graph_nodes: Dict[Tuple[str, str], List[LineageNode]] = defaultdict(list)

        for node in self.graph.nodes.values():
            ct = node.canonical_type or map_node_type(node).value
            dataset_zone = classify_dataset_zone(node) if ct == "dataset" else None
            actor_cap = classify_actor_capability(node) if ct in ("service", "job", "system") else None

            # Determine which lane this node would fall in
            if actor_cap == ActorCapability.ORCHESTRATION:
                lane = PipelineLane.TRANSFORMATION.value
            elif ct == "system" or actor_cap == ActorCapability.INFRA:
                lane = PipelineLane.INGESTION.value
            else:
                lane = assign_lane(node, ct, dataset_zone, actor_cap)

            # Tool identity: group by platform (+ integration_id if present)
            platform = (node.platform or "unknown").lower()
            int_id = node.integration_id or ""
            tool_id = f"{platform}:{int_id}" if int_id else platform
            tk: Tuple[str, str] = (lane, tool_id)

            node_to_tool[node.id] = tk
            tool_key_to_graph_nodes[tk].append(node)

            if tk not in tool_info:
                # Determine display name
                display = platform.title()
                if actor_cap == ActorCapability.ORCHESTRATION:
                    display = node.name if node.name else platform.title()
                tool_info[tk] = {
                    "platform": platform,
                    "display_name": display,
                    "integration_id": int_id or None,
                    "asset_count": 0,
                    "is_orchestrator": actor_cap == ActorCapability.ORCHESTRATION,
                    "is_infra": actor_cap == ActorCapability.INFRA or ct == "system",
                }
            tool_info[tk]["asset_count"] += 1

        # ── Step 2: Merge pipeline tool_nodes not already covered ─────
        covered_integration_ids: Set[str] = {
            info["integration_id"]
            for info in tool_info.values()
            if info["integration_id"]
        }

        # Track which platforms already exist per lane to avoid duplicates
        platform_per_lane: Dict[Tuple[str, str], Tuple[str, str]] = {}
        for tk, info in tool_info.items():
            lane_plat_key = (tk[0], info["platform"])
            if lane_plat_key not in platform_per_lane:
                platform_per_lane[lane_plat_key] = tk

        for tn in self.tool_nodes:
            int_id = tn.get("integrationId") or tn.get("integration_id") or ""
            if int_id and int_id in covered_integration_ids:
                continue

            tool_type = (tn.get("toolType") or tn.get("tool_type") or "unknown").lower()

            # Determine lane
            if tool_type in INFRA_PLATFORMS:
                lane = PipelineLane.INGESTION.value
            elif tool_type in INGESTION_PLATFORMS:
                lane = PipelineLane.INGESTION.value
            elif tool_type in TRANSFORM_PLATFORMS:
                lane = PipelineLane.TRANSFORMATION.value
            elif tool_type in ORCHESTRATION_PLATFORMS:
                lane = PipelineLane.TRANSFORMATION.value
            elif tool_type in REPORTING_PLATFORMS:
                lane = PipelineLane.REPORTING.value
            elif tool_type in WAREHOUSE_PLATFORMS:
                lane = PipelineLane.WAREHOUSE_RAW.value
            else:
                lane = PipelineLane.WAREHOUSE_RAW.value

            # If same platform already exists in this lane, merge instead of duplicate
            existing_key = platform_per_lane.get((lane, tool_type))
            if existing_key and existing_key in tool_info:
                existing = tool_info[existing_key]
                if not existing["integration_id"] and int_id:
                    existing["integration_id"] = int_id
                if int_id:
                    covered_integration_ids.add(int_id)
                continue

            tool_id = f"{tool_type}:{int_id}" if int_id else tool_type
            tk = (lane, tool_id)
            if tk not in tool_info:
                display = tn.get("name") or tool_type.title()
                tool_info[tk] = {
                    "platform": tool_type,
                    "display_name": display,
                    "integration_id": int_id or None,
                    "asset_count": 0,
                    "is_orchestrator": tool_type in ORCHESTRATION_PLATFORMS,
                    "is_infra": tool_type in INFRA_PLATFORMS,
                    "from_pipeline_stack": True,
                }
                platform_per_lane[(lane, tool_type)] = tk
                if int_id:
                    covered_integration_ids.add(int_id)

        # Warehouse lanes: if a warehouse appears in both raw and analytics,
        # keep both.  If it only appears in raw (all nodes classified raw),
        # check if there are analytics-zone datasets and split.
        # (No change needed — assign_lane already handles this.)

        # ── Step 3: Build one ViewNode per tool per lane ──────────────
        view_nodes: List[ViewNode] = []

        for (lane, tool_id), info in sorted(tool_info.items(), key=lambda x: (LANE_ORDER.get(x[0][0], 99), x[0][1])):
            platform = info["platform"]
            node_view_id = f"tool:{lane}:{tool_id}"

            # Enrich: aggregate health, jobs, sub-nodes from graph nodes
            graph_nodes = tool_key_to_graph_nodes.get((lane, tool_id), [])
            health_summary = {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0, "stale": 0}
            job_count = 0
            last_run_ts: Optional[str] = None
            last_run_dt = None
            sub_nodes: List[Dict[str, Any]] = []

            for gn in graph_nodes:
                # Health aggregation
                status = gn.health_status.value if hasattr(gn, "health_status") else "unknown"
                if status in health_summary:
                    health_summary[status] += 1
                else:
                    health_summary["unknown"] += 1
                # Job count
                gn_ct = gn.canonical_type or ""
                if gn_ct == "job":
                    job_count += 1
                # Last run timestamp (most recent observed_at)
                if hasattr(gn, "observed_at") and gn.observed_at:
                    if last_run_dt is None or gn.observed_at > last_run_dt:
                        last_run_dt = gn.observed_at
                        last_run_ts = gn.observed_at.isoformat()
                # Sub-nodes (cap at 20)
                if len(sub_nodes) < 20:
                    sub_nodes.append({
                        "id": gn.id,
                        "name": gn.name,
                        "type": gn_ct or "unknown",
                        "fqn": gn.fqn or gn.name,
                    })

            # Coverage gaps
            coverage_gaps: List[str] = []
            if info["asset_count"] == 0 and info.get("from_pipeline_stack"):
                coverage_gaps.append("no_data_extracted")
            # Check for sparse lineage: tool has assets but very few edges
            tool_edge_count = 0
            for edge in self.graph.edges.values():
                if edge.plane == LinePlane.CONTROL:
                    continue
                src_tk = node_to_tool.get(edge.source_id)
                tgt_tk = node_to_tool.get(edge.target_id)
                if src_tk == (lane, tool_id) or tgt_tk == (lane, tool_id):
                    tool_edge_count += 1
            if info["asset_count"] > 5 and tool_edge_count < 2:
                coverage_gaps.append("sparse_lineage")

            view_nodes.append(ViewNode(
                id=node_view_id,
                name=info["display_name"],
                canonical_type="service",
                original_type="service",
                platform=platform,
                platform_domain="orchestration" if info.get("is_orchestrator") else (
                    "infrastructure" if info.get("is_infra") else "other"
                ),
                layer=lane,
                cluster_id=lane,
                x=0, y=0,  # computed below
                inferred=False,
                needs_mapping=False,
                metadata={
                    "lane": lane,
                    "assetCount": info["asset_count"],
                    "integrationId": info["integration_id"],
                    "isOrchestrator": info.get("is_orchestrator", False),
                    "isInfra": info.get("is_infra", False),
                    "fromPipelineStack": info.get("from_pipeline_stack", False),
                    "healthSummary": health_summary,
                    "jobCount": job_count,
                    "lastRunTs": last_run_ts,
                    "coverageGaps": coverage_gaps,
                    "subNodes": sub_nodes,
                    "totalSubNodeCount": len(graph_nodes),
                },
            ))

        # ── Step 4: Build tool-to-tool flow edges ─────────────────────
        # Aggregate graph edges into cross-tool flows
        tool_edge_counts: Dict[str, int] = defaultdict(int)  # "src_tk→tgt_tk" → count

        for edge in self.graph.edges.values():
            if edge.plane == LinePlane.CONTROL:
                continue
            src_tk = node_to_tool.get(edge.source_id)
            tgt_tk = node_to_tool.get(edge.target_id)
            if not src_tk or not tgt_tk or src_tk == tgt_tk:
                continue
            pair_key = f"tool:{src_tk[0]}:{src_tk[1]}→tool:{tgt_tk[0]}:{tgt_tk[1]}"
            tool_edge_counts[pair_key] += 1

        # Build a node-id-to-lane lookup for semantic type derivation
        view_node_lane: Dict[str, str] = {}
        for vn in view_nodes:
            view_node_lane[vn.id] = vn.layer

        view_edges: List[ViewEdge] = []
        for pair, count in tool_edge_counts.items():
            src_id, tgt_id = pair.split("→")
            src_lane = view_node_lane.get(src_id, "")
            tgt_lane = view_node_lane.get(tgt_id, "")
            semantic_type, semantic_label = _derive_semantic_type(src_lane, tgt_lane)
            view_edges.append(ViewEdge(
                id=f"flow-{pair}",
                source_id=src_id,
                target_id=tgt_id,
                canonical_type="derives",
                original_type="data_flow",
                confidence=1.0,
                inferred=False,
                evidence_count=count,
                metadata={
                    "semanticType": semantic_type,
                    "label": semantic_label,
                    "dataFlowCount": count,
                    "srcLane": src_lane,
                    "tgtLane": tgt_lane,
                },
            ))

        # ── Step 4b: Compute topological order per tool ─────────────────
        # Tools receiving data from earlier lanes appear first within their lane
        tool_topo_order: Dict[str, float] = {}
        for (lane, tool_id) in tool_info:
            node_view_id = f"tool:{lane}:{tool_id}"
            upstream_lane_orders: List[float] = []
            for pair_key in tool_edge_counts:
                src_id, tgt_id = pair_key.split("→")
                if tgt_id == node_view_id:
                    # Extract source lane order from the source tool's lane
                    src_lane = src_id.split(":")[1] if src_id.count(":") >= 2 else ""
                    upstream_lane_orders.append(LANE_ORDER.get(src_lane, 99))
            if upstream_lane_orders:
                tool_topo_order[node_view_id] = sum(upstream_lane_orders) / len(upstream_lane_orders)
            else:
                tool_topo_order[node_view_id] = -1  # source tools first

        # ── Step 5: Skip empty lanes, compact positions ───────────────
        by_lane: Dict[str, List[ViewNode]] = defaultdict(list)
        for vn in view_nodes:
            by_lane[vn.layer].append(vn)

        # Sort within each lane: orchestrators/infra last, then by pipeline flow order, then alphabetical
        for lane_name in by_lane:
            by_lane[lane_name].sort(key=lambda n: (
                1 if n.metadata.get("isOrchestrator") else 0,
                1 if n.metadata.get("isInfra") else 0,
                tool_topo_order.get(n.id, 0),
                n.name,
            ))

        # Only include lanes that have tools
        active_lanes = [
            l.value for l in PipelineLane
            if by_lane.get(l.value)
        ]

        # Assign compact positions (skip empty lanes)
        lane_x_map: Dict[str, float] = {}
        for idx, lane_name in enumerate(active_lanes):
            lane_x_map[lane_name] = idx * LANE_X_SPACING

        for lane_name, lane_nodes in by_lane.items():
            x = lane_x_map.get(lane_name, 0)
            for idx, vn in enumerate(lane_nodes):
                vn.x = x
                vn.y = idx * TOOL_Y_SPACING

        # ── Step 6: Build lane metadata (active lanes only) ───────────
        lane_labels = {
            PipelineLane.INGESTION.value: "Ingestion",
            PipelineLane.WAREHOUSE_RAW.value: "Warehouse (Raw)",
            PipelineLane.TRANSFORMATION.value: "Transformation",
            PipelineLane.WAREHOUSE_ANALYTICS.value: "Warehouse (Analytics)",
            PipelineLane.REPORTING.value: "Reporting",
        }

        lanes: List[LaneMeta] = []
        for lane_name in active_lanes:
            lanes.append(LaneMeta(
                name=lane_name,
                label=lane_labels.get(lane_name, lane_name),
                order=LANE_ORDER.get(lane_name, 99),
                x=lane_x_map.get(lane_name, 0),
                node_count=len(by_lane.get(lane_name, [])),
            ))

        # Stats
        agg_health = {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0, "stale": 0}
        total_assets = 0
        coverage_gap_count = 0
        for n in view_nodes:
            hs = n.metadata.get("healthSummary", {})
            for k in agg_health:
                agg_health[k] += hs.get(k, 0)
            total_assets += n.metadata.get("assetCount", 0)
            if n.metadata.get("coverageGaps"):
                coverage_gap_count += 1

        stats = {
            "totalNodes": len(view_nodes),
            "totalEdges": len(view_edges),
            "orchestratorCount": sum(
                1 for n in view_nodes if n.metadata.get("isOrchestrator")
            ),
            "laneDistribution": {
                lane_name: len(by_lane.get(lane_name, []))
                for lane_name in active_lanes
            },
            "opsSummary": {
                "totalTools": len(view_nodes),
                "totalAssets": total_assets,
                "healthDistribution": agg_health,
                "coverageGapCount": coverage_gap_count,
            },
        }

        return RenderedView(
            view_type="lane_pipeline_overview",
            nodes=view_nodes,
            edges=view_edges,
            clusters=[],
            unmapped_nodes=[],
            stats=stats,
            lanes=lanes,
            orchestrators=[],  # no separate overlays — orchestrators are in the lanes
        )

    def build_data_plane(self) -> RenderedView:
        """
        Build the Data Plane view.

        Shows dataset-to-dataset derivation chains with optional job and
        semantic nodes. Clusters by (database, schema).

        Algorithm:
        1. Select nodes with canonical_type in (DATASET, SEMANTIC, JOB)
        2. Select relevant edges
        3. Deduplicate Airflow table refs by FQN
        4. Cluster by (database, schema)
        5. Compute deterministic layered layout via topological sort
        """
        # Step 1: Select relevant nodes (datasets + semantic only, no jobs)
        selected_types = {
            CanonicalNodeType.DATASET.value,
            CanonicalNodeType.SEMANTIC.value,
        }

        # Build bypass edges for JOB nodes: when dataset → job → dataset
        # exists, create a direct dataset → dataset derives edge so the
        # data plane stays clean.  Carry confidence and evidence from the
        # original edges for provenance.
        job_bypass_edges: List[_BypassInfo] = []
        for node in self.graph.nodes.values():
            ct = node.canonical_type or map_node_type(node).value
            if ct != CanonicalNodeType.JOB.value:
                continue
            upstream_pairs: List[Tuple[str, LineageEdge]] = []
            downstream_pairs: List[Tuple[str, LineageEdge]] = []
            for edge in self.graph.edges.values():
                if edge.target_id == node.id:
                    src = self.graph.nodes.get(edge.source_id)
                    if src:
                        src_ct = src.canonical_type or map_node_type(src).value
                        if src_ct in selected_types:
                            upstream_pairs.append((src.id, edge))
                if edge.source_id == node.id:
                    tgt = self.graph.nodes.get(edge.target_id)
                    if tgt:
                        tgt_ct = tgt.canonical_type or map_node_type(tgt).value
                        if tgt_ct in selected_types:
                            downstream_pairs.append((tgt.id, edge))
            for up_id, up_edge in upstream_pairs:
                for down_id, down_edge in downstream_pairs:
                    if up_id != down_id:
                        job_bypass_edges.append(_BypassInfo(
                            upstream_id=up_id,
                            downstream_id=down_id,
                            upstream_edge_id=up_edge.id,
                            downstream_edge_id=down_edge.id,
                            min_confidence=min(up_edge.confidence, down_edge.confidence),
                            total_evidence=len(up_edge.evidence) + len(down_edge.evidence),
                        ))

        # Step 2: Safety-net dedup for tool-platform table nodes.
        # The resolver should catch these; this is a warning-only fallback.
        _DEDUP_PLATFORMS = {"airflow", "fivetran"}
        warehouse_fqn_map: Dict[str, str] = {}  # FQN → node ID
        airflow_remap: Dict[str, str] = {}  # duplicate node ID → warehouse node ID

        for node in self.graph.nodes.values():
            ct = node.canonical_type or map_node_type(node).value
            if ct != CanonicalNodeType.DATASET.value:
                continue
            nt = node.node_type.value
            if nt not in ("table", "view", "materialized_view", "source"):
                continue
            fqn = node.fqn
            if not fqn:
                continue
            if node.platform in _DEDUP_PLATFORMS:
                if fqn in warehouse_fqn_map:
                    logger.warning(
                        "[ViewBuilder] Resolver missed dedup: %s (platform=%s, fqn=%s) "
                        "duplicates %s — remapping as safety net",
                        node.id, node.platform, fqn, warehouse_fqn_map[fqn],
                    )
                    airflow_remap[node.id] = warehouse_fqn_map[fqn]
            elif fqn not in warehouse_fqn_map:
                warehouse_fqn_map[fqn] = node.id

        # Step 2b: Deduplicate inferred (bridge) nodes by FQN
        # If the reconciler created an inferred node for an asset that was
        # already discovered by an extractor, drop the inferred duplicate
        # and remap its edges to the real node.
        real_fqn_map: Dict[str, str] = {}  # FQN → real node ID
        inferred_remap: Dict[str, str] = {}  # inferred node ID → real node ID

        for node in self.graph.nodes.values():
            if not node.fqn or node.inferred:
                continue
            if node.fqn not in real_fqn_map:
                real_fqn_map[node.fqn] = node.id

        for node in self.graph.nodes.values():
            if not node.fqn or not node.inferred:
                continue
            real_id = real_fqn_map.get(node.fqn)
            if real_id and real_id != node.id:
                inferred_remap[node.id] = real_id

        # Step 3: Build node list
        view_nodes: List[ViewNode] = []
        node_id_set: Set[str] = set()
        unmapped: List[Dict[str, Any]] = []

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.fqn):
            if node.id in airflow_remap or node.id in inferred_remap:
                continue

            ct = node.canonical_type or map_node_type(node).value
            if ct not in selected_types:
                continue

            layer = get_layer(node)
            nm = is_needs_mapping(node)

            # Cluster by database.schema for datasets, platform for semantics
            if ct == CanonicalNodeType.DATASET.value:
                db = node.database or ""
                sch = node.schema or ""
                cluster_id = f"{db}.{sch}" if db or sch else node.platform or "default"
            elif ct == CanonicalNodeType.SEMANTIC.value:
                cluster_id = node.platform or "reporting"
            else:
                cluster_id = node.platform or "jobs"

            view_nodes.append(ViewNode(
                id=node.id,
                name=node.name,
                canonical_type=ct,
                original_type=node.node_type.value,
                platform=node.platform,
                platform_domain=node.platform_domain.value,
                layer=layer,
                cluster_id=cluster_id,
                x=0, y=0,  # computed below
                inferred=node.inferred,
                needs_mapping=nm,
                metadata={
                    "fqn": node.fqn,
                    "database": node.database,
                    "schema": node.schema,
                    "description": node.description,
                    "owner": node.owner,
                    "criticality": node.criticality,
                    "rowCount": node.row_count,
                    "columnCount": len(node.columns) if node.columns else 0,
                    "upstreamCount": node.upstream_count,
                    "downstreamCount": node.downstream_count,
                    "integrationId": node.integration_id,
                    "dbtResourceType": node.raw_metadata.get("dbt_resource_type"),
                    "healthStatus": node.health_status.value,
                    "tags": node.tags,
                    "platforms": node.raw_metadata.get("discovered_platforms"),
                    "materialization": node.raw_metadata.get("materialized"),
                },
            ))
            node_id_set.add(node.id)

            if nm:
                unmapped.append({
                    "id": node.id,
                    "name": node.name,
                    "fqn": node.fqn,
                    "originalType": node.node_type.value,
                    "platform": node.platform,
                    "sources": node.sources,
                })

        # Step 4: Build edges (remap airflow refs and inferred duplicates)
        view_edges: List[ViewEdge] = []
        seen_edge_pairs: Set[str] = set()

        for edge in self.graph.edges.values():
            src_id = airflow_remap.get(edge.source_id, edge.source_id)
            tgt_id = airflow_remap.get(edge.target_id, edge.target_id)
            src_id = inferred_remap.get(src_id, src_id)
            tgt_id = inferred_remap.get(tgt_id, tgt_id)

            if src_id not in node_id_set or tgt_id not in node_id_set:
                continue
            if src_id == tgt_id:
                continue

            pair = f"{src_id}→{tgt_id}"
            if pair in seen_edge_pairs:
                continue
            seen_edge_pairs.add(pair)

            canonical_et = edge.canonical_edge_type or "derives"

            view_edges.append(ViewEdge(
                id=edge.id,
                source_id=src_id,
                target_id=tgt_id,
                canonical_type=canonical_et,
                original_type=edge.edge_type.value,
                confidence=edge.confidence,
                inferred=edge.inferred,
                evidence_count=len(edge.evidence),
            ))

        # Step 4b: Add bypass edges for job nodes (dataset → job → dataset).
        # Confidence = min(source edges) capped at 0.8; evidence refs point
        # to the two original edges for provenance.
        for bypass in job_bypass_edges:
            final_src = airflow_remap.get(bypass.upstream_id, bypass.upstream_id)
            final_tgt = airflow_remap.get(bypass.downstream_id, bypass.downstream_id)
            final_src = inferred_remap.get(final_src, final_src)
            final_tgt = inferred_remap.get(final_tgt, final_tgt)
            if final_src not in node_id_set or final_tgt not in node_id_set:
                continue
            if final_src == final_tgt:
                continue
            pair = f"{final_src}→{final_tgt}"
            if pair in seen_edge_pairs:
                continue
            seen_edge_pairs.add(pair)
            confidence = min(bypass.min_confidence, 0.8)
            view_edges.append(ViewEdge(
                id=f"bypass-{final_src}-{final_tgt}",
                source_id=final_src,
                target_id=final_tgt,
                canonical_type="derives",
                original_type="job_bypass",
                confidence=confidence,
                inferred=True,
                evidence_count=bypass.total_evidence,
                evidence_refs=[bypass.upstream_edge_id, bypass.downstream_edge_id],
            ))

        # Step 4c: Transitive reduction — remove shortcut edges.
        # BigQuery job history resolves view chains to underlying base tables,
        # creating edges that bypass intermediate views (e.g., raw.customers →
        # int_customer_orders instead of raw.customers → stg_customers →
        # int_customer_orders).  Remove an edge A→C when a 2-hop path A→B→C
        # already exists, preferring the multi-hop path.
        adj: Dict[str, Set[str]] = defaultdict(set)
        for e in view_edges:
            adj[e.source_id].add(e.target_id)

        reduced_edges: List[ViewEdge] = []
        for edge in view_edges:
            has_alt = any(
                edge.target_id in adj[mid]
                for mid in adj[edge.source_id]
                if mid != edge.target_id
            )
            if has_alt:
                logger.debug(
                    "[ViewBuilder] Removed transitive edge: %s → %s",
                    edge.source_id, edge.target_id,
                )
            else:
                reduced_edges.append(edge)

        if len(reduced_edges) < len(view_edges):
            logger.info(
                "[ViewBuilder] Transitive reduction: %d → %d edges (removed %d shortcuts)",
                len(view_edges), len(reduced_edges), len(view_edges) - len(reduced_edges),
            )
        view_edges = reduced_edges

        # Step 5: Compute deterministic layout (semantic layers + topological refinement)
        positions = _semantic_topological_layout(view_nodes, view_edges, self.graph)
        for vn in view_nodes:
            pos = positions.get(vn.id, (0.0, 0.0))
            vn.x = pos[0]
            vn.y = pos[1]

        # Step 6: Build clusters from node positions
        clusters = _build_clusters_from_nodes(view_nodes)

        return RenderedView(
            view_type="data_plane",
            nodes=view_nodes,
            edges=view_edges,
            clusters=clusters,
            unmapped_nodes=unmapped,
            stats={
                "datasetCount": sum(
                    1 for n in view_nodes
                    if n.canonical_type == CanonicalNodeType.DATASET.value
                ),
                "semanticCount": sum(
                    1 for n in view_nodes
                    if n.canonical_type == CanonicalNodeType.SEMANTIC.value
                ),
                "edgeCount": len(view_edges),
                "inferredNodeCount": sum(1 for n in view_nodes if n.inferred),
                "inferredEdgeCount": sum(1 for e in view_edges if e.inferred),
                "needsMappingCount": len(unmapped),
                "clusterCount": len(clusters),
                "airflowDeduped": len(airflow_remap),
                "inferredDeduped": len(inferred_remap),
            },
        )


# ---------------------------------------------------------------------------
# Layout algorithms
# ---------------------------------------------------------------------------

def _assign_positions(
    nodes: List[ViewNode],
    x_spacing: float,
    y_spacing: float,
) -> None:
    """Assign x,y positions based on layer ordering."""
    # Group by layer
    by_layer: Dict[str, List[ViewNode]] = defaultdict(list)
    for n in nodes:
        by_layer[n.layer].append(n)

    # Sort layers by LAYER_ORDER
    sorted_layers = sorted(by_layer.keys(), key=lambda l: get_layer_order(l))

    for layer_idx, layer in enumerate(sorted_layers):
        layer_nodes = sorted(by_layer[layer], key=lambda n: n.name)
        for node_idx, node in enumerate(layer_nodes):
            node.x = layer_idx * x_spacing
            node.y = node_idx * y_spacing


def _refine_service_positions(
    nodes: List[ViewNode],
    edges: List[ViewEdge],
) -> None:
    """Ensure source.layer_order < target.layer_order for service edges."""
    # Build lookup
    node_map = {n.id: n for n in nodes}

    changed = True
    iterations = 0
    while changed and iterations < 10:
        changed = False
        iterations += 1
        for edge in edges:
            src = node_map.get(edge.source_id)
            tgt = node_map.get(edge.target_id)
            if not src or not tgt:
                continue
            src_order = get_layer_order(src.layer)
            tgt_order = get_layer_order(tgt.layer)
            if src_order >= tgt_order:
                # Push target to next layer position
                new_order = src_order + 1
                # Find a layer name with this order, or keep current
                for layer_name, order in LAYER_ORDER.items():
                    if order == new_order:
                        tgt.layer = layer_name
                        changed = True
                        break


def _topological_layout(
    nodes: List[ViewNode],
    edges: List[ViewEdge],
) -> Dict[str, Tuple[float, float]]:
    """
    Compute deterministic layered layout using topological sort.

    Algorithm:
    1. Build adjacency lists
    2. Compute longest-path layer assignment (roots at layer 0)
    3. Within each layer, sort alphabetically by (cluster_id, name)
    4. Convert to pixel positions
    """
    if not nodes:
        return {}

    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}

    # Build adjacency
    successors: Dict[str, List[str]] = defaultdict(list)
    predecessors: Dict[str, List[str]] = defaultdict(list)
    in_degree: Dict[str, int] = {n.id: 0 for n in nodes}

    for e in edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            successors[e.source_id].append(e.target_id)
            predecessors[e.target_id].append(e.source_id)
            in_degree[e.target_id] = in_degree.get(e.target_id, 0) + 1

    # Longest-path layer assignment (topological order)
    layer_of: Dict[str, int] = {}

    # Kahn's algorithm for topological sort
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    # Sort roots for determinism
    queue.sort(key=lambda nid: (node_map[nid].cluster_id or "", node_map[nid].name))

    for nid in queue:
        layer_of[nid] = 0

    visited_order: List[str] = []
    head = 0
    while head < len(queue):
        nid = queue[head]
        head += 1
        visited_order.append(nid)

        for succ in sorted(successors[nid]):
            if succ not in in_degree:
                continue
            # Longest path: layer = max of all predecessors + 1
            candidate_layer = layer_of.get(nid, 0) + 1
            layer_of[succ] = max(layer_of.get(succ, 0), candidate_layer)
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # Handle nodes not reached (cycles or disconnected)
    for n in nodes:
        if n.id not in layer_of:
            # Assign to layer based on domain hint
            layer_of[n.id] = get_layer_order(n.layer)

    # Group by layer, sort within layer
    by_layer: Dict[int, List[str]] = defaultdict(list)
    for nid, layer in layer_of.items():
        by_layer[layer].append(nid)

    # Sort within each layer by (cluster_id, name) for determinism
    for layer in by_layer:
        by_layer[layer].sort(
            key=lambda nid: (node_map[nid].cluster_id or "", node_map[nid].name)
        )

    # Convert to pixel positions
    positions: Dict[str, Tuple[float, float]] = {}
    for layer_idx, layer in enumerate(sorted(by_layer.keys())):
        nids = by_layer[layer]
        for node_idx, nid in enumerate(nids):
            x = layer_idx * LAYER_SPACING_X
            y = node_idx * NODE_SPACING_Y
            positions[nid] = (x, y)

    return positions


def _semantic_topological_layout(
    nodes: List[ViewNode],
    edges: List[ViewEdge],
    graph: LineageGraph,
) -> Dict[str, Tuple[float, float]]:
    """
    Compute layered layout using semantic layer assignment + topological refinement.

    Algorithm:
    1. Assign each node a semantic layer (0-6) based on metadata
    2. If all same layer (no diversity), fall back to pure topological sort
    3. Enforce edge consistency: source layer < target layer
    4. Within each layer, sort by (cluster_id, topo_order, name)
    5. Convert to pixel positions
    """
    if not nodes:
        return {}

    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}

    # Build out-degree for downstream detection
    out_degree: Dict[str, int] = {n.id: 0 for n in nodes}
    for e in edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            out_degree[e.source_id] = out_degree.get(e.source_id, 0) + 1

    # Step 1: Assign semantic layer to each node
    semantic_layer: Dict[str, int] = {}
    for vn in nodes:
        graph_node = graph.nodes.get(vn.id)
        if graph_node:
            ct = graph_node.canonical_type or map_node_type(graph_node).value
            has_downstream = out_degree.get(vn.id, 0) > 0
            semantic_layer[vn.id] = classify_data_plane_layer(
                graph_node, ct, has_downstream_data_edges=has_downstream,
            )
        else:
            # ViewNode without a graph node — derive from metadata
            semantic_layer[vn.id] = 6 if vn.canonical_type == "semantic" else 1

    # Check diversity — fall back to pure topo if all same layer
    if len(set(semantic_layer.values())) <= 1:
        return _topological_layout(nodes, edges)

    # Step 2: Enforce edge consistency (source layer < target layer)
    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        for e in edges:
            if e.source_id in semantic_layer and e.target_id in semantic_layer:
                if semantic_layer[e.source_id] >= semantic_layer[e.target_id]:
                    semantic_layer[e.target_id] = semantic_layer[e.source_id] + 1
                    changed = True

    # Step 3: Compute topo order for intra-layer sorting
    topo_order = _compute_topo_order(nodes, edges)

    # Step 4: Group by layer, sort within
    by_layer: Dict[int, List[str]] = defaultdict(list)
    for nid, layer in semantic_layer.items():
        by_layer[layer].append(nid)

    for layer in by_layer:
        by_layer[layer].sort(key=lambda nid: (
            node_map[nid].cluster_id or "",
            topo_order.get(nid, 999),
            node_map[nid].name,
        ))

    # Step 5: Pixel positions
    positions: Dict[str, Tuple[float, float]] = {}
    for layer_idx, layer in enumerate(sorted(by_layer.keys())):
        for node_idx, nid in enumerate(by_layer[layer]):
            positions[nid] = (layer_idx * LAYER_SPACING_X, node_idx * NODE_SPACING_Y)

    return positions


def _compute_topo_order(
    nodes: List[ViewNode],
    edges: List[ViewEdge],
) -> Dict[str, int]:
    """Compute a topological ordering index for each node (Kahn's algorithm)."""
    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}
    in_degree: Dict[str, int] = {n.id: 0 for n in nodes}
    successors: Dict[str, List[str]] = defaultdict(list)

    for e in edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            successors[e.source_id].append(e.target_id)
            in_degree[e.target_id] = in_degree.get(e.target_id, 0) + 1

    queue = sorted(
        [nid for nid, deg in in_degree.items() if deg == 0],
        key=lambda nid: (node_map[nid].cluster_id or "", node_map[nid].name),
    )

    order: Dict[str, int] = {}
    idx = 0
    head = 0
    while head < len(queue):
        nid = queue[head]
        head += 1
        order[nid] = idx
        idx += 1
        for succ in sorted(successors[nid]):
            if succ not in in_degree:
                continue
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # Assign unvisited nodes (cycles) a high order
    for n in nodes:
        if n.id not in order:
            order[n.id] = idx
            idx += 1

    return order


def _build_clusters_from_nodes(nodes: List[ViewNode]) -> List[ViewCluster]:
    """Build visual clusters from node positions and cluster_ids."""
    by_cluster: Dict[str, List[ViewNode]] = defaultdict(list)
    for n in nodes:
        if n.cluster_id:
            by_cluster[n.cluster_id].append(n)

    clusters: List[ViewCluster] = []
    for cluster_id, cluster_nodes in sorted(by_cluster.items()):
        if len(cluster_nodes) < 2:
            continue  # don't cluster singletons

        min_x = min(n.x for n in cluster_nodes)
        max_x = max(n.x for n in cluster_nodes)
        min_y = min(n.y for n in cluster_nodes)
        max_y = max(n.y for n in cluster_nodes)

        platform = cluster_nodes[0].platform
        layer = cluster_nodes[0].layer

        clusters.append(ViewCluster(
            id=cluster_id,
            label=cluster_id,
            platform=platform,
            layer=layer,
            x=min_x - CLUSTER_PADDING,
            y=min_y - CLUSTER_PADDING,
            width=(max_x - min_x) + 2 * CLUSTER_PADDING + 170,  # node width
            height=(max_y - min_y) + 2 * CLUSTER_PADDING + 65,  # node height
            node_count=len(cluster_nodes),
        ))

    return clusters
