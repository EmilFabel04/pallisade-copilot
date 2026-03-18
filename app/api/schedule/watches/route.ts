import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/schedule/watches - List all group monitors
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const groups = await prisma.monitorGroup.findMany({
      where: {
        organizationId,
        watchType: { not: null },
        monitoringPlanId: null, // Exclude groups that belong to a plan
      },
      orderBy: { createdAt: 'desc' },
      include: {
        monitors: {
          select: {
            id: true,
            name: true,
            monitorType: true,
            targetFqn: true,
            enabled: true,
            lastStatus: true,
            lastRunAt: true,
            schedule: true,
          },
        },
      },
    });

    const watches = groups.map((g) => {
      const monitors = g.monitors || [];
      return {
        id: g.id,
        name: g.name,
        description: g.description,
        watchType: g.watchType,
        groupType: g.groupType,
        anchorFqn: g.anchorFqn,
        anchorNodeId: g.anchorNodeId,
        anchorNodeType: g.anchorNodeType,
        anchorPlatform: g.anchorPlatform,
        scopeConfig: g.scopeConfig,
        presetGroupId: (g as any).presetGroupId || null,
        presetKey: (g as any).presetKey || null,
        enabled: g.enabled,
        schedule: g.schedule,
        timezone: g.timezone,
        alertChannels: g.alertChannels,
        alertOnStatus: g.alertOnStatus,
        lastStatus: g.lastStatus,
        lastRunAt: g.lastRunAt?.toISOString() ?? null,
        healthScore: g.healthScore,
        healthDetails: g.healthDetails,
        coveragePct: g.coveragePct,
        lastHealthAt: g.lastHealthAt?.toISOString() ?? null,
        createdAt: g.createdAt.toISOString(),
        monitorCount: monitors.length,
        passCount: monitors.filter((m) => m.lastStatus === 'PASS').length,
        failCount: monitors.filter((m) => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR').length,
        warnCount: monitors.filter((m) => m.lastStatus === 'WARN').length,
        monitors: monitors.map((m) => ({
          id: m.id,
          name: m.name,
          monitorType: m.monitorType,
          targetFqn: m.targetFqn,
          enabled: m.enabled,
          lastStatus: m.lastStatus,
          lastRunAt: m.lastRunAt?.toISOString() ?? null,
          schedule: m.schedule,
        })),
      };
    });

    return NextResponse.json({ watches });
  } catch (error: any) {
    console.error('[Watches] List error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
