import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/schedule/plans/[planId] - Get a single monitoring plan
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { planId } = await params;

    const plan = await prisma.monitoringPlan.findFirst({
      where: { id: planId, organizationId },
      include: {
        monitorGroups: {
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
        },
      },
    });

    if (!plan) {
      return NextResponse.json({ error: 'Plan not found' }, { status: 404 });
    }

    // Compute fresh aggregate from child groups
    const groups = plan.monitorGroups || [];
    let totalMonitors = 0;
    let weightedHealth = 0;
    let weightedCoverage = 0;
    let passCount = 0;
    let warnCount = 0;
    let failCount = 0;
    let errorCount = 0;
    let lowestHealthGroup: string | null = null;
    let lowestHealthScore = Infinity;
    const allFailureGroups: any[] = [];

    for (const group of groups) {
      const monCount = group.monitors?.length || 0;
      totalMonitors += monCount;
      const healthScore = (group as any).healthScore ?? 100;
      const coveragePct = (group as any).coveragePct ?? 0;
      weightedHealth += healthScore * monCount;
      weightedCoverage += coveragePct * monCount;

      for (const m of group.monitors || []) {
        if (m.lastStatus === 'PASS') passCount++;
        else if (m.lastStatus === 'WARN') warnCount++;
        else if (m.lastStatus === 'FAIL') failCount++;
        else if (m.lastStatus === 'ERROR') errorCount++;
      }

      if (healthScore < lowestHealthScore) {
        lowestHealthScore = healthScore;
        lowestHealthGroup = group.name;
      }

      const details = (group as any).healthDetails;
      if (details?.failureGroups) {
        allFailureGroups.push(...details.failureGroups);
      }
    }

    const aggregate = {
      healthScore: totalMonitors > 0 ? Math.round(weightedHealth / totalMonitors * 10) / 10 : 100,
      coveragePct: totalMonitors > 0 ? Math.round(weightedCoverage / totalMonitors * 1000) / 1000 : 0,
      totalMonitors,
      passCount,
      warnCount,
      failCount,
      errorCount,
      lowestHealthGroup,
      topFailureGroups: allFailureGroups
        .sort((a, b) => (b.signalCount || 0) - (a.signalCount || 0))
        .slice(0, 3),
    };

    return NextResponse.json({ plan, aggregate });
  } catch (error: any) {
    console.error('[Plans] Get error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PATCH /api/schedule/plans/[planId] - Update plan (schedule propagates to children)
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { planId } = await params;
    const body = await request.json();

    const existing = await prisma.monitoringPlan.findFirst({
      where: { id: planId, organizationId },
    });
    if (!existing) {
      return NextResponse.json({ error: 'Plan not found' }, { status: 404 });
    }

    const {
      name,
      description,
      schedule,
      timezone,
      enabled,
      alertChannels,
      alertOnStatus,
    } = body;

    const result = await prisma.$transaction(async (tx) => {
      const updated = await tx.monitoringPlan.update({
        where: { id: planId },
        data: {
          ...(name !== undefined && { name }),
          ...(description !== undefined && { description }),
          ...(schedule !== undefined && { schedule }),
          ...(timezone !== undefined && { timezone }),
          ...(enabled !== undefined && { enabled }),
          ...(alertChannels !== undefined && { alertChannels }),
          ...(alertOnStatus !== undefined && { alertOnStatus }),
        },
      });

      // Propagate schedule/alerts to all child groups
      const propagateData: Record<string, any> = {};
      if (schedule !== undefined) propagateData.schedule = schedule;
      if (timezone !== undefined) propagateData.timezone = timezone;
      if (enabled !== undefined) propagateData.enabled = enabled;
      if (alertChannels !== undefined) propagateData.alertChannels = alertChannels;
      if (alertOnStatus !== undefined) propagateData.alertOnStatus = alertOnStatus;

      if (Object.keys(propagateData).length > 0) {
        await tx.monitorGroup.updateMany({
          where: { monitoringPlanId: planId },
          data: propagateData,
        });

        // Also propagate schedule to individual monitors
        if (schedule !== undefined || timezone !== undefined || enabled !== undefined) {
          const monitorData: Record<string, any> = {};
          if (schedule !== undefined) monitorData.schedule = schedule;
          if (timezone !== undefined) monitorData.timezone = timezone;
          if (enabled !== undefined) monitorData.enabled = enabled;

          const childGroups = await tx.monitorGroup.findMany({
            where: { monitoringPlanId: planId },
            select: { id: true },
          });
          const groupIds = childGroups.map((g) => g.id);

          if (groupIds.length > 0) {
            await tx.monitor.updateMany({
              where: { monitorGroupId: { in: groupIds } },
              data: monitorData,
            });
          }
        }
      }

      return updated;
    });

    return NextResponse.json({ plan: result });
  } catch (error: any) {
    console.error('[Plans] Update error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// DELETE /api/schedule/plans/[planId] - Delete plan (groups become standalone)
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { planId } = await params;

    const existing = await prisma.monitoringPlan.findFirst({
      where: { id: planId, organizationId },
    });
    if (!existing) {
      return NextResponse.json({ error: 'Plan not found' }, { status: 404 });
    }

    // Delete child monitors, then groups, then the plan
    await prisma.$transaction(async (tx) => {
      const childGroups = await tx.monitorGroup.findMany({
        where: { monitoringPlanId: planId },
        select: { id: true },
      });
      const groupIds = childGroups.map((g) => g.id);

      if (groupIds.length > 0) {
        await tx.monitor.deleteMany({
          where: { monitorGroupId: { in: groupIds } },
        });
        await tx.monitorGroup.deleteMany({
          where: { id: { in: groupIds } },
        });
      }

      await tx.monitoringPlan.delete({
        where: { id: planId },
      });
    });

    return NextResponse.json({ deleted: true });
  } catch (error: any) {
    console.error('[Plans] Delete error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
