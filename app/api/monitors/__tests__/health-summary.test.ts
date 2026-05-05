/**
 * Run with: npx jest app/api/monitors/__tests__/health-summary.test.ts
 */

// Mock ESM dependencies so Jest can load the route module without a real
// Next.js / Prisma runtime. Only the pure aggregate() function is tested here.
jest.mock('@/auth', () => ({ auth: jest.fn() }));
jest.mock('@/lib/db', () => ({ __esModule: true, default: {} }));

import { aggregate } from '../health-summary/route';

const DATA_FQN = 'analytics.fct_orders';

function mon(over: Partial<{
  monitorType: string; targetFqn: string | null; lastStatus: string | null; lastRunAt: Date | null;
}> = {}) {
  return {
    monitorType: 'FRESHNESS',
    targetFqn: DATA_FQN,
    lastStatus: 'PASS' as string | null,
    lastRunAt: new Date('2026-05-04T10:00:00Z') as Date | null,
    ...over,
  };
}

describe('health-summary aggregate()', () => {
  it('returns zeros for an empty profile', () => {
    expect(aggregate([])).toEqual({
      total: 0,
      healthy: 0,
      warning: 0,
      failing: 0,
      dataAssets: 0,
      pipelineTools: 0,
      lastRunAt: null,
    });
  });

  it('counts PASS, NULL, and SKIPPED as healthy', () => {
    const out = aggregate([
      mon({ lastStatus: 'PASS' }),
      mon({ lastStatus: null }),
      mon({ lastStatus: 'SKIPPED' }),
    ]);
    expect(out.healthy).toBe(3);
    expect(out.warning).toBe(0);
    expect(out.failing).toBe(0);
  });

  it('counts WARN as warning, FAIL and ERROR as failing', () => {
    const out = aggregate([
      mon({ lastStatus: 'WARN' }),
      mon({ lastStatus: 'FAIL' }),
      mon({ lastStatus: 'ERROR' }),
    ]);
    expect(out.warning).toBe(1);
    expect(out.failing).toBe(2);
  });

  it('counts distinct targetFqn for data-tier monitors only', () => {
    const out = aggregate([
      mon({ monitorType: 'FRESHNESS', targetFqn: 'a.x' }),
      mon({ monitorType: 'VOLUME',    targetFqn: 'a.x' }),
      mon({ monitorType: 'FRESHNESS', targetFqn: 'a.y' }),
      mon({ monitorType: 'SYNC_LAG',  targetFqn: 'a.z' }),
    ]);
    expect(out.dataAssets).toBe(2);
  });

  it('counts distinct toolType for pipeline-tier monitors only', () => {
    const out = aggregate([
      mon({ monitorType: 'FRESHNESS' }),
      mon({ monitorType: 'SYNC_LAG',          targetFqn: null }),
      mon({ monitorType: 'DAG_LAST_RUN',      targetFqn: null }),
      mon({ monitorType: 'DAG_SCHEDULE_LAG',  targetFqn: null }),
    ]);
    expect(out.pipelineTools).toBe(2); // ingestion (SYNC_LAG) + orchestration (DAG_*)
  });

  it('returns the most recent lastRunAt as ISO', () => {
    const earlier = new Date('2026-05-04T08:00:00Z');
    const later = new Date('2026-05-04T11:30:00Z');
    const out = aggregate([
      mon({ lastRunAt: earlier }),
      mon({ lastRunAt: later }),
      mon({ lastRunAt: null }),
    ]);
    expect(out.lastRunAt).toBe(later.toISOString());
  });
});
