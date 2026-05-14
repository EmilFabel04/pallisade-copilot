import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
import { resolveWarehouseCredentials, resolveOrganizationId } from './_shared';

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

      const organizationId = await resolveOrganizationId(session.user.email!);

      const res = await scannerClient.fetch(session, '/api/v1/discovery/direct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, tableFqn, credentials, stackId, organizationId }),
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

