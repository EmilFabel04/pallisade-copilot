import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

/**
 * GET /api/pipeline/[stackId]/lineage/engine
 *
 * Proxies to the FastAPI engine endpoints:
 *   ?action=stats        → /api/v1/lineage/engine/stats
 *   ?action=upstream&id= → /api/v1/lineage/engine/upstream/{id}
 *   ?action=downstream&id= → /api/v1/lineage/engine/downstream/{id}
 *   ?action=explain-edge&id= → /api/v1/lineage/engine/explain-edge/{id}
 *   ?action=blast-radius&id= → /api/v1/lineage/engine/blast-radius/{id}
 *   ?action=control-plane&id= → /api/v1/lineage/engine/control-plane/{id} (optional id for specific DAG)
 *   ?action=cross-links&id= → /api/v1/lineage/engine/cross-links/{id}
 *   ?action=run-history&id= → /api/v1/lineage/engine/run-history/{id}
 *
 * Passes through filter params: level, system, domain, kind, min_confidence, depth, plane
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;
    const { searchParams } = new URL(request.url);
    const action = searchParams.get('action') || 'stats';
    const assetId = searchParams.get('id') || '';

    // Build query params to forward
    const forwardParams = new URLSearchParams();
    for (const key of ['level', 'system', 'domain', 'kind', 'min_confidence', 'depth', 'fmt', 'plane']) {
      const val = searchParams.get(key);
      if (val) forwardParams.set(key, val);
    }
    const qs = forwardParams.toString() ? `?${forwardParams.toString()}` : '';

    let endpoint: string;
    switch (action) {
      case 'stats':
        endpoint = `/api/v1/lineage/engine/stats${qs}`;
        break;
      case 'upstream':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/upstream/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'downstream':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/downstream/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'blast-radius':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/blast-radius/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'explain-edge':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/explain-edge/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'export':
        endpoint = `/api/v1/lineage/engine/export${qs}`;
        break;
      case 'control-plane':
        endpoint = assetId
          ? `/api/v1/lineage/engine/control-plane/${encodeURIComponent(assetId)}${qs}`
          : `/api/v1/lineage/engine/control-plane${qs}`;
        break;
      case 'cross-links':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/cross-links/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'run-history':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/run-history/${encodeURIComponent(assetId)}${qs}`;
        break;
      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }

    const res = await fetch(`${SCANNER_API_URL}${endpoint}`, {
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(30000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[ENGINE PROXY] Error:', error);
    return NextResponse.json(
      { error: 'Failed to proxy to engine API' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/pipeline/[stackId]/lineage/engine
 *
 * Proxies to /api/v1/lineage/engine/build
 * Body: { config: { adapters: [...], resolver: {...}, ... } }
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();

    const res = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[ENGINE PROXY] Build error:', error);
    return NextResponse.json(
      { error: 'Failed to build engine graph' },
      { status: 500 }
    );
  }
}
