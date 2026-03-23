import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// POST /api/pipeline/[stackId]/nodes/[nodeId]/schemas - Get available schemas (Snowflake, Postgres)
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId, nodeId } = await params;
    const body = await request.json().catch(() => ({}));

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Get the pipeline node (may not exist yet for unsaved nodes)
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

    // Use config from request body (for unsaved/new nodes) or resolve from Integration/node
    let credentials: Record<string, any> = {};
    let toolType = body.toolType || node?.toolType;

    if (body.config && Object.keys(body.config).length > 0) {
      credentials = body.config;
    } else if ((node as any)?.integrationId && (node as any)?.integration?.credentials) {
      // Prefer Integration table
      try {
        const intCreds = (node as any).integration.credentials as any;
        if (intCreds.encrypted) {
          credentials = JSON.parse(decrypt(intCreds.encrypted));
        } else {
          credentials = intCreds;
        }
      } catch (e) {
        console.error('[SCHEMAS] Integration credentials decryption failed:', e);
        return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
      }
    } else if (node?.config) {
      // Legacy fallback: PipelineNode.config
      try {
        const configJson = node.config as { encrypted?: string; [key: string]: any };
        if (configJson.encrypted) {
          credentials = JSON.parse(decrypt(configJson.encrypted));
        } else {
          credentials = configJson;
        }
      } catch (e) {
        console.error('[SCHEMAS] Credentials decryption failed:', e);
        return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
      }
    }

    if (!toolType) {
      return NextResponse.json({ error: 'Could not determine tool type' }, { status: 400 });
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

    const connectionType = connectionTypeMap[toolType] || toolType;

    // Map frontend field names to adapter field names
    const connConfig = { ...credentials };
    if (connConfig.username && !connConfig.user) {
      connConfig.user = connConfig.username;
      delete connConfig.username;
    }

    // Fetch schemas from scanner backend
    console.log('[SCHEMAS] Calling scanner at:', `${SCANNER_API_URL}/api/v1/schemas`);
    console.log('[SCHEMAS] Connection type:', connectionType);

    try {
      const response = await fetch(`${SCANNER_API_URL}/api/v1/schemas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_type: connectionType,
          connection_config: connConfig,
        }),
        signal: AbortSignal.timeout(30000),
      });

      console.log('[SCHEMAS] Scanner response status:', response.status);
      
      const data = await response.json();
      console.log('[SCHEMAS] Scanner response:', data.success, 'schemas:', data.datasets?.length || 0);
      
      if (data.success && data.datasets) {
        // Return as schemas for consistency with the field name
        return NextResponse.json({
          schemas: data.datasets || [],
          count: data.count || data.datasets.length,
          source: 'scanner',
        });
      } else {
        console.log('[SCHEMAS] Scanner returned error:', data.error);
        return NextResponse.json({ 
          error: data.error || 'Failed to fetch schemas',
          schemas: [],
        }, { status: 400 });
      }
    } catch (err: any) {
      console.log('[SCHEMAS] Scanner backend error:', err.message);
      return NextResponse.json({ 
        error: 'Failed to connect to scanner backend',
        schemas: [],
      }, { status: 500 });
    }
  } catch (error: any) {
    console.error('Error fetching schemas:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  return POST(request, { params });
}
