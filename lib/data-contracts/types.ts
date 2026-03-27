import { z } from 'zod';

// ─── Data SLA Scope ────────────────────────────────────────
export const DataSLAScope = z.enum(['schema', 'dbt_model_group', 'dashboard', 'exception']);
export type DataSLAScope = z.infer<typeof DataSLAScope>;

// ─── Schema Expectation ────────────────────────────────────
export const SchemaExpectationSchema = z.object({
  columnName: z.string(),
  expectedType: z.string().nullable().optional(),
  notNull: z.boolean().default(false),
  unique: z.boolean().default(false),
});
export type SchemaExpectation = z.infer<typeof SchemaExpectationSchema>;

// ─── Quality Rule ──────────────────────────────────────────
export const QualityRuleSchema = z.object({
  field: z.string(),
  rule: z.enum(['not_null', 'unique', 'accepted_values', 'range', 'custom']),
  params: z.record(z.string(), z.unknown()).default({}),
});
export type QualityRule = z.infer<typeof QualityRuleSchema>;

// ─── Domain SLA Config Schemas ─────────────────────────────
// These match the PolicyProfile config shapes in types/sla.ts

const FreshnessConfigSchema = z.object({
  enabled: z.boolean().optional(),
  maxHours: z.number().min(0).optional(),
  warningHours: z.number().min(0).optional(),
}).passthrough().nullable().optional();

const SchemaConfigSchema = z.object({
  enabled: z.boolean().optional(),
  strictness: z.enum(['strict', 'warn', 'ignore']).optional(),
  allowEvolution: z.boolean().optional(),
}).passthrough().nullable().optional();

const VolumeConfigSchema = z.object({
  enabled: z.boolean().optional(),
  minRows: z.number().min(0).optional(),
  maxRows: z.number().min(0).optional(),
  growthRateThreshold: z.number().min(0).max(1).optional(),
}).passthrough().nullable().optional();

const AnomalyConfigSchema = z.object({
  enabled: z.boolean().optional(),
  sensitivity: z.number().min(0).max(1).optional(),
  lookbackDays: z.number().min(1).optional(),
}).passthrough().nullable().optional();

const QualityConfigSchema = z.object({
  enabled: z.boolean().optional(),
  maxNullRate: z.number().min(0).max(1).optional(),
  maxDuplicateRate: z.number().min(0).max(1).optional(),
}).passthrough().nullable().optional();

const IngestionConfigSchema = z.object({
  syncLagToleranceMinutes: z.number().min(0).optional(),
  failureTolerance: z.enum(['strict', 'normal', 'relaxed']).optional(),
  schemaDriftStrictness: z.enum(['strict', 'warn', 'ignore']).optional(),
}).passthrough().nullable().optional();

const BIConfigSchema = z.object({
  freshnessHours: z.number().min(0).optional(),
  contentHealthEnabled: z.boolean().optional(),
  upstreamBreakStrictness: z.enum(['strict', 'warn', 'ignore']).optional(),
  refreshFailureAlerting: z.boolean().optional(),
}).passthrough().nullable().optional();

const OrchestrationConfigSchema = z.object({
  runLatencyMinutes: z.number().min(0).optional(),
  scheduleLagMinutes: z.number().min(0).optional(),
  failureTolerance: z.enum(['strict', 'normal', 'relaxed']).optional(),
}).passthrough().nullable().optional();

const TransformConfigSchema = z.object({
  testFailureTolerance: z.enum(['strict', 'normal', 'relaxed']).optional(),
  modelFreshnessHours: z.number().min(0).optional(),
}).passthrough().nullable().optional();

// ─── Data SLA Input ────────────────────────────────────────
export const DataSLAInputSchema = z.object({
  scope: DataSLAScope,
  scopeRef: z.string().min(1),
  name: z.string().nullable().optional(),
  nodeFqns: z.array(z.string()).nullable().optional(),

  // SLA tier
  slaTier: z.enum(['T0', 'T1', 'T2', 'T3']).nullable().optional(),
  notes: z.string().nullable().optional(),

  // Domain-specific SLA config sections
  freshnessConfig: FreshnessConfigSchema,
  schemaConfig: SchemaConfigSchema,
  volumeConfig: VolumeConfigSchema,
  anomalyConfig: AnomalyConfigSchema,
  qualityConfig: QualityConfigSchema,
  ingestionConfig: IngestionConfigSchema,
  biConfig: BIConfigSchema,
  orchestrationConfig: OrchestrationConfigSchema,
  transformConfig: TransformConfigSchema,

  // Legacy fields
  expectedFreshnessMinutes: z.number().min(0).nullable().optional(),
  expectedExtractionFrequencyMinutes: z.number().min(0).nullable().optional(),
  alertPolicyJson: z.any().nullable().optional(),

  // Data-asset-specific
  schemaExpectations: z.array(SchemaExpectationSchema).nullable().optional(),
  qualityRules: z.array(QualityRuleSchema).nullable().optional(),
  overridesJson: z.record(z.string(), z.unknown()).nullable().optional(),
  isException: z.boolean().default(false),
  parentContractId: z.string().nullable().optional(),

  // Status management
  status: z.enum(['active', 'inactive', 'archived']).optional(),
  archivedAt: z.union([z.date(), z.null()]).optional(),
});
export type DataSLAInput = z.infer<typeof DataSLAInputSchema>;

// ─── Data SLA Compliance Result ────────────────────────────
export interface DataSLAFieldCompliance {
  fieldName: string;
  definedValue: unknown;
  slaValue: unknown | null;
  actualValue: unknown | null;
  status: 'compliant' | 'override' | 'violation' | 'unknown';
}

export interface DataSLAComplianceResult {
  dataSlaId: string;
  nodeId: string;
  overallStatus: 'PASS' | 'WARN' | 'FAIL';
  fields: DataSLAFieldCompliance[];
  checkedAt: string;
}
