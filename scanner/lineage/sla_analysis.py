"""Phase 1 of two-phase SLA discovery: analyze plan + clarifications.

Phase 2 (compute_sla) lives in sla_discovery.py and runs after the user has
answered any clarifications this phase emitted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass(frozen=True)
class AnalysisPlan:
    table_fqn: str
    warehouse_ancestor_fqn: Optional[str]
    volume_timestamp_pick: Optional[Dict[str, Any]]
    volume_timestamp_candidates: List[Dict[str, Any]]
    schema_snapshot: Dict[str, Any]
    row_count: Optional[int]
    unsupported: bool = False
    skipped_reason: Optional[str] = None


@dataclass(frozen=True)
class AnalyzeResult:
    table_fqn: str
    plan: AnalysisPlan
    status: Literal["ready", "awaiting_clarifications"]
    clarification_ids: List[str] = field(default_factory=list)


def plan_to_dict(plan: AnalysisPlan) -> Dict[str, Any]:
    return asdict(plan)


def plan_from_dict(data: Dict[str, Any]) -> AnalysisPlan:
    return AnalysisPlan(
        table_fqn=data["table_fqn"],
        warehouse_ancestor_fqn=data.get("warehouse_ancestor_fqn"),
        volume_timestamp_pick=data.get("volume_timestamp_pick"),
        volume_timestamp_candidates=list(data.get("volume_timestamp_candidates") or []),
        schema_snapshot=dict(data.get("schema_snapshot") or {}),
        row_count=data.get("row_count"),
        unsupported=bool(data.get("unsupported", False)),
        skipped_reason=data.get("skipped_reason"),
    )
