import { z } from 'zod';

// ─── SLA Tier ─────────────────────────────────────────────────
export type SlaTier = 'T0' | 'T1' | 'T2' | 'T3';

// ─── Pipeline Contract ───────────────────────────────────────
export interface PipelineContractData {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  alertPolicyJson: AlertPolicy | null;
  notes: string | null;
}

export interface AlertPolicy {
  channels?: string[];           // e.g. ["slack", "email", "pagerduty"]
  severityRouting?: Record<string, string>; // e.g. { "critical": "#oncall", "warning": "#data-alerts" }
}

// ─── Inheritance ─────────────────────────────────────────────
export type InheritanceState = 'INHERITED' | 'PARTIAL_OVERRIDE' | 'FULL_OVERRIDE';

export const INHERITANCE_CONFIG: Record<InheritanceState, { label: string; color: string; bg: string }> = {
  INHERITED:        { label: 'Inherited',  color: 'text-blue-400',  bg: 'bg-blue-500/15' },
  PARTIAL_OVERRIDE: { label: 'Overridden', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  FULL_OVERRIDE:    { label: 'Standalone', color: 'text-zinc-400',  bg: 'bg-zinc-500/15' },
};

// ─── Source Contract (extended) ──────────────────────────────
export interface SourceContractWithOverrides {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  notes: string | null;
  inheritFromPipeline: boolean;
  pipelineStackId: string | null;
  overridesJson: Record<string, any> | null;
}

// ─── Effective Contract (resolved) ──────────────────────────
export interface EffectiveContract {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  toolOverrides: Record<string, any>;
  inheritanceState: InheritanceState;
}

// ─── Override Key (layer-based) ──────────────────────────────
export type OverrideKey =
  | 'warehouse'
  | 'ingestion'
  | 'orchestration'
  | 'transformation'
  | 'reporting'
  | 'storage'
  | 'observability';

// Map integration types (from Prisma enum) → override schema key
export const INTEGRATION_TYPE_TO_OVERRIDE_KEY: Record<string, OverrideKey> = {
  // Warehouse
  SNOWFLAKE: 'warehouse',
  BIGQUERY: 'warehouse',
  POSTGRES: 'warehouse',
  REDSHIFT: 'warehouse',
  SQLSERVER: 'warehouse',
  AZURE_SQL: 'warehouse',
  AZURE_SYNAPSE: 'warehouse',
  DATABRICKS: 'warehouse',
  // Ingestion
  FIVETRAN: 'ingestion',
  AIRBYTE: 'ingestion',
  STITCH: 'ingestion',
  // Transformation
  DBT_CLOUD: 'transformation',
  DBT_CORE: 'transformation',
  // Orchestration
  AIRFLOW: 'orchestration',
  DAGSTER: 'orchestration',
  PREFECT: 'orchestration',
  N8N: 'orchestration',
  // Reporting
  TABLEAU: 'reporting',
  LOOKER: 'reporting',
  POWERBI: 'reporting',
  METABASE: 'reporting',
  // Observability
  ELEMENTARY: 'observability',
  MONTE_CARLO: 'observability',
  BIGEYE: 'observability',
  SODA: 'observability',
  // Storage
  AMAZON_S3: 'storage',
  GCS: 'storage',
  ADLS: 'storage',
};

// ─── Tool-Specific Override Schemas ──────────────────────────

// Warehouse (BigQuery, Snowflake, Postgres, etc.)
export const WarehouseOverridesSchema = z.object({
  maxQueryCostUsd: z.number().min(0).optional(),
  requireDryRun: z.boolean().optional(),
  defaultDataset: z.string().optional(),
  readOnlyEnforced: z.boolean().optional(),
}).strict();
export type WarehouseContractOverrides = z.infer<typeof WarehouseOverridesSchema>;

// Ingestion (Fivetran, Airbyte, Stitch)
export const IngestionOverridesSchema = z.object({
  maxSyncDelayMinutes: z.number().min(0).optional(),
  connectorPriority: z.enum(['low', 'medium', 'high']).optional(),
  schemaChangePolicy: z.enum(['ignore', 'warn', 'fail']).optional(),
}).strict();
export type IngestionContractOverrides = z.infer<typeof IngestionOverridesSchema>;

// Orchestration (Airflow, Dagster, Prefect, n8n)
export const OrchestrationOverridesSchema = z.object({
  maxRetries: z.number().int().min(0).optional(),
  retryBackoffMinutes: z.number().min(0).optional(),
  oncallRequired: z.boolean().optional(),
}).strict();
export type OrchestrationContractOverrides = z.infer<typeof OrchestrationOverridesSchema>;

// Transformation (dbt Cloud, dbt Core)
export const TransformationOverridesSchema = z.object({
  expectedRunCadenceMinutes: z.number().min(0).optional(),
  requiredTests: z.array(z.enum(['not_null', 'unique', 'relationships', 'accepted_values', 'freshness'])).optional(),
  freshnessTestsRequired: z.boolean().optional(),
}).strict();
export type TransformationContractOverrides = z.infer<typeof TransformationOverridesSchema>;

// Reporting (Tableau, Looker, PowerBI, Metabase)
export const ReportingOverridesSchema = z.object({
  refreshSlaMinutes: z.number().min(0).optional(),
  ownerAckRequired: z.boolean().optional(),
}).strict();
export type ReportingContractOverrides = z.infer<typeof ReportingOverridesSchema>;

// Storage (S3, GCS, ADLS)
export const StorageOverridesSchema = z.object({
  retentionDays: z.number().int().min(0).optional(),
  encryptionRequired: z.boolean().optional(),
}).strict();
export type StorageContractOverrides = z.infer<typeof StorageOverridesSchema>;

// Observability (Elementary, Monte Carlo, Bigeye, Soda)
export const ObservabilityOverridesSchema = z.object({
  incidentSeverityMapping: z.record(z.string(), z.string()).optional(),
  monitorMinimumSet: z.array(z.enum(['freshness', 'volume', 'schema', 'anomaly'])).optional(),
}).strict();
export type ObservabilityContractOverrides = z.infer<typeof ObservabilityOverridesSchema>;

// Schema registry keyed by override key
export const OVERRIDE_SCHEMAS: Record<OverrideKey, z.ZodObject<any>> = {
  warehouse: WarehouseOverridesSchema,
  ingestion: IngestionOverridesSchema,
  orchestration: OrchestrationOverridesSchema,
  transformation: TransformationOverridesSchema,
  reporting: ReportingOverridesSchema,
  storage: StorageOverridesSchema,
  observability: ObservabilityOverridesSchema,
};

/**
 * Validate overrides JSON against the correct schema for the given integration type.
 * Returns { success: true, data } or { success: false, error }.
 */
export function validateOverrides(
  integrationType: string,
  overrides: unknown
): { success: true; data: Record<string, any> } | { success: false; error: string } {
  const key = INTEGRATION_TYPE_TO_OVERRIDE_KEY[integrationType];
  if (!key) {
    return { success: false, error: `Unknown integration type: ${integrationType}` };
  }
  const schema = OVERRIDE_SCHEMAS[key];
  const result = schema.safeParse(overrides);
  if (!result.success) {
    const issues = result.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ');
    return { success: false, error: `Invalid overrides: ${issues}` };
  }
  return { success: true, data: result.data };
}

// ─── UI Helpers ──────────────────────────────────────────────

export const OVERRIDE_LABELS: Record<OverrideKey, string> = {
  warehouse: 'Warehouse',
  ingestion: 'Ingestion',
  orchestration: 'Orchestration',
  transformation: 'Transformation',
  reporting: 'Reporting',
  storage: 'Storage',
  observability: 'Observability',
};

/** Get the override key for an integration type, or null if unsupported */
export function getOverrideKey(integrationType: string): OverrideKey | null {
  return INTEGRATION_TYPE_TO_OVERRIDE_KEY[integrationType] ?? null;
}
