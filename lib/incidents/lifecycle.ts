import type { PrismaClient, MonitorRun } from '@prisma/client';

export type LifecycleAction = 'opened' | 'updated' | 'noop' | 'auto_resolved';

export interface LifecycleResult {
  action: LifecycleAction;
  shouldDiagnose: boolean;
  incidentId?: string;
}

const FAILING = new Set(['FAIL', 'WARN', 'ERROR']);

export async function handleRun(
  run: MonitorRun,
  prisma: PrismaClient,
): Promise<LifecycleResult> {
  const monitor = await prisma.monitor.findUnique({
    where: { id: run.monitorId },
    select: {
      id: true,
      organizationId: true,
      pipelineStackId: true,
      targetFqn: true,
      monitorGroupId: true,
    },
  });
  if (!monitor || !monitor.organizationId || !monitor.pipelineStackId) {
    return { action: 'noop', shouldDiagnose: false };
  }

  const existing = await prisma.incident.findFirst({
    where: { monitorId: run.monitorId, status: { in: ['OPEN', 'ACKNOWLEDGED'] } },
  });

  if (FAILING.has(run.status)) {
    if (!existing) {
      const severity = run.status === 'WARN' ? 'WARN' : 'FAIL';
      const created = await prisma.incident.create({
        data: {
          organizationId: monitor.organizationId,
          pipelineStackId: monitor.pipelineStackId,
          monitorId: monitor.id,
          monitorGroupId: monitor.monitorGroupId ?? null,
          targetFqn: monitor.targetFqn ?? 'unknown',
          status: 'OPEN',
          severity,
          openedAt: run.startedAt,
          openingRunId: run.id,
          consecutiveCount: 1,
        },
      });
      return { action: 'opened', shouldDiagnose: true, incidentId: created.id };
    }
    // Existing open/ack incident — diagnosis decision made later in diagnose.ts
    return { action: 'updated', shouldDiagnose: existing.consecutiveCount < 3, incidentId: existing.id };
  }

  // PASS / SKIPPED on a target with an open incident → auto-resolve
  if (run.status === 'PASS' && existing) {
    await prisma.incident.update({
      where: { id: existing.id },
      data: {
        status: 'RESOLVED',
        resolvedAt: run.completedAt ?? new Date(),
        resolvedBy: 'system',
        resolutionType: 'AUTO_RECOVERED',
      },
    });
    return { action: 'auto_resolved', shouldDiagnose: false, incidentId: existing.id };
  }

  return { action: 'noop', shouldDiagnose: false };
}
