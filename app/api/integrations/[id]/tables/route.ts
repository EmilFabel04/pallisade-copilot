import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';

// GET /api/integrations/[id]/tables - Discover tables from connected warehouse
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { id } = await params;

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Get the integration
    const integration = await prisma.integration.findFirst({
      where: {
        id,
        organizationId: user.organizationId,
      },
    });

    if (!integration) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    // Only data warehouses can discover tables
    const warehouseTypes = ['SNOWFLAKE', 'BIGQUERY', 'REDSHIFT', 'DATABRICKS', 'POSTGRES', 'MYSQL', 'SQLSERVER', 'AZURE_SQL', 'AZURE_SYNAPSE'];
    if (!warehouseTypes.includes(integration.type)) {
      return NextResponse.json({ error: 'This integration type does not support table discovery' }, { status: 400 });
    }

    // Decrypt credentials
    let credentials: Record<string, any> = {};
    if (integration.credentials) {
      try {
        const credentialsJson = integration.credentials as { encrypted?: string };
        if (credentialsJson.encrypted) {
          const decrypted = decrypt(credentialsJson.encrypted);
          credentials = JSON.parse(decrypted);
        }
      } catch (e) {
        console.error('[TABLES] Credentials decryption failed:', e);
        return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
      }
    }

    if (Object.keys(credentials).length === 0) {
      return NextResponse.json({ error: 'No credentials found' }, { status: 400 });
    }

    // Map integration type to connection type
    const connectionTypeMap: Record<string, string> = {
      'SNOWFLAKE': 'snowflake',
      'BIGQUERY': 'bigquery',
      'REDSHIFT': 'redshift',
      'DATABRICKS': 'databricks',
      'POSTGRES': 'postgres',
      'MYSQL': 'mysql',
      'SQLSERVER': 'sqlserver',
      'AZURE_SQL': 'sqlserver',
      'AZURE_SYNAPSE': 'sqlserver',
    };

    // Try to discover tables from the Python backend
    let tables: any[] = [];
    let useBackend = false;

    try {
      const healthCheck = await scannerClient.fetch(session, '/health', {
        method: 'GET',
        signal: AbortSignal.timeout(3000),
      });
      useBackend = healthCheck.ok;
    } catch {
      console.log('[TABLES] Scanner backend not available');
    }

    if (useBackend) {
      try {
        const response = await scannerClient.fetch(session, '/api/tables', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            connection_type: connectionTypeMap[integration.type],
            connection_config: credentials,
          }),
          signal: AbortSignal.timeout(30000), // 30s timeout for table discovery
        });

        if (response.ok) {
          const data = await response.json();
          tables = data.tables || [];
          
          // Update integration metadata with discovered tables
          await prisma.integration.update({
            where: { id: integration.id },
            data: {
              metadata: {
                ...(integration.metadata as object || {}),
                tables,
                tableCount: tables.length,
                lastTableDiscovery: new Date().toISOString(),
              },
              lastSyncAt: new Date(),
            },
          });

          return NextResponse.json({
            success: true,
            tables,
            count: tables.length,
            database: credentials.database || 'Unknown',
            schema: credentials.schema || 'public',
            integration: {
              id: integration.id,
              name: integration.name,
              type: integration.type,
            },
          });
        } else {
          const errorData = await response.json().catch(() => ({}));
          console.error('[TABLES] Backend error:', errorData);
        }
      } catch (backendError) {
        console.error('[TABLES] Backend call failed:', backendError);
      }
    }

    // Fallback: Return cached tables or demo tables
    const cachedMetadata = integration.metadata as { tables?: string[] } | null;
    if (cachedMetadata?.tables && cachedMetadata.tables.length > 0) {
      return NextResponse.json({
        success: true,
        tables: cachedMetadata.tables,
        count: cachedMetadata.tables.length,
        database: credentials.database || 'Unknown',
        schema: credentials.schema || 'public',
        cached: true,
        integration: {
          id: integration.id,
          name: integration.name,
          type: integration.type,
        },
      });
    }

    // Return demo tables based on integration type
    const demoTables = getDemoTables(integration.type, credentials);
    
    return NextResponse.json({
      success: true,
      tables: demoTables,
      count: demoTables.length,
      database: credentials.database || 'Unknown',
      schema: credentials.schema || 'public',
      demo: true,
      message: 'Scanner backend offline - showing example tables',
      integration: {
        id: integration.id,
        name: integration.name,
        type: integration.type,
      },
    });

  } catch (error: any) {
    console.error('Table discovery error:', error);
    return NextResponse.json({ error: error.message || 'Discovery failed' }, { status: 500 });
  }
}

function getDemoTables(integrationType: string, credentials: Record<string, any>): string[] {
  const database = credentials.database || 'DEMO_DB';
  const schema = credentials.schema || 'PUBLIC';
  const prefix = `${database}.${schema}`;

  // Return realistic demo tables based on warehouse type
  return [
    `${prefix}.users`,
    `${prefix}.orders`,
    `${prefix}.products`,
    `${prefix}.transactions`,
    `${prefix}.events`,
    `${prefix}.customers`,
    `${prefix}.inventory`,
    `${prefix}.audit_log`,
    `${prefix}.daily_metrics`,
    `${prefix}.sessions`,
    `${prefix}.payments`,
    `${prefix}.subscriptions`,
  ];
}

