// Pipeline monitor type → tool family. Multiple monitor types may share a
// family (DAG_LAST_RUN and DAG_SCHEDULE_LAG both target Airflow/Dagster).
// Used by /api/monitors/health-summary (counting distinct pipeline tools)
// and /api/monitors/pipeline-status (fallback grouping when an Integration
// link is missing).

export const PIPELINE_TYPE_TO_FAMILY: Record<string, string> = {
  SYNC_LAG: 'ingestion',
  FAILED_SYNCS: 'ingestion',
  CONNECTOR_SCHEMA_DRIFT: 'ingestion',
  DAG_LAST_RUN: 'orchestration',
  DAG_SCHEDULE_LAG: 'orchestration',
  TASK_FAILURE_RATE: 'orchestration',
  DBT_TEST_FAILURES: 'transform',
  DBT_MODEL_FRESHNESS: 'transform',
  DBT_SOURCE_FRESHNESS: 'transform',
  DBT_CORE_SOURCE_VALIDATION: 'transform',
  DBT_CORE_REF_INTEGRITY: 'transform',
  BI_FRESHNESS_PROXY: 'bi',
  BI_UPSTREAM_BREAK_RISK: 'bi',
  BI_REFRESH_FAILURE: 'bi',
  BI_CONTENT_HEALTH: 'bi',
  CERTIFICATE: 'infra',
  SERVER_HEALTH: 'infra',
  LOG_ANALYSIS: 'infra',
};

// IntegrationType enum value (uppercase) → canonical toolType string (lowercase).
// Used by health-summary and pipeline-status routes to resolve toolType from
// integration.type so both routes count the same way.
export const TOOL_TYPE_BY_INTEGRATION_TYPE: Record<string, string> = {
  FIVETRAN: 'fivetran', AIRBYTE: 'airbyte', STITCH: 'stitch',
  AIRFLOW: 'airflow', DAGSTER: 'dagster', PREFECT: 'prefect', N8N: 'n8n',
  DBT_CLOUD: 'dbt_cloud', DBT_CORE: 'dbt_core',
  TABLEAU: 'tableau', LOOKER: 'looker', POWERBI: 'powerbi', METABASE: 'metabase',
  SNOWFLAKE: 'snowflake', BIGQUERY: 'bigquery', POSTGRES: 'postgres', REDSHIFT: 'redshift',
  LINUX_SERVER: 'linux_server',
};

// Reverse map: concrete tool key → its family. Used by PipelineToolDetailPanel
// to match monitors whose monitorType falls in the same family as the tile's toolType.
// For example, tool.toolType === 'airflow' and monitor has no integration but is
// DAG_LAST_RUN → family 'orchestration' === TOOL_TO_FAMILY['airflow'] → include it.
export const TOOL_TO_FAMILY: Record<string, string> = {
  fivetran: 'ingestion', airbyte: 'ingestion', stitch: 'ingestion',
  airflow: 'orchestration', dagster: 'orchestration', prefect: 'orchestration', n8n: 'orchestration',
  dbt_cloud: 'transform', dbt_core: 'transform',
  looker: 'bi', tableau: 'bi', powerbi: 'bi', metabase: 'bi',
  linux_server: 'infra',
};
