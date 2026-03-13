/**
 * Shared monitor-based health and coverage scoring utility.
 *
 * Used by:
 * - Unified lineage route (buildMonitorSummary enrichment)
 * - DataAssetDetailPanel (asset-level health & coverage)
 * - InspectorPanel / ToolDetailView (tool-level health & coverage)
 *
 * Mirrors applicability mapping from scanner/monitors/recommender.py:_recommend_direct()
 */

// ---------------------------------------------------------------------------
// Asset categories
// ---------------------------------------------------------------------------

export type AssetCategory =
  | 'warehouse'
  | 'bi'
  | 'ingestion'
  | 'orchestration'
  | 'dbt_transform'
  | 'infra';

// ---------------------------------------------------------------------------
// Applicable monitor types per asset/tool category
// ---------------------------------------------------------------------------

export const APPLICABLE_MONITORS: Record<AssetCategory, string[]> = {
  warehouse: [
    'FRESHNESS',
    'VOLUME',
    'SCHEMA_CHANGE',
    'ANOMALY',
    'UNIQUENESS',
    'NULL_RATE',
    'REFERENTIAL',
  ],
  bi: [
    'BI_FRESHNESS_PROXY',
    'BI_CONTENT_HEALTH',
    'BI_UPSTREAM_BREAK_RISK',
    'BI_REFRESH_FAILURE',
  ],
  ingestion: [
    'SYNC_LAG',
    'FAILED_SYNCS',
    'CONNECTOR_SCHEMA_DRIFT',
  ],
  orchestration: [
    'DAG_LAST_RUN',
    'DAG_SCHEDULE_LAG',
    'TASK_FAILURE_RATE',
  ],
  dbt_transform: [
    'DBT_TEST_FAILURES',
    'DBT_MODEL_FRESHNESS',
    'DBT_SOURCE_FRESHNESS',
  ],
  infra: [
    'SERVER_HEALTH',
    'CERTIFICATE',
    'LOG_ANALYSIS',
  ],
};

/** Warehouse coverage uses an 80 % threshold for "good"; others require 100 %. */
const WAREHOUSE_GOOD_THRESHOLD = 80;

// ---------------------------------------------------------------------------
// Category resolver
// ---------------------------------------------------------------------------

/**
 * Resolve an asset/tool category from node metadata.
 *
 * @param layer       PipelineLayer string (INGESTION, TRANSFORMATION, WAREHOUSE, REPORTING, …)
 * @param platformDomain  Optional platform domain (warehouse, ingestion, orchestration, transform, bi, …)
 * @param platform    Optional platform slug (bigquery, dbt_cloud, airflow, tableau, …)
 */
export function resolveAssetCategory(
  layer?: string,
  platformDomain?: string,
  platform?: string,
): AssetCategory | null {
  const l = (layer || '').toUpperCase();
  const pd = (platformDomain || '').toLowerCase();
  const p = (platform || '').toLowerCase();

  // Platform-domain first (most precise)
  if (pd === 'bi' || pd === 'reporting') return 'bi';
  if (pd === 'ingestion') return 'ingestion';
  if (pd === 'orchestration') return 'orchestration';
  if (pd === 'transform' || pd === 'transformation') {
    // dbt-specific platforms → dbt_transform
    if (['dbt_cloud', 'dbt_core', 'dbt'].includes(p)) return 'dbt_transform';
    return 'dbt_transform'; // transformation domain is dbt-centric in this codebase
  }
  if (pd === 'warehouse') return 'warehouse';
  if (pd === 'infrastructure' || pd === 'infra') return 'infra';

  // Fallback to pipeline layer
  if (l === 'REPORTING') return 'bi';
  if (l === 'INGESTION') return 'ingestion';
  if (l === 'ORCHESTRATION') return 'orchestration';
  if (l === 'TRANSFORMATION') return 'dbt_transform';
  if (l === 'WAREHOUSE') return 'warehouse';
  if (l === 'INFRASTRUCTURE') return 'infra';

  return null;
}

// ---------------------------------------------------------------------------
// Status → score mapping
// ---------------------------------------------------------------------------

const STATUS_SCORE: Record<string, number | null> = {
  PASS: 100,
  WARN: 50,
  FAIL: 0,
  ERROR: 0,
  // Excluded from scoring
  SKIPPED: null,
  RUNNING: null,
};

