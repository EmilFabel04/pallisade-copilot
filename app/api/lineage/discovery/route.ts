import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

interface DiscoveryResultPayload {
  nodeFqn: string;
  warehouseAncestorFqn?: string | null;
  freshness?: Record<string, any> | null;
  volume?: Record<string, any> | null;
  quality?: Record<string, any> | null;
  schema?: Record<string, any> | null;
  unsupported?: boolean;
  skippedReason?: string | null;
}

// POST /api/lineage/discovery — Persist discovery results from a lineage scan
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const { results } = body as { results: DiscoveryResultPayload[] };

    if (!results || results.length === 0) {
      return NextResponse.json({ persisted: 0 });
    }

    let persisted = 0;

    for (const result of results) {
      if (result.unsupported || result.skippedReason) continue;

      const hasConfig = result.freshness || result.volume || result.quality || result.schema;
      if (!hasConfig) continue;

      const shortName = result.nodeFqn.split('.').pop() || result.nodeFqn;
      const profileName = `Discovered SLA — ${shortName}`;

      const profile = await prisma.policyProfile.upsert({
        where: {
          organizationId_name: { organizationId, name: profileName },
        },
        create: {
          organizationId,
          name: profileName,
          description: `Auto-discovered from warehouse history for ${result.nodeFqn}`,
          isBuiltIn: true,
          freshnessConfig: result.freshness || undefined,
          volumeConfig: result.volume || undefined,
          qualityConfig: result.quality || undefined,
          schemaConfig: result.schema || undefined,
        },
        update: {
          freshnessConfig: result.freshness || undefined,
          volumeConfig: result.volume || undefined,
          qualityConfig: result.quality || undefined,
          schemaConfig: result.schema || undefined,
          updatedAt: new Date(),
        },
      });

      await prisma.policyAssignment.upsert({
        where: {
          organizationId_assignmentType_nodeFqn: {
            organizationId,
            assignmentType: 'auto_discovered',
            nodeFqn: result.nodeFqn,
          },
        },
        create: {
          organizationId,
          profileId: profile.id,
          assignmentType: 'auto_discovered',
          nodeFqn: result.nodeFqn,
        },
        update: {
          profileId: profile.id,
        },
      });

      persisted++;
    }

    return NextResponse.json({ persisted });
  } catch (error: any) {
    console.error('[Discovery] Error persisting results:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}
