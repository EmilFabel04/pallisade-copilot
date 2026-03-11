/**
 * Monitor Catalog — Single source of truth for all monitor definitions.
 *
 * Consumed by:
 * - Frontend: CreateTaskModal, MonitorConfigForm (dynamic rendering)
 * - API: /api/schedule/monitor-catalog (filtering by connected integrations)
 *
 * The Python backend does NOT import this file; it only needs the monitorType
 * string key to route execution via TOOL_MONITOR_REGISTRY / MONITOR_REGISTRY.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MonitorCategory =
  | 'warehouse'
  | 'ingestion'
  | 'orchestration'
  | 'transformation'
  | 'infrastructure';

export type ExecutorType = 'warehouse_sql' | 'tool_api' | 'ssh';

export type TargetSelectorType =
  | 'fqn'        // database.schema.table picker
  | 'connector'  // Fivetran/Airbyte connector picker
  | 'dag'        // Airflow/Dagster DAG picker
  | 'dbt_job'    // dbt Cloud job picker
  | 'server'     // Linux server picker
  | 'none';      // No target needed

export interface ConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'select' | 'textarea' | 'checkbox' | 'multi-text';
  placeholder?: string;
  default_value?: any;
  required?: boolean;
  options?: Array<{ value: string; label: string }>;
  help_text?: string;
  /** Hidden under "Advanced Settings" toggle when true */
  advanced?: boolean;
}

export interface MonitorDefinition {
  key: string;
  label: string;
  description: string;
  category: MonitorCategory;
  /** toolType values from PipelineNode. OR logic: any ONE must be connected. */
  required_integrations: string[];
  target_selector_type: TargetSelectorType;
  config_schema: ConfigField[];
  executor_type: ExecutorType;
  supports_baselines: boolean;
  /** Backend can auto-detect config values from warehouse/tool metadata */
  auto_configurable?: boolean;
}

// ---------------------------------------------------------------------------
// Display constants
// ---------------------------------------------------------------------------

export const MONITOR_CATEGORY_LABELS: Record<MonitorCategory, string> = {
  warehouse: 'Data Quality',
  ingestion: 'Ingestion',
  orchestration: 'Orchestration',
  transformation: 'Transformation',
  infrastructure: 'Infrastructure',
};

export const MONITOR_CATEGORY_ORDER: MonitorCategory[] = [
  'warehouse',
  'ingestion',
  'orchestration',
  'transformation',
  'infrastructure',
];

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------

const WAREHOUSE_TOOL_TYPES = [
  'bigquery', 'snowflake', 'postgres', 'redshift',
  'databricks', 'sqlserver', 'azure_sql', 'azure_synapse',
];

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