// ---------------------------------------------------------------------------
// Health scoring
// ---------------------------------------------------------------------------

export type HealthStatus = 'healthy' | 'degraded' | 'at_risk' | 'unhealthy' | 'unmonitored';

export interface HealthResult {
  healthScore: number | null; // 0-100 or null if no stable signals
  healthStatus: HealthStatus;
}

/**
 * Compute health score from the latest status of each configured monitor.
 * Simple average: PASS = 100, WARN = 50, FAIL / ERROR = 0.
 * SKIPPED, RUNNING, and null statuses are excluded from the denominator.
 */
export function computeMonitorHealth(
  monitors: Array<{ lastStatus: string | null }>,
): HealthResult {
  if (monitors.length === 0) {
    return { healthScore: null, healthStatus: 'unmonitored' };
  }

  let sum = 0;
  let count = 0;

  for (const m of monitors) {
    const s = m.lastStatus?.toUpperCase() ?? '';
    const score = STATUS_SCORE[s];
    if (score !== null && score !== undefined) {
      sum += score;
      count += 1;
    }
  }

  if (count === 0) {
    return { healthScore: null, healthStatus: 'unmonitored' };
  }

  const healthScore = Math.round((sum / count) * 10) / 10; // one decimal
  return { healthScore, healthStatus: healthStatusFromScore(healthScore) };
}

export function healthStatusFromScore(score: number): HealthStatus {
  if (score >= 90) return 'healthy';
  if (score >= 70) return 'degraded';
  if (score >= 40) return 'at_risk';
  return 'unhealthy';
}

// ---------------------------------------------------------------------------
// Coverage scoring
// ---------------------------------------------------------------------------

export type CoverageStatus = 'good' | 'partial' | 'none';

export interface CoverageResult {
  coveragePct: number;           // 0-100
  coverageStatus: CoverageStatus;
  configured: number;            // count of configured applicable types
  available: number;             // count of total applicable types
  missingTypes: string[];        // applicable types not yet configured
}

/**
 * Compute monitor coverage for an asset or tool category.
 *
 * @param configuredTypes   Unique monitor type keys that are actively configured
 * @param category          The asset/tool category (determines applicable types)
 */
export function computeMonitorCoverage(
  configuredTypes: string[],
  category: AssetCategory,
): CoverageResult {
  const applicableTypes = APPLICABLE_MONITORS[category] || [];
  if (applicableTypes.length === 0) {
    return { coveragePct: 0, coverageStatus: 'none', configured: 0, available: 0, missingTypes: [] };
  }

  const configuredSet = new Set(configuredTypes.map(t => t.toUpperCase()));
  const configured = applicableTypes.filter(t => configuredSet.has(t)).length;
  const available = applicableTypes.length;
  const coveragePct = Math.round((configured / available) * 1000) / 10; // one decimal

  const missingTypes = applicableTypes.filter(t => !configuredSet.has(t));

  let coverageStatus: CoverageStatus;
  if (configured === 0) {
    coverageStatus = 'none';
  } else if (category === 'warehouse') {
    coverageStatus = coveragePct >= WAREHOUSE_GOOD_THRESHOLD ? 'good' : 'partial';
  } else {
    coverageStatus = coveragePct >= 100 ? 'good' : 'partial';
  }

  return { coveragePct, coverageStatus, configured, available, missingTypes };
}

// ---------------------------------------------------------------------------
// Combined scoring
// ---------------------------------------------------------------------------

export interface MonitorScoringResult extends HealthResult, CoverageResult {}

/**
 * Compute health + coverage for an asset or tool.
 *
 * @param monitors     Array of configured monitors with lastStatus and monitorType
 * @param category     The asset/tool category
 */
export function computeMonitorScoring(
  monitors: Array<{ monitorType: string; lastStatus: string | null }>,
  category: AssetCategory,
): MonitorScoringResult {
  const health = computeMonitorHealth(monitors);
  const configuredTypes = [...new Set(monitors.map(m => m.monitorType.toUpperCase()))];
  const coverage = computeMonitorCoverage(configuredTypes, category);
  return { ...health, ...coverage };
}

/**
 * Get the list of applicable monitor types for a category.
 * Convenience re-export for callers that need just the list.
 */
export function getApplicableMonitorTypes(category: AssetCategory): string[] {
  return APPLICABLE_MONITORS[category] || [];
}
