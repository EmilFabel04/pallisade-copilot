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
  | 'data_drift'        // Detect schema/quality drift
  | 'full_pipeline'     // Full pipeline coverage (data + tools)
  | 'tool_health'       // Holistic tool health
  | 'custom_watch';     // User-assembled

export const WATCH_TYPE_LABELS: Record<WatchType, string> = {
  pipeline_health: 'Data Pipeline',
  dashboard_shield: 'Dashboard',
  source_guard: 'Ingestion Source',
  model_quality: 'Transformation',
  data_drift: 'Data Drift',
  full_pipeline: 'Full Pipeline',
  tool_health: 'Tool Health',
  custom_watch: 'Custom',
};

export const WATCH_TYPE_DESCRIPTIONS: Record<WatchType, string> = {
  pipeline_health: 'Monitor a warehouse table and its upstream dependencies for freshness, volume, and schema changes.',
  dashboard_shield: 'End-to-end monitoring for a BI dashboard, tracking upstream data health through to the reporting layer.',
  source_guard: 'Monitor an ingestion connector and its downstream destination tables.',
  model_quality: 'Monitor a dbt model with test failures, freshness, and upstream source checks.',
  data_drift: 'Detect schema changes, volume anomalies, and quality drift across pipeline assets.',
  full_pipeline: 'Unified monitoring across your entire pipeline — data, orchestration, and BI.',
  tool_health: 'Holistic health monitoring for a pipeline tool — checks all relevant categories with configurable thresholds.',
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
  data_drift: {
    maxDepth: 3,
    maxNodes: 12,
    maxMonitors: 10,
    domainFilters: ['warehouse', 'transform', 'ingestion'],
  },
  full_pipeline: {
    maxDepth: 5,
    maxNodes: 30,
    maxMonitors: 40,
    domainFilters: [],
  },
  tool_health: {
    maxDepth: 0,
    maxNodes: 1,
    maxMonitors: 12,
    domainFilters: [],
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
  // True once at least one constituent monitor has produced a run. When false,
  // healthScore/healthStatus are derived from defaults (or a stale persisted
  // value) and SHOULD NOT be surfaced as a real health badge — render "NEW"
  // or "No runs yet" instead.
  hasRun: boolean;
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

// ---------------------------------------------------------------------------
// Preset Types
// ---------------------------------------------------------------------------

export type PresetKey =
  | 'pipeline_health'
  | 'data_drift'
  | 'ingestion_watch'
  | 'bi_reliability'
  | 'full_coverage';

export interface PresetDefinition {
  key: PresetKey;
  label: string;
  description: string;
  eligible: boolean;
  eligibleDomains: string[];
  estimatedWatches: string;
  estimatedMonitors: string;
}

export interface PresetPreviewResult {
  presetKey: string;
  watches: PresetWatchPreview[];
  totalMonitors: number;
  totalNodes: number;
  deduplicatedCount: number;
  warnings: string[];
}

export interface PresetWatchPreview {
  watchType: WatchType;
  anchorNodeId: string;
  anchorName: string;
  anchorFqn: string;
  anchorNodeType: string;
  anchorPlatform: string;
  scopeResult: {
    anchor_id: string;
    anchor_name: string;
    watch_type: string;
    nodes: Array<{ node_id: string; depth: number; score: number }>;
    recommendations: Array<{
      monitor_key: string;
      target_fqn: string;
      target_node_id: string;
      source: string;
      reason: string;
      priority: number;
      config_hints: Record<string, any>;
      integration_type: string;
      already_monitored: boolean;
    }>;
    total_upstream_count: number;
    scoped_node_count: number;
    coverage_pct: number;
  };
  monitorCount: number;
  coveragePct: number;
}

export const PRESET_LABELS: Record<PresetKey, string> = {
  pipeline_health: 'Pipeline Health',
  data_drift: 'Data Drift',
  ingestion_watch: 'Ingestion Watch',
  bi_reliability: 'BI Reliability',
  full_coverage: 'Full Coverage',
};

export const PRESET_DESCRIPTIONS: Record<PresetKey, string> = {
  pipeline_health: 'Protect a warehouse table and its upstream pipeline.',
  data_drift: 'Detect schema and quality changes across pipeline assets.',
  ingestion_watch: 'Protect ingestion connectors feeding your data.',
  bi_reliability: 'End-to-end protection for dashboards and their data path.',
  full_coverage: 'Maximum coverage across your entire pipeline.',
};

// ---------------------------------------------------------------------------
// Monitor Families (canonical — maps to scanner/monitors/families.py)
// ---------------------------------------------------------------------------

export type MonitorFamilyKey =
  | 'pipeline_health'
  | 'data_drift'
  | 'ingestion_reliability'
  | 'bi_reliability'
  | 'model_quality'
  | 'full_coverage';

export interface MonitorFamilyDefinition {
  key: MonitorFamilyKey;
  label: string;
  description: string;
  eligible_domains: string[];
  eligible_asset_kinds: string[];
  watch_type: WatchType;
  is_meta: boolean;
  estimated_monitors: string;
}

export interface FamilyEligibility extends MonitorFamilyDefinition {
  eligible: boolean;
  matching_node_count: number;
  reason: string;
}

// ---------------------------------------------------------------------------
// Monitoring Plan Types
// ---------------------------------------------------------------------------

export type MonitoringPlanMode = 'recommended' | 'manual';
export type PlanScopeType = 'pipeline' | 'stream' | 'asset' | 'tool' | 'custom';

export interface PlanScopeConfig {
  anchorNodeIds?: string[];
  maxDepth?: number;
  toolType?: string;
  platform?: string;
  nodeIds?: string[];  // For custom scope — explicit user-selected node IDs
}

export interface GroupPreview {
  group_index: number;
  family: string;
  watch_type: string;
  anchor_id: string;
  anchor_name: string;
  anchor_fqn: string;
  anchor_node_type: string;
  anchor_platform: string;
  node_count: number;
  monitor_count: number;
  coverage_pct: number;
  shared_node_ids: string[];
  recommendations: Array<{
    monitor_key: string;
    target_fqn: string;
    target_node_id: string;
    source: string;
    reason: string;
    priority: number;
    config_hints: Record<string, any>;
    integration_type: string;
    already_monitored: boolean;
  }>;
}

export interface MonitoringPlanPreview {
  scope_type: PlanScopeType;
  mode: MonitoringPlanMode;
  families: string[];
  groups: GroupPreview[];
  total_nodes: number;
  total_monitors: number;
  raw_monitor_count: number;
  dedup_count: number;
  coverage_pct: number;
  warnings: string[];
  family_eligibility: FamilyEligibility[];
}

export interface MonitoringPlanSummary {
  id: string;
  name: string;
  description?: string;
  scopeType: PlanScopeType;
  scopeConfig?: PlanScopeConfig;
  anchorFqn?: string;
  anchorNodeId?: string;
  mode: MonitoringPlanMode;
  families: string[];
  totalAssets: number;
  totalMonitors: number;
  coveragePct?: number;
  healthScore?: number;
  healthStatus?: HealthStatus;
  passCount: number;
  warnCount: number;
  failCount: number;
  errorCount: number;
  lastAggregatedAt?: string;
  schedule?: string;
  timezone?: string;
  enabled: boolean;
  alertChannels: string[];
  alertOnStatus: string[];
  createdBy?: string;
  createdAt: string;
  updatedAt: string;
  monitorGroups: WatchSummary[];
}

export interface PlanAggregate {
  healthScore: number;
  healthStatus: HealthStatus;
  coveragePct: number;
  totalMonitors: number;
  passCount: number;
  warnCount: number;
  failCount: number;
  errorCount: number;
  lowestHealthGroup?: string;
  topFailureGroups: FailureGroup[];
}

// ---------------------------------------------------------------------------
// Watch Summary
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
  presetGroupId?: string;
  presetKey?: string;
  alertChannels?: string[];
  alertOnStatus?: string[];
  monitors: Array<{
    id: string;
    name: string;
    monitorType?: string;
    targetFqn?: string;
    enabled: boolean;
    lastStatus?: string;
    lastRunAt?: string;
    schedule?: string;
    config?: Record<string, any>;
  }>;
  createdAt: string;
}
