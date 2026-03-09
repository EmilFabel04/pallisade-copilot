/**
 * ToolIcon coverage test.
 *
 * Ensures every Prisma IntegrationType enum value has a corresponding
 * SVG icon in the TOOL_SVGS registry (exported as INTEGRATION_TYPES).
 *
 * To run (with vitest):
 *   npx vitest run lib/__tests__/tool-icon.test.ts
 *
 * To run (with jest + ts-jest):
 *   npx jest lib/__tests__/tool-icon.test.ts
 */

import { INTEGRATION_TYPES } from '@/components/icons/ToolIcon';

// All values from the Prisma IntegrationType enum (lowercased).
// Keep in sync with prisma/schema.prisma.
const PRISMA_INTEGRATION_TYPES = [
  // Warehouses
  'snowflake',
  'bigquery',
  'postgres',
  'redshift',
  'sqlserver',
  'azure_sql',
  'azure_synapse',
  'databricks',
  // Ingestion
  'fivetran',
  'airbyte',
  'stitch',
  // Transformation / Orchestration
  'dbt_cloud',
  'dbt_core',
  'airflow',
  'dagster',
  'prefect',
  'n8n',
  // Reporting / BI
  'tableau',
  'looker',
  'powerbi',
  'metabase',
  // Observability
  'elementary',
  'monte_carlo',
  'bigeye',
  'soda',
  // Cloud Storage
  'amazon_s3',
  'gcs',
  'adls',
  // Version Control
  'github',
  'gitlab',
  'bitbucket',
  // Notifications
  'slack',
  'pagerduty',
  'opsgenie',
  'teams',
  // Infrastructure
  'linux_server',
  // Other
  'jira',
  'custom_webhook',
];

describe('ToolIcon coverage', () => {
  it.each(PRISMA_INTEGRATION_TYPES)(
    'has an SVG mapping for %s',
    (type) => {
      expect(INTEGRATION_TYPES).toContain(type);
    },
  );

  it('has no duplicate keys in INTEGRATION_TYPES', () => {
    const unique = new Set(INTEGRATION_TYPES);
    expect(unique.size).toBe(INTEGRATION_TYPES.length);
  });
});
