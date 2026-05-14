import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
import {
  resolveOrganizationId,
  resolveWarehouseCredentials,
} from '@/app/api/nodes/[nodeId]/sla/discover/_shared';

// POST /api/nodes/sla/discover-bulk/analyze — Phase 1 bulk
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json().catch(() => ({}));
    const stackId: string | null = body.stackId ?? null;
    const nodes: Array<{ platform?: string; tableFqn?: string }> = body.nodes ?? [];

    if (!stackId || !Array.isArray(nodes) || nodes.length === 0) {
      return NextResponse.json(
        { error: 'stackId and nodes are required' },
        { status: 400 }
      );
    }
    if (nodes.length > 50) {
      return NextResponse.json({ error: 'Max 50 nodes per request' }, { status: 400 });
    }

    // Group by platform — resolve credentials once per platform.
    const byPlatform: Record<string, string[]> = {};
    for (const n of nodes) {
      if (n.platform && n.tableFqn) {
        const p = n.platform.toLowerCase();
        (byPlatform[p] ||= []).push(n.tableFqn);
      }
    }

    const organizationId = await resolveOrganizationId(session.user.email);
    const allResults: any[] = [];

    for (const [platform, tableFqns] of Object.entries(byPlatform)) {
      const credentials = await resolveWarehouseCredentials(
        session.user.email,
        stackId,
        platform
      );
      if (!credentials) {
        allResults.push(
          ...tableFqns.map((fqn) => ({
            table_fqn: fqn,
            status: 'ready',
            clarification_ids: [],
            plan: {
              table_fqn: fqn,
              warehouse_ancestor_fqn: null,
              volume_timestamp_pick: null,
              volume_timestamp_candidates: [],
              schema_snapshot: { columns: [] },
              row_count: null,
              unsupported: true,
              skipped_reason: `No ${platform} credentials found for this pipeline`,
            },
          }))
        );
        continue;
      }

      const res = await scannerClient.fetch(session, '/api/v1/discovery/analyze-bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, tableFqns, credentials, stackId, organizationId }),
        signal: AbortSignal.timeout(120000),
      });

      if (res.ok) {
        const data = await res.json();
        allResults.push(...(data.results ?? []));
      } else {
        allResults.push(
          ...tableFqns.map((fqn) => ({
            table_fqn: fqn,
            status: 'ready',
            clarification_ids: [],
            plan: {
              table_fqn: fqn,
              warehouse_ancestor_fqn: null,
              volume_timestamp_pick: null,
              volume_timestamp_candidates: [],
              schema_snapshot: { columns: [] },
              row_count: null,
              unsupported: true,
              skipped_reason: 'Analyze-bulk request failed',
            },
          }))
        );
      }
    }

    return NextResponse.json({ results: allResults });
  } catch (e: any) {
    console.error('[Discovery AnalyzeBulk] Unhandled error:', e);
    return NextResponse.json(
      { error: e?.message || 'Internal error' },
      { status: 500 }
    );
  }
}
