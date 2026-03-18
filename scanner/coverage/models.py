"""
Coverage engine data models.

These models represent coverage scoring at every level of the lineage graph:
per-node, per-dimension, and aggregated into full reports with gap analysis
and monitor recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class CoverageCategory(str, Enum):
    """High-level category for what is being covered."""

    FRESHNESS = "freshness"
    VOLUME = "volume"
    SCHEMA = "schema"
    QUALITY = "quality"
    LINEAGE = "lineage"
    OWNERSHIP = "ownership"
    DOCUMENTATION = "documentation"


class CoverageDimension(str, Enum):
    """
    Specific dimension of observability coverage.

    Each dimension maps to a concrete check or monitor type
    that can be evaluated regardless of the underlying tool.
    """

    # Freshness dimensions
    FRESHNESS_MONITOR = "freshness_monitor"
    FRESHNESS_SLA = "freshness_sla"

    # Volume dimensions
    ROW_COUNT_MONITOR = "row_count_monitor"
    VOLUME_ANOMALY = "volume_anomaly"

    # Schema dimensions
    SCHEMA_CHANGE_DETECTION = "schema_change_detection"
    SCHEMA_CONTRACT = "schema_contract"
    COLUMN_TYPE_VALIDATION = "column_type_validation"

    # Quality dimensions
    NULL_RATE_MONITOR = "null_rate_monitor"
    UNIQUENESS_CHECK = "uniqueness_check"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    RANGE_VALIDATION_CHECK = "range_validation_check"
    ACCEPTED_VALUES_CHECK = "accepted_values_check"
    DATE_CONSISTENCY_CHECK = "date_consistency_check"
    CUSTOM_SQL_CHECK = "custom_sql_check"
    OUTLIER_DETECTION = "outlier_detection"

    # Legacy (kept for backward compat)
    DISTRIBUTION_MONITOR = "distribution_monitor"
    ANOMALY_DETECTION = "anomaly_detection"

    # Lineage dimensions
    UPSTREAM_LINKED = "upstream_linked"
    DOWNSTREAM_LINKED = "downstream_linked"
    COLUMN_LINEAGE_MAPPED = "column_lineage_mapped"

    # Governance dimensions
    OWNER_ASSIGNED = "owner_assigned"
    DESCRIPTION_EXISTS = "description_exists"
    TAGS_APPLIED = "tags_applied"
    DATA_CONTRACT_EXISTS = "data_contract_exists"


class GapSeverity(str, Enum):
    """Severity of a coverage gap."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class MonitorType(str, Enum):
    """Types of universal monitors that can be recommended or configured."""

    FRESHNESS = "freshness"
    VOLUME = "volume"
    SCHEMA_CHANGE = "schema_change"
    REFERENTIAL = "referential"
    CUSTOM_SQL = "custom_sql"

    # New canonical warehouse monitors
    NULL_CHECK = "null_check"
    UNIQUENESS_CHECK = "uniqueness_check"
    RANGE_VALIDATION = "range_validation"
    ACCEPTED_VALUES = "accepted_values"
    DATE_CONSISTENCY = "date_consistency"
    DATA_TYPE_VALIDATION = "data_type_validation"
    OUTLIER_DETECTION = "outlier_detection"

    # Legacy (deprecated — kept for backward compat)
    NULL_RATE = "null_rate"
    DISTRIBUTION = "distribution"
    ANOMALY = "anomaly"


# ---------------------------------------------------------------------------
# Category -> dimension mapping
# ---------------------------------------------------------------------------

