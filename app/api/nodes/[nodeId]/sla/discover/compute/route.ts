import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
import { resolveOrganizationId, resolveWarehouseCredentials } from '../_shared';

// POST /api/nodes/[nodeId]/sla/discover/compute — Phase 2 of two-phase discovery
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
    const plan = body.plan ?? null;
    const answers = body.answers ?? {};

    if (!platform || !tableFqn || !stackId || !plan) {
      return NextResponse.json(
        { error: 'platform, tableFqn, stackId, and plan are required' },
        { status: 400 }
      );
    }

    if (plan?.table_fqn !== tableFqn) {
      return NextResponse.json(
        { error: 'plan.table_fqn does not match tableFqn' },
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

    const res = await scannerClient.fetch(session, '/api/v1/discovery/compute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform,
        tableFqn,
        credentials,
        plan,
        answers,
        stackId,
        organizationId,
      }),
      signal: AbortSignal.timeout(120000), // compute is slower, give it 2 minutes
    });

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json({ status: 'ok', result: data });
    }

    const errorData = await res.json().catch(() => ({}));
    return NextResponse.json(
      { error: errorData.detail || 'Compute failed' },
      { status: res.status || 500 }
    );
  } catch (e: any) {
    console.error('[Discovery Compute] Unhandled error:', e);
    return NextResponse.json(
      { error: e?.message || 'Internal error' },
      { status: 500 }
    );
  }
}
