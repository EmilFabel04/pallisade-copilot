import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// ---------------------------------------------------------------------------
// Health aggregation (mirrors scanner/monitors/health.py)
// ---------------------------------------------------------------------------

const STATUS_SCORE: Record<string, number> = {
  PASS: 1.0, WARN: 0.5, FAIL: 0.0, ERROR: 0.0, SKIPPED: 0.8, RUNNING: 0.8,
};

const DEPTH_MULTIPLIER: Record<number, number> = { 0: 2.0, 1: 1.5 };
const PRIORITY_WEIGHT: Record<number, number> = { 1: 3.0, 2: 2.0, 3: 1.0 };

const MONITOR_TYPE_CATEGORY: Record<string, string> = {
  FRESHNESS: 'stale_data',
  DBT_MODEL_FRESHNESS: 'stale_data',
  DBT_SOURCE_FRESHNESS: 'stale_data',
  BI_FRESHNESS_PROXY: 'stale_data',
  SCHEMA_CHANGE: 'schema_break',
  CONNECTOR_SCHEMA_DRIFT: 'schema_break',
  SYNC_LAG: 'ingestion_lag',
  FAILED_SYNCS: 'ingestion_lag',
  DAG_LAST_RUN: 'orchestration_failure',
  DAG_SCHEDULE_LAG: 'orchestration_failure',
  TASK_FAILURE_RATE: 'orchestration_failure',
  VOLUME: 'quality_anomaly',
  NULL_RATE: 'quality_anomaly',
  UNIQUENESS: 'quality_anomaly',
  DISTRIBUTION: 'quality_anomaly',
  ANOMALY: 'quality_anomaly',
  REFERENTIAL: 'quality_anomaly',
  CUSTOM_SQL: 'quality_anomaly',
  BI_UPSTREAM_BREAK_RISK: 'quality_anomaly',
  BI_CONTENT_HEALTH: 'quality_anomaly',
  BI_REFRESH_FAILURE: 'quality_anomaly',
  DBT_TEST_FAILURES: 'transform_failure',
};

const FAILURE_CATEGORY_LABELS: Record<string, string> = {
  stale_data: 'Stale Data',
  schema_break: 'Schema Break',
  ingestion_lag: 'Ingestion Lag',
  orchestration_failure: 'Orchestration Failure',
  quality_anomaly: 'Quality Anomaly',
  transform_failure: 'Transform Failure',
};

interface MonitorSignal {
  monitorId: string;
  monitorName: string;
  monitorType: string | null;
  targetFqn: string | null;
  status: string;
  message: string | null;
  depth: number;
  priority: number;
}

function computeHealthScore(signals: MonitorSignal[]): number {
  if (signals.length === 0) return 100;
  let totalWeightedValue = 0;
  let totalWeight = 0;
  for (const s of signals) {
    const statusVal = STATUS_SCORE[s.status] ?? 0;
    const depthMult = DEPTH_MULTIPLIER[s.depth] ?? 1.0;
    const prioWeight = PRIORITY_WEIGHT[s.priority] ?? 0.5;
    const weight = prioWeight * depthMult;
    totalWeightedValue += weight * statusVal;
    totalWeight += weight;
  }
  if (totalWeight === 0) return 100;
  return Math.round((totalWeightedValue / totalWeight) * 1000) / 10;
}

function healthStatusFromScore(score: number): string {
  if (score >= 90) return 'healthy';
  if (score >= 70) return 'degraded';
  if (score >= 40) return 'at_risk';
  return 'unhealthy';
}

function groupFailures(signals: MonitorSignal[]) {
  const failing = signals.filter((s) => s.status === 'FAIL' || s.status === 'ERROR' || s.status === 'WARN');
  if (failing.length === 0) return [];

  const buckets = new Map<string, MonitorSignal[]>();
  for (const s of failing) {
    const cat = MONITOR_TYPE_CATEGORY[s.monitorType || ''] || 'quality_anomaly';
    const existing = buckets.get(cat) || [];
    existing.push(s);
    buckets.set(cat, existing);
  }

  const groups = Array.from(buckets.entries()).map(([category, catSignals]) => {
    const hasCritical = catSignals.some((s) => s.status === 'FAIL' || s.status === 'ERROR');
    const deepest = catSignals.reduce((a, b) => (b.depth > a.depth ? b : a));
    const summaryParts = catSignals.slice(0, 3).map((s) => `${s.monitorName}: ${s.status}`);
    if (catSignals.length > 3) summaryParts.push(`+${catSignals.length - 3} more`);

    return {
      category,
      severity: hasCritical ? 'critical' as const : 'warning' as const,
      summary: summaryParts.join(', '),
      rootCauseHint: deepest.targetFqn || 'unknown',
      signalCount: catSignals.length,
    };
  });

  groups.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === 'critical' ? -1 : 1;
    return b.signalCount - a.signalCount;
  });
  return groups;
}

function aggregateStatus(signals: MonitorSignal[]): string {
  if (signals.length === 0) return 'none';
  const statuses = new Set(signals.map((s) => s.status));
  const hasFail = statuses.has('FAIL') || statuses.has('ERROR');
  const hasPass = statuses.has('PASS');
  if (hasFail && hasPass) return 'mixed';
  if (hasFail) return 'fail';
  if (statuses.has('WARN')) return hasPass ? 'mixed' : 'warn';
  if (hasPass) return 'pass';
  return 'none';
}

