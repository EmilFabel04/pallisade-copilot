import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
import { findPriorAnswers, resolveOrganizationId, resolveWarehouseCredentials } from '../_shared';

// POST /api/nodes/[nodeId]/sla/discover/analyze — Phase 1 of two-phase discovery
export async function POST(
  request: NextRequest,
  { params: _params }: { params: Promise<{ nodeId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json().catch(() => ({}));
    const stackId: string | null = body.stackId ?? null;
    const platform: string | null = body.platform ?? null;
    const tableFqn: string | null = body.tableFqn ?? null;

    if (!platform || !tableFqn || !stackId) {
      return NextResponse.json(
        { error: 'platform, tableFqn, and stackId are required' },
        { status: 400 }
      );
    }

    const credentials = await resolveWarehouseCredentials(
      session.user.email,
      stackId,
      platform
    );
    if (!credentials) {
      return NextResponse.json(
        { error: `No ${platform} warehouse credentials found for this pipeline` },
        { status: 422 }
      );
    }

    const organizationId = await resolveOrganizationId(session.user.email);
    const priorAnswers = await findPriorAnswers(stackId, tableFqn);

    const res = await scannerClient.fetch(session, '/api/v1/discovery/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform,
        tableFqn,
        credentials,
        stackId,
        organizationId,
        priorAnswers,
      }),
      signal: AbortSignal.timeout(60000),
    });

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json({ status: 'ok', result: data });
    }

    const errorData = await res.json().catch(() => ({}));
    return NextResponse.json(
      { error: errorData.detail || 'Analyze failed' },
      { status: res.status || 500 }
    );
  } catch (e: any) {
    console.error('[Discovery Analyze] Unhandled error:', e);
    return NextResponse.json(
      { error: e?.message || 'Internal error' },
      { status: 500 }
    );
  }
}
