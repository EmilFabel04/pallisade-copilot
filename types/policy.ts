/**
 * Pipeline Monitoring Policy Types
 *
 * Monitoring Policy is a SEPARATE concept from DataContract:
 * - Monitoring Policy = lightweight operational expectations (freshness, strictness,
 *   sensitivity). Cross-domain. Used to drive monitor defaults and auto-config.
 * - DataContract = governance/compliance artifact. Warehouse-table-specific. Has
 *   lifecycle (DRAFT/ACTIVE/VIOLATED/DEPRECATED), ownership, violation history.
 */

// ---------------------------------------------------------------------------
// Domain config shapes (match the Json blobs in Prisma PolicyProfile)
// ---------------------------------------------------------------------------

export interface FreshnessConfig {
  enabled?: boolean;
  maxHours?: number;
  warningHours?: number;
}

export interface SchemaConfig {
  enabled?: boolean;
  strictness?: 'strict' | 'warn' | 'ignore';
  allowEvolution?: boolean;
}

export interface VolumeConfig {
  enabled?: boolean;
  minRows?: number;
  maxRows?: number;
  growthRateThreshold?: number;
}

export interface AnomalyConfig {
  enabled?: boolean;
  sensitivity?: number;  // 0.0–1.0
  lookbackDays?: number;
}

export interface QualityConfig {
  enabled?: boolean;
  maxNullRate?: number;
  maxDuplicateRate?: number;
}

export interface IngestionConfig {
  syncLagToleranceMinutes?: number;
  failureTolerance?: 'strict' | 'normal' | 'relaxed';
  schemaDriftStrictness?: 'strict' | 'warn' | 'ignore';
}

export interface BIConfig {
  freshnessHours?: number;
  contentHealthEnabled?: boolean;
  upstreamBreakStrictness?: 'strict' | 'warn' | 'ignore';
  refreshFailureAlerting?: boolean;
}

export interface OrchestrationConfig {
  runLatencyMinutes?: number;
  scheduleLagMinutes?: number;
  failureTolerance?: 'strict' | 'normal' | 'relaxed';
}

export interface TransformConfig {
  testFailureTolerance?: 'strict' | 'normal' | 'relaxed';
  modelFreshnessHours?: number;
}

// ---------------------------------------------------------------------------
// Policy Profile
// ---------------------------------------------------------------------------

export interface PolicyProfile {
  id: string;
  name: string;
  description?: string | null;
  isBuiltIn: boolean;
  targetDomain?: string | null;  // "warehouse"|"ingestion"|"bi"|"orchestration"|"transform"|null
  criticality?: string | null;   // Maps to Criticality enum

  freshnessConfig?: FreshnessConfig | null;
  schemaConfig?: SchemaConfig | null;
  volumeConfig?: VolumeConfig | null;
  anomalyConfig?: AnomalyConfig | null;
  qualityConfig?: QualityConfig | null;
  ingestionConfig?: IngestionConfig | null;
  biConfig?: BIConfig | null;
  orchestrationConfig?: OrchestrationConfig | null;
  transformConfig?: TransformConfig | null;

  createdAt?: string;
  updatedAt?: string;
}

// ---------------------------------------------------------------------------
// Policy Assignment
// ---------------------------------------------------------------------------

export type PolicyAssignmentType = 'direct' | 'branch' | 'domain_default' | 'criticality_default';

export interface PolicyAssignment {
  id: string;
  profileId: string;
  assignmentType: PolicyAssignmentType;
  nodeFqn?: string | null;
  nodeDomain?: string | null;
  nodeCriticality?: string | null;
  branchRootFqn?: string | null;
  overrides?: Record<string, any> | null;
  organizationId: string;
  createdAt?: string;
  updatedAt?: string;
}

// ---------------------------------------------------------------------------
// Policy Status (for UI badges)
// ---------------------------------------------------------------------------

export type PolicyStatus = 'assigned' | 'inherited' | 'override' | 'none';

// ---------------------------------------------------------------------------
// Effective Policy (resolved from the chain)
// ---------------------------------------------------------------------------

export interface EffectivePolicy {
  source: string;  // data_contract | direct_override | direct_profile | branch | criticality_default | domain_default | builtin
  profileId?: string | null;
  profileName?: string | null;
  status: PolicyStatus;

  freshness: FreshnessConfig;
  schema: SchemaConfig;
  volume: VolumeConfig;
  anomaly: AnomalyConfig;
  quality: QualityConfig;
  ingestion: IngestionConfig;
  bi: BIConfig;
  orchestration: OrchestrationConfig;
  transform: TransformConfig;
}

// ---------------------------------------------------------------------------
// API request/response types
// ---------------------------------------------------------------------------

export interface PolicyAssignRequest {
  profileId: string;
  assignmentType: PolicyAssignmentType;
  nodeFqns?: string[];
  branchRootFqn?: string;
  nodeDomain?: string;
  nodeCriticality?: string;
  overrides?: Record<string, any>;
}

export interface PolicyResolveRequest {
  nodes: Array<{ fqn: string; domain: string; criticality: string }>;
  stackId?: string;
}

export interface PolicyResolveResponse {
  policies: Record<string, EffectivePolicy>;
}

// ---------------------------------------------------------------------------
// Domain → applicable policy controls mapping
// ---------------------------------------------------------------------------

export type PolicyDomain = 'warehouse' | 'ingestion' | 'bi' | 'orchestration' | 'transform';

/**
 * Maps node domains to which policy config sections are relevant.
 * Used by PolicyEditorPanel to show only applicable controls.
 */
export const DOMAIN_POLICY_SECTIONS: Record<PolicyDomain, string[]> = {
  warehouse: ['freshness', 'schema', 'volume', 'anomaly', 'quality'],
  ingestion: ['freshness', 'ingestion'],
  bi: ['bi', 'freshness'],
  orchestration: ['orchestration'],
  transform: ['transform', 'freshness', 'schema'],
};

/**
 * Maps UnifiedNodeCategory to PolicyDomain.
 */
export function categoryToPolicyDomain(category: string): PolicyDomain | null {
  const mapping: Record<string, PolicyDomain> = {
    // Warehouse / data assets
    table: 'warehouse',
    view: 'warehouse',
    model: 'warehouse',  // dbt models land in warehouse
    dataset: 'warehouse',
    warehouse: 'warehouse',  // platform tool node
    notebook: 'warehouse',   // Databricks notebook → warehouse-like
    // Ingestion
    source: 'ingestion',
    connector: 'ingestion',
    ingestion: 'ingestion',
    // BI / Reporting
    dashboard: 'bi',
    report: 'bi',
    workbook: 'bi',
    question: 'bi',
    reporting: 'bi',
    // Orchestration
    dag: 'orchestration',
    task: 'orchestration',
    workflow: 'orchestration',
    orchestration: 'orchestration',
    // Transform
    transformation: 'transform',
    test: 'transform',  // dbt/elementary tests → transform domain
  };
  return mapping[category] ?? null;
}

/**
 * Criticality → default built-in profile mapping.
 */
export const CRITICALITY_PROFILE_MAP: Record<string, string> = {
  critical: 'Critical SLA',
  high: 'Critical SLA',
  medium: 'Standard',
  low: 'Relaxed',
};
