"""
Lineage Reconciliation Engine

Post-canonicalization phase that uses an LLM to analyze the graph for
structural issues (duplicates, disconnected components, missing bridge
nodes) and produce a structured JSON patch to make the pipeline flow
coherent from ingestion → warehouse → transform → reporting.

Pipeline position:
  Adapters → Resolver → Investigator → Canonicalize → [Reconciler] → ViewBuilder
"""

import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..graph import (
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from .canonical import (
    CanonicalEdgeType,
    CanonicalNodeType,
    canonicalize_graph_in_place,
)
from .ids import generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)

RECONCILER_SCHEMA_VERSION = "1.0"

# Reverse mapping: layer string → PlatformDomain
_LAYER_TO_DOMAIN: Dict[str, PlatformDomain] = {
    "ingestion": PlatformDomain.INGESTION,
    "warehouse_raw": PlatformDomain.WAREHOUSE,
    "warehouse_analytics": PlatformDomain.WAREHOUSE,
    "transformation": PlatformDomain.TRANSFORM,
    "reporting": PlatformDomain.BI,
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ReconcilerConfig:
    """Configuration for a reconciliation run."""
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: Optional[str] = None
    max_tokens: int = 8192
    temperature: float = 0.0
    dry_run: bool = False
    max_nodes_for_llm: int = 500
    max_edges_for_llm: int = 1000


@dataclass
class MergeSuggestion:
    keep_id: str
    merge_ids: List[str]
    reason: str
    confidence: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MergeSuggestion":
        return cls(
            keep_id=data.get("keep_canonical_id") or data["keep_id"],
            merge_ids=data.get("merge_these_canonical_ids") or data.get("merge_ids", []),
            reason=data.get("reason", ""),
            confidence=float(data.get("confidence", 0.0)),
        )


@dataclass
class AddNodePatch:
    canonical_id: str
    node_type: str  # system, service, job, dataset, semantic
    platform: str
    namespace: str
    display_name: str
    integration_id: str
    aliases: List[str]
    inferred: bool
    confidence: float
    reason: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AddNodePatch":
        return cls(
            canonical_id=data["canonical_id"],
            node_type=data["type"],
            platform=data.get("platform", "unknown"),
            namespace=data.get("namespace", ""),
            display_name=data.get("display_name", ""),
            integration_id=data.get("integration_id", ""),
            aliases=data.get("aliases", []),
            inferred=data.get("inferred", True),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", ""),
        )


@dataclass
class AddEdgePatch:
    from_id: str
    to_id: str
    edge_type: str  # hosts, runs, reads, writes, derives, serves
    inferred: bool
    confidence: float
    reason: str
    evidence_refs: List[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AddEdgePatch":
        return cls(
            from_id=data["from_id"],
            to_id=data["to_id"],
            edge_type=data["type"],
            inferred=data.get("inferred", True),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", ""),
            evidence_refs=data.get("evidence_refs", []),
        )


@dataclass
class LayerAssignment:
    canonical_id: str
    layer: str
    reason: str
    confidence: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LayerAssignment":
        return cls(
            canonical_id=data["canonical_id"],
            layer=data["layer"],
            reason=data.get("reason", ""),
            confidence=float(data.get("confidence", 0.0)),
        )


@dataclass
class UnknownItem:
    entity_ref: str
    issue: str
    suggested_action: str
    questions: List[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnknownItem":
        return cls(
            entity_ref=data.get("entity_ref", ""),
            issue=data.get("issue", ""),
            suggested_action=data.get("suggested_action", ""),
            questions=data.get("questions_to_confirm", []),
        )


@dataclass
class ReconciliationPatch:
    patch_version: str
    merge_suggestions: List[MergeSuggestion]
    add_nodes: List[AddNodePatch]
    add_edges: List[AddEdgePatch]
    layer_assignments: List[LayerAssignment]
    unknowns: List[UnknownItem]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patch_version": self.patch_version,
            "merge_suggestions": [
                {"keep_id": m.keep_id, "merge_ids": m.merge_ids,
                 "reason": m.reason, "confidence": m.confidence}
                for m in self.merge_suggestions
            ],
            "add_nodes": [
                {"canonical_id": n.canonical_id, "type": n.node_type,
                 "platform": n.platform, "namespace": n.namespace,
                 "display_name": n.display_name, "reason": n.reason,
                 "confidence": n.confidence, "inferred": n.inferred}
                for n in self.add_nodes
            ],
            "add_edges": [
                {"from_id": e.from_id, "to_id": e.to_id,
                 "type": e.edge_type, "confidence": e.confidence,
                 "reason": e.reason, "inferred": e.inferred}
                for e in self.add_edges
            ],
            "layer_assignments": [
                {"canonical_id": la.canonical_id, "layer": la.layer,
                 "reason": la.reason, "confidence": la.confidence}
                for la in self.layer_assignments
            ],
            "unknowns": [
                {"entity_ref": u.entity_ref, "issue": u.issue,
                 "suggested_action": u.suggested_action,
                 "questions": u.questions}
                for u in self.unknowns
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReconciliationPatch":
        return cls(
            patch_version=data.get("patch_version", RECONCILER_SCHEMA_VERSION),
            merge_suggestions=[
                MergeSuggestion.from_dict(m)
                for m in data.get("merge_suggestions", [])
            ],
            add_nodes=[
                AddNodePatch.from_dict(n) for n in data.get("add_nodes", [])
            ],
            add_edges=[
                AddEdgePatch.from_dict(e) for e in data.get("add_edges", [])
            ],
            layer_assignments=[
                LayerAssignment.from_dict(la)
                for la in data.get("layer_assignments", [])
            ],
            unknowns=[
                UnknownItem.from_dict(u) for u in data.get("unknowns", [])
            ],
        )

    @classmethod
    def empty(cls) -> "ReconciliationPatch":
        return cls(
            patch_version=RECONCILER_SCHEMA_VERSION,
            merge_suggestions=[],
            add_nodes=[],
            add_edges=[],
            layer_assignments=[],
            unknowns=[],
        )


@dataclass
class GraphDiagnostics:
    dataset_roots: List[Dict[str, Any]] = field(default_factory=list)
    disconnected_components: List[List[str]] = field(default_factory=list)
    suspected_duplicates: List[Dict[str, Any]] = field(default_factory=list)
    missing_links_hints: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_roots": self.dataset_roots,
            "disconnected_components": self.disconnected_components,
            "suspected_duplicates": self.suspected_duplicates,
            "missing_links_hints": self.missing_links_hints,
        }


@dataclass
class ReconciliationResult:
    success: bool
    patch: ReconciliationPatch
    diagnostics: GraphDiagnostics
    graph: Optional[LineageGraph] = None
    applied: Dict[str, int] = field(default_factory=dict)
    unknowns: List[UnknownItem] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    duration_ms: int = 0
    run_id: str = ""
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "patch": self.patch.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "applied": self.applied,
            "unknowns": [
                {"entity_ref": u.entity_ref, "issue": u.issue,
                 "suggested_action": u.suggested_action,
                 "questions": u.questions}
                for u in self.unknowns
            ],
            "validation_errors": self.validation_errors,
            "duration_ms": self.duration_ms,
            "run_id": self.run_id,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
        }


# ---------------------------------------------------------------------------
# DiagnosticsBuilder
# ---------------------------------------------------------------------------


class DiagnosticsBuilder:
    """Compute structural diagnostics from the lineage graph for LLM input."""

    def __init__(self, graph: LineageGraph):
        self.graph = graph

    def build(self) -> GraphDiagnostics:
        return GraphDiagnostics(
            dataset_roots=self._find_dataset_roots(),
            disconnected_components=self._find_disconnected_components(),
            suspected_duplicates=self._find_suspected_duplicates(),
            missing_links_hints=self._find_missing_links_hints(),
        )

    def _find_dataset_roots(self) -> List[Dict[str, Any]]:
        """Find DATASET-canonical nodes with no upstream edges."""
        roots = []
        for node_id, node in self.graph.nodes.items():
            if node.canonical_type != CanonicalNodeType.DATASET.value:
                continue
            upstream = self.graph._upstream.get(node_id, set())
            if not upstream:
                roots.append({
                    "node_id": node_id,
                    "name": node.name,
                    "fqn": node.fqn,
                    "platform": node.platform,
                    "platform_domain": node.platform_domain.value,
                })
        return roots

    def _find_disconnected_components(self) -> List[List[str]]:
        """Find connected components using BFS on undirected adjacency."""
        visited: Set[str] = set()
        components: List[List[str]] = []

        for node_id in self.graph.nodes:
            if node_id in visited:
                continue
            component: List[str] = []
            queue = deque([node_id])
            while queue:
                current = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                # Treat edges as undirected for component detection
                neighbors = set()
                neighbors.update(self.graph._upstream.get(current, set()))
                neighbors.update(self.graph._downstream.get(current, set()))
                for neighbor in neighbors:
                    if neighbor not in visited and neighbor in self.graph.nodes:
                        queue.append(neighbor)
            if len(component) >= 2:
                components.append(component)

        # Sort by size descending; exclude the largest (main component)
        components.sort(key=len, reverse=True)
        if len(components) > 1:
            return components[1:]  # everything except the main component
        return []

    def _find_suspected_duplicates(self) -> List[Dict[str, Any]]:
        """Find node pairs that might be the same asset based on name."""
        # Group by normalized name (lowercase, last segment of FQN)
        name_groups: Dict[str, List[str]] = defaultdict(list)
        for node_id, node in self.graph.nodes.items():
            normalized = normalize_identifier(node.name)
            name_groups[normalized].append(node_id)

        duplicates = []
        for name, ids in name_groups.items():
            if len(ids) < 2:
                continue
            # Check if they're different platforms (potential cross-adapter dupe)
            nodes = [self.graph.nodes[nid] for nid in ids]
            platforms = {n.platform for n in nodes}
            if len(platforms) > 1:
                duplicates.append({
                    "name": name,
                    "node_ids": ids,
                    "platforms": list(platforms),
                    "reason": "Same name across different platforms",
                })
        return duplicates

    def _find_missing_links_hints(self) -> List[Dict[str, Any]]:
        """Infer where edges are probably missing."""
        hints = []

        # Collect integrations present
        integrations = set()
        for node in self.graph.nodes.values():
            if node.platform:
                integrations.add(node.platform.lower())

        from .platforms import INGESTION_PLATFORMS
        ingestion_tools = integrations & INGESTION_PLATFORMS

        # If ingestion tools exist but raw datasets have no upstream
        dataset_roots = self._find_dataset_roots()
        raw_roots = [
            r for r in dataset_roots
            if r.get("platform_domain") == "warehouse"
        ]
        if ingestion_tools and raw_roots:
            hints.append({
                "description": (
                    f"Ingestion tools {list(ingestion_tools)} are present but "
                    f"{len(raw_roots)} warehouse datasets have no upstream edges. "
                    f"These tools likely write to those raw datasets."
                ),
                "ingestion_tools": list(ingestion_tools),
                "orphan_datasets": [r["node_id"] for r in raw_roots],
            })

        # If transform tools exist but no warehouse_analytics datasets
        from .platforms import TRANSFORM_PLATFORMS
        transform_tools = integrations & TRANSFORM_PLATFORMS
        if transform_tools:
            transform_nodes = [
                n for n in self.graph.nodes.values()
                if n.platform and n.platform.lower() in transform_tools
            ]
            if transform_nodes:
                has_downstream = any(
                    self.graph._downstream.get(n.id, set())
                    for n in transform_nodes
                    if n.canonical_type == CanonicalNodeType.DATASET.value
                )
                if not has_downstream:
                    hints.append({
                        "description": (
                            f"Transform tools {list(transform_tools)} produce "
                            f"datasets but no downstream reporting edges found."
                        ),
                    })

        return hints

    def build_llm_input(
        self,
        config: ReconcilerConfig,
        diagnostics: Optional[GraphDiagnostics] = None,
    ) -> Dict[str, Any]:
        """Build the full input JSON for the LLM prompt."""
        diag = diagnostics or self.build()

        # Collect integrations from unique (platform, integration_id) pairs
        integrations = set()
        for node in self.graph.nodes.values():
            if node.platform:
                integrations.add(node.platform.lower())

        # Collect diagnostic node IDs for prioritization
        priority_ids: Set[str] = set()
        for root in diag.dataset_roots:
            priority_ids.add(root["node_id"])
        for dup in diag.suspected_duplicates:
            priority_ids.update(dup.get("node_ids", []))
        for comp in diag.disconnected_components:
            priority_ids.update(comp)

        # Serialize nodes (prioritize diagnostic nodes)
        all_node_ids = list(self.graph.nodes.keys())
        priority_list = [nid for nid in all_node_ids if nid in priority_ids]
        rest = [nid for nid in all_node_ids if nid not in priority_ids]
        ordered_ids = priority_list + rest
        truncated_ids = ordered_ids[:config.max_nodes_for_llm]

        canonical_nodes = []
        for nid in truncated_ids:
            node = self.graph.nodes[nid]
            canonical_nodes.append({
                "canonical_id": nid,
                "type": node.canonical_type or "dataset",
                "platform": node.platform or "unknown",
                "display_name": node.name,
                "namespace": node.namespace or "",
                "fqn": node.fqn,
                "integration_id": node.integration_id or "",
                "aliases": list({node.fqn, node.name} - {None, ""}),
                "inferred": node.inferred,
                "confidence": node.confidence if hasattr(node, "confidence") else 1.0,
                "platform_domain": node.platform_domain.value,
            })

        # Serialize edges (truncate)
        all_edges = list(self.graph.edges.values())
        truncated_edges = all_edges[:config.max_edges_for_llm]
        canonical_edges = []
        for edge in truncated_edges:
            canonical_edges.append({
                "from_id": edge.source_id,
                "to_id": edge.target_id,
                "type": edge.canonical_edge_type or "derives",
                "inferred": edge.inferred,
                "confidence": edge.confidence,
                "evidence": [
                    {"adapter_id": e.adapter_id, "source_ref": e.source_ref}
                    for e in edge.evidence[:3]  # limit evidence per edge
                ],
            })

        # Build evidence summary (per-adapter counts)
        adapter_counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"nodes": 0, "edges": 0}
        )
        for node in self.graph.nodes.values():
            for src in node.sources:
                adapter_counts[src]["nodes"] += 1
        for edge in self.graph.edges.values():
            for ev in edge.evidence:
                adapter_counts[ev.adapter_id]["edges"] += 1

        evidence_summary = {
            adapter: {"node_count": counts["nodes"], "edge_count": counts["edges"]}
            for adapter, counts in adapter_counts.items()
        }

        return {
            "integrations_present": sorted(integrations),
            "canonical_nodes": canonical_nodes,
            "canonical_edges": canonical_edges,
            "evidence_summary": evidence_summary,
            "graph_diagnostics": diag.to_dict(),
        }


