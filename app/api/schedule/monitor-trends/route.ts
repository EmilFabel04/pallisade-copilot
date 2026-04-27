import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const MONITOR_TYPE_TO_CATEGORY: Record<string, string> = {
  FRESHNESS: 'freshness',
  VOLUME: 'volume',
  NULL_CHECK: 'quality',
  SCHEMA_CHANGE: 'schema',
  OUTLIER_DETECTION: 'anomaly',
  ANOMALY: 'anomaly',
  UNIQUENESS_CHECK: 'uniqueness',
  RANGE_VALIDATION: 'anomaly',
  ACCEPTED_VALUES: 'quality',
  DATE_CONSISTENCY: 'quality',
  DATA_TYPE_VALIDATION: 'quality',
};

const PIPELINE_MONITOR_TYPES = new Set([
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY',
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE', 'BI_CONTENT_HEALTH',
  'SERVER_HEALTH', 'CERTIFICATE', 'LOG_ANALYSIS',
]);

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  category: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface CategoryHealth {
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: 'stable' | 'warning' | 'drifting' | 'pending';
  monitors: MonitorTrend[];
}

function deriveDataStatus(passing: number, warning: number, failing: number, total: number): CategoryHealth['status'] {
  if (total === 0) return 'pending';
  if (passing + warning + failing === 0) return 'pending';
  if (failing > 0) return 'drifting';
  if (warning > 0) return 'warning';
  return 'stable';
}

function derivePipelineStatus(passing: number, warning: number, failing: number, total: number): 'healthy' | 'degraded' | 'down' | 'pending' {
  if (total === 0) return 'pending';
  if (passing + warning + failing === 0) return 'pending';
  if (failing === total) return 'down';
  if (failing > 0 || warning > 0) return 'degraded';
  return 'healthy';
}

export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Fetch all monitor groups with their monitors and last 30 runs each
    const groups = await prisma.monitorGroup.findMany({
      where: {
        organizationId,
        watchType: { not: null },
      },
      include: {
        monitors: {
          select: {
            id: true,
            name: true,
            monitorType: true,
            targetFqn: true,
            lastStatus: true,
            enabled: true,
            runs: {
              orderBy: { startedAt: 'desc' },
              take: 30,
              select: {
                value: true,
                status: true,
                startedAt: true,
              },
            },
          },
        },
      },
    });

    // Flatten all monitors with their group metadata
    const allMonitors = groups.flatMap((g) =>
      g.monitors.map((m) => ({
        ...m,
        anchorPlatform: g.anchorPlatform,
        watchType: g.watchType,
        groupName: g.name,
      }))
    );

    // Separate data vs pipeline monitors
    const dataMonitors = allMonitors.filter(
      (m) => MONITOR_TYPE_TO_CATEGORY[(m.monitorType || '').toUpperCase()] !== undefined
    );
    const pipelineMonitors = allMonitors.filter(
      (m) => PIPELINE_MONITOR_TYPES.has((m.monitorType || '').toUpperCase())
    );

    // Helper to build a MonitorTrend from a monitor record
    function buildTrend(m: typeof allMonitors[0], category: string): MonitorTrend {
      const runs = m.runs.map((r) => ({
        value: r.value,
        status: r.status,
        at: r.startedAt.toISOString(),
      })).reverse(); // oldest first for sparkline

      const values = runs.map((r) => r.value).filter((v): v is number => v !== null);
      const latestValue = values.length > 0 ? values[values.length - 1] : null;
      const baselineMean = values.length > 1
        ? values.slice(0, -1).reduce((a, b) => a + b, 0) / (values.length - 1)
        : null;
      const pctChange = latestValue !== null && baselineMean !== null && baselineMean !== 0
        ? ((latestValue - baselineMean) / baselineMean) * 100
        : null;

      return {
        id: m.id,
        name: m.name,
        targetFqn: m.targetFqn || '',
        category,
        latestStatus: m.lastStatus,
        latestValue,
        baselineMean: baselineMean !== null ? Math.round(baselineMean * 100) / 100 : null,
        pctChange: pctChange !== null ? Math.round(pctChange * 10) / 10 : null,
        runs,
      };
    }

    // Build data health by category
    const dataHealth: Record<string, CategoryHealth> = {};
    for (const m of dataMonitors) {
      const category = MONITOR_TYPE_TO_CATEGORY[(m.monitorType || '').toUpperCase()];
      if (!category) continue;

      if (!dataHealth[category]) {
        dataHealth[category] = { total: 0, passing: 0, warning: 0, failing: 0, status: 'pending', monitors: [] };
      }

      const cat = dataHealth[category];
      cat.total++;

      const ls = (m.lastStatus || '').toUpperCase();
      if (ls === 'PASS') cat.passing++;
      else if (ls === 'WARN') cat.warning++;
      else if (ls === 'FAIL' || ls === 'ERROR') cat.failing++;

      cat.monitors.push(buildTrend(m, category));
    }

    // Derive status for each category
    for (const cat of Object.values(dataHealth)) {
      cat.status = deriveDataStatus(cat.passing, cat.warning, cat.failing, cat.total);
    }

    // Build per-asset grouping (data monitors only)
    const assets: Record<string, { name: string; fqn: string; total: number; passing: number; warning: number; failing: number; status: CategoryHealth['status']; monitors: MonitorTrend[] }> = {};
    for (const m of dataMonitors) {
      const fqn = m.targetFqn || '';
      if (!fqn) continue;
      const category = MONITOR_TYPE_TO_CATEGORY[(m.monitorType || '').toUpperCase()];
      if (!category) continue;

      if (!assets[fqn]) {
        const parts = fqn.split('.');
        assets[fqn] = {
          name: parts[parts.length - 1] || fqn,
          fqn,
          total: 0, passing: 0, warning: 0, failing: 0,
          status: 'pending',
          monitors: [],
        };
      }

      const asset = assets[fqn];
      asset.total++;
      const ls = (m.lastStatus || '').toUpperCase();
      if (ls === 'PASS') asset.passing++;
      else if (ls === 'WARN') asset.warning++;
      else if (ls === 'FAIL' || ls === 'ERROR') asset.failing++;

      asset.monitors.push(buildTrend(m, category));
    }

    for (const asset of Object.values(assets)) {
      asset.status = deriveDataStatus(asset.passing, asset.warning, asset.failing, asset.total);
    }

    // Build pipeline health by platform
    const pipelineHealth: Record<string, { total: number; passing: number; warning: number; failing: number; status: string; monitors: MonitorTrend[] }> = {};
    for (const m of pipelineMonitors) {
      const platform = (m.anchorPlatform || m.watchType || 'other').toLowerCase();

      if (!pipelineHealth[platform]) {
        pipelineHealth[platform] = { total: 0, passing: 0, warning: 0, failing: 0, status: 'pending', monitors: [] };
      }

      const ph = pipelineHealth[platform];
      ph.total++;

      const ls = (m.lastStatus || '').toUpperCase();
      if (ls === 'PASS') ph.passing++;
      else if (ls === 'WARN') ph.warning++;
      else if (ls === 'FAIL' || ls === 'ERROR') ph.failing++;

      ph.monitors.push(buildTrend(m, 'pipeline'));
    }

    for (const ph of Object.values(pipelineHealth)) {
      ph.status = derivePipelineStatus(ph.passing, ph.warning, ph.failing, ph.total);
    }

    return NextResponse.json({
      dataHealth,
      assets,
      pipelineHealth,
      updatedAt: new Date().toISOString(),
    });
  } catch (error: any) {
    console.error('[MonitorTrends] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
