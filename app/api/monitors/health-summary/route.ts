import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { PIPELINE_TYPE_TO_FAMILY } from '@/lib/monitors/families';
import type { MonitorHealthSummary } from '@/types/monitors-summary';
import type { $Enums } from '@prisma/client';

const DATA_MONITOR_TYPES = new Set([
  'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK', 'UNIQUENESS_CHECK',
  'OUTLIER_DETECTION', 'ANOMALY', 'RANGE_VALIDATION', 'ACCEPTED_VALUES',
  'DATE_CONSISTENCY', 'DATA_TYPE_VALIDATION',
]);

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
