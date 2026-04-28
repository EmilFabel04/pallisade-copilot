import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { notifyEvents } from '@/lib/notifications';
import { detectHighImpactEvents } from '@/lib/high-impact-events';
import { routeNotification } from '@/lib/notification-router';
import { getInternalApiKey, INTERNAL_API_KEY_HEADER } from '@/lib/internal-api-key';

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
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { watchId } = await params;
    const organizationId = (session.user as any).organizationId;

    const body = await request.json().catch(() => ({}));
    const stackId = body.stackId || new URL(request.url).searchParams.get('stackId');
    if (!stackId) {
      return NextResponse.json(
        { error: 'stackId is required (in body or query)' },
        { status: 400 }
      );
    }

    const group = await prisma.monitorGroup.findFirst({
      where: { id: watchId, organizationId, pipelineStackId: stackId, watchType: { not: null } },
      include: {
        monitors: {
          where: { enabled: true },
          select: { id: true, name: true, monitorType: true, targetFqn: true, config: true },
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
        const runRes = await fetch(`${baseUrl}/api/schedule/tasks/${monitor.id}/run?grouped=true`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Cookie: cookie },
          body: JSON.stringify({ stackId }),
        });

        const runData = await runRes.json();
        const resultStatus = runData.result?.status || runData.run?.status || 'ERROR';
        const resultMessage = runData.result?.message || runData.run?.message || null;

        const monConfig = (monitor.config as any) || {};
        const depth = monConfig._watchDepth ?? (monitor.targetFqn === group.anchorFqn ? 0 : 1);
        const priority = monConfig._watchPriority ?? 2;

        signals.push({
          monitorId: monitor.id,
          monitorName: monitor.name,
          monitorType: monitor.monitorType,
          targetFqn: monitor.targetFqn,
          status: resultStatus,
          message: resultMessage,
          depth,
          priority,
        });
      } catch (err: any) {
        const monConfig = (monitor.config as any) || {};
        const depth = monConfig._watchDepth ?? (monitor.targetFqn === group.anchorFqn ? 0 : 1);
        const priority = monConfig._watchPriority ?? 2;

        signals.push({
          monitorId: monitor.id,
          monitorName: monitor.name,
          monitorType: monitor.monitorType,
          targetFqn: monitor.targetFqn,
          status: 'ERROR',
          message: `Failed to execute: ${err.message}`,
          depth,
          priority,
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

    // ── Notifications & routing (fire-and-forget) ──────────────
    const errorCount = signals.filter((r) => r.status === 'ERROR').length;
    const summaryObj = { total: signals.length, pass: passCount, fail: failCount, warn: warnCount, error: errorCount };

    // Per-monitor alert dispatch — manual runs now honour the same
    // destination routing as scheduled runs. Fires one POST per monitor
    // that produced a non-PASS/SKIPPED signal. The /api/schedule/alert
    // route resolves the monitor's alertConfig.destinations internally.
    const alertSignals = signals.filter((s) => s.status === 'FAIL' || s.status === 'ERROR' || s.status === 'WARN');
    if (alertSignals.length > 0) {
      const baseUrl = process.env.NEXTAUTH_URL || process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000';
      const internalKey = getInternalApiKey();
      for (const sig of alertSignals) {
        fetch(`${baseUrl}/api/schedule/alert`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            [INTERNAL_API_KEY_HEADER]: internalKey,
          },
          body: JSON.stringify({
            taskId: sig.monitorId,
            taskName: sig.monitorName,
            status: sig.status,
            message: sig.message,
            organizationId: group.organizationId,
          }),
        }).catch(() => {});
      }
    }

    // Previous health score (from before this run's update)
    const previousHealthScore = group.healthScore ?? 100;

    // 1. In-app notification (always)
    notifyEvents.monitorGroupCompleted(
      group.organizationId,
      stackId,
      undefined,
      group.name,
      watchId,
      summaryObj,
      { currentHealthScore: healthScore, previousHealthScore },
    ).catch(() => {});

    // 2. Detect high-impact events
    detectHighImpactEvents({
      watchId,
      organizationId: group.organizationId,
      pipelineStackId: stackId,
      currentHealthScore: healthScore,
      previousHealthScore,
      results: signals.map((s) => ({
        monitorId: s.monitorId,
        monitorName: s.monitorName,
        status: s.status,
      })),
    }).then((events) => {
      for (const event of events) {
        if (event.eventType === 'monitor.health_score_dropped') {
          notifyEvents.healthScoreDropped(
            group.organizationId, stackId, undefined,
            group.name, watchId,
            event.previousScore!, event.currentScore!, event.severity,
          ).catch(() => {});
        } else if (event.eventType === 'monitor.sustained_failure') {
          notifyEvents.sustainedFailure(
            group.organizationId, stackId, undefined,
            group.name, watchId,
            event.monitorName!, event.monitorId!, event.consecutiveFailures!, event.severity,
          ).catch(() => {});
        }
        // Route high-impact events to external platforms
        routeNotification({
          organizationId: group.organizationId,
          severity: event.severity,
          title: event.title,
          message: event.message,
          actionUrl: `/dashboard/schedule?group=${watchId}`,
        }).catch(() => {});
      }
    }).catch(() => {});

    // 3. Route the group result to external platforms
    const groupSeverity =
      healthScore < 40 ? 'CRITICAL' as const
      : failCount > 0 || errorCount > 0 ? 'ERROR' as const
      : warnCount > 0 ? 'WARN' as const
      : 'INFO' as const;

    const isRecovery = previousHealthScore < 70 && healthScore >= 70 && failCount === 0;

    routeNotification({
      organizationId: group.organizationId,
      severity: groupSeverity,
      title: `${group.name}: ${passCount} pass, ${failCount} fail, ${warnCount} warn`,
      message: `Health score: ${healthScore.toFixed(0)} — ${healthStatus}`,
      metadata: { ...summaryObj, healthScore, healthStatus },
      actionUrl: `/dashboard/schedule?group=${watchId}`,
      isRecovery,
    }).catch(() => {});

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
