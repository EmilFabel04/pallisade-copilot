"""
Universal Lineage Coverage Engine.

Provides tech-agnostic coverage scoring, gap analysis, and monitor
recommendations across any data tool connected to Pallisade.

Inspired by Elementary's dbt-native observability but generalized to work
with any warehouse, orchestrator, BI tool, or transformation layer.
"""

from .models import (
    CoverageCategory,
    CoverageDimension,
    CoverageGap,
    CoverageReport,
    CoverageScore,
    MonitorRecommendation,
    NodeCoverage,
)
from .scorer import CoverageScorer
from .gap_analyzer import GapAnalyzer

__all__ = [
    "CoverageCategory",
    "CoverageDimension",
    "CoverageGap",
    "CoverageReport",
    "CoverageScore",
    "CoverageScorer",
    "GapAnalyzer",
    "MonitorRecommendation",
    "NodeCoverage",
]
