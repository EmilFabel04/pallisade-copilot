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
  | 'infrastructure'
  | 'reporting';

export type ExecutorType = 'warehouse_sql' | 'tool_api' | 'ssh' | 'bi_api';

export type TargetSelectorType =
  | 'fqn'        // database.schema.table picker
  | 'connector'  // Fivetran/Airbyte connector picker
  | 'dag'        // Airflow/Dagster DAG picker
  | 'dbt_job'    // dbt Cloud job picker
  | 'server'     // Linux server picker
  | 'bi_asset'   // BI dashboard/report picker
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
  reporting: 'Reporting / BI',
};

export const MONITOR_CATEGORY_ORDER: MonitorCategory[] = [
  'warehouse',
  'ingestion',
  'orchestration',
  'transformation',
  'infrastructure',
  'reporting',
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
    label: 'Data Freshness Check',
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
    label: 'Volume Check',
    description: 'Row count monitoring — hard thresholds, time-series anomaly detection, seasonality, detrending',
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
    key: 'NULL_CHECK',
    label: 'NULL Check',
    description: 'Detect unexpected null values — hybrid baseline z-score + hard threshold',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      { key: 'columns', label: 'Columns (comma-separated, blank = all non-PK)', type: 'text', placeholder: 'Auto-detect', advanced: true },
      { key: 'max_null_rate', label: 'Max null rate (0-1)', type: 'number', placeholder: '0.05', default_value: 0.05, advanced: true },
    ],
  },
  {
    key: 'UNIQUENESS_CHECK',
    label: 'Uniqueness Check',
    description: 'Detect duplicate values in columns expected to be unique — PK heuristic auto-detection',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      { key: 'columns', label: 'Columns (comma-separated, blank = auto-detect PKs)', type: 'text', placeholder: 'Auto-detect', advanced: true },
      { key: 'max_duplicate_rate', label: 'Max duplicate rate (0-1)', type: 'number', placeholder: '0.01', default_value: 0.01, advanced: true },
    ],
  },
  {
    key: 'RANGE_VALIDATION',
    label: 'Range Validation',
    description: 'Ensure numeric column values fall within expected bounds',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    config_schema: [
      { key: 'column', label: 'Column', type: 'text', required: true, placeholder: 'e.g. price' },
      { key: 'min_value', label: 'Min value', type: 'number', placeholder: '0' },
      { key: 'max_value', label: 'Max value', type: 'number', placeholder: '100' },
      { key: 'max_violation_pct', label: 'Max violation % (0-1)', type: 'number', placeholder: '0.01', default_value: 0.01, advanced: true },
    ],
  },
  {
    key: 'ACCEPTED_VALUES',
    label: 'Accepted Values Check',
    description: 'Ensure categorical column values are within an allowed set',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    config_schema: [
      { key: 'column', label: 'Column', type: 'text', required: true, placeholder: 'e.g. status' },
      { key: 'allowed_values', label: 'Allowed values (one per line)', type: 'multi-text', required: true, placeholder: 'active\ninactive\npending' },
      { key: 'case_sensitive', label: 'Case-sensitive comparison', type: 'checkbox', default_value: false, advanced: true },
      { key: 'max_violation_pct', label: 'Max violation % (0-1)', type: 'number', placeholder: '0.0', default_value: 0.0, advanced: true },
    ],
  },
  {
    key: 'DATA_TYPE_VALIDATION',
    label: 'Data Type Validation',
    description: 'Ensure column data types match expected definitions — auto-snapshots on first run',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    auto_configurable: true,
    config_schema: [
      { key: 'strictness', label: 'Strictness', type: 'select', default_value: 'warn', options: [
        { value: 'warn', label: 'Warn on mismatch' },
        { value: 'fail', label: 'Fail on mismatch' },
      ], advanced: true },
    ],
  },
  {
    key: 'DATE_CONSISTENCY',
    label: 'Date Consistency Check',
    description: 'Validate date column relationships (e.g., start_date <= end_date)',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: false,
    config_schema: [
      { key: 'left_column', label: 'Left column', type: 'text', required: true, placeholder: 'e.g. start_date' },
      { key: 'operator', label: 'Operator', type: 'select', required: true, default_value: '<=', options: [
        { value: '<=', label: '<= (before or equal)' },
        { value: '<', label: '< (strictly before)' },
        { value: '>=', label: '>= (after or equal)' },
        { value: '>', label: '> (strictly after)' },
        { value: '=', label: '= (equal)' },
      ]},
      { key: 'right_column', label: 'Right column', type: 'text', required: true, placeholder: 'e.g. end_date or CURRENT_DATE' },
      { key: 'max_violation_pct', label: 'Max violation % (0-1)', type: 'number', placeholder: '0.0', default_value: 0.0, advanced: true },
    ],
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
    key: 'OUTLIER_DETECTION',
    label: 'Outlier Detection',
    description: 'Statistical anomaly detection on numeric column metrics — Z-score/MAD with confidence scaling',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'fqn',
    executor_type: 'warehouse_sql',
    supports_baselines: true,
    auto_configurable: true,
    config_schema: [
      { key: 'column', label: 'Column', type: 'text', placeholder: 'e.g. revenue, order_count', required: true },
      {
        key: 'metric',
        label: 'Metric',
        type: 'select',
        default_value: 'avg',
        options: [
          { value: 'avg', label: 'Average' },
          { value: 'sum', label: 'Sum' },
          { value: 'min', label: 'Min' },
          { value: 'max', label: 'Max' },
          { value: 'stddev', label: 'Std Dev' },
          { value: 'zero_rate', label: 'Zero Rate' },
        ],
      },
      { key: 'anomaly_threshold', label: 'Z-score threshold', type: 'number', placeholder: '3.0', advanced: true },
      { key: 'lookback_days', label: 'Lookback days', type: 'number', placeholder: '30', advanced: true },
    ],
  },
  {
    key: 'REFERENTIAL',
    label: 'Referential Integrity Check',
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

  // ==========================================================================
  // WAREHOUSE OPS — Snowflake, BigQuery, Redshift
  // ==========================================================================
  {
    key: 'QUERY_PERFORMANCE',
    label: 'Query Performance',
    description: 'Detects slow queries, timeouts, and queue congestion in your warehouse',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: true,
    config_schema: [
      { key: 'query_time_threshold_seconds', label: 'Max avg query time (seconds)', type: 'number', placeholder: '300', default_value: 300 },
      { key: 'lookback_hours', label: 'Lookback hours', type: 'number', placeholder: '24', default_value: 24, advanced: true },
    ],
  },
  {
    key: 'COST_ANOMALY',
    label: 'Cost Anomaly',
    description: 'Alerts when warehouse spending spikes beyond normal patterns',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: true,
    config_schema: [
      { key: 'cost_spike_multiplier', label: 'Cost spike multiplier', type: 'number', placeholder: '1.5', default_value: 1.5 },
      { key: 'lookback_days', label: 'Rolling avg window (days)', type: 'number', placeholder: '7', default_value: 7, advanced: true },
    ],
  },
  {
    key: 'STORAGE_GROWTH',
    label: 'Storage Growth',
    description: 'Tracks abnormal storage growth rates across warehouse tables',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: true,
    config_schema: [
      { key: 'growth_rate_multiplier', label: 'Growth rate alert multiplier', type: 'number', placeholder: '2.0', default_value: 2.0 },
      { key: 'lookback_days', label: 'Trend window (days)', type: 'number', placeholder: '30', default_value: 30, advanced: true },
    ],
  },

  // ==========================================================================
  // REPORTING / BI — Looker, Tableau, Power BI, Metabase
  // ==========================================================================
  {
    key: 'BI_FRESHNESS_PROXY',
    label: 'Dashboard Freshness',
    description: 'Checks BI asset last_updated time and upstream table freshness via lineage',
    category: 'reporting',
    required_integrations: ['looker', 'tableau', 'powerbi', 'metabase'],
    target_selector_type: 'bi_asset',
    executor_type: 'bi_api',
    supports_baselines: false,
    config_schema: [
      { key: 'asset_id', label: 'BI Asset ID', type: 'text', required: true, placeholder: 'e.g. dashboard/123' },
      { key: 'asset_type', label: 'Asset Type', type: 'select', default_value: 'dashboard', options: [
        { value: 'dashboard', label: 'Dashboard' },
        { value: 'report', label: 'Report' },
        { value: 'workbook', label: 'Workbook' },
        { value: 'explore', label: 'Explore' },
        { value: 'question', label: 'Question' },
      ]},
      { key: 'max_stale_hours', label: 'Max stale hours', type: 'number', placeholder: '24', default_value: 24 },
      { key: 'check_upstream', label: 'Check upstream table freshness', type: 'checkbox', default_value: true, advanced: true },
    ],
  },
  {
    key: 'BI_UPSTREAM_BREAK_RISK',
    label: 'Upstream Break Risk',
    description: 'Counts failing monitors on upstream warehouse tables via lineage',
    category: 'reporting',
    required_integrations: ['looker', 'tableau', 'powerbi', 'metabase'],
    target_selector_type: 'bi_asset',
    executor_type: 'bi_api',
    supports_baselines: false,
    config_schema: [
      { key: 'asset_id', label: 'BI Asset ID', type: 'text', required: true, placeholder: 'e.g. dashboard/123' },
      { key: 'lookback_hours', label: 'Lookback hours', type: 'number', placeholder: '24', default_value: 24, advanced: true },
    ],
  },
  {
    key: 'BI_CONTENT_HEALTH',
    label: 'Content Health',
    description: 'Verifies BI asset exists, is accessible, and deliveries are not failing',
    category: 'reporting',
    required_integrations: ['looker', 'tableau', 'powerbi', 'metabase'],
    target_selector_type: 'bi_asset',
    executor_type: 'bi_api',
    supports_baselines: false,
    config_schema: [
      { key: 'asset_id', label: 'BI Asset ID', type: 'text', required: true, placeholder: 'e.g. dashboard/123' },
      { key: 'check_deliveries', label: 'Check scheduled deliveries', type: 'checkbox', default_value: true, advanced: true },
    ],
  },
  {
    key: 'BI_REFRESH_FAILURE',
    label: 'Refresh Failure',
    description: 'Detects BI dataset/extract refresh job failures',
    category: 'reporting',
    required_integrations: ['powerbi', 'tableau'],
    target_selector_type: 'bi_asset',
    executor_type: 'bi_api',
    supports_baselines: false,
    config_schema: [
      { key: 'asset_id', label: 'BI Asset ID', type: 'text', required: true, placeholder: 'e.g. dataset/456' },
      { key: 'workspace_id', label: 'Workspace ID', type: 'text', placeholder: 'Power BI workspace or Tableau site', advanced: true },
      { key: 'lookback_hours', label: 'Lookback hours', type: 'number', placeholder: '24', default_value: 24, advanced: true },
    ],
  },

  // ==========================================================================
  // CONTRACT CHECK — Validates data asset against its data contract
  // ==========================================================================
  {
    key: 'CONTRACT_CHECK',
    label: 'Contract Check',
    description: 'Validates a data asset against its data contract, checking per-field compliance',
    category: 'warehouse',
    required_integrations: [],
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
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
  'QUERY_PERFORMANCE', 'COST_ANOMALY', 'STORAGE_GROWTH',
  'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS',
];

export const BI_MONITOR_TYPES = [
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK',
  'BI_CONTENT_HEALTH', 'BI_REFRESH_FAILURE',
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
  QUERY_PERFORMANCE: ['bigquery', 'snowflake', 'postgres', 'redshift', 'databricks'],
  COST_ANOMALY: ['bigquery', 'snowflake', 'postgres', 'redshift', 'databricks'],
  STORAGE_GROWTH: ['bigquery', 'snowflake', 'postgres', 'redshift', 'databricks'],
  CERTIFICATE: ['linux_server'],
  SERVER_HEALTH: ['linux_server'],
  LOG_ANALYSIS: ['linux_server'],
};

/**
 * Domain-specific monitor map — maps platform domain to the set of monitors
 * that should appear when a tool node of that domain is selected.
 * Used by MultiMonitorModal for per-domain filtering.
 */
export const DOMAIN_MONITOR_MAP: Record<string, Set<string>> = {
  ingestion: new Set(['SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT']),
  orchestration: new Set(['DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE']),
  transform: new Set(['DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS']),
  warehouse: new Set(['QUERY_PERFORMANCE', 'COST_ANOMALY', 'STORAGE_GROWTH']),
  bi: new Set(['BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_CONTENT_HEALTH', 'BI_REFRESH_FAILURE']),
  infrastructure: new Set(['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS']),
};

// ---------------------------------------------------------------------------
// Asset prefill for monitor creation flows
// ---------------------------------------------------------------------------

export interface AssetPrefill {
  nodeId: string;
  fqn: string;
  name: string;
  platform?: string;
  domain?: string;
  criticality?: string;
  nodeType?: string;
  /** For tool nodes: child asset graph node IDs */
  subNodeIds?: string[];
  /** Platform-specific child items (connectors, DAGs) with their IDs */
  childItems?: Array<{ id: string; name: string; platformId: string }>;
}
