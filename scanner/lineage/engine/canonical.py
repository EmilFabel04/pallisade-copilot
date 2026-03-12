"""
Canonical Type Taxonomy & Mapper

Maps the engine's granular NodeType/EdgeType enums to a strict 5-node,
6-edge canonical taxonomy. This enables consistent categorization across
all adapters and a clean mapping to pipeline layers for the ViewBuilder.

Canonical Node Types:
    system   — infrastructure (Linux servers, cloud accounts, VMs)
    service  — tool instances (Snowflake, dbt Cloud, Looker, n8n)
    job      — executable units (DAG, task, workflow, connector, monitor)
    dataset  — data assets (table, view, model, seed, snapshot, file, topic)
    semantic — presentation layer (dashboard, report, workbook, explore)

Canonical Edge Types:
    hosts    — system → service
    runs     — service → job
    reads    — job/semantic → dataset
    writes   — job → dataset
    derives  — dataset → dataset
    serves   — dataset → semantic
"""

import hashlib
from enum import Enum
from typing import Dict, Optional, Set, Tuple

from ..graph import (
    EdgeType,
    LineageEdge,
    LineageNode,
    NodeType,
    PlatformDomain,
)


class CanonicalNodeType(Enum):
    """Strict 5-type node taxonomy."""
    SYSTEM = "system"
    SERVICE = "service"
    JOB = "job"
    DATASET = "dataset"
    SEMANTIC = "semantic"


class CanonicalEdgeType(Enum):
    """Strict 6-type edge taxonomy."""
    HOSTS = "hosts"
    RUNS = "runs"
    READS = "reads"
    WRITES = "writes"
    DERIVES = "derives"
    SERVES = "serves"


# ---- Node type mapping ----
# Key: (NodeType, optional PlatformDomain for disambiguation)
# Value: CanonicalNodeType
#
# When PlatformDomain is None, the mapping applies regardless of domain.
# When both (NodeType, domain) and (NodeType, None) exist, the specific
# domain match wins.

_NODE_TYPE_MAP: Dict[Tuple[NodeType, Optional[PlatformDomain]], CanonicalNodeType] = {
    # Data assets → DATASET
    (NodeType.TABLE, None): CanonicalNodeType.DATASET,
    (NodeType.VIEW, None): CanonicalNodeType.DATASET,
    (NodeType.MATERIALIZED_VIEW, None): CanonicalNodeType.DATASET,
    (NodeType.SOURCE, None): CanonicalNodeType.DATASET,
    (NodeType.SEED, None): CanonicalNodeType.DATASET,
    (NodeType.SNAPSHOT, None): CanonicalNodeType.DATASET,
    (NodeType.FEATURE, None): CanonicalNodeType.DATASET,
    (NodeType.MODEL_ARTIFACT, None): CanonicalNodeType.DATASET,

    # MODEL is ambiguous: dbt model = DATASET, Looker model = SEMANTIC
    (NodeType.MODEL, PlatformDomain.TRANSFORM): CanonicalNodeType.DATASET,
    (NodeType.MODEL, PlatformDomain.WAREHOUSE): CanonicalNodeType.DATASET,
    (NodeType.MODEL, PlatformDomain.BI): CanonicalNodeType.SEMANTIC,
    (NodeType.MODEL, None): CanonicalNodeType.DATASET,  # default: treat as data asset

    # Jobs / executable units → JOB
    (NodeType.TASK, None): CanonicalNodeType.JOB,
    (NodeType.DAG, None): CanonicalNodeType.JOB,
    (NodeType.FLOW, None): CanonicalNodeType.JOB,
    (NodeType.PIPELINE, None): CanonicalNodeType.JOB,
    (NodeType.WORKFLOW, None): CanonicalNodeType.JOB,
    (NodeType.NOTEBOOK, None): CanonicalNodeType.JOB,
    (NodeType.CONNECTOR, None): CanonicalNodeType.JOB,
    (NodeType.MONITOR, None): CanonicalNodeType.JOB,
    (NodeType.MACRO, None): CanonicalNodeType.JOB,

    # BI / presentation → SEMANTIC
    (NodeType.DASHBOARD, None): CanonicalNodeType.SEMANTIC,
    (NodeType.REPORT, None): CanonicalNodeType.SEMANTIC,
    (NodeType.WORKBOOK, None): CanonicalNodeType.SEMANTIC,
    (NodeType.QUESTION, None): CanonicalNodeType.SEMANTIC,
    (NodeType.EXPLORE, None): CanonicalNodeType.SEMANTIC,

    # DATASET NodeType with BI domain = SEMANTIC (Power BI dataset)
    (NodeType.DATASET, PlatformDomain.BI): CanonicalNodeType.SEMANTIC,
    (NodeType.DATASET, None): CanonicalNodeType.DATASET,

    # Unknown → DATASET (most common case; surfaced as needs_mapping)
    (NodeType.UNKNOWN, None): CanonicalNodeType.DATASET,
}


