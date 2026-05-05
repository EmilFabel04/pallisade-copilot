import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { PIPELINE_TYPE_TO_FAMILY, TOOL_TYPE_BY_INTEGRATION_TYPE } from '@/lib/monitors/families';
import type { $Enums } from '@prisma/client';
import type { PipelineToolStatusResponse } from '@/types/monitors-summary';
import { aggregateByTool, type ToolMonitor } from './aggregate';

const PIPELINE_MONITOR_TYPES: $Enums.MonitorKind[] = [
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY',
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE', 'BI_CONTENT_HEALTH',
  'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS',
];

// Each pipeline-tool family can host one of several concrete tools (e.g. orchestration → airflow OR dagster).
// When a monitor lacks an Integration link, we look up the stack's configured PipelineNode for that family
// so the user sees the actual tool's logo (Airflow) rather than the generic family badge ("Orchestration").
const FAMILY_TOOL_PREFERENCE: Record<string, string[]> = {
  ingestion: ['fivetran', 'airbyte'],
  orchestration: ['airflow', 'dagster'],
  transform: ['dbt_cloud', 'dbt_core'],
  bi: ['looker', 'tableau', 'power_bi', 'metabase'],
  infra: ['linux_server'],
};

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  // Stack-scoped pipeline nodes (configured tools) for family fallback resolution.
  const stack = await prisma.pipelineStack.findFirst({
    where: { id: stackId, organizationId },
    include: {
      nodes: { select: { toolType: true } },
    },
  });
  const stackToolTypes = new Set((stack?.nodes ?? []).map((n) => (n.toolType || '').toLowerCase()));

  // Build a per-family default: pick the first configured tool from the preference list.
  const familyDefault: Record<string, string> = {};
  for (const [family, prefs] of Object.entries(FAMILY_TOOL_PREFERENCE)) {
    const hit = prefs.find((t) => stackToolTypes.has(t));
    if (hit) familyDefault[family] = hit;
  }

  const monitors = await prisma.monitor.findMany({
    where: {
      organizationId,
      pipelineStackId: stackId,
      enabled: true,
      monitorType: { in: PIPELINE_MONITOR_TYPES },
    },
    select: {
      monitorType: true,
      lastStatus: true,
      lastRunAt: true,
      integration: { select: { type: true } },
    },
  });

  const toolMonitors: ToolMonitor[] = monitors.map((m) => {
    const integrationKey = m.integration?.type
      ? TOOL_TYPE_BY_INTEGRATION_TYPE[m.integration.type] || m.integration.type.toLowerCase()
      : null;
    if (integrationKey) {
      return { toolType: integrationKey, lastStatus: m.lastStatus, lastRunAt: m.lastRunAt };
    }
    const family = PIPELINE_TYPE_TO_FAMILY[(m.monitorType || '').toUpperCase()];
    const resolved = (family && familyDefault[family]) || family || 'unknown';
    return { toolType: resolved, lastStatus: m.lastStatus, lastRunAt: m.lastRunAt };
  });

  const response: PipelineToolStatusResponse = { tools: aggregateByTool(toolMonitors) };
  return NextResponse.json(response);
}
