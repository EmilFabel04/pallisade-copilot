import type { SlaTier } from '@/components/contracts/types';

export interface TierBaseline {
  expectedFreshnessMinutes: number;
  maxSyncDelayMinutes: number;
  oncallRequired: boolean;
  maxRetries: number;
  schemaChangePolicy: 'fail' | 'warn' | 'ignore';
}

const TIER_BASELINES: Record<SlaTier, TierBaseline> = {
  T0: {
    expectedFreshnessMinutes: 15,
    maxSyncDelayMinutes: 15,
    oncallRequired: true,
    maxRetries: 5,
    schemaChangePolicy: 'fail',
  },
  T1: {
    expectedFreshnessMinutes: 60,
    maxSyncDelayMinutes: 60,
    oncallRequired: true,
    maxRetries: 3,
    schemaChangePolicy: 'warn',
  },
  T2: {
    expectedFreshnessMinutes: 360,
    maxSyncDelayMinutes: 360,
    oncallRequired: false,
    maxRetries: 3,
    schemaChangePolicy: 'warn',
  },
  T3: {
    expectedFreshnessMinutes: 1440,
    maxSyncDelayMinutes: 1440,
    oncallRequired: false,
    maxRetries: 1,
    schemaChangePolicy: 'ignore',
  },
};

export function getTierBaseline(tier: SlaTier): TierBaseline {
  return TIER_BASELINES[tier];
}

export function getTierBaselineValue(tier: SlaTier, field: string): unknown {
  const baseline = TIER_BASELINES[tier];
  if (!baseline) return undefined;
  return (baseline as unknown as Record<string, unknown>)[field];
}