CATEGORY_DIMENSIONS: Dict[CoverageCategory, List[CoverageDimension]] = {
    CoverageCategory.FRESHNESS: [
        CoverageDimension.FRESHNESS_MONITOR,
        CoverageDimension.FRESHNESS_SLA,
    ],
    CoverageCategory.VOLUME: [
        CoverageDimension.ROW_COUNT_MONITOR,
        CoverageDimension.VOLUME_ANOMALY,
    ],
    CoverageCategory.SCHEMA: [
        CoverageDimension.SCHEMA_CHANGE_DETECTION,
        CoverageDimension.SCHEMA_CONTRACT,
        CoverageDimension.COLUMN_TYPE_VALIDATION,
    ],
    CoverageCategory.QUALITY: [
        CoverageDimension.NULL_RATE_MONITOR,
        CoverageDimension.UNIQUENESS_CHECK,
        CoverageDimension.REFERENTIAL_INTEGRITY,
        CoverageDimension.RANGE_VALIDATION_CHECK,
        CoverageDimension.ACCEPTED_VALUES_CHECK,
        CoverageDimension.DATE_CONSISTENCY_CHECK,
        CoverageDimension.CUSTOM_SQL_CHECK,
        CoverageDimension.OUTLIER_DETECTION,
    ],
    CoverageCategory.LINEAGE: [
        CoverageDimension.UPSTREAM_LINKED,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.COLUMN_LINEAGE_MAPPED,
    ],
    CoverageCategory.OWNERSHIP: [
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
        CoverageDimension.TAGS_APPLIED,
    ],
    CoverageCategory.DOCUMENTATION: [
        CoverageDimension.DESCRIPTION_EXISTS,
        CoverageDimension.DATA_CONTRACT_EXISTS,
    ],
}

# Which dimensions are applicable to which node types (by NodeType name).
# Nodes that don't appear here get a generic subset.
NODE_TYPE_APPLICABLE_DIMENSIONS: Dict[str, List[CoverageDimension]] = {
    "TABLE": [
        CoverageDimension.FRESHNESS_MONITOR,
        CoverageDimension.FRESHNESS_SLA,
        CoverageDimension.ROW_COUNT_MONITOR,
        CoverageDimension.VOLUME_ANOMALY,
        CoverageDimension.SCHEMA_CHANGE_DETECTION,
        CoverageDimension.SCHEMA_CONTRACT,
        CoverageDimension.COLUMN_TYPE_VALIDATION,
        CoverageDimension.NULL_RATE_MONITOR,
        CoverageDimension.UNIQUENESS_CHECK,
        CoverageDimension.REFERENTIAL_INTEGRITY,
        CoverageDimension.RANGE_VALIDATION_CHECK,
        CoverageDimension.ACCEPTED_VALUES_CHECK,
        CoverageDimension.DATE_CONSISTENCY_CHECK,
        CoverageDimension.OUTLIER_DETECTION,
        CoverageDimension.UPSTREAM_LINKED,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.COLUMN_LINEAGE_MAPPED,
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
        CoverageDimension.DATA_CONTRACT_EXISTS,
    ],
    "VIEW": [
        CoverageDimension.SCHEMA_CHANGE_DETECTION,
        CoverageDimension.COLUMN_TYPE_VALIDATION,
        CoverageDimension.NULL_RATE_MONITOR,
        CoverageDimension.UPSTREAM_LINKED,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.COLUMN_LINEAGE_MAPPED,
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
    ],
    "MODEL": [
        CoverageDimension.FRESHNESS_MONITOR,
        CoverageDimension.FRESHNESS_SLA,
        CoverageDimension.ROW_COUNT_MONITOR,
        CoverageDimension.VOLUME_ANOMALY,
        CoverageDimension.SCHEMA_CHANGE_DETECTION,
        CoverageDimension.SCHEMA_CONTRACT,
        CoverageDimension.COLUMN_TYPE_VALIDATION,
        CoverageDimension.NULL_RATE_MONITOR,
        CoverageDimension.UNIQUENESS_CHECK,
        CoverageDimension.RANGE_VALIDATION_CHECK,
        CoverageDimension.ACCEPTED_VALUES_CHECK,
        CoverageDimension.DATE_CONSISTENCY_CHECK,
        CoverageDimension.OUTLIER_DETECTION,
        CoverageDimension.UPSTREAM_LINKED,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.COLUMN_LINEAGE_MAPPED,
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
        CoverageDimension.DATA_CONTRACT_EXISTS,
    ],
    "SOURCE": [
        CoverageDimension.FRESHNESS_MONITOR,
        CoverageDimension.ROW_COUNT_MONITOR,
        CoverageDimension.SCHEMA_CHANGE_DETECTION,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
    ],
    "DASHBOARD": [
        CoverageDimension.UPSTREAM_LINKED,
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
    ],
    "DAG": [
        CoverageDimension.FRESHNESS_MONITOR,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.OWNER_ASSIGNED,
        CoverageDimension.DESCRIPTION_EXISTS,
    ],
    "TASK": [
        CoverageDimension.UPSTREAM_LINKED,
        CoverageDimension.DOWNSTREAM_LINKED,
        CoverageDimension.OWNER_ASSIGNED,
    ],
}

