/**
 * Run with: npx jest lib/incidents/__tests__/lifecycle.test.ts
 */

import { handleRun, LifecycleResult } from '../lifecycle';

// Minimal fakes — we type the prisma client narrowly so the test does not
// require a real DB connection.
type FakeRun = {
  id: string;
  monitorId: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'ERROR' | 'SKIPPED';
  startedAt: Date;
  completedAt: Date | null;
};

type FakeIncident = {
  id: string;
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';
  signature: string | null;
  consecutiveCount: number;
};

function makePrismaMock(opts: {
  monitor: { id: string; organizationId: string; pipelineStackId: string; targetFqn: string; monitorGroupId?: string | null };
  existingIncident?: FakeIncident | null;
}) {
  const incidentCreate = jest.fn(async (args: any) => ({ id: 'inc_new', ...args.data }));
  const incidentUpdate = jest.fn(async (args: any) => ({ ...opts.existingIncident, ...args.data }));
  const incidentFindFirst = jest.fn(async () => opts.existingIncident ?? null);
  const monitorFindUnique = jest.fn(async () => opts.monitor);

  return {
    incident: { create: incidentCreate, update: incidentUpdate, findFirst: incidentFindFirst },
    monitor: { findUnique: monitorFindUnique },
    _spies: { incidentCreate, incidentUpdate, incidentFindFirst },
  } as any;
}

describe('handleRun: opening', () => {
  it('opens a new incident when a FAIL run has no open incident on this monitor', async () => {
    const prisma = makePrismaMock({
      monitor: {
        id: 'mon_1',
        organizationId: 'org_1',
        pipelineStackId: 'stack_1',
        targetFqn: 'raw.orders',
        monitorGroupId: 'grp_1',
      },
      existingIncident: null,
    });

    const run: FakeRun = {
      id: 'run_1',
      monitorId: 'mon_1',
      status: 'FAIL',
      startedAt: new Date('2026-05-04T10:00:00Z'),
      completedAt: new Date('2026-05-04T10:00:05Z'),
    };

    const result: LifecycleResult = await handleRun(run as any, prisma);

    expect(result.action).toBe('opened');
    expect(result.shouldDiagnose).toBe(true);
    expect(prisma._spies.incidentCreate).toHaveBeenCalledTimes(1);
    const call = prisma._spies.incidentCreate.mock.calls[0][0];
    expect(call.data).toMatchObject({
      monitorId: 'mon_1',
      organizationId: 'org_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      status: 'OPEN',
      severity: 'FAIL',
      openingRunId: 'run_1',
      consecutiveCount: 1,
    });
    expect(call.data.openedAt).toEqual(run.startedAt);
  });

  it('opens with severity=WARN when the run is WARN', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: null,
    });
    const run: FakeRun = {
      id: 'run_w',
      monitorId: 'mon_1',
      status: 'WARN',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    await handleRun(run as any, prisma);
    const call = prisma._spies.incidentCreate.mock.calls[0][0];
    expect(call.data.severity).toBe('WARN');
  });
});
