/**
 * Pallisade feature flags. Read from env at module load; default false.
 * Frontend code reads via NEXT_PUBLIC_FF_* (build-time exposure).
 */
export const FEATURE_FLAGS = {
  ff_artefacts_v2: process.env.NEXT_PUBLIC_FF_ARTEFACTS_V2 === 'true',
} as const;

export type FeatureFlag = keyof typeof FEATURE_FLAGS;

export function isFeatureEnabled(flag: FeatureFlag): boolean {
  return FEATURE_FLAGS[flag] === true;
}
