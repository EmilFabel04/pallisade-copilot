import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { aggregate } from './aggregate';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  const monitors = await prisma.monitor.findMany({
    where: { organizationId, pipelineStackId: stackId, enabled: true },
    select: { monitorType: true, targetFqn: true, lastStatus: true, lastRunAt: true },
  });

  return NextResponse.json(aggregate(monitors));
}
