"""
Coverage Scorer.

Walks the entire lineage graph and computes a multi-dimensional
coverage score for every node. Aggregates into a full CoverageReport
with per-category breakdowns.

This is the core differentiator — Elementary's coverage analysis is
locked to dbt tests. This scorer works across any tool connected
to Pallisade: warehouses, orchestrators, BI tools, observability
platforms, and more.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from ..lineage.graph import (
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    NodeType,
)
from .models import (
    CATEGORY_DIMENSIONS,
    CATEGORY_WEIGHTS,
    CRITICALITY_MULTIPLIERS,
    DEFAULT_APPLICABLE_DIMENSIONS,
    NODE_TYPE_APPLICABLE_DIMENSIONS,
    CoverageCategory,
    CoverageDimension,
    CoverageReport,
    CoverageScore,
    DimensionScore,
    NodeCoverage,
)


class CoverageScorer:
    """
    Scores every node in a lineage graph for observability coverage.

    The scorer cross-references the lineage graph against:
    - Existing monitors (from any observability platform)
    - Data contracts (from Pallisade's contract system)
    - Lineage edge metadata (column mappings, evidence)
    - Node metadata (owner, description, tags)

    Each node gets a weighted score across 7 coverage categories.
    """

    def __init__(
        self,
        graph: LineageGraph,
        monitors: Optional[Dict[str, List[str]]] = None,
        contracts: Optional[Dict[str, Dict[str, Any]]] = None,
        findings: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        observability_checks: Optional[Dict[str, List[str]]] = None,
    ):
        """
        Parameters
        ----------
        graph : LineageGraph
            The unified lineage graph to score.
        monitors : dict, optional
            Mapping of node FQN -> list of active monitor types
            (e.g., {"db.schema.table": ["freshness", "volume"]}).
        contracts : dict, optional
            Mapping of node FQN -> contract config dict.
        findings : dict, optional
            Mapping of node FQN -> list of active findings.
        observability_checks : dict, optional
            Mapping of node FQN -> list of check types from external
            observability tools (Monte Carlo, Soda, Elementary, etc.).
        """
        self.graph = graph
        self.monitors = monitors or {}
        self.contracts = contracts or {}
        self.findings = findings or {}
        self.observability_checks = observability_checks or {}

        # Precompute column-level edge indexes.
        self._column_edges: Dict[str, List[LineageEdge]] = {}
        for edge in graph.edges.values():
            if edge.lineage_level == LineageLevel.COLUMN:
                self._column_edges.setdefault(edge.target_id, []).append(edge)
                self._column_edges.setdefault(edge.source_id, []).append(edge)

    def score(self) -> CoverageReport:
        """Score all nodes and produce a full coverage report."""
        report = CoverageReport(
            generated_at=datetime.now(timezone.utc),
        )

        for node_id, node in self.graph.nodes.items():
            node_coverage = self._score_node(node)
            report.node_coverages.append(node_coverage)

        # Aggregate per-category scores (weighted by criticality).
        report.category_scores = self._aggregate_categories(
            report.node_coverages
        )

        # Compute overall score.
        report.overall_score = self._compute_overall_score(
            report.category_scores
        )

        report.compute_summary()
        return report

    def _score_node(self, node: LineageNode) -> NodeCoverage:
        """Compute full coverage for a single node."""
        node_type_str = (
            node.node_type.name
            if isinstance(node.node_type, NodeType)
            else str(node.node_type)
        )

        applicable = self._get_applicable_dimensions(node_type_str)

        nc = NodeCoverage(
            node_id=node.id,
            node_name=node.name or node.fqn or node.id,
            node_type=node_type_str,
            platform=node.platform,
            criticality=getattr(node, "criticality", "medium") or "medium",
            applicable_dimensions=len(applicable),
        )

        # Score each applicable dimension.
        dimension_scores: Dict[CoverageDimension, DimensionScore] = {}
        for dim in applicable:
            ds = self._evaluate_dimension(node, dim)
            dimension_scores[dim] = ds
            if ds.covered:
                nc.covered_dimensions.append(dim)
            else:
                nc.uncovered_dimensions.append(dim)

        nc.covered_count = len(nc.covered_dimensions)

        # Group by category and compute category-level scores.
        for category, dims in CATEGORY_DIMENSIONS.items():
            relevant = [
                dimension_scores[d] for d in dims if d in dimension_scores
            ]
            if not relevant:
                continue

            covered = sum(1 for d in relevant if d.covered)
            score = covered / len(relevant) if relevant else 0.0

            nc.category_scores[category] = CoverageScore(
                category=category,
                score=score,
                dimensions_covered=covered,
                dimensions_total=len(relevant),
                dimension_scores=relevant,
            )

        # Compute weighted overall score.
        nc.overall_score = self._compute_node_overall(nc.category_scores)

        return nc

    def _evaluate_dimension(
        self, node: LineageNode, dimension: CoverageDimension
    ) -> DimensionScore:
        """Evaluate a single coverage dimension for a node."""
        node_fqn = self._get_node_fqn(node)
        ext_checks = self.observability_checks.get(node_fqn, [])
        mon_types = self.monitors.get(node_fqn, [])
        contract = self.contracts.get(node_fqn, {})

        # Dispatch to dimension-specific evaluation.
        evaluator = self._dimension_evaluators.get(dimension)
        if evaluator:
            return evaluator(self, node, node_fqn, mon_types, ext_checks, contract)

        # Default: uncovered.
        return DimensionScore(
            dimension=dimension, covered=False, score=0.0
        )

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _eval_freshness_monitor(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "freshness" in monitors
            or "FRESHNESS" in ext_checks
            or any(c in ext_checks for c in ("freshness", "freshness_anomalies"))
        )
        return DimensionScore(
            dimension=CoverageDimension.FRESHNESS_MONITOR,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "freshness"),
        )

    def _eval_freshness_sla(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        has_sla = (
            bool(contract.get("freshnessEnabled"))
            or getattr(node, "expected_freshness_hours", None) is not None
        )
        return DimensionScore(
            dimension=CoverageDimension.FRESHNESS_SLA,
            covered=has_sla,
            score=1.0 if has_sla else 0.0,
            source="data_contract" if has_sla else None,
        )

    def _eval_row_count_monitor(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "volume" in monitors
            or "VOLUME" in ext_checks
            or any(c in ext_checks for c in ("volume", "volume_anomalies", "row_count"))
        )
        return DimensionScore(
            dimension=CoverageDimension.ROW_COUNT_MONITOR,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "volume"),
        )

    def _eval_volume_anomaly(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = any(
            c in ext_checks
            for c in ("volume_anomalies", "ANOMALY", "anomaly")
        ) or "anomaly" in monitors
        return DimensionScore(
            dimension=CoverageDimension.VOLUME_ANOMALY,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "anomaly"),
        )

    def _eval_schema_change(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "schema_change" in monitors
            or "SCHEMA" in ext_checks
            or any(
                c in ext_checks
                for c in ("schema", "schema_changes", "schema_change_detection")
            )
        )
        return DimensionScore(
            dimension=CoverageDimension.SCHEMA_CHANGE_DETECTION,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "schema"),
        )

    def _eval_schema_contract(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        has_contract = bool(contract.get("schemaEnabled"))
        return DimensionScore(
            dimension=CoverageDimension.SCHEMA_CONTRACT,
            covered=has_contract,
            score=1.0 if has_contract else 0.0,
            source="data_contract" if has_contract else None,
        )

    def _eval_column_type_validation(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        # Covered if we have schema info (columns) from any source
        # or an explicit data_type_validation monitor.
        has_columns = bool(getattr(node, "columns", None))
        has_monitor = "data_type_validation" in monitors
        covered = has_columns or has_monitor
        return DimensionScore(
            dimension=CoverageDimension.COLUMN_TYPE_VALIDATION,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=("pallisade_monitor" if has_monitor else node.platform) if covered else None,
        )

    def _eval_null_rate(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "null_rate" in monitors
            or "null_check" in monitors
            or "NULLS" in ext_checks
            or any(c in ext_checks for c in ("nulls", "null_rate", "not_null"))
            or bool(contract.get("maxNullRate"))
        )
        return DimensionScore(
            dimension=CoverageDimension.NULL_RATE_MONITOR,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "null"),
        )

    def _eval_uniqueness(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "uniqueness" in monitors
            or "uniqueness_check" in monitors
            or "UNIQUENESS" in ext_checks
            or any(c in ext_checks for c in ("uniqueness", "unique", "distinct"))
            or bool(contract.get("maxDuplicateRate"))
            or any(
                m.get("config", {}).get("metric") == "distinct_count"
                for m in monitors.values()
                if isinstance(m, dict)
            )
        )
        return DimensionScore(
            dimension=CoverageDimension.UNIQUENESS_CHECK,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "uniqueness"),
        )

    def _eval_referential(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "referential" in monitors
            or "REFERENTIAL" in ext_checks
            or any(
                c in ext_checks
                for c in ("referential", "referential_integrity", "relationships")
            )
        )
        return DimensionScore(
            dimension=CoverageDimension.REFERENTIAL_INTEGRITY,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "referential"),
        )

    def _eval_distribution(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        # Legacy dimension — also satisfied by outlier_detection
        covered = (
            "distribution" in monitors
            or "outlier_detection" in monitors
            or "DISTRIBUTION" in ext_checks
            or any(
                c in ext_checks
                for c in ("distribution", "column_anomalies", "dimension_anomalies")
            )
        )
        return DimensionScore(
            dimension=CoverageDimension.DISTRIBUTION_MONITOR,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "distribution"),
        )

    def _eval_custom_sql(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "custom_sql" in monitors
            or "CUSTOM_SQL" in ext_checks
            or any(c in ext_checks for c in ("custom_sql", "custom"))
        )
        return DimensionScore(
            dimension=CoverageDimension.CUSTOM_SQL_CHECK,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "custom_sql"),
        )

    def _eval_anomaly_detection(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        # Legacy dimension — also satisfied by outlier_detection
        covered = (
            "anomaly" in monitors
            or "outlier_detection" in monitors
            or "ANOMALY" in ext_checks
            or any(
                c in ext_checks
                for c in (
                    "anomaly",
                    "anomaly_detection",
                    "all_columns_anomalies",
                    "column_anomalies",
                )
            )
        )
        return DimensionScore(
            dimension=CoverageDimension.ANOMALY_DETECTION,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "anomaly"),
        )

    def _eval_upstream_linked(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        upstream = self.graph._upstream.get(node.id, set())
        covered = len(upstream) > 0
        return DimensionScore(
            dimension=CoverageDimension.UPSTREAM_LINKED,
            covered=covered,
            score=1.0 if covered else 0.0,
            details=f"{len(upstream)} upstream nodes" if covered else None,
        )

    def _eval_downstream_linked(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        downstream = self.graph._downstream.get(node.id, set())
        covered = len(downstream) > 0
        return DimensionScore(
            dimension=CoverageDimension.DOWNSTREAM_LINKED,
            covered=covered,
            score=1.0 if covered else 0.0,
            details=f"{len(downstream)} downstream nodes" if covered else None,
        )

    def _eval_column_lineage(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        col_edges = self._column_edges.get(node.id, [])
        covered = len(col_edges) > 0
        return DimensionScore(
            dimension=CoverageDimension.COLUMN_LINEAGE_MAPPED,
            covered=covered,
            score=1.0 if covered else 0.0,
            details=(
                f"{len(col_edges)} column-level edges" if covered else None
            ),
        )

    def _eval_owner_assigned(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        has_owner = bool(
            getattr(node, "owner", None) or contract.get("owner")
        )
        return DimensionScore(
            dimension=CoverageDimension.OWNER_ASSIGNED,
            covered=has_owner,
            score=1.0 if has_owner else 0.0,
            source=node.platform if has_owner else None,
        )

    def _eval_description(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        has_desc = bool(
            getattr(node, "description", None)
            or contract.get("description")
        )
        return DimensionScore(
            dimension=CoverageDimension.DESCRIPTION_EXISTS,
            covered=has_desc,
            score=1.0 if has_desc else 0.0,
        )

    def _eval_tags(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        has_tags = bool(getattr(node, "tags", None))
        return DimensionScore(
            dimension=CoverageDimension.TAGS_APPLIED,
            covered=has_tags,
            score=1.0 if has_tags else 0.0,
        )

    def _eval_data_contract(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        has_contract = bool(contract)
        return DimensionScore(
            dimension=CoverageDimension.DATA_CONTRACT_EXISTS,
            covered=has_contract,
            score=1.0 if has_contract else 0.0,
            source="data_contract" if has_contract else None,
        )

    # ------------------------------------------------------------------
    # New canonical dimension evaluators
    # ------------------------------------------------------------------

    def _eval_range_validation(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = "range_validation" in monitors
        return DimensionScore(
            dimension=CoverageDimension.RANGE_VALIDATION_CHECK,
            covered=covered,
            score=1.0 if covered else 0.0,
            source="pallisade_monitor" if covered else None,
        )

    def _eval_accepted_values(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = "accepted_values" in monitors
        return DimensionScore(
            dimension=CoverageDimension.ACCEPTED_VALUES_CHECK,
            covered=covered,
            score=1.0 if covered else 0.0,
            source="pallisade_monitor" if covered else None,
        )

    def _eval_date_consistency(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = "date_consistency" in monitors
        return DimensionScore(
            dimension=CoverageDimension.DATE_CONSISTENCY_CHECK,
            covered=covered,
            score=1.0 if covered else 0.0,
            source="pallisade_monitor" if covered else None,
        )

    def _eval_outlier_detection(
        self, node, fqn, monitors, ext_checks, contract
    ) -> DimensionScore:
        covered = (
            "outlier_detection" in monitors
            or "anomaly" in monitors
            or any(
                c in ext_checks
                for c in ("anomaly", "anomaly_detection", "column_anomalies")
            )
        )
        return DimensionScore(
            dimension=CoverageDimension.OUTLIER_DETECTION,
            covered=covered,
            score=1.0 if covered else 0.0,
            source=self._find_source(monitors, ext_checks, "anomaly") or (
                "pallisade_monitor" if "outlier_detection" in monitors else None
            ),
        )

    # Map of dimension -> evaluator method.
    _dimension_evaluators: Dict = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_applicable_dimensions(
        self, node_type: str
    ) -> List[CoverageDimension]:
        return NODE_TYPE_APPLICABLE_DIMENSIONS.get(
            node_type, DEFAULT_APPLICABLE_DIMENSIONS
        )

    def _get_node_fqn(self, node: LineageNode) -> str:
        """Build the FQN used for looking up monitors/contracts."""
        if node.fqn:
            return node.fqn.lower()
        parts = [
            p
            for p in (
                getattr(node, "database", None),
                getattr(node, "schema", None),
                node.name,
            )
            if p
        ]
        return ".".join(parts).lower()

    @staticmethod
    def _find_source(
        monitors: List[str],
        ext_checks: List[str],
        keyword: str,
    ) -> Optional[str]:
        if keyword in monitors:
            return "pallisade_monitor"
        for check in ext_checks:
            if keyword.lower() in check.lower():
                return "external_observability"
        return None

    def _aggregate_categories(
        self, node_coverages: List[NodeCoverage]
    ) -> Dict[CoverageCategory, float]:
        """Compute weighted average per category across all nodes."""
        aggregated: Dict[CoverageCategory, float] = {}

        for category in CoverageCategory:
            total_weight = 0.0
            weighted_sum = 0.0

            for nc in node_coverages:
                cs = nc.category_scores.get(category)
                if cs is None:
                    continue

                crit_mult = CRITICALITY_MULTIPLIERS.get(nc.criticality, 1.0)
                weight = crit_mult
                weighted_sum += cs.score * weight
                total_weight += weight

            aggregated[category] = (
                weighted_sum / total_weight if total_weight > 0 else 0.0
            )

        return aggregated

    def _compute_overall_score(
        self, category_scores: Dict[CoverageCategory, float]
    ) -> float:
        """Compute final weighted overall score."""
        total = 0.0
        weight_sum = 0.0
        for category, weight in CATEGORY_WEIGHTS.items():
            score = category_scores.get(category, 0.0)
            total += score * weight
            weight_sum += weight

        return total / weight_sum if weight_sum > 0 else 0.0

    def _compute_node_overall(
        self, category_scores: Dict[CoverageCategory, CoverageScore]
    ) -> float:
        """Compute weighted overall score for a single node."""
        total = 0.0
        weight_sum = 0.0
        for category, weight in CATEGORY_WEIGHTS.items():
            cs = category_scores.get(category)
            if cs is None:
                continue
            total += cs.score * weight
            weight_sum += weight

        return total / weight_sum if weight_sum > 0 else 0.0


# Populate the dimension evaluator dispatch table.
CoverageScorer._dimension_evaluators = {
    CoverageDimension.FRESHNESS_MONITOR: CoverageScorer._eval_freshness_monitor,
    CoverageDimension.FRESHNESS_SLA: CoverageScorer._eval_freshness_sla,
    CoverageDimension.ROW_COUNT_MONITOR: CoverageScorer._eval_row_count_monitor,
    CoverageDimension.VOLUME_ANOMALY: CoverageScorer._eval_volume_anomaly,
    CoverageDimension.SCHEMA_CHANGE_DETECTION: CoverageScorer._eval_schema_change,
    CoverageDimension.SCHEMA_CONTRACT: CoverageScorer._eval_schema_contract,
    CoverageDimension.COLUMN_TYPE_VALIDATION: CoverageScorer._eval_column_type_validation,
    CoverageDimension.NULL_RATE_MONITOR: CoverageScorer._eval_null_rate,
    CoverageDimension.UNIQUENESS_CHECK: CoverageScorer._eval_uniqueness,
    CoverageDimension.REFERENTIAL_INTEGRITY: CoverageScorer._eval_referential,
    CoverageDimension.RANGE_VALIDATION_CHECK: CoverageScorer._eval_range_validation,
    CoverageDimension.ACCEPTED_VALUES_CHECK: CoverageScorer._eval_accepted_values,
    CoverageDimension.DATE_CONSISTENCY_CHECK: CoverageScorer._eval_date_consistency,
    CoverageDimension.CUSTOM_SQL_CHECK: CoverageScorer._eval_custom_sql,
    CoverageDimension.OUTLIER_DETECTION: CoverageScorer._eval_outlier_detection,
    # Legacy dimensions (kept for backward compat)
    CoverageDimension.DISTRIBUTION_MONITOR: CoverageScorer._eval_distribution,
    CoverageDimension.ANOMALY_DETECTION: CoverageScorer._eval_anomaly_detection,
    CoverageDimension.UPSTREAM_LINKED: CoverageScorer._eval_upstream_linked,
    CoverageDimension.DOWNSTREAM_LINKED: CoverageScorer._eval_downstream_linked,
    CoverageDimension.COLUMN_LINEAGE_MAPPED: CoverageScorer._eval_column_lineage,
    CoverageDimension.OWNER_ASSIGNED: CoverageScorer._eval_owner_assigned,
    CoverageDimension.DESCRIPTION_EXISTS: CoverageScorer._eval_description,
    CoverageDimension.TAGS_APPLIED: CoverageScorer._eval_tags,
    CoverageDimension.DATA_CONTRACT_EXISTS: CoverageScorer._eval_data_contract,
}
