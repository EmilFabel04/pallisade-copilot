import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';

// GET /api/pipeline/[stackId]/nodes/[nodeId]/tables - Get tables from a warehouse node
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

    // Only warehouse nodes have tables
    if (node.layer !== 'WAREHOUSE') {
      return NextResponse.json({ 
        error: 'Table discovery is only available for warehouse nodes',
        layer: node.layer,
      }, { status: 400 });
    }

    // Check connection status
    if (node.status !== 'CONNECTED' && node.status !== 'HEALTHY') {
      return NextResponse.json({ 
        error: 'Node is not connected',
        status: node.status,
      }, { status: 400 });
    }

    // Decrypt credentials from node config
    let credentials: Record<string, any> = {};
    if (node.config) {
      try {
        const configJson = node.config as { encrypted?: string; [key: string]: any };
        if (configJson.encrypted) {
          const decrypted = decrypt(configJson.encrypted);
          credentials = JSON.parse(decrypted);
        } else {
          // Config might not be encrypted (for testing)
          credentials = configJson;
        }
      } catch (e) {
        console.error('[TABLES] Credentials decryption failed:', e);
        return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
      }
    }

    if (Object.keys(credentials).length === 0) {
      return NextResponse.json({ error: 'No credentials configured' }, { status: 400 });
    }

    // Map tool type to connection type
    const connectionTypeMap: Record<string, string> = {
      'snowflake': 'snowflake',
      'bigquery': 'bigquery',
      'redshift': 'redshift',
      'postgres': 'postgres',
      'sqlserver': 'sqlserver',
      'azure_sql': 'sqlserver',
    };

    const connectionType = connectionTypeMap[node.toolType] || node.toolType;

    // Try to fetch tables from scanner backend
    console.log('[TABLES] Calling scanner at:', `${SCANNER_API_URL}/api/v1/tables`);
    console.log('[TABLES] Connection type:', connectionType);
    console.log('[TABLES] Credentials keys:', Object.keys(credentials));
    
    try {
      const response = await fetch(`${SCANNER_API_URL}/api/v1/tables`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_type: connectionType,
          connection_config: credentials,
        }),
        signal: AbortSignal.timeout(15000),
      });

      console.log('[TABLES] Scanner response status:', response.status);
      
      const data = await response.json();
      console.log('[TABLES] Scanner response:', data.success, 'tables:', data.tables?.length || 0);
      
      if (data.success && data.tables) {
        return NextResponse.json({
          tables: data.tables || [],
          schemas: data.schemas || [],
          source: 'scanner',
        });
      } else {
        console.log('[TABLES] Scanner returned error:', data.error);
      }
    } catch (err) {
      console.log('[TABLES] Scanner backend not available:', err);
    }

    // Fallback: Return demo tables based on tool type
    const demoTables = generateDemoTables(node.toolType, credentials);
    
    return NextResponse.json({
      tables: demoTables,
      schemas: ['analytics', 'public', 'staging'],
      source: 'demo',
      demo: true,
    });
  } catch (error: any) {
    console.error('Error fetching tables:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

function generateDemoTables(toolType: string, credentials: Record<string, any>): string[] {
  const schema = credentials.schema || 'analytics';
  const database = credentials.database || 'demo_db';

  // Generate realistic table names based on common data warehouse patterns
  const tables = [
    `${database}.${schema}.customers`,
    `${database}.${schema}.orders`,
    `${database}.${schema}.products`,
    `${database}.${schema}.order_items`,
    `${database}.${schema}.payments`,
    `${database}.${schema}.users`,
    `${database}.${schema}.events`,
    `${database}.${schema}.sessions`,
    `${database}.staging.raw_customers`,
    `${database}.staging.raw_orders`,
    `${database}.staging.raw_products`,
  ];

  return tables;
}
