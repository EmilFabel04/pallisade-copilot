"""
Coverage API Router.

Endpoints for lineage coverage analysis, gap identification,
and monitor recommendations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import structlog

from scanner.coverage.models import CoverageReport
from scanner.coverage.scorer import CoverageScorer
from scanner.coverage.gap_analyzer import GapAnalyzer
from scanner.lineage.graph import LineageGraph

logger = structlog.get_logger()

router = APIRouter(prefix="/coverage")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class CoverageRequest(BaseModel):
    """Request body for coverage analysis."""

    graph_data: Dict[str, Any] = Field(
        ..., description="Serialized LineageGraph (from graph.to_dict())"
    )
    monitors: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Node FQN -> list of active monitor types.",
    )
    contracts: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description="Node FQN -> data contract config.",
    )
    observability_checks: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Node FQN -> list of check types from external tools.",
    )


class CoverageSummaryResponse(BaseModel):
    """Summary-level coverage response."""

    overall_score: float
    total_nodes: int
    nodes_with_full_coverage: int
    nodes_with_partial_coverage: int
    nodes_with_no_coverage: int
    category_scores: Dict[str, float]
    gaps_summary: Dict[str, int]
    recommendations_count: int


class NodeCoverageResponse(BaseModel):
    """Coverage detail for a single node."""

    node_id: str
    node_name: str
    node_type: str
    platform: Optional[str]
    criticality: str
    overall_score: float
    coverage_percent: float
    covered_count: int
    applicable_dimensions: int
    uncovered_dimensions: List[str]
    covered_dimensions: List[str]
    category_scores: Dict[str, Any]


class GapResponse(BaseModel):
    """A single coverage gap."""

    node_id: str
    node_name: str
    node_type: str
    dimension: str
    category: str
    severity: str
    title: str
    description: str
    impact: str
    recommendation: str


class RecommendationResponse(BaseModel):
    """A single monitor recommendation."""

    monitor_type: str
    target_node_id: str
    target_node_name: str
    target_platform: Optional[str]
    priority: str
    description: str
    sql_template: Optional[str]
    closes_gaps: List[str]
    config: Dict[str, Any]
    compatible_integrations: List[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=CoverageSummaryResponse)
async def analyze_coverage(request: CoverageRequest):
    """
    Analyze lineage coverage and return a summary report.

    Accepts a serialized lineage graph and optional context (monitors,
    contracts, observability checks) and returns coverage scores,
    gap counts, and recommendation counts.
    """
    try:
        graph = LineageGraph.from_dict(request.graph_data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid graph data: {exc}",
        )

    report = _run_analysis(
        graph,
        request.monitors,
        request.contracts,
        request.observability_checks,
    )

    return report.to_dict()


@router.post("/analyze/detailed")
async def analyze_coverage_detailed(request: CoverageRequest):
    """
    Full detailed coverage analysis including node-level detail,
    all gaps, and all recommendations.
    """
    try:
        graph = LineageGraph.from_dict(request.graph_data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid graph data: {exc}",
        )

    report = _run_analysis(
        graph,
        request.monitors,
        request.contracts,
        request.observability_checks,
    )

    return report.to_detailed_dict()


@router.post("/gaps", response_model=List[GapResponse])
async def get_coverage_gaps(
    request: CoverageRequest,
    severity: Optional[str] = Query(
        default=None,
        description="Filter by gap severity (critical, high, medium, low, info).",
    ),
    category: Optional[str] = Query(
        default=None,
        description="Filter by category (freshness, volume, schema, quality, lineage, ownership, documentation).",
    ),
    limit: int = Query(default=50, ge=1, le=500),
):
    """
    Get coverage gaps sorted by severity.

    Optionally filter by severity level or category.
    """
    try:
        graph = LineageGraph.from_dict(request.graph_data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid graph data: {exc}",
        )

    report = _run_analysis(
        graph,
        request.monitors,
        request.contracts,
        request.observability_checks,
    )

    gaps = report.gaps

    if severity:
        gaps = [g for g in gaps if g.severity.value == severity.lower()]
    if category:
        gaps = [g for g in gaps if g.category.value == category.lower()]

    return [g.to_dict() for g in gaps[:limit]]


@router.post("/recommendations", response_model=List[RecommendationResponse])
async def get_recommendations(
    request: CoverageRequest,
    monitor_type: Optional[str] = Query(
        default=None,
        description="Filter by monitor type.",
    ),
    limit: int = Query(default=25, ge=1, le=200),
):
    """
    Get monitor recommendations to close coverage gaps.

    Returns concrete, actionable monitor configs with SQL templates
    that work across any connected warehouse.
    """
    try:
        graph = LineageGraph.from_dict(request.graph_data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid graph data: {exc}",
        )

    report = _run_analysis(
        graph,
        request.monitors,
        request.contracts,
        request.observability_checks,
    )

    recs = report.recommendations

    if monitor_type:
        recs = [r for r in recs if r.monitor_type.value == monitor_type.lower()]

    return [r.to_dict() for r in recs[:limit]]


@router.post("/node/{node_id}", response_model=NodeCoverageResponse)
async def get_node_coverage(node_id: str, request: CoverageRequest):
    """Get detailed coverage for a specific node."""
    try:
        graph = LineageGraph.from_dict(request.graph_data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid graph data: {exc}",
        )

    if node_id not in graph.nodes:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in graph.",
        )

    report = _run_analysis(
        graph,
        request.monitors,
        request.contracts,
        request.observability_checks,
    )

    for nc in report.node_coverages:
        if nc.node_id == node_id:
            return nc.to_dict()

    raise HTTPException(status_code=404, detail="Node coverage not found.")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_analysis(
    graph: LineageGraph,
    monitors: Optional[Dict[str, List[str]]],
    contracts: Optional[Dict[str, Dict[str, Any]]],
    observability_checks: Optional[Dict[str, List[str]]],
) -> CoverageReport:
    """Run the full scoring + gap analysis pipeline."""
    scorer = CoverageScorer(
        graph=graph,
        monitors=monitors or {},
        contracts=contracts or {},
        observability_checks=observability_checks or {},
    )

    report = scorer.score()

    analyzer = GapAnalyzer(graph)
    report = analyzer.analyze(report)

    logger.info(
        "coverage_analysis_complete",
        overall_score=round(report.overall_score, 3),
        total_nodes=report.total_nodes,
        total_gaps=len(report.gaps),
        critical_gaps=report.critical_gaps,
        recommendations=len(report.recommendations),
    )

    return report
