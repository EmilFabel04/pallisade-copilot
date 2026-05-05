import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import type { MonitorHealthSummary } from '@/types/monitors-summary';
import type { $Enums } from '@prisma/client';

const DATA_MONITOR_TYPES = new Set([
  'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK', 'UNIQUENESS_CHECK',
  'OUTLIER_DETECTION', 'ANOMALY', 'RANGE_VALIDATION', 'ACCEPTED_VALUES',
  'DATE_CONSISTENCY', 'DATA_TYPE_VALIDATION',
]);

// Pipeline monitor type → tool family. Multiple monitor types may share a family
// (DAG_LAST_RUN and DAG_SCHEDULE_LAG both target Airflow/Dagster). The hero
// counts distinct families, so users see "3 pipeline tools" when they have
// Fivetran, Airflow, and dbt — not "8 monitor variants".
const PIPELINE_TYPE_TO_FAMILY: Record<string, string> = {
  SYNC_LAG: 'ingestion', FAILED_SYNCS: 'ingestion', CONNECTOR_SCHEMA_DRIFT: 'ingestion',
  DAG_LAST_RUN: 'orchestration', DAG_SCHEDULE_LAG: 'orchestration', TASK_FAILURE_RATE: 'orchestration',
  DBT_TEST_FAILURES: 'transform', DBT_MODEL_FRESHNESS: 'transform', DBT_SOURCE_FRESHNESS: 'transform',
  DBT_CORE_SOURCE_VALIDATION: 'transform', DBT_CORE_REF_INTEGRITY: 'transform',
  BI_FRESHNESS_PROXY: 'bi', BI_UPSTREAM_BREAK_RISK: 'bi', BI_REFRESH_FAILURE: 'bi', BI_CONTENT_HEALTH: 'bi',
  CERTIFICATE: 'infra', SERVER_HEALTH: 'infra', LOG_ANALYSIS: 'infra',
};

type MonitorRow = {
  monitorType: $Enums.MonitorKind | string | null;
  targetFqn: string | null;
  lastStatus: $Enums.MonitorRunStatus | string | null;
  lastRunAt: Date | null;
};

export function aggregate(monitors: MonitorRow[]): MonitorHealthSummary {
  let healthy = 0, warning = 0, failing = 0;
  const dataFqns = new Set<string>();
  const pipelineFamilies = new Set<string>();
  let mostRecent: Date | null = null;

  for (const m of monitors) {
    const status = (m.lastStatus || '').toUpperCase();
    if (status === 'WARN') warning += 1;
    else if (status === 'FAIL' || status === 'ERROR') failing += 1;
    else healthy += 1;

    const type = (m.monitorType || '').toUpperCase();
    if (DATA_MONITOR_TYPES.has(type) && m.targetFqn) {
      dataFqns.add(m.targetFqn);
    }
    const family = PIPELINE_TYPE_TO_FAMILY[type];
    if (family) pipelineFamilies.add(family);

    if (m.lastRunAt && (!mostRecent || m.lastRunAt > mostRecent)) {
      mostRecent = m.lastRunAt;
    }
  }

  return {
    total: monitors.length,
    healthy,
    warning,
    failing,
    dataAssets: dataFqns.size,
    pipelineTools: pipelineFamilies.size,
    lastRunAt: mostRecent ? mostRecent.toISOString() : null,
  };
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  const monitors = await prisma.monitor.findMany({
    where: { organizationId, pipelineStackId: stackId, enabled: true },
    select: { monitorType: true, targetFqn: true, lastStatus: true, lastRunAt: true },
  });

  return NextResponse.json(aggregate(monitors));
}
