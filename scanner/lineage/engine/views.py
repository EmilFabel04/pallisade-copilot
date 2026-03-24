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
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..graph import (
    EdgeType,
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
    FunctionalRole,
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
    resolve_functional_role,
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
    job_node_id: str = ""
    job_node_name: str = ""


@dataclass
class _ToolEdgeAgg:
    """Aggregated derivation evidence for a tool→tool edge."""
    edges: List[LineageEdge]       # underlying canonical derivation edges
    pair_counts: Counter           # Counter[(src_name, tgt_name)] — frequency
    asset_ids: Set[str]            # unique node IDs involved (both src + tgt)
    lane_pair_counts: Counter = field(default_factory=Counter)  # Counter[(src_lane, tgt_lane)]
    seen_pairs: Set[tuple] = field(default_factory=set)  # deduplicate (src_nid, tgt_nid)  # Counter[(src_lane, tgt_lane)]


# ── Evidence label normalisation ──────────────────────────────────────────

_EVIDENCE_LABEL_MAP: Dict[str, str] = {
    "live_dbt": "dbt_manifest",
    "dbt_manifest": "dbt_manifest",
    "live_warehouse": "query_history",
    "warehouse_catalog": "query_history",
    "live_fivetran": "fivetran_api",
    "live_airbyte": "airbyte_api",
    "compiled_sql": "compiled_sql",
    "regex": "regex",
}


def _normalise_evidence_label(edge: LineageEdge) -> str:
    """Return a stable, human-readable evidence label for a derivation edge.

    Priority:
      1. edge.discovered_from (already human-readable)
      2. First evidence.adapter_id mapped through _EVIDENCE_LABEL_MAP
      3. Raw adapter_id as last resort
    """
    df = edge.discovered_from or ""
    if df:
        if df.startswith("bridge:"):
            return "bridge_inferred"
        return df
    for ev in edge.evidence:
        mapped = _EVIDENCE_LABEL_MAP.get(ev.adapter_id)
        if mapped:
            return mapped
        return ev.adapter_id  # raw fallback
    return "unknown"


# ── Control-plane category helpers ────────────────────────────────────────

_CONTROL_PLANE_CATEGORIES = frozenset({"version_control", "infrastructure"})
_CONTROL_PLANE_PLATFORMS = frozenset({
    "github", "gitlab", "bitbucket",                    # VCS
    "slack", "pagerduty", "opsgenie", "teams",          # Notifications
    "jira", "linear", "asana",                          # Ticketing
    "custom_webhook",                                    # Other
    "linux", "linux_server", "ssh",                      # Infrastructure
})


def _is_control_plane_category(category: str, platform: str = "") -> bool:
    """Check if a tool is control-plane (no data lineage assets expected)."""
    if category in _CONTROL_PLANE_CATEGORIES:
        return True
    if platform.lower() in _CONTROL_PLANE_PLATFORMS:
        return True
    return False


# Layout constants
LAYER_SPACING_X = 300  # px between layers (left-to-right)
NODE_SPACING_Y = 180   # px between nodes within a layer
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
# Platform → layer / domain helpers (for Pipeline Overview dedup)
# ---------------------------------------------------------------------------

from .platforms import get_platform, get_category, ToolCategory
from .edge_semantics import (
    BASIS_EXPLICIT_CONFIG,
    BASIS_METADATA_REFERENCE,
    BASIS_MONITORING_COEXISTENCE,
    BASIS_PIPELINE_COEXISTENCE,
    BASIS_TO_EDGE_ORIGIN,
    CODE_OWNERSHIP,
    CONFIDENCE_EXPLICIT_CONFIG,
    CONFIDENCE_METADATA_XREF,
    CONFIDENCE_MONITORING_COEX,
    CONFIDENCE_PIPELINE_COEX,
    DATA_DERIVATION,
    HOSTING,
    INFERRED_ADJACENCY,
    JOB_ORCHESTRATION,
    MONITORING,
    derive_semantic_type,
    enforce_semantic_constraints,
)

# ---------------------------------------------------------------------------
# Control-plane evidence probing
#
# Control-plane edges must come from normalized evidence or narrowly-scoped
# policy fallbacks, never from vendor-specific assumptions or adjacency.
# All matching uses normalized canonical names from the platform registry
# and alias resolution — zero vendor-specific branching.
# ---------------------------------------------------------------------------

# CP metadata key families per evidence type.
# Authoritative contract defined in edge_semantics.py (CP_META_KEYS_*).
# Legacy aliases are kept for backward compatibility with older adapters.
_CP_EVIDENCE_KEYS: Dict[str, List[str]] = {
    JOB_ORCHESTRATION: [
        "orchestrated_tools",                         # contract key
        "managed_connectors", "triggered_tools",      # legacy aliases
        "dag_tasks", "workflow_targets",
    ],
    CODE_OWNERSHIP: [
        "managed_targets", "managed_repos",           # contract keys
        "code_targets", "project_repos",              # legacy aliases
        "repository_tools",
    ],
    HOSTING: [
        "hosted_tools", "hosted_platforms",            # contract keys
        "running_services",                            # contract key
        "managed_services", "hosted_services",         # legacy aliases
    ],
    MONITORING: [
        "monitored_tools", "monitored_tables",        # contract keys
        "monitored_platforms", "quality_targets",      # legacy aliases
    ],
}


def _build_normalized_identity_set(platform: str, integration_id: Optional[str], display_name: str) -> Set[str]:
    """Build a set of normalized identities for a tool using the platform registry.

    Includes canonical name, all aliases, integration_id, and lowercased display name.
    No vendor-specific logic — purely registry-driven.
    """
    identities: Set[str] = set()
    platform_lower = platform.lower()
    identities.add(platform_lower)

    p_info = get_platform(platform_lower)
    if p_info:
        identities.add(p_info.name.lower())
        for alias in p_info.aliases:
            identities.add(alias.lower())

    if integration_id:
        identities.add(integration_id.lower())

    if display_name:
        identities.add(display_name.lower())

    return identities


def _probe_control_plane_evidence(
    src_vn: "ViewNode",
    tgt_vn: "ViewNode",
    ev_type: str,
    tool_info: Dict[Tuple[str, str], Dict],
    tool_key_to_graph_nodes: Dict[Tuple[str, str], List],
    pipeline_edges: Optional[List[Dict[str, Any]]] = None,
    tgt_category: Optional[str] = None,
) -> Optional[Tuple[str, float]]:
    """Probe for evidence justifying a control-plane edge.

    Returns (relationship_basis, confidence) or None if no evidence found.
    All matching uses normalized canonical names from the platform registry
    and alias resolution — no vendor-specific branching.

    Probe order (first match wins):
      1. Metadata cross-reference — raw_metadata contains explicit tool references
      2. PipelineEdge structural evidence — user-drawn edges in pipeline config
      3. Monitoring coexistence — narrow fallback ONLY for MONITORING evidence type
    """
    # ── Probe 1: Metadata cross-reference ─────────────────────────────
    evidence_keys = _CP_EVIDENCE_KEYS.get(ev_type, [])
    if evidence_keys:
        # Build normalized identity set for the target tool
        tgt_platform = tgt_vn.metadata.get("platform_raw", tgt_vn.platform or "")
        tgt_int_id = tgt_vn.metadata.get("integrationId")
        tgt_display = tgt_vn.name or ""
        tgt_identities = _build_normalized_identity_set(tgt_platform, tgt_int_id, tgt_display)

        # Parse src tool key from src_vn.id  (format: "tool:<lane>:<tool_id>")
        src_id_parts = src_vn.id.split(":", 2)
        src_tk_lane = src_id_parts[1] if len(src_id_parts) >= 3 else ""
        src_tk_tool = src_id_parts[2] if len(src_id_parts) >= 3 else src_vn.id
        src_tk = (src_tk_lane, src_tk_tool)

        # Check graph nodes belonging to the source tool for metadata references
        for gn in tool_key_to_graph_nodes.get(src_tk, []):
            rm = gn.raw_metadata or {}
            for key in evidence_keys:
                values = rm.get(key)
                if not values:
                    continue
                # Normalize to list
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, (list, tuple)):
                    continue
                for val in values:
                    if isinstance(val, str) and val.lower() in tgt_identities:
                        return (BASIS_METADATA_REFERENCE, CONFIDENCE_METADATA_XREF)

        # Also check tool_node-level metadata (from pipeline stack config)
        src_info = tool_info.get(src_tk, {})
        src_raw_meta = src_info.get("raw_metadata") or {}
        if src_raw_meta:
            logger.debug(
                "[CP-Probe] src=%s → tgt=%s: tool_info raw_metadata=%s, tgt_identities=%s",
                src_vn.id, tgt_vn.id, src_raw_meta, tgt_identities,
            )
        for key in evidence_keys:
            values = src_raw_meta.get(key)
            if not values:
                continue
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, (list, tuple)):
                continue
            for val in values:
                if isinstance(val, str) and val.lower() in tgt_identities:
                    return (BASIS_METADATA_REFERENCE, CONFIDENCE_METADATA_XREF)

    # ── Probe 2: PipelineEdge structural evidence ──────────────────────
    # User-drawn PipelineEdge records connecting these two tools.
    if pipeline_edges:
        src_int_id = src_vn.metadata.get("integrationId")
        tgt_int_id = tgt_vn.metadata.get("integrationId")
        # Also gather graph node IDs for each tool
        src_id_parts = src_vn.id.split(":", 2)
        src_tk2 = (src_id_parts[1] if len(src_id_parts) >= 3 else "",
                   src_id_parts[2] if len(src_id_parts) >= 3 else src_vn.id)
        tgt_id_parts = tgt_vn.id.split(":", 2)
        tgt_tk2 = (tgt_id_parts[1] if len(tgt_id_parts) >= 3 else "",
                   tgt_id_parts[2] if len(tgt_id_parts) >= 3 else tgt_vn.id)
        src_gn_ids = {gn.id for gn in tool_key_to_graph_nodes.get(src_tk2, [])}
        tgt_gn_ids = {gn.id for gn in tool_key_to_graph_nodes.get(tgt_tk2, [])}

        for pe in pipeline_edges:
            pe_src = pe.get("sourceId", "")
            pe_tgt = pe.get("targetId", "")
            src_match = (
                pe_src in src_gn_ids
                or (src_int_id and pe_src == src_int_id)
            )
            tgt_match = (
                pe_tgt in tgt_gn_ids
                or (tgt_int_id and pe_tgt == tgt_int_id)
            )
            if src_match and tgt_match:
                return (BASIS_EXPLICIT_CONFIG, CONFIDENCE_EXPLICIT_CONFIG)

    # ── Probe 3: Pipeline co-presence fallback ───────────────────────
    # If two tools from valid CP categories co-exist in the same pipeline,
    # create a weak edge — but with guardrails:
    #
    #  - HOSTING: never use coexistence (too noisy — need real evidence)
    #  - JOB_ORCHESTRATION: only if the source tool has NO metadata-specified
    #    targets (if orchestrated_tools is set, those are the real targets)
    #  - CODE_OWNERSHIP: only if the source tool has NO managed_repos metadata
    #  - MONITORING: always allow (quality tools monitor everything co-located)

    if ev_type == MONITORING:
        return (BASIS_MONITORING_COEXISTENCE, CONFIDENCE_MONITORING_COEX)

    if ev_type == HOSTING:
        # Infrastructure edges need explicit evidence — coexistence is too broad
        return None

    # For orchestration and VCS: only coexist if the source has no explicit
    # metadata targets (otherwise the metadata already defines the edges).
    src_raw_meta_for_coex = src_info.get("raw_metadata") or {}
    _has_explicit_targets = False
    for key in evidence_keys:
        if src_raw_meta_for_coex.get(key):
            _has_explicit_targets = True
            break
    # Also check graph nodes for explicit metadata
    if not _has_explicit_targets:
        for gn in tool_key_to_graph_nodes.get(src_tk, []):
            rm = gn.raw_metadata or {}
            for key in evidence_keys:
                if rm.get(key):
                    _has_explicit_targets = True
                    break
            if _has_explicit_targets:
                break

    if _has_explicit_targets:
        # Source has metadata specifying its targets — don't create
        # coexistence edges to tools NOT in the metadata.
        return None

    # Orchestration → ingestion coexistence is too noisy: ingestion tools
    # (Fivetran, Airbyte) have their own scheduling and are rarely
    # orchestrated by external orchestrators without explicit config.
    if ev_type == JOB_ORCHESTRATION and tgt_category == "ingestion":
        return None

    return (BASIS_PIPELINE_COEXISTENCE, CONFIDENCE_PIPELINE_COEX)


