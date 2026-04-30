import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';

// POST /api/nodes/sla/discover-bulk — Bulk SLA discovery for multiple nodes
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { nodeIds, stackId, nodes } = body;

    // New direct path: caller sends node metadata with platform + FQN
    if (nodes && Array.isArray(nodes) && nodes.length > 0 && stackId) {
      if (nodes.length > 50) {
        return NextResponse.json({ error: 'Max 50 nodes per request' }, { status: 400 });
      }

      // Group by platform so we resolve credentials once per platform
      const byPlatform: Record<string, string[]> = {};
      for (const n of nodes) {
        if (n.platform && n.tableFqn) {
          const p = n.platform.toLowerCase();
          if (!byPlatform[p]) byPlatform[p] = [];
          byPlatform[p].push(n.tableFqn);
        }
      }

      // Resolve credentials and call direct-bulk for each platform.
      // Look up the caller's organizationId so FastAPI can attach
      // clarifications to the right scope.
      const userRow = await prisma.user.findUnique({
        where: { email: session.user.email! },
        select: { organizationId: true },
      });
      const organizationId = userRow?.organizationId ?? undefined;

      const allResults: any[] = [];
      for (const [platform, tableFqns] of Object.entries(byPlatform)) {
        const credentials = await resolveWarehouseCredentials(session.user.email!, stackId, platform);
        if (!credentials) {
          allResults.push(
            ...tableFqns.map((fqn) => ({
              node_fqn: fqn,
              unsupported: true,
              skipped_reason: `No ${platform} credentials found for this pipeline`,
            }))
          );
          continue;
        }

        const res = await scannerClient.fetch(session, '/api/v1/discovery/direct-bulk', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ platform, tableFqns, credentials, stackId, organizationId }),
          signal: AbortSignal.timeout(300000),
        });

        if (res.ok) {
          const data = await res.json();
          allResults.push(...(data.results || []));
        } else {
          allResults.push(
            ...tableFqns.map((fqn) => ({
              node_fqn: fqn,
              unsupported: true,
              skipped_reason: 'Discovery request failed',
            }))
          );
        }
      }

      return NextResponse.json({ results: allResults });
    }

    // Legacy path: graph-based discovery
    if (!nodeIds || !Array.isArray(nodeIds) || nodeIds.length === 0) {
      return NextResponse.json({ error: 'nodeIds or nodes required' }, { status: 400 });
    }

    if (nodeIds.length > 50) {
      return NextResponse.json({ error: 'Max 50 nodes per request' }, { status: 400 });
    }

    const res = await scannerClient.fetch(session, '/api/v1/discovery/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodeIds, stackId }),
      signal: AbortSignal.timeout(300000),
    });

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }

    const errorData = await res.json().catch(() => ({}));
    return NextResponse.json(
      { error: errorData.detail || 'Bulk discovery failed' },
      { status: res.status || 500 }
    );
  } catch (error: any) {
    if (error?.name === 'TimeoutError') {
      return NextResponse.json({ error: 'Scanner timeout' }, { status: 504 });
    }
    console.error('[Discovery] Bulk error:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}

/**
 * Resolve warehouse credentials from the Integration table.
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

  const pipelineNode = await prisma.pipelineNode.findFirst({
    where: {
      stackId,
      toolType: platform.toLowerCase(),
      stack: { organizationId: user.organizationId },
    },
    include: { integration: true },
  });

  if (!pipelineNode) return null;

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