# Default applicable dimensions for node types not listed above.
DEFAULT_APPLICABLE_DIMENSIONS: List[CoverageDimension] = [
    CoverageDimension.UPSTREAM_LINKED,
    CoverageDimension.DOWNSTREAM_LINKED,
    CoverageDimension.OWNER_ASSIGNED,
    CoverageDimension.DESCRIPTION_EXISTS,
]

# ---------------------------------------------------------------------------
# Weights for coverage scoring
# ---------------------------------------------------------------------------

# Category-level weights (must sum to 1.0).
CATEGORY_WEIGHTS: Dict[CoverageCategory, float] = {
    CoverageCategory.FRESHNESS: 0.20,
    CoverageCategory.VOLUME: 0.10,
    CoverageCategory.SCHEMA: 0.15,
    CoverageCategory.QUALITY: 0.25,
    CoverageCategory.LINEAGE: 0.15,
    CoverageCategory.OWNERSHIP: 0.10,
    CoverageCategory.DOCUMENTATION: 0.05,
}

# Criticality multipliers — critical assets weigh more in the aggregate.
CRITICALITY_MULTIPLIERS: Dict[str, float] = {
    "critical": 2.0,
    "high": 1.5,
    "medium": 1.0,
    "low": 0.5,
}


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """Score for a single coverage dimension on a single node."""

    dimension: CoverageDimension
    covered: bool
    score: float  # 0.0 to 1.0
    source: Optional[str] = None  # which integration/tool provides coverage
    details: Optional[str] = None
    monitor_id: Optional[str] = None  # linked monitor if one exists

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "covered": self.covered,
            "score": self.score,
            "source": self.source,
            "details": self.details,
            "monitor_id": self.monitor_id,
        }


@dataclass
class CoverageScore:
    """Aggregated coverage score for a category."""

    category: CoverageCategory
    score: float  # 0.0 to 1.0
    dimensions_covered: int
    dimensions_total: int
    dimension_scores: List[DimensionScore] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        if self.dimensions_total == 0:
            return 0.0
        return self.dimensions_covered / self.dimensions_total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "score": round(self.score, 3),
            "dimensions_covered": self.dimensions_covered,
            "dimensions_total": self.dimensions_total,
            "coverage_ratio": round(self.coverage_ratio, 3),
            "dimension_scores": [d.to_dict() for d in self.dimension_scores],
        }


@dataclass
class NodeCoverage:
    """Complete coverage assessment for a single lineage node."""

    node_id: str
    node_name: str
    node_type: str
    platform: Optional[str] = None
    criticality: str = "medium"

    # Overall score (weighted combination of category scores)
    overall_score: float = 0.0

    # Per-category breakdown
    category_scores: Dict[CoverageCategory, CoverageScore] = field(
        default_factory=dict
    )

    # Quick access: which dimensions are missing
    uncovered_dimensions: List[CoverageDimension] = field(default_factory=list)
    covered_dimensions: List[CoverageDimension] = field(default_factory=list)

    # Metadata
    applicable_dimensions: int = 0
    covered_count: int = 0

    @property
    def coverage_percent(self) -> float:
        if self.applicable_dimensions == 0:
            return 0.0
        return (self.covered_count / self.applicable_dimensions) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "platform": self.platform,
            "criticality": self.criticality,
            "overall_score": round(self.overall_score, 3),
            "coverage_percent": round(self.coverage_percent, 1),
            "applicable_dimensions": self.applicable_dimensions,
            "covered_count": self.covered_count,
            "uncovered_dimensions": [d.value for d in self.uncovered_dimensions],
            "covered_dimensions": [d.value for d in self.covered_dimensions],
            "category_scores": {
                k.value: v.to_dict() for k, v in self.category_scores.items()
            },
        }


@dataclass
class CoverageGap:
    """A specific identified gap in coverage with severity and context."""

    node_id: str
    node_name: str
    node_type: str
    dimension: CoverageDimension
    category: CoverageCategory
    severity: GapSeverity
    title: str
    description: str
    impact: str  # Why this gap matters
    recommendation: str  # What to do about it

    # Contextual info
    criticality: str = "medium"
    upstream_count: int = 0
    downstream_count: int = 0
    platform: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "dimension": self.dimension.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "criticality": self.criticality,
            "upstream_count": self.upstream_count,
            "downstream_count": self.downstream_count,
            "platform": self.platform,
        }


