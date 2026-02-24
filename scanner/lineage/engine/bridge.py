"""
Deterministic Bridge Rules

Non-LLM fallback rules that fix structural gaps in the lineage graph,
specifically the "raw tables appear as sources" problem.

Rules:
1. If an ingestion integration exists AND raw datasets have no upstream
   writer actor, create an inferred ingestion job node and writes edges.
2. If transform tools exist but dbt models have no downstream analytics
   datasets, create derives edges where FQN matching suggests the link.

All inferred nodes/edges are marked inferred=True with low confidence
and evidence reason "bridge_missing_ingestion".
"""

import logging
from datetime import datetime, timezone
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
from .canonical import CanonicalEdgeType, CanonicalNodeType
from .ids import generate_edge_id
from .zones import (
    DatasetZone,
    INGESTION_PLATFORMS,
    TRANSFORM_PLATFORMS,
    classify_dataset_zone,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures for bridge results
# ---------------------------------------------------------------------------

class BridgeResult:
    """Result of applying bridge rules."""

    def __init__(self):
        self.added_nodes: List[LineageNode] = []
        self.added_edges: List[LineageEdge] = []
        self.rules_applied: List[Dict[str, Any]] = []

    @property
    def total_changes(self) -> int:
        return len(self.added_nodes) + len(self.added_edges)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added_nodes": len(self.added_nodes),
            "added_edges": len(self.added_edges),
            "rules_applied": self.rules_applied,
        }


# ---------------------------------------------------------------------------
# Bridge Rule Engine
# ---------------------------------------------------------------------------

