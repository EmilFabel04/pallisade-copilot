/**
 * Shared Pipeline SLA field definitions per domain.
 * Single source of truth — used by PipelineSLAEditor, PipelineSLAEditorPanel,
 * and PipelineSLAsTab (governance create modal).
 *
 * Pipeline SLAs are about TOOL-LEVEL operational health — sync failures,
 * DAG runs, build times, connector health — NOT data quality.
 * Data quality (schema, volume, anomaly, nulls) belongs in Data SLAs.
 */

export interface PipelineSLAFieldDef {
  key: string;
  label: string;
  type: 'number' | 'select';
  placeholder?: string;
  options?: { value: string; label: string }[];
  unit?: string;
}

const FAILURE_TOLERANCE = [
  { value: 'none', label: 'None — alert on first failure' },
  { value: 'low', label: 'Low — 1 consecutive failure' },
  { value: 'medium', label: 'Medium — 2-3 consecutive' },
  { value: 'high', label: 'High — 4+ consecutive' },
];


/**
 * Tool-level operational SLA fields per pipeline domain.
 *
 *   ingestion:     Fivetran, Airbyte, Stitch — sync health
 *   orchestration: Airflow, Dagster, Prefect — DAG/pipeline runs
 *   transform:     dbt, Dataform — build & test health
 *   bi:            Looker, Tableau, Power BI — dashboard refresh health
 *   warehouse:     BigQuery, Snowflake, Redshift — platform operations
 */
export const PIPELINE_SLA_FIELDS: Record<string, PipelineSLAFieldDef[]> = {
  ingestion: [
    { key: 'ingestion.syncFrequencyMinutes', label: 'Expected Sync Frequency', type: 'number', placeholder: '60', unit: 'min' },
    { key: 'ingestion.syncLagToleranceMinutes', label: 'Max Sync Lag', type: 'number', placeholder: '30', unit: 'min' },
    { key: 'ingestion.failureTolerance', label: 'Sync Failure Tolerance', type: 'select', options: FAILURE_TOLERANCE },
    { key: 'ingestion.schemaDriftStrictness', label: 'Schema Change Handling', type: 'select', options: [
      { value: 'block', label: 'Block — pause sync on schema change' },
      { value: 'warn', label: 'Warn — continue but alert' },
      { value: 'allow', label: 'Allow — auto-propagate changes' },
    ]},
    { key: 'ingestion.connectorHealthCheck', label: 'Connector Health Check', type: 'select', options: [
      { value: 'strict', label: 'Strict — alert on any degradation' },
      { value: 'normal', label: 'Normal — alert on failures only' },
      { value: 'relaxed', label: 'Relaxed — alert on extended outage' },
    ]},

  ],

  orchestration: [
    { key: 'orchestration.maxRunDurationMinutes', label: 'Max Run Duration', type: 'number', placeholder: '120', unit: 'min' },
    { key: 'orchestration.scheduleLagMinutes', label: 'Max Schedule Lag', type: 'number', placeholder: '15', unit: 'min' },
    { key: 'orchestration.failureTolerance', label: 'DAG Failure Tolerance', type: 'select', options: FAILURE_TOLERANCE },
    { key: 'orchestration.retryPolicy', label: 'Retry Policy', type: 'select', options: [
      { value: 'none', label: 'No retries — fail immediately' },
      { value: '1', label: '1 retry' },
      { value: '2', label: '2 retries' },
      { value: '3', label: '3 retries' },
    ]},
    { key: 'orchestration.taskFailureThreshold', label: 'Task Failure Threshold', type: 'number', placeholder: '1', unit: 'tasks' },
    { key: 'orchestration.slaDeadlineMinutes', label: 'SLA Deadline (from schedule)', type: 'number', placeholder: '60', unit: 'min' },

  ],

  transform: [
    { key: 'transform.maxBuildDurationMinutes', label: 'Max Build Duration', type: 'number', placeholder: '60', unit: 'min' },
    { key: 'transform.testFailureTolerance', label: 'Test Failure Handling', type: 'select', options: [
      { value: 'block', label: 'Block — fail build on test failure' },
      { value: 'warn', label: 'Warn — continue but alert' },
      { value: 'skip', label: 'Skip — ignore test results' },
    ]},
    { key: 'transform.modelFailureTolerance', label: 'Model Build Failure Tolerance', type: 'select', options: FAILURE_TOLERANCE },
    { key: 'transform.staleDependencyHours', label: 'Stale Dependency Threshold', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'transform.expectedRunFrequencyHours', label: 'Expected Run Frequency', type: 'number', placeholder: '24', unit: 'hrs' },

  ],

  bi: [
    { key: 'bi.refreshFrequencyMinutes', label: 'Expected Refresh Frequency', type: 'number', placeholder: '60', unit: 'min' },
    { key: 'bi.maxRefreshLagMinutes', label: 'Max Refresh Lag', type: 'number', placeholder: '30', unit: 'min' },
    { key: 'bi.refreshFailureTolerance', label: 'Refresh Failure Tolerance', type: 'select', options: FAILURE_TOLERANCE },
    { key: 'bi.brokenContentHandling', label: 'Broken Content Handling', type: 'select', options: [
      { value: 'block', label: 'Block — alert on any broken content' },
      { value: 'warn', label: 'Warn — flag but keep serving' },
      { value: 'ignore', label: 'Ignore — no content checks' },
    ]},
    { key: 'bi.upstreamBreakHandling', label: 'Upstream Break Handling', type: 'select', options: [
      { value: 'strict', label: 'Strict — alert when upstream fails' },
      { value: 'warn', label: 'Warn — degrade gracefully' },
      { value: 'ignore', label: 'Ignore — independent of upstream' },
    ]},

  ],

  warehouse: [
    { key: 'warehouse.maxQueryDurationSeconds', label: 'Max Query Duration', type: 'number', placeholder: '300', unit: 'sec' },
    { key: 'warehouse.loadJobFailureTolerance', label: 'Load Job Failure Tolerance', type: 'select', options: FAILURE_TOLERANCE },
    { key: 'warehouse.slotUtilizationThreshold', label: 'Slot/Credit Usage Threshold', type: 'number', placeholder: '80', unit: '%' },
    { key: 'warehouse.tableLoadFrequencyHours', label: 'Expected Table Load Frequency', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'warehouse.maintenanceWindow', label: 'Maintenance Window', type: 'select', options: [
      { value: 'none', label: 'None — always available' },
      { value: 'weekly', label: 'Weekly (Sunday 2-6 AM)' },
      { value: 'daily', label: 'Daily (2-4 AM)' },
      { value: 'custom', label: 'Custom schedule' },
    ]},

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