export const MONITOR_CATALOG: MonitorDefinition[] = [
  // ==========================================================================
  // WAREHOUSE — Data Quality
  // ==========================================================================
  {
    key: 'FRESHNESS',
    label: 'Freshness',
    description: 'Auto-detects timestamp column & alert threshold',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      { key: 'timestamp_column', label: 'Timestamp column', type: 'text', placeholder: 'Auto-detect', advanced: true },
      { key: 'max_hours', label: 'Max hours since last update', type: 'number', placeholder: 'Auto-compute from history', advanced: true },
    ],
  },
  {
    key: 'VOLUME',
    label: 'Volume',
    description: 'Baseline-driven row count anomaly detection (auto-learns expected range)',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      { key: 'min_rows', label: 'Min expected rows', type: 'number', placeholder: 'Auto-compute (baseline - 3\u03C3)', advanced: true },
      { key: 'max_rows', label: 'Max expected rows', type: 'number', placeholder: 'Auto-compute (baseline + 3\u03C3)', advanced: true },
    ],
  },
  {
    key: 'SCHEMA_CHANGE',
    label: 'Schema Change',
    description: 'Detect column additions/removals',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    auto_configurable: true,
    config_schema: [],
  },
  {
    key: 'NULL_RATE',
    label: 'Null Rate',
    description: 'Scans all columns for unexpected null spikes',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [],
  },
  {
    key: 'UNIQUENESS',
    label: 'Uniqueness',
    description: 'Detects drops in column uniqueness (key degradation)',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      {
        key: 'column',
        label: 'Column',
        type: 'text',
        placeholder: 'Leave blank to check all columns',
        help_text: 'Specific column to monitor, or leave blank to auto-discover all columns.',
        advanced: true,
      },
    ],
  },
  {
    key: 'DISTRIBUTION',
    label: 'Distribution',
    description: 'Detects shifts in numeric column averages',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [],
  },
  {
    key: 'CUSTOM_SQL',
    label: 'Custom SQL',
    description: 'Run a custom SQL check (must return a single numeric value)',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    config_schema: [
      {
        key: 'sql',
        label: 'Custom SQL query',
        type: 'textarea',
        required: true,
        placeholder: "SELECT COUNT(*) FROM orders WHERE created_at > NOW() - INTERVAL '24 hours'",
      },
    ],
  },
  {
    key: 'ANOMALY',
    label: 'Anomaly',
    description: 'Z-score detection on any metric across all columns',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      {
        key: 'metric',
        label: 'Metric',
        type: 'select',
        default_value: 'row_count',
        options: [
          { value: 'row_count', label: 'Row Count' },
          { value: 'avg', label: 'Average' },
          { value: 'sum', label: 'Sum' },
          { value: 'null_rate', label: 'Null Rate' },
          { value: 'distinct_count', label: 'Distinct Count' },
        ],
        advanced: true,
      },
      { key: 'anomaly_threshold', label: 'Z-score threshold', type: 'number', placeholder: '3.0', advanced: true },
      { key: 'lookback_days', label: 'Lookback days', type: 'number', placeholder: '30', advanced: true },
      { key: 'timestamp_column', label: 'Timestamp column', type: 'text', placeholder: 'Auto-detect', advanced: true },
    ],
  },
  {
    key: 'REFERENTIAL',
    label: 'Referential Integrity',
    description: 'Check foreign key references exist in parent table',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    config_schema: [
      { key: 'parent_table', label: 'Parent table (FQN)', type: 'text', required: true, placeholder: 'dataset.parent_table' },
      { key: 'child_column', label: 'Child column (FK)', type: 'text', required: true, placeholder: 'parent_id' },
      { key: 'parent_column', label: 'Parent column (PK)', type: 'text', required: true, placeholder: 'id' },
    ],
  },

  // ==========================================================================
  // INGESTION — Fivetran / Airbyte
  // ==========================================================================
  {
    key: 'SYNC_LAG',
    label: 'Sync Lag',
    description: 'Alert when connector sync lags behind expected schedule',
    category: 'ingestion',
    required_integrations: ['fivetran', 'airbyte'],
    target_selector_type: 'connector',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'connector_id',
        label: 'Connector ID',
        type: 'text',
        required: true,
        placeholder: 'e.g. speak_strongly',
        help_text: 'Fivetran connector ID (from connector settings)',
      },
      { key: 'max_lag_minutes', label: 'Max lag (minutes)', type: 'number', placeholder: 'Auto from sync frequency', advanced: true },
    ],
  },
  {
    key: 'FAILED_SYNCS',
    label: 'Failed Syncs',
    description: 'Detect connectors with recent sync failures',
    category: 'ingestion',
    required_integrations: ['fivetran', 'airbyte'],
    target_selector_type: 'connector',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'connector_id',
        label: 'Connector ID',
        type: 'text',
        required: true,
        placeholder: 'e.g. speak_strongly',
      },
      { key: 'lookback_hours', label: 'Lookback hours', type: 'number', placeholder: '24', default_value: 24, advanced: true },
    ],
  },
  {
    key: 'CONNECTOR_SCHEMA_DRIFT',
    label: 'Schema Drift (Connector)',
    description: 'Detect schema changes at the connector level',
    category: 'ingestion',
    required_integrations: ['fivetran', 'airbyte'],
    target_selector_type: 'connector',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'connector_id',
        label: 'Connector ID',
        type: 'text',
        required: true,
        placeholder: 'e.g. speak_strongly',
      },
    ],
  },

  // ==========================================================================
  // ORCHESTRATION — Airflow / Dagster
  // ==========================================================================
  {
    key: 'DAG_LAST_RUN',
    label: 'DAG Last Run',
    description: 'Alert when a DAG last run failed or is stale',
    category: 'orchestration',
    required_integrations: ['airflow', 'dagster'],
    target_selector_type: 'dag',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'dag_id',
        label: 'DAG ID',
        type: 'text',
        required: true,
        placeholder: 'e.g. etl_daily_pipeline',
      },
      { key: 'max_stale_hours', label: 'Max hours since last success', type: 'number', placeholder: 'Auto from schedule', advanced: true },
    ],
  },
  {
    key: 'DAG_SCHEDULE_LAG',
    label: 'DAG Schedule Lag',
    description: 'Alert when DAG runs are behind schedule',
    category: 'orchestration',
    required_integrations: ['airflow', 'dagster'],
    target_selector_type: 'dag',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'dag_id',
        label: 'DAG ID',
        type: 'text',
        required: true,
        placeholder: 'e.g. etl_daily_pipeline',
      },
      { key: 'max_lag_minutes', label: 'Max lag (minutes)', type: 'number', placeholder: '30', default_value: 30, advanced: true },
    ],
  },
  {
    key: 'TASK_FAILURE_RATE',
    label: 'Task Failure Rate',
    description: 'Alert when task failure rate exceeds threshold',
    category: 'orchestration',
    required_integrations: ['airflow', 'dagster'],
    target_selector_type: 'dag',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'dag_id',
        label: 'DAG ID',
        type: 'text',
        required: true,
        placeholder: 'e.g. etl_daily_pipeline',
      },
      { key: 'max_failure_pct', label: 'Max failure %', type: 'number', placeholder: '10', default_value: 10, advanced: true },
      { key: 'lookback_hours', label: 'Lookback hours', type: 'number', placeholder: '24', default_value: 24, advanced: true },
    ],
  },

  // ==========================================================================
  // TRANSFORMATION — dbt Cloud / dbt Core
  // ==========================================================================
  {
    key: 'DBT_TEST_FAILURES',
    label: 'Test Failures',
    description: 'Alert on dbt test failures from latest run',
    category: 'transformation',
    required_integrations: ['dbt_cloud', 'dbt_core'],
    target_selector_type: 'dbt_job',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'job_id',
        label: 'dbt Cloud Job ID',
        type: 'number',
        required: true,
        placeholder: 'e.g. 12345',
        help_text: 'Find this in dbt Cloud under Jobs > Settings',
      },
      {
        key: 'include_warnings',
        label: 'Include warnings as failures',
        type: 'checkbox',
        default_value: false,
        advanced: true,
      },
    ],
  },
  {
    key: 'DBT_MODEL_FRESHNESS',
    label: 'Model Freshness',
    description: 'Alert when dbt model was last built too long ago',
    category: 'transformation',
    required_integrations: ['dbt_cloud', 'dbt_core'],
    target_selector_type: 'dbt_job',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'job_id',
        label: 'dbt Cloud Job ID',
        type: 'number',
        required: true,
        placeholder: 'e.g. 12345',
      },
      { key: 'max_hours', label: 'Max hours since last run', type: 'number', placeholder: '24', default_value: 24 },
    ],
  },
  {
    key: 'DBT_SOURCE_FRESHNESS',
    label: 'Source Freshness',
    description: 'Monitor dbt source freshness SLA compliance',
    category: 'transformation',
    required_integrations: ['dbt_cloud', 'dbt_core'],
    target_selector_type: 'dbt_job',
    executor_type: 'tool_api',
    supports_baselines: false,
    config_schema: [
      {
        key: 'job_id',
        label: 'dbt Cloud Job ID',
        type: 'number',
        required: true,
        placeholder: 'e.g. 12345',
      },
    ],
  },

  // ==========================================================================
  // INFRASTRUCTURE — Linux Server
  // ==========================================================================
  {
    key: 'CERTIFICATE',
    label: 'Certificate',
    description: 'Detects expiring or missing TLS/SSL certificates',
    category: 'infrastructure',
    required_integrations: ['linux_server'],
    target_selector_type: 'server',
    executor_type: 'ssh',
    supports_baselines: false,
    config_schema: [
      { key: 'cert_paths', label: 'Certificate paths (one per line)', type: 'multi-text', placeholder: '/etc/ssl/certs/server.crt', advanced: true },
      { key: 'warn_days', label: 'Warn (days before expiry)', type: 'number', placeholder: '30', default_value: 30, advanced: true },
      { key: 'fail_days', label: 'Fail (days before expiry)', type: 'number', placeholder: '7', default_value: 7, advanced: true },
    ],
  },
  {
    key: 'SERVER_HEALTH',
    label: 'Server Health',
    description: 'Monitors CPU, memory, disk usage',
    category: 'infrastructure',
    required_integrations: ['linux_server'],
    target_selector_type: 'server',
    executor_type: 'ssh',
    supports_baselines: false,
    auto_configurable: true,
    config_schema: [],
  },
  {
    key: 'LOG_ANALYSIS',
    label: 'Log Analysis',
    description: 'Scans server logs for error patterns',
    category: 'infrastructure',
    required_integrations: ['linux_server'],
    target_selector_type: 'server',
    executor_type: 'ssh',
    supports_baselines: false,
    config_schema: [
      { key: 'log_paths', label: 'Log file paths', type: 'multi-text', required: true, placeholder: '/var/log/syslog' },
      { key: 'error_patterns', label: 'Error patterns (comma-separated)', type: 'text', placeholder: 'ERROR, FATAL, CRITICAL', advanced: true },
    ],
  },
];