# ---------------------------------------------------------------------------
# PatchValidator
# ---------------------------------------------------------------------------


class PatchValidator:
    """Validate a reconciliation patch against the current graph state."""

    def __init__(self, graph: LineageGraph):
        self.graph = graph
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate(self, patch: ReconciliationPatch) -> bool:
        """Run all validation checks. Returns True if patch is safe to apply."""
        self.errors = []
        self.warnings = []

        self._validate_version(patch.patch_version)
        self._validate_merges(patch.merge_suggestions)

        # Collect pending node IDs from add_nodes
        pending_ids = {n.canonical_id for n in patch.add_nodes}
        self._validate_add_nodes(patch.add_nodes)
        self._validate_add_edges(patch.add_edges, pending_ids)
        self._validate_layer_assignments(patch.layer_assignments, pending_ids)

        if self.errors:
            logger.warning(
                "Patch validation failed with %d errors: %s",
                len(self.errors), "; ".join(self.errors[:5]),
            )
        return len(self.errors) == 0

    def _validate_version(self, version: str) -> None:
        if version != RECONCILER_SCHEMA_VERSION:
            self.warnings.append(
                f"Patch version {version} != expected {RECONCILER_SCHEMA_VERSION}"
            )

    def _validate_merges(self, merges: List[MergeSuggestion]) -> None:
        all_keep = set()
        all_remove: Set[str] = set()

        for merge in merges:
            # Check keep_id exists
            if merge.keep_id not in self.graph.nodes:
                self.errors.append(
                    f"Merge keep_id '{merge.keep_id}' not found in graph"
                )
            # Check merge_ids exist
            for mid in merge.merge_ids:
                if mid not in self.graph.nodes:
                    self.errors.append(
                        f"Merge target '{mid}' not found in graph"
                    )
                if mid in all_keep:
                    self.errors.append(
                        f"Circular merge: '{mid}' is both kept and merged"
                    )
                if mid in all_remove:
                    self.errors.append(
                        f"Duplicate merge target: '{mid}' appears in multiple merges"
                    )
                all_remove.add(mid)

            if merge.keep_id in all_remove:
                self.errors.append(
                    f"Circular merge: '{merge.keep_id}' is both kept and merged"
                )
            all_keep.add(merge.keep_id)

            # Confidence range
            if not 0.0 <= merge.confidence <= 1.0:
                self.errors.append(
                    f"Merge confidence {merge.confidence} out of range [0, 1]"
                )

    def _validate_add_nodes(self, nodes: List[AddNodePatch]) -> None:
        valid_types = {t.value for t in CanonicalNodeType}
        seen_ids: Set[str] = set()

        for node in nodes:
            if node.node_type not in valid_types:
                self.errors.append(
                    f"Invalid node type '{node.node_type}' for '{node.canonical_id}'"
                )
            if node.canonical_id in self.graph.nodes:
                self.warnings.append(
                    f"Node '{node.canonical_id}' already exists (will skip)"
                )
            if node.canonical_id in seen_ids:
                self.errors.append(
                    f"Duplicate add_node ID: '{node.canonical_id}'"
                )
            seen_ids.add(node.canonical_id)
            if not 0.0 <= node.confidence <= 1.0:
                self.errors.append(
                    f"Node confidence {node.confidence} out of range [0, 1]"
                )

    def _validate_add_edges(
        self, edges: List[AddEdgePatch], pending_ids: Set[str],
    ) -> None:
        valid_types = {t.value for t in CanonicalEdgeType}
        existing_ids = set(self.graph.nodes.keys())
        valid_ids = existing_ids | pending_ids

        for edge in edges:
            if edge.edge_type not in valid_types:
                self.errors.append(
                    f"Invalid edge type '{edge.edge_type}' for "
                    f"'{edge.from_id}' → '{edge.to_id}'"
                )
            if edge.from_id not in valid_ids:
                self.errors.append(
                    f"Edge source '{edge.from_id}' not found in graph or add_nodes"
                )
            if edge.to_id not in valid_ids:
                self.errors.append(
                    f"Edge target '{edge.to_id}' not found in graph or add_nodes"
                )
            if not 0.0 <= edge.confidence <= 1.0:
                self.errors.append(
                    f"Edge confidence {edge.confidence} out of range [0, 1]"
                )

    def _validate_layer_assignments(
        self, assignments: List[LayerAssignment], pending_ids: Set[str],
    ) -> None:
        valid_layers = set(_LAYER_TO_DOMAIN.keys())
        existing_ids = set(self.graph.nodes.keys())
        valid_ids = existing_ids | pending_ids

        for la in assignments:
            if la.canonical_id not in valid_ids:
                self.errors.append(
                    f"Layer assignment for '{la.canonical_id}' not found"
                )
            if la.layer not in valid_layers:
                self.warnings.append(
                    f"Unrecognized layer '{la.layer}' for '{la.canonical_id}' "
                    f"(valid: {valid_layers})"
                )