# ---- Edge type mapping ----

_EDGE_TYPE_MAP: Dict[EdgeType, CanonicalEdgeType] = {
    # Derives (data lineage)
    EdgeType.DEPENDS_ON: CanonicalEdgeType.DERIVES,
    EdgeType.DERIVED_FROM: CanonicalEdgeType.DERIVES,

    # Reads
    EdgeType.JOINS: CanonicalEdgeType.READS,
    EdgeType.REFERENCES: CanonicalEdgeType.READS,
    EdgeType.READS_FROM: CanonicalEdgeType.READS,
    EdgeType.QUERIES: CanonicalEdgeType.READS,
    EdgeType.TESTS: CanonicalEdgeType.READS,
    EdgeType.MONITORS: CanonicalEdgeType.READS,

    # Writes
    EdgeType.POPULATES: CanonicalEdgeType.WRITES,
    EdgeType.REFRESHES: CanonicalEdgeType.WRITES,
    EdgeType.WRITES_TO: CanonicalEdgeType.WRITES,
    EdgeType.MATERIALIZES: CanonicalEdgeType.WRITES,
    EdgeType.SYNCS_TO: CanonicalEdgeType.WRITES,

    # Runs (orchestration)
    EdgeType.TRIGGERS: CanonicalEdgeType.RUNS,
    EdgeType.PRODUCED_BY: CanonicalEdgeType.RUNS,
}


# ---- Layer assignment for view builder ----
# Maps (CanonicalNodeType, PlatformDomain) to a pipeline layer string.
# Used by the ViewBuilder to assign nodes to visual layers.

DOMAIN_TO_LAYER: Dict[PlatformDomain, str] = {
    PlatformDomain.INGESTION: "INGESTION",
    PlatformDomain.WAREHOUSE: "WAREHOUSE",
    PlatformDomain.TRANSFORM: "TRANSFORMATION",
    PlatformDomain.ORCHESTRATION: "ORCHESTRATION",
    PlatformDomain.BI: "REPORTING",
    PlatformDomain.CATALOG: "WAREHOUSE",
    PlatformDomain.APP: "REPORTING",
    PlatformDomain.OTHER: "WAREHOUSE",
}

# Layer ordering for deterministic layout (left → right)
LAYER_ORDER: Dict[str, int] = {
    "INGESTION": 0,
    "ORCHESTRATION": 1,
    "WAREHOUSE": 2,
    "TRANSFORMATION": 3,
    "REPORTING": 4,
    "STORAGE": 5,
    "VERSION_CONTROL": 6,
    "INFRASTRUCTURE": 7,
}


def map_node_type(node: LineageNode) -> CanonicalNodeType:
    """Map a LineageNode to its canonical type.

    Checks domain-specific mapping first, then falls back to
    domain-agnostic mapping, then defaults to DATASET.
    """
    # Try domain-specific mapping first
    specific = _NODE_TYPE_MAP.get((node.node_type, node.platform_domain))
    if specific is not None:
        return specific

    # Fall back to domain-agnostic mapping
    generic = _NODE_TYPE_MAP.get((node.node_type, None))
    if generic is not None:
        return generic

    # Ultimate fallback
    return CanonicalNodeType.DATASET


def map_edge_type(edge: LineageEdge) -> CanonicalEdgeType:
    """Map a LineageEdge to its canonical edge type.

    Falls back to DERIVES for unknown edge types.
    """
    return _EDGE_TYPE_MAP.get(edge.edge_type, CanonicalEdgeType.DERIVES)


def infer_canonical_edge_type(
    source_canonical: CanonicalNodeType,
    target_canonical: CanonicalNodeType,
    original_edge_type: EdgeType,
) -> CanonicalEdgeType:
    """Infer canonical edge type from source/target canonical types.

    When the original mapping is ambiguous (e.g., READS_FROM between
    dataset → semantic), this uses the node types to pick the right
    canonical edge.
    """
    # First try the standard mapping
    mapped = _EDGE_TYPE_MAP.get(original_edge_type)

    # Apply semantic overrides based on node type pairs
    if source_canonical == CanonicalNodeType.DATASET and target_canonical == CanonicalNodeType.SEMANTIC:
        return CanonicalEdgeType.SERVES
    if source_canonical == CanonicalNodeType.DATASET and target_canonical == CanonicalNodeType.DATASET:
        if mapped in (CanonicalEdgeType.READS, CanonicalEdgeType.WRITES):
            return CanonicalEdgeType.DERIVES
        return mapped or CanonicalEdgeType.DERIVES
    if source_canonical == CanonicalNodeType.SYSTEM and target_canonical == CanonicalNodeType.SERVICE:
        return CanonicalEdgeType.HOSTS
    if source_canonical == CanonicalNodeType.SERVICE and target_canonical == CanonicalNodeType.JOB:
        return CanonicalEdgeType.RUNS

    return mapped or CanonicalEdgeType.DERIVES


