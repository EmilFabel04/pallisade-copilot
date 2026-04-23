import { SourceCapability } from './types';

const TOOL_CAPABILITIES: Record<string, SourceCapability[]> = {
  // Warehouses
  bigquery: ['Query', 'Metadata', 'Lineage'],
  snowflake: ['Query', 'Metadata', 'Lineage'],
  postgres: ['Query', 'Metadata'],
  redshift: ['Query', 'Metadata'],
  sqlserver: ['Query', 'Metadata'],
  azure_sql: ['Query', 'Metadata'],
  azure_synapse: ['Query', 'Metadata'],
  databricks: ['Query', 'Metadata', 'Lineage', 'Logs'],
  mysql: ['Query', 'Metadata'],

  // Ingestion
  fivetran: ['Logs', 'Metadata'],
  airbyte: ['Logs', 'Metadata'],
  stitch: ['Metadata'],

  // Transformation
  dbt_cloud: ['Metadata', 'Lineage'],
  dbt_core: ['Metadata', 'Lineage'],

  // Orchestration
  airflow: ['Logs', 'Lineage'],
  dagster: ['Logs', 'Lineage'],
  prefect: ['Logs'],
  n8n: ['Logs'],

  // Reporting
  looker: ['Metadata', 'Lineage'],
  tableau: ['Metadata', 'Lineage'],
  powerbi: ['Metadata', 'Lineage'],
  metabase: ['Metadata', 'Lineage'],

  // Storage
  amazon_s3: ['Metadata'],
  gcs: ['Metadata'],
  adls: ['Metadata'],

  // Version control
  github: ['Write', 'Metadata'],
};

export function getCapabilities(toolType: string, pairedToolTypes?: string[]): SourceCapability[] {
  const base = TOOL_CAPABILITIES[toolType] || ['Metadata'];
  const caps = [...base];

  // dbt + github pairing enables Write
  if (
    (toolType === 'dbt_cloud' || toolType === 'dbt_core') &&
    pairedToolTypes?.includes('github') &&
    !caps.includes('Write')
  ) {
    caps.push('Write');
  }

  return caps;
}

export const CAPABILITY_CONFIG: Record<SourceCapability, { label: string; color: string; bg: string }> = {
  Query: { label: 'Query', color: 'text-indigo-400', bg: 'bg-indigo-500/15' },
  Logs: { label: 'Logs', color: 'text-cyan-400', bg: 'bg-cyan-500/15' },
  Lineage: { label: 'Lineage', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  Metadata: { label: 'Metadata', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
  Write: { label: 'Write', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  MCP: { label: 'MCP', color: 'text-purple-400', bg: 'bg-purple-500/15' },
};
