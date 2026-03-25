import { z } from 'zod';

// ─── Contract Scope ────────────────────────────────────────
export const ContractScope = z.enum(['schema', 'dbt_model_group', 'dashboard', 'exception']);
export type ContractScope = z.infer<typeof ContractScope>;

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

// ─── Data Contract Input ───────────────────────────────────
export const DataContractInputSchema = z.object({
  scope: ContractScope,
  scopeRef: z.string().min(1),
  ownerUser: z.string().nullable().optional(),
  ownerTeam: z.string().nullable().optional(),
  contactChannel: z.string().nullable().optional(),
  slaTier: z.enum(['T0', 'T1', 'T2', 'T3']).nullable().optional(),
  expectedFreshnessMinutes: z.number().min(0).nullable().optional(),
  expectedExtractionFrequencyMinutes: z.number().min(0).nullable().optional(),
  alertPolicyJson: z.any().nullable().optional(),
  notes: z.string().nullable().optional(),
  schemaExpectations: z.array(SchemaExpectationSchema).nullable().optional(),
  qualityRules: z.array(QualityRuleSchema).nullable().optional(),
  overridesJson: z.record(z.string(), z.unknown()).nullable().optional(),
  isException: z.boolean().default(false),
  parentContractId: z.string().nullable().optional(),
});
export type DataContractInput = z.infer<typeof DataContractInputSchema>;

// ─── Contract Compliance Result ────────────────────────────
export interface ContractFieldCompliance {
  fieldName: string;
  contractValue: unknown;
  slaValue: unknown | null;
  actualValue: unknown | null;
  status: 'compliant' | 'override' | 'violation' | 'unknown';
}

export interface ContractComplianceResult {
  contractId: string;
  nodeId: string;
  overallStatus: 'PASS' | 'WARN' | 'FAIL';
  fields: ContractFieldCompliance[];
  checkedAt: string;
}
