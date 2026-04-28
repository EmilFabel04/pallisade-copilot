/**
 * Route-level test for GET /api/schedule/tasks.
 *
 * Verifies that the schedule tasks list is scoped by pipelineStackId,
 * not just organizationId, and that requests without stackId are
 * rejected with 400.
 *
 * Self-skips if DATABASE_URL is not a test DB.
 */
import { PrismaClient } from '@prisma/client';
import { GET } from '../route';
import { NextRequest } from 'next/server';

const prisma = new PrismaClient();
const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

jest.mock('@/auth', () => ({
  auth: jest.fn(),
}));

describeIfTestDb('GET /api/schedule/tasks — stack isolation', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `tasks-iso-${Date.now()}` },
    });
    orgId = org.id;
    const { auth } = require('@/auth');
    (auth as jest.Mock).mockResolvedValue({
      user: { id: 'u', organizationId: orgId },
    });
    const a = await prisma.pipelineStack.create({
      data: { name: 'A', organizationId: orgId },
    });
    const b = await prisma.pipelineStack.create({
      data: { name: 'B', organizationId: orgId },
    });
    stackAId = a.id;
    stackBId = b.id;
    await prisma.monitor.create({
      data: {
        name: 'in-a', monitorType: 'FRESHNESS', targetFqn: 'db.s.t1',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    await prisma.monitor.create({
      data: {
        name: 'in-b', monitorType: 'FRESHNESS', targetFqn: 'db.s.t2',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
  });

  afterAll(async () => {
    await prisma.pipelineStack.deleteMany({ where: { organizationId: orgId } });
    await prisma.organization.delete({ where: { id: orgId } });
    await prisma.$disconnect();
  });

  it('returns only the requested stack monitors', async () => {
    const req = new NextRequest(`http://localhost/api/schedule/tasks?stackId=${stackAId}`);
    const res = await GET(req);
    const body = await res.json();
    expect(body.tasks).toHaveLength(1);
    expect(body.tasks[0].name).toBe('in-a');
  });

  it('400s when stackId is missing', async () => {
    const req = new NextRequest('http://localhost/api/schedule/tasks');
    const res = await GET(req);
    expect(res.status).toBe(400);
  });
});
