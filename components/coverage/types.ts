/**
 * Coverage analysis type definitions.
 *
 * These types mirror the Python coverage engine models and define
 * the data shapes used in the frontend for coverage visualization.
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type CoverageCategory =
  | "freshness"
  | "volume"
  | "schema"
  | "quality"
  | "lineage"
  | "ownership"
  | "documentation";

export type CoverageDimension =
  | "freshness_monitor"
  | "freshness_sla"
  | "row_count_monitor"
  | "volume_anomaly"
  | "schema_change_detection"
  | "schema_contract"
  | "column_type_validation"
  | "null_rate_monitor"
  | "uniqueness_check"
  | "referential_integrity"
  | "range_validation_check"
  | "accepted_values_check"
  | "date_consistency_check"
  | "custom_sql_check"
  | "outlier_detection"
  // Legacy (kept for backward compat)
  | "distribution_monitor"
  | "anomaly_detection"
  | "upstream_linked"
  | "downstream_linked"
  | "column_lineage_mapped"
  | "owner_assigned"
  | "description_exists"
  | "tags_applied"
  | "data_contract_exists";

export type GapSeverity = "critical" | "high" | "medium" | "low" | "info";

export type MonitorType =
  | "freshness"
  | "volume"
  | "schema_change"
  | "referential"
  | "custom_sql"
  // New canonical types
  | "null_check"
  | "uniqueness_check"
  | "range_validation"
  | "accepted_values"
  | "date_consistency"
  | "data_type_validation"
  | "outlier_detection"
  // Legacy (kept for backward compat)
  | "null_rate"
  | "distribution"
  | "anomaly";

// ---------------------------------------------------------------------------
// Score types
// ---------------------------------------------------------------------------

export interface DimensionScore {
  dimension: CoverageDimension;
  covered: boolean;
  score: number;
  source: string | null;
  details: string | null;
  monitor_id: string | null;
}

export interface CategoryScore {
  category: CoverageCategory;
  score: number;
  dimensions_covered: number;
  dimensions_total: number;
  coverage_ratio: number;
  dimension_scores: DimensionScore[];
}

export interface NodeCoverage {
  node_id: string;
  node_name: string;
  node_type: string;
  platform: string | null;
  criticality: string;
  overall_score: number;
  coverage_percent: number;
  applicable_dimensions: number;
  covered_count: number;
  uncovered_dimensions: string[];
  covered_dimensions: string[];
  category_scores: Record<string, CategoryScore>;
}

// ---------------------------------------------------------------------------
// Gap types
// ---------------------------------------------------------------------------

export interface CoverageGap {
  node_id: string;
  node_name: string;
  node_type: string;
  dimension: CoverageDimension;
  category: CoverageCategory;
  severity: GapSeverity;
  title: string;
  description: string;
  impact: string;
  recommendation: string;
  criticality: string;
  upstream_count: number;
  downstream_count: number;
  platform: string | null;
}

// ---------------------------------------------------------------------------
// Recommendation types
// ---------------------------------------------------------------------------

export interface MonitorRecommendation {
  monitor_type: MonitorType;
  target_node_id: string;
  target_node_name: string;
  target_platform: string | null;
  config: Record<string, unknown>;
  closes_gaps: string[];
  priority: GapSeverity;
  description: string;
  sql_template: string | null;
  compatible_integrations: string[];
}

// ---------------------------------------------------------------------------
// Report types
// ---------------------------------------------------------------------------

export interface CoverageReportSummary {
  overall_score: number;
  total_nodes: number;
  nodes_with_full_coverage: number;
  nodes_with_partial_coverage: number;
  nodes_with_no_coverage: number;
  category_scores: Record<CoverageCategory, number>;
  gaps_summary: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    total: number;
  };
  recommendations_count: number;
  generated_at: string | null;
}

export interface CoverageReportDetailed extends CoverageReportSummary {
  node_coverages: NodeCoverage[];
  gaps: CoverageGap[];
  recommendations: MonitorRecommendation[];
}

// ---------------------------------------------------------------------------
// Visual constants
// ---------------------------------------------------------------------------

export const COVERAGE_COLORS = {
  excellent: "#10B981", // >= 80%
  good: "#22C55E", // >= 60%
  fair: "#F59E0B", // >= 40%
  poor: "#F97316", // >= 20%
  critical: "#EF4444", // < 20%
} as const;

export const SEVERITY_COLORS: Record<GapSeverity, string> = {
  critical: "#EF4444",
  high: "#F97316",
  medium: "#F59E0B",
  low: "#3B82F6",
  info: "#6B7280",
};

export const CATEGORY_COLORS: Record<CoverageCategory, string> = {
  freshness: "#06B6D4",
  volume: "#8B5CF6",
  schema: "#F59E0B",
  quality: "#10B981",
  lineage: "#3B82F6",
  ownership: "#F97316",
  documentation: "#6B7280",
};

export const CATEGORY_LABELS: Record<CoverageCategory, string> = {
  freshness: "Freshness",
  volume: "Volume",
  schema: "Schema",
  quality: "Quality",
  lineage: "Lineage",
  ownership: "Ownership",
  documentation: "Documentation",
};

export function getCoverageColor(percent: number): string {
  if (percent >= 80) return COVERAGE_COLORS.excellent;
  if (percent >= 60) return COVERAGE_COLORS.good;
  if (percent >= 40) return COVERAGE_COLORS.fair;
  if (percent >= 20) return COVERAGE_COLORS.poor;
  return COVERAGE_COLORS.critical;
}
