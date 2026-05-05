import type {
  PipelineToolStatus,
  PipelineToolStatusValue,
} from '@/types/monitors-summary';

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

export type ToolMonitor = {
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
