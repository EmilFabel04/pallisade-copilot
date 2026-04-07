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

  const group = await prisma.monitorGroup.findFirst({
    where: {
      organizationId: orgId,
      anchorFqn,
      monitoringPlanId: null, // standalone groups only
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
  });

  return NextResponse.json({ group: group || null });
}
