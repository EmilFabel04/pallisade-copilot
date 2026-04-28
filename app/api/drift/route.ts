import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const stackId = searchParams.get('stackId');
    if (!stackId) {
      return NextResponse.json(
        { error: 'stackId query parameter is required' },
        { status: 400 }
      );
    }
    const status = searchParams.get('status');
    const category = searchParams.get('category');
    const runId = searchParams.get('runId');

    const where: any = { organizationId, pipelineStackId: stackId };
    if (status) where.status = status;
    if (category) where.driftCategory = category;
    if (runId) where.runId = runId;

    const recommendations = await prisma.driftRecommendation.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      include: {
        monitor: {
          select: { id: true, name: true, monitorType: true, targetFqn: true, enabled: true },
        },
      },
    });

    const latestRun = await prisma.driftRecommendation.findFirst({
      where: { organizationId, pipelineStackId: stackId },
      orderBy: { createdAt: 'desc' },
      select: { runId: true, createdAt: true },
    });

    const counts = await prisma.driftRecommendation.groupBy({
      by: ['status'],
      where: { organizationId, pipelineStackId: stackId, runId: latestRun?.runId || '' },
      _count: true,
    });

    const statusCounts: Record<string, number> = {};
    for (const c of counts) {
      statusCounts[c.status] = c._count;
    }

    return NextResponse.json({
      recommendations,
      latestRunId: latestRun?.runId || null,
      lastAnalyzedAt: latestRun?.createdAt || null,
      counts: statusCounts,
    });
  } catch (error: any) {
    console.error('[Drift] List error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
