import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const orgId = (session.user as any).organizationId;
  if (!orgId) {
    return NextResponse.json({ error: 'No organization found' }, { status: 400 });
  }

  const anchorFqn = req.nextUrl.searchParams.get('anchorFqn');
  if (!anchorFqn) {
    return NextResponse.json({ error: 'anchorFqn is required' }, { status: 400 });
  }

  // Return any existing monitor group for this anchor so new asset-level
  // monitors (e.g. DATA_TYPE_VALIDATION) merge into the same group rather than
  // spawning a separate custom_watch. Standalone groups are preferred when
  // both a standalone and a plan-backed group exist for the same anchor.
  const groups = await prisma.monitorGroup.findMany({
    where: {
      organizationId: orgId,
      anchorFqn,
    },
    include: {
      monitors: {
        select: {
          id: true,
          name: true,
          monitorType: true,
          enabled: true,
          lastStatus: true,
          lastRunAt: true,
          config: true,
        },
        orderBy: { createdAt: 'asc' },
      },
    },
    orderBy: { createdAt: 'asc' },
  });

  const group =
    groups.find((g) => g.monitoringPlanId === null) ?? groups[0] ?? null;

  return NextResponse.json({ group });
}