# ---------------------------------------------------------------------------
# PatchApplier
# ---------------------------------------------------------------------------


# Mapping from canonical edge type string → EdgeType for the edge_type field
_CANONICAL_TO_EDGE_TYPE: Dict[str, EdgeType] = {
    "hosts": EdgeType.TRIGGERS,
    "runs": EdgeType.TRIGGERS,
    "reads": EdgeType.READS_FROM,
    "writes": EdgeType.WRITES_TO,
    "derives": EdgeType.DERIVED_FROM,
    "serves": EdgeType.QUERIES,
}

# Mapping from canonical node type string → NodeType
_CANONICAL_TO_NODE_TYPE: Dict[str, NodeType] = {
    "system": NodeType.UNKNOWN,
    "service": NodeType.CONNECTOR,
    "job": NodeType.TASK,
    "dataset": NodeType.TABLE,
    "semantic": NodeType.DASHBOARD,
}


class PatchApplier:
    """Apply a validated reconciliation patch to the graph.

    Uses a graph-rebuild approach for merges to maintain index consistency.
    """

    def __init__(self, graph: LineageGraph, run_id: str):
        self.graph = graph
        self.run_id = run_id
        self.remap: Dict[str, str] = {}  # removed_id → kept_id

    def apply(self, patch: ReconciliationPatch) -> Dict[str, int]:
        """Apply the full patch. Returns counts of applied operations."""
        counts = {
            "merges": 0, "nodes_added": 0,
            "edges_added": 0, "layers_assigned": 0,
        }

        # Step 1: Apply merges (rebuild graph)
        if patch.merge_suggestions:
            counts["merges"] = self._apply_merges(patch.merge_suggestions)

        # Step 2: Add new nodes
        for node_patch in patch.add_nodes:
            if self._apply_add_node(node_patch):
                counts["nodes_added"] += 1

        # Step 3: Add new edges
        for edge_patch in patch.add_edges:
            if self._apply_add_edge(edge_patch):
                counts["edges_added"] += 1

        # Step 4: Apply layer assignments
        for la in patch.layer_assignments:
            if self._apply_layer_assignment(la):
                counts["layers_assigned"] += 1

        return counts

    def _apply_merges(self, merges: List[MergeSuggestion]) -> int:
        """Merge nodes by rebuilding the graph without merged nodes."""
        merged_ids: Set[str] = set()
        count = 0

        for merge in merges:
            keep_node = self.graph.nodes.get(merge.keep_id)
            if not keep_node:
                logger.warning("Merge keep_id '%s' not found, skipping", merge.keep_id)
                continue

            for remove_id in merge.merge_ids:
                remove_node = self.graph.nodes.get(remove_id)
                if not remove_node:
                    logger.warning("Merge target '%s' not found, skipping", remove_id)
                    continue
                # Merge metadata into keeper
                _merge_node_metadata(keep_node, remove_node)
                keep_node.evidence.append(Evidence(
                    adapter_id="reconciler",
                    source_ref=f"merge:{remove_id}",
                    snippet=merge.reason[:200],
                ))
                keep_node.raw_metadata["reconciler_run_id"] = self.run_id
                self.remap[remove_id] = merge.keep_id
                merged_ids.add(remove_id)
                count += 1

        if not merged_ids:
            return 0

        # Rebuild graph without merged nodes
        new_graph = LineageGraph()
        for node_id, node in self.graph.nodes.items():
            if node_id not in merged_ids:
                new_graph.add_node(node)

        # Remap edges and add to new graph
        seen_edge_keys: Set[Tuple[str, str, str]] = set()
        for edge in self.graph.edges.values():
            src = self.remap.get(edge.source_id, edge.source_id)
            tgt = self.remap.get(edge.target_id, edge.target_id)
            if src not in new_graph.nodes or tgt not in new_graph.nodes:
                continue
            if src == tgt:
                continue
            edge_key = (src, tgt, edge.canonical_edge_type or edge.edge_type.value)
            if edge_key in seen_edge_keys:
                continue
            seen_edge_keys.add(edge_key)
            edge.source_id = src
            edge.target_id = tgt
            new_graph.add_edge(edge)

        # Replace graph in place
        self.graph.nodes = new_graph.nodes
        self.graph.edges = new_graph.edges
        self.graph._upstream = new_graph._upstream
        self.graph._downstream = new_graph._downstream
        self.graph._by_platform = new_graph._by_platform
        self.graph._by_type = new_graph._by_type
        self.graph._by_database = new_graph._by_database
        self.graph._by_lineage_level = new_graph._by_lineage_level
        self.graph._by_asset_kind = new_graph._by_asset_kind
        self.graph._by_confidence_bucket = new_graph._by_confidence_bucket
        self.graph._by_plane = new_graph._by_plane

        return count

    def _apply_add_node(self, patch: AddNodePatch) -> bool:
        """Create a new node from patch data."""
        # Skip if already exists (idempotency)
        if patch.canonical_id in self.graph.nodes:
            logger.info("Node '%s' already exists, skipping", patch.canonical_id)
            return False

        # Map canonical node type → NodeType
        node_type = _CANONICAL_TO_NODE_TYPE.get(patch.node_type, NodeType.UNKNOWN)

        # Map platform → PlatformDomain
        domain = _LAYER_TO_DOMAIN.get(
            patch.reason.lower() if "ingestion" in patch.reason.lower()
            else "",
            PlatformDomain.OTHER,
        )
        # Better domain inference from the node type + platform
        from .platforms import get_domain
        platform_lower = patch.platform.lower()
        inferred_domain = get_domain(platform_lower)
        if inferred_domain != PlatformDomain.OTHER:
            domain = inferred_domain

        node = LineageNode(
            id=patch.canonical_id,
            name=patch.display_name,
            fqn=patch.canonical_id,
            node_type=node_type,
            platform=patch.platform,
            namespace=patch.namespace,
            integration_id=patch.integration_id or None,
            platform_domain=domain,
            inferred=True,
            canonical_type=patch.node_type,
            evidence=[Evidence(
                adapter_id="reconciler",
                source_ref=f"reconciler:add_node",
                snippet=patch.reason[:200],
            )],
            raw_metadata={
                "reconciler_added": True,
                "reconciler_run_id": self.run_id,
                "reconciler_confidence": patch.confidence,
            },
        )
        node.sources = ["reconciler"]
        node.confidence = patch.confidence

        self.graph.add_node(node)
        return True

    def _apply_add_edge(self, patch: AddEdgePatch) -> bool:
        """Create a new edge from patch data."""
        # Remap IDs through any merges
        from_id = self.remap.get(patch.from_id, patch.from_id)
        to_id = self.remap.get(patch.to_id, patch.to_id)

        if from_id not in self.graph.nodes:
            logger.warning("Edge source '%s' not in graph, skipping", from_id)
            return False
        if to_id not in self.graph.nodes:
            logger.warning("Edge target '%s' not in graph, skipping", to_id)
            return False

        edge_type = _CANONICAL_TO_EDGE_TYPE.get(
            patch.edge_type, EdgeType.DERIVED_FROM,
        )
        edge_id = generate_edge_id(
            from_id, to_id, patch.edge_type, "table", "reconciler",
        )

        # Skip if edge already exists (idempotency)
        if edge_id in self.graph.edges:
            return False

        edge = LineageEdge(
            id=edge_id,
            source_id=from_id,
            target_id=to_id,
            edge_type=edge_type,
            confidence=patch.confidence,
            lineage_level=LineageLevel.TABLE,
            plane=LinePlane.DATA,
            canonical_edge_type=patch.edge_type,
            inferred=True,
            evidence=[Evidence(
                adapter_id="reconciler",
                source_ref="reconciler:add_edge",
                snippet=patch.reason[:200],
            )],
        )

        self.graph.add_edge(edge)
        return True

    def _apply_layer_assignment(self, la: LayerAssignment) -> bool:
        """Update a node's platform_domain based on layer assignment."""
        node_id = self.remap.get(la.canonical_id, la.canonical_id)
        node = self.graph.nodes.get(node_id)
        if not node:
            logger.warning("Layer target '%s' not in graph, skipping", node_id)
            return False

        domain = _LAYER_TO_DOMAIN.get(la.layer)
        if domain:
            node.platform_domain = domain
        node.raw_metadata["reconciler_layer"] = la.layer
        node.raw_metadata["reconciler_run_id"] = self.run_id
        return True


