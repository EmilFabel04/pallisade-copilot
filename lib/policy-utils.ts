/**
 * Shared policy utilities for comparing monitor config against resolved policies.
 *
 * Used by MonitorEditPanel, plan detail page, schedule dashboard, and cards
 * to determine policy compliance status without relying on the stored
 * policyOverrides DB field.
 */

// Maps: monitorType → { configField → [policySection, policySectionField] }
type PolicyFieldMap = Record<string, Record<string, [string, string]>>;

export const POLICY_FIELD_MAP: PolicyFieldMap = {
  FRESHNESS: {
    max_hours: ['freshness', 'maxHours'],
    warning_hours: ['freshness', 'warningHours'],
  },
  VOLUME: {
    min_rows: ['volume', 'minRows'],
    max_rows: ['volume', 'maxRows'],
    growth_rate_threshold: ['volume', 'growthRateThreshold'],
  },
  OUTLIER_DETECTION: {
    anomaly_threshold: ['anomaly', 'sensitivity'],
    lookback_days: ['anomaly', 'lookbackDays'],
  },
  ANOMALY: {
    anomaly_threshold: ['anomaly', 'sensitivity'],
    lookback_days: ['anomaly', 'lookbackDays'],
  },
  NULL_CHECK: {
    max_null_rate: ['quality', 'maxNullRate'],
  },
  UNIQUENESS_CHECK: {
    max_duplicate_rate: ['quality', 'maxDuplicateRate'],
  },
  SCHEMA_CHANGE: {
    strictness: ['schema', 'strictness'],
  },
  SYNC_LAG: {
    max_lag_minutes: ['ingestion', 'syncLagToleranceMinutes'],
  },
  FAILED_SYNCS: {
    failure_tolerance: ['ingestion', 'failureTolerance'],
  },
  CONNECTOR_SCHEMA_DRIFT: {
    strictness: ['ingestion', 'schemaDriftStrictness'],
  },
  BI_FRESHNESS_PROXY: {
    max_stale_hours: ['bi', 'freshnessHours'],
  },
  BI_UPSTREAM_BREAK_RISK: {
    strictness: ['bi', 'upstreamBreakStrictness'],
  },
  DAG_LAST_RUN: {
    max_stale_hours: ['orchestration', 'runLatencyMinutes'],
  },
  DAG_SCHEDULE_LAG: {
    max_lag_minutes: ['orchestration', 'scheduleLagMinutes'],
  },
  TASK_FAILURE_RATE: {
    max_failure_pct: ['orchestration', 'failureTolerance'],
  },
  DBT_TEST_FAILURES: {
    failure_tolerance: ['transform', 'testFailureTolerance'],
  },
  DBT_MODEL_FRESHNESS: {
    max_hours: ['transform', 'modelFreshnessHours'],
  },
  DBT_SOURCE_FRESHNESS: {
    max_hours: ['transform', 'modelFreshnessHours'],
  },
};

/** Piecewise linear: sensitivity (0-1) → z-score threshold */
export function sensitivityToZscore(sensitivity: number): number {
  if (sensitivity >= 0.99) return 2.0;
  if (sensitivity >= 0.95) return 2.0 + (0.99 - sensitivity) / (0.99 - 0.95) * 1.0;
  if (sensitivity >= 0.90) return 3.0 + (0.95 - sensitivity) / (0.95 - 0.90) * 0.5;
  if (sensitivity >= 0.80) return 3.5 + (0.90 - sensitivity) / (0.90 - 0.80) * 0.5;
  return 4.0 + (0.80 - sensitivity) / (0.80 - 0.50) * 1.0;
}

