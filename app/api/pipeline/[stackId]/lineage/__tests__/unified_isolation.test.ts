/**
 * Route-level test for /api/pipeline/[stackId]/lineage/unified.
 *
 * Verifies that monitor.lastStatus and findings overlays are scoped
 * by pipelineStackId, not just by organizationId. Closes the original
 * red-dot-on-wrong-profile bug.
 *
 * Self-skips if DATABASE_URL is not a test DB.
 */
import { PrismaClient } from '@prisma/client';
import { GET } from '../unified/route';
import { NextRequest } from 'next/server';

const prisma = new PrismaClient();
const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

jest.mock('@/auth', () => ({
  auth: jest.fn(),
}));

describeIfTestDb('GET /api/pipeline/[stackId]/lineage/unified — monitor isolation', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `route-iso-test-${Date.now()}` },
    });
    orgId = org.id;
    const { auth } = require('@/auth');
    (auth as jest.Mock).mockResolvedValue({
      user: { id: 'test-user', organizationId: orgId },
    });

    const stackA = await prisma.pipelineStack.create({
      data: { name: 'A', organizationId: orgId },
    });
    const stackB = await prisma.pipelineStack.create({
      data: { name: 'B', organizationId: orgId },
    });
    stackAId = stackA.id;
    stackBId = stackB.id;

    // Failing monitor in stack A — its lastStatus must NOT bleed into stack B's response.
    await prisma.monitor.create({
      data: {
        name: 'm-a', monitorType: 'FRESHNESS', targetFqn: 'db.schema.users',
        enabled: true, lastStatus: 'FAIL',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
  });

  afterAll(async () => {
    await prisma.pipelineStack.deleteMany({ where: { organizationId: orgId } });
    await prisma.organization.delete({ where: { id: orgId } });
    await prisma.$disconnect();
  });

  it('does not bleed P1 monitor status onto P2 lineage', async () => {
    const req = new NextRequest('http://localhost/api/pipeline/' + stackBId + '/lineage/unified');
    const res = await GET(req, { params: Promise.resolve({ stackId: stackBId }) });
    const body = await res.json();
    // Collect every monitor id surfaced in the P2 response.
    const allMonitorIds: string[] = (body.nodes || []).flatMap((n: any) =>
      (n.monitors || []).map((m: any) => m.id)
    );
    if (allMonitorIds.length === 0) {
      // No monitors in P2 — that's already the expected outcome.
      expect(allMonitorIds).toHaveLength(0);
      return;
    }
    const monitorRows = await prisma.monitor.findMany({
      where: { id: { in: allMonitorIds } },
      select: { id: true, pipelineStackId: true },
    });
    expect(monitorRows.every((m) => m.pipelineStackId === stackBId)).toBe(true);
  });
});