def _merge_node_metadata(primary: LineageNode, secondary: LineageNode) -> None:
    """Merge metadata from secondary node into primary.

    Mirrors the pattern from resolver.py.
    """
    if secondary.description and not primary.description:
        primary.description = secondary.description
    elif (
        secondary.description
        and secondary.platform_domain == PlatformDomain.TRANSFORM
        and primary.platform_domain == PlatformDomain.WAREHOUSE
    ):
        primary.description = secondary.description

    if secondary.owner and not primary.owner:
        primary.owner = secondary.owner

    primary.tags = list(set(primary.tags + secondary.tags))

    if secondary.row_count and not primary.row_count:
        primary.row_count = secondary.row_count

    if len(secondary.columns) > len(primary.columns):
        primary.columns = secondary.columns

    primary.sources = list(set(primary.sources + secondary.sources))

    if not primary.raw_metadata.get("dbt_resource_type"):
        dbt_resource = secondary.raw_metadata.get("dbt_resource_type")
        if dbt_resource and dbt_resource in ("model", "seed", "snapshot"):
            primary.raw_metadata["dbt_resource_type"] = dbt_resource

    if not primary.integration_id and secondary.integration_id:
        primary.integration_id = secondary.integration_id


# ---------------------------------------------------------------------------
# LLM Reconciler
# ---------------------------------------------------------------------------


