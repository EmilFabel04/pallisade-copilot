import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { computeNextRun } from '@/lib/cron';

// GET /api/schedule/bundles - List all monitor bundles
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
      where: { organizationId },
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

    const bundles = groups.map((g) => {
      const monitors = g.monitors || [];
      return {
        id: g.id,
        name: g.name,
        description: g.description,
        groupType: g.groupType,
        anchorFqn: g.anchorFqn,
        anchorNodeId: g.anchorNodeId,
        enabled: g.enabled,
        schedule: g.schedule,
        timezone: g.timezone,
        alertChannels: g.alertChannels,
        alertOnStatus: g.alertOnStatus,
        lastStatus: g.lastStatus,
        lastRunAt: g.lastRunAt?.toISOString() ?? null,
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

    return NextResponse.json({ bundles });
  } catch (error: any) {
    console.error('[Bundles] List error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// POST /api/schedule/bundles - Create a new monitor bundle
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const userId = (session.user as any).id;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const {
      name,
      description,
      groupType,
      anchorFqn,
      anchorNodeId,
      schedule,
      timezone = 'UTC',
      alertChannels = [],
      alertOnStatus = ['FAIL', 'WARN', 'ERROR'],
      integrationId,
      monitors = [],
    } = body;

    if (!name) {
      return NextResponse.json({ error: 'name is required' }, { status: 400 });
    }
    if (!monitors.length) {
      return NextResponse.json({ error: 'At least one monitor is required' }, { status: 400 });
    }

    // Resolve integrationId — validate it's a real Integration FK for warehouse monitors
    const TOOL_MONITOR_KINDS = [
      'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
      'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
      'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
    ];
    const INFRA_MONITOR_KINDS = ['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS'];

    let validIntegrationId: string | undefined;
    if (integrationId) {
      const integration = await prisma.integration.findUnique({
        where: { id: integrationId },
        select: { id: true },
      });
      if (integration) {
        validIntegrationId = integrationId;
      }
    }

    const nextRunAt = schedule ? computeNextRun(schedule, timezone) : undefined;

    // Create group + monitors in a transaction
    const result = await prisma.$transaction(async (tx) => {
      const group = await tx.monitorGroup.create({
        data: {
          name,
          description,
          groupType: groupType || 'custom',
          anchorFqn: anchorFqn || null,
          anchorNodeId: anchorNodeId || null,
          enabled: true,
          schedule: schedule || null,
          timezone,
          alertChannels,
          alertOnStatus,
          organizationId,
          createdBy: userId,
        },
      });

      const createdMonitors = [];

      for (const mon of monitors) {
        // Check if a matching monitor already exists (same org + targetFqn + monitorType)
        const existing = mon.targetFqn && mon.monitorType
          ? await tx.monitor.findFirst({
              where: {
                organizationId,
                targetFqn: mon.targetFqn,
                monitorType: mon.monitorType,
              },
            })
          : null;

        if (existing) {
          // Link existing monitor to this group
          const updated = await tx.monitor.update({
            where: { id: existing.id },
            data: { monitorGroupId: group.id },
          });
          createdMonitors.push(updated);
        } else {
          // Build config for this monitor
          const isToolMonitor = TOOL_MONITOR_KINDS.includes(mon.monitorType);
          const isInfraMonitor = INFRA_MONITOR_KINDS.includes(mon.monitorType);
          let taskConfig = mon.config || {};

          if (isInfraMonitor && integrationId) {
            taskConfig = { ...taskConfig, serverNodeId: integrationId };
          } else if (isToolMonitor && integrationId) {
            taskConfig = { ...taskConfig, toolNodeId: integrationId };
          } else if (!validIntegrationId && integrationId) {
            taskConfig = { ...taskConfig, nodeId: integrationId };
          }

          const created = await tx.monitor.create({
            data: {
              name: mon.name || `${mon.monitorType} — ${mon.targetFqn}`,
              taskMode: 'structured',
              monitorType: mon.monitorType || null,
              targetFqn: mon.targetFqn || null,
              config: Object.keys(taskConfig).length > 0 ? taskConfig : undefined,
              schedule: schedule || null,
              timezone,
              enabled: true,
              alertChannels,
              alertOnStatus,
              nextRunAt,
              createdBy: userId,
              source: 'pallisade',
              organizationId,
              monitorGroupId: group.id,
              ...(validIntegrationId && !isToolMonitor && !isInfraMonitor
                ? { integrationId: validIntegrationId }
                : {}),
            },
          });
          createdMonitors.push(created);
        }
      }

      return { group, monitors: createdMonitors };
    });

    return NextResponse.json(
      {
        bundle: {
          id: result.group.id,
          name: result.group.name,
          groupType: result.group.groupType,
          monitorCount: result.monitors.length,
          monitors: result.monitors.map((m) => ({
            id: m.id,
            name: m.name,
            monitorType: m.monitorType,
            targetFqn: m.targetFqn,
          })),
        },
      },
      { status: 201 },
    );
  } catch (error: any) {
    console.error('[Bundles] Create error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
