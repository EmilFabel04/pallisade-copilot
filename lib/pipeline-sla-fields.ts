/**
 * Shared Pipeline SLA field definitions per domain.
 * Single source of truth — used by PipelineSLAEditor, PipelineSLAEditorPanel,
 * and PipelineSLAsTab (governance create modal).
 */

export interface PipelineSLAFieldDef {
  key: string;
  label: string;
  type: 'number' | 'select';
  placeholder?: string;
  options?: { value: string; label: string }[];
  unit?: string;
}

const STRICTNESS = [
  { value: 'strict', label: 'Strict — block on violation' },
  { value: 'warn', label: 'Warn — alert but continue' },
  { value: 'ignore', label: 'Ignore — no enforcement' },
];

const TOLERANCE = [
  { value: 'none', label: 'None — alert immediately' },
  { value: 'low', label: 'Low — 1 consecutive failure' },
  { value: 'medium', label: 'Medium — 2-3 consecutive' },
  { value: 'high', label: 'High — 4+ consecutive' },
];

/**
 * Complete field definitions per domain, aligned with DOMAIN_SLA_SECTIONS in types/sla.ts:
 *   warehouse:     freshness, schema, volume, anomaly, quality
 *   ingestion:     freshness, ingestion
 *   bi:            bi, freshness
 *   orchestration: orchestration
 *   transform:     transform, freshness, schema
 */
export const PIPELINE_SLA_FIELDS: Record<string, PipelineSLAFieldDef[]> = {
  ingestion: [
    // --- Ingestion ---
    { key: 'ingestion.syncLagToleranceMinutes', label: 'Sync Lag Tolerance', type: 'number', placeholder: '30', unit: 'min' },
    { key: 'ingestion.failureTolerance', label: 'Failure Tolerance', type: 'select', options: TOLERANCE },
    { key: 'ingestion.schemaDriftStrictness', label: 'Schema Drift Strictness', type: 'select', options: STRICTNESS },
    // --- Freshness ---
    { key: 'freshness.maxHours', label: 'Max Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'freshness.warningHours', label: 'Freshness Warning', type: 'number', placeholder: '12', unit: 'hrs' },
  ],

  orchestration: [
    // --- Orchestration ---
    { key: 'orchestration.runLatencyMinutes', label: 'Run Latency Threshold', type: 'number', placeholder: '60', unit: 'min' },
    { key: 'orchestration.scheduleLagMinutes', label: 'Schedule Lag Tolerance', type: 'number', placeholder: '15', unit: 'min' },
    { key: 'orchestration.failureTolerance', label: 'Failure Tolerance', type: 'select', options: TOLERANCE },
  ],

  transform: [
    // --- Transform ---
    { key: 'transform.testFailureTolerance', label: 'Test Failure Tolerance', type: 'select', options: [
      { value: 'none', label: 'None — block on any failure' },
      { value: 'warn', label: 'Warn — alert but continue' },
      { value: 'relaxed', label: 'Relaxed — allow failures' },
    ]},
    { key: 'transform.modelFreshnessHours', label: 'Model Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    // --- Freshness ---
    { key: 'freshness.maxHours', label: 'Source Freshness', type: 'number', placeholder: '48', unit: 'hrs' },
    { key: 'freshness.warningHours', label: 'Freshness Warning', type: 'number', placeholder: '24', unit: 'hrs' },
    // --- Schema ---
    { key: 'schema.strictness', label: 'Schema Strictness', type: 'select', options: STRICTNESS },
    { key: 'schema.allowEvolution', label: 'Allow Schema Evolution', type: 'select', options: [
      { value: 'true', label: 'Yes — allow additive changes' },
      { value: 'false', label: 'No — lock schema' },
    ]},
  ],

  bi: [
    // --- BI ---
    { key: 'bi.freshnessHours', label: 'Dashboard Freshness', type: 'number', placeholder: '12', unit: 'hrs' },
    { key: 'bi.upstreamBreakStrictness', label: 'Upstream Break Strictness', type: 'select', options: STRICTNESS },
    { key: 'bi.refreshFailureAlerting', label: 'Refresh Failure Alerting', type: 'select', options: [
      { value: 'immediate', label: 'Immediate' },
      { value: 'batched', label: 'Batched (daily digest)' },
      { value: 'off', label: 'Off' },
    ]},
    // --- Freshness ---
    { key: 'freshness.maxHours', label: 'Data Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'freshness.warningHours', label: 'Freshness Warning', type: 'number', placeholder: '12', unit: 'hrs' },
  ],

  warehouse: [
    // --- Freshness ---
    { key: 'freshness.maxHours', label: 'Max Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'freshness.warningHours', label: 'Warning Threshold', type: 'number', placeholder: '12', unit: 'hrs' },
    // --- Schema ---
    { key: 'schema.strictness', label: 'Schema Strictness', type: 'select', options: STRICTNESS },
    { key: 'schema.allowEvolution', label: 'Allow Schema Evolution', type: 'select', options: [
      { value: 'true', label: 'Yes — allow additive changes' },
      { value: 'false', label: 'No — lock schema' },
    ]},
    // --- Volume ---
    { key: 'volume.growthRateThreshold', label: 'Growth Rate Threshold', type: 'number', placeholder: '15', unit: '%' },
    { key: 'volume.minRows', label: 'Min Row Count', type: 'number', placeholder: '1' },
    { key: 'volume.maxRows', label: 'Max Row Count', type: 'number', placeholder: '1000000000' },
    // --- Anomaly ---
    { key: 'anomaly.sensitivity', label: 'Anomaly Sensitivity', type: 'number', placeholder: '95', unit: '%' },
    { key: 'anomaly.lookbackDays', label: 'Lookback Window', type: 'number', placeholder: '14', unit: 'days' },
    // --- Quality ---
    { key: 'quality.maxNullRate', label: 'Max Null Rate', type: 'number', placeholder: '5', unit: '%' },
    { key: 'quality.maxDuplicateRate', label: 'Max Duplicate Rate', type: 'number', placeholder: '2', unit: '%' },
  ],
};

export const PIPELINE_SLA_DOMAINS = ['ingestion', 'orchestration', 'transform', 'bi', 'warehouse'] as const;

export const DOMAIN_LABELS: Record<string, string> = {
  ingestion: 'Ingestion',
  orchestration: 'Orchestration',
  transform: 'Transformation',
  bi: 'BI / Reporting',
  warehouse: 'Warehouse',
};