RECONCILER_SYSTEM_PROMPT = """You are a Lineage Reconciliation Engine for a data pipeline observability platform.

Your job: take the extracted lineage evidence + current canonical graph, then propose a PATCH that makes the pipeline flow coherent and readable from ingestion → warehouse(raw) → transform → warehouse(marts) → reporting.

CRITICAL RULES:
1) Output MUST be valid JSON ONLY. No prose, no markdown, no trailing comments.
2) Do NOT invent integrations, datasets, or tools that are not present in the input.
3) Prefer adding INFERRED bridge nodes/edges over guessing merges.
4) Only propose merges when there is STRONG identifier evidence (same fully-qualified name, same URN, or explicit alias mapping).
5) Every node/edge you add must conform to allowed taxonomy and edge rules.
6) Any inference must be flagged inferred=true and must include a reason and confidence (0..1).
7) If uncertain, put items under "unknowns" instead of forcing a change.

ALLOWED NODE TYPES:
- system
- service
- job
- dataset
- semantic
(If something doesn't fit, do NOT add it; list it as unknown.)

ALLOWED EDGE TYPES:
- hosts (system -> service)
- runs  (service -> job)
- reads (job -> dataset)
- writes (job -> dataset)
- derives (dataset -> dataset)
- serves (dataset -> semantic)

LAYER GOAL FOR PIPELINE OVERVIEW:
We want a stable left-to-right flow with these layers:
- ingestion (sources + ingestors + loaders, e.g., API, n8n, airbyte)
- warehouse_raw (raw landing datasets)
- transformation (dbt/spark/sql transform jobs/services)
- warehouse_analytics (staging/intermediate/marts datasets)
- reporting (BI/semantic assets)

IMPORTANT: Node.type is NOT the same as layer. Datasets remain type="dataset". Use "layer_assignments" to classify how the UI should place nodes.

YOUR OUTPUT:
Return a JSON object with this exact schema:

{
  "patch_version": "1.0",
  "merge_suggestions": [
    {
      "keep_canonical_id": "string",
      "merge_these_canonical_ids": ["string"],
      "reason": "string",
      "confidence": 0.0
    }
  ],
  "add_nodes": [
    {
      "canonical_id": "string (stable URN-like)",
      "type": "system|service|job|dataset|semantic",
      "platform": "string",
      "namespace": "string",
      "display_name": "string",
      "integration_id": "string",
      "aliases": ["string"],
      "inferred": true,
      "confidence": 0.0,
      "reason": "string"
    }
  ],
  "add_edges": [
    {
      "from_id": "string",
      "to_id": "string",
      "type": "hosts|runs|reads|writes|derives|serves",
      "inferred": true,
      "confidence": 0.0,
      "reason": "string",
      "evidence_refs": ["string"]
    }
  ],
  "layer_assignments": [
    {
      "canonical_id": "string",
      "layer": "ingestion|warehouse_raw|transformation|warehouse_analytics|reporting",
      "reason": "string",
      "confidence": 0.0
    }
  ],
  "unknowns": [
    {
      "entity_ref": "string (node id or alias)",
      "issue": "string",
      "suggested_action": "string",
      "questions_to_confirm": ["string"]
    }
  ]
}

PATCH LOGIC YOU SHOULD APPLY (IN ORDER):
Step A) Fix obvious duplicates:
- If two dataset nodes refer to the same fully-qualified name (BigQuery project.dataset.table, Snowflake db.schema.table, etc.), propose a merge.
- If a node is the same asset but represented via alias vs URN, propose merge.

Step B) Fix "raw tables incorrectly appear as sources":
- If there is an ingestion integration present (e.g., n8n/airbyte/fivetran/custom loader) AND dataset_roots include warehouse raw datasets,
  then propose an inferred ingestion job node and writes edges to those raw datasets.
  Confidence should be low-to-medium (0.25-0.6) unless evidence_summary explicitly confirms the write mapping.

Step C) Ensure transformation actor exists:
- If dbt is present, datasets produced by dbt should be assigned to transformation/warehouse_analytics properly.

Step D) Assign layers for overview readability:
- n8n/airbyte/fivetran/API loaders → layer=ingestion
- raw landing datasets → layer=warehouse_raw
- dbt/spark/sql transform services/jobs → layer=transformation
- staging/intermediate/marts datasets → layer=warehouse_analytics
- BI dashboards/explores → layer=reporting

Step E) If you cannot confidently connect something:
- Do NOT guess. Put it in unknowns.

NOW PROCESS THE INPUT JSON PROVIDED IN THE USER MESSAGE.
Return ONLY the JSON patch response."""


