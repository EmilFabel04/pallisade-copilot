import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
import {
  resolveOrganizationId,
  resolveWarehouseCredentials,
} from '@/app/api/nodes/[nodeId]/sla/discover/_shared';

// POST /api/nodes/sla/discover-bulk/compute — Phase 2 bulk
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json().catch(() => ({}));
    const stackId: string | null = body.stackId ?? null;
    const items: Array<{
      platform?: string;
      tableFqn?: string;
      plan?: any;
      answers?: Record<string, any>;
    }> = body.items ?? [];

    if (!stackId || !Array.isArray(items) || items.length === 0) {
      return NextResponse.json(
        { error: 'stackId and items are required' },
        { status: 400 }
      );
    }
    if (items.length > 50) {
      return NextResponse.json({ error: 'Max 50 items per request' }, { status: 400 });
    }

    // Validate plan.table_fqn matches item.tableFqn for every item.
    for (const item of items) {
      if (!item.plan?.table_fqn || !item.tableFqn) {
        return NextResponse.json(
          { error: 'each item must include plan.table_fqn and tableFqn' },
          { status: 400 }
        );
      }
      if (item.plan.table_fqn !== item.tableFqn) {
        return NextResponse.json(
          { error: `plan.table_fqn does not match tableFqn for ${item.tableFqn}` },
          { status: 400 }
        );
      }
    }

    // Group by platform — same as analyze-bulk.
    const byPlatform: Record<string, typeof items> = {};
    for (const item of items) {
      const p = (item.platform ?? '').toLowerCase();
      if (!p) continue;
      (byPlatform[p] ||= []).push(item);
    }

    const organizationId = await resolveOrganizationId(session.user.email);
    const allResults: any[] = [];

    for (const [platform, group] of Object.entries(byPlatform)) {
      const credentials = await resolveWarehouseCredentials(
        session.user.email,
        stackId,
        platform
      );
      if (!credentials) {
        allResults.push(
          ...group.map((item) => ({
            node_fqn: item.tableFqn,
            unsupported: true,
            skipped_reason: `No ${platform} credentials found for this pipeline`,
          }))
        );
        continue;
      }

      const scannerItems = group.map((item) => ({
        tableFqn: item.tableFqn,
        plan: item.plan,
        answers: item.answers ?? {},
      }));

      const res = await scannerClient.fetch(session, '/api/v1/discovery/compute-bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          credentials,
          items: scannerItems,
          stackId,
          organizationId,
        }),
        signal: AbortSignal.timeout(300000),
      });

      if (res.ok) {
        const data = await res.json();
        allResults.push(...(data.results ?? []));
      } else {
        allResults.push(
          ...group.map((item) => ({
            node_fqn: item.tableFqn,
            unsupported: true,
            skipped_reason: 'Compute-bulk request failed',
          }))
        );
      }
    }

    return NextResponse.json({ results: allResults });
  } catch (e: any) {
    console.error('[Discovery ComputeBulk] Unhandled error:', e);
    return NextResponse.json(
      { error: e?.message || 'Internal error' },
      { status: 500 }
    );
  }
}
