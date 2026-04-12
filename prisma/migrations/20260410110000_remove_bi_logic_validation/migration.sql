-- Remove the unused BI_LOGIC_VALIDATION value from MonitorKind.
-- Recreate the enum without the value and rebind the Monitor.monitorType
-- column to the new enum type.

CREATE TYPE "MonitorKind_new" AS ENUM (
  'FRESHNESS',
  'VOLUME',
  'SCHEMA_CHANGE',
  'REFERENTIAL',
  'CUSTOM_SQL',
  'ANOMALY',
  'NULL_CHECK',
  'UNIQUENESS_CHECK',
  'RANGE_VALIDATION',
  'ACCEPTED_VALUES',
  'DATE_CONSISTENCY',
  'DATA_TYPE_VALIDATION',
  'OUTLIER_DETECTION',
  'NULL_RATE',
  'UNIQUENESS',
  'DISTRIBUTION',
  'CERTIFICATE',
  'SERVER_HEALTH',
  'LOG_ANALYSIS',
  'SYNC_LAG',
  'FAILED_SYNCS',
  'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN',
  'DAG_SCHEDULE_LAG',
  'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES',
  'DBT_MODEL_FRESHNESS',
  'DBT_SOURCE_FRESHNESS',
  'BI_FRESHNESS_PROXY',
  'BI_UPSTREAM_BREAK_RISK',
  'BI_CONTENT_HEALTH',
  'BI_REFRESH_FAILURE',
  'AI_PROMPT'
);

ALTER TABLE "Monitor"
  ALTER COLUMN "monitorType" TYPE "MonitorKind_new"
  USING ("monitorType"::text::"MonitorKind_new");

ALTER TYPE "MonitorKind" RENAME TO "MonitorKind_old";
ALTER TYPE "MonitorKind_new" RENAME TO "MonitorKind";
DROP TYPE "MonitorKind_old";
