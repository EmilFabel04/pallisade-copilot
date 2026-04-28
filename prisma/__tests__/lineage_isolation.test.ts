/**
 * Schema-level isolation test for the lineage migration.
 *
 * Runs against a live Prisma test DB. To execute locally:
 *   DATABASE_URL=<test-db-url> npx jest prisma/__tests__/lineage_isolation.test.ts
 *
 * If DATABASE_URL is not pointed at a test DB, the test skips itself.
 */
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

describeIfTestDb('Lineage isolation (schema-level)', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `iso-test-${Date.now()}` },
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

  it('allows two profiles in the same org to hold the same FQN', async () => {
    const fqn = 'db.schema.users';
    const a = await prisma.lineageNode.create({
      data: {
        name: fqn, tableName: 'users',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    const b = await prisma.lineageNode.create({
      data: {
        name: fqn, tableName: 'users',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
    expect(a.id).not.toBe(b.id);
  });

  it('findMany filtered by pipelineStackId returns only that stack', async () => {
    const aRows = await prisma.lineageNode.findMany({
      where: { organizationId: orgId, pipelineStackId: stackAId },
    });
    const bRows = await prisma.lineageNode.findMany({
      where: { organizationId: orgId, pipelineStackId: stackBId },
    });
    expect(aRows.every((r) => r.pipelineStackId === stackAId)).toBe(true);
    expect(bRows.every((r) => r.pipelineStackId === stackBId)).toBe(true);
    expect(aRows.length).toBeGreaterThan(0);
    expect(bRows.length).toBeGreaterThan(0);
  });

  it('cascades delete from PipelineStack to LineageNode rows', async () => {
    const tempStack = await prisma.pipelineStack.create({
      data: { name: 'Temp', organizationId: orgId },
    });
    await prisma.lineageNode.create({
      data: {
        name: 'db.schema.cascade_check', tableName: 'cascade_check',
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    await prisma.pipelineStack.delete({ where: { id: tempStack.id } });
    const orphaned = await prisma.lineageNode.findMany({
      where: { pipelineStackId: tempStack.id },
    });
    expect(orphaned).toHaveLength(0);
  });
});
