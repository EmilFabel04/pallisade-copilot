import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { computeNextRun } from '@/lib/cron';
import { notifyEvents } from '@/lib/notifications';

// GET /api/schedule/watches/[watchId] - Get watch detail
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { watchId } = await params;
    const organizationId = (session.user as any).organizationId;

    const group = await prisma.monitorGroup.findFirst({
      where: { id: watchId, organizationId, watchType: { not: null } },
      include: {
        monitors: {
          include: {
            runs: {
              orderBy: { startedAt: 'desc' },
              take: 1,
            },
          },
        },
      },
    });

    if (!group) {
      return NextResponse.json({ error: 'Watch not found' }, { status: 404 });
    }

    const monitors = group.monitors.map((m) => {
      const lastRun = m.runs[0] || null;
      return {
        id: m.id,
        name: m.name,
        monitorType: m.monitorType,
        targetFqn: m.targetFqn,
        enabled: m.enabled,
        lastStatus: m.lastStatus,
        lastRunAt: m.lastRunAt?.toISOString() ?? null,
        schedule: m.schedule,
        config: m.config,
        policyOverrides: (m as any).policyOverrides || [],
        lastRun: lastRun
          ? {
              id: lastRun.id,
              status: lastRun.status,
              value: lastRun.value,
              message: lastRun.message,
              startedAt: lastRun.startedAt.toISOString(),
              completedAt: lastRun.completedAt?.toISOString() ?? null,
              durationMs: lastRun.durationMs,
            }
          : null,
      };
    });

    // Resolve policies for all monitor targets (bulk, deduplicated)
    const uniqueFqns = [
      ...new Set(
        group.monitors
          .map((m) => m.targetFqn)
          .filter(Boolean) as string[]
      ),
    ];

    let resolvedPolicies: Record<string, any> = {};
    if (uniqueFqns.length > 0) {
      try {
        const baseUrl = request.nextUrl?.origin || process.env.NEXTAUTH_URL || 'http://localhost:3000';
        const cookie = request.headers.get('cookie') || '';
        const policyRes = await fetch(`${baseUrl}/api/schedule/policies/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', cookie },
          body: JSON.stringify({
            nodes: uniqueFqns.map((fqn) => ({
              fqn,
              domain: 'warehouse',
              criticality: 'medium',
            })),
          }),
        });
        if (policyRes.ok) {
          const data = await policyRes.json();
          resolvedPolicies = data.policies || {};
        }
      } catch (err) {
        console.warn('[Watch] Policy resolution failed (non-fatal):', err);
      }
    }

    // Attach resolved policy to each monitor
    const monitorsWithPolicy = monitors.map((m) => ({
      ...m,
      resolvedPolicy: m.targetFqn ? resolvedPolicies[m.targetFqn] || null : null,
    }));

    return NextResponse.json({
      watch: {
        id: group.id,
        name: group.name,
        description: group.description,
        watchType: group.watchType,
        groupType: group.groupType,
        anchorFqn: group.anchorFqn,
        anchorNodeId: group.anchorNodeId,
        anchorNodeType: group.anchorNodeType,
        anchorPlatform: group.anchorPlatform,
        scopeConfig: group.scopeConfig,
        enabled: group.enabled,
        schedule: group.schedule,
        timezone: group.timezone,
        alertChannels: group.alertChannels,
        alertOnStatus: group.alertOnStatus,
        lastStatus: group.lastStatus,
        lastRunAt: group.lastRunAt?.toISOString() ?? null,
        healthScore: group.healthScore,
        healthDetails: group.healthDetails,
        coveragePct: group.coveragePct,
        lastHealthAt: group.lastHealthAt?.toISOString() ?? null,
        createdAt: group.createdAt.toISOString(),
        monitorCount: monitorsWithPolicy.length,
        passCount: monitorsWithPolicy.filter((m) => m.lastStatus === 'PASS').length,
        failCount: monitorsWithPolicy.filter((m) => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR').length,
        warnCount: monitorsWithPolicy.filter((m) => m.lastStatus === 'WARN').length,
        monitors: monitorsWithPolicy,
      },
    });
  } catch (error: any) {
    console.error('[Watches] Get detail error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PATCH /api/schedule/watches/[watchId] - Update watch
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { watchId } = await params;
    const organizationId = (session.user as any).organizationId;

    const group = await prisma.monitorGroup.findFirst({
      where: { id: watchId, organizationId, watchType: { not: null } },
    });
    if (!group) {
      return NextResponse.json({ error: 'Watch not found' }, { status: 404 });
    }

    const body = await request.json();
    const {
      name,
      description,
      enabled,
      schedule,
      timezone,
      alertChannels,
      alertOnStatus,
      scopeConfig,
      removeMonitorIds,
    } = body;

    const updateData: any = {};
    if (name !== undefined) updateData.name = name;
    if (description !== undefined) updateData.description = description;
    if (enabled !== undefined) updateData.enabled = enabled;
    if (schedule !== undefined) updateData.schedule = schedule;
    if (timezone !== undefined) updateData.timezone = timezone;
    if (alertChannels !== undefined) updateData.alertChannels = alertChannels;
    if (alertOnStatus !== undefined) updateData.alertOnStatus = alertOnStatus;
    if (scopeConfig !== undefined) updateData.scopeConfig = scopeConfig;

    // Propagate schedule/alert changes to member monitors
    const monitorUpdate: any = {};
    if (schedule !== undefined) {
      monitorUpdate.schedule = schedule;
      monitorUpdate.nextRunAt = schedule
        ? computeNextRun(schedule, timezone || group.timezone || 'UTC')
        : null;
    }
    if (timezone !== undefined) monitorUpdate.timezone = timezone;
    if (enabled !== undefined) monitorUpdate.enabled = enabled;
    if (alertChannels !== undefined) monitorUpdate.alertChannels = alertChannels;
    if (alertOnStatus !== undefined) monitorUpdate.alertOnStatus = alertOnStatus;

    await prisma.$transaction(async (tx) => {
      // Remove monitors from this watch if requested
      if (removeMonitorIds && Array.isArray(removeMonitorIds) && removeMonitorIds.length > 0) {
        // Delete runs first, then the monitors themselves
        await tx.monitorRun.deleteMany({
          where: { monitorId: { in: removeMonitorIds } },
        });
        await tx.monitorBaseline.deleteMany({
          where: { monitorId: { in: removeMonitorIds } },
        });
        await tx.monitor.deleteMany({
          where: { id: { in: removeMonitorIds }, monitorGroupId: watchId },
        });
      }

      await tx.monitorGroup.update({
        where: { id: watchId },
        data: updateData,
      });

      if (Object.keys(monitorUpdate).length > 0) {
        await tx.monitor.updateMany({
          where: { monitorGroupId: watchId },
          data: monitorUpdate,
        });
      }
    }, { maxWait: 10000, timeout: 30000 });

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('[Watches] Update error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// DELETE /api/schedule/watches/[watchId] - Delete watch and its monitors
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { watchId } = await params;
    const organizationId = (session.user as any).organizationId;

    const group = await prisma.monitorGroup.findFirst({
      where: { id: watchId, organizationId, watchType: { not: null } },
      include: { monitors: { select: { id: true } } },
    });
    if (!group) {
      return NextResponse.json({ error: 'Watch not found' }, { status: 404 });
    }

    await prisma.$transaction(async (tx) => {
      const monitorIds = group.monitors.map((m) => m.id);
      if (monitorIds.length > 0) {
        await tx.monitorRun.deleteMany({
          where: { monitorId: { in: monitorIds } },
        });
        await tx.monitorBaseline.deleteMany({
          where: { monitorId: { in: monitorIds } },
        });
        await tx.monitor.deleteMany({
          where: { id: { in: monitorIds } },
        });
      }
      await tx.monitorGroup.delete({
        where: { id: watchId },
      });
    }, { maxWait: 10000, timeout: 30000 });

    // Fire-and-forget notification
    notifyEvents.monitorGroupDeleted(
      group.organizationId,
      undefined,
      (session.user as any).id ?? undefined, // actorUserId from session
      group.name,
      watchId,
    ).catch(() => {});

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('[Watches] Delete error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
