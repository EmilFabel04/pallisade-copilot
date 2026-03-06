import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { encrypt, decrypt } from '@/lib/crypto';

// GET /api/integrations - List all integrations for the user's organization
// Now includes both legacy Integrations AND Pipeline nodes for compatibility
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ integrations: [], pipelineNodes: [] });
    }

    // Optional: filter by stackId if provided
    const stackId = request.nextUrl.searchParams.get('stackId');

    // Fetch integrations — when stackId is provided, only return integrations
    // that either: (a) are linked to a node in that stack, or
    // (b) have NO pipeline nodes at all (standalone OAuth like Slack, GitHub)
    const integrationWhere: any = { organizationId: user.organizationId };
    if (stackId) {
      integrationWhere.OR = [
        { pipelineNodes: { some: { stackId } } },
        { pipelineNodes: { none: {} } },
      ];
    }

    const legacyIntegrations = await prisma.integration.findMany({
      where: integrationWhere,
      select: {
        id: true,
        name: true,
        type: true,
        status: true,
        connectionInfo: true,
        lastSyncAt: true,
        lastTestAt: true,
        lastError: true,
        healthScore: true,
        scanCount: true,
        lastScanAt: true,
        config: true,
        createdAt: true,
        updatedAt: true,
        pipelineNodes: { select: { id: true } },
      },
      orderBy: { createdAt: 'desc' },
    });

    // Fetch Pipeline nodes (new approach)
    const pipelineNodes = await prisma.pipelineNode.findMany({
      where: {
        stack: { organizationId: user.organizationId },
        ...(stackId ? { stackId } : {}),
      },
      select: {
        id: true,
        name: true,
        layer: true,
        toolType: true,
        status: true,
        lastTestedAt: true,
        lastError: true,
        healthScore: true,
        lastScanAt: true,
        findingsCount: true,
        criticalCount: true,
        highCount: true,
        createdAt: true,
        updatedAt: true,
        stackId: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    // Map pipeline nodes to integration-like format for backwards compatibility
    const pipelineAsIntegrations = pipelineNodes.map(node => ({
      id: node.id,
      name: node.name,
      type: mapToolTypeToIntegrationType(node.toolType),
      status: mapPipelineStatus(node.status),
      connectionInfo: `Pipeline: ${node.layer.toLowerCase()}`,
      lastSyncAt: null,
      lastTestAt: node.lastTestedAt,
      lastError: node.lastError,
      healthScore: node.healthScore,
      scanCount: null,
      lastScanAt: node.lastScanAt,
      config: null,
      createdAt: node.createdAt,
      updatedAt: node.updatedAt,
      // Extra fields to identify source
      source: 'pipeline' as const,
      layer: node.layer,
      stackId: node.stackId,
      findingsCount: node.findingsCount,
    }));

    // Combine both sources, with Pipeline nodes first.
    // Deduplicate: if a PipelineNode exists for a type, skip the legacy Integration
    // to prevent duplicate connector cards and duplicate auto-discovery records.
    const pipelineTypes = new Set(pipelineAsIntegrations.map(p => p.type));
    const dedupedLegacy = legacyIntegrations
      .filter(i => !pipelineTypes.has(i.type))
      .map(i => ({
        ...i,
        source: 'legacy' as const,
        managedByPipeline: (i.pipelineNodes?.length || 0) > 0,
      }));
    const allIntegrations = [...pipelineAsIntegrations, ...dedupedLegacy];

    return NextResponse.json({ 
      integrations: allIntegrations,
      // Also provide separate access for modern consumers
      pipelineNodes,
      legacyIntegrations,
    });
  } catch (error) {
    console.error('Error fetching integrations:', error);
    return NextResponse.json({ error: 'Failed to fetch integrations' }, { status: 500 });
  }
}

// Map pipeline tool types to integration types
function mapToolTypeToIntegrationType(toolType: string): string {
  const map: Record<string, string> = {
    'snowflake': 'SNOWFLAKE',
    'bigquery': 'BIGQUERY',
    'redshift': 'REDSHIFT',
    'postgres': 'POSTGRES',
    'sqlserver': 'SQLSERVER',
    'azure_sql': 'AZURE_SQL',
    'fivetran': 'FIVETRAN',
    'airbyte': 'AIRBYTE',
    'stitch': 'STITCH',
    'dbt_cloud': 'DBT_CLOUD',
    'dbt_core': 'DBT_CORE',
    'airflow': 'AIRFLOW',
    'dagster': 'DAGSTER',
    'n8n': 'N8N',
    'looker': 'LOOKER',
    'tableau': 'TABLEAU',
    'powerbi': 'POWERBI',
    'metabase': 'METABASE',
    'elementary': 'ELEMENTARY',
    'monte_carlo': 'MONTE_CARLO',
    'bigeye': 'BIGEYE',
    'soda': 'SODA',
    'databricks': 'DATABRICKS',
    'amazon_s3': 'AMAZON_S3',
    'gcs': 'GCS',
    'adls': 'ADLS',
  };
  return map[toolType] || toolType.toUpperCase();
}

// Map pipeline node status to integration status
function mapPipelineStatus(status: string): string {
  const map: Record<string, string> = {
    'CONNECTED': 'ACTIVE',
    'HEALTHY': 'ACTIVE',
    'WARNING': 'ACTIVE',
    'ERROR': 'ERROR',
    'FAILED': 'ERROR',
    'PENDING': 'INACTIVE',
    'TESTING': 'TESTING',
  };
  return map[status] || 'INACTIVE';
}

// POST /api/integrations - Create a new integration
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      include: { organization: true },
    });

    if (!user) {
      return NextResponse.json({ error: 'User not found' }, { status: 404 });
    }

    // Create organization if user doesn't have one
    let organizationId = user.organizationId;
    if (!organizationId) {
      const org = await prisma.organization.create({
        data: {
          name: `${user.name || user.email}'s Organization`,
          users: { connect: { id: user.id } },
        },
      });
      organizationId = org.id;
    }

    const body = await request.json();
    const { type, name, credentials, config } = body;

    if (!type || !name) {
      return NextResponse.json({ error: 'Type and name are required' }, { status: 400 });
    }

    // Encrypt credentials before storing
    const encryptedCredentials = credentials ? encrypt(JSON.stringify(credentials)) : null;

    // Generate connection info for display
    const connectionInfo = generateConnectionInfo(type, credentials, config);

    const integration = await prisma.integration.create({
      data: {
        type,
        name,
        credentials: encryptedCredentials ? { encrypted: encryptedCredentials } : undefined,
        config,
        connectionInfo,
        status: 'INACTIVE',
        organizationId,
      },
    });

    return NextResponse.json({
      integration: {
        id: integration.id,
        name: integration.name,
        type: integration.type,
        status: integration.status,
        connectionInfo: integration.connectionInfo,
        createdAt: integration.createdAt,
      },
    });
  } catch (error: any) {
    console.error('Error creating integration:', error);
    if (error.code === 'P2002') {
      return NextResponse.json({ error: 'An integration with this name already exists' }, { status: 409 });
    }
    return NextResponse.json({ error: 'Failed to create integration' }, { status: 500 });
  }
}

