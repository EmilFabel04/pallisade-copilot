import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

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

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { nodeId } = await params;

    // Look up the lineage node
    const node = await prisma.lineageNode.findFirst({
      where: { id: nodeId, organizationId },
      include: { integration: true },
    });

    if (!node) {
      return NextResponse.json({ error: 'Node not found' }, { status: 404 });
    }

    // Check if node already has a user-defined profile
    const existingAssignment = await prisma.policyAssignment.findFirst({
      where: {
        organizationId,
        nodeFqn: node.name,
        assignmentType: { in: ['direct', 'imported_dbt'] },
      },
    });

    if (existingAssignment) {
      return NextResponse.json({ reason: 'user_defined' }, { status: 422 });
    }

    // Proxy to FastAPI scanner for discovery computation
    const scannerUrl = process.env.SCANNER_API_URL || 'http://localhost:8000';
    try {
      const res = await fetch(`${scannerUrl}/api/v1/discovery/node`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodeFqn: node.name,
          nodeId: node.id,
          platform: node.platform,
          database: node.database,
          schema: node.schema,
          tableName: node.tableName,
          integrationId: node.integrationId,
        }),
        signal: AbortSignal.timeout(30000),
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json({ status: 'ok', result: data });
      }

      const errorData = await res.json().catch(() => ({}));
      if (errorData.reason === 'no_warehouse_ancestor') {
        return NextResponse.json({ reason: 'no_warehouse_ancestor' }, { status: 422 });
      }

      return NextResponse.json({ error: 'Discovery failed' }, { status: 500 });
    } catch {
      return NextResponse.json({ error: 'Scanner unavailable' }, { status: 503 });
    }
  } catch (error: any) {
    console.error('[Discovery] On-demand error:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}
