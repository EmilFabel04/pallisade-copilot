import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';

// POST /api/pipeline/[stackId]/nodes/[nodeId]/schemas - Get available schemas (Snowflake, Postgres)
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
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

    // Only warehouse nodes have schemas
    if (node.layer !== 'WAREHOUSE') {
      return NextResponse.json({ 
        error: 'Schema discovery is only available for warehouse nodes',
        layer: node.layer,
      }, { status: 400 });
    }

    // Use config from request body (for unsaved changes) or from node
    let credentials: Record<string, any> = {};
    
    if (body.config && Object.keys(body.config).length > 0) {
      credentials = body.config;
    } else if (node.config) {
      try {
        const configJson = node.config as { encrypted?: string; [key: string]: any };
        if (configJson.encrypted) {
          const decrypted = decrypt(configJson.encrypted);
          credentials = JSON.parse(decrypted);
        } else {
          credentials = configJson;
        }
      } catch (e) {
        console.error('[SCHEMAS] Credentials decryption failed:', e);
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

    // Fetch schemas from scanner backend (uses same datasets endpoint)
    console.log('[SCHEMAS] Calling scanner at:', `${SCANNER_API_URL}/api/datasets`);
    console.log('[SCHEMAS] Connection type:', connectionType);
    
    try {
      const response = await fetch(`${SCANNER_API_URL}/api/datasets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_type: connectionType,
          connection_config: credentials,
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
