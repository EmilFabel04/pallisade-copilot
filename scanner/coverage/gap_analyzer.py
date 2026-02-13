"""
Gap Analyzer and Monitor Recommender.

Takes the coverage report from the scorer and identifies the most
impactful gaps, prioritizes them by risk, and generates concrete
monitor recommendations to close them.

This is analogous to Elementary's test recommendations, but works
across any integration and produces tech-agnostic SQL monitors.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..lineage.graph import LineageGraph
from .models import (
    CATEGORY_DIMENSIONS,
    CoverageCategory,
    CoverageDimension,
    CoverageGap,
    CoverageReport,
    GapSeverity,
    MonitorRecommendation,
    MonitorType,
    NodeCoverage,
)


# Map coverage dimensions to the monitor type that closes them.
DIMENSION_TO_MONITOR: Dict[CoverageDimension, MonitorType] = {
    CoverageDimension.FRESHNESS_MONITOR: MonitorType.FRESHNESS,
    CoverageDimension.FRESHNESS_SLA: MonitorType.FRESHNESS,
    CoverageDimension.ROW_COUNT_MONITOR: MonitorType.VOLUME,
    CoverageDimension.VOLUME_ANOMALY: MonitorType.VOLUME,
    CoverageDimension.SCHEMA_CHANGE_DETECTION: MonitorType.SCHEMA_CHANGE,
    CoverageDimension.NULL_RATE_MONITOR: MonitorType.NULL_RATE,
    CoverageDimension.UNIQUENESS_CHECK: MonitorType.UNIQUENESS,
    CoverageDimension.REFERENTIAL_INTEGRITY: MonitorType.REFERENTIAL,
    CoverageDimension.DISTRIBUTION_MONITOR: MonitorType.DISTRIBUTION,
    CoverageDimension.CUSTOM_SQL_CHECK: MonitorType.CUSTOM_SQL,
    CoverageDimension.ANOMALY_DETECTION: MonitorType.ANOMALY,
}

# SQL templates for tech-agnostic monitor recommendations.
MONITOR_SQL_TEMPLATES: Dict[MonitorType, str] = {
    MonitorType.FRESHNESS: (
        "SELECT MAX({timestamp_column}) AS last_value, "
        "EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX({timestamp_column}))) "
        "/ 3600.0 AS hours_since_update "
        "FROM {fqn} WHERE {timestamp_column} IS NOT NULL"
    ),
    MonitorType.VOLUME: "SELECT COUNT(*) AS row_count FROM {fqn}",
    MonitorType.SCHEMA_CHANGE: (
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = '{schema}' AND table_name = '{table}' "
        "ORDER BY ordinal_position"
    ),
    MonitorType.NULL_RATE: (
        "SELECT '{column}' AS column_name, "
        "CAST(SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END) AS FLOAT) "
        "/ NULLIF(COUNT(*), 0) AS null_rate "
        "FROM {fqn}"
    ),
    MonitorType.UNIQUENESS: (
        "SELECT COUNT(*) AS total_rows, "
        "COUNT(DISTINCT {column}) AS distinct_count, "
        "COUNT(*) - COUNT(DISTINCT {column}) AS duplicate_count "
        "FROM {fqn}"
    ),
    MonitorType.DISTRIBUTION: (
        "SELECT {column}, COUNT(*) AS cnt "
        "FROM {fqn} GROUP BY {column} ORDER BY cnt DESC LIMIT 100"
    ),
    MonitorType.ANOMALY: (
        "SELECT CAST({timestamp_column} AS DATE) AS bucket, "
        "COUNT(*) AS row_count "
        "FROM {fqn} "
        "WHERE {timestamp_column} >= CURRENT_DATE - INTERVAL '30 days' "
        "GROUP BY CAST({timestamp_column} AS DATE) ORDER BY bucket"
    ),
}

# Human-readable descriptions for each gap dimension.
GAP_DESCRIPTIONS: Dict[CoverageDimension, Dict[str, str]] = {
    CoverageDimension.FRESHNESS_MONITOR: {
        "title": "No freshness monitoring",
        "description": (
            "This asset has no monitor checking how recently its data "
            "was updated. Stale data could propagate to downstream "
            "consumers without detection."
        ),
        "impact": (
            "Downstream dashboards and models may use outdated data, "
            "leading to incorrect business decisions."
        ),
        "recommendation": (
            "Add a freshness monitor with a threshold based on the "
            "expected update frequency of this asset."
        ),
    },
    CoverageDimension.FRESHNESS_SLA: {
        "title": "No freshness SLA defined",
        "description": (
            "This asset has no documented freshness SLA or data contract "
            "defining how fresh the data should be."
        ),
        "impact": (
            "Without an SLA, there is no objective measure of whether "
            "data freshness meets business requirements."
        ),
        "recommendation": (
            "Define a freshness SLA in a data contract specifying the "
            "maximum acceptable data age in hours."
        ),
    },
    CoverageDimension.ROW_COUNT_MONITOR: {
        "title": "No volume monitoring",
        "description": (
            "This asset has no monitor tracking row counts or volume "
            "changes over time."
        ),
        "impact": (
            "Unexpected drops in row count (from failed loads) or spikes "
            "(from duplicate ingestion) will go undetected."
        ),
        "recommendation": (
            "Add a volume monitor to track row counts and detect "
            "anomalous changes."
        ),
    },
    CoverageDimension.VOLUME_ANOMALY: {
        "title": "No volume anomaly detection",
        "description": (
            "This asset lacks statistical anomaly detection for volume "
            "changes. Simple threshold checks may miss subtle issues."
        ),
        "impact": (
            "Gradual data drift or seasonal anomalies will not be "
            "caught until they cause visible business impact."
        ),
        "recommendation": (
            "Enable anomaly detection (Z-score based) on the daily "
            "row count with at least 30 days of baseline data."
        ),
    },
    CoverageDimension.SCHEMA_CHANGE_DETECTION: {
        "title": "No schema change detection",
        "description": (
            "This asset is not monitored for schema changes (column "
            "additions, deletions, or type changes)."
        ),
        "impact": (
            "Upstream schema changes can break downstream transformations, "
            "BI dashboards, and API contracts silently."
        ),
        "recommendation": (
            "Add a schema change monitor that compares the current schema "
            "against a baseline on each scan."
        ),
    },
    CoverageDimension.SCHEMA_CONTRACT: {
        "title": "No schema contract",
        "description": (
            "This asset has no formal schema contract defining expected "
            "columns, types, and constraints."
        ),
        "impact": (
            "Without a schema contract, there is no authoritative "
            "definition of what the table should look like."
        ),
        "recommendation": (
            "Create a data contract with the expected schema definition "
            "including column names, types, and nullability."
        ),
    },
    CoverageDimension.NULL_RATE_MONITOR: {
        "title": "No null rate monitoring",
        "description": (
            "No monitor is checking for unexpected null values in "
            "this asset's columns."
        ),
        "impact": (
            "Null values in critical columns can cause calculation "
            "errors, broken joins, and incorrect aggregations."
        ),
        "recommendation": (
            "Add null rate monitors for columns that should not "
            "contain nulls, or set a maximum null rate threshold."
        ),
    },
    CoverageDimension.UNIQUENESS_CHECK: {
        "title": "No uniqueness check",
        "description": (
            "No monitor is verifying that primary key or unique "
            "columns maintain their uniqueness constraints."
        ),
        "impact": (
            "Duplicate rows can cause incorrect aggregations, "
            "fan-out in joins, and inflated metrics."
        ),
        "recommendation": (
            "Add uniqueness checks on primary key columns and "
            "any columns expected to be unique."
        ),
    },
    CoverageDimension.UPSTREAM_LINKED: {
        "title": "No upstream lineage",
        "description": (
            "This asset has no documented upstream dependencies "
            "in the lineage graph."
        ),
        "impact": (
            "Without upstream lineage, root cause analysis is "
            "impossible when data quality issues occur."
        ),
        "recommendation": (
            "Connect additional integrations or verify that the "
            "asset's source dependencies are being captured."
        ),
    },
    CoverageDimension.DOWNSTREAM_LINKED: {
        "title": "No downstream lineage",
        "description": (
            "This asset has no documented downstream consumers "
            "in the lineage graph."
        ),
        "impact": (
            "Impact analysis cannot determine who is affected "
            "when this asset has issues."
        ),
        "recommendation": (
            "Connect downstream tools (BI, orchestrators) or "
            "verify that consumer relationships are being captured."
        ),
    },
    CoverageDimension.COLUMN_LINEAGE_MAPPED: {
        "title": "No column-level lineage",
        "description": (
            "This asset only has table-level lineage. Column-level "
            "mappings showing which columns derive from which "
            "sources are not available."
        ),
        "impact": (
            "Fine-grained impact analysis and root cause analysis "
            "at the column level is not possible."
        ),
        "recommendation": (
            "Ensure SQL transformations use explicit SELECT lists "
            "(not SELECT *) and that dbt or SQL parsing can map "
            "column dependencies."
        ),
    },
    CoverageDimension.OWNER_ASSIGNED: {
        "title": "No owner assigned",
        "description": (
            "This asset has no designated owner for accountability."
        ),
        "impact": (
            "When incidents occur, there is no clear person "
            "responsible for triaging and resolving issues."
        ),
        "recommendation": (
            "Assign an owner in the data contract or source "
            "platform (dbt, warehouse grants, etc.)."
        ),
    },
    CoverageDimension.DESCRIPTION_EXISTS: {
        "title": "No description",
        "description": "This asset has no documentation or description.",
        "impact": (
            "Users cannot understand the purpose, contents, or "
            "intended use of this asset without manual investigation."
        ),
        "recommendation": (
            "Add a description in the source platform (dbt schema.yml, "
            "warehouse comment, or data contract)."
        ),
    },
    CoverageDimension.DATA_CONTRACT_EXISTS: {
        "title": "No data contract",
        "description": (
            "This asset has no formal data contract defining SLAs, "
            "quality expectations, and ownership."
        ),
        "impact": (
            "Without a data contract, there are no enforceable "
            "quality guarantees for consumers of this data."
        ),
        "recommendation": (
            "Create a data contract defining freshness SLA, "
            "quality thresholds, schema expectations, and ownership."
        ),
    },
}

# All warehouse-type integrations that can run SQL monitors.
WAREHOUSE_INTEGRATIONS = [
    "SNOWFLAKE",
    "BIGQUERY",
    "POSTGRES",
    "REDSHIFT",
    "SQLSERVER",
    "AZURE_SQL",
    "AZURE_SYNAPSE",
]


class GapAnalyzer:
    """
    Analyzes coverage gaps and generates prioritized monitor
    recommendations.
    """

    def __init__(self, graph: LineageGraph):
        self.graph = graph

    def analyze(self, report: CoverageReport) -> CoverageReport:
        """
        Enrich a coverage report with gaps and recommendations.

        Mutates the report in place (adds gaps and recommendations)
        and returns it.
        """
        gaps: List[CoverageGap] = []

        for nc in report.node_coverages:
            node_gaps = self._gaps_for_node(nc)
            gaps.extend(node_gaps)

        # Sort gaps: critical first, then by downstream impact.
        gaps.sort(
            key=lambda g: (
                _severity_rank(g.severity),
                -g.downstream_count,
                g.node_name,
            )
        )
        report.gaps = gaps

        # Generate monitor recommendations from the gaps.
        report.recommendations = self._generate_recommendations(gaps)

        report.compute_summary()
        return report

    def _gaps_for_node(self, nc: NodeCoverage) -> List[CoverageGap]:
        """Generate gap entries for all uncovered dimensions of a node."""
        gaps: List[CoverageGap] = []

        # Look up the node in the graph for extra context.
        node = self.graph.nodes.get(nc.node_id)
        upstream_count = len(
            self.graph._upstream.get(nc.node_id, set())
        )
        downstream_count = len(
            self.graph._downstream.get(nc.node_id, set())
        )

        for dim in nc.uncovered_dimensions:
            category = _dimension_category(dim)
            severity = self._compute_gap_severity(
                dim, nc.criticality, upstream_count, downstream_count
            )

            desc_info = GAP_DESCRIPTIONS.get(dim, {})

            gap = CoverageGap(
                node_id=nc.node_id,
                node_name=nc.node_name,
                node_type=nc.node_type,
                dimension=dim,
                category=category,
                severity=severity,
                title=desc_info.get("title", f"Missing {dim.value}"),
                description=desc_info.get(
                    "description", f"Coverage dimension {dim.value} is not met."
                ),
                impact=desc_info.get("impact", "Unknown impact."),
                recommendation=desc_info.get(
                    "recommendation", f"Add a {dim.value} check."
                ),
                criticality=nc.criticality,
                upstream_count=upstream_count,
                downstream_count=downstream_count,
                platform=nc.platform,
            )
            gaps.append(gap)

        return gaps

    def _compute_gap_severity(
        self,
        dim: CoverageDimension,
        criticality: str,
        upstream_count: int,
        downstream_count: int,
    ) -> GapSeverity:
        """
        Compute gap severity based on:
        - The dimension type (freshness/schema gaps are more severe)
        - The node's criticality level
        - Its position in the graph (more downstream = higher impact)
        """
        # Base severity by dimension category.
        base_severity_map = {
            CoverageDimension.FRESHNESS_MONITOR: 3,
            CoverageDimension.SCHEMA_CHANGE_DETECTION: 3,
            CoverageDimension.NULL_RATE_MONITOR: 2,
            CoverageDimension.UNIQUENESS_CHECK: 2,
            CoverageDimension.ROW_COUNT_MONITOR: 2,
            CoverageDimension.UPSTREAM_LINKED: 2,
            CoverageDimension.COLUMN_LINEAGE_MAPPED: 1,
            CoverageDimension.OWNER_ASSIGNED: 1,
            CoverageDimension.DESCRIPTION_EXISTS: 0,
            CoverageDimension.TAGS_APPLIED: 0,
        }
        base = base_severity_map.get(dim, 1)

        # Criticality boost.
        crit_boost = {"critical": 2, "high": 1, "medium": 0, "low": -1}
        base += crit_boost.get(criticality, 0)

        # Downstream fan-out boost — more consumers = higher impact.
        if downstream_count >= 10:
            base += 2
        elif downstream_count >= 5:
            base += 1

        # Map numeric score to severity.
        if base >= 5:
            return GapSeverity.CRITICAL
        elif base >= 3:
            return GapSeverity.HIGH
        elif base >= 2:
            return GapSeverity.MEDIUM
        elif base >= 1:
            return GapSeverity.LOW
        else:
            return GapSeverity.INFO

    def _generate_recommendations(
        self, gaps: List[CoverageGap]
    ) -> List[MonitorRecommendation]:
        """
        Generate deduplicated monitor recommendations from the gap list.

        Groups gaps by (node, monitor_type) to avoid recommending the
        same monitor multiple times for the same asset.
        """
        seen: set = set()
        recommendations: List[MonitorRecommendation] = []

        for gap in gaps:
            monitor_type = DIMENSION_TO_MONITOR.get(gap.dimension)
            if monitor_type is None:
                # Dimension doesn't map to a runnable monitor
                # (e.g., ownership, description).
                continue

            key = (gap.node_id, monitor_type)
            if key in seen:
                # Already have a recommendation for this node+monitor.
                # Add the dimension to the existing one.
                for rec in recommendations:
                    if (
                        rec.target_node_id == gap.node_id
                        and rec.monitor_type == monitor_type
                    ):
                        if gap.dimension not in rec.closes_gaps:
                            rec.closes_gaps.append(gap.dimension)
                        break
                continue
            seen.add(key)

            sql_template = MONITOR_SQL_TEMPLATES.get(monitor_type)

            rec = MonitorRecommendation(
                monitor_type=monitor_type,
                target_node_id=gap.node_id,
                target_node_name=gap.node_name,
                target_platform=gap.platform,
                closes_gaps=[gap.dimension],
                priority=gap.severity,
                description=self._monitor_description(monitor_type, gap),
                sql_template=sql_template,
                compatible_integrations=WAREHOUSE_INTEGRATIONS,
                config=self._default_config(monitor_type),
            )
            recommendations.append(rec)

        # Sort by priority (critical first).
        recommendations.sort(key=lambda r: _severity_rank(r.priority))
        return recommendations

    @staticmethod
    def _monitor_description(
        monitor_type: MonitorType, gap: CoverageGap
    ) -> str:
        descs = {
            MonitorType.FRESHNESS: (
                f"Monitor data freshness for {gap.node_name} by checking "
                f"the most recent timestamp value."
            ),
            MonitorType.VOLUME: (
                f"Monitor row count for {gap.node_name} and detect "
                f"anomalous volume changes using Z-score analysis."
            ),
            MonitorType.SCHEMA_CHANGE: (
                f"Detect schema changes (added/removed columns, type "
                f"changes) for {gap.node_name}."
            ),
            MonitorType.NULL_RATE: (
                f"Monitor null rates across columns in {gap.node_name} "
                f"and alert when rates exceed thresholds."
            ),
            MonitorType.UNIQUENESS: (
                f"Verify uniqueness constraints on key columns in "
                f"{gap.node_name}."
            ),
            MonitorType.DISTRIBUTION: (
                f"Monitor value distribution changes in {gap.node_name} "
                f"columns to detect data drift."
            ),
            MonitorType.REFERENTIAL: (
                f"Verify referential integrity between {gap.node_name} "
                f"and its related tables."
            ),
            MonitorType.CUSTOM_SQL: (
                f"Run custom SQL assertions against {gap.node_name}."
            ),
            MonitorType.ANOMALY: (
                f"Statistical anomaly detection across metrics for "
                f"{gap.node_name} using Z-score analysis."
            ),
        }
        return descs.get(monitor_type, f"Monitor {gap.node_name}.")

    @staticmethod
    def _default_config(monitor_type: MonitorType) -> Dict[str, Any]:
        """Sensible default config for each monitor type."""
        defaults = {
            MonitorType.FRESHNESS: {
                "max_hours": 24,
                "timestamp_column": "updated_at",
            },
            MonitorType.VOLUME: {
                "anomaly_threshold": 3.0,
                "lookback_days": 30,
            },
            MonitorType.SCHEMA_CHANGE: {
                "fail_on_column_removed": True,
                "fail_on_type_change": True,
                "fail_on_column_added": False,
            },
            MonitorType.NULL_RATE: {"max_null_rate": 0.05},
            MonitorType.UNIQUENESS: {"max_duplicate_rate": 0.0},
            MonitorType.DISTRIBUTION: {"lookback_days": 30},
            MonitorType.ANOMALY: {
                "anomaly_threshold": 3.0,
                "lookback_days": 30,
            },
        }
        return defaults.get(monitor_type, {})


def _dimension_category(dim: CoverageDimension) -> CoverageCategory:
    """Find which category a dimension belongs to."""
    for cat, dims in CATEGORY_DIMENSIONS.items():
        if dim in dims:
            return cat
    return CoverageCategory.QUALITY


def _severity_rank(severity: GapSeverity) -> int:
    """Numeric rank for sorting (lower = more severe)."""
    return {
        GapSeverity.CRITICAL: 0,
        GapSeverity.HIGH: 1,
        GapSeverity.MEDIUM: 2,
        GapSeverity.LOW: 3,
        GapSeverity.INFO: 4,
    }.get(severity, 5)
