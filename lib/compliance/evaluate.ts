import type { SlaTier } from '@/components/contracts/types';
import { compareFieldToBaseline, type ComplianceStatus } from './field-comparison';
import { getTierBaseline } from './tier-baselines';

export interface FieldComplianceResult {
  fieldName: string;
  slaValue: unknown;
  contractValue: unknown | null;
  baselineValue: unknown;
  status: ComplianceStatus;
}

export interface NodeComplianceResult {
  overallStatus: 'compliant' | 'override' | 'violation' | 'unknown';
  fields: FieldComplianceResult[];
}

export function evaluateNodeCompliance(
  slaValues: Record<string, unknown>,
  contractValues: Record<string, unknown> | null,
  slaTier: SlaTier | null,
): NodeComplianceResult {
  const baseline: Record<string, unknown> = contractValues
    ? contractValues
    : slaTier
      ? (getTierBaseline(slaTier) as unknown as Record<string, unknown>)
      : {};

  const fields: FieldComplianceResult[] = [];

  // Only evaluate fields that are explicitly set in slaValues.
  // Fields absent from the SLA cannot be compared, so we skip them rather
  // than forcing them to 'unknown' and degrading the overall status.
  const evaluableFields = Object.keys(slaValues).filter(k => k in baseline);

  for (const fieldName of evaluableFields) {
    const baselineValue = baseline[fieldName];
    if (baselineValue == null) continue;
    const slaValue = slaValues[fieldName] ?? null;
    const status = compareFieldToBaseline(fieldName, slaValue, baselineValue);

    fields.push({
      fieldName,
      slaValue,
      contractValue: contractValues?.[fieldName] ?? null,
      baselineValue,
      status,
    });
  }

  let overallStatus: string = 'compliant';
  for (const f of fields) {
    if (f.status === 'violation') { overallStatus = 'violation'; break; }
    if (f.status === 'override' && overallStatus !== 'violation') overallStatus = 'override';
    if (f.status === 'unknown' && overallStatus === 'compliant') overallStatus = 'unknown';
  }

  if (fields.length === 0) overallStatus = 'unknown';

  return { overallStatus: overallStatus as NodeComplianceResult['overallStatus'], fields };
}
