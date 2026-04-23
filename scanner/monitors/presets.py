"""
Pipeline Monitor Presets + Smart Builder.

Preset-driven watch generation that lets users create broad pipeline protection
with a single action. Each preset defines which watches to create, how to resolve
anchors, and what scope overrides to apply.

Presets create multiple independent Health Watches (MonitorGroups), each with
a different anchor and watch type, tied together by a shared presetGroupId.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..lineage.graph import (
    AssetKind,
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from .recommender import is_bi_node
from .scope import (
    ScopeResult,
    build_watch_scope,
    _node_priority_score,
    DEFAULT_SCOPE,
)
from .families import check_node_eligibility as _family_check_eligibility

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WatchSpec:
    """Specification for one watch within a preset."""
    watch_type: str
    anchor_strategy: str  # "selected" | "auto_upstream_connector" | "auto_highest_priority"
    anchor_domain_filter: Optional[str] = None  # PlatformDomain value for auto strategies
    scope_overrides: Optional[Dict[str, Any]] = None
    max_anchors: int = 1  # For multi-anchor strategies like ingestion_watch


@dataclass
class PresetDefinition:
    """Definition of a monitor preset."""
    key: str
    label: str
    description: str
    eligible_domains: List[str]        # PlatformDomain values that can anchor
    eligible_asset_kinds: List[str]    # AssetKind values that can anchor
    watch_specs: List[WatchSpec] = field(default_factory=list)
    global_monitor_cap: int = 40
    estimated_watches: str = "1"       # Display hint: "1", "1-3", "up to 4"
    estimated_monitors: str = "8-12"   # Display hint


@dataclass
class WatchPreview:
    """Preview of one watch within a preset application."""
    watch_type: str
    anchor_node_id: str
    anchor_name: str
    anchor_fqn: str
    anchor_node_type: str
    anchor_platform: str
    scope_result: ScopeResult
    monitor_count: int
    coverage_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "watch_type": self.watch_type,
            "anchor_node_id": self.anchor_node_id,
            "anchor_name": self.anchor_name,
            "anchor_fqn": self.anchor_fqn,
            "anchor_node_type": self.anchor_node_type,
            "anchor_platform": self.anchor_platform,
            "scope_result": self.scope_result.to_dict(),
            "monitor_count": self.monitor_count,
            "coverage_pct": self.coverage_pct,
        }


@dataclass
class PresetPreviewResult:
    """Full preview of a preset application."""
    preset_key: str
    watches: List[WatchPreview] = field(default_factory=list)
    total_monitors: int = 0
    total_nodes: int = 0
    deduplicated_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preset_key": self.preset_key,
            "watches": [w.to_dict() for w in self.watches],
            "total_monitors": self.total_monitors,
            "total_nodes": self.total_nodes,
            "deduplicated_count": self.deduplicated_count,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESET_DEFINITIONS: Dict[str, PresetDefinition] = {
    "pipeline_health": PresetDefinition(
        key="pipeline_health",
        label="Pipeline Health",
        description="Protect a warehouse table and its upstream pipeline with freshness, volume, and schema checks.",
        eligible_domains=["warehouse"],
        eligible_asset_kinds=["table", "view", "model", "dataset"],
        watch_specs=[
            WatchSpec(
                watch_type="pipeline_health",
                anchor_strategy="selected",
            ),
        ],
        global_monitor_cap=12,
        estimated_watches="1",
        estimated_monitors="8-12",
    ),

    "data_drift": PresetDefinition(
        key="data_drift",
        label="Data Drift",
        description="Detect schema changes, volume anomalies, and quality drift across pipeline assets.",
        eligible_domains=["warehouse", "transform"],
        eligible_asset_kinds=["table", "view", "model", "dataset"],
        watch_specs=[
            WatchSpec(
                watch_type="data_drift",
                anchor_strategy="selected",
            ),
        ],
        global_monitor_cap=10,
        estimated_watches="1",
        estimated_monitors="6-10",
    ),

    "ingestion_watch": PresetDefinition(
        key="ingestion_watch",
        label="Ingestion Watch",
        description="Protect all ingestion connectors feeding a warehouse table with sync lag, failure, and schema drift checks.",
        eligible_domains=["warehouse"],
        eligible_asset_kinds=["table", "view", "model", "dataset"],
        watch_specs=[
            WatchSpec(
                watch_type="source_guard",
                anchor_strategy="auto_upstream_connector",
                anchor_domain_filter="ingestion",
                max_anchors=3,
            ),
        ],
        global_monitor_cap=18,
        estimated_watches="1-3",
        estimated_monitors="6-18",
    ),

    "bi_reliability": PresetDefinition(
        key="bi_reliability",
        label="BI Reliability",
        description="End-to-end protection for a BI asset and its upstream data path.",
        eligible_domains=["bi"],
        eligible_asset_kinds=["dashboard", "report", "workbook", "question", "explore"],
        watch_specs=[
            WatchSpec(
                watch_type="dashboard_shield",
                anchor_strategy="selected",
            ),
            WatchSpec(
                watch_type="pipeline_health",
                anchor_strategy="auto_highest_priority",
                anchor_domain_filter="warehouse",
                scope_overrides={"maxNodes": 8, "maxMonitors": 8},
            ),
        ],
        global_monitor_cap=23,
        estimated_watches="2",
        estimated_monitors="15-23",
    ),

    "full_coverage": PresetDefinition(
        key="full_coverage",
        label="Full Coverage",
        description="Maximum monitoring coverage across your entire pipeline — data, orchestration, and BI layers.",
        eligible_domains=["warehouse", "transform", "bi", "ingestion", "orchestration"],
        eligible_asset_kinds=[],  # Empty = any asset kind
        watch_specs=[
            WatchSpec(
                watch_type="full_pipeline",
                anchor_strategy="selected",
                scope_overrides={
                    "maxDepth": 5,
                    "maxNodes": 30,
                    "maxMonitors": 40,
                    "domainFilters": [],
                    "excludeInvisibleNodes": True,
                },
            ),
        ],
        global_monitor_cap=40,
        estimated_watches="1",
        estimated_monitors="15-40",
    ),
}


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def check_preset_eligibility(node: LineageNode, preset_key: str) -> bool:
    """Check if a node can anchor a given preset.

    Delegates to families.py for eligibility logic. Falls back to
    preset-local check for keys not in families (backward compat).
    """
    # Try families first (canonical source of truth)
    if _family_check_eligibility(node, preset_key):
        return True

    # Fallback for preset keys that don't map directly to a family key
    # (e.g. "ingestion_watch" maps to family "ingestion_reliability")
    preset = PRESET_DEFINITIONS.get(preset_key)
    if not preset:
        return False

    domain_ok = (
        not preset.eligible_domains
        or node.platform_domain.value in preset.eligible_domains
    )
    kind_ok = (
        not preset.eligible_asset_kinds
        or node.asset_kind.value in preset.eligible_asset_kinds
    )
    return domain_ok and kind_ok


def get_all_presets(node: Optional[LineageNode] = None) -> List[Dict[str, Any]]:
    """Return all preset definitions with eligibility for a given node.

    Enriches results with family data from families.py where available.
    """
    results = []
    for key, preset in PRESET_DEFINITIONS.items():
        eligible = check_preset_eligibility(node, key) if node else True
        results.append({
            "key": preset.key,
            "label": preset.label,
            "description": preset.description,
            "eligible": eligible,
            "eligible_domains": preset.eligible_domains,
            "estimated_watches": preset.estimated_watches,
            "estimated_monitors": preset.estimated_monitors,
        })
    return results


# ---------------------------------------------------------------------------
# Anchor resolution
# ---------------------------------------------------------------------------

def _resolve_anchors(
    graph: LineageGraph,
    anchor_id: str,
    spec: WatchSpec,
) -> List[str]:
    """Resolve anchor node IDs for a watch spec."""

    if spec.anchor_strategy == "selected":
        return [anchor_id]

    if spec.anchor_strategy == "auto_upstream_connector":
        # BFS upstream from anchor, filter to ingestion connectors
        upstream = graph.get_upstream_with_depth(anchor_id, depth=5)
        connectors = []
        for node, depth in upstream:
            if (
                node.platform_domain.value == "ingestion"
                or node.asset_kind.value == "connector"
            ):
                score = _node_priority_score(node, depth)
                connectors.append((node.id, score))

        # Sort by score (highest first), cap at max_anchors
        connectors.sort(key=lambda x: x[1], reverse=True)
        result = [cid for cid, _ in connectors[:spec.max_anchors]]

        if not result:
            logger.info("[Presets] No upstream connectors found for %s", anchor_id)
        return result

    if spec.anchor_strategy == "auto_highest_priority":
        domain_filter = spec.anchor_domain_filter
        # Check if the selected node itself matches
        anchor_node = graph.nodes.get(anchor_id)
        if anchor_node and domain_filter and anchor_node.platform_domain.value == domain_filter:
            return [anchor_id]

        # BFS upstream, find highest-priority node in the target domain
        upstream = graph.get_upstream_with_depth(anchor_id, depth=5)
        candidates = []
        for node, depth in upstream:
            if domain_filter and node.platform_domain.value != domain_filter:
                continue
            score = _node_priority_score(node, depth)
            candidates.append((node.id, score))

        if not candidates:
            logger.info(
                "[Presets] No upstream %s nodes found for %s",
                domain_filter, anchor_id,
            )
            return []

        candidates.sort(key=lambda x: x[1], reverse=True)
        return [candidates[0][0]]

    logger.warning("[Presets] Unknown anchor strategy: %s", spec.anchor_strategy)
    return [anchor_id]


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def preview_preset(
    graph: LineageGraph,
    anchor_id: str,
    preset_key: str,
    existing_monitor_fqns: Optional[Set[str]] = None,
) -> PresetPreviewResult:
    """
    Preview what a preset would create without persisting anything.

    Args:
        graph: The lineage graph.
        anchor_id: User-selected anchor node ID.
        preset_key: Which preset to apply.
        existing_monitor_fqns: Set of "KEY:fqn" strings for dedup marking.

    Returns:
        PresetPreviewResult with per-watch breakdowns.
    """
    preset = PRESET_DEFINITIONS.get(preset_key)
    if not preset:
        return PresetPreviewResult(
            preset_key=preset_key,
            warnings=[f"Unknown preset: {preset_key}"],
        )

    existing_fqns = set(existing_monitor_fqns or [])
    result = PresetPreviewResult(preset_key=preset_key)
    cumulative_fqns: Set[str] = set(existing_fqns)
    total_monitors_so_far = 0

    # Check if nodes have proper domain assignments — if not, fall back
    # to a single broad watch that ignores domain filters
    upstream_check = graph.get_upstream_with_depth(anchor_id, depth=5)
    known_domains = {"bi", "warehouse", "transform", "ingestion"}
    has_domain_assignments = any(
        n.platform_domain.value in known_domains for n, _ in upstream_check
    )
    anchor_node_check = graph.nodes.get(anchor_id)
    if anchor_node_check and anchor_node_check.platform_domain.value in known_domains:
        has_domain_assignments = True

    if not has_domain_assignments and len(preset.watch_specs) > 1:
        # Nodes lack domain assignments — create one broad pipeline_health watch
        fallback_spec = WatchSpec(
            watch_type="pipeline_health",
            anchor_strategy="selected",
            scope_overrides={
                "maxDepth": 5,
                "maxNodes": 30,
                "maxMonitors": min(30, preset.global_monitor_cap),
                "domainFilters": [],
            },
        )
        scope_result = build_watch_scope(
            graph=graph,
            anchor_id=anchor_id,
            watch_type="pipeline_health",
            scope_config=fallback_spec.scope_overrides,
            existing_monitor_fqns=cumulative_fqns,
        )
        if scope_result.recommendations:
            new_recs = [r for r in scope_result.recommendations if not r.already_monitored]
            scope_result.recommendations = new_recs
            if scope_result.recommendations:
                for rec in scope_result.recommendations:
                    cumulative_fqns.add(f"{rec.monitor_key}:{rec.target_fqn}")
                a_node = graph.nodes.get(anchor_id)
                watch_preview = WatchPreview(
                    watch_type="pipeline_health",
                    anchor_node_id=anchor_id,
                    anchor_name=a_node.name if a_node else "unknown",
                    anchor_fqn=a_node.fqn if a_node else "",
                    anchor_node_type=a_node.node_type.value if a_node else "",
                    anchor_platform=a_node.platform or "" if a_node else "",
                    scope_result=scope_result,
                    monitor_count=len(scope_result.recommendations),
                    coverage_pct=scope_result.coverage_pct,
                )
                result.watches.append(watch_preview)
                total_monitors_so_far += len(scope_result.recommendations)

        result.total_monitors = sum(w.monitor_count for w in result.watches)
        all_node_ids: Set[str] = set()
        for w in result.watches:
            for rec in w.scope_result.recommendations:
                all_node_ids.add(rec.target_node_id)
        result.total_nodes = len(all_node_ids)
        return result

    for spec in preset.watch_specs:
        resolved_anchors = _resolve_anchors(graph, anchor_id, spec)

        if not resolved_anchors:
            # Track skipped specs — only surface as warnings if the overall
            # preset produces zero monitors (otherwise they're just noise).
            result._skipped_specs = getattr(result, '_skipped_specs', [])
            result._skipped_specs.append(spec)
            continue

        for resolved_id in resolved_anchors:
            # Check global cap
            if total_monitors_so_far >= preset.global_monitor_cap:
                result.warnings.append(
                    f"Global monitor cap ({preset.global_monitor_cap}) reached. Some watches were skipped."
                )
                break

            scope_result = build_watch_scope(
                graph=graph,
                anchor_id=resolved_id,
                watch_type=spec.watch_type,
                scope_config=spec.scope_overrides,
                existing_monitor_fqns=cumulative_fqns,
            )

            if not scope_result.recommendations:
                continue

            # Strip monitors already covered by prior watches in this preset
            new_recs = [r for r in scope_result.recommendations if not r.already_monitored]
            deduped_count = len(scope_result.recommendations) - len(new_recs)
            result.deduplicated_count += deduped_count
            scope_result.recommendations = new_recs

            if not scope_result.recommendations:
                continue

            # Apply global cap: trim recommendations if exceeding
            remaining_budget = preset.global_monitor_cap - total_monitors_so_far
            if len(scope_result.recommendations) > remaining_budget:
                scope_result.recommendations = scope_result.recommendations[:remaining_budget]

            # Track dedup across watches for subsequent iterations
            for rec in scope_result.recommendations:
                cumulative_fqns.add(f"{rec.monitor_key}:{rec.target_fqn}")

            anchor_node = graph.nodes.get(resolved_id)
            watch_preview = WatchPreview(
                watch_type=spec.watch_type,
                anchor_node_id=resolved_id,
                anchor_name=anchor_node.name if anchor_node else "unknown",
                anchor_fqn=anchor_node.fqn if anchor_node else "",
                anchor_node_type=anchor_node.node_type.value if anchor_node else "",
                anchor_platform=anchor_node.platform or "" if anchor_node else "",
                scope_result=scope_result,
                monitor_count=len(scope_result.recommendations),
                coverage_pct=scope_result.coverage_pct,
            )
            result.watches.append(watch_preview)
            total_monitors_so_far += len(scope_result.recommendations)

    # Compute totals
    result.total_monitors = sum(w.monitor_count for w in result.watches)
    all_node_ids: Set[str] = set()
    for w in result.watches:
        for rec in w.scope_result.recommendations:
            all_node_ids.add(rec.target_node_id)
    result.total_nodes = len(all_node_ids)

    # Only surface skipped-spec warnings if no monitors were generated at all
    if result.total_monitors == 0:
        for spec in getattr(result, '_skipped_specs', []):
            if spec.anchor_strategy == "auto_upstream_connector":
                result.warnings.append(
                    "No upstream connectors found. Consider using the Pipeline Health preset instead."
                )
            elif spec.anchor_strategy == "auto_highest_priority":
                result.warnings.append(
                    f"No upstream {spec.anchor_domain_filter or 'matching'} nodes found for {spec.watch_type} watch."
                )

    return result


# ---------------------------------------------------------------------------
# Smart Builder — auto-determine presets from graph shape
# ---------------------------------------------------------------------------

def smart_build_preview(
    graph: LineageGraph,
    anchor_id: str,
    existing_monitor_fqns: Optional[Set[str]] = None,
) -> PresetPreviewResult:
    """
    Auto-determine the best watches to create based on upstream graph shape.

    Unlike presets which follow a fixed recipe, smart build analyzes the
    upstream graph and creates one watch per domain layer that has nodes.
    """
    anchor_node = graph.nodes.get(anchor_id)
    if not anchor_node:
        return PresetPreviewResult(
            preset_key="smart_build",
            warnings=["Anchor node not found"],
        )

    # BFS upstream to discover domain layers
    upstream = graph.get_upstream_with_depth(anchor_id, depth=5)
    domain_nodes: Dict[str, List[Tuple[LineageNode, int]]] = {}
    for node, depth in upstream:
        domain = node.platform_domain.value
        if domain not in domain_nodes:
            domain_nodes[domain] = []
        domain_nodes[domain].append((node, depth))

    # Also include the anchor's own domain
    anchor_domain = anchor_node.platform_domain.value
    if anchor_domain not in domain_nodes:
        domain_nodes[anchor_domain] = [(anchor_node, 0)]

    # Map domains to watch types
    domain_to_watch = {
        "bi": "dashboard_shield",
        "warehouse": "pipeline_health",
        "transform": "model_quality",
        "ingestion": "source_guard",
    }

    # Build watch specs dynamically
    specs: List[WatchSpec] = []

    # Check if any known domain has nodes
    known_domains = {"bi", "warehouse", "transform", "ingestion"}
    has_known_domains = bool(known_domains & set(domain_nodes.keys()))

    if has_known_domains:
        # Order: BI first, then warehouse, transform, ingestion
        for domain in ["bi", "warehouse", "transform", "ingestion"]:
            if domain not in domain_nodes:
                continue
            watch_type = domain_to_watch.get(domain)
            if not watch_type:
                continue

            if domain == "ingestion":
                specs.append(WatchSpec(
                    watch_type="source_guard",
                    anchor_strategy="auto_upstream_connector",
                    anchor_domain_filter="ingestion",
                    max_anchors=2,
                ))
            elif domain == anchor_domain:
                specs.append(WatchSpec(
                    watch_type=watch_type,
                    anchor_strategy="selected",
                ))
            else:
                specs.append(WatchSpec(
                    watch_type=watch_type,
                    anchor_strategy="auto_highest_priority",
                    anchor_domain_filter=domain,
                ))
    else:
        # Fallback: nodes don't have domain assignments yet.
        # Create a single pipeline_health watch covering all upstream.
        specs.append(WatchSpec(
            watch_type="pipeline_health",
            anchor_strategy="selected",
            scope_overrides={
                "maxDepth": 5,
                "maxNodes": 30,
                "maxMonitors": 30,
                "domainFilters": [],  # No domain filtering — include everything
            },
        ))

    # Create a temporary preset and preview it
    existing_fqns = set(existing_monitor_fqns or [])
    result = PresetPreviewResult(preset_key="smart_build")
    cumulative_fqns: Set[str] = set(existing_fqns)
    total_monitors_so_far = 0
    global_cap = 40

    for spec in specs:
        if total_monitors_so_far >= global_cap:
            break

        resolved_anchors = _resolve_anchors(graph, anchor_id, spec)
        if not resolved_anchors:
            continue

        for resolved_id in resolved_anchors:
            if total_monitors_so_far >= global_cap:
                break

            scope_result = build_watch_scope(
                graph=graph,
                anchor_id=resolved_id,
                watch_type=spec.watch_type,
                scope_config=spec.scope_overrides,
                existing_monitor_fqns=cumulative_fqns,
            )

            if not scope_result.recommendations:
                continue

            # Strip monitors already covered by prior watches
            new_recs = [r for r in scope_result.recommendations if not r.already_monitored]
            scope_result.recommendations = new_recs

            if not scope_result.recommendations:
                continue

            remaining_budget = global_cap - total_monitors_so_far
            if len(scope_result.recommendations) > remaining_budget:
                scope_result.recommendations = scope_result.recommendations[:remaining_budget]

            for rec in scope_result.recommendations:
                cumulative_fqns.add(f"{rec.monitor_key}:{rec.target_fqn}")

            anchor_n = graph.nodes.get(resolved_id)
            watch_preview = WatchPreview(
                watch_type=spec.watch_type,
                anchor_node_id=resolved_id,
                anchor_name=anchor_n.name if anchor_n else "unknown",
                anchor_fqn=anchor_n.fqn if anchor_n else "",
                anchor_node_type=anchor_n.node_type.value if anchor_n else "",
                anchor_platform=anchor_n.platform or "" if anchor_n else "",
                scope_result=scope_result,
                monitor_count=len(scope_result.recommendations),
                coverage_pct=scope_result.coverage_pct,
            )
            result.watches.append(watch_preview)
            total_monitors_so_far += len(scope_result.recommendations)

    result.total_monitors = sum(w.monitor_count for w in result.watches)
    all_node_ids: Set[str] = set()
    for w in result.watches:
        for rec in w.scope_result.recommendations:
            all_node_ids.add(rec.target_node_id)
    result.total_nodes = len(all_node_ids)

    return result
