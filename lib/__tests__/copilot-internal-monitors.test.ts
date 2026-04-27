import { POST } from '@/app/api/copilot/internal/list-configured-monitors/route';
import { POST as runHistoryPOST } from '@/app/api/copilot/internal/get-monitor-run-history/route';
import { NextRequest } from 'next/server';

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    monitor: { findMany: jest.fn(), findFirst: jest.fn() },
    monitorRun: { findMany: jest.fn() },
  },
}));

import prisma from '@/lib/db';
const mockedPrisma = prisma as unknown as { monitor: { findMany: jest.Mock } };
const mockedPrisma2 = prisma as unknown as {
  monitor: { findMany: jest.Mock; findFirst: jest.Mock };
  monitorRun: { findMany: jest.Mock };
};

const SECRET = 'pallisade-internal';

function makeRequest(body: any, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest('http://localhost/api/copilot/internal/list-configured-monitors', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Secret': headers['X-Internal-Secret'] ?? SECRET,
      'X-Organization-Id': headers['X-Organization-Id'] ?? 'org_1',
    },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  process.env.INTERNAL_API_SECRET = SECRET;
  mockedPrisma.monitor.findMany.mockReset();
});

describe('list-configured-monitors POST', () => {
  test('rejects missing internal secret', async () => {
    const req = makeRequest({}, { 'X-Internal-Secret': '' });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  test('rejects mismatched internal secret', async () => {
    const req = makeRequest({}, { 'X-Internal-Secret': 'wrong' });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  test('rejects missing X-Organization-Id', async () => {
    const req = makeRequest({}, { 'X-Organization-Id': '' });
    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  test('returns monitors scoped to org with default filters', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([
      {
        id: 'mon_1',
        name: 'orders source validation',
        monitorType: 'DBT_CORE_SOURCE_VALIDATION',
        targetFqn: 'analytics.orders',
        enabled: true,
        schedule: '0 6 * * *',
        lastRunAt: new Date('2026-04-27T06:00:00Z'),
        lastStatus: 'FAIL',
      },
    ]);

    const req = makeRequest({});
    const res = await POST(req);
    const data = await res.json();

    expect(res.status).toBe(200);
    expect(mockedPrisma.monitor.findMany).toHaveBeenCalledWith(
      expect.objectContaining({
        where: expect.objectContaining({ organizationId: 'org_1' }),
      }),
    );
    expect(data.monitors).toHaveLength(1);
    expect(data.monitors[0]).toMatchObject({
      id: 'mon_1',
      name: 'orders source validation',
      monitorType: 'DBT_CORE_SOURCE_VALIDATION',
      targetFqn: 'analytics.orders',
      lastStatus: 'FAIL',
    });
  });

  test('applies monitor_type filter (case-insensitive, accepts list)', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({
      monitor_type: ['dbt_core_source_validation', 'DBT_CORE_REF_INTEGRITY'],
    });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.monitorType).toEqual({
      in: ['DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY'],
    });
  });

  test('splits comma-separated monitor_type string into array', async () => {
    // The LLM sends comma-separated strings (per tool description). The
    // endpoint must split them before passing to Prisma's `in` clause —
    // otherwise Prisma rejects "FOO,BAR" as a single invalid enum value.
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({
      monitor_type: 'DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY',
    });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.monitorType).toEqual({
      in: ['DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY'],
    });
  });

  test('splits comma-separated status string into array', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({ status: 'FAIL,ERROR' });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.lastStatus).toEqual({ in: ['FAIL', 'ERROR'] });
  });

  test('handles whitespace and blanks around comma-separated values', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({ monitor_type: 'FRESHNESS, ,VOLUME ' });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.monitorType).toEqual({ in: ['FRESHNESS', 'VOLUME'] });
  });

  test('applies status filter and target_fqn filter', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({
      status: ['FAIL', 'ERROR'],
      target_fqn: 'analytics.orders',
    });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.lastStatus).toEqual({ in: ['FAIL', 'ERROR'] });
    expect(where.targetFqn).toBe('analytics.orders');
  });

  test('respects limit parameter (default 50, max 200)', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);

    await POST(makeRequest({}));
    expect((mockedPrisma.monitor.findMany.mock.calls[0][0] as any).take).toBe(50);

    await POST(makeRequest({ limit: 10 }));
    expect((mockedPrisma.monitor.findMany.mock.calls[1][0] as any).take).toBe(10);

    await POST(makeRequest({ limit: 999 }));
    expect((mockedPrisma.monitor.findMany.mock.calls[2][0] as any).take).toBe(200);
  });
});

