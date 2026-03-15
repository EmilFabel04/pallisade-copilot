import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { computeNextRun } from '@/lib/cron';

const VALID_WATCH_TYPES = [
  'pipeline_health',
  'dashboard_shield',
  'source_guard',
  'model_quality',
  'data_drift',
  'custom_watch',
];

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

// POST /api/schedule/watches - Create a new group monitor
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
      watchType,
      anchorFqn,
      anchorNodeId,
      anchorNodeType,
      anchorPlatform,
      scopeConfig,
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
    if (!watchType || !VALID_WATCH_TYPES.includes(watchType)) {
      return NextResponse.json(
        { error: `watchType must be one of: ${VALID_WATCH_TYPES.join(', ')}` },
        { status: 400 },
      );
    }
    if (!monitors.length) {
      return NextResponse.json({ error: 'At least one monitor is required' }, { status: 400 });
    }

    // Validate integrationId if provided
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

    const TOOL_MONITOR_KINDS = [
      'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
      'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
      'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
    ];
    const BI_MONITOR_KINDS = [
      'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK',
      'BI_CONTENT_HEALTH', 'BI_REFRESH_FAILURE',
    ];
    const INFRA_MONITOR_KINDS = ['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS'];

    const result = await prisma.$transaction(async (tx) => {
      const group = await tx.monitorGroup.create({
        data: {
          name,
          description,
          groupType: watchType,
          watchType,
          anchorFqn: anchorFqn || null,
          anchorNodeId: anchorNodeId || null,
          anchorNodeType: anchorNodeType || null,
          anchorPlatform: anchorPlatform || null,
          scopeConfig: scopeConfig || null,
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

      for (let idx = 0; idx < monitors.length; idx++) {
        const mon = monitors[idx];
        const isAnchor = mon.targetFqn === anchorFqn;
        const depth = mon.depth ?? (isAnchor ? 0 : 1);
        const priority = mon.priority ?? (isAnchor ? 1 : 2);

        // Dedup: check if matching monitor already exists (by unique constraint fields)
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
          const existingConfig = (existing.config as any) || {};
          const updated = await tx.monitor.update({
            where: { id: existing.id },
            data: {
              monitorGroupId: group.id,
              config: { ...existingConfig, _watchDepth: depth, _watchPriority: priority },
            },
          });
          createdMonitors.push(updated);
        } else {
          const isToolMonitor = TOOL_MONITOR_KINDS.includes(mon.monitorType);
          const isBIMonitor = BI_MONITOR_KINDS.includes(mon.monitorType);
          const isInfraMonitor = INFRA_MONITOR_KINDS.includes(mon.monitorType);
          let taskConfig = {
            ...(mon.config || {}),
            _watchDepth: depth,
            _watchPriority: priority,
          };

          if (isInfraMonitor && integrationId) {
            taskConfig = { ...taskConfig, serverNodeId: integrationId };
          } else if (isToolMonitor && integrationId) {
            taskConfig = { ...taskConfig, toolNodeId: integrationId };
          } else if (isBIMonitor && integrationId) {
            taskConfig = { ...taskConfig, biNodeId: integrationId };
          } else if (!validIntegrationId && integrationId) {
            taskConfig = { ...taskConfig, nodeId: integrationId };
          }

          try {
            const created = await tx.monitor.create({
              data: {
                name: mon.name || `${mon.monitorType} — ${mon.targetFqn || 'monitor'}`,
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
                ...(validIntegrationId && !isToolMonitor && !isInfraMonitor && !isBIMonitor
                  ? { integrationId: validIntegrationId }
                  : {}),
              },
            });
            createdMonitors.push(created);
          } catch (createErr: any) {
            // Unique constraint violation — link existing monitor instead
            if (createErr?.code === 'P2002' && mon.targetFqn && mon.monitorType) {
              const dup = await tx.monitor.findFirst({
                where: { organizationId, targetFqn: mon.targetFqn, monitorType: mon.monitorType },
              });
              if (dup) {
                const updated = await tx.monitor.update({
                  where: { id: dup.id },
                  data: { monitorGroupId: group.id },
                });
                createdMonitors.push(updated);
              }
            } else {
              throw createErr;
            }
          }
        }
      }

      return { group, monitors: createdMonitors };
    }, { maxWait: 10000, timeout: 30000 });

    return NextResponse.json(
      {
        watch: {
          id: result.group.id,
          name: result.group.name,
          watchType: result.group.watchType,
          anchorFqn: result.group.anchorFqn,
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
    console.error('[Watches] Create error:', error?.message || error, error?.stack);
    return NextResponse.json({ error: error?.message || String(error) }, { status: 500 });
  }
}
