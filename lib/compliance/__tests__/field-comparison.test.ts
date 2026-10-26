import { compareFieldToBaseline, type ComplianceStatus } from '../field-comparison';

describe('compareFieldToBaseline — numeric lower-is-stricter', () => {
  it('returns compliant when equal', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 30, 30)).toBe('compliant');
  });
  it('returns override when SLA is stricter (lower)', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 15, 30)).toBe('override');
  });
  it('returns violation when SLA is looser (higher)', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 60, 30)).toBe('violation');
  });
});

describe('compareFieldToBaseline — numeric higher-is-stricter', () => {
  it('returns override when SLA is stricter (higher retries)', () => {
    expect(compareFieldToBaseline('maxRetries', 5, 3)).toBe('override');
  });
  it('returns violation when SLA is looser (lower retries)', () => {
    expect(compareFieldToBaseline('maxRetries', 1, 3)).toBe('violation');
  });
});

describe('compareFieldToBaseline — boolean true-is-stricter', () => {
  it('returns override when SLA=true, baseline=false', () => {
    expect(compareFieldToBaseline('oncallRequired', true, false)).toBe('override');
  });
  it('returns violation when SLA=false, baseline=true', () => {
    expect(compareFieldToBaseline('oncallRequired', false, true)).toBe('violation');
  });
  it('returns compliant when both true', () => {
    expect(compareFieldToBaseline('oncallRequired', true, true)).toBe('compliant');
  });
});

describe('compareFieldToBaseline — ordered enum', () => {
  it('schemaChangePolicy: fail > warn = override', () => {
    expect(compareFieldToBaseline('schemaChangePolicy', 'fail', 'warn')).toBe('override');
  });
  it('schemaChangePolicy: ignore < warn = violation', () => {
    expect(compareFieldToBaseline('schemaChangePolicy', 'ignore', 'warn')).toBe('violation');
  });
  it('connectorPriority: critical > high = override', () => {
    expect(compareFieldToBaseline('connectorPriority', 'critical', 'high')).toBe('override');
  });
});

describe('compareFieldToBaseline — superset (requiredTests)', () => {
  it('superset is override', () => {
    expect(compareFieldToBaseline('requiredTests', ['not_null', 'unique', 'freshness'], ['not_null', 'unique'])).toBe('override');
  });
  it('subset is violation', () => {
    expect(compareFieldToBaseline('requiredTests', ['not_null'], ['not_null', 'unique'])).toBe('violation');
  });
  it('equal set is compliant', () => {
    expect(compareFieldToBaseline('requiredTests', ['not_null', 'unique'], ['not_null', 'unique'])).toBe('compliant');
  });
});

describe('compareFieldToBaseline — null handling', () => {
  it('returns unknown when SLA value is null', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', null, 30)).toBe('unknown');
  });
  it('returns unknown when baseline is null', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 30, null)).toBe('unknown');
  });
});
