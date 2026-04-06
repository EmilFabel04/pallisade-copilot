import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

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

    // Read optional stackId from request body or query params
    let stackId: string | null = null;
    try {
      const body = await request.json();
      stackId = body.stackId || null;
    } catch {
      // No body — check query params
      stackId = new URL(request.url).searchParams.get('stackId');
    }

    // Proxy to FastAPI scanner discovery endpoint
    const qs = stackId ? `?stack_id=${encodeURIComponent(stackId)}` : '';
    const res = await fetch(`${SCANNER_API_URL}/api/v1/discovery/node${qs}`, {
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
