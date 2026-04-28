/**
 * Schema-level isolation test for the Monitor + Finding migration.
 *
 * Runs against a live Prisma test DB. To execute locally:
 *   DATABASE_URL=<test-db-url> npx jest prisma/__tests__/monitor_finding_isolation.test.ts
 *
 * If DATABASE_URL is not pointed at a test DB, the test skips itself.
 */
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

describeIfTestDb('Monitor + Finding isolation (schema-level)', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `mon-iso-test-${Date.now()}` },
    });
    orgId = org.id;
    const stackA = await prisma.pipelineStack.create({
      data: { name: 'Stack A', organizationId: orgId },
    });
    const stackB = await prisma.pipelineStack.create({
      data: { name: 'Stack B', organizationId: orgId },
    });
    stackAId = stackA.id;
    stackBId = stackB.id;
  });

  afterAll(async () => {
    await prisma.pipelineStack.deleteMany({ where: { organizationId: orgId } });
    await prisma.organization.delete({ where: { id: orgId } });
    await prisma.$disconnect();
  });

  it('allows two profiles in the same org to hold a Monitor with the same (targetFqn, monitorType)', async () => {
    const a = await prisma.monitor.create({
      data: {
        name: 'm-a', monitorType: 'FRESHNESS', targetFqn: 'db.schema.users',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    const b = await prisma.monitor.create({
      data: {
        name: 'm-b', monitorType: 'FRESHNESS', targetFqn: 'db.schema.users',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
    expect(a.id).not.toBe(b.id);
  });

  it('Monitor.findMany filtered by pipelineStackId returns only that profile', async () => {
    const aRows = await prisma.monitor.findMany({
      where: { organizationId: orgId, pipelineStackId: stackAId },
    });
    const bRows = await prisma.monitor.findMany({
      where: { organizationId: orgId, pipelineStackId: stackBId },
    });
    expect(aRows.every((r) => r.pipelineStackId === stackAId)).toBe(true);
    expect(bRows.every((r) => r.pipelineStackId === stackBId)).toBe(true);
    expect(aRows.length).toBeGreaterThan(0);
    expect(bRows.length).toBeGreaterThan(0);
  });

  it('Finding unique constraint includes pipelineStackId — same fingerprint allowed across stacks', async () => {
    const fp = `fp-${Date.now()}`;
    await prisma.finding.create({
      data: {
        fingerprint: fp, table: 'db.schema.users', scanType: 'quality',
        findingType: 'null_rate', severity: 'LOW', title: 't', description: 'd',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    const b = await prisma.finding.create({
      data: {
        fingerprint: fp, table: 'db.schema.users', scanType: 'quality',
        findingType: 'null_rate', severity: 'LOW', title: 't', description: 'd',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
    expect(b.pipelineStackId).toBe(stackBId);
  });

  it('cascades delete from PipelineStack to Monitor + MonitorRun', async () => {
    const tempStack = await prisma.pipelineStack.create({
      data: { name: 'Temp', organizationId: orgId },
    });
    const monitor = await prisma.monitor.create({
      data: {
        name: 'cascade-check', monitorType: 'FRESHNESS', targetFqn: 'cascade.users',
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    await prisma.monitorRun.create({
      data: { status: 'PASS', monitorId: monitor.id },
    });
    await prisma.pipelineStack.delete({ where: { id: tempStack.id } });
    const orphanMonitors = await prisma.monitor.findMany({
      where: { pipelineStackId: tempStack.id },
    });
    const orphanRuns = await prisma.monitorRun.findMany({
      where: { monitorId: monitor.id },
    });
    expect(orphanMonitors).toHaveLength(0);
    expect(orphanRuns).toHaveLength(0);
  });

  it('cascades delete from PipelineStack to MonitorGroup, MonitoringPlan, Finding, DriftRecommendation', async () => {
    const tempStack = await prisma.pipelineStack.create({
      data: { name: 'Temp2', organizationId: orgId },
    });
    const plan = await prisma.monitoringPlan.create({
      data: {
        name: 'p', scopeType: 'pipeline', mode: 'manual', families: [],
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    const group = await prisma.monitorGroup.create({
      data: {
        name: 'g', groupType: 'custom',
        organizationId: orgId, pipelineStackId: tempStack.id, monitoringPlanId: plan.id,
      },
    });
    const monitor = await prisma.monitor.create({
      data: {
        name: 'm', monitorType: 'FRESHNESS', targetFqn: 'cascade2.users',
        organizationId: orgId, pipelineStackId: tempStack.id, monitorGroupId: group.id,
      },
    });
    await prisma.finding.create({
      data: {
        fingerprint: `cascade-fp-${Date.now()}`, table: 'cascade2.users', scanType: 'quality',
        findingType: 'null_rate', severity: 'LOW', title: 't', description: 'd',
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    await prisma.driftRecommendation.create({
      data: {
        organizationId: orgId, pipelineStackId: tempStack.id,
        monitorId: monitor.id, monitorName: 'm', monitorType: 'FRESHNESS',
        targetFqn: 'cascade2.users', driftCategory: 'threshold', severity: 'low',
        currentField: 'x', currentValue: '1', recommendedValue: '2',
        reasoning: 'r', confidence: 0.9, evidence: {}, runId: 'run-x',
      },
    });
    await prisma.pipelineStack.delete({ where: { id: tempStack.id } });
    expect(await prisma.monitor.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.monitorGroup.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.monitoringPlan.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.finding.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.driftRecommendation.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
  });
});