class LLMReconciler:
    """Send graph diagnostics to an LLM and receive a structured patch."""

    def __init__(self, config: ReconcilerConfig):
        self.config = config
        self._anthropic_client = None
        self._openai_client = None

    async def reconcile(
        self,
        llm_input: Dict[str, Any],
    ) -> Tuple[ReconciliationPatch, int, int]:
        """Call the LLM and parse the patch response.

        Returns (patch, input_tokens, output_tokens).
        """
        input_json = json.dumps(llm_input, default=str)

        if self.config.provider == "anthropic":
            return await self._call_anthropic(input_json)
        elif self.config.provider == "openai":
            return await self._call_openai(input_json)
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

    async def _call_anthropic(
        self, input_json: str,
    ) -> Tuple[ReconciliationPatch, int, int]:
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required for reconciler")

        api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=3)

        response = await client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=RECONCILER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": input_json}],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        parsed = self._parse_json_response(raw_text)
        patch = ReconciliationPatch.from_dict(parsed)
        return patch, input_tokens, output_tokens

    async def _call_openai(
        self, input_json: str,
    ) -> Tuple[ReconciliationPatch, int, int]:
        try:
            import openai
        except ImportError:
            raise ImportError("openai package required for reconciler")

        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        client = openai.AsyncOpenAI(api_key=api_key, max_retries=3)

        response = await client.chat.completions.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": RECONCILER_SYSTEM_PROMPT},
                {"role": "user", "content": input_json},
            ],
        )

        raw_text = response.choices[0].message.content or "{}"
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        parsed = self._parse_json_response(raw_text)
        patch = ReconciliationPatch.from_dict(parsed)
        return patch, input_tokens, output_tokens

    def _parse_json_response(self, raw_text: str) -> Dict[str, Any]:
        """Extract JSON from LLM response text."""
        text = raw_text.strip()

        # Try direct JSON parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` fences
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding the first { ... } block
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        logger.error("Failed to parse LLM response as JSON: %s...", text[:200])
        return {}


