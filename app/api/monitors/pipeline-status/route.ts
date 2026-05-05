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

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

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

  const toolMonitors: ToolMonitor[] = monitors.map((m) => ({
    toolType:
      (m.integration?.type ? TOOL_TYPE_BY_INTEGRATION_TYPE[m.integration.type] : null) ||
      PIPELINE_TYPE_TO_FAMILY[(m.monitorType || '').toUpperCase()] ||
      'unknown',
    lastStatus: m.lastStatus,
    lastRunAt: m.lastRunAt,
  }));

  const response: PipelineToolStatusResponse = { tools: aggregateByTool(toolMonitors) };
  return NextResponse.json(response);
}
