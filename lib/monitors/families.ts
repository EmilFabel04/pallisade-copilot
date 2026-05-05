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