def map_edge_type_explicit(
    adapter_edge_type: EdgeType,
    from_node: LineageNode,
    to_node: LineageNode,
) -> CanonicalEdgeType:
    """Map an adapter edge type using full node context (dict + semantic overrides).

    Single source of truth for edge type mapping.  Adapters and bridge code
    should call this (and set ``edge.canonical_edge_type = result.value``)
    instead of manually choosing a CanonicalEdgeType.  When the edge already
    has ``canonical_edge_type`` set, ``canonicalize_graph_in_place`` will
    preserve it.
    """
    from_canonical = map_node_type(from_node)
    to_canonical = map_node_type(to_node)
    return infer_canonical_edge_type(from_canonical, to_canonical, adapter_edge_type)


def generate_urn(node: LineageNode) -> str:
    """Generate a stable URN for a node.

    Format: urn:pallisade:{canonical_type}:{platform}:{namespace}:{name}

    The URN is deterministic — same physical asset always gets the same URN
    regardless of which adapter discovered it.
    """
    canonical = map_node_type(node)
    platform = (node.platform or "unknown").lower()
    namespace = (node.namespace or "").lower()
    name = node.fqn.lower() if node.fqn else node.name.lower()
    return f"urn:pallisade:{canonical.value}:{platform}:{namespace}:{name}"


def get_layer(node: LineageNode) -> str:
    """Get the pipeline layer for a node based on its platform domain."""
    return DOMAIN_TO_LAYER.get(node.platform_domain, "WAREHOUSE")


def get_layer_order(layer: str) -> int:
    """Get the numeric ordering for a layer (lower = further left)."""
    return LAYER_ORDER.get(layer, 99)


def is_needs_mapping(node: LineageNode) -> bool:
    """Check if a node needs manual mapping/review.

    A node needs mapping when:
    - Its type is UNKNOWN
    - Its platform domain is OTHER and we can't determine a canonical type
    """
    if node.node_type == NodeType.UNKNOWN:
        return True
    if node.platform_domain == PlatformDomain.OTHER and node.node_type not in (
        NodeType.TABLE, NodeType.VIEW, NodeType.MODEL,
    ):
        return True
    return False


def canonicalize_graph_in_place(
    nodes: Dict[str, LineageNode],
    edges: Dict[str, LineageEdge],
) -> Dict[str, Set[str]]:
    """Apply canonical types and URNs to all nodes/edges in place.

    Returns a dict with:
        - "needs_mapping": set of node IDs that need manual mapping
        - "unmapped_edge_types": set of original edge type values with no mapping
    """
    needs_mapping: Set[str] = set()
    unmapped_edge_types: Set[str] = set()

    for node in nodes.values():
        # Respect explicitly set canonical_type from adapters (e.g., "service", "job").
        # Only fall back to map_node_type when no canonical_type was set.
        if not node.canonical_type:
            canonical = map_node_type(node)
            node.canonical_type = canonical.value
        node.urn = generate_urn(node)

        # Populate platform_native_domain from the platform registry.
        # This reflects the platform's own domain (e.g. "orchestration" for
        # Airflow) independently of what domain this particular node represents.
        from .platforms import get_platform
        platform_info = get_platform(node.platform or "")
        if platform_info:
            node.platform_native_domain = platform_info.domain.value
        else:
            # Unknown platform — flag for UI to surface as uncategorized
            if node.platform:
                node.raw_metadata["needs_mapping"] = True
                needs_mapping.add(node.id)

        if is_needs_mapping(node):
            needs_mapping.add(node.id)

    for edge in edges.values():
        # Respect explicitly set canonical_edge_type from adapters/bridge/
        # cross-tool synthesis.  Only infer when not already set (mirrors
        # the node preservation guard above at line 278).
        if edge.canonical_edge_type:
            continue

        # Get source/target canonical types for smart edge inference
        source = nodes.get(edge.source_id)
        target = nodes.get(edge.target_id)
        if source and target and source.canonical_type and target.canonical_type:
            src_canonical = CanonicalNodeType(source.canonical_type)
            tgt_canonical = CanonicalNodeType(target.canonical_type)
            canonical_edge = infer_canonical_edge_type(
                src_canonical, tgt_canonical, edge.edge_type,
            )
        else:
            canonical_edge = map_edge_type(edge)
            if edge.edge_type not in _EDGE_TYPE_MAP:
                unmapped_edge_types.add(edge.edge_type.value)

        edge.canonical_edge_type = canonical_edge.value

    return {
        "needs_mapping": needs_mapping,
        "unmapped_edge_types": unmapped_edge_types,
    }