// Helper to generate human-readable connection info
function generateConnectionInfo(type: string, credentials: any, config: any): string {
  if (!credentials && !config) return '';

  switch (type) {
    case 'SNOWFLAKE':
      return `${credentials?.account || 'account'}.snowflakecomputing.com / ${credentials?.database || 'database'}`;
    case 'BIGQUERY':
      return `Project: ${credentials?.project_id || config?.project_id || 'unknown'}`;
    case 'REDSHIFT':
      return `${credentials?.host || 'cluster'} / ${credentials?.database || 'database'}`;
    case 'DATABRICKS':
      return `${credentials?.host || 'workspace'} / ${credentials?.catalog || 'hive_metastore'}`;
    case 'AMAZON_S3':
      return `S3: ${credentials?.bucket || 'all buckets'} (${credentials?.region || 'us-east-1'})`;
    case 'GCS':
      return `GCS: ${credentials?.project_id || 'project'} / ${credentials?.bucket || 'all buckets'}`;
    case 'ADLS':
      return `ADLS: ${credentials?.account_name || 'account'} / ${credentials?.container || 'all containers'}`;
    case 'POSTGRES':
    case 'MYSQL':
      return `${credentials?.host || 'localhost'}:${credentials?.port || '5432'} / ${credentials?.database || 'database'}`;
    case 'GITHUB':
      return config?.repos ? `${config.repos.length} repositories` : 'All accessible repos';
    case 'GITLAB':
      return config?.groups ? `${config.groups.length} groups` : 'All accessible projects';
    case 'DBT_CLOUD':
      return `Account: ${credentials?.account_id || config?.account_id || 'unknown'}`;
    case 'AIRFLOW':
      return credentials?.base_url || config?.base_url || 'Airflow instance';
    case 'PREFECT':
      return `Workspace: ${config?.workspace || 'default'}`;
    case 'SLACK':
      return config?.channel ? `#${config.channel}` : 'Slack workspace';
    case 'PAGERDUTY':
      return config?.service ? `Service: ${config.service}` : 'PagerDuty service';
    case 'JIRA':
      return `${credentials?.domain || config?.domain || 'atlassian'}.atlassian.net`;
    case 'LINEAR':
      return config?.team ? `Team: ${config.team}` : 'Linear workspace';
    case 'ELEMENTARY':
      return 'Elementary data observability';
    case 'MONTE_CARLO':
      return 'Monte Carlo data observability';
    case 'BIGEYE':
      return 'Bigeye data quality';
    case 'SODA':
      return 'Soda data quality';
    default:
      return '';
  }
}

