import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import type { $Enums } from '@prisma/client';
import type {
  PipelineToolStatus,
  PipelineToolStatusValue,
  PipelineToolStatusResponse,
} from '@/types/monitors-summary';

const PIPELINE_MONITOR_TYPES: $Enums.MonitorKind[] = [
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY',
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE', 'BI_CONTENT_HEALTH',
  'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS',
];

// Map IntegrationType enum values (uppercase) to canonical toolType strings (lowercase).
// This allows the GET handler to resolve toolType from integration.type.
const TOOL_TYPE_BY_INTEGRATION_TYPE: Record<string, string> = {
  FIVETRAN: 'fivetran', AIRBYTE: 'airbyte', STITCH: 'stitch',
  AIRFLOW: 'airflow', DAGSTER: 'dagster', PREFECT: 'prefect', N8N: 'n8n',
  DBT_CLOUD: 'dbt_cloud', DBT_CORE: 'dbt_core',
  TABLEAU: 'tableau', LOOKER: 'looker', POWERBI: 'powerbi', METABASE: 'metabase',
  SNOWFLAKE: 'snowflake', BIGQUERY: 'bigquery', POSTGRES: 'postgres', REDSHIFT: 'redshift',
  LINUX_SERVER: 'linux_server',
};

const FAMILY_BY_TYPE: Record<string, string> = {
  SYNC_LAG: 'ingestion', FAILED_SYNCS: 'ingestion', CONNECTOR_SCHEMA_DRIFT: 'ingestion',
  DAG_LAST_RUN: 'orchestration', DAG_SCHEDULE_LAG: 'orchestration', TASK_FAILURE_RATE: 'orchestration',
  DBT_TEST_FAILURES: 'transform', DBT_MODEL_FRESHNESS: 'transform', DBT_SOURCE_FRESHNESS: 'transform',
  DBT_CORE_SOURCE_VALIDATION: 'transform', DBT_CORE_REF_INTEGRITY: 'transform',
  BI_FRESHNESS_PROXY: 'bi', BI_UPSTREAM_BREAK_RISK: 'bi', BI_REFRESH_FAILURE: 'bi', BI_CONTENT_HEALTH: 'bi',
  CERTIFICATE: 'infra', SERVER_HEALTH: 'infra', LOG_ANALYSIS: 'infra',
};

const DISPLAY_OVERRIDES: Record<string, string> = {
  fivetran: 'Fivetran',
  airbyte: 'Airbyte',
  airflow: 'Airflow',
  dagster: 'Dagster',
  dbt_cloud: 'dbt cloud',
  dbt_core: 'dbt core',
  looker: 'Looker',
  tableau: 'Tableau',
  bigquery: 'BigQuery',
  snowflake: 'Snowflake',
  postgres: 'Postgres',
  redshift: 'Redshift',
  linux_server: 'linux server',
};

function displayName(toolType: string): string {
  if (DISPLAY_OVERRIDES[toolType]) return DISPLAY_OVERRIDES[toolType];
  return toolType
    .split('_')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

type ToolMonitor = {
  toolType: string;
  lastStatus: string | null;
  lastRunAt: Date | null;
};

function precedence(status: string): number {
  const s = status.toUpperCase();
  if (s === 'FAIL') return 4;
  if (s === 'ERROR') return 3;
  if (s === 'WARN') return 2;
  if (s === 'PASS' || s === 'SKIPPED') return 1;
  return 0;
}

export function aggregateByTool(monitors: ToolMonitor[]): PipelineToolStatus[] {
  const buckets = new Map<string, ToolMonitor[]>();
  for (const m of monitors) {
    const key = m.toolType || 'unknown';
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(m);
  }
  const out: PipelineToolStatus[] = [];
  for (const [toolType, items] of buckets) {
    let topStatus = '';
    let topRank = 0;
    let failCount = 0, warnCount = 0;
    let mostRecent: Date | null = null;
    for (const m of items) {
      const s = (m.lastStatus || '').toUpperCase();
      if (s === 'FAIL' || s === 'ERROR') failCount += 1;
      if (s === 'WARN') warnCount += 1;
      const r = precedence(s);
      if (r > topRank) { topRank = r; topStatus = s; }
      if (m.lastRunAt && (!mostRecent || m.lastRunAt > mostRecent)) mostRecent = m.lastRunAt;
    }
    let status: PipelineToolStatusValue;
    if (topRank === 0) status = 'NEVER_RUN';
    else if (topStatus === 'SKIPPED' || topStatus === 'PASS') status = 'PASS';
    else status = topStatus as PipelineToolStatusValue;

    out.push({
      toolType,
      displayName: displayName(toolType),
      status,
      failCount,
      warnCount,
      monitorCount: items.length,
      lastRunAt: mostRecent ? mostRecent.toISOString() : null,
    });
  }
  return out.sort((a, b) => {
    const aRank = a.status === 'FAIL' ? 4 : a.status === 'ERROR' ? 3 : a.status === 'WARN' ? 2 : 1;
    const bRank = b.status === 'FAIL' ? 4 : b.status === 'ERROR' ? 3 : b.status === 'WARN' ? 2 : 1;
    if (aRank !== bRank) return bRank - aRank;
    return a.displayName.localeCompare(b.displayName);
  });
}

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
      FAMILY_BY_TYPE[(m.monitorType || '').toUpperCase()] ||
      'unknown',
    lastStatus: m.lastStatus,
    lastRunAt: m.lastRunAt,
  }));

  const response: PipelineToolStatusResponse = { tools: aggregateByTool(toolMonitors) };
  return NextResponse.json(response);
}
