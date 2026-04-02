"""
SLA Discovery Module

Analyses lineage graph nodes and warehouse history to automatically
suggest SLA thresholds for freshness, volume, quality, and schema.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scanner.lineage.graph import LineageGraph, LineageNode, NodeType, PlatformDomain

MIN_DATA_POINTS = 7

# NodeTypes that are considered native warehouse assets
_WAREHOUSE_NODE_TYPES = {NodeType.TABLE, NodeType.VIEW, NodeType.MATERIALIZED_VIEW}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DiscoveryResult:
    """Outcome of profiling a single lineage node."""
    node_fqn: str
    warehouse_ancestor_fqn: Optional[str] = None
    freshness: Optional[Dict[str, Any]] = None
    volume: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    schema: Optional[Dict[str, Any]] = None
    unsupported: bool = False
    skipped_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------

def _find_warehouse_ancestor(node: LineageNode, graph: LineageGraph) -> Optional[LineageNode]:
    """Return the nearest warehouse TABLE/VIEW ancestor of *node* via BFS.

    If *node* itself is a warehouse table or view it is returned immediately.
    Otherwise we walk upstream through ``graph._upstream`` (Dict[str, Set[str]])
    in BFS order, sorting neighbour IDs for determinism, and return the first
    warehouse node we encounter.  Returns ``None`` if no warehouse ancestor is
    found.
    """
    if (
        node.platform_domain == PlatformDomain.WAREHOUSE
        and node.node_type in _WAREHOUSE_NODE_TYPES
    ):
        return node

    visited: set[str] = {node.id}
    queue: deque[str] = deque(sorted(graph._upstream.get(node.id, set())))

    while queue:
        current_id = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)

        current_node = graph.nodes.get(current_id)
        if current_node is None:
            continue

        if (
            current_node.platform_domain == PlatformDomain.WAREHOUSE
            and current_node.node_type in _WAREHOUSE_NODE_TYPES
        ):
            return current_node

        # Enqueue upstream neighbours (sorted for determinism)
        for neighbour_id in sorted(graph._upstream.get(current_id, set())):
            if neighbour_id not in visited:
                queue.append(neighbour_id)

    return None


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list, p: float) -> float:
    """Return the p-th percentile (0–100) of a sorted list."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("Empty list")
    if n == 1:
        return float(sorted_values[0])
    k = (p / 100) * (n - 1)
    lo, hi = int(k), min(int(k) + 1, n - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


# ---------------------------------------------------------------------------
# Compute functions
# ---------------------------------------------------------------------------

def _compute_freshness(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Return freshness thresholds derived from historical update timestamps.

    Returns a dict with keys ``enabled``, ``maxHours``, ``warningHours``,
    or ``None`` on error / insufficient data.
    """
    try:
        history = adapter.get_freshness_history(table_fqn)
    except (NotImplementedError, Exception):
        return None

    if not history:
        return None

    # Sort timestamps
    sorted_ts = sorted(history)

    # Need at least 2 timestamps to compute intervals
    if len(sorted_ts) < 2:
        return None

    intervals_hours = [
        (sorted_ts[i + 1] - sorted_ts[i]).total_seconds() / 3600
        for i in range(len(sorted_ts) - 1)
    ]

    if not intervals_hours:
        return None

    mean_hours = statistics.mean(intervals_hours)
    p95 = _percentile(sorted(intervals_hours), 95)

    max_hours = max(1, math.ceil(p95 * 1.2))
    warning_hours = max(1, math.ceil(mean_hours))

    return {
        "enabled": True,
        "maxHours": max_hours,
        "warningHours": warning_hours,
    }


def _compute_volume(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Return volume thresholds derived from historical row-count snapshots.

    Returns a dict with keys ``enabled``, ``minRows``, ``maxRows``, and
    optionally ``growthRateThreshold``, or ``None`` on error / insufficient data.
    """
    try:
        history = adapter.get_row_count_history(table_fqn)
    except (NotImplementedError, Exception):
        return None

    if not history or len(history) < MIN_DATA_POINTS:
        return None

    counts = [float(count) for _date, count in history]

    mean = statistics.mean(counts)
    sd = statistics.stdev(counts)

    min_rows = max(0.0, mean - 2 * sd)
    max_rows = mean + 2 * sd

    result: Dict[str, Any] = {
        "enabled": True,
        "minRows": min_rows,
        "maxRows": max_rows,
    }

    # Detect consistent growth: compute daily deltas and check if they are
    # mostly positive and relatively consistent.
    if len(counts) >= 2:
        deltas = [counts[i + 1] - counts[i] for i in range(len(counts) - 1)]
        positive_deltas = [d for d in deltas if d > 0]
        if len(positive_deltas) / len(deltas) >= 0.8:
            # Consistent growth — add a growth rate threshold
            mean_delta = statistics.mean(positive_deltas)
            sd_delta = statistics.stdev(positive_deltas) if len(positive_deltas) > 1 else 0.0
            result["growthRateThreshold"] = max(0.0, mean_delta - 2 * sd_delta)

    return result


def _compute_quality(
    adapter: Any,
    table_fqn: str,
    timestamp_column: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Return quality thresholds derived from historical daily null rates.

    Returns a dict with keys ``enabled`` and ``maxNullRate``, or ``None`` on
    error / insufficient data.
    """
    try:
        history = adapter.get_daily_null_rates(table_fqn, timestamp_column)
    except (NotImplementedError, Exception):
        return None

    if not history or len(history) < MIN_DATA_POINTS:
        return None

    rates = [float(rate) for _date, rate in history]

    mean = statistics.mean(rates)
    sd = statistics.stdev(rates)

    max_null_rate = min(0.5, mean + 2 * sd)

    return {
        "enabled": True,
        "maxNullRate": max_null_rate,
    }


def _compute_schema(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Return schema-enforcement configuration derived from change history.

    Returns a dict with keys ``enforcement`` and ``allowEvolution``, or
    ``None`` on error.
    """
    try:
        changes = adapter.get_schema_change_history(table_fqn)
    except (NotImplementedError, Exception):
        return None

    if not changes:
        return {
            "enforcement": "strict",
            "allowEvolution": False,
        }

    # Any additions or removals → recommend warn + allow evolution
    return {
        "enforcement": "warn",
        "allowEvolution": True,
    }


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def discover_sla_profile(
    node: LineageNode,
    graph: LineageGraph,
    adapter: Any,
) -> DiscoveryResult:
    """Build an SLA profile for *node* by analysing its warehouse ancestor.

    Uses ``discover_timestamp_column`` from ``scanner.monitors.freshness`` to
    identify the partition/timestamp column for quality profiling.
    """
    ancestor = _find_warehouse_ancestor(node, graph)
    if ancestor is None:
        return DiscoveryResult(
            node_fqn=node.fqn,
            unsupported=True,
            skipped_reason="No warehouse ancestor found in lineage graph",
        )

    table_fqn = ancestor.fqn

    freshness = _compute_freshness(adapter, table_fqn)
    volume = _compute_volume(adapter, table_fqn)
    schema = _compute_schema(adapter, table_fqn)

    # Attempt to discover a timestamp column for quality profiling
    timestamp_column: Optional[str] = None
    try:
        from scanner.monitors.freshness import discover_timestamp_column

        # discover_timestamp_column expects a callable query_func plus
        # database/schema/table parts.  We attempt to parse from fqn.
        parts = table_fqn.split(".")
        if len(parts) == 3 and hasattr(adapter, "execute_query"):
            database, schema_name, table_name = parts

            def _query_func(sql: str) -> list:
                return adapter.execute_query(sql)

            dialect = getattr(adapter, "dialect", "postgres")
            timestamp_column = discover_timestamp_column(
                _query_func, database, schema_name, table_name, dialect=dialect
            )
    except Exception:
        timestamp_column = None

    quality: Optional[Dict[str, Any]] = None
    if timestamp_column is not None:
        quality = _compute_quality(adapter, table_fqn, timestamp_column)

    return DiscoveryResult(
        node_fqn=node.fqn,
        warehouse_ancestor_fqn=table_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
    )


async def discover_sla_profiles_bulk(
    nodes: List[LineageNode],
    graph: LineageGraph,
    adapter_registry: Dict[str, Any],
    node_limit: int = 100,
) -> List[DiscoveryResult]:
    """Discover SLA profiles for a collection of nodes in priority order.

    Nodes are sorted by criticality (critical > high > medium > low) then by
    depth (shallower first), then capped at *node_limit* before profiling.
    """
    _CRITICALITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    sorted_nodes = sorted(
        nodes,
        key=lambda n: (_CRITICALITY_ORDER.get(n.criticality, 99), n.depth),
    )
    capped = sorted_nodes[:node_limit]

    results: List[DiscoveryResult] = []
    for node in capped:
        platform = node.platform or ""
        adapter = adapter_registry.get(platform)
        if adapter is None:
            results.append(DiscoveryResult(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason=f"No adapter registered for platform '{platform}'",
            ))
            continue

        result = await discover_sla_profile(node, graph, adapter)
        results.append(result)

    return results
