"""Phase 1 of two-phase SLA discovery — analyze plan + clarifications."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

# Dual-import to handle both `pytest` (run from repo root) and `python -m scanner`
# (run from inside scanner/) — mirrors sla_discovery.py:26-28.
try:
    from scanner.lineage.sla_discovery import (
        _pick_volume_timestamp_column,
        _call_nextjs_create_context_request,
        _find_warehouse_ancestor,
    )
except ImportError:  # pragma: no cover
    from lineage.sla_discovery import (  # type: ignore
        _pick_volume_timestamp_column,
        _call_nextjs_create_context_request,
        _find_warehouse_ancestor,
    )


logger = logging.getLogger(__name__)


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


def _get_confidence_threshold() -> float:
    """Lazy CONFIG import — mirrors sla_discovery.py:1008-1013."""
    try:
        from copilot.clarifications.config import CONFIG
    except ImportError:
        from scanner.copilot.clarifications.config import CONFIG  # type: ignore
    return float(CONFIG.confidence_threshold)


def analyze_sla(
    table_fqn: str,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    prior_answers: Optional[Dict[str, Dict[str, Any]]] = None,
) -> AnalyzeResult:
    """Run phase 1: pick timestamp candidates, snapshot schema, emit clarifications.

    No warehouse-side aggregation runs here. Volume SQL, freshness probes,
    quality checks, and uniqueness checks all defer to ``compute_sla``.

    ``prior_answers`` is a dict keyed by clarification kind (e.g.
    ``timestamp_choice``) whose value is the prior answer payload — used to
    short-circuit asking the user a question they have already answered for
    this scope. The caller (Next.js proxy) looks these up from
    ``ContextResolution.answer`` before invoking analyze.
    """
    columns = list(adapter.get_columns(table_fqn) or [])
    if not columns:
        plan = AnalysisPlan(
            table_fqn=table_fqn,
            warehouse_ancestor_fqn=None,
            volume_timestamp_pick=None,
            volume_timestamp_candidates=[],
            schema_snapshot={"columns": []},
            row_count=None,
            unsupported=True,
            skipped_reason="No columns visible to the adapter.",
        )
        return AnalyzeResult(
            table_fqn=table_fqn,
            plan=plan,
            status="ready",
            clarification_ids=[],
        )

    pick = _pick_volume_timestamp_column(adapter, table_fqn)
    row_count = _safe_row_count(adapter, table_fqn)

    # Build a dtype lookup from the columns list for enriching candidate entries.
    dtype_by_name: Dict[str, str] = {
        c.name: getattr(c, "data_type", None) or "" for c in columns
    }

    schema_snapshot = {
        "columns": [
            {"name": c.name, "data_type": getattr(c, "data_type", None)}
            for c in columns
        ]
    }

    # If the caller supplied a prior answer for this scope, use it as the
    # picker's choice — no need to re-ask the user a question they've already
    # answered. The clarification emit is skipped, the plan goes out as ready.
    prior_ts_answer = (prior_answers or {}).get("timestamp_choice") or {}
    prior_ts_column = (
        prior_ts_answer.get("column") if isinstance(prior_ts_answer, dict) else None
    )

    if prior_ts_column:
        pick_dict: Optional[Dict[str, Any]] = {
            "column": prior_ts_column,
            "confidence": 1.0,  # user-confirmed
            "source": "prior_answer",
        }
    else:
        pick_dict = (
            {
                "column": pick.column,
                "confidence": pick.confidence,
            }
            if pick.column is not None
            else None
        )

    candidates = [
        {
            "column": col_name,
            "data_type": dtype_by_name.get(col_name, ""),
            "confidence": pick.confidence if col_name == pick.column else None,
        }
        for col_name in (pick.candidates or [])
    ]

    plan = AnalysisPlan(
        table_fqn=table_fqn,
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick=pick_dict,
        volume_timestamp_candidates=candidates,
        schema_snapshot=schema_snapshot,
        row_count=row_count,
        unsupported=False,
        skipped_reason=None,
    )

    clarification_ids: List[str] = []

    needs_clarification = (
        prior_ts_column is None
        and pipeline_stack_id is not None
        and pick.column is not None
        and pick.confidence < _get_confidence_threshold()
    )

    if needs_clarification:
        emitted = _call_nextjs_create_context_request(
            kind="timestamp_choice",
            scope_type="node",
            scope_ref=table_fqn,
            pipeline_stack_id=pipeline_stack_id,
            organization_id=organization_id,
            payload={
                "table_fqn": table_fqn,
                "candidates": [c["column"] for c in candidates],
                "confidence": pick.confidence,
                "evidence": {
                    "picked_column": pick.column,
                    "picker": "sla_analysis.analyze_sla",
                },
            },
        )
        if emitted and emitted.get("context_request_id"):
            clarification_ids.append(emitted["context_request_id"])

    status: Literal["ready", "awaiting_clarifications"] = (
        "awaiting_clarifications" if clarification_ids else "ready"
    )
    return AnalyzeResult(
        table_fqn=table_fqn,
        plan=plan,
        status=status,
        clarification_ids=clarification_ids,
    )


def _safe_row_count(adapter: Any, table_fqn: str) -> Optional[int]:
    try:
        rc = adapter.get_row_count(table_fqn)
        return int(rc) if rc is not None else None
    except Exception:
        logger.exception("get_row_count failed for %s", table_fqn)
        return None


def analyze_sla_bulk(
    nodes: List[tuple],  # (table_fqn, platform_key)
    adapters: Dict[str, Any],
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    prior_answers_by_table: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
) -> List[AnalyzeResult]:
    """Bulk analyze: run phase 1 for multiple tables.

    Simple loop wrapper — takes a list of (table_fqn, platform_key) tuples
    and returns a list of AnalyzeResults, one per node.

    ``prior_answers_by_table`` is keyed by table FQN; the inner dict matches
    the ``prior_answers`` arg on ``analyze_sla``.
    """
    results: List[AnalyzeResult] = []
    for table_fqn, platform in nodes:
        adapter = adapters.get(platform)
        if adapter is None:
            plan = AnalysisPlan(
                table_fqn=table_fqn,
                warehouse_ancestor_fqn=None,
                volume_timestamp_pick=None,
                volume_timestamp_candidates=[],
                schema_snapshot={"columns": []},
                row_count=None,
                unsupported=True,
                skipped_reason=f"No adapter for platform '{platform}'.",
            )
            results.append(
                AnalyzeResult(table_fqn=table_fqn, plan=plan, status="ready", clarification_ids=[])
            )
            continue
        results.append(
            analyze_sla(
                table_fqn=table_fqn,
                adapter=adapter,
                pipeline_stack_id=pipeline_stack_id,
                organization_id=organization_id,
                prior_answers=(prior_answers_by_table or {}).get(table_fqn),
            )
        )
    return results


def analyze_sla_profile(
    node: Any,
    graph: Any,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> AnalyzeResult:
    """Graph-aware analyze: resolves the warehouse ancestor first, then analyzes.

    Mirrors ``discover_sla_profile`` — walks the lineage graph to find the
    nearest warehouse ancestor of *node*, then delegates to ``analyze_sla``
    for phase-1 column inspection.
    """
    ancestor = _find_warehouse_ancestor(node, graph)
    warehouse_fqn: Optional[str] = ancestor.fqn if ancestor is not None else None

    target_fqn = warehouse_fqn or getattr(node, "fqn", None)
    if not target_fqn:
        plan = AnalysisPlan(
            table_fqn=getattr(node, "fqn", None) or "<unknown>",
            warehouse_ancestor_fqn=None,
            volume_timestamp_pick=None,
            volume_timestamp_candidates=[],
            schema_snapshot={"columns": []},
            row_count=None,
            unsupported=True,
            skipped_reason="No warehouse ancestor found.",
        )
        return AnalyzeResult(table_fqn=plan.table_fqn, plan=plan, status="ready")

    inner = analyze_sla(
        table_fqn=target_fqn,
        adapter=adapter,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    # Frozen dataclass — rebuild with warehouse_ancestor_fqn set.
    plan = AnalysisPlan(
        table_fqn=inner.plan.table_fqn,
        warehouse_ancestor_fqn=warehouse_fqn,
        volume_timestamp_pick=inner.plan.volume_timestamp_pick,
        volume_timestamp_candidates=inner.plan.volume_timestamp_candidates,
        schema_snapshot=inner.plan.schema_snapshot,
        row_count=inner.plan.row_count,
        unsupported=inner.plan.unsupported,
        skipped_reason=inner.plan.skipped_reason,
    )
    return AnalyzeResult(
        table_fqn=plan.table_fqn,
        plan=plan,
        status=inner.status,
        clarification_ids=inner.clarification_ids,
    )
