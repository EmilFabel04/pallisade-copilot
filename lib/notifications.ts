/**
 * Notification Helper
 *
 * Fire-and-forget notification creation, mirroring lib/audit.ts pattern.
 * Never throws — logs errors to console instead.
 *
 * Usage:
 *   import { notify, notifyEvents } from '@/lib/notifications';
 *
 *   await notifyEvents.monitorFailed(orgId, pipelineId, userId, 'Freshness check', taskId, 'Threshold exceeded');
 */

import prisma from '@/lib/db';

export interface NotifyParams {
  organizationId: string;
  pipelineStackId?: string;
  actorUserId?: string;
  eventType: string;
  severity?: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';
  title: string;
  message: string;
  dedupeKey?: string;
  entityType?: string;
  entityId?: string;
  actionUrl?: string;
  metadata?: Record<string, any>;
}

const DEDUPE_WINDOW_MS = 15 * 60 * 1000; // 15 minutes

/**
 * Create a notification event. If dedupeKey is provided, skips creation
 * when an identical event exists within the last 15 minutes.
 */
export async function notify(params: NotifyParams): Promise<void> {
  try {
    // Dedupe check
    if (params.dedupeKey) {
      const cutoff = new Date(Date.now() - DEDUPE_WINDOW_MS);
      const existing = await prisma.notificationEvent.findFirst({
        where: {
          dedupeKey: params.dedupeKey,
          createdAt: { gte: cutoff },
        },
        select: { id: true },
      });
      if (existing) return;
    }

    await prisma.notificationEvent.create({
      data: {
        organizationId: params.organizationId,
        pipelineStackId: params.pipelineStackId || undefined,
        actorUserId: params.actorUserId || undefined,
        eventType: params.eventType,
        severity: params.severity || 'INFO',
        title: params.title,
        message: params.message,
        dedupeKey: params.dedupeKey || undefined,
        entityType: params.entityType || undefined,
        entityId: params.entityId || undefined,
        actionUrl: params.actionUrl || undefined,
        metadata: params.metadata || undefined,
      },
    });
  } catch (error) {
    console.error('Failed to create notification event:', error);
  }
}

/**
 * Convenience helpers for common notification events.
 */