function makeRunHistoryRequest(body: any, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest('http://localhost/api/copilot/internal/get-monitor-run-history', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Secret': headers['X-Internal-Secret'] ?? SECRET,
      'X-Organization-Id': headers['X-Organization-Id'] ?? 'org_1',
    },
    body: JSON.stringify(body),
  });
}

describe('get-monitor-run-history POST', () => {
  beforeEach(() => {
    mockedPrisma2.monitor.findFirst.mockReset();
    mockedPrisma2.monitorRun.findMany.mockReset();
  });

  test('rejects when monitor_id missing', async () => {
    const res = await runHistoryPOST(makeRunHistoryRequest({}));
    expect(res.status).toBe(400);
  });

  test('returns 404 when monitor does not belong to org', async () => {
    mockedPrisma2.monitor.findFirst.mockResolvedValue(null);
    const res = await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_other' }));
    expect(res.status).toBe(404);
    expect(mockedPrisma2.monitor.findFirst).toHaveBeenCalledWith({
      where: { id: 'mon_other', organizationId: 'org_1' },
      select: { id: true, name: true, monitorType: true, targetFqn: true },
    });
  });

  test('returns recent runs ordered newest first', async () => {
    mockedPrisma2.monitor.findFirst.mockResolvedValue({
      id: 'mon_1',
      name: 'orders source validation',
      monitorType: 'DBT_CORE_SOURCE_VALIDATION',
      targetFqn: 'analytics.orders',
    });
    mockedPrisma2.monitorRun.findMany.mockResolvedValue([
      {
        id: 'run_2',
        status: 'FAIL',
        message: 'source freshness exceeded threshold',
        details: null,
        sqlExecuted: 'SELECT MAX(_loaded_at) ...',
        startedAt: new Date('2026-04-27T06:00:00Z'),
        completedAt: new Date('2026-04-27T06:00:02Z'),
        durationMs: 2000,
      },
      {
        id: 'run_1',
        status: 'PASS',
        message: null,
        details: null,
        sqlExecuted: 'SELECT MAX(_loaded_at) ...',
        startedAt: new Date('2026-04-26T06:00:00Z'),
        completedAt: new Date('2026-04-26T06:00:01Z'),
        durationMs: 1000,
      },
    ]);

    const res = await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1', limit: 5 }));
    const data = await res.json();

    expect(res.status).toBe(200);
    expect(data.monitor.id).toBe('mon_1');
    expect(data.runs).toHaveLength(2);
    expect(data.runs[0].id).toBe('run_2');
    expect(mockedPrisma2.monitorRun.findMany).toHaveBeenCalledWith({
      where: { monitorId: 'mon_1' },
      select: expect.any(Object),
      orderBy: { startedAt: 'desc' },
      take: 5,
    });
  });

  test('clamps limit to [1, 50]', async () => {
    mockedPrisma2.monitor.findFirst.mockResolvedValue({ id: 'mon_1', name: 'x', monitorType: 'FRESHNESS', targetFqn: 't' });
    mockedPrisma2.monitorRun.findMany.mockResolvedValue([]);

    await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1' }));
    expect((mockedPrisma2.monitorRun.findMany.mock.calls[0][0] as any).take).toBe(10);

    await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1', limit: 100 }));
    expect((mockedPrisma2.monitorRun.findMany.mock.calls[1][0] as any).take).toBe(50);

    await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1', limit: 0 }));
    expect((mockedPrisma2.monitorRun.findMany.mock.calls[2][0] as any).take).toBe(1);
  });
});
