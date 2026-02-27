import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// GET /api/pipeline/[stackId]/nodes/[nodeId]/tables - Get data from any pipeline node
// Use ?refresh=true to force fresh discovery from warehouse
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
    const { searchParams } = new URL(request.url);
    const forceRefresh = searchParams.get('refresh') === 'true';

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Get the pipeline node (include integration for credential resolution)
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
        integration: true,
      },
    });

    if (!node) {
      return NextResponse.json({ error: 'Node not found' }, { status: 404 });
    }

    // Resolve credentials — prefer Integration table, fall back to legacy PipelineNode.config
    let credentials: Record<string, any> = {};
    let cachedData: Record<string, any> | null = (node.config as any)?._cached || null;

    if ((node as any).integrationId && (node as any).integration?.credentials) {
      try {
        const intCreds = (node as any).integration.credentials as any;
        if (intCreds.encrypted) {
          credentials = JSON.parse(decrypt(intCreds.encrypted));
        } else {
          credentials = intCreds;
        }
      } catch (e) {
        console.error('[NODE DATA] Integration credentials parsing failed:', e);
      }
    } else if (node.config) {
      try {
        const configJson = node.config as { encrypted?: string; _cached?: any; [key: string]: any };
        if (configJson.encrypted) {
          credentials = JSON.parse(decrypt(configJson.encrypted));
        } else {
          const { _cached, ...creds } = configJson;
          credentials = creds;
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

    // Return cached data if available and not forcing refresh
    if (!forceRefresh && cachedData && cachedData.data) {
      console.log(`[NODE DATA] Returning cached data for ${nodeId}, lastSync: ${cachedData.lastSync}`);
      return NextResponse.json({
        ...cachedData.data,
        source: 'cached',
        lastSync: cachedData.lastSync,
        connected: true,
      });
    }

    // Handle different node types (fetch fresh data)
    console.log(`[NODE DATA] Fetching fresh data for node: ${node.name} (${node.toolType}), layer=${node.layer}, status=${node.status}, forceRefresh=${forceRefresh}`);
    console.log(`[NODE DATA] Credentials keys: ${Object.keys(credentials).filter(k => !k.startsWith('_')).join(', ')}`);
    let result: Response;
    switch (node.layer) {
      case 'WAREHOUSE':
        result = await getWarehouseData(node, credentials);
        break;
      case 'TRANSFORMATION':
        result = await getTransformationData(node, credentials);
        break;
      case 'INGESTION':
        result = await getIngestionData(node, credentials);
        break;
      case 'REPORTING':
        result = await getReportingData(node, credentials);
        break;
      default:
        return NextResponse.json({ tables: [], models: [], connectors: [] });
    }

    // Cache the result if it was successful
    const responseData = await result.json();
    if (responseData.connected !== false && responseData.source !== 'error') {
      const lastSync = new Date().toISOString();
      try {
        // Store cached data in node config
        const currentConfig = node.config as Record<string, any> || {};
        await prisma.pipelineNode.update({
          where: { id: nodeId },
          data: {
            config: {
              ...currentConfig,
              _cached: {
                data: responseData,
                lastSync,
              },
            },
          },
        });
        console.log(`[NODE DATA] Cached data for ${nodeId}`);
        responseData.lastSync = lastSync;
      } catch (cacheErr) {
        console.error('[NODE DATA] Failed to cache data:', cacheErr);
      }
    }

    return NextResponse.json(responseData);
  } catch (error: any) {
    console.error('Error fetching node data:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// Get tables from warehouse nodes (Snowflake, BigQuery, Postgres, etc.)
async function getWarehouseData(node: any, credentials: Record<string, any>) {
  // Check connection status - allow CONNECTED, HEALTHY, WARNING (exclude PENDING, TESTING, ERROR)
  const validStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];
  if (!validStatuses.includes(node.status)) {
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
    console.error(`[WAREHOUSE] Scanner error for ${node.toolType}: ${err.message}`);
    // Return error instead of demo data so user knows there's a problem
    return NextResponse.json({
      tables: [],
      source: 'error',
      connected: false,
      error: `Scanner unavailable: ${err.message}`,
      message: `Could not fetch tables from ${node.toolType}. Make sure the scanner is running and credentials are correct.`,
    });
  }

  // If we get here, scanner returned empty/invalid data
  console.log(`[WAREHOUSE] Scanner returned no data for ${node.toolType}`);
  return NextResponse.json({
    tables: [],
    source: 'empty',
    connected: true,
    message: 'No tables found. Check your database/schema configuration.',
  });
}

// Get dbt models from transformation nodes
async function getTransformationData(node: any, credentials: Record<string, any>) {
  const validStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];
  const isConnected = validStatuses.includes(node.status);

  if (node.toolType === 'dbt_cloud' || node.toolType === 'dbt_core') {
    // For dbt Core with uploaded manifest, parse it directly
    if (node.toolType === 'dbt_core' && credentials.manifest) {
      try {
        console.log('[DBT CORE] Parsing uploaded manifest content');
        const manifest = typeof credentials.manifest === 'string'
          ? JSON.parse(credentials.manifest)
          : credentials.manifest;

        const models: any[] = [];
        const tests: any[] = [];
        const sources: any[] = [];

        // Extract models and tests from nodes
        for (const [nodeId, nodeData] of Object.entries(manifest.nodes || {})) {
          const n = nodeData as any;
          if (n.resource_type === 'model') {
            models.push({
              name: n.name,
              schema: n.schema,
              database: n.database,
              materialization: n.config?.materialized || 'view',
              description: n.description || '',
              path: n.path,
              unique_id: nodeId,
              columns: Object.keys(n.columns || {}).length,
            });
          } else if (n.resource_type === 'test') {
            tests.push({
              name: n.name,
              test_type: n.test_metadata?.name || 'generic',
            });
          }
        }

        // Extract sources
        for (const [sourceId, sourceData] of Object.entries(manifest.sources || {})) {
          const s = sourceData as any;
          sources.push({
            name: s.name,
            source_name: s.source_name,
            schema: s.schema,
            database: s.database,
          });
        }

        console.log(`[DBT CORE] Found ${models.length} models, ${tests.length} tests, ${sources.length} sources`);

        return NextResponse.json({
          models,
          tests,
          sources,
          tables: [],
          source: 'manifest',
          connected: true,
        });
      } catch (err: any) {
        console.error('[DBT CORE] Failed to parse manifest:', err.message);
        return NextResponse.json({
          models: [],
          tables: [],
          source: 'error',
          connected: false,
          error: `Failed to parse manifest: ${err.message}`,
        });
      }
    }

    // For dbt Cloud or dbt Core with paths, use scanner
    try {
      const configType = node.toolType === 'dbt_cloud' ? 'cloud' : 'core';

      let config: Record<string, any>;
      if (configType === 'cloud') {
        // Map api_token to api_key (frontend uses api_token)
        config = {
          api_key: credentials.api_token || credentials.api_key,
          account_id: credentials.account_id,
          project_id: credentials.project_id,
          environment_id: credentials.environment_id,
          api_mode: credentials.api_mode,
        };
      } else {
        config = {
          project_path: credentials.project_path || credentials.projectPath,
          manifest_path: credentials.manifest_path || credentials.manifestPath,
          profiles_dir: credentials.profiles_dir || credentials.profilesDir,
        };
      }

      console.log(`[DBT] Fetching ${configType} models from scanner`);
      const response = await fetch(`${SCANNER_API_URL}/api/v1/dbt/models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config_type: configType,
          config,
        }),
        signal: AbortSignal.timeout(15000),
      });

      const data = await response.json();
      console.log(`[DBT] Scanner response: success=${data.success}, models=${data.models?.length || 0}`);

      if (data.success && data.models && data.models.length > 0) {
        return NextResponse.json({
          models: data.models,
          tests: data.tests || [],
          sources: data.sources || [],
          tables: [],
          source: data.source || 'live',
          connected: true,
        });
      } else if (data.error) {
        console.log(`[DBT] Scanner error: ${data.error}`);
        return NextResponse.json({
          models: [],
          tables: [],
          source: 'error',
          connected: false,
          error: data.error,
        });
      }
    } catch (err: any) {
      console.error(`[DBT] Scanner error: ${err.message}`);
      return NextResponse.json({
        models: [],
        tables: [],
        source: 'error',
        connected: false,
        error: `Scanner unavailable: ${err.message}`,
        message: node.toolType === 'dbt_cloud'
          ? 'Could not fetch dbt Cloud models. Check your API token and account ID.'
          : 'Could not fetch dbt models. Make sure the scanner is running.',
      });
    }

    // Scanner returned empty/no data
    return NextResponse.json({
      models: [],
      tables: [],
      source: 'empty',
      connected: isConnected,
      message: 'No dbt models found.',
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
      connected: isConnected,
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
      connected: isConnected,
    });
  }

  return NextResponse.json({ tables: [], models: [] });
}

// Get connectors from ingestion nodes (Fivetran, Airbyte)
async function getIngestionData(node: any, credentials: Record<string, any>) {
  const validStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];
  const isConnected = validStatuses.includes(node.status);

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
      connected: isConnected,
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
      connected: isConnected,
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
      connected: isConnected,
    });
  }

  return NextResponse.json({ connectors: [], tables: [] });
}

// Get reporting tool data (Looker, Tableau, etc.)
async function getReportingData(node: any, credentials: Record<string, any>) {
  const validStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];
  const isConnected = validStatuses.includes(node.status);

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
    connected: isConnected,
  });
}
