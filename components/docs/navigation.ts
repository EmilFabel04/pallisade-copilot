export interface NavItem {
  title: string;
  slug: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const docsNavigation: NavSection[] = [
  {
    title: 'User Guides',
    items: [
      { title: 'Getting Started', slug: 'getting-started' },
      { title: 'AI Assistant', slug: 'copilot' },
      { title: 'Data Lineage', slug: 'lineage' },
      { title: 'Pipeline Builder', slug: 'pipeline-builder' },
      { title: 'Scheduled Monitoring', slug: 'scheduled-monitoring' },
      { title: 'Sources Browser', slug: 'sources-browser' },
      { title: 'Change Plans', slug: 'change-plans' },
      { title: 'Artifacts', slug: 'artifacts' },
      { title: 'Team & Access Control', slug: 'team-access' },
    ],
  },
  {
    title: 'Integrations',
    items: [
      { title: 'BigQuery', slug: 'integrations/bigquery' },
      { title: 'Snowflake', slug: 'integrations/snowflake' },
      { title: 'PostgreSQL', slug: 'integrations/postgres' },
      { title: 'Redshift', slug: 'integrations/redshift' },
      { title: 'Databricks', slug: 'integrations/databricks' },
      { title: 'SQL Server', slug: 'integrations/sql-server' },
      { title: 'dbt Cloud', slug: 'integrations/dbt-cloud' },
      { title: 'dbt Core', slug: 'integrations/dbt-core' },
      { title: 'Apache Airflow', slug: 'integrations/airflow' },
      { title: 'Dagster', slug: 'integrations/dagster' },
      { title: 'Prefect', slug: 'integrations/prefect' },
      { title: 'Fivetran', slug: 'integrations/fivetran' },
      { title: 'Airbyte', slug: 'integrations/airbyte' },
      { title: 'Looker', slug: 'integrations/looker' },
      { title: 'Tableau', slug: 'integrations/tableau' },
      { title: 'Power BI', slug: 'integrations/powerbi' },
      { title: 'Metabase', slug: 'integrations/metabase' },
      { title: 'Slack', slug: 'integrations/slack' },
      { title: 'Microsoft Teams', slug: 'integrations/teams' },
      { title: 'PagerDuty', slug: 'integrations/pagerduty' },
      { title: 'OpsGenie', slug: 'integrations/opsgenie' },
      { title: 'Linux / SSH', slug: 'integrations/linux-ssh' },
    ],
  },
  {
    title: 'Technical Reference',
    items: [
      { title: 'Architecture', slug: 'reference/architecture' },
      { title: 'API Reference', slug: 'reference/api' },
      { title: 'Lineage Engine', slug: 'reference/lineage-engine' },
      { title: 'Monitor System', slug: 'reference/monitor-system' },
      { title: 'Copilot System', slug: 'reference/copilot-system' },
      { title: 'Data Model', slug: 'reference/data-model' },
      { title: 'Self-Hosting', slug: 'reference/self-hosting' },
    ],
  },
];

/** Flatten all nav items into ordered array for prev/next navigation */
export function getFlatNavItems(): NavItem[] {
  return docsNavigation.flatMap((section) => section.items);
}

/** Find the section a slug belongs to */
export function findSectionForSlug(slug: string): NavSection | undefined {
  return docsNavigation.find((section) =>
    section.items.some((item) => item.slug === slug)
  );
}
