import { getTierBaseline, getTierBaselineValue } from '../tier-baselines';

describe('getTierBaseline', () => {
  it('T0 has strictest freshness', () => {
    const baseline = getTierBaseline('T0');
    expect(baseline.expectedFreshnessMinutes).toBe(15);
  });

  it('T3 has most relaxed freshness', () => {
    const baseline = getTierBaseline('T3');
    expect(baseline.expectedFreshnessMinutes).toBe(1440);
  });

  it('T0 requires oncall', () => {
    const baseline = getTierBaseline('T0');
    expect(baseline.oncallRequired).toBe(true);
  });

  it('T2 does not require oncall', () => {
    const baseline = getTierBaseline('T2');
    expect(baseline.oncallRequired).toBe(false);
  });

  it('T1 has warn schema change policy', () => {
    const baseline = getTierBaseline('T1');
    expect(baseline.schemaChangePolicy).toBe('warn');
  });

  it('T0 has fail schema change policy', () => {
    const baseline = getTierBaseline('T0');
    expect(baseline.schemaChangePolicy).toBe('fail');
  });
});

describe('getTierBaselineValue', () => {
  it('returns the value for a field in a tier', () => {
    expect(getTierBaselineValue('T1', 'maxSyncDelayMinutes')).toBe(60);
  });

  it('returns undefined for a field not in tier baseline', () => {
    expect(getTierBaselineValue('T0', 'maxQueryCostUsd')).toBeUndefined();
  });

  it('returns undefined for invalid tier', () => {
    expect(getTierBaselineValue('T9' as any, 'expectedFreshnessMinutes')).toBeUndefined();
  });
});
