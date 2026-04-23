import prisma from '@/lib/db';

export interface HighImpactEvent {
  eventType: 'monitor.health_score_dropped' | 'monitor.sustained_failure';
  severity: 'WARN' | 'ERROR' | 'CRITICAL';
  title: string;
  message: string;
  metadata: Record<string, unknown>;
  monitorId?: string;
  monitorName?: string;
  consecutiveFailures?: number;
  previousScore?: number;
  currentScore?: number;
}

interface DetectParams {
  watchId: string;
  organizationId: string;
  pipelineStackId: string | undefined;
  currentHealthScore: number;
  previousHealthScore: number;
  results: Array<{ monitorId: string; monitorName: string; status: string }>;
}

function healthStatus(score: number): string {
  if (score >= 90) return 'healthy';
  if (score >= 70) return 'degraded';
  if (score >= 40) return 'at_risk';
  return 'unhealthy';
}

function detectHealthScoreDrop(params: DetectParams): HighImpactEvent | null {
  const { currentHealthScore, previousHealthScore } = params;
  if (currentHealthScore >= previousHealthScore) return null;
  const prevStatus = healthStatus(previousHealthScore);
  const currStatus = healthStatus(currentHealthScore);
  if (prevStatus === currStatus) return null;

  const severity: 'WARN' | 'ERROR' | 'CRITICAL' =
    currentHealthScore < 40 ? 'CRITICAL' : currentHealthScore < 70 ? 'ERROR' : 'WARN';

  return {
    eventType: 'monitor.health_score_dropped',
    severity,
    title: `Health dropped: ${prevStatus} → ${currStatus}`,
    message: `Health score fell from ${previousHealthScore.toFixed(0)} to ${currentHealthScore.toFixed(0)}`,
    metadata: { previousScore: previousHealthScore, currentScore: currentHealthScore, prevStatus, currStatus },
    previousScore: previousHealthScore,
    currentScore: currentHealthScore,
  };
}

async function detectSustainedFailures(params: DetectParams): Promise<HighImpactEvent[]> {
  const events: HighImpactEvent[] = [];
  const CONSECUTIVE_THRESHOLD = 3;

  const failedMonitors = params.results.filter(
    (r) => r.status === 'FAIL' || r.status === 'ERROR',
  );
  if (failedMonitors.length === 0) return events;

  const monitorIds = failedMonitors.map((m) => m.monitorId);

  const recentRuns = await prisma.monitorRun.findMany({
    where: {
      monitorId: { in: monitorIds },
      status: { notIn: ['SKIPPED', 'RUNNING'] },
    },
    orderBy: { startedAt: 'desc' },
    take: CONSECUTIVE_THRESHOLD * monitorIds.length,
    select: { monitorId: true, status: true },
  });

  const runsByMonitor = new Map<string, string[]>();
  for (const run of recentRuns) {
    const runs = runsByMonitor.get(run.monitorId) || [];
    runs.push(run.status);
    runsByMonitor.set(run.monitorId, runs);
  }

  for (const monitor of failedMonitors) {
    const runs = runsByMonitor.get(monitor.monitorId) || [];
    const lastN = runs.slice(0, CONSECUTIVE_THRESHOLD);
    if (lastN.length >= CONSECUTIVE_THRESHOLD && lastN.every((s) => s === 'FAIL' || s === 'ERROR')) {
      events.push({
        eventType: 'monitor.sustained_failure',
        severity: 'CRITICAL',
        title: `${monitor.monitorName} has failed ${CONSECUTIVE_THRESHOLD}+ times`,
        message: `Monitor "${monitor.monitorName}" has failed ${CONSECUTIVE_THRESHOLD} consecutive runs`,
        metadata: { monitorId: monitor.monitorId, monitorName: monitor.monitorName, consecutiveFailures: CONSECUTIVE_THRESHOLD },
        monitorId: monitor.monitorId,
        monitorName: monitor.monitorName,
        consecutiveFailures: CONSECUTIVE_THRESHOLD,
      });
    }
  }

  return events;
}

export async function detectHighImpactEvents(params: DetectParams): Promise<HighImpactEvent[]> {
  const events: HighImpactEvent[] = [];
  const healthDrop = detectHealthScoreDrop(params);
  if (healthDrop) events.push(healthDrop);
  const sustained = await detectSustainedFailures(params);
  events.push(...sustained);
  return events;
}
