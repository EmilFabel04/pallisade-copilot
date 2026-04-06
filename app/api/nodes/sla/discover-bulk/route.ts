import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// POST /api/nodes/sla/discover-bulk — Bulk SLA discovery for multiple nodes
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { nodeIds, stackId } = body;

    if (!nodeIds || !Array.isArray(nodeIds) || nodeIds.length === 0) {
      return NextResponse.json({ error: 'nodeIds required' }, { status: 400 });
    }

    if (nodeIds.length > 50) {
      return NextResponse.json({ error: 'Max 50 nodes per request' }, { status: 400 });
    }

    const res = await fetch(`${SCANNER_API_URL}/api/v1/discovery/bulk`, {
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
