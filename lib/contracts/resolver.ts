import {
  NodeSLAWithOverrides,
  EffectiveSLA,
  PipelineSLAData,
  validateOverrides,
} from '@/components/contracts/types';

/**
 * Resolve the effective SLA for a source integration.
 *
 * Pipeline contracts and data contracts are separate concepts:
 * - Pipeline contract = governance agreement on the pipeline as a whole
 * - Source SLA = derived from SLA assignments on child data assets
 *
 * Sources only have SLA data when explicitly set via SourceContract
 * (created by auto-sync from SLA assignments in lineage).
 * There is NO inheritance from pipeline contract to source SLA.
 */
export function resolveEffectiveSLA(
  _pipelineSLA: PipelineSLAData | null,
  nodeSLA: NodeSLAWithOverrides | null,
  integrationType: string
): EffectiveSLA {
  // No source SLA → empty (no pipeline inheritance)
  if (!nodeSLA) {
    return {
      slaTier: null,
      expectedFreshnessMinutes: null,
      expectedExtractionFrequencyMinutes: null,
      toolOverrides: {},
      inheritanceState: null,
    };
  }

  // Source has its own SLA data (set via auto-sync from lineage assignments)
  const overrides = resolveToolOverrides(nodeSLA.overridesJson, integrationType);
  return {
    slaTier: nodeSLA.slaTier ?? null,
    expectedFreshnessMinutes: nodeSLA.expectedFreshnessMinutes ?? null,
    expectedExtractionFrequencyMinutes: nodeSLA.expectedExtractionFrequencyMinutes ?? null,
    toolOverrides: overrides,
    inheritanceState: null,
  };
}

/**
 * Validate and return tool-specific overrides. Returns empty object if invalid or null.
 */
function resolveToolOverrides(
  overridesJson: Record<string, any> | null | undefined,
  integrationType: string
): Record<string, any> {
  if (!overridesJson || Object.keys(overridesJson).length === 0) {
    return {};
  }
  const result = validateOverrides(integrationType, overridesJson);
  return result.success ? result.data : {};
}
