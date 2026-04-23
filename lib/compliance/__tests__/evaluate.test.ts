import { describe, it, expect } from 'vitest';
import { evaluateNodeCompliance } from '../evaluate';

describe('evaluateNodeCompliance against tier baseline', () => {
  it('returns compliant when SLA matches T0 baseline', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 15, oncallRequired: true },
      null,
      'T0',
    );
    expect(result.overallStatus).toBe('compliant');
    expect(result.fields.every(f => f.status === 'compliant')).toBe(true);
  });

  it('returns violation when SLA is looser than T0', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 60 },
      null,
      'T0',
    );
    const freshness = result.fields.find(f => f.fieldName === 'expectedFreshnessMinutes');
    expect(freshness?.status).toBe('violation');
    expect(result.overallStatus).toBe('violation');
  });

  it('returns override when SLA is stricter than T1', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 15 },
      null,
      'T1',
    );
    const freshness = result.fields.find(f => f.fieldName === 'expectedFreshnessMinutes');
    expect(freshness?.status).toBe('override');
    expect(result.overallStatus).toBe('override');
  });
});

describe('evaluateNodeCompliance against contract', () => {
  it('uses contract as baseline when provided', () => {
    const contract = { expectedFreshnessMinutes: 30, oncallRequired: true };
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 60 },
      contract,
      'T0',
    );
    const freshness = result.fields.find(f => f.fieldName === 'expectedFreshnessMinutes');
    expect(freshness?.status).toBe('violation');
    expect(freshness?.contractValue).toBe(30);
    expect(freshness?.slaValue).toBe(60);
  });
});

describe('evaluateNodeCompliance — overall status priority', () => {
  it('violation wins over override', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 10, oncallRequired: false },
      { expectedFreshnessMinutes: 30, oncallRequired: true },
      'T0',
    );
    expect(result.overallStatus).toBe('violation');
  });

  it('returns unknown when no SLA values and no tier', () => {
    const result = evaluateNodeCompliance({}, null, null);
    expect(result.overallStatus).toBe('unknown');
  });
});
