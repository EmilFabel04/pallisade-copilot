import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const url = new URL(request.url);
  const stackId = url.searchParams.get('stackId');
  const status = url.searchParams.get('status'); // 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'active' (open+ack)
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  const where: any = { organizationId, pipelineStackId: stackId };
  if (status === 'active') where.status = { in: ['OPEN', 'ACKNOWLEDGED'] };
  else if (status) where.status = status;

  const incidents = await prisma.incident.findMany({
    where,
    orderBy: [{ status: 'asc' }, { openedAt: 'desc' }],
    include: {
      monitor: {
        select: { id: true, name: true, monitorType: true, targetFqn: true, lastStatus: true },
      },
    },
  });

  const now = Date.now();
  const result = incidents.map((i) => ({
    id: i.id,
    monitorId: i.monitorId,
    monitorGroupId: i.monitorGroupId,
    monitorType: i.monitor?.monitorType ?? null,
    targetFqn: i.targetFqn,
    status: i.status,
    severity: i.severity,
    openedAt: i.openedAt.toISOString(),
    signature: i.signature,
    consecutiveCount: i.consecutiveCount,
    llmHypothesis: i.llmHypothesis,
    llmHypothesisAt: i.llmHypothesisAt?.toISOString() ?? null,
    ownerSystem: i.ownerSystem,
    ownerConfidence: i.ownerConfidence,
    acknowledgedAt: i.acknowledgedAt?.toISOString() ?? null,
    acknowledgedBy: i.acknowledgedBy,
    resolvedAt: i.resolvedAt?.toISOString() ?? null,
    resolvedBy: i.resolvedBy,
    resolutionType: i.resolutionType,
    resolutionNote: i.resolutionNote,
    mutedUntil: i.mutedUntil?.toISOString() ?? null,
    isMuted: !!(i.mutedUntil && i.mutedUntil.getTime() > now),
    mutedReason: i.mutedReason,
  }));

  return NextResponse.json({ incidents: result });
}