// ---------------------------------------------------------------------------
// Filtering & grouping functions
// ---------------------------------------------------------------------------

/**
 * Given connected tool types from PipelineNodes, return applicable monitors.
 * A monitor is available if ANY of its required_integrations is connected.
 */
export function getAvailableMonitors(
  connectedToolTypes: string[],
): MonitorDefinition[] {
  const normalized = new Set(connectedToolTypes.map((t) => t.toLowerCase()));
  return MONITOR_CATALOG.filter((monitor) =>
    monitor.required_integrations.some((req) => normalized.has(req.toLowerCase())),
  );
}

/**
 * Group monitors by category in display order.
 */
export function groupMonitorsByCategory(
  monitors: MonitorDefinition[],
): Array<{ category: MonitorCategory; label: string; monitors: MonitorDefinition[] }> {
  return MONITOR_CATEGORY_ORDER.map((category) => ({
    category,
    label: MONITOR_CATEGORY_LABELS[category],
    monitors: monitors.filter((m) => m.category === category),
  })).filter((group) => group.monitors.length > 0);
}

/**
 * Find a monitor definition by key.
 */
export function getMonitorDefinition(key: string): MonitorDefinition | undefined {
  return MONITOR_CATALOG.find((m) => m.key === key);
}

// Tool monitor type sets for route-level detection
export const TOOL_MONITOR_TYPES = [
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
];

export const TOOL_NODE_TYPE_MAP: Record<string, string[]> = {
  SYNC_LAG: ['fivetran', 'airbyte'],
  FAILED_SYNCS: ['fivetran', 'airbyte'],
  CONNECTOR_SCHEMA_DRIFT: ['fivetran', 'airbyte'],
  DAG_LAST_RUN: ['airflow', 'dagster'],
  DAG_SCHEDULE_LAG: ['airflow', 'dagster'],
  TASK_FAILURE_RATE: ['airflow', 'dagster'],
  DBT_TEST_FAILURES: ['dbt_cloud', 'dbt_core'],
  DBT_MODEL_FRESHNESS: ['dbt_cloud', 'dbt_core'],
  DBT_SOURCE_FRESHNESS: ['dbt_cloud', 'dbt_core'],
};
