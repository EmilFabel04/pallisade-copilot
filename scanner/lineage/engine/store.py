"""
Graph Store — build, query, and filter the lineage graph.

Orchestrates adapters and the resolver pipeline, then provides
rich query methods with filtering support.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import yaml

from ..graph import (
    AssetKind,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LinePlane,
    LineageNode,
    NodeType,
    PlatformDomain,
    TimeWindow,
)
from .adapter import AdapterRegistry, BaseLineageAdapter, Capability, create_default_registry
from .canonical import canonicalize_graph_in_place
from .reconciler import ReconcilerConfig, ReconciliationEngine, ReconciliationResult
from .resolver import ResolverConfig, ResolverPipeline, ResolutionStats

logger = logging.getLogger(__name__)


@dataclass
class Filters:
    """Filter criteria for graph queries."""
    lineage_levels: Optional[Set[LineageLevel]] = None
    systems: Optional[Set[str]] = None          # whitelist
    exclude_systems: Optional[Set[str]] = None  # blacklist
    platform_domains: Optional[Set[PlatformDomain]] = None
    asset_kinds: Optional[Set[AssetKind]] = None
    min_confidence: float = 0.0
    adapter_ids: Optional[Set[str]] = None
    time_window: Optional[TimeWindow] = None
    include_unresolved: bool = False
    planes: Optional[Set[LinePlane]] = None


@dataclass
class CoverageStats:
    """Lineage coverage metrics."""
    total_nodes: int = 0
    total_edges: int = 0
    edges_by_level: Dict[str, int] = field(default_factory=dict)
    edges_by_plane: Dict[str, int] = field(default_factory=dict)
    edges_by_system: Dict[str, int] = field(default_factory=dict)
    nodes_by_domain: Dict[str, int] = field(default_factory=dict)
    nodes_by_kind: Dict[str, int] = field(default_factory=dict)
    high_confidence_pct: float = 0.0
    medium_confidence_pct: float = 0.0
    low_confidence_pct: float = 0.0
    coverage_table: float = 0.0
    coverage_column: float = 0.0
    coverage_tool: float = 0.0
    resolution_stats: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "edges_by_level": self.edges_by_level,
            "edges_by_plane": self.edges_by_plane,
            "edges_by_system": self.edges_by_system,
            "nodes_by_domain": self.nodes_by_domain,
            "nodes_by_kind": self.nodes_by_kind,
            "high_confidence_pct": round(self.high_confidence_pct, 2),
            "medium_confidence_pct": round(self.medium_confidence_pct, 2),
            "low_confidence_pct": round(self.low_confidence_pct, 2),
            "coverage_table": round(self.coverage_table, 2),
            "coverage_column": round(self.coverage_column, 2),
            "coverage_tool": round(self.coverage_tool, 2),
            "resolution_stats": self.resolution_stats,
        }


class GraphStore:
    """
    Central store for building, querying, and filtering the lineage graph.
    """

    def __init__(self, registry: Optional[AdapterRegistry] = None):
        self.registry = registry or create_default_registry()
        self.graph: Optional[LineageGraph] = None
        self.resolution_stats: Optional[ResolutionStats] = None

    def build_graph(self, config: Dict[str, Any]) -> LineageGraph:
        """
        Build a lineage graph from config.

        Config format::

            adapters:
              - id: warehouse_main
                type: warehouse_catalog
                params: {path: ...}
            resolver:
              evidence_weights: {...}
              fuzzy_resolution: false
            sql_parser:
              default_dialect: postgres
        """
        all_nodes: List[LineageNode] = []
        all_edges: List[LineageEdge] = []

        # Instantiate and run adapters
        for adapter_cfg in config.get("adapters", []):
            adapter_id = adapter_cfg["id"]
            adapter_type = adapter_cfg["type"]
            params = adapter_cfg.get("params", {})

            try:
                adapter = self.registry.create(adapter_type, adapter_id, **params)
            except ValueError as e:
                logger.error(f"Failed to create adapter {adapter_id}: {e}")
                continue

            try:
                nodes = adapter.discover_assets(params)
                all_nodes.extend(nodes)
                logger.info(f"Adapter {adapter_id}: discovered {len(nodes)} assets")
            except Exception as e:
                logger.error(f"Adapter {adapter_id} discover_assets failed: {e}")

            try:
                edges = adapter.extract_lineage(params)
                all_edges.extend(edges)
                logger.info(f"Adapter {adapter_id}: extracted {len(edges)} edges")
            except Exception as e:
                logger.error(f"Adapter {adapter_id} extract_lineage failed: {e}")

        # Run resolver pipeline
        resolver_cfg = config.get("resolver", {})
        resolver_config = ResolverConfig(
            evidence_weights=resolver_cfg.get("evidence_weights", {}),
            fuzzy_resolution=resolver_cfg.get("fuzzy_resolution", False),
        )

        pipeline = ResolverPipeline(resolver_config)
        self.graph = pipeline.resolve(all_nodes, all_edges)
        self.resolution_stats = pipeline.stats
        self.graph.built_at = datetime.utcnow()

        # Apply canonical type mapping
        self.canonicalize()

        return self.graph

    def build_graph_from_yaml(self, config_path: str) -> LineageGraph:
        """Build graph from a YAML config file."""
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return self.build_graph(config)

    def canonicalize(self) -> None:
        """Apply canonical type mapping and URNs to all nodes/edges.

        Call after resolver produces the graph. Populates canonical_type,
        canonical_edge_type, and urn fields on every node/edge, and
        identifies nodes that need manual mapping.
        """
        if not self.graph:
            return
        result = canonicalize_graph_in_place(self.graph.nodes, self.graph.edges)
        self._needs_mapping = result.get("needs_mapping", set())
        logger.info(
            f"Canonicalized graph: {len(self._needs_mapping)} nodes need mapping"
        )

    def update_graph(
        self,
        delta_nodes: List[LineageNode],
        delta_edges: List[LineageEdge],
    ) -> LineageGraph:
        """Incrementally add nodes/edges to an existing graph."""
        if not self.graph:
            self.graph = LineageGraph()

        for node in delta_nodes:
            self.graph.add_node(node)
        for edge in delta_edges:
            self.graph.add_edge(edge)

        return self.graph

    # ---- Query methods ----

    def get_upstream(
        self, asset_id: str, depth: int = -1, filters: Optional[Filters] = None,
    ) -> List[LineageNode]:
        """Get upstream nodes with optional filtering."""
        if not self.graph:
            return []
        raw = self.graph.get_upstream(asset_id, depth=depth)
        return self._filter_nodes(raw, filters)

    def get_downstream(
        self, asset_id: str, depth: int = -1, filters: Optional[Filters] = None,
    ) -> List[LineageNode]:
        """Get downstream nodes with optional filtering."""
        if not self.graph:
            return []
        raw = self.graph.get_downstream(asset_id, depth=depth)
        return self._filter_nodes(raw, filters)

    def blast_radius(
        self, asset_id: str, filters: Optional[Filters] = None,
    ) -> Dict[str, Any]:
        """Compute the downstream blast radius of an asset."""
        if not self.graph:
            return {"total": 0, "by_kind": {}, "by_domain": {}}

        downstream = self.get_downstream(asset_id, filters=filters)

        by_kind: Dict[str, int] = defaultdict(int)
        by_domain: Dict[str, int] = defaultdict(int)
        for node in downstream:
            by_kind[node.asset_kind.value] += 1
            by_domain[node.platform_domain.value] += 1

        return {
            "asset_id": asset_id,
            "total": len(downstream),
            "by_kind": dict(by_kind),
            "by_domain": dict(by_domain),
            "affected_nodes": [n.id for n in downstream],
        }

    def subgraph(
        self,
        seed_ids: List[str],
        depth: int = 2,
        filters: Optional[Filters] = None,
    ) -> LineageGraph:
        """Extract a subgraph around multiple seed nodes."""
        if not self.graph:
            return LineageGraph()

        sub = LineageGraph()

        for seed_id in seed_ids:
            if seed_id not in self.graph.nodes:
                continue
            sub.add_node(self.graph.nodes[seed_id])
            for node in self.graph.get_upstream(seed_id, depth=depth):
                if self._node_passes(node, filters):
                    sub.add_node(node)
            for node in self.graph.get_downstream(seed_id, depth=depth):
                if self._node_passes(node, filters):
                    sub.add_node(node)

        # Add edges within the subgraph
        for edge in self.graph.edges.values():
            if edge.source_id in sub.nodes and edge.target_id in sub.nodes:
                if self._edge_passes(edge, filters):
                    sub.add_edge(edge)

        return sub

    def explain_edge(self, edge_id: str) -> Dict[str, Any]:
        """Return evidence and reasoning for an edge."""
        if not self.graph or edge_id not in self.graph.edges:
            return {"error": f"Edge {edge_id} not found"}

        edge = self.graph.edges[edge_id]
        source = self.graph.nodes.get(edge.source_id)
        target = self.graph.nodes.get(edge.target_id)

        return {
            "edge_id": edge.id,
            "from": source.fqn if source else edge.source_id,
            "to": target.fqn if target else edge.target_id,
            "edge_type": edge.edge_type.value,
            "lineage_level": edge.lineage_level.value,
            "confidence": edge.confidence,
            "evidence": [e.to_dict() for e in edge.evidence],
            "column_mappings": [m.to_dict() for m in edge.column_mappings],
            "discovered_from": edge.discovered_from,
        }

    def get_stats(self) -> CoverageStats:
        """Compute coverage and distribution statistics."""
        if not self.graph:
            return CoverageStats()

        stats = CoverageStats()
        stats.total_nodes = len(self.graph.nodes)
        stats.total_edges = len(self.graph.edges)

        # Edges by level
        for level, edge_ids in self.graph._by_lineage_level.items():
            stats.edges_by_level[level.value] = len(edge_ids)

        # Edges by plane
        for plane, edge_ids in self.graph._by_plane.items():
            stats.edges_by_plane[plane.value] = len(edge_ids)

        # Edges by discovered_from (system)
        for edge in self.graph.edges.values():
            src = edge.discovered_from or "unknown"
            stats.edges_by_system[src] = stats.edges_by_system.get(src, 0) + 1

        # Nodes by domain and kind
        for node in self.graph.nodes.values():
            d = node.platform_domain.value
            k = node.asset_kind.value
            stats.nodes_by_domain[d] = stats.nodes_by_domain.get(d, 0) + 1
            stats.nodes_by_kind[k] = stats.nodes_by_kind.get(k, 0) + 1

        # Confidence distribution
        total = max(len(self.graph.edges), 1)
        low = len(self.graph._by_confidence_bucket.get("low", set()))
        med = len(self.graph._by_confidence_bucket.get("medium", set()))
        high = len(self.graph._by_confidence_bucket.get("high", set()))
        stats.low_confidence_pct = low / total
        stats.medium_confidence_pct = med / total
        stats.high_confidence_pct = high / total

        # Coverage scores
        table_edges = stats.edges_by_level.get("table", 0)
        column_edges = stats.edges_by_level.get("column", 0)
        tool_edges = stats.edges_by_level.get("tool", 0)

        # Estimate expected edges from node counts
        table_nodes = sum(1 for n in self.graph.nodes.values()
                          if n.asset_kind.value in ("table", "view", "model"))
        bi_nodes = sum(1 for n in self.graph.nodes.values()
                       if n.asset_kind.value in ("dashboard", "dataset"))

        expected_table = max(table_nodes - 1, 1)  # at least 1 to avoid /0
        expected_tool = max(bi_nodes, 1)
        # Column edges are optional; eligible = tables with column info
        eligible_column = sum(
            1 for n in self.graph.nodes.values()
            if n.columns and n.asset_kind.value in ("table", "view", "model")
        )
        eligible_column = max(eligible_column, 1)

        stats.coverage_table = min(table_edges / expected_table, 1.0)
        stats.coverage_column = min(column_edges / eligible_column, 1.0)
        stats.coverage_tool = min(tool_edges / expected_tool, 1.0)

        if self.resolution_stats:
            stats.resolution_stats = self.resolution_stats.to_dict()

        return stats

    # ---- Cross-plane queries ----

    def get_cross_links(self, asset_id: str) -> List[LineageEdge]:
        """Return all CROSS-plane edges where asset_id is source or target."""
        if not self.graph:
            return []
        cross_ids = self.graph._by_plane.get(LinePlane.CROSS, set())
        return [
            self.graph.edges[eid] for eid in cross_ids
            if eid in self.graph.edges
            and (self.graph.edges[eid].source_id == asset_id
                 or self.graph.edges[eid].target_id == asset_id)
        ]

    def get_control_plane_subgraph(
        self, dag_id: Optional[str] = None,
    ) -> LineageGraph:
        """Return a subgraph containing orchestration nodes and their cross-links.

        If dag_id is given, restrict to that DAG and its tasks.
        Otherwise return all orchestration nodes.
        """
        if not self.graph:
            return LineageGraph()

        sub = LineageGraph()

        # Collect orchestration nodes
        for node in self.graph.nodes.values():
            if node.platform_domain != PlatformDomain.ORCHESTRATION:
                continue
            if dag_id:
                # Match the DAG itself or tasks belonging to it
                is_dag = node.node_type == NodeType.DAG and node.name == dag_id
                is_task = (node.node_type == NodeType.TASK
                           and node.raw_metadata.get("dag_id") == dag_id)
                if not is_dag and not is_task:
                    continue
            sub.add_node(node)

        # Add CONTROL and CROSS edges that touch these nodes
        for edge in self.graph.edges.values():
            if edge.plane in (LinePlane.CONTROL, LinePlane.CROSS):
                src_in = edge.source_id in sub.nodes
                tgt_in = edge.target_id in sub.nodes
                if src_in or tgt_in:
                    # For cross-links, also add the data-plane node
                    if edge.source_id not in sub.nodes and edge.source_id in self.graph.nodes:
                        sub.add_node(self.graph.nodes[edge.source_id])
                    if edge.target_id not in sub.nodes and edge.target_id in self.graph.nodes:
                        sub.add_node(self.graph.nodes[edge.target_id])
                    sub.add_edge(edge)

        return sub

    # ---- Reconciliation ----

    async def reconcile(
        self, config: Optional[ReconcilerConfig] = None,
    ) -> ReconciliationResult:
        """Run LLM reconciliation on the current graph.

        Analyzes the graph for structural issues (duplicates, disconnected
        components, missing bridge nodes) and uses an LLM to produce a
        structured patch.

        Args:
            config: Reconciler configuration. If None, uses defaults.

        Returns:
            ReconciliationResult with the patch, diagnostics, and applied counts.
        """
        if not self.graph or not self.graph.nodes:
            raise ValueError("No graph built. Call build_graph() first.")

        engine = ReconciliationEngine(config or ReconcilerConfig())
        result = await engine.reconcile(self.graph)

        if result.success and result.graph:
            self.graph = result.graph
            self.canonicalize()

        self._last_reconciliation = result
        return result

    # ---- Filter helpers ----

    def _filter_nodes(
        self, nodes: List[LineageNode], filters: Optional[Filters]
    ) -> List[LineageNode]:
        if not filters:
            return nodes
        return [n for n in nodes if self._node_passes(n, filters)]

    def _node_passes(self, node: LineageNode, filters: Optional[Filters]) -> bool:
        if not filters:
            return True

        if filters.systems and (node.platform or "unknown") not in filters.systems:
            return False
        if filters.exclude_systems and (node.platform or "unknown") in filters.exclude_systems:
            return False
        if filters.platform_domains and node.platform_domain not in filters.platform_domains:
            return False
        if filters.asset_kinds and node.asset_kind not in filters.asset_kinds:
            return False

        return True

    def _edge_passes(self, edge: LineageEdge, filters: Optional[Filters]) -> bool:
        if not filters:
            return True

        if filters.lineage_levels and edge.lineage_level not in filters.lineage_levels:
            return False
        if edge.confidence < filters.min_confidence:
            return False
        if filters.planes and edge.plane not in filters.planes:
            return False
        if filters.adapter_ids:
            edge_adapters = {e.adapter_id for e in edge.evidence}
            if not edge_adapters & filters.adapter_ids:
                return False
        if filters.time_window:
            for ev in edge.evidence:
                if ev.observed_at and (
                    ev.observed_at < filters.time_window.start
                    or ev.observed_at > filters.time_window.end
                ):
                    return False

        return True
