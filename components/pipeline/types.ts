/**
 * Pipeline Canvas Types
 * 
 * Type definitions for the pipeline builder
 */

// Pipeline layers in data flow order
export type PipelineLayer = 'SOURCE' | 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING' | 'STORAGE' | 'VERSION_CONTROL' | 'ORCHESTRATION' | 'INFRASTRUCTURE' | 'NOTIFICATIONS' | 'UNCATEGORIZED';

// Integration types (for non-pipeline integrations like notifications/ticketing)
export type IntegrationType = 'NOTIFICATIONS' | 'TICKETING';

// Node status
export type PipelineNodeStatus = 'PENDING' | 'CONNECTED' | 'TESTING' | 'ERROR' | 'ACTIVE';

// Layer colors for visual distinction
export const LAYER_COLORS: Record<PipelineLayer, string> = {
  SOURCE: '#64748B',         // Slate
  INGESTION: '#10B981',      // Emerald
  TRANSFORMATION: '#F59E0B', // Amber
  WAREHOUSE: '#6366F1',      // Indigo
  REPORTING: '#06B6D4',      // Cyan
  STORAGE: '#A855F7',        // Purple-500
  VERSION_CONTROL: '#8B5CF6', // Purple
  ORCHESTRATION: '#F97316',  // Orange
  INFRASTRUCTURE: '#94A3B8', // Slate
  NOTIFICATIONS: '#EC4899',  // Pink
  UNCATEGORIZED: '#78716C',  // Stone — neutral for unknown platforms
};

// Integration type colors
export const INTEGRATION_COLORS: Record<IntegrationType, string> = {
  NOTIFICATIONS: '#EC4899',  // Pink
  TICKETING: '#F97316',      // Orange
};

// Status colors
export const STATUS_COLORS: Record<PipelineNodeStatus, string> = {
  PENDING: '#6B7280',    // Gray
  CONNECTED: '#10B981',  // Green
  TESTING: '#F59E0B',    // Amber
  ERROR: '#EF4444',      // Red
  ACTIVE: '#10B981',     // Green
};

// Layer labels for UI
export const LAYER_LABELS: Record<PipelineLayer, string> = {
  SOURCE: 'Sources',
  INGESTION: 'Ingestion',
  TRANSFORMATION: 'Transformation',
  WAREHOUSE: 'Warehouse',
  REPORTING: 'Reporting',
  STORAGE: 'Storage',
  VERSION_CONTROL: 'Version Control',
  ORCHESTRATION: 'Orchestration',
  INFRASTRUCTURE: 'Infrastructure',
  NOTIFICATIONS: 'Notifications',
  UNCATEGORIZED: 'Uncategorized',
};

// Integration type labels
export const INTEGRATION_LABELS: Record<IntegrationType, string> = {
  NOTIFICATIONS: 'Notifications',
  TICKETING: 'Ticketing',
};

// Get tools by layer
export function getToolsByLayer(layer: PipelineLayer): ToolDefinition[] {
  return TOOLS[layer] || [];
}

// Config field definition
export interface ConfigField {
  name: string;
  label: string;
  type: 'text' | 'password' | 'select' | 'file' | 'folder' | 'textarea' | 'number' | 'multi-select';
  required: boolean;
  placeholder?: string;
  helperText?: string;
  options?: { value: string; label: string }[];
  // For multi-select fields that load options dynamically from API
  dynamicOptions?: boolean;
  // API endpoint to fetch options (relative path, e.g., 'datasets')
  optionsEndpoint?: string;
  // Conditional visibility: only show this field when another field has a specific value
  showWhen?: { field: string; value: string };
}

// Tool definition
export type GraphDomain = 'DATA_PLANE' | 'CONTROL_PLANE' | 'NONE';

export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  layer: PipelineLayer;
  configFields: ConfigField[];
  // Complementary integrations — IDs of tools that unlock extra capabilities when paired
  recommendedWith?: string[];
  recommendedReason?: string;
  // DATA_PLANE tools create lineage nodes/edges; CONTROL_PLANE tools do not
  graphDomain?: GraphDomain;
  // Multi-role: additional layers this tool can serve beyond its primary layer.
  // Detected at connection time via observed_capabilities() on the backend.
  additionalLayers?: PipelineLayer[];
  // Tile display status — defaults to 'live' when absent
  status?: 'live' | 'coming_soon';
}

// Multi-role display configuration
export interface RoleInfo {
  layer: PipelineLayer;
  label: string;
  color: string;
  description: string;
}

