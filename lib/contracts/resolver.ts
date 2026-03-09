import {
  PipelineContractData,
  SourceContractWithOverrides,
  EffectiveContract,
  InheritanceState,
  SlaTier,
  validateOverrides,
} from '@/components/contracts/types';

/**
 * Core contract fields that can be inherited from pipeline → source.
 */
const INHERITABLE_FIELDS = [
  'ownerUser',
  'ownerTeam',
  'contactChannel',
  'slaTier',
  'expectedFreshnessMinutes',
  'expectedExtractionFrequencyMinutes',
] as const;

/**
 * Resolve the effective contract for an integration by merging pipeline defaults
 * with source-level overrides according to inheritance rules.
 *
 * Precedence:
 *   1. If no source contract → pipeline defaults (INHERITED)
 *   2. If inheritFromPipeline=false → source-only (FULL_OVERRIDE)
 *   3. If inheritFromPipeline=true → source fields override pipeline where non-null (PARTIAL_OVERRIDE or INHERITED)
 */
export function resolveEffectiveContract(
  pipelineContract: PipelineContractData | null,
  sourceContract: SourceContractWithOverrides | null,
  integrationType: string
): EffectiveContract {
  // No source contract at all → pure pipeline defaults
  if (!sourceContract) {
    return {
      ownerUser: pipelineContract?.ownerUser ?? null,
      ownerTeam: pipelineContract?.ownerTeam ?? null,
      contactChannel: pipelineContract?.contactChannel ?? null,
      slaTier: pipelineContract?.slaTier ?? null,
      expectedFreshnessMinutes: pipelineContract?.expectedFreshnessMinutes ?? null,
      expectedExtractionFrequencyMinutes: pipelineContract?.expectedExtractionFrequencyMinutes ?? null,
      toolOverrides: {},
      inheritanceState: 'INHERITED',
    };
  }

  // Source exists but not inheriting → standalone
  if (!sourceContract.inheritFromPipeline) {
    const overrides = resolveToolOverrides(sourceContract.overridesJson, integrationType);
    return {
      ownerUser: sourceContract.ownerUser,
      ownerTeam: sourceContract.ownerTeam,
      contactChannel: sourceContract.contactChannel,
      slaTier: sourceContract.slaTier,
      expectedFreshnessMinutes: sourceContract.expectedFreshnessMinutes,
      expectedExtractionFrequencyMinutes: sourceContract.expectedExtractionFrequencyMinutes,
      toolOverrides: overrides,
      inheritanceState: 'FULL_OVERRIDE',
    };
  }

  // Inheriting: merge source over pipeline
  const merged: Record<string, any> = {};
  let hasSourceOverride = false;

  for (const field of INHERITABLE_FIELDS) {
    const sourceVal = sourceContract[field];
    const pipelineVal = pipelineContract?.[field] ?? null;

    if (sourceVal !== null && sourceVal !== undefined) {
      merged[field] = sourceVal;
      hasSourceOverride = true;
    } else {
      merged[field] = pipelineVal;
    }
  }

  const overrides = resolveToolOverrides(sourceContract.overridesJson, integrationType);
  if (Object.keys(overrides).length > 0) {
    hasSourceOverride = true;
  }

  const inheritanceState: InheritanceState = hasSourceOverride ? 'PARTIAL_OVERRIDE' : 'INHERITED';

  return {
    ownerUser: merged.ownerUser as string | null,
    ownerTeam: merged.ownerTeam as string | null,
    contactChannel: merged.contactChannel as string | null,
    slaTier: merged.slaTier as SlaTier | null,
    expectedFreshnessMinutes: merged.expectedFreshnessMinutes as number | null,
    expectedExtractionFrequencyMinutes: merged.expectedExtractionFrequencyMinutes as number | null,
    toolOverrides: overrides,
    inheritanceState,
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