class BridgeRuleEngine:
    """
    Applies deterministic bridge rules to fix structural gaps.

    Usage::

        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()
        # result.added_nodes / result.added_edges are already in the graph
    """

    def __init__(self, graph: LineageGraph):
        self.graph = graph

    def apply_all(self) -> BridgeResult:
        """Apply all bridge rules in order."""
        result = BridgeResult()
        self._bridge_missing_ingestion(result)
        return result

    def _bridge_missing_ingestion(self, result: BridgeResult) -> None:
        """
        Rule: If ingestion integrations exist AND raw datasets have no
        upstream writer actor, create inferred bridge.

        Creates:
        - One inferred job node per ingestion integration:
            urn:job:{platform}:unknown_loader::{integration_id}
        - One writes edge per orphaned raw dataset:
            unknown_loader --writes--> raw_dataset
        """
        # Collect ingestion service/job nodes present in graph
        ingestion_nodes: Dict[str, LineageNode] = {}  # platform -> node
        ingestion_integration_ids: Dict[str, str] = {}  # platform -> integration_id

        for node in self.graph.nodes.values():
            platform = (node.platform or "").lower()
            if platform in INGESTION_PLATFORMS:
                canonical = node.canonical_type or ""
                if canonical in ("service", "job"):
                    ingestion_nodes[platform] = node
                    ingestion_integration_ids[platform] = node.integration_id or "default"

        if not ingestion_integration_ids:
            # Check if any nodes at all have ingestion platforms
            for node in self.graph.nodes.values():
                platform = (node.platform or "").lower()
                if platform in INGESTION_PLATFORMS:
                    ingestion_integration_ids[platform] = node.integration_id or "default"
            if not ingestion_integration_ids:
                logger.info("[Bridge] No ingestion platforms found in graph, skipping")
                return

        logger.info(
            "[Bridge] Found ingestion platforms: %s (service/job nodes: %s)",
            list(ingestion_integration_ids.keys()),
            list(ingestion_nodes.keys()),
        )

        # Find raw datasets with no upstream writer
        raw_orphans: List[LineageNode] = []
        raw_with_writer: List[str] = []
        all_datasets = 0
        raw_datasets = 0

        for node in self.graph.nodes.values():
            if node.canonical_type != CanonicalNodeType.DATASET.value:
                continue
            all_datasets += 1

            zone = classify_dataset_zone(node)
            if zone != DatasetZone.RAW:
                continue
            raw_datasets += 1

            # Check if any edge connects this raw dataset to an ingestion actor
            upstream_ids = self.graph._upstream.get(node.id, set())
            downstream_ids = self.graph._downstream.get(node.id, set())
            has_writer = False
            # Check upstream: service/job writes to this dataset
            for up_id in upstream_ids:
                up_node = self.graph.nodes.get(up_id)
                if not up_node:
                    continue
                up_canonical = up_node.canonical_type or ""
                up_platform = (up_node.platform or "").lower()
                if up_canonical in ("service", "job"):
                    has_writer = True
                    break
                # Also count ingestion-platform nodes as writers
                if up_platform in INGESTION_PLATFORMS:
                    has_writer = True
                    break
                # Also check edge type
                for edge in self.graph.edges.values():
                    if (edge.target_id == node.id and
                            edge.source_id == up_id and
                            edge.canonical_edge_type in ("writes", "runs")):
                        has_writer = True
                        break
                if has_writer:
                    break
            # Check downstream: LLM may have created edge in reverse direction
            if not has_writer:
                for down_id in downstream_ids:
                    down_node = self.graph.nodes.get(down_id)
                    if not down_node:
                        continue
                    down_platform = (down_node.platform or "").lower()
                    if down_platform in INGESTION_PLATFORMS:
                        has_writer = True
                        break

            # Check if this raw dataset derives from other datasets (e.g. a BQ view).
            # Views that derive from other tables don't need an inferred ingestion writer.
            if not has_writer:
                for up_id in upstream_ids:
                    up_node = self.graph.nodes.get(up_id)
                    if not up_node:
                        continue
                    if up_node.canonical_type == CanonicalNodeType.DATASET.value:
                        has_writer = True
                        logger.info(
                            "[Bridge] %s derives from dataset %s — not an orphan",
                            node.name, up_node.name,
                        )
                        break

            if has_writer:
                raw_with_writer.append(node.name)
            else:
                raw_orphans.append(node)

        logger.info(
            "[Bridge] Datasets: %d total, %d raw, %d raw with writer, %d raw orphans",
            all_datasets, raw_datasets, len(raw_with_writer), len(raw_orphans),
        )
        if raw_with_writer:
            logger.info("[Bridge] Raw datasets with existing writer: %s", raw_with_writer)
        if raw_orphans:
            logger.info("[Bridge] Raw orphans (no upstream writer): %s",
                        [n.name for n in raw_orphans])

        if not raw_orphans:
            return

        # Deduplicate raw_orphans by FQN (safety net for resolver misses)
        seen_fqns: Dict[str, LineageNode] = {}
        unique_orphans: List[LineageNode] = []
        for orphan in raw_orphans:
            fqn_key = (orphan.fqn or orphan.name).lower()
            if fqn_key not in seen_fqns:
                seen_fqns[fqn_key] = orphan
                unique_orphans.append(orphan)
            else:
                logger.info(
                    "[Bridge] Skipping duplicate orphan: %s (same FQN as %s)",
                    orphan.id, seen_fqns[fqn_key].id,
                )
        skipped = len(raw_orphans) - len(unique_orphans)
        raw_orphans = unique_orphans

        logger.info(
            "[Bridge] Found %d raw datasets with no upstream writer "
            "(%d duplicates skipped), %d ingestion platforms present",
            len(raw_orphans),
            skipped,
            len(ingestion_integration_ids),
        )

        # Create one inferred loader job per ingestion platform
        for platform, int_id in ingestion_integration_ids.items():
            loader_id = f"urn:job:{platform}:unknown_loader::{int_id}"

            # Skip if already exists
            if loader_id in self.graph.nodes:
                loader_node = self.graph.nodes[loader_id]
            else:
                loader_node = LineageNode(
                    id=loader_id,
                    name=f"{platform.title()} Loader (inferred)",
                    fqn=loader_id,
                    node_type=NodeType.WORKFLOW,
                    platform=platform,
                    platform_domain=PlatformDomain.INGESTION,
                    inferred=True,
                    canonical_type=CanonicalNodeType.JOB.value,
                    integration_id=int_id,
                    evidence=[Evidence(
                        adapter_id="bridge_rule",
                        source_ref="bridge:missing_ingestion",
                        snippet=(
                            f"Inferred {platform} loader job — raw datasets exist "
                            f"with no upstream writer but {platform} integration is present"
                        ),
                    )],
                    raw_metadata={
                        "bridge_rule": "missing_ingestion",
                        "bridge_confidence": 0.4,
                    },
                )
                loader_node.sources = ["bridge_rule"]
                loader_node.confidence = 0.4

                self.graph.add_node(loader_node)
                result.added_nodes.append(loader_node)

            # Create writes edges to each orphan
            for orphan in raw_orphans:
                edge_id = generate_edge_id(
                    loader_id, orphan.id,
                    "writes", "table", "bridge_missing_ingestion",
                )

                if edge_id in self.graph.edges:
                    continue

                edge = LineageEdge(
                    id=edge_id,
                    source_id=loader_id,
                    target_id=orphan.id,
                    edge_type=EdgeType.WRITES_TO,
                    lineage_level=LineageLevel.TABLE,
                    confidence=0.4,
                    plane=LinePlane.CROSS,
                    canonical_edge_type=CanonicalEdgeType.WRITES.value,
                    inferred=True,
                    discovered_from="bridge:missing_ingestion",
                    discovered_at=datetime.now(timezone.utc),
                    evidence=[Evidence(
                        adapter_id="bridge_rule",
                        source_ref="bridge:missing_ingestion",
                        snippet=(
                            f"Inferred: {platform} likely writes to "
                            f"{orphan.name} (raw dataset with no upstream writer)"
                        ),
                    )],
                )
                self.graph.add_edge(edge)
                result.added_edges.append(edge)

            # Also connect the ingestion service to the loader job (runs edge)
            if platform in ingestion_nodes:
                service_node = ingestion_nodes[platform]
                runs_edge_id = generate_edge_id(
                    service_node.id, loader_id,
                    "runs", "tool", "bridge_missing_ingestion",
                )
                if runs_edge_id not in self.graph.edges:
                    runs_edge = LineageEdge(
                        id=runs_edge_id,
                        source_id=service_node.id,
                        target_id=loader_id,
                        edge_type=EdgeType.TRIGGERS,
                        lineage_level=LineageLevel.TOOL,
                        confidence=0.5,
                        plane=LinePlane.CONTROL,
                        canonical_edge_type=CanonicalEdgeType.RUNS.value,
                        inferred=True,
                        discovered_from="bridge:missing_ingestion",
                        discovered_at=datetime.now(timezone.utc),
                        evidence=[Evidence(
                            adapter_id="bridge_rule",
                            source_ref="bridge:service_runs_loader",
                            snippet=f"{service_node.name} runs inferred loader",
                        )],
                    )
                    self.graph.add_edge(runs_edge)
                    result.added_edges.append(runs_edge)

        result.rules_applied.append({
            "rule": "bridge_missing_ingestion",
            "orphaned_raw_datasets": len(raw_orphans),
            "ingestion_platforms": list(ingestion_integration_ids.keys()),
            "nodes_added": len(result.added_nodes),
            "edges_added": len(result.added_edges),
        })

        logger.info(
            "[Bridge] Applied missing_ingestion: +%d nodes, +%d edges",
            len(result.added_nodes),
            len(result.added_edges),
        )
