"""
Normalization + Resolution Pipeline

Runs after adapters emit raw nodes/edges. Normalizes identifiers,
deduplicates nodes, links logical↔physical assets, merges edges,
and applies evidence weighting.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..graph import (
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
)
from .ids import normalize_identifier, normalize_fqn

logger = logging.getLogger(__name__)


# Default evidence weights by evidence type
DEFAULT_EVIDENCE_WEIGHTS: Dict[str, float] = {
    "declarative": 1.0,
    "api_metadata": 0.9,
    "compiled_sql": 0.8,
    "query_history": 0.6,
    "regex": 0.3,
}


@dataclass
class ResolverConfig:
    """Configuration for the resolver pipeline."""
    evidence_weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_EVIDENCE_WEIGHTS))
    fuzzy_resolution: bool = False
    fuzzy_threshold: float = 0.8  # minimum similarity for fuzzy match


@dataclass
class ResolutionStats:
    """Statistics from the resolution pipeline."""
    nodes_before: int = 0
    nodes_after: int = 0
    nodes_deduplicated: int = 0
    edges_before: int = 0
    edges_after: int = 0
    edges_merged: int = 0
    logical_physical_links: int = 0
    unresolved_refs: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "nodes_before": self.nodes_before,
            "nodes_after": self.nodes_after,
            "nodes_deduplicated": self.nodes_deduplicated,
            "edges_before": self.edges_before,
            "edges_after": self.edges_after,
            "edges_merged": self.edges_merged,
            "logical_physical_links": self.logical_physical_links,
            "unresolved_refs": self.unresolved_refs,
        }


class ResolverPipeline:
    """
    Post-adapter pipeline that normalizes, deduplicates, and merges
    raw nodes and edges into a clean graph.
    """

    def __init__(self, config: Optional[ResolverConfig] = None):
        self.config = config or ResolverConfig()
        self.stats = ResolutionStats()

    def resolve(
        self,
        nodes: List[LineageNode],
        edges: List[LineageEdge],
    ) -> LineageGraph:
        """
        Run the full resolution pipeline.

        Args:
            nodes: Raw nodes from all adapters
            edges: Raw edges from all adapters

        Returns:
            Merged, deduplicated LineageGraph with indexes populated
        """
        self.stats.nodes_before = len(nodes)
        self.stats.edges_before = len(edges)

        # Step 1: Normalize all identifiers
        nodes = self._normalize_nodes(nodes)

        # Step 2: Deduplicate nodes by stable_id
        merged_nodes, id_remap = self._deduplicate_nodes(nodes)

        # Step 3: Remap edge references and merge edges
        edges = self._remap_edge_refs(edges, id_remap)
        merged_edges = self._merge_edges(edges)

        # Step 4: Build the graph
        graph = LineageGraph()
        for node in merged_nodes:
            graph.add_node(node)

        unresolved = 0
        for edge in merged_edges:
            if edge.source_id in graph.nodes and edge.target_id in graph.nodes:
                graph.add_edge(edge)
            else:
                unresolved += 1
                logger.warning(
                    f"Unresolved edge: {edge.source_id[:12]}→{edge.target_id[:12]} "
                    f"from={edge.discovered_from} "
                    f"(source_exists={edge.source_id in graph.nodes}, "
                    f"target_exists={edge.target_id in graph.nodes})"
                )

        self.stats.nodes_after = len(graph.nodes)
        self.stats.edges_after = len(graph.edges)
        self.stats.unresolved_refs = unresolved

        logger.info(
            f"Resolution complete: {self.stats.nodes_before} -> {self.stats.nodes_after} nodes, "
            f"{self.stats.edges_before} -> {self.stats.edges_after} edges, "
            f"{self.stats.nodes_deduplicated} deduplicated, "
            f"{self.stats.edges_merged} merged, "
            f"{unresolved} unresolved"
        )

        return graph

    def _normalize_nodes(self, nodes: List[LineageNode]) -> List[LineageNode]:
        """Normalize identifiers on all nodes using their adapter's case_hint."""
        for node in nodes:
            hint = node.raw_metadata.get("case_hint", "lower")
            if node.database:
                node.database = normalize_identifier(node.database, hint)
            if node.schema:
                node.schema = normalize_identifier(node.schema, hint)
            node.name = normalize_identifier(node.name, hint)
            # Rebuild FQN from normalized parts
            parts = [p for p in [node.database, node.schema, node.name] if p]
            node.fqn = ".".join(parts)
        return nodes

    def _deduplicate_nodes(
        self, nodes: List[LineageNode]
    ) -> Tuple[List[LineageNode], Dict[str, str]]:
        """
        Deduplicate nodes using two passes:
        1. stable_id — deterministic hash from (domain, namespace, container, name)
        2. FQN fallback — catches divergent containers (e.g. dbt omits database)

        Returns:
            Tuple of (merged_nodes, id_remap) where id_remap maps
            old node IDs to the canonical surviving node ID.
        """
        by_stable: Dict[str, List[LineageNode]] = defaultdict(list)
        for node in nodes:
            by_stable[node.stable_id].append(node)

        merged: List[LineageNode] = []
        id_remap: Dict[str, str] = {}

        for stable_id, group in by_stable.items():
            if len(group) == 1:
                node = group[0]
                id_remap[node.id] = node.id
                merged.append(node)
                continue

            # Sort by priority: warehouse > transform > bi > other
            # Secondary key: prefer real warehouse platforms over dbt (both
            # use platform_domain=WAREHOUSE, so without this tiebreaker the
            # winner depends on extraction order which is non-deterministic).
            group.sort(key=lambda n: (
                _domain_priority(n.platform_domain.value),
                0 if n.platform in _WH_PLATFORMS else 1,
            ))
            primary = group[0]

            for secondary in group[1:]:
                _merge_node_metadata(primary, secondary)
                id_remap[secondary.id] = primary.id
                self.stats.nodes_deduplicated += 1

            id_remap[primary.id] = primary.id
            merged.append(primary)

        stable_deduped = self.stats.nodes_deduplicated

        # Second pass: schema-qualified name dedup for same-domain nodes.
        # Catches cases where adapters produce different container/FQN values
        # for the same physical table (e.g. dbt omits database field,
        # giving FQN "raw.customers" vs BigQuery's "project.raw.customers").
        # Key: (platform_domain, namespace, schema, name) — database-independent.
        by_short: Dict[Tuple[str, str, str, str], List[LineageNode]] = defaultdict(list)
        no_short: List[LineageNode] = []
        for node in merged:
            if node.name:
                key = (
                    node.platform_domain.value,
                    (node.namespace or "").lower(),
                    (node.schema or "").lower(),
                    node.name.lower(),
                )
                by_short[key].append(node)
            else:
                no_short.append(node)

        fqn_merged: List[LineageNode] = []
        for key, group in by_short.items():
            if len(group) == 1:
                fqn_merged.append(group[0])
                continue
            group.sort(key=lambda n: (
                _domain_priority(n.platform_domain.value),
                0 if n.platform in _WH_PLATFORMS else 1,
            ))
            primary = group[0]
            for secondary in group[1:]:
                _merge_node_metadata(primary, secondary)
                id_remap[secondary.id] = primary.id
                self.stats.nodes_deduplicated += 1
            fqn_merged.append(primary)

        merged = fqn_merged + no_short
        fqn_deduped = self.stats.nodes_deduplicated - stable_deduped

        # Pass 2.5: database-qualified dedup for WAREHOUSE domain.
        # When different adapters discover the same physical table
        # (e.g., Fivetran sees destination table, BigQuery sees it via parser),
        # they share (database, schema, name) but differ in namespace/system.
        # Key: (database, schema, name) — only for WAREHOUSE domain with database set.
        by_db_qual: Dict[Tuple[str, str, str], List[LineageNode]] = defaultdict(list)
        no_db: List[LineageNode] = []
        for node in merged:
            if (node.platform_domain.value == "warehouse"
                    and node.database and node.name):
                key = (
                    node.database.lower(),
                    (node.schema or "").lower(),
                    node.name.lower(),
                )
                by_db_qual[key].append(node)
            else:
                no_db.append(node)

        db_merged: List[LineageNode] = []
        for key, group in by_db_qual.items():
            if len(group) == 1:
                db_merged.append(group[0])
                continue
            group.sort(key=lambda n: (
                _domain_priority(n.platform_domain.value),
                0 if n.platform in _WH_PLATFORMS else 1,
            ))
            primary = group[0]
            for secondary in group[1:]:
                _merge_node_metadata(primary, secondary)
                id_remap[secondary.id] = primary.id
                self.stats.nodes_deduplicated += 1
            db_merged.append(primary)

        merged = db_merged + no_db
        db_deduped = self.stats.nodes_deduplicated - stable_deduped - fqn_deduped

        # Third pass: cross-domain dedup for warehouse ↔ transform.
        # dbt/transform nodes and warehouse nodes often represent the same
        # physical table but have different platform_domain values.
        # Key: (namespace, schema, name) — domain-independent.
        _CROSS_DOMAINS = {"warehouse", "transform"}
        cross_candidates: Dict[Tuple[str, str, str], List[LineageNode]] = defaultdict(list)
        non_cross: List[LineageNode] = []
        for node in merged:
            if node.platform_domain.value in _CROSS_DOMAINS and node.name:
                key = (
                    (node.namespace or "").lower(),
                    (node.schema or "").lower(),
                    node.name.lower(),
                )
                cross_candidates[key].append(node)
            else:
                non_cross.append(node)

        cross_merged: List[LineageNode] = []
        for key, group in cross_candidates.items():
            if len(group) == 1:
                cross_merged.append(group[0])
                continue
            # Only merge if the group contains nodes from different domains
            domains = {n.platform_domain.value for n in group}
            if len(domains) <= 1:
                cross_merged.extend(group)
                continue
            group.sort(key=lambda n: (
                _domain_priority(n.platform_domain.value),
                0 if n.platform in _WH_PLATFORMS else 1,
            ))
            primary = group[0]
            for secondary in group[1:]:
                _merge_node_metadata(primary, secondary)
                id_remap[secondary.id] = primary.id
                self.stats.nodes_deduplicated += 1
            cross_merged.append(primary)

        merged = cross_merged + non_cross
        cross_deduped = self.stats.nodes_deduplicated - stable_deduped - fqn_deduped - db_deduped

        logger.info(
            "[Resolver] Dedup: %d nodes → %d unique "
            "(%d stable_id, %d schema+name, %d db-qualified, %d cross-domain)",
            len(nodes), len(merged), stable_deduped, fqn_deduped, db_deduped, cross_deduped,
        )

        return merged, id_remap

    def _remap_edge_refs(
        self, edges: List[LineageEdge], id_remap: Dict[str, str]
    ) -> List[LineageEdge]:
        """Remap edge source/target IDs through the deduplication remap."""
        for edge in edges:
            edge.source_id = id_remap.get(edge.source_id, edge.source_id)
            edge.target_id = id_remap.get(edge.target_id, edge.target_id)
        return edges

    def _merge_edges(self, edges: List[LineageEdge]) -> List[LineageEdge]:
        """
        Merge edges with identical (source, target, type, level).

        When the same logical relationship is discovered by multiple
        adapters, keep all evidence records and select max confidence.
        """
        # Group by (source, target, type, level)
        groups: Dict[Tuple[str, str, str, str], List[LineageEdge]] = defaultdict(list)
        for edge in edges:
            key = (
                edge.source_id,
                edge.target_id,
                edge.edge_type.value,
                edge.lineage_level.value,
            )
            groups[key].append(edge)

        merged: List[LineageEdge] = []
        for key, group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
                continue

            # Take the first edge as primary, merge in others
            primary = group[0]
            for other in group[1:]:
                # Merge evidence
                primary.evidence.extend(other.evidence)
                # Merge column mappings (deduplicate by to_column)
                existing_cols = {m.to_column for m in primary.column_mappings}
                for m in other.column_mappings:
                    if m.to_column not in existing_cols:
                        primary.column_mappings.append(m)
                        existing_cols.add(m.to_column)
                # Take max confidence
                primary.confidence = max(primary.confidence, other.confidence)
                self.stats.edges_merged += 1

            # Apply evidence weighting
            primary.confidence = self._compute_weighted_confidence(primary)
            merged.append(primary)

        return merged

    def _compute_weighted_confidence(self, edge: LineageEdge) -> float:
        """
        Compute confidence from evidence using configurable weights.

        Uses the highest-weight evidence source type to determine confidence.
        """
        if not edge.evidence:
            return edge.confidence

        max_weight = 0.0
        for ev in edge.evidence:
            # Determine evidence type from source_ref or adapter_id
            ev_type = self._classify_evidence(ev)
            weight = self.config.evidence_weights.get(ev_type, 0.5)
            max_weight = max(max_weight, weight)

        return max_weight

    def _classify_evidence(self, ev: Evidence) -> str:
        """Classify evidence into a weight category."""
        ref = ev.source_ref.lower()
        if "manifest" in ref or "artifact" in ref:
            return "declarative"
        elif "api" in ref or "metadata" in ref:
            return "api_metadata"
        elif "compiled" in ref or "sql" in ref or "view_def" in ref:
            return "compiled_sql"
        elif "query" in ref or "history" in ref:
            return "query_history"
        elif "regex" in ref or "pattern" in ref:
            return "regex"
        return "api_metadata"  # default to middle tier