# ---------------------------------------------------------------------------
# ReconciliationEngine (Orchestrator)
# ---------------------------------------------------------------------------


class ReconciliationEngine:
    """Top-level orchestrator for the reconciliation process."""

    def __init__(self, config: Optional[ReconcilerConfig] = None):
        self.config = config or ReconcilerConfig()

    async def reconcile(
        self,
        graph: LineageGraph,
    ) -> ReconciliationResult:
        """Run the full reconciliation pipeline."""
        start_time = time.time()
        run_id = uuid.uuid4().hex[:12]

        # Step 1: Build diagnostics
        builder = DiagnosticsBuilder(graph)
        diagnostics = builder.build()

        logger.info(
            "[Reconciler:%s] Diagnostics: %d dataset_roots, "
            "%d disconnected_components, %d suspected_duplicates, "
            "%d missing_links_hints",
            run_id,
            len(diagnostics.dataset_roots),
            len(diagnostics.disconnected_components),
            len(diagnostics.suspected_duplicates),
            len(diagnostics.missing_links_hints),
        )

        # If graph is trivially small or has no issues, skip LLM
        total_issues = (
            len(diagnostics.dataset_roots)
            + len(diagnostics.disconnected_components)
            + len(diagnostics.suspected_duplicates)
            + len(diagnostics.missing_links_hints)
        )
        if total_issues == 0:
            logger.info("[Reconciler:%s] No issues found, skipping LLM call", run_id)
            duration_ms = int((time.time() - start_time) * 1000)
            return ReconciliationResult(
                success=True,
                patch=ReconciliationPatch.empty(),
                diagnostics=diagnostics,
                graph=graph,
                applied={"merges": 0, "nodes_added": 0, "edges_added": 0, "layers_assigned": 0},
                duration_ms=duration_ms,
                run_id=run_id,
            )

        # Step 2: Build LLM input
        llm_input = builder.build_llm_input(self.config, diagnostics)

        # Step 3: Call LLM
        llm = LLMReconciler(self.config)
        try:
            patch, input_tokens, output_tokens = await llm.reconcile(llm_input)
        except Exception as e:
            logger.error("[Reconciler:%s] LLM call failed: %s", run_id, e)
            duration_ms = int((time.time() - start_time) * 1000)
            return ReconciliationResult(
                success=False,
                patch=ReconciliationPatch.empty(),
                diagnostics=diagnostics,
                validation_errors=[f"LLM call failed: {e}"],
                duration_ms=duration_ms,
                run_id=run_id,
            )

        logger.info(
            "[Reconciler:%s] LLM returned: %d merges, %d nodes, "
            "%d edges, %d layers, %d unknowns",
            run_id,
            len(patch.merge_suggestions),
            len(patch.add_nodes),
            len(patch.add_edges),
            len(patch.layer_assignments),
            len(patch.unknowns),
        )

        # Step 4: Validate patch
        validator = PatchValidator(graph)
        is_valid = validator.validate(patch)

        if not is_valid:
            if self.config.dry_run:
                duration_ms = int((time.time() - start_time) * 1000)
                return ReconciliationResult(
                    success=False,
                    patch=patch,
                    diagnostics=diagnostics,
                    validation_errors=validator.errors,
                    unknowns=patch.unknowns,
                    duration_ms=duration_ms,
                    run_id=run_id,
                    llm_input_tokens=input_tokens,
                    llm_output_tokens=output_tokens,
                )
            # For non-dry-run, log warnings but continue with valid parts
            logger.warning(
                "[Reconciler:%s] Validation warnings: %s",
                run_id, validator.errors,
            )

        # Step 5: Apply or return dry-run
        if self.config.dry_run:
            duration_ms = int((time.time() - start_time) * 1000)
            return ReconciliationResult(
                success=True,
                patch=patch,
                diagnostics=diagnostics,
                unknowns=patch.unknowns,
                validation_errors=validator.errors,
                duration_ms=duration_ms,
                run_id=run_id,
                llm_input_tokens=input_tokens,
                llm_output_tokens=output_tokens,
            )

        # Apply patch
        applier = PatchApplier(graph, run_id)
        applied = applier.apply(patch)

        # Re-canonicalize after modifications
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "[Reconciler:%s] Applied: %s in %dms",
            run_id, applied, duration_ms,
        )

        return ReconciliationResult(
            success=True,
            patch=patch,
            diagnostics=diagnostics,
            graph=graph,
            applied=applied,
            unknowns=patch.unknowns,
            validation_errors=validator.errors,
            duration_ms=duration_ms,
            run_id=run_id,
            llm_input_tokens=input_tokens,
            llm_output_tokens=output_tokens,
        )
