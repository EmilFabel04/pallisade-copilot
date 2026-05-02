"""
Endpoint Classification

Classifies nodes as SOURCE / INTERNAL / SINK / ORPHAN based on graph topology
and node metadata. Drives layout anchoring (sources pinned left, sinks pinned
right) and frontend affordances (orphan warnings, sink visuals).

Distinct from DataPlaneRole:
  - DataPlaneRole answers "what does this asset represent?" (semantic)
  - EndpointKind answers "is this terminal in the graph?" (structural)

A node can be both — e.g., a Hightouch destination has role=ACTIVATE and
kind=SINK. A leaf warehouse table has role=STORE_SERVE and kind=SINK with
LOWER confidence (it might be unused rather than truly terminal).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from ..graph import LineageNode, PlatformDomain


class EndpointKind(Enum):
    """Structural role of a node in the graph."""
    SOURCE = "source"      # No upstream — anchors leftmost in layout
    INTERNAL = "internal"  # Has both upstream and downstream
    SINK = "sink"          # No downstream — anchors rightmost in layout
    ORPHAN = "orphan"      # No edges at all — extraction/integration gap


_TERMINAL_DOMAINS = frozenset({PlatformDomain.BI})

_ACTIVATION_PLATFORMS = frozenset({
    "hightouch", "census", "polytomic", "rudderstack_reverse", "grouparoo",
})


@dataclass
class EndpointClassification:
    """Result of endpoint classification."""
    kind: EndpointKind
    reason: str            # Human-readable explanation
    confidence: float      # 0.0 - 1.0; lower = clarification candidate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def classify_endpoint(
    node: LineageNode,
    canonical_type: str,
    has_upstream: bool,
    has_downstream: bool,
) -> EndpointClassification:
    """Classify a node by its position in the graph topology.

    Confidence reflects how certain we are this is a true endpoint rather
    than an extraction gap or an unused leaf:
      - SOURCE confidence high when the node platform is non-warehouse OR
        explicitly tagged as a dbt source
      - SOURCE confidence lower when it's a warehouse table with no upstream
        (could be an extraction gap)
      - SINK confidence high when the node is a known terminal (BI, activation)
      - SINK confidence lower when it's just a leaf warehouse table
        (could be unused, not truly terminal)
    """
    rm = node.raw_metadata or {}
    platform = (node.platform or "").lower()

    # ORPHAN
    if not has_upstream and not has_downstream:
        return EndpointClassification(
            kind=EndpointKind.ORPHAN,
            reason="no edges in either direction (likely extraction gap)",
            confidence=0.5,
        )

    # SOURCE
    if not has_upstream and has_downstream:
        if rm.get("dbt_resource_type") == "source":
            return EndpointClassification(
                kind=EndpointKind.SOURCE,
                reason="explicit dbt source declaration",
                confidence=0.95,
            )
        if node.platform_domain != PlatformDomain.WAREHOUSE:
            return EndpointClassification(
                kind=EndpointKind.SOURCE,
                reason=f"non-warehouse platform '{platform}' with no upstream",
                confidence=0.85,
            )
        return EndpointClassification(
            kind=EndpointKind.SOURCE,
            reason="warehouse leaf with no upstream (may be extraction gap)",
            confidence=0.55,
        )

    # SINK
    if has_upstream and not has_downstream:
        if canonical_type == "semantic" or node.platform_domain in _TERMINAL_DOMAINS:
            return EndpointClassification(
                kind=EndpointKind.SINK,
                reason="terminal BI / semantic node",
                confidence=0.95,
            )
        if platform in _ACTIVATION_PLATFORMS or rm.get("activation_target"):
            return EndpointClassification(
                kind=EndpointKind.SINK,
                reason="activation/reverse-ETL target",
                confidence=0.95,
            )
        return EndpointClassification(
            kind=EndpointKind.SINK,
            reason="leaf warehouse asset (may be unused, not truly terminal)",
            confidence=0.50,
        )

    # INTERNAL
    return EndpointClassification(
        kind=EndpointKind.INTERNAL,
        reason="node has both upstream and downstream edges",
        confidence=1.0,
    )
