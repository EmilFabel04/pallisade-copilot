import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// POST /api/pipeline/[stackId]/nodes/[nodeId]/datasets - Get available datasets/schemas
// POST is used because config might be passed in body (for nodes not yet saved)
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

    // Only warehouse nodes have datasets
    if (node.layer !== 'WAREHOUSE') {
      return NextResponse.json({
        error: 'Dataset discovery is only available for warehouse nodes',
        layer: node.layer,
      }, { status: 400 });
    }

    // Use config from request body (for unsaved changes), Integration table, or legacy node config
    let credentials: Record<string, any> = {};

    if (body.config && Object.keys(body.config).length > 0) {
      credentials = body.config;
    } else if ((node as any).integrationId && (node as any).integration?.credentials) {
      // Prefer Integration table
      try {
        const intCreds = (node as any).integration.credentials as any;
        if (intCreds.encrypted) {
          credentials = JSON.parse(decrypt(intCreds.encrypted));
        } else {
          credentials = intCreds;
        }
      } catch (e) {
        console.error('[DATASETS] Integration credentials decryption failed:', e);
        return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
      }
    } else if (node.config) {
      // Legacy fallback
      try {
        const configJson = node.config as { encrypted?: string; [key: string]: any };
        if (configJson.encrypted) {
          credentials = JSON.parse(decrypt(configJson.encrypted));
        } else {
          credentials = configJson;
        }
      } catch (e) {
        console.error('[DATASETS] Credentials decryption failed:', e);
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

    // Fetch datasets from scanner backend (uses /schemas endpoint)
    console.log('[DATASETS] Calling scanner at:', `${SCANNER_API_URL}/api/v1/schemas`);
    console.log('[DATASETS] Connection type:', connectionType);

    try {
      const response = await fetch(`${SCANNER_API_URL}/api/v1/schemas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_type: connectionType,
          connection_config: credentials,
        }),
        signal: AbortSignal.timeout(30000), // 30 second timeout
      });

      console.log('[DATASETS] Scanner response status:', response.status);
      
      const data = await response.json();
      console.log('[DATASETS] Scanner response:', data.success, 'datasets:', data.datasets?.length || 0);
      
      if (data.success && data.datasets) {
        return NextResponse.json({
          datasets: data.datasets || [],
          count: data.count || data.datasets.length,
          source: 'scanner',
        });
      } else {
        console.log('[DATASETS] Scanner returned error:', data.error);
        return NextResponse.json({ 
          error: data.error || 'Failed to fetch datasets',
          datasets: [],
        }, { status: 400 });
      }
    } catch (err: any) {
      console.log('[DATASETS] Scanner backend error:', err.message);
      return NextResponse.json({ 
        error: 'Failed to connect to scanner backend',
        datasets: [],
      }, { status: 500 });
    }
  } catch (error: any) {
    console.error('Error fetching datasets:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// Also support GET for nodes that are already configured
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  // Delegate to POST with empty body
  return POST(request, { params });
}
