import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_URL = process.env.SCANNER_URL || 'http://localhost:8000';

// GET /api/schedule/plans/families - List monitor families with eligibility
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const stackId = request.nextUrl.searchParams.get('stackId') || '';
    const scopeType = request.nextUrl.searchParams.get('scopeType') || 'pipeline';
    const anchorNodeId = request.nextUrl.searchParams.get('anchorNodeId') || '';
    const nodeIds = request.nextUrl.searchParams.get('nodeIds') || '';

    const params = new URLSearchParams();
    if (stackId) params.set('stack_id', stackId);
    params.set('scope_type', scopeType);
    if (anchorNodeId) params.set('anchor_node_id', anchorNodeId);
    if (nodeIds) params.set('node_ids', nodeIds);
    const qs = params.toString() ? `?${params.toString()}` : '';

    const res = await fetch(
      `${SCANNER_URL}/api/v1/monitors/plans/families${qs}`,
      {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      },
    );

    if (!res.ok) {
      const err = await res.text();
      console.error('[Plans] Families error from FastAPI:', err);
      return NextResponse.json(
        { error: `Families fetch failed: ${res.status}` },
        { status: res.status },
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error('[Plans] Families error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
