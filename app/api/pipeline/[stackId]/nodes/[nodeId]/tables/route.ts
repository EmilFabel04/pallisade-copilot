import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// GET /api/pipeline/[stackId]/nodes/[nodeId]/tables - Get data from any pipeline node
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId, nodeId } = await params;

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Get the pipeline node
    const node = await prisma.pipelineNode.findFirst({
      where: {
        id: nodeId,
        stackId: stackId,
        stack: {
          organizationId: user.organizationId,
        },
      },
      include: {
        stack: true,
      },
    });

    if (!node) {
      return NextResponse.json({ error: 'Node not found' }, { status: 404 });
    }

    // Get credentials from node config
    let credentials: Record<string, any> = {};
    if (node.config) {
      try {
        const configJson = node.config as { encrypted?: string; [key: string]: any };
        if (configJson.encrypted) {
          // Decrypt if credentials are encrypted
          const decrypted = decrypt(configJson.encrypted);
          credentials = JSON.parse(decrypted);
        } else {
          // Config is stored directly (not encrypted)
          credentials = configJson;
        }
      } catch (e) {
        console.error('[NODE DATA] Credentials parsing failed:', e);
      }
    }

    // Check if node has been configured
    if (!node.config || Object.keys(credentials).length === 0) {
      console.log(`[NODE DATA] Node ${nodeId} (${node.toolType}) has no configuration`);
      return NextResponse.json({
        tables: [],
        models: [],
        connectors: [],
        source: 'unconfigured',
        connected: false,
        message: 'Node not configured. Please add credentials in the pipeline editor.',
      });
    }

    // Handle different node types
    switch (node.layer) {
      case 'WAREHOUSE':
        return await getWarehouseData(node, credentials);
      case 'TRANSFORMATION':
        return await getTransformationData(node, credentials);
      case 'INGESTION':
        return await getIngestionData(node, credentials);
      case 'REPORTING':
        return await getReportingData(node, credentials);
      default:
        return NextResponse.json({ tables: [], models: [], connectors: [] });
    }
  } catch (error: any) {
    console.error('Error fetching node data:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// Get tables from warehouse nodes (Snowflake, BigQuery, Postgres, etc.)
async function getWarehouseData(node: any, credentials: Record<string, any>) {
  // Check connection status
  if (node.status !== 'CONNECTED' && node.status !== 'ACTIVE' && node.status !== 'HEALTHY') {
    console.log(`[WAREHOUSE] Node ${node.id} not connected. Status: ${node.status}`);
    return NextResponse.json({
      tables: [],
      status: node.status,
      connected: false,
      source: 'disconnected',
      message: `Node status is ${node.status}. Test the connection first.`,
    });
  }

  const connectionTypeMap: Record<string, string> = {
    'snowflake': 'snowflake',
    'bigquery': 'bigquery',
    'redshift': 'redshift',
    'postgres': 'postgres',
    'sqlserver': 'sqlserver',
    'azure_sql': 'sqlserver',
  };

  const connectionType = connectionTypeMap[node.toolType] || node.toolType;

  // Validate required credentials for each warehouse type
  if (connectionType === 'bigquery' && !credentials.project_id) {
    console.log('[WAREHOUSE] BigQuery missing project_id');
    return NextResponse.json({
      tables: [],
      connected: false,
      source: 'misconfigured',
      message: 'BigQuery requires project_id to be configured.',
    });
  }

  if (connectionType === 'snowflake' && (!credentials.account || !credentials.database)) {
    console.log('[WAREHOUSE] Snowflake missing account or database');
    return NextResponse.json({
      tables: [],
      connected: false,
      source: 'misconfigured',
      message: 'Snowflake requires account and database to be configured.',
    });
  }

  // Map frontend field names to scanner expected names
  const scannerCredentials = { ...credentials };

  // Snowflake: frontend uses 'username', scanner expects 'user'
  if (connectionType === 'snowflake' && credentials.username && !credentials.user) {
    scannerCredentials.user = credentials.username;
  }

  // Postgres/Redshift: frontend uses 'username', scanner expects 'user'
  if ((connectionType === 'postgres' || connectionType === 'redshift') && credentials.username && !credentials.user) {
    scannerCredentials.user = credentials.username;
  }

  // SQL Server: frontend uses 'server', scanner expects 'host'
  if (connectionType === 'sqlserver' && credentials.server && !credentials.host) {
    scannerCredentials.host = credentials.server;
  }

  // Try to fetch tables from scanner backend
  try {
    console.log(`[WAREHOUSE] Fetching tables from scanner: ${SCANNER_API_URL}/api/v1/tables`);
    console.log(`[WAREHOUSE] Connection type: ${connectionType}, project_id: ${scannerCredentials.project_id}, datasets: ${scannerCredentials.datasets}`);

    const response = await fetch(`${SCANNER_API_URL}/api/v1/tables`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        connection_type: connectionType,
        connection_config: scannerCredentials,
      }),
      signal: AbortSignal.timeout(30000), // Increased timeout for BigQuery
    });

    const data = await response.json();
    console.log(`[WAREHOUSE] Scanner response: success=${data.success}, tables=${data.tables?.length || 0}`);

    if (data.success && data.tables) {
      // Scanner already returns properly formatted TableInfo objects
      return NextResponse.json({
        tables: data.tables,
        schemas: data.schemas || [],
        datasets: data.datasets || credentials.datasets || [],
        source: 'live',
        connected: true,
      });
    } else if (data.error) {
      console.log(`[WAREHOUSE] Scanner returned error: ${data.error}`);
      // Return the error but still show something
      return NextResponse.json({
        tables: [],
        error: data.error,
        source: 'error',
        connected: false,
        message: `Failed to fetch tables: ${data.error}`,
      });
    }
  } catch (err: any) {
    console.log(`[WAREHOUSE] Scanner not available: ${err.message}`);
    // Fall through to demo data
  }

  console.log(`[WAREHOUSE] Falling back to demo data for ${node.toolType}`);

  // Generate demo tables based on tool type
  if (node.toolType === 'bigquery') {
    return generateBigQueryDemoData(credentials);
  }

  return generateGenericWarehouseDemoData(credentials);
}

