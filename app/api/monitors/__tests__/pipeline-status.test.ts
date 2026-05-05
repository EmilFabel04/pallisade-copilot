/**
 * Run with: npx jest app/api/monitors/__tests__/pipeline-status.test.ts
 */

// Mock ESM dependencies so Jest can load the route module without a real
// Next.js / Prisma runtime. Only the pure aggregateByTool() function is tested here.
jest.mock('@/auth', () => ({ auth: jest.fn() }));
jest.mock('@/lib/db', () => ({ __esModule: true, default: {} }));

import { aggregateByTool } from '../pipeline-status/route';

function mon(toolType: string, lastStatus: string | null, lastRunAt: Date | null = new Date('2026-05-04T10:00:00Z')) {
  return { toolType, lastStatus, lastRunAt };
}

describe('pipeline-status aggregateByTool()', () => {
  it('groups by tool and applies FAIL > ERROR > WARN > PASS precedence', () => {
    const out = aggregateByTool([
      mon('fivetran', 'PASS'),
      mon('fivetran', 'WARN'),
      mon('fivetran', 'FAIL'),
      mon('airflow', 'PASS'),
      mon('airflow', 'ERROR'),
    ]);
    const fivetran = out.find((t) => t.toolType === 'fivetran')!;
    expect(fivetran.status).toBe('FAIL');
    expect(fivetran.failCount).toBe(1);
    expect(fivetran.warnCount).toBe(1);
    expect(fivetran.monitorCount).toBe(3);

    const airflow = out.find((t) => t.toolType === 'airflow')!;
    expect(airflow.status).toBe('ERROR');
    expect(airflow.failCount).toBe(1);
  });

  it('marks NEVER_RUN when every monitor for a tool has null lastStatus', () => {
    const out = aggregateByTool([
      mon('dbt_cloud', null, null),
      mon('dbt_cloud', null, null),
    ]);
    expect(out[0].status).toBe('NEVER_RUN');
    expect(out[0].lastRunAt).toBeNull();
  });

  it('returns empty array for no monitors', () => {
    expect(aggregateByTool([])).toEqual([]);
  });

  it('returns the most recent lastRunAt across the tool', () => {
    const a = new Date('2026-05-04T09:00:00Z');
    const b = new Date('2026-05-04T11:30:00Z');
    const out = aggregateByTool([
      mon('fivetran', 'PASS', a),
      mon('fivetran', 'PASS', b),
      mon('fivetran', 'PASS', null),
    ]);
    expect(out[0].lastRunAt).toBe(b.toISOString());
  });

  it('produces a friendly displayName for known tool types', () => {
    const out = aggregateByTool([
      mon('fivetran', 'PASS'),
      mon('dbt_cloud', 'PASS'),
      mon('linux_server', 'PASS'),
      mon('something_unknown', 'PASS'),
    ]);
    const byType: Record<string, string> = Object.fromEntries(out.map((t) => [t.toolType, t.displayName]));
    expect(byType.fivetran).toBe('Fivetran');
    expect(byType.dbt_cloud).toBe('dbt cloud');
    expect(byType.linux_server).toBe('linux server');
    expect(byType.something_unknown).toBe('Something Unknown');
  });
});
