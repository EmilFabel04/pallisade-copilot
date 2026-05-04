import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  // Find LineageNodes flagged as having downstream dashboards but no monitors targeting their FQN.
  // For v1 we use a simple proxy: pick LineageNodes whose `criticality` is 'HIGH' or 'CRITICAL',
  // intersected with the absence of a Monitor row sharing the same targetFqn.
  // Note: LineageNode.name stores the fully-qualified name (database.schema.table).
  const monitoredFqns = new Set(
    (await prisma.monitor.findMany({
      where: { organizationId, pipelineStackId: stackId },
      select: { targetFqn: true },
    })).map((m) => m.targetFqn).filter((x): x is string => !!x)
  );

  const criticalNodes = await prisma.lineageNode.findMany({
    where: {
      organizationId,
      pipelineStackId: stackId,
      criticality: { in: ['HIGH', 'CRITICAL'] as any },
    },
    select: { name: true, criticality: true, tableName: true },
    take: 50,
  });

  const assets = criticalNodes
    .filter((n) => n.name && !monitoredFqns.has(n.name))
    .map((n) => ({ fqn: n.name, reason: `criticality=${n.criticality ?? 'HIGH'}` }))
    .slice(0, 10);

  return NextResponse.json({ assets });
}
