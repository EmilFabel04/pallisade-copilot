import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// GET /api/lineage/upstream?fqn=db.schema.table&limit=20
// Walks upstream edges from the node matching `fqn` and returns all upstream nodes.
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { searchParams } = new URL(request.url);
    const fqn = searchParams.get('fqn') || '';
    const limit = Math.min(parseInt(searchParams.get('limit') || '20'), 50);

    if (!fqn.trim()) {
      return NextResponse.json({ nodes: [] });
    }

    // Find the anchor node
    const anchor = await prisma.lineageNode.findFirst({
      where: { organizationId, name: fqn },
      select: { id: true, name: true, tableName: true },
    });

    if (!anchor) {
      return NextResponse.json({ nodes: [] });
    }

    // Node types that are tools/connectors, not physical data assets
    const TOOL_NODE_TYPES = new Set(['connector', 'dag', 'task', 'flow', 'pipeline', 'workflow', 'tool', 'service', 'job']);

    // BFS upstream: follow edges where targetId = current node → sourceId is upstream
    const visited = new Set<string>();
    const queue = [anchor.id];
    const upstreamNodes: Array<{ id: string; name: string; fqn: string; nodeType: string | null; platform: string | null }> = [];

    while (queue.length > 0 && upstreamNodes.length < limit) {
      const currentId = queue.shift()!;
      if (visited.has(currentId)) continue;
      visited.add(currentId);

      const edges = await prisma.lineageEdge.findMany({
        where: { organizationId, targetId: currentId },
        select: {
          source: {
            select: { id: true, name: true, tableName: true, nodeType: true, platform: true },
          },
        },
      });

      for (const edge of edges) {
        if (!visited.has(edge.source.id) && upstreamNodes.length < limit) {
          // Skip tool/connector nodes (Fivetran connector, Airflow DAGs, etc.)
          const nt = (edge.source.nodeType || '').toLowerCase();
          if (!nt || TOOL_NODE_TYPES.has(nt)) continue;

          upstreamNodes.push({
            id: edge.source.id,
            name: edge.source.tableName || edge.source.name,
            fqn: edge.source.name,
            nodeType: edge.source.nodeType,
            platform: edge.source.platform,
          });
          queue.push(edge.source.id);
        }
      }
    }

    return NextResponse.json({ nodes: upstreamNodes });
  } catch (error: any) {
    console.error('[Lineage Upstream] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