// Generate BigQuery-specific demo data using configured datasets
function generateBigQueryDemoData(credentials: Record<string, any>) {
  const projectId = credentials.project_id || 'my-project';
  const configuredDatasets = credentials.datasets || ['analytics', 'staging'];
  
  const tablesByDataset: Record<string, string[]> = {
    'analytics': ['customers', 'orders', 'products', 'order_items', 'users', 'events', 'sessions'],
    'staging': ['stg_customers', 'stg_orders', 'stg_products', 'stg_payments'],
    'marts': ['dim_customers', 'dim_products', 'dim_dates', 'fct_orders', 'fct_revenue'],
    'raw': ['raw_stripe_payments', 'raw_shopify_orders', 'raw_salesforce_contacts'],
  };

  const tables: any[] = [];
  
  for (const dataset of configuredDatasets) {
    const datasetTables = tablesByDataset[dataset] || tablesByDataset['analytics'];
    for (const tableName of datasetTables) {
      tables.push({
        name: tableName,
        dataset: dataset,
        schema: dataset,
        database: projectId,
        columns: Math.floor(Math.random() * 20) + 5,
        rowCount: Math.floor(Math.random() * 100000) + 1000,
      });
    }
  }

  return NextResponse.json({
    tables,
    datasets: configuredDatasets,
    source: 'demo',
    connected: true,
  });
}

// Generate generic warehouse demo data
function generateGenericWarehouseDemoData(credentials: Record<string, any>) {
  const database = credentials.database || 'analytics';
  const schemas = credentials.schemas || ['analytics', 'staging', 'marts'];
  
  const tablesBySchema: Record<string, string[]> = {
    'analytics': ['customers', 'orders', 'products', 'order_items', 'users'],
    'staging': ['stg_customers', 'stg_orders', 'stg_products'],
    'marts': ['dim_customers', 'dim_products', 'fct_orders'],
    'public': ['customers', 'orders', 'products'],
  };

  const tables: any[] = [];
  
  for (const schema of schemas) {
    const schemaTables = tablesBySchema[schema] || tablesBySchema['public'];
    for (const tableName of schemaTables) {
      tables.push({
        name: tableName,
        schema: schema,
        database: database,
        columns: Math.floor(Math.random() * 20) + 5,
        rowCount: Math.floor(Math.random() * 100000) + 1000,
      });
    }
  }

  return NextResponse.json({
    tables,
    schemas,
    source: 'demo',
    connected: true,
  });
}

