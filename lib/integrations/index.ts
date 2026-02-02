/**
 * Pallisade Native Integrations
 * 
 * Enterprise-grade integrations with proper OAuth, error handling,
 * and two-way data flow.
 */

export * from './slack';
export * from './pagerduty';
export * from './jira';
export * from './teams';
export * from './email';
export * from './opsgenie';

// Integration registry
export const INTEGRATIONS = {
  // ===== NOTIFICATIONS =====
  notifications: {
    slack: {
      id: 'slack',
      name: 'Slack',
      description: 'Send alerts to Slack channels',
      category: 'notifications',
      icon: '💬',
      authType: 'webhook', // or 'oauth'
      features: ['alerts', 'incident_updates', 'daily_digest'],
      configFields: [
        { name: 'webhook_url', label: 'Webhook URL', type: 'url', required: true },
        { name: 'channel', label: 'Default Channel', type: 'text', required: false },
      ],
    },
    pagerduty: {
      id: 'pagerduty',
      name: 'PagerDuty',
      description: 'Create incidents and escalate alerts',
      category: 'notifications',
      icon: '🚨',
      authType: 'api_key',
      features: ['incidents', 'escalation', 'on_call'],
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true },
        { name: 'service_id', label: 'Service ID', type: 'text', required: true },
        { name: 'routing_key', label: 'Routing Key', type: 'password', required: true },
      ],
    },
    opsgenie: {
      id: 'opsgenie',
      name: 'Opsgenie',
      description: 'Alert management and on-call scheduling',
      category: 'notifications',
      icon: '📟',
      authType: 'api_key',
      features: ['alerts', 'teams', 'schedules'],
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true },
        { name: 'team', label: 'Team Name', type: 'text', required: false },
      ],
    },
    teams: {
      id: 'teams',
      name: 'Microsoft Teams',
      description: 'Send alerts to Teams channels',
      category: 'notifications',
      icon: '👥',
      authType: 'webhook',
      features: ['alerts', 'cards'],
      configFields: [
        { name: 'webhook_url', label: 'Incoming Webhook URL', type: 'url', required: true },
      ],
    },
    email: {
      id: 'email',
      name: 'Email',
      description: 'Send email notifications',
      category: 'notifications',
      icon: '📧',
      authType: 'smtp',
      features: ['alerts', 'digest', 'reports'],
      configFields: [
        { name: 'recipients', label: 'Recipients (comma-separated)', type: 'text', required: true },
        { name: 'smtp_host', label: 'SMTP Host', type: 'text', required: false },
        { name: 'smtp_port', label: 'SMTP Port', type: 'number', required: false },
      ],
    },
  },

  // ===== TICKETING =====
  ticketing: {
    jira: {
      id: 'jira',
      name: 'Jira',
      description: 'Create and track issues in Jira',
      category: 'ticketing',
      icon: '🎫',
      authType: 'oauth',
      features: ['create_issues', 'link_incidents', 'sync_status'],
      configFields: [
        { name: 'site_url', label: 'Jira Site URL', type: 'url', required: true },
        { name: 'project_key', label: 'Default Project Key', type: 'text', required: true },
        { name: 'issue_type', label: 'Default Issue Type', type: 'select', options: ['Bug', 'Task', 'Story'], required: true },
      ],
    },
    linear: {
      id: 'linear',
      name: 'Linear',
      description: 'Create issues in Linear',
      category: 'ticketing',
      icon: '📐',
      authType: 'oauth',
      features: ['create_issues', 'sync_status'],
      configFields: [
        { name: 'team_id', label: 'Team ID', type: 'text', required: true },
      ],
    },
    asana: {
      id: 'asana',
      name: 'Asana',
      description: 'Create tasks in Asana',
      category: 'ticketing',
      icon: '✅',
      authType: 'oauth',
      features: ['create_tasks', 'projects'],
      configFields: [
        { name: 'workspace_id', label: 'Workspace ID', type: 'text', required: true },
        { name: 'project_id', label: 'Default Project ID', type: 'text', required: true },
      ],
    },
  },

  // ===== DATA WAREHOUSES =====
  warehouses: {
    snowflake: {
      id: 'snowflake',
      name: 'Snowflake',
      description: 'Connect to Snowflake data warehouse',
      category: 'warehouses',
      icon: '❄️',
      authType: 'credentials',
      features: ['scan', 'query_history', 'lineage', 'metadata'],
      configFields: [
        { name: 'account', label: 'Account Identifier', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
        { name: 'warehouse', label: 'Warehouse', type: 'text', required: true },
        { name: 'database', label: 'Database', type: 'text', required: true },
        { name: 'schema', label: 'Schema', type: 'text', required: false, default: 'PUBLIC' },
        { name: 'role', label: 'Role', type: 'text', required: false },
      ],
    },
    bigquery: {
      id: 'bigquery',
      name: 'BigQuery',
      description: 'Connect to Google BigQuery',
      category: 'warehouses',
      icon: '🔷',
      authType: 'service_account',
      features: ['scan', 'query_history', 'lineage', 'metadata'],
      configFields: [
        { name: 'project_id', label: 'Project ID', type: 'text', required: true },
        { name: 'credentials_json', label: 'Service Account JSON', type: 'textarea', required: true },
        { name: 'dataset', label: 'Default Dataset', type: 'text', required: false },
      ],
    },
    redshift: {
      id: 'redshift',
      name: 'Redshift',
      description: 'Connect to Amazon Redshift',
      category: 'warehouses',
      icon: '🔴',
      authType: 'credentials',
      features: ['scan', 'query_history', 'metadata'],
      configFields: [
        { name: 'host', label: 'Cluster Endpoint', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true, default: 5439 },
        { name: 'database', label: 'Database', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
      ],
    },
    databricks: {
      id: 'databricks',
      name: 'Databricks',
      description: 'Connect to Databricks Lakehouse',
      category: 'warehouses',
      icon: '🧱',
      authType: 'token',
      features: ['scan', 'query_history', 'lineage', 'unity_catalog'],
      configFields: [
        { name: 'host', label: 'Workspace URL', type: 'url', required: true },
        { name: 'token', label: 'Access Token', type: 'password', required: true },
        { name: 'http_path', label: 'SQL Warehouse HTTP Path', type: 'text', required: true },
        { name: 'catalog', label: 'Catalog', type: 'text', required: false },
      ],
    },
    postgres: {
      id: 'postgres',
      name: 'PostgreSQL',
      description: 'Connect to PostgreSQL database',
      category: 'warehouses',
      icon: '🐘',
      authType: 'credentials',
      features: ['scan', 'metadata'],
      configFields: [
        { name: 'host', label: 'Host', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true, default: 5432 },
        { name: 'database', label: 'Database', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
        { name: 'ssl', label: 'Use SSL', type: 'boolean', required: false, default: true },
      ],
    },
    mysql: {
      id: 'mysql',
      name: 'MySQL',
      description: 'Connect to MySQL database',
      category: 'warehouses',
      icon: '🐬',
      authType: 'credentials',
      features: ['scan', 'metadata'],
      configFields: [
        { name: 'host', label: 'Host', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true, default: 3306 },
        { name: 'database', label: 'Database', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
      ],
    },
  },

  // ===== ORCHESTRATORS =====
  orchestrators: {
    dbt_cloud: {
      id: 'dbt_cloud',
      name: 'dbt Cloud',
      description: 'Connect to dbt Cloud for models, tests, and lineage',
      category: 'orchestrators',
      icon: '🔧',
      authType: 'api_key',
      features: ['models', 'tests', 'lineage', 'run_history', 'webhooks'],
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true },
        { name: 'account_id', label: 'Account ID', type: 'text', required: true },
        { name: 'project_id', label: 'Project ID', type: 'text', required: false },
      ],
    },
    airflow: {
      id: 'airflow',
      name: 'Apache Airflow',
      description: 'Connect to Airflow for DAG monitoring',
      category: 'orchestrators',
      icon: '🌀',
      authType: 'credentials',
      features: ['dags', 'task_status', 'run_history'],
      configFields: [
        { name: 'base_url', label: 'Airflow URL', type: 'url', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
      ],
    },
    fivetran: {
      id: 'fivetran',
      name: 'Fivetran',
      description: 'Connect to Fivetran for connector monitoring',
      category: 'orchestrators',
      icon: '🔌',
      authType: 'api_key',
      features: ['connectors', 'sync_status', 'trigger_sync'],
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true },
        { name: 'api_secret', label: 'API Secret', type: 'password', required: true },
      ],
    },
    dagster: {
      id: 'dagster',
      name: 'Dagster',
      description: 'Connect to Dagster Cloud',
      category: 'orchestrators',
      icon: '⚡',
      authType: 'token',
      features: ['assets', 'runs', 'schedules'],
      configFields: [
        { name: 'url', label: 'Dagster Cloud URL', type: 'url', required: true },
        { name: 'token', label: 'User Token', type: 'password', required: true },
      ],
    },
    prefect: {
      id: 'prefect',
      name: 'Prefect',
      description: 'Connect to Prefect Cloud',
      category: 'orchestrators',
      icon: '🌊',
      authType: 'api_key',
      features: ['flows', 'runs', 'deployments'],
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true },
        { name: 'workspace', label: 'Workspace', type: 'text', required: true },
      ],
    },
  },

  // ===== CODE REPOS =====
  repos: {
    github: {
      id: 'github',
      name: 'GitHub',
      description: 'Scan repositories for secrets and connect to PRs',
      category: 'repos',
      icon: '🐙',
      authType: 'oauth',
      features: ['scan_secrets', 'pr_comments', 'webhooks'],
      configFields: [], // OAuth handles this
    },
    gitlab: {
      id: 'gitlab',
      name: 'GitLab',
      description: 'Scan GitLab repositories',
      category: 'repos',
      icon: '🦊',
      authType: 'token',
      features: ['scan_secrets', 'mr_comments'],
      configFields: [
        { name: 'url', label: 'GitLab URL', type: 'url', required: true, default: 'https://gitlab.com' },
        { name: 'token', label: 'Personal Access Token', type: 'password', required: true },
      ],
    },
    bitbucket: {
      id: 'bitbucket',
      name: 'Bitbucket',
      description: 'Scan Bitbucket repositories',
      category: 'repos',
      icon: '🪣',
      authType: 'app_password',
      features: ['scan_secrets'],
      configFields: [
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'app_password', label: 'App Password', type: 'password', required: true },
        { name: 'workspace', label: 'Workspace', type: 'text', required: true },
      ],
    },
  },

  // ===== BI TOOLS =====
  bi: {
    looker: {
      id: 'looker',
      name: 'Looker',
      description: 'Connect to Looker for dashboard lineage',
      category: 'bi',
      icon: '👁️',
      authType: 'api_key',
      features: ['dashboards', 'looks', 'lineage'],
      configFields: [
        { name: 'base_url', label: 'Looker URL', type: 'url', required: true },
        { name: 'client_id', label: 'Client ID', type: 'text', required: true },
        { name: 'client_secret', label: 'Client Secret', type: 'password', required: true },
      ],
    },
    tableau: {
      id: 'tableau',
      name: 'Tableau',
      description: 'Connect to Tableau Server/Cloud',
      category: 'bi',
      icon: '📊',
      authType: 'token',
      features: ['workbooks', 'datasources', 'lineage'],
      configFields: [
        { name: 'server_url', label: 'Server URL', type: 'url', required: true },
        { name: 'site_id', label: 'Site ID', type: 'text', required: true },
        { name: 'token_name', label: 'Token Name', type: 'text', required: true },
        { name: 'token_secret', label: 'Token Secret', type: 'password', required: true },
      ],
    },
    metabase: {
      id: 'metabase',
      name: 'Metabase',
      description: 'Connect to Metabase for question lineage',
      category: 'bi',
      icon: '📈',
      authType: 'credentials',
      features: ['questions', 'dashboards', 'lineage'],
      configFields: [
        { name: 'url', label: 'Metabase URL', type: 'url', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
      ],
    },
  },
} as const;

// Get all integrations as flat list
export function getAllIntegrations() {
  const all: any[] = [];
  for (const category of Object.values(INTEGRATIONS)) {
    for (const integration of Object.values(category)) {
      all.push(integration);
    }
  }
  return all;
}

// Get integrations by category
export function getIntegrationsByCategory(category: string) {
  return INTEGRATIONS[category as keyof typeof INTEGRATIONS] || {};
}

// Get single integration config
export function getIntegrationConfig(id: string) {
  for (const category of Object.values(INTEGRATIONS)) {
    for (const [key, integration] of Object.entries(category)) {
      if (key === id || (integration as any).id === id) {
        return integration;
      }
    }
  }
  return null;
}

