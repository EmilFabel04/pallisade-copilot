import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';

// POST /api/nodes/[nodeId]/sla/discover — On-demand SLA discovery for a single node
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ nodeId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { nodeId } = await params;

    let stackId: string | null = null;
    let platform: string | null = null;
    let tableFqn: string | null = null;
    try {
      const body = await request.json();
      stackId = body.stackId || null;
      platform = body.platform || null;
      tableFqn = body.tableFqn || null;
    } catch {
      stackId = new URL(request.url).searchParams.get('stackId');
    }

    // If platform + tableFqn provided, use the direct endpoint (no lineage graph needed)
    if (platform && tableFqn && stackId) {
      const credentials = await resolveWarehouseCredentials(session.user.email!, stackId, platform);
      if (!credentials) {
        return NextResponse.json(
          { error: `No ${platform} warehouse credentials found for this pipeline` },
          { status: 422 }
        );
      }

      const res = await scannerClient.fetch(session, '/api/v1/discovery/direct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, tableFqn, credentials }),
        signal: AbortSignal.timeout(60000),
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json({ status: 'ok', result: data });
      }

      const errorData = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Discovery failed' },
        { status: res.status || 500 }
      );
    }

    // Fallback: use the graph-based endpoint (requires lineage to be populated)
    const qs = stackId ? `?stack_id=${encodeURIComponent(stackId)}` : '';
    const res = await scannerClient.fetch(session, `/api/v1/discovery/node${qs}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodeId }),
      signal: AbortSignal.timeout(60000),
    });

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json({ status: 'ok', result: data });
    }

    const errorData = await res.json().catch(() => ({}));

    if (res.status === 404) {
      return NextResponse.json(
        { error: errorData.detail || 'Node not found in lineage graph' },
        { status: 404 }
      );
    }

    if (res.status === 422) {
      const reason = errorData.detail?.reason || 'unsupported';
      return NextResponse.json({ reason }, { status: 422 });
    }

    return NextResponse.json(
      { error: errorData.detail || 'Discovery failed' },
      { status: res.status || 500 }
    );
  } catch (error: any) {
    if (error?.name === 'TimeoutError') {
      return NextResponse.json({ error: 'Scanner timeout' }, { status: 504 });
    }
    console.error('[Discovery] On-demand error:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}

/**
 * Resolve warehouse credentials from the Integration table.
 * Finds the PipelineNode for the given stack + platform (e.g. "bigquery"),
 * then decrypts credentials from its linked Integration.
 */
async function resolveWarehouseCredentials(
  userEmail: string,
  stackId: string,
  platform: string
): Promise<Record<string, any> | null> {
  const user = await prisma.user.findUnique({
    where: { email: userEmail },
    select: { organizationId: true },
  });
  if (!user?.organizationId) return null;

  // Find the warehouse PipelineNode matching this platform
  const pipelineNode = await prisma.pipelineNode.findFirst({
    where: {
      stackId,
      toolType: platform.toLowerCase(),
      stack: { organizationId: user.organizationId },
    },
    include: { integration: true },
  });

  if (!pipelineNode) return null;

  // Resolve credentials — prefer Integration, fall back to PipelineNode.config
  if ((pipelineNode as any).integrationId && (pipelineNode as any).integration?.credentials) {
    try {
      const intCreds = (pipelineNode as any).integration.credentials as any;
      if (intCreds.encrypted) {
        return JSON.parse(decrypt(intCreds.encrypted));
      }
      return intCreds;
    } catch (e) {
      console.error('[Discovery] Integration credentials parsing failed:', e);
    }
  }

  if (pipelineNode.config) {
    try {
      const configJson = pipelineNode.config as { encrypted?: string; _cached?: any; [key: string]: any };
      if (configJson.encrypted) {
        return JSON.parse(decrypt(configJson.encrypted));
      }
      const { _cached, ...creds } = configJson;
      return creds;
    } catch (e) {
      console.error('[Discovery] Config credentials parsing failed:', e);
    }
  }

  return null;
}
