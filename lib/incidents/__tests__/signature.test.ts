import { fallbackSignature } from '../signature';

describe('fallbackSignature', () => {
  it('produces the same slug for the same monitor type and breach class', () => {
    const a = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    const b = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    expect(a).toEqual(b);
  });

  it('differs across monitor types', () => {
    const a = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    const b = fallbackSignature({ monitorType: 'VOLUME',    breachClass: 'over-threshold' });
    expect(a).not.toEqual(b);
  });

  it('produces a kebab-case slug shorter than 32 chars', () => {
    const slug = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    expect(slug).toMatch(/^[a-z0-9-]+$/);
    expect(slug.length).toBeLessThanOrEqual(32);
  });
});