// Get dbt models from transformation nodes
async function getTransformationData(node: any, credentials: Record<string, any>) {
  if (node.toolType === 'dbt_cloud' || node.toolType === 'dbt_core') {
    // Try to fetch from scanner/dbt integration
    try {
      const response = await fetch(`${SCANNER_API_URL}/api/v1/dbt/models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: credentials.api_key,
          account_id: credentials.account_id,
          project_id: credentials.project_id,
        }),
        signal: AbortSignal.timeout(15000),
      });
      
      const data = await response.json();
      if (data.models) {
        return NextResponse.json({
          models: data.models,
          tables: [],
          source: 'live',
          connected: true,
        });
      }
    } catch (err) {
      console.log('[DBT] Scanner not available, using demo data');
    }

    // Demo dbt models
    const demoModels = [
      { name: 'stg_customers', schema: 'staging', materialization: 'view', description: 'Staged customer data from source', testCount: 3 },
      { name: 'stg_orders', schema: 'staging', materialization: 'view', description: 'Staged order data', testCount: 4 },
      { name: 'stg_products', schema: 'staging', materialization: 'view', description: 'Staged product catalog', testCount: 2 },
      { name: 'int_orders_pivoted', schema: 'intermediate', materialization: 'table', description: 'Orders pivoted by status', testCount: 1 },
      { name: 'dim_customers', schema: 'marts', materialization: 'table', description: 'Customer dimension table', testCount: 5 },
      { name: 'dim_products', schema: 'marts', materialization: 'table', description: 'Product dimension table', testCount: 3 },
      { name: 'fct_orders', schema: 'marts', materialization: 'incremental', description: 'Order facts with daily partitions', testCount: 8 },
      { name: 'fct_daily_revenue', schema: 'marts', materialization: 'incremental', description: 'Daily revenue aggregations', testCount: 4 },
    ];

    return NextResponse.json({
      models: demoModels,
      tables: [],
      source: 'demo',
      connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
    });
  }

  // Airflow/Dagster
  if (node.toolType === 'airflow') {
    return NextResponse.json({
      tables: [],
      models: [],
      dags: [
        { name: 'daily_etl', status: 'success', lastRun: '2 hours ago' },
        { name: 'hourly_sync', status: 'running', lastRun: '5 min ago' },
        { name: 'weekly_reports', status: 'success', lastRun: '3 days ago' },
      ],
      source: 'demo',
      connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
    });
  }

  if (node.toolType === 'dagster') {
    return NextResponse.json({
      tables: [],
      models: [],
      assets: [
        { name: 'raw_data', status: 'materialized', lastRun: '1 hour ago' },
        { name: 'cleaned_data', status: 'materialized', lastRun: '1 hour ago' },
        { name: 'analytics', status: 'pending', lastRun: '1 day ago' },
      ],
      source: 'demo',
      connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
    });
  }

  return NextResponse.json({ tables: [], models: [] });
}

// Get connectors from ingestion nodes (Fivetran, Airbyte)
async function getIngestionData(node: any, credentials: Record<string, any>) {
  if (node.toolType === 'fivetran') {
    // Try to fetch from Fivetran API
    try {
      const response = await fetch(`${SCANNER_API_URL}/api/v1/fivetran/connectors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: credentials.api_key,
          api_secret: credentials.api_secret,
          group_id: credentials.group_id,
        }),
        signal: AbortSignal.timeout(15000),
      });
      
      const data = await response.json();
      if (data.connectors) {
        return NextResponse.json({
          connectors: data.connectors,
          tables: [],
          source: 'live',
          connected: true,
        });
      }
    } catch (err) {
      console.log('[FIVETRAN] Scanner not available, using demo data');
    }

    // Demo Fivetran connectors
    const demoConnectors = [
      { name: 'Stripe', status: 'active', lastSync: '5 min ago' },
      { name: 'Salesforce', status: 'active', lastSync: '1 hour ago' },
      { name: 'HubSpot', status: 'active', lastSync: '30 min ago' },
      { name: 'Google Analytics', status: 'paused', lastSync: '2 days ago' },
      { name: 'PostgreSQL Production', status: 'active', lastSync: '15 min ago' },
    ];

    return NextResponse.json({
      connectors: demoConnectors,
      tables: [],
      source: 'demo',
      connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
    });
  }

  if (node.toolType === 'airbyte') {
    const demoConnectors = [
      { name: 'MySQL Source', status: 'active', lastSync: '10 min ago' },
      { name: 'Shopify', status: 'active', lastSync: '2 hours ago' },
      { name: 'Zendesk', status: 'failed', lastSync: '1 day ago' },
    ];

    return NextResponse.json({
      connectors: demoConnectors,
      tables: [],
      source: 'demo',
      connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
    });
  }

  if (node.toolType === 'stitch') {
    const demoConnectors = [
      { name: 'MongoDB', status: 'active', lastSync: '20 min ago' },
      { name: 'Intercom', status: 'active', lastSync: '1 hour ago' },
    ];

    return NextResponse.json({
      connectors: demoConnectors,
      tables: [],
      source: 'demo',
      connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
    });
  }

  return NextResponse.json({ connectors: [], tables: [] });
}

// Get reporting tool data (Looker, Tableau, etc.)
async function getReportingData(node: any, credentials: Record<string, any>) {
  const dashboards = [
    { name: 'Executive Summary', views: 1245, lastViewed: '2 hours ago' },
    { name: 'Sales Dashboard', views: 892, lastViewed: '30 min ago' },
    { name: 'Marketing Analytics', views: 567, lastViewed: '1 day ago' },
  ];

  return NextResponse.json({
    tables: [],
    models: [],
    connectors: [],
    dashboards,
    source: 'demo',
    connected: node.status === 'ACTIVE' || node.status === 'CONNECTED',
  });
}