// Which tools support multiple roles and what those roles look like
export const MULTI_ROLE_TOOLS: Record<string, RoleInfo[]> = {
  databricks: [
    { layer: 'WAREHOUSE', label: 'Warehouse', color: '#6366F1', description: 'Unity Catalog tables & SQL queries' },
    { layer: 'ORCHESTRATION', label: 'Orchestration', color: '#F97316', description: 'Databricks Jobs & Workflows' },
    { layer: 'TRANSFORMATION', label: 'Transformation', color: '#F59E0B', description: 'Notebooks & Spark jobs' },
  ],
  snowflake: [
    { layer: 'WAREHOUSE', label: 'Warehouse', color: '#6366F1', description: 'Tables, views & SQL queries' },
    { layer: 'TRANSFORMATION', label: 'Transformation', color: '#F59E0B', description: 'Snowflake Tasks & Streams' },
  ],
};

/** Check if a tool supports multiple roles. */
export function isMultiRoleTool(toolId: string): boolean {
  return toolId in MULTI_ROLE_TOOLS;
}

/** Get the role info for a multi-role tool. Returns undefined for single-role tools. */
export function getMultiRoleInfo(toolId: string): RoleInfo[] | undefined {
  return MULTI_ROLE_TOOLS[toolId];
}

// All available tools organized by layer with their config fields
export const TOOLS: Record<PipelineLayer, ToolDefinition[]> = {
  SOURCE: [
    {
      id: 'custom_source',
      name: 'Custom Source',
      description: 'Monitor any HTTPS-accessible REST API as a source — IoT portals, vertical-SaaS platforms, custom internal services.',
      layer: 'SOURCE',
      status: 'live',
      configFields: [],
    },
    {
      id: 'salesforce',
      name: 'Salesforce',
      description: 'Monitor Salesforce objects as pipeline sources. Coming soon.',
      layer: 'SOURCE',
      status: 'coming_soon',
      configFields: [],
    },
    {
      id: 'shopify',
      name: 'Shopify',
      description: 'Monitor Shopify orders, customers, and products. Coming soon.',
      layer: 'SOURCE',
      status: 'coming_soon',
      configFields: [],
    },
    {
      id: 'hubspot',
      name: 'HubSpot',
      description: 'Monitor HubSpot CRM objects as pipeline sources. Coming soon.',
      layer: 'SOURCE',
      status: 'coming_soon',
      configFields: [],
    },
  ],
  INGESTION: [
    { 
      id: 'fivetran', 
      name: 'Fivetran', 
      description: 'Automated data integration', 
      layer: 'INGESTION',
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your Fivetran API key' },
        { name: 'api_secret', label: 'API Secret', type: 'password', required: true, placeholder: 'Your Fivetran API secret' },
        { name: 'group_id', label: 'Group ID', type: 'text', required: false, placeholder: 'Optional: specific group ID' },
      ],
    },
    { 
      id: 'airbyte', 
      name: 'Airbyte', 
      description: 'Open-source data integration', 
      layer: 'INGESTION',
      configFields: [
        { name: 'host', label: 'Airbyte Host URL', type: 'text', required: true, placeholder: 'https://api.airbyte.com (Cloud) or http://localhost:8000 (OSS)' },
        { name: 'client_id', label: 'Client ID', type: 'text', required: false, placeholder: 'Cloud: Settings → Applications → Client ID' },
        { name: 'client_secret', label: 'Client Secret', type: 'password', required: false, placeholder: 'Cloud: Settings → Applications → Client Secret' },
        { name: 'workspace_id', label: 'Workspace ID', type: 'text', required: false, placeholder: 'Workspace ID' },
        { name: 'username', label: 'Username', type: 'text', required: false, placeholder: 'OSS only: basic auth username' },
        { name: 'password', label: 'Password', type: 'password', required: false, placeholder: 'OSS only: basic auth password' },
      ],
    },
    { 
      id: 'stitch', 
      name: 'Stitch', 
      description: 'Simple data pipeline', 
      layer: 'INGESTION',
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your Stitch API key' },
        { name: 'client_id', label: 'Client ID', type: 'text', required: true, placeholder: 'Your Stitch client ID' },
      ],
    },
  ],
  TRANSFORMATION: [
    {
      id: 'dbt_cloud',
      name: 'dbt Cloud',
      description: 'dbt Cloud (hosted)',
      layer: 'TRANSFORMATION',
      recommendedWith: ['github'],
      recommendedReason: 'Connect GitHub to enable PR creation for dbt model fixes',
      configFields: [
        { name: 'api_mode', label: 'API Mode', type: 'select', required: true, options: [
          { value: 'admin', label: 'Admin API (Full Access) - Requires "Job Viewer" token' },
          { value: 'discovery', label: 'Discovery API (Metadata Only) - Works with "Metadata Only" token' },
        ], helperText: 'Discovery API is read-only but works with minimal permissions. Admin API provides full run history and artifacts.' },
        { name: 'api_token', label: 'Service Token', type: 'password', required: true, placeholder: 'Your dbt Cloud service token (dbtc_...)' },
        { name: 'account_id', label: 'Account ID', type: 'text', required: true, placeholder: 'dbt Cloud account ID', helperText: 'Required for Admin API' },
        { name: 'environment_id', label: 'Environment ID', type: 'text', required: false, placeholder: 'dbt Cloud environment ID', helperText: 'Required for Discovery API mode' },
        { name: 'project_id', label: 'Project ID', type: 'text', required: false, placeholder: 'Optional: filter to specific project' },
      ],
    },
    {
      id: 'dbt_core',
      name: 'dbt Core',
      description: 'dbt Core (upload, project, or GitHub)',
      layer: 'TRANSFORMATION',
      recommendedWith: ['github'],
      recommendedReason: 'Connect GitHub to enable PR creation for dbt model fixes',
      configFields: [
        { name: 'source_mode', label: 'Source', type: 'select', required: true, options: [
          { value: 'upload', label: 'Upload manifest.json' },
          { value: 'project', label: 'Upload dbt project (zip)' },
          { value: 'github', label: 'Connect GitHub repo' },
        ], helperText: 'Choose how to provide your dbt project' },
        // Upload manifest mode
        { name: 'manifest', label: 'Manifest File', type: 'file', required: false, helperText: 'Upload your manifest.json from target/ folder', showWhen: { field: 'source_mode', value: 'upload' } },
        // Upload project folder mode
        { name: 'project_files', label: 'dbt Project Folder', type: 'folder', required: false, helperText: 'Select your dbt project folder (models/, dbt_project.yml, etc.)', showWhen: { field: 'source_mode', value: 'project' } },
        // GitHub repo mode
        { name: 'github_repo', label: 'Repository', type: 'select', required: false, dynamicOptions: true, optionsEndpoint: 'github-repos', helperText: 'Select from repositories configured in your GitHub connector', showWhen: { field: 'source_mode', value: 'github' } },
        { name: 'github_branch', label: 'Branch', type: 'text', required: false, placeholder: 'main', showWhen: { field: 'source_mode', value: 'github' } },
        { name: 'dbt_project_path', label: 'dbt Project Path', type: 'text', required: false, placeholder: '/ (repo root)', helperText: 'Path to dbt project within the repo (leave empty for root)', showWhen: { field: 'source_mode', value: 'github' } },
        // Common fields
        { name: 'warehouse_type', label: 'Target Warehouse', type: 'select', required: false, options: [
          { value: 'bigquery', label: 'BigQuery' },
          { value: 'snowflake', label: 'Snowflake' },
          { value: 'postgres', label: 'Postgres' },
          { value: 'redshift', label: 'Redshift' },
        ], helperText: 'The warehouse your dbt project targets' },
        { name: 'project_name', label: 'Project Name', type: 'text', required: false, placeholder: 'Name to identify this dbt project' },
      ],
    },
    {
      id: 'airflow',
      name: 'Airflow',
      description: 'Apache Airflow orchestration',
      layer: 'TRANSFORMATION',
      recommendedWith: ['github'],
      recommendedReason: 'Connect GitHub to enable PR creation for DAG fixes and code suggestions',
      configFields: [
        { name: 'source_mode', label: 'Connection Mode', type: 'select', required: false, options: [
          { value: 'api', label: 'Airflow API' },
          { value: 'github', label: 'GitHub DAG Files' },
        ], helperText: 'Connect via Airflow REST API or parse DAG files from a GitHub repo' },
        // API mode fields
        { name: 'host', label: 'Airflow Host', type: 'text', required: false, placeholder: 'https://your-airflow.com', showWhen: { field: 'source_mode', value: 'api' } },
        { name: 'username', label: 'Username', type: 'text', required: false, placeholder: 'Airflow username', showWhen: { field: 'source_mode', value: 'api' } },
        { name: 'password', label: 'Password', type: 'password', required: false, placeholder: 'Airflow password', showWhen: { field: 'source_mode', value: 'api' } },
        { name: 'code_repo', label: 'Code Repository', type: 'select', required: false, dynamicOptions: true, optionsEndpoint: 'github-repos', helperText: 'Select from repositories configured in your GitHub connector', showWhen: { field: 'source_mode', value: 'api' } },
        // GitHub mode fields
        { name: 'github_repo', label: 'Repository', type: 'select', required: false, dynamicOptions: true, optionsEndpoint: 'github-repos', helperText: 'Select from repositories configured in your GitHub connector', showWhen: { field: 'source_mode', value: 'github' } },
        { name: 'github_branch', label: 'Branch', type: 'text', required: false, placeholder: 'main', showWhen: { field: 'source_mode', value: 'github' } },
        { name: 'dag_directory', label: 'DAG Directory', type: 'text', required: false, placeholder: 'dags', helperText: 'Path to DAGs folder in the repo (default: dags)', showWhen: { field: 'source_mode', value: 'github' } },
      ],
    },
    {
      id: 'dagster',
      name: 'Dagster',
      description: 'Dagster orchestration',
      layer: 'TRANSFORMATION',
      recommendedWith: ['github'],
      recommendedReason: 'Connect GitHub to enable PR creation for pipeline fixes',
      configFields: [
        { name: 'host', label: 'Dagster Host', type: 'text', required: true, placeholder: 'https://your-dagster.com' },
        { name: 'api_token', label: 'API Token', type: 'password', required: false, placeholder: 'Dagster Cloud token' },
        { name: 'code_repo', label: 'Code Repository', type: 'text', required: false, placeholder: 'owner/repo', helperText: 'GitHub repo where your pipeline code lives (optional)' },
      ],
    },
    {
      id: 'prefect',
      name: 'Prefect',
      description: 'Prefect workflow orchestration',
      layer: 'TRANSFORMATION',
      recommendedWith: ['github'],
      recommendedReason: 'Connect GitHub to enable PR creation for flow fixes',
      configFields: [
        { name: 'api_url', label: 'Prefect API URL', type: 'text', required: true, placeholder: 'https://api.prefect.cloud/api' },
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your Prefect API key' },
        { name: 'workspace_id', label: 'Workspace ID', type: 'text', required: false, placeholder: 'Prefect Cloud workspace ID' },
        { name: 'code_repo', label: 'Code Repository', type: 'text', required: false, placeholder: 'owner/repo', helperText: 'GitHub repo where your flow code lives (optional)' },
      ],
    },
  ],
  WAREHOUSE: [
    {
      id: 'snowflake',
      name: 'Snowflake',
      description: 'Snowflake Data Cloud',
      layer: 'WAREHOUSE',
      additionalLayers: ['TRANSFORMATION'],
      configFields: [
        { name: 'account', label: 'Account Identifier', type: 'text', required: true, placeholder: 'xy12345.us-east-1' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'Your Snowflake username' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Your Snowflake password' },
        { name: 'warehouse', label: 'Warehouse', type: 'text', required: true, placeholder: 'COMPUTE_WH' },
        { name: 'database', label: 'Database', type: 'text', required: true, placeholder: 'Database name' },
        { name: 'schemas', label: 'Schemas to Scan', type: 'multi-select', required: false, placeholder: 'Select schemas...', dynamicOptions: true, optionsEndpoint: 'schemas', helperText: 'Leave empty to scan all schemas, or select specific ones' },
      ],
    },
    { 
      id: 'bigquery', 
      name: 'BigQuery', 
      description: 'Google BigQuery', 
      layer: 'WAREHOUSE',
      configFields: [
        { name: 'project_id', label: 'Project ID', type: 'text', required: true, placeholder: 'your-gcp-project-id' },
        { name: 'credentials', label: 'Service Account Key', type: 'file', required: true, helperText: 'Upload your service account JSON key file' },
        { name: 'datasets', label: 'Datasets to Scan', type: 'multi-select', required: false, placeholder: 'Select datasets...', dynamicOptions: true, optionsEndpoint: 'datasets', helperText: 'Leave empty to scan all datasets, or select specific ones' },
        { name: 'location', label: 'Data Location', type: 'select', required: false, options: [
          { value: 'US', label: 'US (Multi-region)' },
          { value: 'EU', label: 'EU (Multi-region)' },
          { value: 'us-central1', label: 'Iowa (us-central1)' },
          { value: 'us-east1', label: 'South Carolina (us-east1)' },
          { value: 'us-east4', label: 'Northern Virginia (us-east4)' },
          { value: 'us-west1', label: 'Oregon (us-west1)' },
          { value: 'us-west2', label: 'Los Angeles (us-west2)' },
          { value: 'europe-west1', label: 'Belgium (europe-west1)' },
          { value: 'europe-west2', label: 'London (europe-west2)' },
          { value: 'europe-west3', label: 'Frankfurt (europe-west3)' },
          { value: 'asia-east1', label: 'Taiwan (asia-east1)' },
          { value: 'asia-southeast1', label: 'Singapore (asia-southeast1)' },
          { value: 'asia-northeast1', label: 'Tokyo (asia-northeast1)' },
          { value: 'australia-southeast1', label: 'Sydney (australia-southeast1)' },
          { value: 'southamerica-east1', label: 'Sao Paulo (southamerica-east1)' },
          { value: 'africa-south1', label: 'Johannesburg (africa-south1)' },
        ]},
      ],
    },
    { 
      id: 'postgres', 
      name: 'PostgreSQL', 
      description: 'PostgreSQL database', 
      layer: 'WAREHOUSE',
      configFields: [
        { name: 'host', label: 'Host', type: 'text', required: true, placeholder: 'localhost' },
        { name: 'port', label: 'Port', type: 'number', required: true, placeholder: '5432' },
        { name: 'database', label: 'Database', type: 'text', required: true, placeholder: 'postgres' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'postgres' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Password' },
        { name: 'ssl', label: 'SSL Mode', type: 'select', required: false, options: [
          { value: 'disable', label: 'Disable' },
          { value: 'require', label: 'Require' },
          { value: 'verify-ca', label: 'Verify CA' },
        ]},
      ],
    },
    { 
      id: 'redshift', 
      name: 'Redshift', 
      description: 'Amazon Redshift', 
      layer: 'WAREHOUSE',
      configFields: [
        { name: 'host', label: 'Cluster Endpoint', type: 'text', required: true, placeholder: 'cluster.region.redshift.amazonaws.com' },
        { name: 'port', label: 'Port', type: 'number', required: true, placeholder: '5439' },
        { name: 'database', label: 'Database', type: 'text', required: true, placeholder: 'dev' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'admin' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Password' },
      ],
    },
    {
      id: 'azure_sql',
      name: 'Azure SQL',
      description: 'Azure SQL Database',
      layer: 'WAREHOUSE',
      configFields: [
        { name: 'server', label: 'Server', type: 'text', required: true, placeholder: 'yourserver.database.windows.net' },
        { name: 'database', label: 'Database', type: 'text', required: true, placeholder: 'yourdb' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'admin@yourserver' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Password' },
      ],
    },
    {
      id: 'databricks',
      name: 'Databricks',
      description: 'Databricks Lakehouse',
      layer: 'WAREHOUSE',
      additionalLayers: ['ORCHESTRATION', 'TRANSFORMATION'],
      configFields: [
        { name: 'host', label: 'Workspace URL', type: 'text', required: true, placeholder: 'https://adb-xxxx.azuredatabricks.net', helperText: 'Your Databricks workspace URL' },
        { name: 'token', label: 'Personal Access Token', type: 'password', required: true, placeholder: 'dapi...' },
        { name: 'http_path', label: 'SQL Warehouse HTTP Path', type: 'text', required: true, placeholder: '/sql/1.0/warehouses/xxxx', helperText: 'Found in SQL Warehouse connection details' },
        { name: 'catalog', label: 'Unity Catalog', type: 'text', required: false, placeholder: 'main', helperText: 'Leave empty for hive_metastore' },
        { name: 'schema', label: 'Schema', type: 'text', required: false, placeholder: 'default' },
      ],
    },
    {
      id: 'sqlserver',
      name: 'SQL Server',
      description: 'Microsoft SQL Server',
      layer: 'WAREHOUSE',
      configFields: [
        { name: 'server', label: 'Server', type: 'text', required: true, placeholder: 'localhost' },
        { name: 'port', label: 'Port', type: 'number', required: false, placeholder: '1433' },
        { name: 'database', label: 'Database', type: 'text', required: true, placeholder: 'master' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'sa' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Password' },
      ],
    },
  ],
  REPORTING: [
    { 
      id: 'tableau', 
      name: 'Tableau', 
      description: 'Tableau visualization', 
      layer: 'REPORTING',
      configFields: [
        { name: 'server', label: 'Tableau Server URL', type: 'text', required: true, placeholder: 'https://your-tableau-server.com' },
        { name: 'site_id', label: 'Site ID', type: 'text', required: false, placeholder: 'Leave empty for default site' },
        { name: 'token_name', label: 'Personal Access Token Name', type: 'text', required: true, placeholder: 'Token name' },
        { name: 'token_secret', label: 'Personal Access Token Secret', type: 'password', required: true, placeholder: 'Token secret' },
      ],
    },
    { 
      id: 'looker', 
      name: 'Looker', 
      description: 'Looker analytics', 
      layer: 'REPORTING',
      configFields: [
        { name: 'host', label: 'Looker Instance URL', type: 'text', required: true, placeholder: 'https://your-company.cloud.looker.com' },
        { name: 'client_id', label: 'Client ID', type: 'text', required: true, placeholder: 'API3 client ID' },
        { name: 'client_secret', label: 'Client Secret', type: 'password', required: true, placeholder: 'API3 client secret' },
      ],
    },
    { 
      id: 'powerbi', 
      name: 'Power BI', 
      description: 'Microsoft Power BI', 
      layer: 'REPORTING',
      configFields: [
        { name: 'tenant_id', label: 'Azure Tenant ID', type: 'text', required: true, placeholder: 'Your Azure AD tenant ID' },
        { name: 'client_id', label: 'Application (Client) ID', type: 'text', required: true, placeholder: 'App registration client ID' },
        { name: 'client_secret', label: 'Client Secret', type: 'password', required: true, placeholder: 'App registration secret' },
        { name: 'workspace_id', label: 'Workspace ID', type: 'text', required: false, placeholder: 'Optional: specific workspace' },
      ],
    },
    {
      id: 'metabase',
      name: 'Metabase',
      description: 'Metabase dashboards',
      layer: 'REPORTING',
      configFields: [
        { name: 'host', label: 'Metabase URL', type: 'text', required: true, placeholder: 'https://your-metabase.com' },
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'mb_...', helperText: 'Generate from Admin > Settings > Authentication > API Keys (Metabase v0.49+)' },
      ],
    },
  ],
  STORAGE: [
    {
      id: 'amazon_s3',
      name: 'Amazon S3',
      description: 'AWS object storage',
      layer: 'STORAGE',
      configFields: [
        { name: 'access_key_id', label: 'Access Key ID', type: 'text', required: true, placeholder: 'AKIAIOSFODNN7EXAMPLE' },
        { name: 'secret_access_key', label: 'Secret Access Key', type: 'password', required: true, placeholder: 'Your AWS secret key' },
        { name: 'region', label: 'Region', type: 'select', required: true, options: [
          { value: 'us-east-1', label: 'US East (N. Virginia)' },
          { value: 'us-east-2', label: 'US East (Ohio)' },
          { value: 'us-west-1', label: 'US West (N. California)' },
          { value: 'us-west-2', label: 'US West (Oregon)' },
          { value: 'eu-west-1', label: 'EU (Ireland)' },
          { value: 'eu-west-2', label: 'EU (London)' },
          { value: 'eu-central-1', label: 'EU (Frankfurt)' },
          { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
          { value: 'ap-southeast-2', label: 'Asia Pacific (Sydney)' },
          { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
        ]},
        { name: 'bucket', label: 'Bucket Name', type: 'text', required: false, placeholder: 'Optional: specific bucket' },
      ],
    },
    {
      id: 'gcs',
      name: 'Google Cloud Storage',
      description: 'GCP object storage',
      layer: 'STORAGE',
      configFields: [
        { name: 'project_id', label: 'Project ID', type: 'text', required: true, placeholder: 'your-gcp-project-id' },
        { name: 'credentials', label: 'Service Account Key', type: 'file', required: true, helperText: 'Upload your service account JSON key file' },
        { name: 'bucket', label: 'Bucket Name', type: 'text', required: false, placeholder: 'Optional: specific bucket' },
      ],
    },
    {
      id: 'adls',
      name: 'Azure Data Lake Storage',
      description: 'Azure ADLS Gen2',
      layer: 'STORAGE',
      configFields: [
        { name: 'account_name', label: 'Storage Account Name', type: 'text', required: true, placeholder: 'yourstorageaccount' },
        { name: 'account_key', label: 'Account Key', type: 'password', required: false, helperText: 'Use either Account Key or SAS Token' },
        { name: 'sas_token', label: 'SAS Token', type: 'password', required: false, helperText: 'Shared Access Signature token' },
        { name: 'container', label: 'Container Name', type: 'text', required: false, placeholder: 'Optional: specific container' },
      ],
    },
  ],
  ORCHESTRATION: [
    {
      id: 'n8n',
      name: 'n8n',
      description: 'n8n workflow automation',
      layer: 'ORCHESTRATION',
      recommendedWith: ['github'],
      recommendedReason: 'Connect GitHub to enable PR creation for workflow fixes',
      configFields: [
        { name: 'host', label: 'n8n Instance URL', type: 'text', required: true, placeholder: 'https://your-n8n.example.com', helperText: 'Base URL of your n8n instance (self-hosted or cloud)' },
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your n8n API key', helperText: 'Generate from Settings > API in your n8n instance' },
      ],
    },
  ],
  INFRASTRUCTURE: [
    {
      id: 'linux_server',
      name: 'Linux Server',
      description: 'SSH-based server monitoring (certificates, health, logs)',
      layer: 'INFRASTRUCTURE',
      configFields: [
        { name: 'host', label: 'Host / IP', type: 'text', required: true, placeholder: '10.0.1.50 or server.example.com' },
        { name: 'port', label: 'SSH Port', type: 'number', required: false, placeholder: '22' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'deploy' },
        { name: 'auth_method', label: 'Auth Method', type: 'select', required: true, options: [
          { value: 'key', label: 'SSH Private Key' },
          { value: 'password', label: 'Password' },
        ]},
        { name: 'private_key', label: 'Private Key', type: 'textarea', required: false, placeholder: '-----BEGIN RSA PRIVATE KEY-----', helperText: 'Paste your SSH private key (for key-based auth)', showWhen: { field: 'auth_method', value: 'key' } },
        { name: 'passphrase', label: 'Key Passphrase', type: 'password', required: false, placeholder: 'Passphrase for encrypted key', helperText: 'Leave empty if your key is not passphrase-protected', showWhen: { field: 'auth_method', value: 'key' } },
        { name: 'password', label: 'Password', type: 'password', required: false, placeholder: 'SSH password', helperText: 'For password-based auth', showWhen: { field: 'auth_method', value: 'password' } },
      ],
    },
  ],
  VERSION_CONTROL: [
    {
      id: 'github',
      name: 'GitHub',
      description: 'GitHub repositories & PRs',
      layer: 'VERSION_CONTROL',
      configFields: [
        { name: 'access_token', label: 'Personal Access Token', type: 'password', required: true, placeholder: 'ghp_xxxxxxxxxxxx', helperText: 'Token needs repo access scope. For PR creation, also needs write access.' },
        { name: 'owner', label: 'Repository Owner', type: 'text', required: true, placeholder: 'organization or username' },
        { name: 'repos', label: 'Repositories', type: 'multi-select', required: false, dynamicOptions: true, optionsEndpoint: 'repos', helperText: 'Select repositories to make visible. Other tools (dbt, Airflow) can pick from these.' },
      ],
    },
    {
      id: 'gitlab',
      name: 'GitLab',
      description: 'GitLab repositories & MRs',
      layer: 'VERSION_CONTROL',
      configFields: [
        { name: 'host', label: 'GitLab URL', type: 'text', required: true, placeholder: 'https://gitlab.com' },
        { name: 'access_token', label: 'Personal Access Token', type: 'password', required: true, placeholder: 'glpat-xxxxxxxxxxxx' },
        { name: 'group_id', label: 'Group ID', type: 'text', required: false, placeholder: 'Optional: specific group' },
      ],
    },
    {
      id: 'bitbucket',
      name: 'Bitbucket',
      description: 'Bitbucket repositories',
      layer: 'VERSION_CONTROL',
      configFields: [
        { name: 'workspace', label: 'Workspace', type: 'text', required: true, placeholder: 'Your Bitbucket workspace' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'Bitbucket username' },
        { name: 'app_password', label: 'App Password', type: 'password', required: true, placeholder: 'Bitbucket app password' },
      ],
    },
  ],
  NOTIFICATIONS: [],
  UNCATEGORIZED: [],
};

// Integration definitions (non-pipeline tools for notifications, ticketing, observability)
export interface IntegrationDefinition {
  id: string;
  name: string;
  description: string;
  category: IntegrationType;
  configFields: ConfigField[];
}

export const INTEGRATIONS: Record<IntegrationType, IntegrationDefinition[]> = {
  NOTIFICATIONS: [
    {
      id: 'slack',
      name: 'Slack',
      description: 'Send alerts to Slack channels',
      category: 'NOTIFICATIONS',
      configFields: [
        { name: 'bot_token', label: 'Bot Token', type: 'password', required: true, placeholder: 'xoxb-...', helperText: 'Create a Slack App, add bot scopes (chat:write, channels:read, groups:read), then paste the Bot Token' },
        { name: 'channel', label: 'Default Channel', type: 'text', required: false, placeholder: '#data-alerts' },
      ],
    },
    {
      id: 'teams',
      name: 'Microsoft Teams',
      description: 'Send alerts to Teams channels',
      category: 'NOTIFICATIONS',
      configFields: [
        { name: 'webhook_url', label: 'Webhook URL', type: 'text', required: true, placeholder: 'https://outlook.office.com/webhook/...' },
      ],
    },
    {
      id: 'pagerduty',
      name: 'PagerDuty',
      description: 'Incident management & on-call',
      category: 'NOTIFICATIONS',
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your PagerDuty API key' },
        { name: 'service_id', label: 'Service ID', type: 'text', required: true, placeholder: 'PagerDuty service ID' },
      ],
    },
    {
      id: 'opsgenie',
      name: 'OpsGenie',
      description: 'Alert management & on-call',
      category: 'NOTIFICATIONS',
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your OpsGenie API key' },
        { name: 'team', label: 'Team Name', type: 'text', required: false, placeholder: 'Optional: specific team' },
      ],
    },
  ],
  TICKETING: [
    {
      id: 'jira',
      name: 'Jira',
      description: 'Create & track Jira issues',
      category: 'TICKETING',
      configFields: [
        { name: 'site_url', label: 'Jira Site URL', type: 'text', required: true, placeholder: 'https://yourcompany.atlassian.net' },
        { name: 'email', label: 'Email', type: 'text', required: true, placeholder: 'user@company.com' },
        { name: 'api_token', label: 'API Token', type: 'password', required: true, placeholder: 'Jira API token' },
        { name: 'project_key', label: 'Default Project Key', type: 'text', required: true, placeholder: 'PROJ' },
      ],
    },
    {
      id: 'linear',
      name: 'Linear',
      description: 'Create & track Linear issues',
      category: 'TICKETING',
      configFields: [
        { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'lin_api_xxxxxxxxxxxx' },
        { name: 'team_id', label: 'Team ID', type: 'text', required: false, placeholder: 'Optional: default team' },
      ],
    },
    {
      id: 'asana',
      name: 'Asana',
      description: 'Create & track Asana tasks',
      category: 'TICKETING',
      configFields: [
        { name: 'access_token', label: 'Personal Access Token', type: 'password', required: true, placeholder: 'Asana PAT' },
        { name: 'workspace_gid', label: 'Workspace ID', type: 'text', required: true, placeholder: 'Asana workspace GID' },
        { name: 'project_gid', label: 'Default Project ID', type: 'text', required: false, placeholder: 'Optional: default project' },
      ],
    },
    {
      id: 'github_issues',
      name: 'GitHub Issues',
      description: 'Create issues in GitHub repos',
      category: 'TICKETING',
      configFields: [
        { name: 'access_token', label: 'Personal Access Token', type: 'password', required: true, placeholder: 'ghp_xxxxxxxxxxxx' },
        { name: 'owner', label: 'Repository Owner', type: 'text', required: true, placeholder: 'organization or username' },
        { name: 'repo', label: 'Repository Name', type: 'text', required: true, placeholder: 'repository-name' },
      ],
    },
  ],
};

// Get tool by ID
export function getToolById(toolId: string): ToolDefinition | undefined {
  for (const layer of Object.values(TOOLS)) {
    const tool = layer.find(t => t.id === toolId);
    if (tool) return tool;
  }
  return undefined;
}

// Pipeline node
export interface PipelineNode {
  id: string;
  name: string;
  layer: PipelineLayer;
  toolType: string;
  positionX: number;
  positionY: number;
  status: PipelineNodeStatus;
  config: Record<string, any> | null;
  healthScore: number | null;
  findingsCount: number;
  criticalCount: number;
  highCount: number;
}

// Pipeline edge (connection between nodes)
export interface PipelineEdge {
  id: string;
  sourceId: string;
  targetId: string;
  label?: string;
}

// Pipeline stack (container for the whole pipeline)
export interface PipelineStack {
  id: string;
  name: string;
  description: string;
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED';
  nodes: PipelineNode[];
  edges: PipelineEdge[];
}

// ─── Graph Domain Map ────────────────────────────────────────────────
// Maps tool IDs to their graph domain. DATA_PLANE tools produce lineage
// nodes/edges; CONTROL_PLANE tools are operational only.

export const GRAPH_DOMAIN_MAP: Record<string, GraphDomain> = {
  // Warehouses — DATA_PLANE
  bigquery: 'DATA_PLANE',
  snowflake: 'DATA_PLANE',
  postgres: 'DATA_PLANE',
  redshift: 'DATA_PLANE',
  databricks: 'DATA_PLANE',
  sqlserver: 'DATA_PLANE',
  azure_sql: 'DATA_PLANE',
  azure_synapse: 'DATA_PLANE',
  mysql: 'DATA_PLANE',
  // Ingestion — DATA_PLANE
  fivetran: 'DATA_PLANE',
  airbyte: 'DATA_PLANE',
  stitch: 'DATA_PLANE',
  // Transformation / Orchestration — DATA_PLANE
  dbt_cloud: 'DATA_PLANE',
  dbt_core: 'DATA_PLANE',
  airflow: 'DATA_PLANE',
  dagster: 'DATA_PLANE',
  prefect: 'DATA_PLANE',
  n8n: 'DATA_PLANE',
  // Reporting / BI — DATA_PLANE
  looker: 'DATA_PLANE',
  tableau: 'DATA_PLANE',
  metabase: 'DATA_PLANE',
  powerbi: 'DATA_PLANE',
  // Storage — DATA_PLANE
  amazon_s3: 'DATA_PLANE',
  gcs: 'DATA_PLANE',
  adls: 'DATA_PLANE',
  // Version Control — CONTROL_PLANE
  github: 'CONTROL_PLANE',
  github_issues: 'CONTROL_PLANE',
  gitlab: 'CONTROL_PLANE',
  bitbucket: 'CONTROL_PLANE',
  // Notifications — CONTROL_PLANE
  slack: 'CONTROL_PLANE',
  teams: 'CONTROL_PLANE',
  pagerduty: 'CONTROL_PLANE',
  opsgenie: 'CONTROL_PLANE',
  // Project Management — CONTROL_PLANE
  jira: 'CONTROL_PLANE',
  linear: 'CONTROL_PLANE',
  asana: 'CONTROL_PLANE',
  // Infrastructure — CONTROL_PLANE
  linux_server: 'CONTROL_PLANE',
  // Other — CONTROL_PLANE
  custom_webhook: 'CONTROL_PLANE',
};

/** Look up graph domain for a tool, defaulting to DATA_PLANE. */
export function getGraphDomain(toolId: string): GraphDomain {
  return GRAPH_DOMAIN_MAP[toolId] ?? 'DATA_PLANE';
}

/** Check if a tool is on the data plane (produces lineage). */
export function isDataPlane(toolId: string): boolean {
  return getGraphDomain(toolId) === 'DATA_PLANE';
}

/** Check if a tool is on the control plane (no lineage). */
export function isControlPlane(toolId: string): boolean {
  return getGraphDomain(toolId) === 'CONTROL_PLANE';
}
