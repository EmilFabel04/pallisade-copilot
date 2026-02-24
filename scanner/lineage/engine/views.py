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
    classify_dataset_zone,
)

logger = logging.getLogger(__name__)

# Layout constants
LAYER_SPACING_X = 300  # px between layers (left-to-right)
NODE_SPACING_Y = 100   # px between nodes within a layer
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sourceId": self.source_id,
            "targetId": self.target_id,
            "canonicalType": self.canonical_type,
            "originalType": self.original_type,
            "confidence": self.confidence,
            "inferred": self.inferred,
            "evidenceCount": self.evidence_count,
        }


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
        Build a lane-based Pipeline Overview view.

        Unlike build_pipeline_overview() which groups by tool, this view
        renders individual nodes (actors + key datasets) placed into fixed
        lanes for a readable left-to-right data flow:

          ingestion → warehouse_raw → transformation → warehouse_analytics → reporting

        Orchestration nodes are shown as overlays (not in the data-plane lanes).

        Algorithm:
        1. Classify every node: dataset_zone / actor_capability
        2. Assign each node to a lane
        3. Separate orchestrator nodes into overlay
        4. Build edges (data-plane only, skip control-plane)
        5. Compute deterministic x/y positions by lane
        6. Build lane metadata
        """
        # Lane layout constants
        LANE_X_SPACING = 350.0
        LANE_NODE_Y_SPACING = 90.0
        ORCHESTRATOR_Y_OFFSET = -120.0  # above the main lanes

        # Step 1: Classify and assign lanes to all nodes
        view_nodes: List[ViewNode] = []
        orchestrator_nodes: List[LineageNode] = []
        node_id_set: Set[str] = set()

        # Track which jobs are run by orchestrators (for overlay)
        orchestrator_runs: Dict[str, List[str]] = defaultdict(list)  # orch_id → [job_ids]
        for edge in self.graph.edges.values():
            if edge.canonical_edge_type == "runs":
                orchestrator_runs[edge.source_id].append(edge.target_id)

        for node in self.graph.nodes.values():
            ct = node.canonical_type or map_node_type(node).value

            # Classify
            dataset_zone = classify_dataset_zone(node) if ct == "dataset" else None
            actor_cap = classify_actor_capability(node) if ct in ("service", "job", "system") else None

            # Orchestration nodes → overlay, not data-plane lane
            if actor_cap == ActorCapability.ORCHESTRATION:
                orchestrator_nodes.append(node)
                continue

            # Skip system/infra nodes from overview (they're not data-plane)
            if ct == "system":
                continue
            if actor_cap == ActorCapability.INFRA:
                continue

            lane = assign_lane(node, ct, dataset_zone, actor_cap)

            # Build badges
            badges: Dict[str, Any] = {}
            if dataset_zone:
                badges["zone"] = dataset_zone.value
            if actor_cap:
                badges["capability"] = actor_cap.value
            materialization = node.node_type.value if ct == "dataset" else None
            if materialization:
                badges["materialization"] = materialization
            # Producer: which adapter/tool produced this node
            if node.sources:
                badges["producer"] = node.sources[0]

            view_nodes.append(ViewNode(
                id=node.id,
                name=node.name,
                canonical_type=ct,
                original_type=node.node_type.value,
                platform=node.platform,
                platform_domain=node.platform_domain.value,
                layer=lane,
                cluster_id=lane,  # cluster by lane for grouping
                x=0, y=0,  # computed below
                inferred=node.inferred,
                needs_mapping=is_needs_mapping(node),
                metadata={
                    "lane": lane,
                    "badges": badges,
                    "fqn": node.fqn,
                    "database": node.database,
                    "schema": node.schema,
                    "integrationId": node.integration_id,
                    "confidence": getattr(node, "confidence", 1.0),
                },
            ))
            node_id_set.add(node.id)

        # Step 1b: Include pipeline tool_nodes not covered by engine graph nodes
        covered_integrations: Set[str] = set()
        for vn in view_nodes:
            int_id = vn.metadata.get("integrationId")
            if int_id:
                covered_integrations.add(int_id)
        for orch_node in orchestrator_nodes:
            if orch_node.integration_id:
                covered_integrations.add(orch_node.integration_id)

        for tn in self.tool_nodes:
            int_id = tn.get("integrationId") or tn.get("integration_id")
            tn_id = tn.get("id", "")
            if int_id and int_id in covered_integrations:
                continue
            if tn_id in node_id_set:
                continue

            tool_type = (tn.get("toolType") or tn.get("tool_type") or "unknown").lower()

            # Determine lane based on tool type
            if tool_type in INFRA_PLATFORMS:
                lane = PipelineLane.INGESTION.value
            elif tool_type in INGESTION_PLATFORMS:
                lane = PipelineLane.INGESTION.value
            elif tool_type in TRANSFORM_PLATFORMS:
                lane = PipelineLane.TRANSFORMATION.value
            elif tool_type in REPORTING_PLATFORMS:
                lane = PipelineLane.REPORTING.value
            elif tool_type in WAREHOUSE_PLATFORMS:
                lane = PipelineLane.WAREHOUSE_RAW.value
            elif tool_type in ORCHESTRATION_PLATFORMS:
                continue  # orchestration → overlay, not a lane node
            else:
                lane = PipelineLane.WAREHOUSE_RAW.value

            display_name = tn.get("name") or tool_type.title()
            node_view_id = tn_id or f"tool:{tool_type}:{int_id or 'default'}"
            view_nodes.append(ViewNode(
                id=node_view_id,
                name=display_name,
                canonical_type="service",
                original_type="service",
                platform=tool_type,
                platform_domain="other",
                layer=lane,
                cluster_id=lane,
                x=0, y=0,
                inferred=False,
                needs_mapping=False,
                metadata={
                    "lane": lane,
                    "badges": {"capability": tool_type},
                    "integrationId": int_id,
                    "fromPipelineStack": True,
                },
            ))
            node_id_set.add(node_view_id)

        # Step 2: Build edges (data-plane only)
        view_edges: List[ViewEdge] = []
        seen_pairs: Set[str] = set()

        for edge in self.graph.edges.values():
            # Skip control-plane edges (orchestration runs)
            if edge.plane == LinePlane.CONTROL:
                continue
            if edge.canonical_edge_type == "runs":
                continue

            src_id = edge.source_id
            tgt_id = edge.target_id

            if src_id not in node_id_set or tgt_id not in node_id_set:
                continue
            if src_id == tgt_id:
                continue

            pair = f"{src_id}→{tgt_id}"
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            view_edges.append(ViewEdge(
                id=edge.id,
                source_id=src_id,
                target_id=tgt_id,
                canonical_type=edge.canonical_edge_type or "derives",
                original_type=edge.edge_type.value,
                confidence=edge.confidence,
                inferred=edge.inferred,
                evidence_count=len(edge.evidence),
            ))

        # Step 3: Compute deterministic lane-based positions
        lane_names = [l.value for l in PipelineLane]
        lane_x_map = {name: i * LANE_X_SPACING for i, name in enumerate(lane_names)}

        # Group nodes by lane, sort within lane for stable positioning
        by_lane: Dict[str, List[ViewNode]] = defaultdict(list)
        for vn in view_nodes:
            by_lane[vn.layer].append(vn)

        # Within each lane, sort by:
        #  1. canonical_type (actors first, then datasets)
        #  2. name (alphabetical)
        TYPE_SORT = {"service": 0, "job": 1, "dataset": 2, "semantic": 3}
        for lane_name in by_lane:
            by_lane[lane_name].sort(
                key=lambda n: (TYPE_SORT.get(n.canonical_type, 9), n.name)
            )

        # Assign positions
        for lane_name, lane_nodes in by_lane.items():
            x = lane_x_map.get(lane_name, 0)
            for idx, vn in enumerate(lane_nodes):
                vn.x = x
                vn.y = idx * LANE_NODE_Y_SPACING

        # Step 4: Build orchestrator overlays
        orchestrators: List[OrchestratorOverlay] = []
        for idx, orch_node in enumerate(sorted(orchestrator_nodes, key=lambda n: n.name)):
            # Position above the transformation lane
            orch_x = lane_x_map.get(PipelineLane.TRANSFORMATION.value, 2 * LANE_X_SPACING)
            orchestrators.append(OrchestratorOverlay(
                id=orch_node.id,
                name=orch_node.name,
                platform=orch_node.platform or "unknown",
                integration_id=orch_node.integration_id,
                x=orch_x + idx * 200,
                y=ORCHESTRATOR_Y_OFFSET,
                runs_job_ids=orchestrator_runs.get(orch_node.id, []),
            ))

        # Step 5: Build lane metadata
        lanes: List[LaneMeta] = []
        lane_labels = {
            PipelineLane.INGESTION.value: "Ingestion",
            PipelineLane.WAREHOUSE_RAW.value: "Warehouse (Raw)",
            PipelineLane.TRANSFORMATION.value: "Transformation",
            PipelineLane.WAREHOUSE_ANALYTICS.value: "Warehouse (Analytics)",
            PipelineLane.REPORTING.value: "Reporting",
        }
        for lane_name in lane_names:
            lanes.append(LaneMeta(
                name=lane_name,
                label=lane_labels.get(lane_name, lane_name),
                order=LANE_ORDER.get(lane_name, 99),
                x=lane_x_map.get(lane_name, 0),
                node_count=len(by_lane.get(lane_name, [])),
            ))

        # Step 6: Build clusters per lane
        clusters = _build_clusters_from_nodes(view_nodes)

        # Stats
        stats = {
            "totalNodes": len(view_nodes),
            "totalEdges": len(view_edges),
            "orchestratorCount": len(orchestrators),
            "inferredNodeCount": sum(1 for n in view_nodes if n.inferred),
            "inferredEdgeCount": sum(1 for e in view_edges if e.inferred),
            "laneDistribution": {
                lane_name: len(by_lane.get(lane_name, []))
                for lane_name in lane_names
            },
        }

        return RenderedView(
            view_type="lane_pipeline_overview",
            nodes=view_nodes,
            edges=view_edges,
            clusters=clusters,
            unmapped_nodes=[],
            stats=stats,
            lanes=lanes,
            orchestrators=orchestrators,
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
        # Step 1: Select relevant nodes
        selected_types = {
            CanonicalNodeType.DATASET.value,
            CanonicalNodeType.SEMANTIC.value,
        }

        # Also include JOB nodes that have both upstream and downstream dataset connections
        # (so the view shows dataset → job → dataset chains)
        job_node_ids: Set[str] = set()
        for edge in self.graph.edges.values():
            src = self.graph.nodes.get(edge.source_id)
            tgt = self.graph.nodes.get(edge.target_id)
            if not src or not tgt:
                continue
            src_ct = src.canonical_type or map_node_type(src).value
            tgt_ct = tgt.canonical_type or map_node_type(tgt).value
            if src_ct in selected_types and tgt_ct == CanonicalNodeType.JOB.value:
                job_node_ids.add(tgt.id)
            if src_ct == CanonicalNodeType.JOB.value and tgt_ct in selected_types:
                job_node_ids.add(src.id)

        # Step 2: Deduplicate Airflow table refs by FQN
        # Airflow adapter creates table nodes (platform=airflow) that duplicate
        # warehouse table nodes. Keep warehouse version, remap edges.
        warehouse_fqn_map: Dict[str, str] = {}  # FQN → node ID
        airflow_remap: Dict[str, str] = {}  # airflow node ID → warehouse node ID

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
            if node.platform == "airflow":
                if fqn in warehouse_fqn_map:
                    airflow_remap[node.id] = warehouse_fqn_map[fqn]
            elif fqn not in warehouse_fqn_map:
                warehouse_fqn_map[fqn] = node.id

        # Step 3: Build node list
        view_nodes: List[ViewNode] = []
        node_id_set: Set[str] = set()
        unmapped: List[Dict[str, Any]] = []

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.fqn):
            if node.id in airflow_remap:
                continue

            ct = node.canonical_type or map_node_type(node).value
            if ct not in selected_types and node.id not in job_node_ids:
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

        # Step 4: Build edges (remap airflow refs)
        view_edges: List[ViewEdge] = []
        seen_edge_pairs: Set[str] = set()

        for edge in self.graph.edges.values():
            src_id = airflow_remap.get(edge.source_id, edge.source_id)
            tgt_id = airflow_remap.get(edge.target_id, edge.target_id)

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

        # Step 5: Compute deterministic layout
        positions = _topological_layout(view_nodes, view_edges)
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
