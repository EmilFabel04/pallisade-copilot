/**
 * Run with: npx jest components/monitors/__tests__/SummaryHero.test.ts
 */
import { selectHeroTone, buildHeadline, buildSubline } from '../SummaryHero.helpers';
import type { MonitorHealthSummary } from '@/types/monitors-summary';

const ZERO: MonitorHealthSummary = {
  total: 0, healthy: 0, warning: 0, failing: 0,
  dataAssets: 0, pipelineTools: 0, lastRunAt: null,
};

const HEALTHY: MonitorHealthSummary = {
  total: 47, healthy: 47, warning: 0, failing: 0,
  dataAssets: 38, pipelineTools: 6, lastRunAt: '2026-05-04T14:32:00Z',
};

describe('selectHeroTone()', () => {
  it('returns grey when total === 0', () => {
    expect(selectHeroTone(ZERO, 0, 0)).toBe('grey');
  });

  it('returns green when all monitors pass and no incidents', () => {
    expect(selectHeroTone(HEALTHY, 0, 0)).toBe('green');
  });

  it('returns amber when health.warning > 0 and no FAIL signals', () => {
    expect(selectHeroTone({ ...HEALTHY, healthy: 45, warning: 2 }, 0, 0)).toBe('amber');
  });

  it('returns amber when warnIncidentCount > 0 and no FAIL signals', () => {
    expect(selectHeroTone(HEALTHY, 0, 1)).toBe('amber');
  });

  it('returns red when health.failing > 0 even if no incidents are open', () => {
    expect(selectHeroTone({ ...HEALTHY, healthy: 44, failing: 3 }, 0, 0)).toBe('red');
  });

  it('returns red when failIncidentCount > 0 even when monitor counts look clean', () => {
    expect(selectHeroTone(HEALTHY, 1, 0)).toBe('red');
  });

  it('red wins over amber when both signals present', () => {
    expect(selectHeroTone({ ...HEALTHY, warning: 2, failing: 1 }, 0, 0)).toBe('red');
  });
});

describe('buildHeadline()', () => {
  it('grey state', () => {
    expect(
      buildHeadline('grey', { health: ZERO, failIncidentCount: 0, warnIncidentCount: 0, oldestOpenMs: null }),
    ).toBe('Setting up. No monitors yet.');
  });

  it('green state', () => {
    expect(
      buildHeadline('green', { health: HEALTHY, failIncidentCount: 0, warnIncidentCount: 0, oldestOpenMs: null }),
    ).toBe('All systems healthy.');
  });

  it('amber pluralization for one warning', () => {
    expect(
      buildHeadline('amber', { health: { ...HEALTHY, warning: 1 }, failIncidentCount: 0, warnIncidentCount: 0, oldestOpenMs: null }),
    ).toBe('1 warning.');
  });

  it('amber pluralization for many', () => {
    expect(
      buildHeadline('amber', { health: { ...HEALTHY, warning: 3 }, failIncidentCount: 0, warnIncidentCount: 0, oldestOpenMs: null }),
    ).toBe('3 warnings.');
  });

  it('amber falls back to monitor warning count when no incident is open', () => {
    expect(
      buildHeadline('amber', {
        health: { ...HEALTHY, healthy: 45, warning: 2 },
        failIncidentCount: 0,
        warnIncidentCount: 0,
        oldestOpenMs: null,
      }),
    ).toBe('2 warnings.');
  });

  it('amber prefers incident warning count over monitor warning count', () => {
    expect(
      buildHeadline('amber', {
        health: { ...HEALTHY, healthy: 44, warning: 2 },
        failIncidentCount: 0,
        warnIncidentCount: 1,
        oldestOpenMs: null,
      }),
    ).toBe('1 warning.');
  });

  it('amber appends blast radius', () => {
    expect(
      buildHeadline('amber', {
        health: { ...HEALTHY, warning: 1 },
        failIncidentCount: 0,
        warnIncidentCount: 0,
        oldestOpenMs: null,
        blastRadius: { dashboards: 5, tables: 0 },
      }),
    ).toBe('1 warning. Affecting 5 dashboards.');
  });

  it('red headline includes critical count and warning suffix', () => {
    expect(
      buildHeadline('red', {
        health: { ...HEALTHY, failing: 2, warning: 1 },
        failIncidentCount: 2,
        warnIncidentCount: 1,
        oldestOpenMs: null,
      }),
    ).toBe('2 critical incidents · 1 warning.');
  });

  it('red headline appends blast radius and oldest age when given', () => {
    expect(
      buildHeadline('red', {
        health: { ...HEALTHY, failing: 1 },
        failIncidentCount: 1,
        warnIncidentCount: 0,
        oldestOpenMs: 2 * 3600 * 1000 + 14 * 60 * 1000,
        blastRadius: { dashboards: 3, tables: 14 },
      }),
    ).toBe('1 critical incident. Affecting 3 BI dashboards and 14 downstream tables. Oldest 2h 14m.');
  });
});

describe('buildSubline()', () => {
  it('formats counts with proper pluralization', () => {
    expect(buildSubline(HEALTHY)).toBe('47 monitors · 47 healthy · 0 warning · 0 failing — 38 data assets, 6 pipeline tools');
  });

  it('handles singular forms', () => {
    expect(
      buildSubline({ total: 1, healthy: 1, warning: 0, failing: 0, dataAssets: 1, pipelineTools: 1, lastRunAt: null }),
    ).toBe('1 monitor · 1 healthy · 0 warning · 0 failing — 1 data asset, 1 pipeline tool');
  });
});