export const notifyEvents = {
  // ── Monitor / Task events ──────────────────────────────────

  monitorFailed: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    taskName: string,
    taskId: string,
    errorMsg: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'monitor.failed',
      severity: 'ERROR',
      title: `Monitor failed: ${taskName}`,
      message: errorMsg.slice(0, 500),
      dedupeKey: `monitor:${taskId}`,
      entityType: 'MONITOR',
      entityId: taskId,
      actionUrl: `/dashboard/schedule?task=${taskId}`,
    }),

  monitorPassed: (
    orgId: string,
    pipelineId: string | undefined,
    taskName: string,
    taskId: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      eventType: 'monitor.passed',
      severity: 'INFO',
      title: `Monitor passed: ${taskName}`,
      message: `${taskName} completed successfully.`,
      entityType: 'MONITOR',
      entityId: taskId,
      actionUrl: `/dashboard/schedule?task=${taskId}`,
    }),

  monitorGroupCompleted: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    groupName: string,
    groupId: string,
    summary: { total: number; pass: number; fail: number; warn: number; error: number },
    health?: { currentHealthScore: number; previousHealthScore: number },
  ) => {
    // Derive severity — CRITICAL when health is unhealthy (<40)
    const severity: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL' =
      health && health.currentHealthScore < 40
        ? 'CRITICAL'
        : summary.fail > 0 || summary.error > 0
          ? 'ERROR'
          : summary.warn > 0
            ? 'WARN'
            : 'INFO';

    const parts: string[] = [];
    if (summary.pass > 0) parts.push(`${summary.pass} passed`);
    if (summary.warn > 0) parts.push(`${summary.warn} warn`);
    if (summary.fail > 0) parts.push(`${summary.fail} fail`);
    if (summary.error > 0) parts.push(`${summary.error} error`);

    return notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'monitor.group_completed',
      severity,
      title: `Multi-monitor ${groupName} ran: ${parts.join(', ')}`,
      message: `${groupName}: ${parts.join(', ')} (${summary.total} monitors)`,
      dedupeKey: `monitor-group:${groupId}`,
      entityType: 'MONITOR',
      entityId: groupId,
      actionUrl: `/dashboard/schedule?group=${groupId}`,
      metadata: { ...summary, ...(health || {}) },
    });
  },

  healthScoreDropped: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    groupName: string,
    groupId: string,
    previousScore: number,
    currentScore: number,
    severity: 'WARN' | 'ERROR' | 'CRITICAL',
  ) => {
    const previousStatus = previousScore >= 90 ? 'healthy' : previousScore >= 70 ? 'degraded' : previousScore >= 40 ? 'at_risk' : 'unhealthy';
    const currentStatus = currentScore >= 90 ? 'healthy' : currentScore >= 70 ? 'degraded' : currentScore >= 40 ? 'at_risk' : 'unhealthy';
    return notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'monitor.health_score_dropped',
      severity,
      title: `${groupName} health dropped: ${previousStatus} → ${currentStatus}`,
      message: `Health score fell from ${previousScore.toFixed(0)} to ${currentScore.toFixed(0)}`,
      dedupeKey: `health-drop:${groupId}`,
      entityType: 'MONITOR',
      entityId: groupId,
      actionUrl: `/dashboard/schedule?group=${groupId}`,
      metadata: { previousScore, currentScore, previousStatus, currentStatus },
    });
  },

  sustainedFailure: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    groupName: string,
    groupId: string,
    monitorName: string,
    monitorId: string,
    consecutiveFailures: number,
    severity: 'WARN' | 'ERROR' | 'CRITICAL',
  ) => {
    return notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'monitor.sustained_failure',
      severity,
      title: `${monitorName} has failed ${consecutiveFailures} times in a row`,
      message: `Monitor "${monitorName}" in ${groupName} has failed ${consecutiveFailures} consecutive runs`,
      dedupeKey: `sustained-fail:${monitorId}`,
      entityType: 'MONITOR',
      entityId: groupId,
      actionUrl: `/dashboard/schedule?group=${groupId}`,
      metadata: { monitorId, monitorName, consecutiveFailures },
    });
  },

  // ── Integration events ─────────────────────────────────────

  integrationCreated: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    name: string,
    type: string,
    integrationId: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'integration.created',
      severity: 'INFO',
      title: `Integration connected: ${name}`,
      message: `${type} integration "${name}" was added.`,
      entityType: 'SOURCE',
      entityId: integrationId,
      actionUrl: `/dashboard/sources?integrationId=${integrationId}`,
      metadata: { type },
    }),

  integrationDeleted: (
    orgId: string,
    actorId: string | undefined,
    name: string,
    integrationId: string,
  ) =>
    notify({
      organizationId: orgId,
      actorUserId: actorId,
      eventType: 'integration.deleted',
      severity: 'WARN',
      title: `Integration removed: ${name}`,
      message: `Integration "${name}" was disconnected.`,
      entityType: 'SOURCE',
      entityId: integrationId,
    }),

  integrationTestFailed: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    name: string,
    integrationId: string,
    error: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'integration.test_failed',
      severity: 'WARN',
      title: `Connection test failed: ${name}`,
      message: error.slice(0, 500),
      dedupeKey: `int-test:${integrationId}`,
      entityType: 'SOURCE',
      entityId: integrationId,
      actionUrl: `/dashboard/sources?integrationId=${integrationId}`,
    }),

  // ── Team / Access events ───────────────────────────────────

  teamInviteSent: (
    orgId: string,
    actorId: string | undefined,
    recipientEmail: string,
  ) =>
    notify({
      organizationId: orgId,
      actorUserId: actorId,
      eventType: 'team.invite_sent',
      severity: 'INFO',
      title: 'Team invite sent',
      message: `Invitation sent to ${recipientEmail}.`,
      entityType: 'INVITE',
      actionUrl: '/dashboard/team',
    }),

  teamAccessChanged: (
    orgId: string,
    actorId: string | undefined,
    memberEmail: string,
    pipelineId: string | undefined,
    newRole: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'team.access_changed',
      severity: 'INFO',
      title: 'Access updated',
      message: `${memberEmail} access changed to ${newRole}.`,
      entityType: 'INVITE',
      actionUrl: '/dashboard/team',
    }),

  // ── Change Plan events ─────────────────────────────────────

  planApplied: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    planTitle: string,
    prUrl: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'plan.applied',
      severity: 'INFO',
      title: `Change plan applied: ${planTitle}`,
      message: `A pull request was opened.`,
      entityType: 'CHANGE_PLAN',
      actionUrl: prUrl,
      metadata: { prUrl },
    }),

  planShared: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    planTitle: string,
    target: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'plan.shared',
      severity: 'INFO',
      title: `Plan shared to ${target}`,
      message: `"${planTitle}" was shared to ${target}.`,
      entityType: 'CHANGE_PLAN',
      metadata: { target },
    }),

  // ── Lineage events ─────────────────────────────────────────

  lineageExtracted: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    integrationName: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'lineage.extracted',
      severity: 'INFO',
      title: 'Lineage extraction complete',
      message: `Lineage extracted for ${integrationName}.`,
      entityType: 'ASSET',
      actionUrl: '/dashboard/lineage',
    }),

  lineageExtractionFailed: (
    orgId: string,
    pipelineId: string | undefined,
    actorId: string | undefined,
    integrationName: string,
    error: string,
  ) =>
    notify({
      organizationId: orgId,
      pipelineStackId: pipelineId,
      actorUserId: actorId,
      eventType: 'lineage.extraction_failed',
      severity: 'ERROR',
      title: 'Lineage extraction failed',
      message: `Failed for ${integrationName}: ${error.slice(0, 300)}`,
      entityType: 'ASSET',
      actionUrl: '/dashboard/lineage',
    }),
};
