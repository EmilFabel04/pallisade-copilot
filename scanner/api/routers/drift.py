"""FastAPI router for drift analysis."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drift")


class DriftAnalyzeRequest(BaseModel):
    org_id: str
    monitors: List[Dict[str, Any]]
    runs_by_monitor: Dict[str, List[Dict[str, Any]]]
    policies: Dict[str, Dict[str, Any]]


class DriftAnalyzeResponse(BaseModel):
    runId: str
    recommendationCount: int
    recommendations: List[Dict[str, Any]]


@router.post("/analyze", response_model=DriftAnalyzeResponse)
async def analyze_drift(req: DriftAnalyzeRequest):
    """Run drift analysis for an organization's monitors."""
    try:
        from scanner.monitors.drift_analyzer import run_drift_analysis

        result = await run_drift_analysis(
            org_id=req.org_id,
            monitors=req.monitors,
            runs_by_monitor=req.runs_by_monitor,
            policies=req.policies,
        )

        return DriftAnalyzeResponse(
            runId=result["runId"],
            recommendationCount=len(result["recommendations"]),
            recommendations=result["recommendations"],
        )
    except Exception as e:
        logger.error("[DriftRoute] Analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
