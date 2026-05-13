/**
 * Pallisade feature flags. ff_artefacts_v2 defaults to ON now that the
 * monitor write slice has landed. Operators can disable per-deploy via
 * NEXT_PUBLIC_FF_ARTEFACTS_V2=false.
 */
export const FEATURE_FLAGS = {
  ff_artefacts_v2: process.env.NEXT_PUBLIC_FF_ARTEFACTS_V2 !== 'false',
} as const;

export type FeatureFlag = keyof typeof FEATURE_FLAGS;

export function isFeatureEnabled(flag: FeatureFlag): boolean {
  return FEATURE_FLAGS[flag] === true;
}
