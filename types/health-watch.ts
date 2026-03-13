/**
 * Group Monitor Types — asset-centric protection model.
 *
 * A Group Monitor wraps a MonitorGroup with watch-specific semantics:
 * scope selection, weighted health aggregation, and failure grouping.
 */

// ---------------------------------------------------------------------------
// Watch Types
// ---------------------------------------------------------------------------

export type WatchType =
  | 'pipeline_health'   // Protect a warehouse table + upstream
  | 'dashboard_shield'  // Protect a BI asset end-to-end
  | 'source_guard'      // Protect an ingestion source
  | 'model_quality'     // Protect a dbt model
  | 'custom_watch';     // User-assembled

export const WATCH_TYPE_LABELS: Record<WatchType, string> = {
  pipeline_health: 'Data Pipeline',
  dashboard_shield: 'Dashboard',
  source_guard: 'Ingestion Source',
  model_quality: 'Transformation',
  custom_watch: 'Custom',
};

export const WATCH_TYPE_DESCRIPTIONS: Record<WatchType, string> = {
  pipeline_health: 'Monitor a warehouse table and its upstream dependencies for freshness, volume, and schema changes.',
  dashboard_shield: 'End-to-end monitoring for a BI dashboard, tracking upstream data health through to the reporting layer.',
  source_guard: 'Monitor an ingestion connector and its downstream destination tables.',
  model_quality: 'Monitor a dbt model with test failures, freshness, and upstream source checks.',
  custom_watch: 'Custom monitoring group — you choose the monitors.',
};

// ---------------------------------------------------------------------------
// Scope Configuration
// ---------------------------------------------------------------------------

export interface ScopeConfig {
  maxDepth: number;
  maxNodes: number;
  maxMonitors: number;
  domainFilters: string[];     // PlatformDomain values to include
  includeNodeIds?: string[];   // Always include these nodes
  excludeNodeIds?: string[];   // Always exclude these nodes
}

export const DEFAULT_SCOPE_CONFIGS: Record<WatchType, ScopeConfig> = {
  pipeline_health: {
    maxDepth: 3,
    maxNodes: 15,
    maxMonitors: 12,
    domainFilters: ['warehouse', 'ingestion', 'orchestration', 'transform'],
  },
  dashboard_shield: {
    maxDepth: 4,
    maxNodes: 20,
    maxMonitors: 15,
    domainFilters: ['warehouse', 'ingestion', 'transform', 'orchestration'],
  },
  source_guard: {
    maxDepth: 1,
    maxNodes: 5,
    maxMonitors: 6,
    domainFilters: ['ingestion', 'warehouse'],
  },
  model_quality: {
    maxDepth: 2,
    maxNodes: 10,
    maxMonitors: 10,
    domainFilters: ['transform', 'warehouse', 'ingestion'],
  },
  custom_watch: {
    maxDepth: 2,
    maxNodes: 10,
    maxMonitors: 8,
    domainFilters: [],
  },
};

// ---------------------------------------------------------------------------
// Health Report
// ---------------------------------------------------------------------------

export type HealthStatus = 'healthy' | 'degraded' | 'at_risk' | 'unhealthy';

export interface HealthReport {
  healthScore: number;         // 0-100
  healthStatus: HealthStatus;
  summary: string;             // e.g. "Executive Revenue is at risk: 2 stale upstream tables"
  directStatus: string;        // "pass"|"fail"|"none"
  upstreamStatus: string;      // "pass"|"fail"|"mixed"|"none"
  coveragePct: number;         // 0.0-1.0
  failureGroups: FailureGroup[];
  computedAt: string;          // ISO timestamp
}

export type FailureCategory =
  | 'stale_data'
  | 'schema_break'
  | 'ingestion_lag'
  | 'orchestration_failure'
  | 'quality_anomaly'
  | 'transform_failure';

export const FAILURE_CATEGORY_LABELS: Record<FailureCategory, string> = {
  stale_data: 'Stale Data',
  schema_break: 'Schema Break',
  ingestion_lag: 'Ingestion Lag',
  orchestration_failure: 'Orchestration Failure',
  quality_anomaly: 'Quality Anomaly',
  transform_failure: 'Transform Failure',
};

export interface FailureGroup {
  category: FailureCategory;
  severity: 'critical' | 'warning';
  summary: string;
  rootCauseHint: string;
  signalCount: number;
}

// ---------------------------------------------------------------------------
// Health status helpers
// ---------------------------------------------------------------------------

export function healthStatusFromScore(score: number): HealthStatus {
  if (score >= 90) return 'healthy';
  if (score >= 70) return 'degraded';
  if (score >= 40) return 'at_risk';
  return 'unhealthy';
}

export const HEALTH_STATUS_COLORS: Record<HealthStatus, string> = {
  healthy: 'bg-emerald-500/20 text-emerald-400',
  degraded: 'bg-amber-500/20 text-amber-400',
  at_risk: 'bg-orange-500/20 text-orange-400',
  unhealthy: 'bg-red-500/20 text-red-400',
};

export const HEALTH_STATUS_LABELS: Record<HealthStatus, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  at_risk: 'At Risk',
  unhealthy: 'Unhealthy',
};

// ---------------------------------------------------------------------------
// Watch summary (API response shape)
// ---------------------------------------------------------------------------

export interface WatchSummary {
  id: string;
  name: string;
  description?: string;
  watchType: WatchType;
  anchorFqn?: string;
  anchorNodeId?: string;
  anchorNodeType?: string;
  anchorPlatform?: string;
  scopeConfig?: ScopeConfig;
  enabled: boolean;
  schedule?: string;
  timezone?: string;
  monitorCount: number;
  passCount: number;
  failCount: number;
  warnCount: number;
  healthScore?: number;
  healthStatus?: HealthStatus;
  healthDetails?: HealthReport;
  coveragePct?: number;
  lastStatus?: string;
  lastRunAt?: string;
  lastHealthAt?: string;
  monitors: Array<{
    id: string;
    name: string;
    monitorType?: string;
    targetFqn?: string;
    enabled: boolean;
    lastStatus?: string;
    lastRunAt?: string;
    schedule?: string;
  }>;
  createdAt: string;
}