@dataclass
class MonitorRecommendation:
    """A recommended monitor to fill a coverage gap."""

    monitor_type: MonitorType
    target_node_id: str
    target_node_name: str
    target_platform: Optional[str] = None

    # Configuration template
    config: Dict[str, Any] = field(default_factory=dict)

    # Which gaps this monitor would close
    closes_gaps: List[CoverageDimension] = field(default_factory=list)

    # Priority based on gap severity and node criticality
    priority: GapSeverity = GapSeverity.MEDIUM

    # Human-readable description of what this monitor does
    description: str = ""

    # SQL template if applicable (tech-agnostic)
    sql_template: Optional[str] = None

    # Which integration types can execute this monitor
    compatible_integrations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_type": self.monitor_type.value,
            "target_node_id": self.target_node_id,
            "target_node_name": self.target_node_name,
            "target_platform": self.target_platform,
            "config": self.config,
            "closes_gaps": [g.value for g in self.closes_gaps],
            "priority": self.priority.value,
            "description": self.description,
            "sql_template": self.sql_template,
            "compatible_integrations": self.compatible_integrations,
        }


@dataclass
class CoverageReport:
    """Full coverage report for a lineage graph or subset."""

    # Aggregate scores
    overall_score: float = 0.0
    total_nodes: int = 0
    nodes_with_full_coverage: int = 0
    nodes_with_partial_coverage: int = 0
    nodes_with_no_coverage: int = 0

    # Per-category aggregates
    category_scores: Dict[CoverageCategory, float] = field(default_factory=dict)

    # Node-level detail
    node_coverages: List[NodeCoverage] = field(default_factory=list)

    # Gaps sorted by severity
    gaps: List[CoverageGap] = field(default_factory=list)

    # Recommended monitors
    recommendations: List[MonitorRecommendation] = field(default_factory=list)

    # Summary stats
    critical_gaps: int = 0
    high_gaps: int = 0
    medium_gaps: int = 0
    low_gaps: int = 0

    # Metadata
    generated_at: Optional[datetime] = None
    organization_id: Optional[str] = None

    def compute_summary(self) -> None:
        """Recompute summary stats from the node-level data."""
        self.total_nodes = len(self.node_coverages)
        self.nodes_with_full_coverage = sum(
            1 for nc in self.node_coverages if nc.coverage_percent == 100.0
        )
        self.nodes_with_no_coverage = sum(
            1 for nc in self.node_coverages if nc.coverage_percent == 0.0
        )
        self.nodes_with_partial_coverage = (
            self.total_nodes
            - self.nodes_with_full_coverage
            - self.nodes_with_no_coverage
        )
        self.critical_gaps = sum(
            1 for g in self.gaps if g.severity == GapSeverity.CRITICAL
        )
        self.high_gaps = sum(1 for g in self.gaps if g.severity == GapSeverity.HIGH)
        self.medium_gaps = sum(
            1 for g in self.gaps if g.severity == GapSeverity.MEDIUM
        )
        self.low_gaps = sum(1 for g in self.gaps if g.severity == GapSeverity.LOW)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 3),
            "total_nodes": self.total_nodes,
            "nodes_with_full_coverage": self.nodes_with_full_coverage,
            "nodes_with_partial_coverage": self.nodes_with_partial_coverage,
            "nodes_with_no_coverage": self.nodes_with_no_coverage,
            "category_scores": {
                k.value: round(v, 3) for k, v in self.category_scores.items()
            },
            "gaps_summary": {
                "critical": self.critical_gaps,
                "high": self.high_gaps,
                "medium": self.medium_gaps,
                "low": self.low_gaps,
                "total": len(self.gaps),
            },
            "recommendations_count": len(self.recommendations),
            "generated_at": (
                self.generated_at.isoformat() if self.generated_at else None
            ),
        }

    def to_detailed_dict(self) -> Dict[str, Any]:
        """Full serialization including node-level and gap detail."""
        base = self.to_dict()
        base["node_coverages"] = [nc.to_dict() for nc in self.node_coverages]
        base["gaps"] = [g.to_dict() for g in self.gaps]
        base["recommendations"] = [r.to_dict() for r in self.recommendations]
        return base
