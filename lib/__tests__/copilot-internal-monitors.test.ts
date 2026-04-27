import { POST } from '@/app/api/copilot/internal/list-configured-monitors/route';
import { NextRequest } from 'next/server';

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    monitor: { findMany: jest.fn() },
  },
}));

import prisma from '@/lib/db';
const mockedPrisma = prisma as unknown as { monitor: { findMany: jest.Mock } };

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
