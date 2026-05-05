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
