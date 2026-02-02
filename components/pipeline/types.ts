/**
 * Pipeline Canvas Types
 * 
 * Type definitions for the pipeline builder
 */

// Pipeline layers in data flow order
export type PipelineLayer = 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING';

// Node status
export type PipelineNodeStatus = 'PENDING' | 'CONNECTED' | 'TESTING' | 'ERROR' | 'ACTIVE';

// Layer colors for visual distinction
export const LAYER_COLORS: Record<PipelineLayer, string> = {
  INGESTION: '#10B981',      // Emerald
  TRANSFORMATION: '#F59E0B', // Amber
  WAREHOUSE: '#6366F1',      // Indigo
  REPORTING: '#06B6D4',      // Cyan
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
  INGESTION: 'Ingestion',
  TRANSFORMATION: 'Transformation',
  WAREHOUSE: 'Warehouse',
  REPORTING: 'Reporting',
};

// Get tools by layer
export function getToolsByLayer(layer: PipelineLayer): ToolDefinition[] {
  return TOOLS[layer] || [];
}

// Config field definition
export interface ConfigField {
  name: string;
  label: string;
  type: 'text' | 'password' | 'select' | 'file' | 'textarea' | 'number' | 'multi-select';
  required: boolean;
  placeholder?: string;
  helperText?: string;
  options?: { value: string; label: string }[];
  // For multi-select fields that load options dynamically from API
  dynamicOptions?: boolean;
  // API endpoint to fetch options (relative path, e.g., 'datasets')
  optionsEndpoint?: string;
}

// Tool definition
export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  layer: PipelineLayer;
  configFields: ConfigField[];
}

// All available tools organized by layer with their config fields
export const TOOLS: Record<PipelineLayer, ToolDefinition[]> = {
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
        { name: 'host', label: 'Airbyte Host URL', type: 'text', required: true, placeholder: 'https://your-airbyte-instance.com' },
        { name: 'api_key', label: 'API Key', type: 'password', required: false, placeholder: 'API key (if authentication enabled)' },
        { name: 'workspace_id', label: 'Workspace ID', type: 'text', required: false, placeholder: 'Workspace ID' },
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
      configFields: [
        { name: 'api_key', label: 'Service Token', type: 'password', required: true, placeholder: 'Your dbt Cloud service token' },
        { name: 'account_id', label: 'Account ID', type: 'text', required: true, placeholder: 'dbt Cloud account ID' },
        { name: 'project_id', label: 'Project ID', type: 'text', required: false, placeholder: 'Optional: specific project ID' },
      ],
    },
    { 
      id: 'dbt_core', 
      name: 'dbt Core', 
      description: 'dbt Core (manifest upload)', 
      layer: 'TRANSFORMATION',
      configFields: [
        { name: 'manifest', label: 'Manifest File', type: 'file', required: true, helperText: 'Upload your manifest.json from target/ folder' },
        { name: 'project_name', label: 'Project Name', type: 'text', required: false, placeholder: 'Name to identify this dbt project' },
      ],
    },
    { 
      id: 'airflow', 
      name: 'Airflow', 
      description: 'Apache Airflow orchestration', 
      layer: 'TRANSFORMATION',
      configFields: [
        { name: 'host', label: 'Airflow Host', type: 'text', required: true, placeholder: 'https://your-airflow.com' },
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'Airflow username' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Airflow password' },
      ],
    },
    { 
      id: 'dagster', 
      name: 'Dagster', 
      description: 'Dagster orchestration', 
      layer: 'TRANSFORMATION',
      configFields: [
        { name: 'host', label: 'Dagster Host', type: 'text', required: true, placeholder: 'https://your-dagster.com' },
        { name: 'api_token', label: 'API Token', type: 'password', required: false, placeholder: 'Dagster Cloud token' },
      ],
    },
  ],
  WAREHOUSE: [
    { 
      id: 'snowflake', 
      name: 'Snowflake', 
      description: 'Snowflake Data Cloud', 
      layer: 'WAREHOUSE',
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
        { name: 'datasets', label: 'Datasets to Scan', type: 'multi-select', required: true, placeholder: 'Select datasets...', dynamicOptions: true, optionsEndpoint: 'datasets', helperText: 'Select one or more datasets to include in scans' },
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
        { name: 'username', label: 'Username', type: 'text', required: true, placeholder: 'admin@example.com' },
        { name: 'password', label: 'Password', type: 'password', required: true, placeholder: 'Password' },
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
