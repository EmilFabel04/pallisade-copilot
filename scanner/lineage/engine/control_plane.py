"""
Control Plane Graph Builder

Derives a high-level tool/integration sequence graph from the asset-level
data plane lineage. The control plane shows the pipeline architecture:

    Fivetran → Snowflake → dbt → Snowflake → Looker

Each node is a tool/integration instance, each edge represents data flow
between tools with metadata about the underlying asset-level edges.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..graph import LineageGraph, LinePlane, PlatformDomain

logger = logging.getLogger(__name__)


@dataclass
class ControlPlaneNode:
    """A node in the control plane graph representing a tool/integration."""
    id: str
    name: str                             # Display name: "Snowflake (prod)"
    tool_type: str                        # "snowflake", "dbt", "fivetran", etc.
    platform_domain: str                  # "warehouse", "transform", etc.
    integration_id: Optional[str] = None  # Link to Pallisade integration
    asset_count: int = 0                  # Number of underlying data assets
    health_summary: Dict[str, int] = field(default_factory=lambda: {
        "healthy": 0, "degraded": 0, "failing": 0, "unknown": 0,
    })
    position: int = 0                     # Sequence position in pipeline

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "toolType": self.tool_type,
            "platformDomain": self.platform_domain,
            "integrationId": self.integration_id,
            "assetCount": self.asset_count,
            "healthSummary": self.health_summary,
            "position": self.position,
        }


@dataclass
class ControlPlaneEdge:
    """An edge in the control plane representing data flow between tools."""
    id: str
    source: str                           # Source tool node ID
    target: str                           # Target tool node ID
    data_flow_count: int = 0              # Number of underlying data edges
    sample_assets: List[str] = field(default_factory=list)  # Top 3 asset names

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "dataFlowCount": self.data_flow_count,
            "sampleAssets": self.sample_assets,
        }


@dataclass
class ControlPlaneGraph:
    """The complete control plane graph."""
    nodes: List[ControlPlaneNode] = field(default_factory=list)
    edges: List[ControlPlaneEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "stats": {
                "tool_count": len(self.nodes),
                "flow_count": len(self.edges),
            },
        }


# Domain ordering for pipeline position (left to right)
_DOMAIN_ORDER = {
    PlatformDomain.INGESTION.value: 0,
    PlatformDomain.WAREHOUSE.value: 1,
    PlatformDomain.TRANSFORM.value: 2,
    PlatformDomain.ORCHESTRATION.value: 3,
    PlatformDomain.BI.value: 4,
    PlatformDomain.CATALOG.value: 5,
    PlatformDomain.APP.value: 6,
    PlatformDomain.OTHER.value: 7,
}


def build_control_plane_graph(data_graph: LineageGraph) -> ControlPlaneGraph:
    """
    Derive tool-sequence graph from asset-level lineage.

    Algorithm:
    1. Group all data-plane nodes by their platform (+ integration_id)
    2. For each data-plane edge (A → B), if A.platform != B.platform,
       create a control-plane edge (A.platform → B.platform)
    3. Deduplicate and weight: edge weight = count of underlying data edges
    4. Assign positions based on domain ordering and edge directions
    """
    # Step 1: Group nodes by tool identity (platform + integration_id)
    tool_key_to_nodes: Dict[str, List[str]] = defaultdict(list)
    tool_key_to_info: Dict[str, Dict[str, Any]] = {}

    for node_id, node in data_graph.nodes.items():
        platform = node.platform or "unknown"
        integration_id = node.integration_id
        # Use integration_id to distinguish multiple instances of the same tool
        tool_key = f"{platform}:{integration_id}" if integration_id else platform

        tool_key_to_nodes[tool_key].append(node_id)

        if tool_key not in tool_key_to_info:
            tool_key_to_info[tool_key] = {
                "platform": platform,
                "platform_domain": node.platform_domain.value if hasattr(node.platform_domain, 'value') else str(node.platform_domain),
                "integration_id": integration_id,
                "namespace": node.namespace,
            }

    # Step 2: Build control plane nodes
    cp_nodes: Dict[str, ControlPlaneNode] = {}
    for tool_key, node_ids in tool_key_to_nodes.items():
        info = tool_key_to_info[tool_key]
        platform = info["platform"]
        domain = info["platform_domain"]

        # Count health statuses
        health: Dict[str, int] = {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0}
        for nid in node_ids:
            node = data_graph.nodes[nid]
            status = node.health_status.value if hasattr(node.health_status, 'value') else str(node.health_status)
            if status in health:
                health[status] += 1
            else:
                health["unknown"] += 1

        # Build display name
        namespace = info.get("namespace", "")
        name = f"{platform.title()}" + (f" ({namespace})" if namespace else "")

        cp_nodes[tool_key] = ControlPlaneNode(
            id=tool_key,
            name=name,
            tool_type=platform,
            platform_domain=domain,
            integration_id=info["integration_id"],
            asset_count=len(node_ids),
            health_summary=health,
            position=_DOMAIN_ORDER.get(domain, 7),
        )

    # Step 3: Build control plane edges from cross-tool data edges
    edge_counts: Dict[str, int] = defaultdict(int)
    edge_samples: Dict[str, List[str]] = defaultdict(list)

    # Build node_id → tool_key lookup
    node_to_tool: Dict[str, str] = {}
    for tool_key, node_ids in tool_key_to_nodes.items():
        for nid in node_ids:
            node_to_tool[nid] = tool_key

    for edge in data_graph.edges.values():
        # Skip control-plane-only edges
        if edge.plane == LinePlane.CONTROL:
            continue

        src_tool = node_to_tool.get(edge.source_id)
        tgt_tool = node_to_tool.get(edge.target_id)

        if not src_tool or not tgt_tool or src_tool == tgt_tool:
            continue

        edge_key = f"{src_tool}→{tgt_tool}"
        edge_counts[edge_key] += 1

        # Collect sample asset names
        if len(edge_samples[edge_key]) < 3:
            src_node = data_graph.nodes.get(edge.source_id)
            if src_node:
                edge_samples[edge_key].append(src_node.name)

    cp_edges: List[ControlPlaneEdge] = []
    for edge_key, count in edge_counts.items():
        src_tool, tgt_tool = edge_key.split("→")
        cp_edges.append(ControlPlaneEdge(
            id=edge_key,
            source=src_tool,
            target=tgt_tool,
            data_flow_count=count,
            sample_assets=edge_samples[edge_key],
        ))

    # Step 4: Refine positions using topological hints from edges
    _refine_positions(cp_nodes, cp_edges)

    return ControlPlaneGraph(
        nodes=sorted(cp_nodes.values(), key=lambda n: n.position),
        edges=cp_edges,
    )


def _refine_positions(
    nodes: Dict[str, ControlPlaneNode],
    edges: List[ControlPlaneEdge],
) -> None:
    """
    Refine node positions based on edge directions.

    Ensures that if A→B exists, position(A) < position(B).
    Uses simple iterative adjustment on top of domain-based defaults.
    """
    changed = True
    iterations = 0
    max_iterations = 10

    while changed and iterations < max_iterations:
        changed = False
        iterations += 1

        for edge in edges:
            src = nodes.get(edge.source)
            tgt = nodes.get(edge.target)
            if not src or not tgt:
                continue

            if src.position >= tgt.position:
                tgt.position = src.position + 1
                changed = True