function generateSummary(anchorName: string, status: string, failureGroups: ReturnType<typeof groupFailures>): string {
  if (failureGroups.length === 0) return `${anchorName} is ${status}`;
  const top = failureGroups[0];
  const catLabel = FAILURE_CATEGORY_LABELS[top.category] || top.category.replace('_', ' ');
  const total = failureGroups.reduce((sum, g) => sum + g.signalCount, 0);
  if (total === 1) return `${anchorName} is ${status}: ${catLabel.toLowerCase()} detected`;
  return `${anchorName} is ${status}: ${total} signals across ${catLabel.toLowerCase()}`;
}

// ---------------------------------------------------------------------------
// POST /api/schedule/watches/[watchId]/run
// ---------------------------------------------------------------------------

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { watchId } = await params;
    const organizationId = (session.user as any).organizationId;

    const group = await prisma.monitorGroup.findFirst({
      where: { id: watchId, organizationId, watchType: { not: null } },
      include: {
        monitors: {
          where: { enabled: true },
          select: { id: true, name: true, monitorType: true, targetFqn: true },
        },
      },
    });

    if (!group) {
      return NextResponse.json({ error: 'Watch not found' }, { status: 404 });
    }

    if (group.monitors.length === 0) {
      return NextResponse.json({ error: 'No enabled monitors in this watch' }, { status: 400 });
    }

    // Run each monitor via the existing single-task run endpoint
    const baseUrl = request.nextUrl.origin;
    const cookie = request.headers.get('cookie') || '';

    const signals: MonitorSignal[] = [];

    for (const monitor of group.monitors) {
      try {
        const runRes = await fetch(`${baseUrl}/api/schedule/tasks/${monitor.id}/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Cookie: cookie },
        });

        const runData = await runRes.json();
        const resultStatus = runData.result?.status || runData.run?.status || 'ERROR';
        const resultMessage = runData.result?.message || runData.run?.message || null;

        signals.push({
          monitorId: monitor.id,
          monitorName: monitor.name,
          monitorType: monitor.monitorType,
          targetFqn: monitor.targetFqn,
          status: resultStatus,
          message: resultMessage,
          // TODO: populate from scope data when available
          depth: monitor.targetFqn === group.anchorFqn ? 0 : 1,
          priority: 2,
        });
      } catch (err: any) {
        signals.push({
          monitorId: monitor.id,
          monitorName: monitor.name,
          monitorType: monitor.monitorType,
          targetFqn: monitor.targetFqn,
          status: 'ERROR',
          message: `Failed to execute: ${err.message}`,
          depth: monitor.targetFqn === group.anchorFqn ? 0 : 1,
          priority: 2,
        });
      }
    }

    // Compute health
    const healthScore = computeHealthScore(signals);
    const healthStatus = healthStatusFromScore(healthScore);
    const failureGroups = groupFailures(signals);
    const anchorName = group.anchorFqn?.split('.').pop() || group.name;
    const summary = generateSummary(anchorName, healthStatus, failureGroups);

    const directSignals = signals.filter((s) => s.depth === 0);
    const upstreamSignals = signals.filter((s) => s.depth > 0);

    const worstStatusPriority: Record<string, number> = {
      FAIL: 0, ERROR: 1, WARN: 2, PASS: 3, SKIPPED: 4,
    };
    const worstStatus = signals.reduce((worst, r) => {
      const rp = worstStatusPriority[r.status] ?? 1;
      const wp = worstStatusPriority[worst] ?? 1;
      return rp < wp ? r.status : worst;
    }, 'PASS');

    const healthReport = {
      healthScore,
      healthStatus,
      summary,
      directStatus: aggregateStatus(directSignals),
      upstreamStatus: aggregateStatus(upstreamSignals),
      coveragePct: group.coveragePct ?? null,
      failureGroups,
      computedAt: new Date().toISOString(),
    };

    // Persist
    await prisma.monitorGroup.update({
      where: { id: watchId },
      data: {
        lastStatus: worstStatus as any,
        lastRunAt: new Date(),
        healthScore,
        healthDetails: healthReport as any,
        lastHealthAt: new Date(),
      },
    });

    const passCount = signals.filter((r) => r.status === 'PASS').length;
    const failCount = signals.filter((r) => r.status === 'FAIL' || r.status === 'ERROR').length;
    const warnCount = signals.filter((r) => r.status === 'WARN').length;

    return NextResponse.json({
      watchId,
      watchType: group.watchType,
      aggregateStatus: worstStatus,
      healthScore,
      healthStatus,
      summary,
      totalMonitors: signals.length,
      passCount,
      failCount,
      warnCount,
      failureGroups,
      results: signals.map((s) => ({
        monitorId: s.monitorId,
        monitorName: s.monitorName,
        monitorType: s.monitorType,
        targetFqn: s.targetFqn,
        status: s.status,
        message: s.message,
      })),
    });
  } catch (error: any) {
    console.error('[Watches] Run error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