/** Get the policy value for a config field, converting sensitivity→zscore if needed */
export function getPolicyValueForField(
  monitorType: string,
  configField: string,
  resolvedPolicy: Record<string, any> | null,
): any {
  if (!resolvedPolicy) return undefined;
  const map = POLICY_FIELD_MAP[monitorType];
  if (!map) return undefined;
  const mapping = map[configField];
  if (!mapping) return undefined;

  const [section, policyField] = mapping;
  const sectionData = resolvedPolicy[section];
  if (!sectionData || typeof sectionData !== 'object') return undefined;

  let raw = sectionData[policyField];
  if (policyField === 'sensitivity' && raw !== undefined && raw !== null) {
    raw = sensitivityToZscore(Number(raw));
  }
  return raw;
}

const HIGHER_IS_LESS_STRICT = new Set([
  'max_hours', 'warning_hours', 'max_null_rate', 'max_duplicate_rate',
  'max_outlier_pct', 'max_lag_minutes', 'max_stale_hours',
  'max_latency_minutes', 'max_schedule_lag_minutes', 'growth_rate_threshold',
  'anomaly_threshold', 'max_failure_pct',
]);
const LOWER_IS_LESS_STRICT = new Set(['min_rows']);
const STRICTNESS_ORDER: Record<string, number> = { strict: 0, warn: 1, ignore: 2 };
const TOLERANCE_ORDER: Record<string, number> = { strict: 0, normal: 1, relaxed: 2 };

export function isLessStrictClient(fieldKey: string, currentValue: any, policyValue: any): boolean {
  if (currentValue == null || policyValue == null) return false;

  // Enum fields
  if (fieldKey === 'strictness' || fieldKey.endsWith('Strictness')) {
    const cur = STRICTNESS_ORDER[String(currentValue).toLowerCase()] ?? 99;
    const pol = STRICTNESS_ORDER[String(policyValue).toLowerCase()] ?? 99;
    return cur > pol;
  }
  if (fieldKey === 'failure_tolerance' || fieldKey.endsWith('Tolerance')) {
    const cur = TOLERANCE_ORDER[String(currentValue).toLowerCase()] ?? 99;
    const pol = TOLERANCE_ORDER[String(policyValue).toLowerCase()] ?? 99;
    return cur > pol;
  }

  const cur = Number(currentValue);
  const pol = Number(policyValue);
  if (Number.isNaN(cur) || Number.isNaN(pol)) return false;

  if (HIGHER_IS_LESS_STRICT.has(fieldKey)) return cur > pol;
  if (LOWER_IS_LESS_STRICT.has(fieldKey)) return cur < pol;
  return false;
}

export type MonitorPolicyStatus = 'policy' | 'override' | 'violation' | 'none';

/**
 * Compute the policy compliance status for a monitor by comparing its
 * config values against the resolved policy. Works without the stored
 * policyOverrides DB field.
 */
export function getMonitorPolicyStatus(
  monitorType: string,
  config: Record<string, any> | null,
  resolvedPolicy: Record<string, any> | null,
): { status: MonitorPolicyStatus; overriddenFields: string[]; violationFields: string[] } {
  if (!resolvedPolicy || !config || Object.keys(config).length === 0 || resolvedPolicy.status === 'none') {
    return { status: 'none', overriddenFields: [], violationFields: [] };
  }

  const map = POLICY_FIELD_MAP[monitorType];
  if (!map || Object.keys(map).length === 0) {
    return { status: 'none', overriddenFields: [], violationFields: [] };
  }

  const overriddenFields: string[] = [];
  const violationFields: string[] = [];

  for (const configField of Object.keys(map)) {
    const policyVal = getPolicyValueForField(monitorType, configField, resolvedPolicy);
    if (policyVal === undefined || policyVal === null) continue;

    const configVal = config[configField];
    if (configVal === undefined || configVal === null) continue;

    // Compare: if config value differs from policy value, it's an override
    if (String(configVal) !== String(policyVal)) {
      overriddenFields.push(configField);
      if (isLessStrictClient(configField, configVal, policyVal)) {
        violationFields.push(configField);
      }
    }
  }

  if (violationFields.length > 0) return { status: 'violation', overriddenFields, violationFields };
  if (overriddenFields.length > 0) return { status: 'override', overriddenFields, violationFields };
  return { status: 'policy', overriddenFields, violationFields };
}
