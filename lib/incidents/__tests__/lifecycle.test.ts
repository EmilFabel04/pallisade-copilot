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

describe('handleRun: auto-resolve', () => {
  it('marks an open incident RESOLVED when a PASS run lands', async () => {
    const prisma = makePrismaMock({
      monitor: {
        id: 'mon_1',
        organizationId: 'org_1',
        pipelineStackId: 'stack_1',
        targetFqn: 'raw.orders',
      },
      existingIncident: {
        id: 'inc_1',
        status: 'OPEN',
        signature: 'fivetran-source-stalled',
        consecutiveCount: 2,
      },
    });

    const run: FakeRun = {
      id: 'run_2',
      monitorId: 'mon_1',
      status: 'PASS',
      startedAt: new Date('2026-05-04T11:00:00Z'),
      completedAt: new Date('2026-05-04T11:00:05Z'),
    };

    const result = await handleRun(run as any, prisma);

    expect(result.action).toBe('auto_resolved');
    expect(result.shouldDiagnose).toBe(false);
    expect(prisma._spies.incidentUpdate).toHaveBeenCalledTimes(1);
    const call = prisma._spies.incidentUpdate.mock.calls[0][0];
    expect(call.where).toEqual({ id: 'inc_1' });
    expect(call.data).toMatchObject({
      status: 'RESOLVED',
      resolvedBy: 'system',
      resolutionType: 'AUTO_RECOVERED',
    });
    expect(call.data.resolvedAt).toEqual(run.completedAt);
  });

  it('does nothing when a PASS run lands with no open incident', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: null,
    });
    const run: FakeRun = {
      id: 'run_3',
      monitorId: 'mon_1',
      status: 'PASS',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    const result = await handleRun(run as any, prisma);
    expect(result.action).toBe('noop');
    expect(prisma._spies.incidentCreate).not.toHaveBeenCalled();
    expect(prisma._spies.incidentUpdate).not.toHaveBeenCalled();
  });

  it('returns shouldDiagnose=true when a FAIL run hits an existing incident with consecutiveCount < 3', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: { id: 'inc_1', status: 'OPEN', signature: 'fivetran-source-stalled', consecutiveCount: 2 },
    });
    const run: FakeRun = {
      id: 'run_4',
      monitorId: 'mon_1',
      status: 'FAIL',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    const result = await handleRun(run as any, prisma);
    expect(result.action).toBe('matched');
    expect(result.shouldDiagnose).toBe(true);
    expect(result.incidentId).toBe('inc_1');
  });

  it('returns shouldDiagnose=false when a FAIL run hits an existing incident with consecutiveCount >= 3', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: { id: 'inc_1', status: 'OPEN', signature: 'fivetran-source-stalled', consecutiveCount: 3 },
    });
    const run: FakeRun = {
      id: 'run_5',
      monitorId: 'mon_1',
      status: 'FAIL',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    const result = await handleRun(run as any, prisma);
    expect(result.action).toBe('matched');
    expect(result.shouldDiagnose).toBe(false);
  });
});
