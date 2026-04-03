/**
 * Pipeline Monitoring SLA Types
 *
 * Monitoring SLA is a SEPARATE concept from DataSLA:
 * - Monitoring SLA = lightweight operational expectations (freshness, strictness,
 *   sensitivity). Cross-domain. Used to drive monitor defaults and auto-config.
 * - DataSLA = governance/compliance artifact. Warehouse-table-specific. Has
 *   lifecycle (DRAFT/ACTIVE/VIOLATED/DEPRECATED), violation history.
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
// SLA Profile
// ---------------------------------------------------------------------------

export interface SLAProfile {
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
// SLA Assignment
// ---------------------------------------------------------------------------

export type SLAAssignmentType = 'direct' | 'branch' | 'auto_discovered' | 'domain_default' | 'criticality_default';

export interface SLAAssignment {
  id: string;
  profileId: string;
  assignmentType: SLAAssignmentType;
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
// SLA Status (for UI badges)
// ---------------------------------------------------------------------------

export type SLAStatus = 'assigned' | 'inherited' | 'override' | 'none';

// ---------------------------------------------------------------------------
// Effective SLA Policy (resolved from the chain)
// ---------------------------------------------------------------------------

export interface EffectiveSLAPolicy {
  source: string;  // direct_override | direct_profile | imported_dbt | branch | auto_discovered | criticality_default | domain_default | builtin
  profileId?: string | null;
  profileName?: string | null;
  status: SLAStatus;

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

export interface SLAAssignRequest {
  profileId: string;
  assignmentType: SLAAssignmentType;
  nodeFqns?: string[];
  branchRootFqn?: string;
  nodeDomain?: string;
  nodeCriticality?: string;
  overrides?: Record<string, any>;
}

export interface SLAResolveRequest {
  nodes: Array<{ fqn: string; domain: string; criticality: string }>;
  stackId?: string;
}

export interface SLAResolveResponse {
  policies: Record<string, EffectiveSLAPolicy>;
}

// ---------------------------------------------------------------------------
// Domain → applicable SLA controls mapping
// ---------------------------------------------------------------------------

export type SLADomain = 'warehouse' | 'ingestion' | 'bi' | 'orchestration' | 'transform';

/**
 * Maps node domains to which SLA config sections are relevant.
 * Used by SLAEditorPanel to show only applicable controls.
 */
export const DOMAIN_SLA_SECTIONS: Record<SLADomain, string[]> = {
  warehouse: ['freshness', 'schema', 'volume', 'anomaly', 'quality', 'uniqueness'],
  ingestion: ['freshness', 'ingestion'],
  bi: ['bi', 'freshness'],
  orchestration: ['orchestration'],
  transform: ['transform', 'freshness', 'schema'],
};

/**
 * Maps UnifiedNodeCategory to SLADomain.
 */
export function categoryToSLADomain(category: string): SLADomain | null {
  const mapping: Record<string, SLADomain> = {
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

