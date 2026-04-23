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

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

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

if TYPE_CHECKING:
    from .landing_zone import LandingZoneProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures for bridge results
# ---------------------------------------------------------------------------

@dataclass
class BridgeDiagnostic:
    """Why a dataset was matched (or not) to an ingestion job."""
    dataset_id: str
    dataset_name: str
    matched_job_id: Optional[str] = None
    matched_job_name: Optional[str] = None
    match_strategy: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    alternatives: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "matched_job_id": self.matched_job_id,
            "matched_job_name": self.matched_job_name,
            "match_strategy": self.match_strategy,
            "confidence": self.confidence,
            "reason": self.reason,
            "alternatives": self.alternatives,
        }


class BridgeResult:
    """Result of applying bridge rules."""

    def __init__(self):
        self.added_nodes: List[LineageNode] = []
        self.added_edges: List[LineageEdge] = []
        self.rules_applied: List[Dict[str, Any]] = []
        self.diagnostics: List[BridgeDiagnostic] = []

    @property
    def total_changes(self) -> int:
        return len(self.added_nodes) + len(self.added_edges)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added_nodes": len(self.added_nodes),
            "added_edges": len(self.added_edges),
            "rules_applied": self.rules_applied,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
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

    Extensibility:
        Register additional scoring strategies via ``register_scoring_strategy``
        for future adapters (Airbyte, n8n, etc.).
    """

    # Class-level registry for additional scoring strategies.
    # Each entry is (name, scorer_fn) where scorer_fn(orphan, job, graph)
    # returns Optional[Tuple[float, str, str]] = (score, strategy_name, reason)
    _extra_scoring_strategies: List = []

    @classmethod
    def register_scoring_strategy(cls, name: str, scorer_fn) -> None:
        """Register an additional scoring strategy for orphan matching.

        Args:
            name: Human-readable strategy name.
            scorer_fn: Callable(orphan, job, graph) -> Optional[Tuple[float, str, str]]
                Returns (score, strategy_name, reason) or None if no match.
        """
        cls._extra_scoring_strategies.append((name, scorer_fn))

    def __init__(
        self,
        graph: LineageGraph,
        landing_zone_profile: Optional[LandingZoneProfile] = None,
    ):
        self.graph = graph
        self.landing_zone_profile = landing_zone_profile

    def apply_all(self) -> BridgeResult:
        """Apply all bridge rules in order."""
        result = BridgeResult()
        self._bridge_missing_ingestion(result)
        return result

    # ------------------------------------------------------------------
    # Orphan identification (unchanged from original)
    # ------------------------------------------------------------------

    def _find_ingestion_context(
        self,
    ) -> Tuple[Dict[str, LineageNode], Dict[str, str]]:
        """Find ingestion service/job nodes and their integration IDs.

        Returns:
            (ingestion_nodes, ingestion_integration_ids) where keys are
            platform names (lowercase).
        """
        ingestion_nodes: Dict[str, LineageNode] = {}
        ingestion_integration_ids: Dict[str, str] = {}

        for node in self.graph.nodes.values():
            platform = (node.platform or "").lower()
            if platform in INGESTION_PLATFORMS:
                canonical = node.canonical_type or ""
                if canonical in ("service", "job"):
                    ingestion_nodes[platform] = node
                    ingestion_integration_ids[platform] = node.integration_id or "default"

        if not ingestion_integration_ids:
            for node in self.graph.nodes.values():
                platform = (node.platform or "").lower()
                if platform in INGESTION_PLATFORMS:
                    ingestion_integration_ids[platform] = node.integration_id or "default"

        return ingestion_nodes, ingestion_integration_ids

    def _find_raw_orphans(self) -> Tuple[List[LineageNode], List[str], int, int]:
        """Find RAW datasets with no upstream writer.

        Returns:
            (raw_orphans, raw_with_writer_names, all_datasets_count, raw_count)
        """
        raw_orphans: List[LineageNode] = []
        raw_with_writer: List[str] = []
        all_datasets = 0
        raw_datasets = 0

        for node in self.graph.nodes.values():
            if node.canonical_type != CanonicalNodeType.DATASET.value:
                continue
            all_datasets += 1

            zone = classify_dataset_zone(node, self.landing_zone_profile)
            if zone != DatasetZone.RAW:
                continue
            raw_datasets += 1

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
                if up_platform in INGESTION_PLATFORMS:
                    has_writer = True
                    break
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

            # Check if raw dataset derives from other datasets (e.g. BQ view)
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

        return raw_orphans, raw_with_writer, all_datasets, raw_datasets

    def _dedup_orphans(
        self, raw_orphans: List[LineageNode]
    ) -> List[LineageNode]:
        """Deduplicate raw orphans by FQN (safety net for resolver misses)."""
        seen_fqns: Dict[str, LineageNode] = {}
        unique: List[LineageNode] = []
        for orphan in raw_orphans:
            fqn_key = (orphan.fqn or orphan.name).lower()
            if fqn_key not in seen_fqns:
                seen_fqns[fqn_key] = orphan
                unique.append(orphan)
            else:
                logger.info(
                    "[Bridge] Skipping duplicate orphan: %s (same FQN as %s)",
                    orphan.id, seen_fqns[fqn_key].id,
                )
        return unique

    # ------------------------------------------------------------------
    # Scored matching
    # ------------------------------------------------------------------

    def _build_job_index(
        self,
    ) -> Tuple[List[LineageNode], Dict[str, Set[str]], Dict[str, Set[str]]]:
        """Build index of ingestion jobs and the schemas/tables they write to.

        Returns:
            (jobs, job_schemas, job_tables) where:
            - jobs: all ingestion JOB/SERVICE nodes
            - job_schemas[job_id]: schemas this job writes to
            - job_tables[job_id]: table names this job writes to
        """
        jobs: List[LineageNode] = []
        job_schemas: Dict[str, Set[str]] = {}
        job_tables: Dict[str, Set[str]] = {}

        for node in self.graph.nodes.values():
            platform = (node.platform or "").lower()
            if platform not in INGESTION_PLATFORMS:
                continue
            canonical = node.canonical_type or ""
            if canonical not in ("job", "service"):
                continue
            # Skip bridge-inferred loaders from previous runs
            if node.inferred:
                continue

            jobs.append(node)
            schemas: Set[str] = set()
            tables: Set[str] = set()

            # From downstream edges (actual writes)
            for down_id in self.graph._downstream.get(node.id, set()):
                down_node = self.graph.nodes.get(down_id)
                if down_node and down_node.canonical_type == CanonicalNodeType.DATASET.value:
                    if down_node.schema:
                        schemas.add(down_node.schema.lower())
                    if down_node.name:
                        tables.add(down_node.name.lower())

            # From metadata
            for t in node.raw_metadata.get("synced_tables", []):
                tables.add(t.lower())
            dest_schema = node.raw_metadata.get("dest_schema", "")
            if dest_schema:
                schemas.add(dest_schema.lower())
            connector_name = (
                node.raw_metadata.get("connector_name")
                or node.raw_metadata.get("connection_name")
                or ""
            )
            if connector_name:
                # Connector name often matches the destination schema
                schemas.add(connector_name.lower())

            job_schemas[node.id] = schemas
            job_tables[node.id] = tables

        return jobs, job_schemas, job_tables

    def _score_orphan(
        self,
        orphan: LineageNode,
        jobs: List[LineageNode],
        job_schemas: Dict[str, Set[str]],
        job_tables: Dict[str, Set[str]],
    ) -> Tuple[Optional[LineageNode], float, str, str, List[Dict[str, Any]]]:
        """Score an orphan against all ingestion jobs.

        Strategies are evaluated in priority order (all evaluated, highest wins):
        0. adapter_destination_table (0.95) — job has warehouse WRITES_TO edge matching orphan name
        0b. adapter_destination_schema (0.9) — job writes to warehouse tables in orphan's schema
        1. synced_table_name (0.85) — orphan name in job metadata synced_tables
        2. same_schema (0.8) — job writes to same schema as orphan
        3. connector_schema_match (0.6) — connector name matches orphan schema

        Returns:
            (best_job, best_score, best_strategy, best_reason, alternatives)
        """
        orphan_schema = (orphan.schema or "").lower()
        orphan_name = (orphan.name or "").lower()
        orphan_db = (orphan.database or "").lower()

        # Container validation: if we have a landing zone profile, verify
        # the orphan actually sits in a known ingestion landing container.
        # If not, do not bridge — emit a mismatch diagnostic instead.
        if self.landing_zone_profile and orphan_schema:
            is_landing, _ = self.landing_zone_profile.is_landing_container(
                orphan_db, orphan_schema,
            )
            if not is_landing:
                known = self.landing_zone_profile.all_containers
                return (
                    None, 0.0, "landing_zone_mismatch",
                    f"Orphan '{orphan_name}' in container "
                    f"({orphan_db}.{orphan_schema}) is not in any known "
                    f"ingestion landing zone; known containers: {known}",
                    [],
                )

        candidates: List[Tuple[float, str, str, LineageNode]] = []

        for job in jobs:
            jid = job.id

            # Strategy 0: Direct adapter destination edges (score 0.95/0.9)
            # If this job already writes to warehouse tables via adapter edges
            # (not bridge-inferred), use those as strong signals.
            job_dest_schemas: Set[str] = set()
            for down_id in self.graph._downstream.get(jid, set()):
                down_node = self.graph.nodes.get(down_id)
                if (down_node
                        and down_node.platform_domain == PlatformDomain.WAREHOUSE
                        and not down_node.inferred):
                    if down_node.schema:
                        job_dest_schemas.add(down_node.schema.lower())
                    if (down_node.name
                            and orphan_name
                            and orphan_name == down_node.name.lower()):
                        candidates.append((
                            0.95, "adapter_destination_table",
                            f"Job '{job.name}' writes to warehouse table "
                            f"'{down_node.name}' matching orphan '{orphan_name}'",
                            job,
                        ))

            if orphan_schema and orphan_schema in job_dest_schemas:
                candidates.append((
                    0.9, "adapter_destination_schema",
                    f"Job '{job.name}' writes to warehouse schema "
                    f"'{orphan_schema}', orphan '{orphan_name}' is in same schema",
                    job,
                ))

            # Strategy 1: name in synced_tables (score 0.85)
            if orphan_name and orphan_name in job_tables.get(jid, set()):
                candidates.append((
                    0.85, "synced_table_name",
                    f"Orphan '{orphan_name}' appears in job '{job.name}' synced_tables",
                    job,
                ))

            # Strategy 2: same schema (score 0.8)
            if orphan_schema and orphan_schema in job_schemas.get(jid, set()):
                candidates.append((
                    0.8, "same_schema",
                    f"Job '{job.name}' writes to schema '{orphan_schema}', "
                    f"orphan '{orphan_name}' is in the same schema",
                    job,
                ))

            # Strategy 3: connector name matches schema (score 0.6)
            connector_name = (
                job.raw_metadata.get("connector_name")
                or job.raw_metadata.get("connection_name")
                or job.name or ""
            ).lower()
            if connector_name and orphan_schema == connector_name:
                candidates.append((
                    0.6, "connector_schema_match",
                    f"Connector name '{connector_name}' matches orphan schema '{orphan_schema}'",
                    job,
                ))

            # Run any registered extra strategies (future adapters)
            for _name, scorer_fn in self._extra_scoring_strategies:
                try:
                    result = scorer_fn(orphan, job, self.graph)
                    if result:
                        score, strategy, reason = result
                        candidates.append((score, strategy, reason, job))
                except Exception:
                    logger.debug("[Bridge] Extra strategy '%s' failed", _name, exc_info=True)

        if not candidates:
            return None, 0.0, "", "", []

        # Sort descending by score
        candidates.sort(key=lambda c: c[0], reverse=True)
        best_score, best_strategy, best_reason, best_job = candidates[0]

        # Record alternatives (other candidates besides the winner)
        alternatives = [
            {"job_id": c[3].id, "job_name": c[3].name,
             "strategy": c[1], "score": c[0]}
            for c in candidates[1:]
            if c[3].id != best_job.id
        ]

        return best_job, best_score, best_strategy, best_reason, alternatives

    # ------------------------------------------------------------------
    # Main bridge rule
    # ------------------------------------------------------------------

    def _bridge_missing_ingestion(self, result: BridgeResult) -> None:
        """
        Smart ingestion bridging with per-dataset scored matching.

        For each orphan raw dataset:
        1. Try to match to a specific ingestion job using deterministic signals
           (synced_tables metadata, same schema, connector name).
        2. If no match, attach to an "Unknown Loader" with low confidence.
        3. Never attribute a dataset to a tool just because the tool exists.

        All bridge edges have inferred=True and confidence <= 0.5.
        """
        ingestion_nodes, ingestion_integration_ids = self._find_ingestion_context()
        if not ingestion_integration_ids:
            logger.info("[Bridge] No ingestion platforms found in graph, skipping")
            return

        logger.info(
            "[Bridge] Found ingestion platforms: %s (service/job nodes: %s)",
            list(ingestion_integration_ids.keys()),
            list(ingestion_nodes.keys()),
        )

        raw_orphans, raw_with_writer, all_datasets, raw_datasets = self._find_raw_orphans()

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

        raw_orphans = self._dedup_orphans(raw_orphans)

        logger.info(
            "[Bridge] %d unique raw orphans, %d ingestion platforms present",
            len(raw_orphans), len(ingestion_integration_ids),
        )

        # Build ingestion job index for scored matching
        jobs, job_schemas, job_tables = self._build_job_index()

        # Track Unknown Loader node (created on demand, at most one)
        unknown_loader_node: Optional[LineageNode] = None
        matched_count = 0
        unknown_count = 0

        for orphan in raw_orphans:
            best_job, best_score, strategy, reason, alternatives = self._score_orphan(
                orphan, jobs, job_schemas, job_tables,
            )

            if best_job and best_score > 0:
                # Matched — create edge from matched job to orphan
                # Cap confidence at 0.5 (hard requirement for bridge edges)
                edge_confidence = min(best_score, 0.5)
                edge_id = generate_edge_id(
                    best_job.id, orphan.id,
                    "writes", "table", f"bridge_scored:{strategy}",
                )
                if edge_id not in self.graph.edges:
                    edge = LineageEdge(
                        id=edge_id,
                        source_id=best_job.id,
                        target_id=orphan.id,
                        edge_type=EdgeType.WRITES_TO,
                        lineage_level=LineageLevel.TABLE,
                        confidence=edge_confidence,
                        plane=LinePlane.CROSS,
                        canonical_edge_type=CanonicalEdgeType.WRITES.value,
                        inferred=True,
                        discovered_from=f"bridge:scored_{strategy}",
                        discovered_at=datetime.now(timezone.utc),
                        evidence=[Evidence(
                            adapter_id="bridge_rule",
                            source_ref=f"bridge:scored_{strategy}",
                            snippet=reason[:200],
                        )],
                    )
                    self.graph.add_edge(edge)
                    result.added_edges.append(edge)
                    matched_count += 1

                result.diagnostics.append(BridgeDiagnostic(
                    dataset_id=orphan.id,
                    dataset_name=orphan.name,
                    matched_job_id=best_job.id,
                    matched_job_name=best_job.name,
                    match_strategy=strategy,
                    confidence=best_score,
                    reason=reason,
                    alternatives=alternatives,
                ))
            elif strategy == "landing_zone_mismatch":
                # Orphan is not in a known landing zone — do NOT bridge.
                # Record diagnostic so users can update their config.
                result.diagnostics.append(BridgeDiagnostic(
                    dataset_id=orphan.id,
                    dataset_name=orphan.name,
                    match_strategy="landing_zone_mismatch",
                    confidence=0.0,
                    reason=reason,
                ))
                logger.info(
                    "[Bridge] Skipping orphan '%s': %s", orphan.name, reason,
                )
            else:
                # No match — fallback to Unknown Loader
                if unknown_loader_node is None:
                    # Pick first ingestion platform for the Unknown Loader
                    platform = list(ingestion_integration_ids.keys())[0]
                    int_id = ingestion_integration_ids[platform]
                    loader_id = f"urn:job:unknown_loader::{int_id}"

                    if loader_id in self.graph.nodes:
                        unknown_loader_node = self.graph.nodes[loader_id]
                    else:
                        unknown_loader_node = LineageNode(
                            id=loader_id,
                            name="Unknown Loader (inferred)",
                            fqn=loader_id,
                            node_type=NodeType.WORKFLOW,
                            platform=platform,
                            platform_domain=PlatformDomain.INGESTION,
                            inferred=True,
                            canonical_type=CanonicalNodeType.JOB.value,
                            integration_id=int_id,
                            evidence=[Evidence(
                                adapter_id="bridge_rule",
                                source_ref="bridge:unknown_fallback",
                                snippet="No specific ingestion job matched — low confidence fallback",
                            )],
                            raw_metadata={
                                "bridge_rule": "unknown_fallback",
                                "bridge_confidence": 0.3,
                            },
                        )
                        unknown_loader_node.sources = ["bridge_rule"]
                        self.graph.add_node(unknown_loader_node)
                        result.added_nodes.append(unknown_loader_node)

                edge_id = generate_edge_id(
                    unknown_loader_node.id, orphan.id,
                    "writes", "table", "bridge_unknown_fallback",
                )
                if edge_id not in self.graph.edges:
                    edge = LineageEdge(
                        id=edge_id,
                        source_id=unknown_loader_node.id,
                        target_id=orphan.id,
                        edge_type=EdgeType.WRITES_TO,
                        lineage_level=LineageLevel.TABLE,
                        confidence=0.3,
                        plane=LinePlane.CROSS,
                        canonical_edge_type=CanonicalEdgeType.WRITES.value,
                        inferred=True,
                        discovered_from="bridge:unknown_fallback",
                        discovered_at=datetime.now(timezone.utc),
                        evidence=[Evidence(
                            adapter_id="bridge_rule",
                            source_ref="bridge:unknown_fallback",
                            snippet=f"No ingestion job matched '{orphan.name}' — fallback",
                        )],
                    )
                    self.graph.add_edge(edge)
                    result.added_edges.append(edge)
                    unknown_count += 1

                result.diagnostics.append(BridgeDiagnostic(
                    dataset_id=orphan.id,
                    dataset_name=orphan.name,
                    matched_job_id=unknown_loader_node.id,
                    matched_job_name=unknown_loader_node.name,
                    match_strategy="fallback_unknown",
                    confidence=0.3,
                    reason=f"No ingestion job matched '{orphan.name}'; "
                           f"attached to Unknown Loader",
                ))

        # Connect ingestion service nodes to their loader jobs (runs edge)
        for platform, service_node in ingestion_nodes.items():
            # Connect service to matched jobs that received bridge edges
            for job in jobs:
                if (job.platform or "").lower() == platform:
                    runs_edge_id = generate_edge_id(
                        service_node.id, job.id,
                        "runs", "tool", "bridge_missing_ingestion",
                    )
                    if runs_edge_id not in self.graph.edges:
                        runs_edge = LineageEdge(
                            id=runs_edge_id,
                            source_id=service_node.id,
                            target_id=job.id,
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
                                snippet=f"{service_node.name} runs {job.name}",
                            )],
                        )
                        self.graph.add_edge(runs_edge)
                        result.added_edges.append(runs_edge)

            # Connect service to Unknown Loader if it was created
            if unknown_loader_node and (unknown_loader_node.platform or "").lower() == platform:
                runs_edge_id = generate_edge_id(
                    service_node.id, unknown_loader_node.id,
                    "runs", "tool", "bridge_missing_ingestion",
                )
                if runs_edge_id not in self.graph.edges:
                    runs_edge = LineageEdge(
                        id=runs_edge_id,
                        source_id=service_node.id,
                        target_id=unknown_loader_node.id,
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
                            snippet=f"{service_node.name} runs Unknown Loader",
                        )],
                    )
                    self.graph.add_edge(runs_edge)
                    result.added_edges.append(runs_edge)

        result.rules_applied.append({
            "rule": "bridge_missing_ingestion",
            "orphaned_raw_datasets": len(raw_orphans),
            "ingestion_platforms": list(ingestion_integration_ids.keys()),
            "matched_to_specific_job": matched_count,
            "matched_to_unknown_loader": unknown_count,
            "nodes_added": len(result.added_nodes),
            "edges_added": len(result.added_edges),
        })

        logger.info(
            "[Bridge] Applied missing_ingestion: +%d nodes, +%d edges "
            "(%d matched to jobs, %d to Unknown Loader)",
            len(result.added_nodes), len(result.added_edges),
            matched_count, unknown_count,
        )
