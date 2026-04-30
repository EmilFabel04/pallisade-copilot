/**
 * Shared watch creation helper.
 *
 * Extracted from app/api/schedule/watches/route.ts so that both
 * single-watch creation and preset batch creation can reuse the same logic.
 */

import prisma from '@/lib/db';
import { computeNextRun } from '@/lib/cron';

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

export interface CreateWatchParams {
  name: string;
  description?: string;
  watchType: string;
  anchorFqn?: string;
  anchorNodeId?: string;
  anchorNodeType?: string;
  anchorPlatform?: string;
  scopeConfig?: any;
  schedule?: string;
  timezone?: string;
  alertChannels?: string[];
  alertOnStatus?: string[];
  alertConfig?: Record<string, any> | null;
  integrationId?: string;
  monitoringPlanId?: string;
  presetGroupId?: string;
  presetKey?: string;
  monitors: Array<{
    name?: string;
    monitorType: string;
    targetFqn: string;
    config?: Record<string, any>;
    depth?: number;
    priority?: number;
    alertChannels?: string[];
    alertOnStatus?: string[];
    alertConfig?: Record<string, any> | null;
  }>;
  organizationId: string;
  pipelineStackId: string;
  userId: string;
}

export interface CreateWatchResult {
  group: any;
  monitors: any[];
}

/**
 * Create a single watch (MonitorGroup + linked Monitors) inside a Prisma transaction.
 * Can be called standalone or as part of a batch transaction.
 */
export async function createWatchInTransaction(
  tx: any,
  params: CreateWatchParams,
): Promise<CreateWatchResult> {
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
    alertConfig,
    integrationId,
    monitoringPlanId,
    presetGroupId,
    presetKey,
    monitors,
    organizationId,
    pipelineStackId,
    userId,
  } = params;

  // Validate integrationId if provided
  let validIntegrationId: string | undefined;
  if (integrationId) {
    const integration = await tx.integration.findUnique({
      where: { id: integrationId },
      select: { id: true },
    });
    if (integration) {
      validIntegrationId = integrationId;
    }
  }

  const nextRunAt = schedule ? computeNextRun(schedule, timezone) : undefined;

  // Dedup: groups are per-asset (per anchorFqn) regardless of plan
  // affiliation. If a group already exists for this asset, attach the new
  // monitors to it instead of creating a duplicate. The previous logic
  // scoped dedup by monitoringPlanId, which meant every new plan creation
  // produced a fresh group for assets that already had one.
  let group = anchorFqn
    ? await tx.monitorGroup.findFirst({
        where: {
          organizationId,
          pipelineStackId,
          anchorFqn,
        },
        orderBy: { createdAt: 'asc' },  // prefer the oldest existing group
      })
    : null;

  if (!group) {
    group = await tx.monitorGroup.create({
      data: {
        name,
        description: description || null,
        groupType: watchType,
        watchType,
        anchorFqn: anchorFqn || null,
        anchorNodeId: anchorNodeId || null,
        anchorNodeType: anchorNodeType || null,
        anchorPlatform: anchorPlatform || null,
        scopeConfig: scopeConfig || null,
        monitoringPlanId: monitoringPlanId || null,
        presetGroupId: presetGroupId || null,
        presetKey: presetKey || null,
        enabled: true,
        schedule: schedule || null,
        timezone,
        alertChannels,
        alertOnStatus,
        alertConfig: alertConfig ?? undefined,
        organizationId,
        pipelineStackId,
        createdBy: userId,
      },
    });
  } else if (!group.enabled) {
    // Reusing an existing group that was disabled in the past. The user is
    // actively adding new monitors → re-enable so the group's toggle reflects
    // intent. Without this the new monitors land in a group that still
    // shows as off.
    group = await tx.monitorGroup.update({
      where: { id: group.id },
      data: { enabled: true },
    });
  }

  const createdMonitors = [];

  // Batch dedup: fetch all existing monitors that match any (targetFqn, monitorType) pair
  const dedupPairs = monitors
    .filter((m) => m.targetFqn && m.monitorType)
    .map((m) => ({ targetFqn: m.targetFqn, monitorType: m.monitorType }));
  const existingMonitors = dedupPairs.length > 0
    ? await tx.monitor.findMany({
        where: {
          organizationId,
          pipelineStackId,
          OR: dedupPairs.map((p) => ({
            targetFqn: p.targetFqn,
            monitorType: p.monitorType,
          })),
        },
      })
    : [];
  const existingMap = new Map<string, any>();
  for (const em of existingMonitors) {
    existingMap.set(`${em.targetFqn}::${em.monitorType}`, em);
  }

  for (let idx = 0; idx < monitors.length; idx++) {
    const mon = monitors[idx];
    const isAnchor = mon.targetFqn === anchorFqn;
    const depth = mon.depth ?? (isAnchor ? 0 : 1);
    const priority = mon.priority ?? (isAnchor ? 1 : 2);

    // Dedup: check if matching monitor already exists (from batch lookup)
    const existing = (mon.targetFqn && mon.monitorType)
      ? existingMap.get(`${mon.targetFqn}::${mon.monitorType}`) || null
      : null;

    if (existing) {
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
      let taskConfig: Record<string, any> = {
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
            taskMode: mon.monitorType === 'AI_PROMPT' ? 'prompt' : 'structured',
            prompt: mon.monitorType === 'AI_PROMPT' ? (mon.config?.prompt || null) : null,
            monitorType: mon.monitorType || null,
            targetFqn: mon.targetFqn || null,
            config: Object.keys(taskConfig).length > 0 ? taskConfig : undefined,
            schedule: schedule || null,
            timezone,
            enabled: true,
            alertChannels: mon.alertChannels ?? alertChannels,
            alertOnStatus: mon.alertOnStatus ?? alertOnStatus,
            alertConfig: (mon.alertConfig ?? alertConfig) ?? undefined,
            nextRunAt,
            createdBy: userId,
            source: 'pallisade',
            organizationId,
            pipelineStackId,
            monitorGroupId: group.id,
            ...(validIntegrationId && !isToolMonitor && !isInfraMonitor && !isBIMonitor
              ? { integrationId: validIntegrationId }
              : {}),
          },
        });
        createdMonitors.push(created);
      } catch (createErr: any) {
        if (createErr?.code === 'P2002' && mon.targetFqn && mon.monitorType) {
          const dup = await tx.monitor.findFirst({
            where: { organizationId, pipelineStackId, targetFqn: mon.targetFqn, monitorType: mon.monitorType },
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
}
