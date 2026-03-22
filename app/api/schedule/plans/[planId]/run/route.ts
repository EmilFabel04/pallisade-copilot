import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { notifyEvents } from '@/lib/notifications';
import { routeNotification } from '@/lib/notification-router';

// POST /api/schedule/plans/[planId]/run - Trigger run for all monitors in all child groups
export async function POST(
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
          where: { enabled: true },
          include: {
            monitors: {
              where: { enabled: true },
              select: { id: true, name: true },
            },
          },
        },
      },
    });

    if (!plan) {
      return NextResponse.json({ error: 'Plan not found' }, { status: 404 });
    }

    if (!plan.monitorGroups.length) {
      return NextResponse.json(
        { error: 'No enabled monitor groups in this plan' },
        { status: 400 },
      );
    }

    // Fan-out: trigger run for each monitor via the existing
    // per-task run endpoint (handles integration resolution, execution,
    // run persistence, and notifications).
    const baseUrl =
      request.nextUrl.origin || process.env.NEXTAUTH_URL || 'http://localhost:3000';
    const cookie = request.headers.get('cookie') || '';
    const groupResults = [];

    for (const group of plan.monitorGroups) {
      const monitorResults = [];

      // Fire all monitors in the group concurrently
      const promises = group.monitors.map(async (monitor) => {
        try {
          const res = await fetch(
            `${baseUrl}/api/schedule/tasks/${monitor.id}/run?grouped=true`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                cookie,
              },
            },
          );
          const body = await res.json().catch(() => ({}));
          return {
            monitorId: monitor.id,
            monitorName: monitor.name,
            status: res.ok ? (body.result?.status || 'triggered') : 'failed',
            statusCode: res.status,
          };
        } catch (err: any) {
          return {
            monitorId: monitor.id,
            monitorName: monitor.name,
            status: 'error',
            error: err.message,
          };
        }
      });

      const results = await Promise.all(promises);
      monitorResults.push(...results);

      groupResults.push({
        groupId: group.id,
        groupName: group.name,
        monitorsTriggered: results.filter(
          (r) => r.status !== 'failed' && r.status !== 'error',
        ).length,
        monitorsFailed: results.filter(
          (r) => r.status === 'failed' || r.status === 'error',
        ).length,
        monitors: results,
      });
    }

    const totalTriggered = groupResults.reduce(
      (sum, g) => sum + g.monitorsTriggered,
      0,
    );
    const totalFailed = groupResults.reduce(
      (sum, g) => sum + g.monitorsFailed,
      0,
    );

    // Collect all monitor statuses across groups for one collective notification
    const allStatuses = groupResults.flatMap((g) =>
      g.monitors.map((m: any) => (m.status || 'ERROR').toUpperCase()),
    );
    const passCount = allStatuses.filter((s: string) => s === 'PASS').length;
    const failCount = allStatuses.filter((s: string) => s === 'FAIL').length;
    const warnCount = allStatuses.filter((s: string) => s === 'WARN').length;
    const errorCount = allStatuses.filter((s: string) => s === 'ERROR' || s === 'FAILED').length;
    const totalMonitors = allStatuses.length;

    const pipelineStack = await prisma.pipelineStack.findFirst({
      where: { organizationId },
      select: { id: true },
    });

    notifyEvents.monitorGroupCompleted(
      organizationId,
      pipelineStack?.id,
      (session.user as any).id,
      plan.name,
      planId,
      {
        total: totalMonitors,
        pass: passCount,
        fail: failCount,
        warn: warnCount,
        error: errorCount,
      },
    );

    // Route to external platforms based on severity
    const planSeverity =
      totalFailed > 0 ? 'ERROR' as const
      : warnCount > 0 ? 'WARN' as const
      : 'INFO' as const;

    routeNotification({
      organizationId: plan.organizationId,
      severity: planSeverity,
      title: `Plan "${plan.name}": ${totalFailed} failed, ${passCount} passed`,
      message: `${groupResults.length} groups run, ${totalTriggered} monitors total`,
      metadata: { planId, groupsRun: groupResults.length, totalTriggered, totalFailed, totalPassed: passCount },
      actionUrl: `/dashboard/schedule?plan=${planId}`,
    }).catch(() => {});

    return NextResponse.json({
      planId: plan.id,
      groupsRun: groupResults.length,
      totalTriggered,
      totalFailed,
      groups: groupResults,
    });
  } catch (error: any) {
    console.error('[Plans] Run error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