# Platforms that are real warehouses (vs dbt which also uses WAREHOUSE domain)
from .platforms import WAREHOUSE_PLATFORMS as _WH_PLATFORMS


# Priority for deduplication: lower = higher priority
_DOMAIN_PRIORITIES = {
    "warehouse": 1,
    "transform": 2,
    "bi": 3,
    "orchestration": 4,
    "ingestion": 5,
    "catalog": 6,
    "app": 7,
    "other": 8,
}


def _domain_priority(domain: str) -> int:
    return _DOMAIN_PRIORITIES.get(domain, 99)


def _merge_node_metadata(primary: LineageNode, secondary: LineageNode) -> None:
    """Merge metadata from secondary node into primary."""
    # Prefer non-None descriptions; prefer transform descriptions over warehouse
    if secondary.description and not primary.description:
        primary.description = secondary.description
    elif (
        secondary.description
        and secondary.platform_domain.value == "transform"
        and primary.platform_domain.value == "warehouse"
    ):
        primary.description = secondary.description

    # Prefer transform owner (usually more meaningful)
    if secondary.owner and secondary.platform_domain.value == "transform":
        primary.owner = secondary.owner
    elif secondary.owner and not primary.owner:
        primary.owner = secondary.owner

    # Merge tags
    primary.tags = list(set(primary.tags + secondary.tags))

    # Prefer warehouse row count (more accurate)
    if secondary.row_count and not primary.row_count:
        primary.row_count = secondary.row_count

    # Prefer more complete columns
    if len(secondary.columns) > len(primary.columns):
        primary.columns = secondary.columns

    # Merge sources
    primary.sources = list(set(primary.sources + secondary.sources))

    # Merge discovered_platforms for multi-platform provenance
    primary_platforms = primary.raw_metadata.setdefault("discovered_platforms", [])
    for p in secondary.raw_metadata.get("discovered_platforms", []):
        if p not in primary_platforms:
            primary_platforms.append(p)
    if secondary.platform and secondary.platform not in primary_platforms:
        primary_platforms.append(secondary.platform)

    # Preserve dbt resource type info so the UI can identify dbt models after dedup.
    # When a dbt model node is merged into a warehouse node, the warehouse node_type
    # (view/table) wins, losing the "model" type. Stash it in raw_metadata.
    if not primary.raw_metadata.get("dbt_resource_type"):
        dbt_resource = secondary.raw_metadata.get("dbt_resource_type")
        if dbt_resource and dbt_resource in ("model", "seed", "snapshot"):
            primary.raw_metadata["dbt_resource_type"] = dbt_resource

    # Preserve ingestion provenance when merging ingestion dest → warehouse.
    # When a warehouse node wins the merge over an ingestion destination node,
    # keep the ingestion metadata so cross-tool edge synthesis can still link them.
    for key in ("ingestion_platform", "ingestion_connector",
                "discovered_via", "connector_name", "connection_name",
                "synced_tables", "synced_schemas", "schema",
                "service", "sync_frequency"):
        if not primary.raw_metadata.get(key) and secondary.raw_metadata.get(key):
            primary.raw_metadata[key] = secondary.raw_metadata[key]

    # Prefer primary's integration_id (warehouse priority), fallback to secondary
    if not primary.integration_id and secondary.integration_id:
        primary.integration_id = secondary.integration_id

    # Merge node-level evidence lists
    primary.evidence.extend(secondary.evidence)