_CATEGORY_TO_LAYER: Dict[str, str] = {
    "warehouse": "WAREHOUSE",
    "ingestion": "INGESTION",
    "transformation": "TRANSFORMATION",
    "orchestration": "ORCHESTRATION",
    "reporting": "REPORTING",
    "infrastructure": "INFRASTRUCTURE",
    "version_control": "VERSION_CONTROL",
    "quality": "WAREHOUSE",
}


def _platform_to_layer(platform: str) -> str:
    """Map a platform name to its LAYER_COLORS-compatible layer string."""
    info = get_platform(platform)
    if info:
        return _CATEGORY_TO_LAYER.get(info.category.value, "WAREHOUSE")
    return "WAREHOUSE"


def _get_display_domain(platform: str) -> str:
    """Map a platform name to its display domain for frontend DOMAIN_COLORS."""
    info = get_platform(platform)
    if info:
        if info.category == ToolCategory.INFRASTRUCTURE:
            return "infrastructure"
        if info.category == ToolCategory.VERSION_CONTROL:
            return "version_control"
        return info.domain.value
    return "other"


# ---------------------------------------------------------------------------
# Semantic edge type helpers (for Pipeline Overview)
# Now delegated to edge_semantics module — see derive_semantic_type()
# ---------------------------------------------------------------------------


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
        pipeline_edges: Optional[List[Dict[str, Any]]] = None,
    ):
        self.graph = graph
        self.tool_nodes = tool_nodes or []
        self.pipeline_edges = pipeline_edges or []

    def _compute_job_bypass_edges(self) -> List[_BypassInfo]:
        """Compute bypass edges for JOB nodes: dataset→job→dataset → dataset→dataset.

        Reusable across data-plane view and lane pipeline overview.
        """
        selected_types = {
            CanonicalNodeType.DATASET.value,
            CanonicalNodeType.SEMANTIC.value,
        }
        bypass_edges: List[_BypassInfo] = []
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
                        bypass_edges.append(_BypassInfo(
                            upstream_id=up_id,
                            downstream_id=down_id,
                            upstream_edge_id=up_edge.id,
                            downstream_edge_id=down_edge.id,
                            min_confidence=min(up_edge.confidence, down_edge.confidence),
                            total_evidence=len(up_edge.evidence) + len(down_edge.evidence),
                            job_node_id=node.id,
                            job_node_name=node.name or node.id,
                        ))
        return bypass_edges

    @staticmethod
    def _aggregate_tool_edge(
        pair_key: str,
        agg: _ToolEdgeAgg,
        src_lane: str,
        tgt_lane: str,
        src_category: Optional[str] = None,
        tgt_category: Optional[str] = None,
        evidence_type: str = DATA_DERIVATION,
        src_role: Optional[str] = None,
        tgt_role: Optional[str] = None,
    ) -> ViewEdge:
        """Build a ViewEdge from aggregated underlying derivation edges."""
        flow_count = len(agg.edges)
        asset_count = len(agg.asset_ids)

        # Weighted confidence: w_i = 1 + log(1 + evidence_count_i)
        total_w = 0.0
        weighted_c = 0.0
        evidence_mix: Dict[str, int] = defaultdict(int)
        all_evidence_refs: List[str] = []
        has_real_evidence = False
        has_bridge = False

        for e in agg.edges:
            ev_count = len(e.evidence)
            if ev_count > 0:
                has_real_evidence = True
            if (e.discovered_from or "").startswith("bridge:"):
                has_bridge = True
            w = 1.0 + math.log(1.0 + ev_count)
            total_w += w
            weighted_c += e.confidence * w
            label = _normalise_evidence_label(e)
            evidence_mix[label] += 1
            for ev in e.evidence:
                if ev.source_ref and len(all_evidence_refs) < 20:
                    all_evidence_refs.append(ev.source_ref)

        confidence = (weighted_c / total_w) if total_w > 0 else 0.5
        confidence = max(0.3, min(0.95, confidence))

        # Determine edge origin (provenance classification)
        if has_real_evidence:
            edge_origin = "evidence"
        elif has_bridge and not has_real_evidence:
            edge_origin = "inferred"
        else:
            edge_origin = "evidence"

        # Top pairs by frequency, stable sort for determinism
        top_raw = agg.pair_counts.most_common(10)
        top_pairs = sorted(
            [{"src": p[0], "tgt": p[1], "count": c} for (p, c) in top_raw],
            key=lambda x: (-x["count"], x["src"], x["tgt"]),
        )

        # Use dominant lane pair from underlying edges (resilient to node merge)
        dominant_src_lane = src_lane
        dominant_tgt_lane = tgt_lane
        if agg.lane_pair_counts:
            dominant_pair = agg.lane_pair_counts.most_common(1)[0][0]
            dominant_src_lane, dominant_tgt_lane = dominant_pair

        # Category + role-driven semantic type derivation
        semantic_type, semantic_label = derive_semantic_type(
            src_category, tgt_category, evidence_type,
            dominant_src_lane, dominant_tgt_lane,
            src_role=src_role, tgt_role=tgt_role,
        )
        # Safety net: enforce constraints
        semantic_type, semantic_label = enforce_semantic_constraints(
            semantic_type, semantic_label,
            src_category, tgt_category, evidence_type,
            src_role=src_role, tgt_role=tgt_role,
        )

        src_id, tgt_id = pair_key.split("→")

        return ViewEdge(
            id=f"flow-{pair_key}",
            source_id=src_id,
            target_id=tgt_id,
            canonical_type="derives",
            original_type="data_flow",
            confidence=round(confidence, 3),
            inferred=False,
            evidence_count=len(agg.edges),  # Number of cross-tool edges (data flows)
            evidence_refs=all_evidence_refs[:20],
            metadata={
                "semanticType": semantic_type,
                "label": semantic_label,
                "evidenceType": evidence_type,
                "edgeOrigin": edge_origin,
                "dataFlowCount": flow_count,
                "flowAssetCount": asset_count,
                "topPairs": top_pairs,
                "evidenceMix": dict(evidence_mix),
                "srcLane": dominant_src_lane,
                "tgtLane": dominant_tgt_lane,
            },
        )

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

        # Step 2.5: Cross-tool counting for merged nodes
        _pk_to_keys: Dict[str, List[str]] = defaultdict(list)
        for tk, info in tool_key_to_info.items():
            plat = info["platform"].lower()
            _pk_to_keys[plat].append(tk)
            pi = get_platform(plat)
            if pi:
                for alias in pi.aliases:
                    _pk_to_keys[alias].append(tk)
                if pi.name != plat:
                    _pk_to_keys[pi.name].append(tk)

        for node in self.graph.nodes.values():
            primary_platform = (node.platform or "unknown").lower()
            rm = node.raw_metadata or {}
            discovered = rm.get("discovered_platforms", [])
            secondary_platforms: Set[str] = set()
            for dp in discovered:
                dp_lower = dp.lower()
                if dp_lower != primary_platform:
                    secondary_platforms.add(dp_lower)
            if not secondary_platforms and primary_platform != "dbt":
                if rm.get("dbt_resource_type") in ("model", "seed", "snapshot"):
                    secondary_platforms.add("dbt")
            for sp in secondary_platforms:
                target_keys = _pk_to_keys.get(sp, [])
                if not target_keys:
                    sp_info = get_platform(sp)
                    if sp_info:
                        target_keys = _pk_to_keys.get(sp_info.name, [])
                for tk in target_keys:
                    tool_key_to_nodes[tk].append(node)

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

    @staticmethod
    def _is_job_like(node: LineageNode) -> bool:
        """Return True if this graph node should count/display as a job.

        dbt models/seeds/snapshots are data assets, not jobs — they
        represent the *output* of a build, not the build process itself.
        Only true operational jobs (Airflow tasks, connector syncs, etc.)
        should count here.
        """
        ct = node.canonical_type or ""
        if ct == "job":
            return True
        rm = node.raw_metadata
        if rm.get("is_task") or rm.get("dag_id"):
            return True
        if rm.get("connector_id") or rm.get("sync_id"):
            return True
        return False

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
        TOOL_Y_SPACING = 120.0

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

            # Compute functional role for richer semantics
            functional_role = resolve_functional_role(node, ct, dataset_zone, actor_cap)

            # Determine which lane this node would fall in
            if actor_cap == ActorCapability.ORCHESTRATION:
                lane = PipelineLane.TRANSFORMATION.value
            elif ct == "system" or actor_cap == ActorCapability.INFRA:
                lane = PipelineLane.INGESTION.value
            else:
                lane = assign_lane(node, ct, dataset_zone, actor_cap, functional_role=functional_role)

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
                    "functional_role": functional_role,
                    "raw_metadata": {},
                }
            tool_info[tk]["asset_count"] += 1

        # ── Step 1b: Aggregate CP metadata from graph nodes ───────────
        # Drivers emit CP-relevant metadata (orchestrated_tools, managed_repos,
        # hosted_tools, etc.) directly on their graph nodes. Aggregate these
        # into tool_info so the CP prober can find them without relying on
        # external enrichment from tool_nodes or the API layer.
        _CP_META_KEYS = {
            "orchestrated_tools", "managed_targets", "managed_repos",
            "managed_connectors",
            "triggered_tools", "hosted_tools", "hosted_platforms",
            "hosted_services", "managed_services", "monitored_tools",
            "monitored_platforms", "code_targets", "project_repos",
            "repository_tools",
        }
        for tk, graph_nodes in tool_key_to_graph_nodes.items():
            if tk not in tool_info:
                continue
            aggregated: Dict[str, List[str]] = {}
            for gn in graph_nodes:
                rm = gn.raw_metadata or {}
                for key in _CP_META_KEYS:
                    vals = rm.get(key)
                    if not vals:
                        continue
                    if isinstance(vals, str):
                        vals = [vals]
                    if not isinstance(vals, (list, tuple)):
                        continue
                    if key not in aggregated:
                        aggregated[key] = []
                    for v in vals:
                        if isinstance(v, str) and v not in aggregated[key]:
                            aggregated[key].append(v)
            if aggregated:
                existing_rm = tool_info[tk].get("raw_metadata") or {}
                existing_rm.update(aggregated)
                tool_info[tk]["raw_metadata"] = existing_rm
                logger.info(
                    "[LanePipelineOverview] Step 1b: tool %s got CP metadata from graph: %s",
                    tk, aggregated,
                )

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
            tool_category = get_category(tool_type)
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
            elif tool_category == ToolCategory.VERSION_CONTROL:
                lane = PipelineLane.TRANSFORMATION.value
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
                    "raw_metadata": tn.get("raw_metadata") or {},
                }
                platform_per_lane[(lane, tool_type)] = tk
                if int_id:
                    covered_integration_ids.add(int_id)

        # Warehouse lanes: if a warehouse appears in both raw and analytics,
        # keep both.  If it only appears in raw (all nodes classified raw),
        # check if there are analytics-zone datasets and split.
        # (No change needed — assign_lane already handles this.)

        # ── Step 2a: Merge raw_metadata from tool_nodes into tool_info ──
        # Graph-discovered tools (Step 1) don't get raw_metadata from the
        # pipeline stack's tool_nodes.  The API layer derives CP evidence
        # (orchestrated_tools, managed_repos, etc.) and stores it in
        # tool_node["raw_metadata"].  Merge it here so the CP prober can
        # find it.
        for tn in self.tool_nodes:
            int_id = tn.get("integrationId") or tn.get("integration_id") or ""
            tn_raw = tn.get("raw_metadata")
            if not tn_raw:
                continue
            # Find matching tool_info entry by integration_id
            for tk, info in tool_info.items():
                if int_id and info.get("integration_id") == int_id:
                    existing_rm = info.get("raw_metadata") or {}
                    existing_rm.update(tn_raw)
                    info["raw_metadata"] = existing_rm
                    break

        # ── Step 2.5: Cross-tool asset counting for merged nodes ──────
        # After resolver merges (e.g., dbt model → BigQuery table), nodes
        # have platform=bigquery but discovered_platforms=["bigquery","dbt"].
        # Count these nodes under their secondary platform tool entries so
        # the dbt card shows the correct model count.
        #
        # Build reverse index: platform_name → list of tool_info keys
        _platform_to_tks: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for tk, info in tool_info.items():
            plat = info["platform"]
            _platform_to_tks[plat].append(tk)
            # Also register aliases (e.g., "dbt" → dbt_core entries)
            plat_info = get_platform(plat)
            if plat_info:
                for alias in plat_info.aliases:
                    _platform_to_tks[alias].append(tk)
                if plat_info.name != plat:
                    _platform_to_tks[plat_info.name].append(tk)

        for node in self.graph.nodes.values():
            primary_platform = (node.platform or "unknown").lower()
            rm = node.raw_metadata or {}
            discovered = rm.get("discovered_platforms", [])

            # Also check dbt metadata fallback
            secondary_platforms: Set[str] = set()
            for dp in discovered:
                dp_lower = dp.lower()
                if dp_lower != primary_platform:
                    secondary_platforms.add(dp_lower)

            # Fallback: dbt metadata without discovered_platforms
            if not secondary_platforms and primary_platform != "dbt":
                if rm.get("dbt_resource_type") in ("model", "seed", "snapshot"):
                    secondary_platforms.add("dbt")

            for sp in secondary_platforms:
                target_tks = _platform_to_tks.get(sp, [])
                # Also check canonical name resolution
                if not target_tks:
                    sp_info = get_platform(sp)
                    if sp_info:
                        target_tks = _platform_to_tks.get(sp_info.name, [])

                for tk in target_tks:
                    tool_info[tk]["asset_count"] = tool_info[tk].get("asset_count", 0) + 1
                    tool_key_to_graph_nodes[tk].append(node)

        # Log discovered tools for debugging
        logger.info(
            "[LanePipelineOverview] Discovered %d tools from graph + %d from pipeline stack. "
            "Graph: %d nodes, %d edges. node_to_tool covers %d nodes.",
            sum(1 for t in tool_info.values() if not t.get("from_pipeline_stack")),
            sum(1 for t in tool_info.values() if t.get("from_pipeline_stack")),
            len(self.graph.nodes), len(self.graph.edges), len(node_to_tool),
        )
        for tk, info in sorted(tool_info.items()):
            logger.info(
                "[LanePipelineOverview]   Tool %s: platform=%s, assets=%d, from_stack=%s",
                tk, info["platform"], info["asset_count"], info.get("from_pipeline_stack", False),
            )

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
                is_job = self._is_job_like(gn)
                if is_job:
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
                        "isJob": is_job,
                    })

            # Collect distinct schemas from graph nodes
            schemas: List[str] = sorted({
                gn.schema for gn in graph_nodes
                if gn.schema and gn.canonical_type == "dataset"
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

            # For VCS tools, asset_count is the service node count (1),
            # not the repo count.  Pull the real repo count from raw_metadata.
            display_asset_count = info["asset_count"]
            if get_category(platform) == "version_control":
                repo_count = 0
                for gn in graph_nodes:
                    repo_count += len((gn.raw_metadata or {}).get("repositories", []))
                if repo_count > 0:
                    display_asset_count = repo_count

            view_nodes.append(ViewNode(
                id=node_view_id,
                name=info["display_name"],
                canonical_type="service",
                original_type="service",
                platform=platform,
                platform_domain=_get_display_domain(platform),
                layer=_platform_to_layer(platform),
                cluster_id=lane,
                x=0, y=0,  # computed below
                inferred=False,
                needs_mapping=False,
                metadata={
                    "lane": lane,
                    "assetCount": display_asset_count,
                    "integrationId": info["integration_id"],
                    "isOrchestrator": info.get("is_orchestrator", False),
                    "isInfra": info.get("is_infra", False),
                    "fromPipelineStack": info.get("from_pipeline_stack", False),
                    "functionalRole": info.get("functional_role", ""),
                    "healthSummary": health_summary,
                    "jobCount": job_count,
                    "lastRunTs": last_run_ts,
                    "coverageGaps": coverage_gaps,
                    "subNodes": sub_nodes,
                    "schemas": schemas,
                    "totalSubNodeCount": len(graph_nodes),
                    "jobSupport": (
                        "not_applicable" if platform in WAREHOUSE_PLATFORMS or platform in INFRA_PLATFORMS
                        else "no_data" if info.get("from_pipeline_stack") and info["asset_count"] == 0
                        else "full"
                    ),
                },
            ))

        # ── Step 4: Build evidence-based tool-to-tool flow edges ─────
        # Aggregate ALL data-plane cross-tool edges with rich evidence.
        # The pipeline overview shows tool→tool connections — any edge type
        # that crosses tool boundaries represents real data flow (service→
        # dataset, job→dataset, dataset→dataset, dataset→semantic, etc.).
        tool_edge_aggs: Dict[str, _ToolEdgeAgg] = {}

        def _add_to_agg(pair_key: str, edge: LineageEdge,
                         src_name: str, tgt_name: str,
                         src_nid: str, tgt_nid: str,
                         src_lane: str = "", tgt_lane: str = "") -> None:
            if pair_key not in tool_edge_aggs:
                tool_edge_aggs[pair_key] = _ToolEdgeAgg(
                    edges=[], pair_counts=Counter(), asset_ids=set(),
                )
            a = tool_edge_aggs[pair_key]
            # Deduplicate: same (src_nid, tgt_nid) pair from multiple adapters
            # (e.g. dbt manifest + BigQuery parser) should only count once.
            node_pair = (src_nid, tgt_nid)
            if node_pair in a.seen_pairs:
                return
            a.seen_pairs.add(node_pair)
            a.edges.append(edge)
            a.pair_counts[(src_name, tgt_name)] += 1
            a.asset_ids.add(src_nid)
            a.asset_ids.add(tgt_nid)
            if src_lane or tgt_lane:
                a.lane_pair_counts[(src_lane, tgt_lane)] += 1

        # 4a: All data-plane edges that cross tool boundaries
        #
        # After resolver merging, many nodes share the same primary platform
        # (e.g. dbt models merged into BigQuery tables → platform=bigquery).
        # To recover cross-tool edges, also check discovered_platforms on
        # source/target nodes.  If the two nodes were *originally* from
        # different tools (based on discovered_platforms), the edge counts
        # as cross-tool.
        _skip_same = 0
        _skip_no_tk = 0
        _skip_control = 0
        _cross_tool = 0

        for edge in self.graph.edges.values():
            if edge.plane == LinePlane.CONTROL:
                _skip_control += 1
                continue
            src_tk = node_to_tool.get(edge.source_id)
            tgt_tk = node_to_tool.get(edge.target_id)
            if not src_tk or not tgt_tk:
                _skip_no_tk += 1
                continue

            src_node = self.graph.nodes.get(edge.source_id)
            tgt_node = self.graph.nodes.get(edge.target_id)
            if not src_node or not tgt_node:
                continue

            # Primary tool keys match — but check if resolver-merged
            # nodes were originally from different platforms.
            if src_tk == tgt_tk:
                # Collect all platforms each node belongs to
                # (primary platform + discovered_platforms + dbt fallback)
                def _node_platforms(node: LineageNode) -> Set[str]:
                    rm = node.raw_metadata or {}
                    plats = set(dp.lower() for dp in rm.get("discovered_platforms", []))
                    plats.add((node.platform or "").lower())
                    # dbt_resource_type fallback (discovered_platforms may be
                    # lost during serialization round-trips)
                    if (node.platform or "").lower() != "dbt" and not plats.intersection({"dbt", "dbt_core"}):
                        if rm.get("dbt_resource_type") in ("model", "seed", "snapshot"):
                            plats.add("dbt")
                    return plats

                src_platforms = _node_platforms(src_node)
                tgt_platforms = _node_platforms(tgt_node)

                # Resolve platform names → tool_info keys using the
                # alias-aware _platform_to_tks index (built in Step 2.5).
                def _resolve_tks(platforms: Set[str]) -> Set[Tuple[str, str]]:
                    result: Set[Tuple[str, str]] = set()
                    for p in platforms:
                        for tk in _platform_to_tks.get(p, []):
                            result.add(tk)
                        # Resolve canonical name (e.g. "dbt" → "dbt_core")
                        p_info = get_platform(p)
                        if p_info and p_info.name != p:
                            for tk in _platform_to_tks.get(p_info.name, []):
                                result.add(tk)
                    return result

                src_all_tks = _resolve_tks(src_platforms)
                tgt_all_tks = _resolve_tks(tgt_platforms)

                # Filter candidates: each node may only use its original
                # lane (for its primary platform) or a secondary platform's
                # lane.  This prevents an analytics node from being assigned
                # to warehouse_raw just because "bigquery" maps to both lanes.
                orig_src_lane = src_tk[0]
                orig_tgt_lane = tgt_tk[0]
                src_primary = (src_node.platform or "").lower()
                tgt_primary = (tgt_node.platform or "").lower()

                def _filter_tks(all_tks: Set[Tuple[str, str]], orig_lane: str, primary_plat: str) -> Set[Tuple[str, str]]:
                    """Keep only: (a) the original lane for the primary platform,
                    or (b) any lane for secondary platforms."""
                    result: Set[Tuple[str, str]] = set()
                    for tk in all_tks:
                        tk_plat = tool_info.get(tk, {}).get("platform", "")
                        if tk_plat == primary_plat or tk_plat in {primary_plat}:
                            # Primary platform: only keep the original lane
                            if tk[0] == orig_lane:
                                result.add(tk)
                        else:
                            # Secondary platform (e.g. dbt): allow its natural lane
                            result.add(tk)
                    return result

                src_all_tks = _filter_tks(src_all_tks, orig_src_lane, src_primary)
                tgt_all_tks = _filter_tks(tgt_all_tks, orig_tgt_lane, tgt_primary)

                # Find a cross-tool pair. Scoring:
                #  +2 if src and tgt are DIFFERENT platforms (true cross-tool)
                #  +1 if src matches source node's primary platform
                #  +1 if src lane matches source node's functional role
                #  +3 if data flows left→right (src lane ≤ tgt lane)
                #  -3 if data flows right→left (src lane > tgt lane)
                src_role = tool_info.get(src_tk, {}).get("functional_role", "")
                cross_pair = None
                best_score = -1
                for s_tk in sorted(src_all_tks):
                    for t_tk in sorted(tgt_all_tks):
                        if s_tk == t_tk:
                            continue
                        s_plat = tool_info.get(s_tk, {}).get("platform", "")
                        t_plat = tool_info.get(t_tk, {}).get("platform", "")
                        score = 0
                        # Prefer cross-platform pairs (bigquery→dbt > bigquery→bigquery)
                        if s_plat != t_plat:
                            score += 2
                        # Prefer src matching primary platform
                        if s_plat == src_primary:
                            score += 1
                        # Prefer src lane matching functional role
                        if s_tk[0] == src_role:
                            score += 1
                        # Strongly prefer forward data flow (left→right in lanes)
                        s_lane_ord = LANE_ORDER.get(s_tk[0], 99)
                        t_lane_ord = LANE_ORDER.get(t_tk[0], 99)
                        if s_lane_ord <= t_lane_ord:
                            score += 3  # forward flow — correct direction
                        else:
                            score -= 3  # backward flow — penalize
                        if score > best_score:
                            best_score = score
                            cross_pair = (s_tk, t_tk)

                if not cross_pair:
                    _skip_same += 1
                    continue
                src_tk, tgt_tk = cross_pair

            # ── Step 4a-ii: Intermediate tool insertion ─────────────
            # When src and tgt are in different lanes (e.g. warehouse_raw →
            # warehouse_analytics), check if the target node was merged from
            # a secondary platform (e.g. dbt) that maps to a tool key in a
            # lane BETWEEN src and tgt.  If so, split the edge through that
            # intermediate tool: src→intermediate + intermediate→tgt.
            _split_through_intermediate = False
            src_lane_ord = LANE_ORDER.get(src_tk[0], 99)
            tgt_lane_ord = LANE_ORDER.get(tgt_tk[0], 99)

            if src_lane_ord < tgt_lane_ord:
                # Check target for secondary platforms (e.g. dbt-merged nodes)
                tgt_rm = tgt_node.raw_metadata or {}
                tgt_discovered = set(dp.lower() for dp in tgt_rm.get("discovered_platforms", []))
                # dbt fallback
                if (tgt_node.platform or "").lower() != "dbt" and not tgt_discovered.intersection({"dbt", "dbt_core"}):
                    if tgt_rm.get("dbt_resource_type") in ("model", "seed", "snapshot"):
                        tgt_discovered.add("dbt")
                tgt_primary = (tgt_node.platform or "").lower()
                secondary = tgt_discovered - {tgt_primary}

                logger.debug(
                    "[LanePipelineOverview] Step 4a-ii: edge %s→%s, src_tk=%s, tgt_tk=%s, "
                    "tgt_discovered=%s, secondary=%s, _platform_to_tks keys=%s",
                    src_node.name, tgt_node.name, src_tk, tgt_tk,
                    tgt_discovered, secondary, list(_platform_to_tks.keys()),
                )

                # Find an intermediate tool key from secondary platforms
                intermediate_tk = None
                for sec_plat in sorted(secondary):
                    for candidate_tk in _platform_to_tks.get(sec_plat, []):
                        mid_ord = LANE_ORDER.get(candidate_tk[0], 99)
                        logger.debug(
                            "[LanePipelineOverview] Step 4a-ii: sec_plat=%s candidate_tk=%s mid_ord=%d "
                            "src_lane_ord=%d tgt_lane_ord=%d",
                            sec_plat, candidate_tk, mid_ord, src_lane_ord, tgt_lane_ord,
                        )
                        if src_lane_ord < mid_ord < tgt_lane_ord:
                            intermediate_tk = candidate_tk
                            break
                    if not intermediate_tk:
                        p_info = get_platform(sec_plat)
                        if p_info:
                            for candidate_tk in _platform_to_tks.get(p_info.name, []):
                                mid_ord = LANE_ORDER.get(candidate_tk[0], 99)
                                if src_lane_ord < mid_ord < tgt_lane_ord:
                                    intermediate_tk = candidate_tk
                                    break
                    if intermediate_tk:
                        break

                if intermediate_tk:
                    _split_through_intermediate = True
                    _cross_tool += 1
                    # Only create the first leg (src→intermediate).
                    # The second leg (intermediate→tgt) is already covered by
                    # direct cross-tool edges (e.g. model→model edges resolved
                    # as dbt→analytics).  Emitting pk2 here would double-count
                    # the same flows that raw→dbt already shows.
                    pk1 = f"tool:{src_tk[0]}:{src_tk[1]}→tool:{intermediate_tk[0]}:{intermediate_tk[1]}"
                    _add_to_agg(pk1, edge, src_node.name, tgt_node.name,
                                src_node.id, tgt_node.id,
                                src_lane=src_tk[0], tgt_lane=intermediate_tk[0])

            if not _split_through_intermediate:
                # Suppress direct warehouse_raw→warehouse_analytics edges
                # for the same platform when a transformation tool exists
                # between them.  These edges are redundant — the split edges
                # from nodes that DO have discovered_platforms already
                # provide raw→transform and transform→analytics connections.
                src_plat_base = src_tk[1].split(":")[0]
                tgt_plat_base = tgt_tk[1].split(":")[0]
                if (src_plat_base == tgt_plat_base
                        and src_tk[0] == PipelineLane.WAREHOUSE_RAW.value
                        and tgt_tk[0] == PipelineLane.WAREHOUSE_ANALYTICS.value):
                    # Check if a transformation tool exists between these lanes
                    _has_transform = any(
                        tk[0] == PipelineLane.TRANSFORMATION.value
                        and info.get("asset_count", 0) > 0
                        for tk, info in tool_info.items()
                    )
                    if _has_transform:
                        continue

                # Debug: trace any same-platform cross-warehouse-lane edge
                if src_tk[0] != tgt_tk[0]:
                    logger.info(
                        "[LanePipelineOverview] CROSS-LANE edge: %s(%s)→%s(%s) "
                        "src_tk=%s tgt_tk=%s discovered_from=%s",
                        src_node.name, src_node.fqn, tgt_node.name, tgt_node.fqn,
                        src_tk, tgt_tk, edge.discovered_from,
                    )

                _cross_tool += 1
                pair_key = f"tool:{src_tk[0]}:{src_tk[1]}→tool:{tgt_tk[0]}:{tgt_tk[1]}"
                _add_to_agg(pair_key, edge, src_node.name, tgt_node.name,
                            src_node.id, tgt_node.id,
                            src_lane=src_tk[0], tgt_lane=tgt_tk[0])

        logger.info(
            "[LanePipelineOverview] Step 4a: %d total edges, %d control-plane, "
            "%d no tool key, %d same-tool (after merge check), %d cross-tool",
            len(self.graph.edges), _skip_control, _skip_no_tk,
            _skip_same, _cross_tool,
        )

        # 4b: Job-bypass edges (dataset→job→dataset compressed to dataset→dataset)
        # These supplement 4a by creating direct dataset→dataset links through
        # intermediate job nodes, adding evidence from both legs.
        # Also collect bypass drilldown metadata per pair_key.
        _bypass_drilldown: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for bp in self._compute_job_bypass_edges():
            src_node = self.graph.nodes.get(bp.upstream_id)
            tgt_node = self.graph.nodes.get(bp.downstream_id)
            if not src_node or not tgt_node:
                continue
            src_tk = node_to_tool.get(bp.upstream_id)
            tgt_tk = node_to_tool.get(bp.downstream_id)
            if not src_tk or not tgt_tk or src_tk == tgt_tk:
                continue
            pair_key = f"tool:{src_tk[0]}:{src_tk[1]}→tool:{tgt_tk[0]}:{tgt_tk[1]}"
            # Create a synthetic edge for the bypass
            up_edge = self.graph.edges.get(bp.upstream_edge_id)
            synth_edge = LineageEdge(
                id=f"bypass-{bp.upstream_id}-{bp.downstream_id}",
                source_id=bp.upstream_id,
                target_id=bp.downstream_id,
                edge_type=up_edge.edge_type if up_edge else EdgeType.DERIVED_FROM,
                confidence=bp.min_confidence,
                discovered_from="bridge:job_bypass",
            )
            _add_to_agg(pair_key, synth_edge, src_node.name, tgt_node.name,
                        src_node.id, tgt_node.id,
                        src_lane=src_tk[0], tgt_lane=tgt_tk[0])
            # Collect bypass drilldown (cap at 5 per pair)
            if len(_bypass_drilldown[pair_key]) < 5:
                _bypass_drilldown[pair_key].append({
                    "jobNodeId": bp.job_node_id,
                    "jobNodeName": bp.job_node_name,
                    "originalEdgeIds": [bp.upstream_edge_id, bp.downstream_edge_id],
                })

        # Build node-id-to-lane, node-id-to-platform, and node-id-to-role lookups
        view_node_lane: Dict[str, str] = {}
        view_node_platform: Dict[str, str] = {}
        view_node_role: Dict[str, str] = {}
        for vn in view_nodes:
            view_node_lane[vn.id] = vn.cluster_id
            view_node_platform[vn.id] = vn.platform
            view_node_role[vn.id] = vn.metadata.get("functionalRole", "")

        view_edges: List[ViewEdge] = []
        for pair_key in sorted(tool_edge_aggs.keys()):
            agg = tool_edge_aggs[pair_key]
            src_id, tgt_id = pair_key.split("→")
            src_lane = view_node_lane.get(src_id, "")
            tgt_lane = view_node_lane.get(tgt_id, "")
            src_plat = view_node_platform.get(src_id, "")
            tgt_plat = view_node_platform.get(tgt_id, "")
            src_cat = get_category(src_plat)
            tgt_cat = get_category(tgt_plat)
            src_role = view_node_role.get(src_id, "")
            tgt_role = view_node_role.get(tgt_id, "")
            ve = self._aggregate_tool_edge(
                pair_key, agg, src_lane, tgt_lane,
                src_category=src_cat.value if src_cat else None,
                tgt_category=tgt_cat.value if tgt_cat else None,
                evidence_type=DATA_DERIVATION,
                src_role=src_role or None,
                tgt_role=tgt_role or None,
            )
            # Attach bypass drilldown metadata if present
            drilldown = _bypass_drilldown.get(pair_key)
            if drilldown:
                ve.metadata["bypassPath"] = {
                    "jobs": drilldown,
                    "summary": f"via {', '.join(d['jobNodeName'] for d in drilldown[:3])}",
                }
            view_edges.append(ve)
            logger.info(
                "[LanePipelineOverview] Evidence edge: %s → %s (%d flows, %d assets, evidence_count=%d)",
                src_id, tgt_id, len(agg.edges), len(agg.asset_ids), ve.evidence_count,
            )

        logger.info(
            "[LanePipelineOverview] Step 4 total: %d evidence-based edges, %d tool-to-tool aggregations",
            sum(len(a.edges) for a in tool_edge_aggs.values()), len(tool_edge_aggs),
        )

        # ── Step 4c: Evidence-gated control-plane edges ────────────────
        # Control-plane edges must come from normalized evidence or
        # narrowly-scoped policy fallbacks, never from vendor-specific
        # assumptions or adjacency.
        #
        # Category pairs define WHICH tool categories CAN connect and
        # with what evidence type.  The _probe_control_plane_evidence()
        # function gates each candidate pair — if no evidence exists,
        # the edge is suppressed.
        _CP_CATEGORY_PAIRS: List[Tuple[str, frozenset, str]] = [
            ("orchestration", frozenset({"transformation", "ingestion"}), JOB_ORCHESTRATION),
            ("version_control", frozenset({"transformation", "orchestration"}), CODE_OWNERSHIP),
            ("infrastructure", frozenset({"warehouse", "ingestion", "orchestration", "transformation"}), HOSTING),
            ("quality", frozenset({"warehouse", "transformation"}), MONITORING),
        ]

        # Index view_nodes by category
        _cat_to_nodes: Dict[str, List[ViewNode]] = defaultdict(list)
        for vn in view_nodes:
            cat = get_category(vn.platform)
            if cat:
                _cat_to_nodes[cat.value].append(vn)

        # Collect existing evidence-based pair keys to avoid duplicates
        _existing_pairs: Set[str] = set()
        for pair_key in tool_edge_aggs:
            _existing_pairs.add(pair_key)

        _cp_count = 0
        _cp_suppressed = 0
        for src_cat, tgt_cats, ev_type in _CP_CATEGORY_PAIRS:
            for src_vn in _cat_to_nodes.get(src_cat, []):
                for tgt_cat in sorted(tgt_cats):
                    for tgt_vn in _cat_to_nodes.get(tgt_cat, []):
                        if src_vn.id == tgt_vn.id:
                            continue
                        pair_key = f"{src_vn.id}→{tgt_vn.id}"
                        if pair_key in _existing_pairs:
                            continue

                        # Evidence gate: probe for actual justification
                        probe_result = _probe_control_plane_evidence(
                            src_vn, tgt_vn, ev_type,
                            tool_info, tool_key_to_graph_nodes,
                            pipeline_edges=self.pipeline_edges,
                            tgt_category=tgt_cat,
                        )
                        if probe_result is None:
                            _cp_suppressed += 1
                            continue

                        basis, confidence = probe_result
                        _existing_pairs.add(pair_key)

                        sem_type, sem_label = derive_semantic_type(
                            src_cat, tgt_cat, ev_type,
                        )
                        sem_type, sem_label = enforce_semantic_constraints(
                            sem_type, sem_label, src_cat, tgt_cat, ev_type,
                        )

                        # Determine edge origin from evidence basis
                        edge_origin = BASIS_TO_EDGE_ORIGIN.get(basis, "evidence")
                        is_inferred = edge_origin == "inferred"

                        view_edges.append(ViewEdge(
                            id=f"cp-{pair_key}",
                            source_id=src_vn.id,
                            target_id=tgt_vn.id,
                            canonical_type=sem_type,
                            original_type=ev_type,
                            confidence=confidence,
                            inferred=is_inferred,
                            evidence_count=0,
                            metadata={
                                "semanticType": sem_type,
                                "label": sem_label,
                                "evidenceType": ev_type,
                                "edgeOrigin": edge_origin,
                                "relationshipBasis": basis,
                                "dataFlowCount": 0,
                            },
                        ))
                        _cp_count += 1
                        logger.info(
                            "[CP-Edge] %s --%s--> %s | basis=%s conf=%.2f origin=%s",
                            src_vn.name, sem_type, tgt_vn.name,
                            basis, confidence, edge_origin,
                        )

        if _cp_count or _cp_suppressed:
            logger.info(
                "[LanePipelineOverview] Step 4c: %d evidence-gated CP edges, "
                "%d suppressed (no evidence)",
                _cp_count, _cp_suppressed,
            )

        # ── Step 4b: Deduplicate ViewNodes by tool_id ─────────────────
        # Merge nodes for the same tool across different lanes into one
        # canonical node per tool.  Remap edge IDs accordingly.
        # Role-aware: warehouse platforms with both raw and analytics roles
        # are kept as separate nodes instead of being collapsed.
        _SPLITTABLE_ROLE_PAIRS = {
            frozenset({FunctionalRole.WAREHOUSE_RAW.value, FunctionalRole.WAREHOUSE_ANALYTICS.value}),
        }

        # Pre-pass: collect functional roles per canonical tool_id
        _tool_id_roles: Dict[str, Set[str]] = defaultdict(set)
        for vn in view_nodes:
            parts = vn.id.split(":", 2)
            canonical_tool_id = parts[2] if len(parts) >= 3 else vn.id
            role = vn.metadata.get("functionalRole", "")
            if role:
                _tool_id_roles[canonical_tool_id].add(role)

        def _should_split(canonical_tool_id: str) -> bool:
            roles = _tool_id_roles.get(canonical_tool_id, set())
            if len(roles) < 2:
                return False
            return frozenset(roles) in _SPLITTABLE_ROLE_PAIRS

        tool_id_groups: Dict[str, List[ViewNode]] = defaultdict(list)
        for vn in view_nodes:
            parts = vn.id.split(":", 2)  # ["tool", lane, tool_id]
            canonical_tool_id = parts[2] if len(parts) >= 3 else vn.id
            role = vn.metadata.get("functionalRole", "")
            if _should_split(canonical_tool_id) and role:
                group_key = f"{canonical_tool_id}:role:{role}"
            else:
                group_key = canonical_tool_id
            tool_id_groups[group_key].append(vn)

        # Collapse splits where one side has zero assets back to a single node
        _to_collapse: List[str] = []
        for group_key, group in tool_id_groups.items():
            if ":role:" in group_key:
                total = sum(vn.metadata.get("assetCount", 0) for vn in group)
                if total == 0:
                    _to_collapse.append(group_key)
        for key in _to_collapse:
            base = key.split(":role:")[0]
            sibling_keys = [
                k for k in tool_id_groups
                if k.startswith(base + ":role:") and k != key
            ]
            if sibling_keys:
                # Merge empty side into the non-empty sibling
                tool_id_groups[sibling_keys[0]].extend(tool_id_groups.pop(key))
            else:
                # No sibling — rename to base key (unsplit)
                tool_id_groups[base] = tool_id_groups.pop(key)

        old_id_to_new_id: Dict[str, str] = {}
        merged_view_nodes: List[ViewNode] = []

        _ROLE_DISPLAY: Dict[str, str] = {
            "warehouse_raw": "Raw",
            "warehouse_analytics": "Analytics",
            "orchestration": "Orchestration",
            "ingestion": "Ingestion",
            "quality": "Quality",
            "version_control": "Version Control",
            "infrastructure": "Infrastructure",
        }

        for canonical_tool_id, group in sorted(tool_id_groups.items()):
            new_id = f"tool:{canonical_tool_id}"
            platform = group[0].platform

            # Derive role-qualified display name for split nodes
            _is_split = ":role:" in canonical_tool_id
            _split_role = canonical_tool_id.split(":role:")[-1] if _is_split else ""
            # Prefer schema names over generic "Raw"/"Analytics" when available
            _group_schemas = sorted({
                s for vn in group
                for s in (vn.metadata.get("schemas") or [])
            })
            if _group_schemas and _is_split:
                _role_suffix = ", ".join(_group_schemas)
            else:
                _role_suffix = _ROLE_DISPLAY.get(_split_role, _split_role.replace("_", " ").title()) if _is_split else ""

            for vn in group:
                old_id_to_new_id[vn.id] = new_id

            if len(group) == 1:
                vn = group[0]
                original_lane = vn.metadata.get("lane")
                vn.id = new_id
                if _role_suffix:
                    vn.name = f"{vn.name} · {_role_suffix}"
                vn.layer = _platform_to_layer(platform)
                vn.cluster_id = vn.layer
                vn.metadata["lanes"] = [original_lane] if original_lane else []
                merged_view_nodes.append(vn)
            else:
                # Merge multiple lane-specific nodes into one
                merged_health = {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0, "stale": 0}
                total_assets = 0
                total_jobs = 0
                total_sub_count = 0
                all_sub_nodes: List[Dict[str, Any]] = []
                all_gaps: Set[str] = set()
                all_lanes: List[str] = []
                last_run_ts: Optional[str] = None
                is_orchestrator = False
                is_infra = False
                from_pipeline_stack = False

                for vn in group:
                    meta = vn.metadata
                    total_assets += meta.get("assetCount", 0)
                    total_jobs += meta.get("jobCount", 0)
                    total_sub_count += meta.get("totalSubNodeCount", 0)

                    hs = meta.get("healthSummary", {})
                    for k in merged_health:
                        merged_health[k] += hs.get(k, 0)

                    sub = meta.get("subNodes", [])
                    if len(all_sub_nodes) < 20:
                        all_sub_nodes.extend(sub[:20 - len(all_sub_nodes)])

                    for gap in meta.get("coverageGaps", []):
                        all_gaps.add(gap)

                    lane_name = meta.get("lane")
                    if lane_name:
                        all_lanes.append(lane_name)

                    if meta.get("lastRunTs"):
                        if last_run_ts is None or meta["lastRunTs"] > last_run_ts:
                            last_run_ts = meta["lastRunTs"]

                    is_orchestrator = is_orchestrator or meta.get("isOrchestrator", False)
                    is_infra = is_infra or meta.get("isInfra", False)
                    from_pipeline_stack = from_pipeline_stack or meta.get("fromPipelineStack", False)

                # Pick the most informative functional role from the group
                merged_role = group[0].metadata.get("functionalRole", "")

                _display_name = f"{group[0].name} · {_role_suffix}" if _role_suffix else group[0].name
                merged_view_nodes.append(ViewNode(
                    id=new_id,
                    name=_display_name,
                    canonical_type="service",
                    original_type="service",
                    platform=platform,
                    platform_domain=group[0].platform_domain,
                    layer=_platform_to_layer(platform),
                    cluster_id=_platform_to_layer(platform),
                    x=0, y=0,
                    inferred=False,
                    needs_mapping=False,
                    metadata={
                        "lanes": sorted(all_lanes, key=lambda l: LANE_ORDER.get(l, 99)),
                        "assetCount": total_assets,
                        "integrationId": group[0].metadata.get("integrationId"),
                        "isOrchestrator": is_orchestrator,
                        "isInfra": is_infra,
                        "fromPipelineStack": from_pipeline_stack,
                        "functionalRole": merged_role,
                        "healthSummary": merged_health,
                        "jobCount": total_jobs,
                        "lastRunTs": last_run_ts,
                        "coverageGaps": sorted(all_gaps),
                        "subNodes": all_sub_nodes,
                        "totalSubNodeCount": total_sub_count,
                    },
                ))

        view_nodes = merged_view_nodes

        # Remap edge source/target IDs to canonical tool IDs
        for edge in view_edges:
            edge.source_id = old_id_to_new_id.get(edge.source_id, edge.source_id)
            edge.target_id = old_id_to_new_id.get(edge.target_id, edge.target_id)

        # Merge duplicate edges (same source+target after remap) and drop self-loops
        edge_map: Dict[Tuple[str, str], ViewEdge] = {}
        for edge in view_edges:
            if edge.source_id == edge.target_id:
                continue  # drop self-loops created by merge
            key = (edge.source_id, edge.target_id)
            if key in edge_map:
                existing = edge_map[key]
                existing.evidence_count += edge.evidence_count
                existing.confidence = max(existing.confidence, edge.confidence)
                existing.metadata["dataFlowCount"] = (
                    existing.metadata.get("dataFlowCount", 0)
                    + edge.metadata.get("dataFlowCount", 0)
                )
                if not edge.inferred:
                    existing.inferred = False  # real edge overrides inferred
                    # Preserve semantics from the evidence-based edge
                    existing.metadata["semanticType"] = edge.metadata.get("semanticType", existing.metadata.get("semanticType"))
                    existing.metadata["label"] = edge.metadata.get("label", existing.metadata.get("label"))
                    existing.metadata["evidenceType"] = edge.metadata.get("evidenceType", existing.metadata.get("evidenceType"))
                # Evidence-backed origin wins over structural on merge
                if edge.metadata.get("edgeOrigin") == "evidence":
                    existing.metadata["edgeOrigin"] = "evidence"
            else:
                edge_map[key] = edge
        view_edges = list(edge_map.values())

        # ── Step 4c: Compute topological order per tool ─────────────────
        LAYER_LAYOUT_ORDER: Dict[str, int] = {
            "INGESTION": 0, "WAREHOUSE": 1, "TRANSFORMATION": 2,
            "ORCHESTRATION": 3, "REPORTING": 4, "INFRASTRUCTURE": 5,
            "VERSION_CONTROL": 6, "STORAGE": 7,
        }

        tool_topo_order: Dict[str, float] = {}
        for vn in view_nodes:
            upstream_orders: List[float] = []
            for edge in view_edges:
                if edge.target_id == vn.id:
                    src_node = next((n for n in view_nodes if n.id == edge.source_id), None)
                    if src_node:
                        upstream_orders.append(LAYER_LAYOUT_ORDER.get(src_node.layer, 99))
            tool_topo_order[vn.id] = (
                sum(upstream_orders) / len(upstream_orders) if upstream_orders else -1
            )

        # ── Step 5: Skip empty layers, compact positions ──────────────
        by_layer: Dict[str, List[ViewNode]] = defaultdict(list)
        for vn in view_nodes:
            by_layer[vn.layer].append(vn)

        # Sort within each layer: orchestrators/infra last, then by pipeline flow order, then alphabetical
        for layer_name in by_layer:
            by_layer[layer_name].sort(key=lambda n: (
                1 if n.metadata.get("isOrchestrator") else 0,
                1 if n.metadata.get("isInfra") else 0,
                tool_topo_order.get(n.id, 0),
                n.name,
            ))

        # Only include layers that have tools, ordered by LAYER_LAYOUT_ORDER
        active_layers = sorted(
            [l for l in by_layer if by_layer[l]],
            key=lambda l: LAYER_LAYOUT_ORDER.get(l, 99),
        )

        # Assign compact positions (skip empty layers)
        layer_x_map: Dict[str, float] = {}
        for idx, layer_name in enumerate(active_layers):
            layer_x_map[layer_name] = idx * LANE_X_SPACING

        for layer_name, layer_nodes in by_layer.items():
            x = layer_x_map.get(layer_name, 0)
            for idx, vn in enumerate(layer_nodes):
                vn.x = x
                vn.y = idx * TOOL_Y_SPACING

        # ── Step 6: Build layer metadata (active layers only) ─────────
        LAYER_LABELS: Dict[str, str] = {
            "INGESTION": "Ingestion",
            "WAREHOUSE": "Warehouse",
            "TRANSFORMATION": "Transformation",
            "ORCHESTRATION": "Orchestration",
            "REPORTING": "Reporting",
            "INFRASTRUCTURE": "Infrastructure",
            "VERSION_CONTROL": "Version Control",
            "STORAGE": "Storage",
        }

        lanes: List[LaneMeta] = []
        for layer_name in active_layers:
            lanes.append(LaneMeta(
                name=layer_name,
                label=LAYER_LABELS.get(layer_name, layer_name),
                order=LAYER_LAYOUT_ORDER.get(layer_name, 99),
                x=layer_x_map.get(layer_name, 0),
                node_count=len(by_layer.get(layer_name, [])),
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
                layer_name: len(by_layer.get(layer_name, []))
                for layer_name in active_layers
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

    # ───────────────────────────────────────────────────────────────────────
    # Tool Details — on-demand detail view for a single tool node
    # ───────────────────────────────────────────────────────────────────────

    def build_tool_details(self, tool_view_id: str) -> Dict[str, Any]:
        """
        Build detailed inspection data for a single tool node.

        The tool_view_id comes from the lane-pipeline-overview response
        (e.g. "tool:transformation:dbt_core:abc123" or "tool:warehouse_raw:bigquery").

        Returns a dict with:
          - summary: health, counts, coverage gaps
          - tabs: domain-specific tab definitions
          - groups: items grouped by tab key
          - connections: upstream/downstream tool connections
        """
        # Parse tool_view_id → extract platform and optional integration_id.
        #
        # Lane overview format:  "tool:{lane}:{platform}:{integration_id}"
        #                    or  "tool:{lane}:{platform}"
        # Role-aware split:      "tool:{platform}:role:{role}"
        # Legacy/non-lane:       "tool:{platform}:{integration_id}"
        #                    or  "tool:{platform}"
        #                    or  "{platform}:{integration_id}"
        #                    or  "{platform}"
        _LANE_VALUES = {"ingestion", "warehouse_raw", "transformation",
                        "warehouse_analytics", "reporting"}

        prefix = "tool:"
        if tool_view_id.startswith(prefix):
            remainder = tool_view_id[len(prefix):]
        else:
            remainder = tool_view_id

        # Detect and strip ":role:{role}" suffix (role-aware split IDs)
        role_filter: Optional[str] = None
        _role_marker = ":role:"
        role_idx = remainder.find(_role_marker)
        if role_idx != -1:
            role_filter = remainder[role_idx + len(_role_marker):]
            remainder = remainder[:role_idx]

        # If the first segment is a lane value, strip it
        parts = remainder.split(":", 1)
        if parts[0].lower() in _LANE_VALUES and len(parts) > 1:
            remainder = parts[1]  # skip the lane segment

        # Now remainder is "{platform}" or "{platform}:{integration_id}"
        parts = remainder.split(":", 1)
        platform = parts[0].lower()
        integration_id = parts[1] if len(parts) > 1 else None

        # Look up platform info — resolve aliases (e.g. "dbt" → "dbt_core")
        platform_info = get_platform(platform)
        category = platform_info.category.value if platform_info else "warehouse"
        platform_domain = _get_display_domain(platform)
        display_name = platform.title()

        # Build a set of platform names to match against (handle aliases)
        # e.g. "dbt_core" should also match nodes with platform="dbt" and vice versa
        platform_matches: Set[str] = {platform}
        if platform_info:
            platform_matches.add(platform_info.name)
            for alias in platform_info.aliases:
                platform_matches.add(alias)

        # Collect ALL graph nodes belonging to this tool (no cap)
        # Match by: (1) node.platform, (2) raw_metadata.discovered_platforms
        # The latter handles resolver-merged nodes (e.g. dbt models merged into
        # BigQuery nodes still have "dbt_core" in discovered_platforms).
        tool_nodes_list: List[LineageNode] = []
        tool_node_ids: Set[str] = set()
        primary_node_ids: Set[str] = set()  # Only direct platform matches (for connections)
        for node in self.graph.nodes.values():
            node_platform = (node.platform or "").lower()
            node_int_id = node.integration_id or ""

            # Check primary platform match (node.platform directly matches)
            primary_match = node_platform in platform_matches

            # Also check discovered_platforms (set by resolver after cross-tool merge)
            cross_tool_match = False
            if not primary_match:
                discovered = node.raw_metadata.get("discovered_platforms", [])
                if any(dp.lower() in platform_matches for dp in discovered):
                    cross_tool_match = True

            # Fallback: check dbt-specific metadata keys for cases where
            # discovered_platforms was lost during serialization.
            if not primary_match and not cross_tool_match and ("dbt" in platform_matches or "dbt_core" in platform_matches):
                if node.raw_metadata.get("dbt_resource_type") or node.raw_metadata.get("dbt_unique_id"):
                    cross_tool_match = True

            matched = primary_match or cross_tool_match

            if matched:
                # For cross-tool matches (discovered_platforms / metadata
                # fallback), skip integration_id filter — merged nodes carry
                # the winning tool's integration_id, not the secondary's.
                # Only enforce integration_id for primary platform matches.
                if integration_id and primary_match and not cross_tool_match:
                    if node_int_id != integration_id:
                        continue
                tool_nodes_list.append(node)
                tool_node_ids.add(node.id)
                if primary_match:
                    primary_node_ids.add(node.id)

        # If a role filter was extracted from the ID, narrow to that role's
        # nodes.  Fall back to the full set if filtering would empty it.
        if role_filter and len(tool_nodes_list) > 1:
            from .zones import resolve_functional_role
            filtered = [
                n for n in tool_nodes_list
                if resolve_functional_role(
                    n,
                    n.canonical_type or (n.raw_metadata or {}).get("canonical_type", "dataset"),
                ) == role_filter
            ]
            if filtered:
                tool_nodes_list = filtered
                tool_node_ids = {n.id for n in filtered}
                primary_node_ids = primary_node_ids & tool_node_ids

        logger.info(
            "[ToolDetails] %s → platform=%s, integration_id=%s, role_filter=%s, "
            "platform_matches=%s, matched_nodes=%d (graph_total=%d)",
            tool_view_id, platform, integration_id, role_filter,
            platform_matches, len(tool_nodes_list), len(self.graph.nodes),
        )

        # Update display name from pipeline tool_nodes if available
        for tn in self.tool_nodes:
            tn_type = (tn.get("toolType") or tn.get("tool_type") or "").lower()
            tn_int = tn.get("integrationId") or tn.get("integration_id") or ""
            if tn_type in platform_matches and (not integration_id or tn_int == integration_id):
                display_name = tn.get("name") or display_name
                break

        # Build shared summary
        health_summary = {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0, "stale": 0}
        job_count = 0
        last_run_ts: Optional[str] = None
        last_run_dt = None

        for gn in tool_nodes_list:
            status = gn.health_status.value if hasattr(gn, "health_status") and gn.health_status else "unknown"
            if status in health_summary:
                health_summary[status] += 1
            else:
                health_summary["unknown"] += 1
            if self._is_job_like(gn):
                job_count += 1
            if hasattr(gn, "observed_at") and gn.observed_at:
                if last_run_dt is None or gn.observed_at > last_run_dt:
                    last_run_dt = gn.observed_at
                    last_run_ts = gn.observed_at.isoformat()

        # Coverage gaps
        coverage_gaps: List[str] = []
        if not tool_nodes_list and _is_control_plane_category(category, platform):
            coverage_gaps.append("no_activity_data_yet")
        elif not tool_nodes_list:
            coverage_gaps.append("no_data_extracted")
        else:
            # Check sparse lineage
            tool_edge_count = 0
            for edge in self.graph.edges.values():
                if edge.plane == LinePlane.CONTROL:
                    continue
                if edge.source_id in tool_node_ids or edge.target_id in tool_node_ids:
                    tool_edge_count += 1
            if len(tool_nodes_list) > 5 and tool_edge_count < 2:
                coverage_gaps.append("sparse_lineage")

        # Domain-specific tabs and groups
        tabs, groups = self._build_domain_tabs(category, tool_nodes_list, tool_node_ids)

        # Build connections (upstream/downstream tools from graph edges)
        # Use primary_node_ids (direct platform matches only) so that
        # cross-tool merged nodes (e.g. BigQuery nodes with dbt in
        # discovered_platforms) are counted as separate tools, not lumped
        # into this tool.  This ensures dbt→BigQuery→Metabase shows
        # BigQuery as downstream of dbt, not Metabase.
        connections = self._build_tool_connections(primary_node_ids or tool_node_ids)

        # For control-plane tools, use tab group items as the asset count.
        # CP graph nodes are service-level (1 per integration), not
        # individual assets — the real count lives in the tab groups
        # (e.g. repos for VCS, DAGs for orchestration).
        total_assets = len(tool_nodes_list)
        if _is_control_plane_category(category, platform):
            group_count = sum(len(items) for items in groups.values())
            if group_count > 0:
                total_assets = group_count

        return {
            "toolId": tool_view_id,
            "platform": platform,
            "platformDomain": platform_domain,
            "category": category,
            "displayName": display_name,
            "integrationId": integration_id,
            "summary": {
                "totalAssets": total_assets,
                "healthSummary": health_summary,
                "jobCount": job_count,
                "lastRunTs": last_run_ts,
                "coverageGaps": coverage_gaps,
            },
            "tabs": tabs,
            "groups": groups,
            "connections": connections,
        }

    def _build_domain_tabs(
        self,
        category: str,
        nodes: List[LineageNode],
        tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Route to the correct domain-specific tab builder."""
        builders = {
            "ingestion": self._tabs_ingestion,
            "transformation": self._tabs_transform,
            "orchestration": self._tabs_orchestration,
            "warehouse": self._tabs_warehouse,
            "reporting": self._tabs_reporting,
            "infrastructure": self._tabs_infra,
            "quality": self._tabs_quality,
            "version_control": self._tabs_version_control,
        }
        builder = builders.get(category, self._tabs_generic)
        return builder(nodes, tool_node_ids)

    @staticmethod
    def _node_to_item(node: LineageNode) -> Dict[str, Any]:
        """Convert a graph node to a ToolDetailItem dict."""
        ct = node.canonical_type or ""
        return {
            "id": node.id,
            "name": node.name,
            "fqn": node.fqn or node.name,
            "canonicalType": ct,
            "originalType": getattr(node, "original_type", "") or (node.node_type.value if hasattr(node, "node_type") and node.node_type else "") or ct,
            "healthStatus": node.health_status.value if hasattr(node, "health_status") and node.health_status else "unknown",
            "observedAt": node.observed_at.isoformat() if hasattr(node, "observed_at") and node.observed_at else None,
            "container": node.schema or "",
            "zone": node.raw_metadata.get("zone", ""),
            "metadata": {
                k: v for k, v in node.raw_metadata.items()
                if isinstance(v, (str, int, float, bool, list))
            } if node.raw_metadata else {},
        }

    def _tabs_ingestion(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Ingestion tools: Connectors + Destinations."""
        connectors = []
        destinations = []
        for n in nodes:
            rm = n.raw_metadata or {}
            ct = n.canonical_type or ""
            if self._is_job_like(n) or rm.get("node_role") == "connector_job" or ct == "job":
                item = self._node_to_item(n)
                item["metadata"]["synced_tables"] = rm.get("synced_tables", [])
                item["metadata"]["dest_schema"] = rm.get("dest_schema", "")
                item["metadata"]["connector_id"] = rm.get("connector_id", "")
                connectors.append(item)
            elif ct == "dataset" or ct == "table" or ct == "view":
                item = self._node_to_item(n)
                item["container"] = rm.get("dest_schema") or n.schema or ""
                destinations.append(item)

        tabs = [
            {"key": "connectors", "label": "Connectors", "count": len(connectors)},
            {"key": "destinations", "label": "Destinations", "count": len(destinations)},
        ]
        groups = {"connectors": connectors, "destinations": destinations}
        return tabs, groups

    def _tabs_transform(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Transform tools: Models (by zone), Tests, Exposures."""
        models = []
        tests = []
        exposures = []
        for n in nodes:
            rm = n.raw_metadata or {}
            dbt_type = rm.get("dbt_resource_type", "")
            ct = n.canonical_type or ""

            if dbt_type in ("model", "seed", "snapshot") or (
                ct == "dataset" and not dbt_type
                and any(dp.lower() in ("dbt", "dbt_core") for dp in rm.get("discovered_platforms", []))
            ):
                item = self._node_to_item(n)
                # Classify zone
                zone = rm.get("zone", "")
                if not zone:
                    zone_enum = classify_dataset_zone(n)
                    zone = zone_enum.value if zone_enum else "unknown"
                item["zone"] = zone
                item["metadata"]["materialized"] = rm.get("materialized", "")
                item["metadata"]["dbt_resource_type"] = dbt_type
                models.append(item)
            elif dbt_type == "test" or ct == "test":
                item = self._node_to_item(n)
                tests.append(item)
            elif dbt_type == "exposure" or ct == "semantic":
                item = self._node_to_item(n)
                exposures.append(item)

        tabs = [
            {"key": "models", "label": "Models", "count": len(models)},
            {"key": "tests", "label": "Tests", "count": len(tests)},
            {"key": "exposures", "label": "Exposures", "count": len(exposures)},
        ]
        groups = {"models": models, "tests": tests, "exposures": exposures}
        return tabs, groups

    def _tabs_orchestration(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Orchestration tools: DAGs/Flows, Tasks."""
        dags = []
        tasks = []
        seen_dags: Set[str] = set()

        for n in nodes:
            rm = n.raw_metadata or {}
            ct = n.canonical_type or ""
            dag_id = rm.get("dag_id", "")
            ot = getattr(n, "original_type", "") or (n.node_type.value if hasattr(n, "node_type") and n.node_type else "") or ""

            if ot in ("dag", "workflow", "pipeline", "flow") or (ct == "job" and not dag_id):
                item = self._node_to_item(n)
                item["metadata"]["schedule"] = rm.get("schedule", "")
                item["metadata"]["task_count"] = rm.get("task_count", 0)
                dags.append(item)
                # Register by dag_id OR node.name to prevent synthetic duplicates
                effective_dag_id = dag_id or n.name
                if effective_dag_id:
                    seen_dags.add(effective_dag_id)
            elif dag_id and ct in ("job", "task", ""):
                # This is a task within a DAG
                item = self._node_to_item(n)
                item["container"] = dag_id
                item["metadata"]["operator"] = rm.get("operator", "")
                tasks.append(item)
                # Also track the DAG if we haven't seen it yet
                if dag_id not in seen_dags:
                    seen_dags.add(dag_id)
                    dags.append({
                        "id": f"dag:{dag_id}",
                        "name": dag_id,
                        "fqn": dag_id,
                        "canonicalType": "job",
                        "originalType": "dag",
                        "healthStatus": "unknown",
                        "observedAt": None,
                        "container": "",
                        "zone": "",
                        "metadata": {"synthetic": True},
                    })
            elif self._is_job_like(n):
                item = self._node_to_item(n)
                dags.append(item)

        # Count tasks per DAG for DAG items
        dag_task_counts: Dict[str, int] = defaultdict(int)
        for t in tasks:
            dag_task_counts[t.get("container", "")] += 1
        for d in dags:
            d_name = d.get("name", "")
            d["itemCount"] = dag_task_counts.get(d_name, 0)

        tabs = [
            {"key": "dags", "label": "DAGs / Flows", "count": len(dags)},
            {"key": "tasks", "label": "Tasks", "count": len(tasks)},
        ]
        groups = {"dags": dags, "tasks": tasks}
        return tabs, groups

    def _tabs_warehouse(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Warehouse tools: Datasets/Schemas, Tables & Views."""
        tables = []
        schema_counts: Dict[str, int] = defaultdict(int)
        schema_health: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0, "stale": 0}
        )

        for n in nodes:
            ct = n.canonical_type or ""
            if ct in ("service", "system"):
                continue
            item = self._node_to_item(n)
            schema_name = n.schema or "default"
            item["container"] = schema_name
            tables.append(item)
            schema_counts[schema_name] += 1
            status = item.get("healthStatus", "unknown")
            if status in schema_health[schema_name]:
                schema_health[schema_name][status] += 1

        # Build dataset (schema-level) summaries
        datasets = []
        for schema_name in sorted(schema_counts.keys()):
            datasets.append({
                "id": f"schema:{schema_name}",
                "name": schema_name,
                "fqn": schema_name,
                "canonicalType": "dataset",
                "originalType": "schema",
                "healthStatus": "healthy" if schema_health[schema_name]["failing"] == 0 and schema_health[schema_name]["degraded"] == 0 else "degraded" if schema_health[schema_name]["failing"] == 0 else "failing",
                "observedAt": None,
                "container": "",
                "itemCount": schema_counts[schema_name],
                "zone": "",
                "metadata": {"healthBreakdown": dict(schema_health[schema_name])},
            })

        tabs = [
            {"key": "datasets", "label": "Datasets / Schemas", "count": len(datasets)},
            {"key": "tables", "label": "Tables & Views", "count": len(tables)},
        ]
        groups = {"datasets": datasets, "tables": tables}
        return tabs, groups

    def _tabs_reporting(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Reporting/BI tools: Dashboards, Explores/Datasources."""
        dashboards = []
        explores = []
        for n in nodes:
            ct = n.canonical_type or ""
            ot = getattr(n, "original_type", "") or (n.node_type.value if hasattr(n, "node_type") and n.node_type else "") or ""
            rm = n.raw_metadata or {}
            if ct in ("service", "system"):
                continue
            item = self._node_to_item(n)

            if ot in ("dashboard", "report", "workbook") or ct == "semantic":
                item["metadata"]["view_count"] = rm.get("view_count", 0)
                item["metadata"]["project_name"] = rm.get("project_name", "")
                dashboards.append(item)
            elif ot in ("explore", "datasource", "model", "look", "data_source"):
                item["metadata"]["connection_type"] = rm.get("connection_type", "")
                explores.append(item)
            else:
                # Default: put in dashboards if semantic-like, else explores
                if ct in ("dataset", "table", "view"):
                    explores.append(item)
                else:
                    dashboards.append(item)

        tabs = [
            {"key": "dashboards", "label": "Dashboards", "count": len(dashboards)},
            {"key": "explores", "label": "Explores / Sources", "count": len(explores)},
        ]
        groups = {"dashboards": dashboards, "explores": explores}
        return tabs, groups

    def _tabs_infra(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Infrastructure tools: Services, Host info."""
        services = []
        host_items = []
        for n in nodes:
            rm = n.raw_metadata or {}
            item = self._node_to_item(n)

            # Extract running services
            running_services = rm.get("running_services", [])
            hosted_tools = rm.get("hosted_tools", [])
            if running_services or hosted_tools:
                for svc in running_services:
                    svc_name = svc if isinstance(svc, str) else svc.get("name", str(svc))
                    services.append({
                        "id": f"svc:{svc_name}",
                        "name": svc_name,
                        "fqn": svc_name,
                        "canonicalType": "service",
                        "originalType": "running_service",
                        "healthStatus": "unknown",
                        "observedAt": item.get("observedAt"),
                        "container": n.name,
                        "zone": "",
                        "metadata": {},
                    })
                for tool in hosted_tools:
                    tool_name = tool if isinstance(tool, str) else tool.get("name", str(tool))
                    services.append({
                        "id": f"hosted:{tool_name}",
                        "name": tool_name,
                        "fqn": tool_name,
                        "canonicalType": "service",
                        "originalType": "hosted_tool",
                        "healthStatus": "unknown",
                        "observedAt": item.get("observedAt"),
                        "container": n.name,
                        "zone": "",
                        "metadata": {},
                    })

            host_items.append(item)

        tabs = [
            {"key": "services", "label": "Services", "count": len(services)},
            {"key": "hosts", "label": "Hosts", "count": len(host_items)},
        ]
        groups = {"services": services, "hosts": host_items}
        return tabs, groups

    def _tabs_quality(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Quality tools: Monitors/Tests, Status."""
        monitors = []
        for n in nodes:
            item = self._node_to_item(n)
            rm = n.raw_metadata or {}
            item["metadata"]["total_tests"] = rm.get("health_total_tests", 0)
            item["metadata"]["failed_tests"] = rm.get("health_failed_tests", 0)
            monitors.append(item)

        # Aggregate status
        total_pass = sum(
            m["metadata"].get("total_tests", 0) - m["metadata"].get("failed_tests", 0)
            for m in monitors
        )
        total_fail = sum(m["metadata"].get("failed_tests", 0) for m in monitors)

        status_items = [{
            "id": "quality:summary",
            "name": "Test Summary",
            "fqn": "quality:summary",
            "canonicalType": "summary",
            "originalType": "summary",
            "healthStatus": "failing" if total_fail > 0 else "healthy",
            "observedAt": None,
            "container": "",
            "zone": "",
            "metadata": {"passing": total_pass, "failing": total_fail, "total": total_pass + total_fail},
        }]

        tabs = [
            {"key": "monitors", "label": "Monitors", "count": len(monitors)},
            {"key": "status", "label": "Status", "count": total_fail},
        ]
        groups = {"monitors": monitors, "status": status_items}
        return tabs, groups

    def _tabs_version_control(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Version control tools: Repositories only.

        Shows the repos whose code this VCS tool manages.
        Works with or without config on tool_nodes.
        """
        repo_items: List[Dict[str, Any]] = []
        seen_repo_ids: Set[str] = set()

        # VCS tools have no graph nodes (CONTROL_PLANE).
        # Pull repo data from pipeline tool_nodes config.
        _VCS_PLATFORMS = {"github", "gitlab", "bitbucket"}
        for tn in self.tool_nodes:
            tn_type = (tn.get("toolType") or tn.get("tool_type") or "").lower()
            if tn_type not in _VCS_PLATFORMS:
                continue

            config = tn.get("config") or tn.get("configuration") or {}
            repos = config.get("repos") or config.get("repositories") or []
            org = config.get("org") or config.get("organization") or config.get("owner") or ""
            logger.info("[VCS-Tabs] tool_node config: org=%r, repo=%r, repos=%r", org, config.get("repo"), repos)
            # Fallback: single repo field → synthesize a one-element list
            # But skip if repo equals the owner (frontend fallback, not a real repo)
            if not repos and config.get("repo"):
                single_repo = config["repo"]
                if single_repo != org:
                    repos = [single_repo]

            # Build repo items (dedup as we go)
            if isinstance(repos, list):
                for repo in repos[:50]:  # bounded
                    repo_name = repo if isinstance(repo, str) else (repo.get("name", str(repo)) if isinstance(repo, dict) else str(repo))
                    # If repo_name already contains owner prefix, don't double it
                    if "/" in repo_name:
                        display = repo_name
                        container = repo_name.split("/")[0]
                    else:
                        display = f"{org}/{repo_name}" if org else repo_name
                        container = org or "Ungrouped"
                    rid = f"repo:{display}"
                    if rid in seen_repo_ids:
                        continue
                    seen_repo_ids.add(rid)
                    repo_items.append({
                        "id": rid,
                        "name": display,
                        "fqn": display,
                        "canonicalType": "repository",
                        "originalType": "repository",
                        "healthStatus": "healthy",
                        "observedAt": None,
                        "container": container,
                        "zone": "",
                        "metadata": {},
                    })

        # ── Repos from graph nodes (adapter-classified pipeline repos) ──
        # The adapter now classifies each repo by scanning its file tree
        # and only stores repos containing pipeline tool code.
        # Note: `nodes` (tool_nodes_list) may be empty for VCS because
        # the platform matching might miss the adapter's service node.
        # Fall back to scanning ALL graph nodes for VCS platforms.
        vcs_graph_nodes = list(nodes)
        if not vcs_graph_nodes and self.graph:
            for gn in self.graph.nodes.values():
                gp = (gn.platform or "").lower()
                if gp in _VCS_PLATFORMS:
                    vcs_graph_nodes.append(gn)
        logger.debug("[VCS-Tabs] Config: %d items, graph nodes: %d", len(repo_items), len(vcs_graph_nodes))
        for n in vcs_graph_nodes:
            rm = n.raw_metadata or {}
            node_owner = rm.get("owner", "")
            graph_repos = rm.get("repositories") or []
            for r in graph_repos:
                if not isinstance(r, dict):
                    continue
                r_name = r.get("name", "")
                r_full = r.get("full_name", "")
                display = r_full or (f"{node_owner}/{r_name}" if node_owner else r_name)
                rid = f"repo:{display}"
                detected = r.get("detected_tools") or []

                if rid in seen_repo_ids:
                    # Enrich existing config repo with API metadata
                    for item in repo_items:
                        if item["id"] == rid:
                            item["metadata"]["defaultBranch"] = r.get("default_branch", "main")
                            item["metadata"]["private"] = r.get("private", False)
                            if detected:
                                item["metadata"]["detectedTools"] = detected
                    continue
                if not r_name:
                    continue

                seen_repo_ids.add(rid)
                repo_items.append({
                    "id": rid,
                    "name": display,
                    "fqn": display,
                    "canonicalType": "repository",
                    "originalType": "repository",
                    "healthStatus": "healthy",
                    "observedAt": None,
                    "container": node_owner or (display.split("/")[0] if "/" in display else "Ungrouped"),
                    "zone": "",
                    "metadata": {
                        "defaultBranch": r.get("default_branch", "main"),
                        "private": r.get("private", False),
                        "detectedTools": detected,
                    },
                })

        tabs = [
            {"key": "repos", "label": "Repositories", "count": len(repo_items)},
        ]
        groups = {"repos": repo_items}
        return tabs, groups

    def _tabs_generic(
        self, nodes: List[LineageNode], tool_node_ids: Set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Fallback for unknown tool categories."""
        jobs = []
        assets = []
        for n in nodes:
            item = self._node_to_item(n)
            if self._is_job_like(n):
                jobs.append(item)
            else:
                assets.append(item)

        tabs = [
            {"key": "jobs", "label": "Jobs", "count": len(jobs)},
            {"key": "assets", "label": "Assets", "count": len(assets)},
        ]
        groups = {"jobs": jobs, "assets": assets}
        return tabs, groups

    def _build_tool_connections(
        self, tool_node_ids: Set[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Find upstream and downstream tool connections from graph edges."""
        upstream: Dict[str, int] = defaultdict(int)   # remote_tool_key → edge_count
        downstream: Dict[str, int] = defaultdict(int)

        for edge in self.graph.edges.values():
            if edge.plane == LinePlane.CONTROL:
                continue
            src_in = edge.source_id in tool_node_ids
            tgt_in = edge.target_id in tool_node_ids

            if src_in and not tgt_in:
                # This tool produces → target is downstream consumer
                tgt_node = self.graph.nodes.get(edge.target_id)
                if tgt_node:
                    key = (tgt_node.platform or "unknown").lower()
                    downstream[key] += 1
            elif tgt_in and not src_in:
                # This tool consumes ← source is upstream producer
                src_node = self.graph.nodes.get(edge.source_id)
                if src_node:
                    key = (src_node.platform or "unknown").lower()
                    upstream[key] += 1

        def _to_list(counts: Dict[str, int]) -> List[Dict[str, Any]]:
            result = []
            for plat, count in sorted(counts.items(), key=lambda x: -x[1]):
                info = get_platform(plat)
                result.append({
                    "toolId": f"tool:{plat}",
                    "name": plat.title(),
                    "platform": plat,
                    "edgeCount": count,
                })
            return result

        return {
            "upstream": _to_list(upstream),
            "downstream": _to_list(downstream),
        }

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

        # Build bypass edges for JOB nodes: dataset→job→dataset → direct
        # dataset→dataset derives.  Uses shared helper.
        job_bypass_edges = self._compute_job_bypass_edges()

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


# ---------------------------------------------------------------------------
# Data-plane neighbor lookup (operates on serialized view dict)
# ---------------------------------------------------------------------------

def compute_neighbors_from_view(
    view_dict: Dict[str, Any],
    node_id: str,
    direction: str = "upstream",
    depth: int = 3,
    limit: int = 50,
) -> Dict[str, Any]:
    """BFS neighbors from a pre-computed RenderedView dict.

    This function operates on the *serialized* data_plane view (the same dict
    that the frontend renders), guaranteeing that the detail panel shows the
    exact same topology the user sees in the Data Plane graph.

    Args:
        view_dict: Serialized RenderedView (from ``to_dict()``).
        node_id: The starting node.
        direction: ``"upstream"`` or ``"downstream"``.
        depth: Maximum BFS hops (1-5).
        limit: Maximum total neighbor nodes returned.

    Returns:
        Dict with ``nodeId``, ``direction``, ``depth``, ``neighbors``
        (list of hop groups), ``totalCount``, and ``source`` indicator.
    """
    nodes_list = view_dict.get("nodes") or []
    edges_list = view_dict.get("edges") or []

    node_lookup: Dict[str, Dict[str, Any]] = {n["id"]: n for n in nodes_list}

    if node_id not in node_lookup:
        return {
            "nodeId": node_id,
            "direction": direction,
            "depth": depth,
            "neighbors": [],
            "totalCount": 0,
            "source": "data_plane",
        }

    # Build adjacency: for upstream we walk edges backwards (target → source),
    # for downstream we walk forwards (source → target).
    adj: Dict[str, List[tuple]] = {}  # neighbour_key → [(peer_id, edge_dict)]
    for e in edges_list:
        src = e.get("sourceId") or e.get("source_id", "")
        tgt = e.get("targetId") or e.get("target_id", "")
        if direction == "upstream":
            adj.setdefault(tgt, []).append((src, e))
        else:
            adj.setdefault(src, []).append((tgt, e))

    # BFS
    visited: set = {node_id}
    frontier = [node_id]
    neighbors_by_hop: List[Dict[str, Any]] = []
    total = 0

    for hop in range(1, depth + 1):
        if not frontier or total >= limit:
            break
        next_frontier: List[str] = []
        hop_items: List[Dict[str, Any]] = []

        for current_id in frontier:
            for peer_id, edge_dict in adj.get(current_id, []):
                if peer_id in visited:
                    continue
                visited.add(peer_id)
                peer_node = node_lookup.get(peer_id)
                if peer_node is None:
                    continue
                hop_items.append({"node": peer_node, "edge": edge_dict})
                next_frontier.append(peer_id)
                total += 1
                if total >= limit:
                    break
            if total >= limit:
                break

        if hop_items:
            neighbors_by_hop.append({"hop": hop, "items": hop_items})
        frontier = next_frontier

    return {
        "nodeId": node_id,
        "direction": direction,
        "depth": depth,
        "neighbors": neighbors_by_hop,
        "totalCount": total,
        "source": "data_plane",
    }
