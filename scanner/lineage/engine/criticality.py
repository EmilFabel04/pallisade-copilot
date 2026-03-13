"""
Topology-based criticality derivation.

Runs as a post-resolve enrichment step on the LineageGraph.
Assigns criticality based on downstream impact when no explicit
criticality has been set (i.e. still at the "medium" default).

Precedence (applied elsewhere, not in this module):
  1. DataContract.criticality  — explicit user override (applied in API route)
  2. dbt meta.criticality      — applied at parse time, survives merge
  3. This module               — topology-derived fallback

This module only upgrades nodes that are still at the default "medium"
and have never been explicitly set by an adapter or merge escalation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.lineage.graph import LineageGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# A node feeding ≥ this many dashboards/BI nodes is critical
DASHBOARD_THRESHOLD_CRITICAL = 3
DASHBOARD_THRESHOLD_HIGH = 1

# A node feeding ≥ this many downstream nodes (any type) is critical/high
DOWNSTREAM_THRESHOLD_CRITICAL = 10
DOWNSTREAM_THRESHOLD_HIGH = 5


def _count_downstream_bi_nodes(graph: "LineageGraph", node_id: str) -> int:
    """Count how many direct + indirect BI/reporting nodes depend on this node."""
    from scanner.lineage.graph import PlatformDomain, NodeType

    bi_count = 0
    visited = set()
    stack = list(graph._downstream.get(node_id, set()))

    while stack:
        nid = stack.pop()
        if nid in visited:
            continue
        visited.add(nid)
        node = graph.nodes.get(nid)
        if not node:
            continue
        if (
            node.platform_domain == PlatformDomain.BI
            or node.node_type in (NodeType.DASHBOARD, NodeType.REPORT)
        ):
            bi_count += 1
        # Continue traversal to catch indirect BI dependents
        stack.extend(graph._downstream.get(nid, set()) - visited)

    return bi_count


def enrich_criticality(graph: "LineageGraph") -> int:
    """
    Derive criticality from topology for nodes still at default "medium".

    Rules:
      - Feeds ≥3 BI/dashboard nodes OR ≥10 downstream nodes → "critical"
      - Feeds ≥1 BI/dashboard node  OR ≥5  downstream nodes → "high"
      - Otherwise → unchanged (stays "medium")

    Only upgrades — never downgrades a node that was explicitly set.

    Returns the number of nodes upgraded.
    """
    upgraded = 0

    for node_id, node in graph.nodes.items():
        # Only touch nodes still at the default
        if node.criticality != "medium":
            continue

        downstream_count = len(graph._downstream.get(node_id, set()))
        bi_count = _count_downstream_bi_nodes(graph, node_id) if downstream_count > 0 else 0

        new_criticality = None
        if bi_count >= DASHBOARD_THRESHOLD_CRITICAL or downstream_count >= DOWNSTREAM_THRESHOLD_CRITICAL:
            new_criticality = "critical"
        elif bi_count >= DASHBOARD_THRESHOLD_HIGH or downstream_count >= DOWNSTREAM_THRESHOLD_HIGH:
            new_criticality = "high"

        if new_criticality:
            node.criticality = new_criticality
            upgraded += 1

    if upgraded:
        logger.info(f"Criticality enrichment: upgraded {upgraded} nodes from topology")

    return upgraded
