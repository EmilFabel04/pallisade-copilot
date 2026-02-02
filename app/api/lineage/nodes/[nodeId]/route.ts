import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/lineage/nodes/[nodeId] - Get specific node with upstream/downstream
export async function GET(
  request: NextRequest,
  { params }: { params: { nodeId: string } }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { nodeId } = params;
    const searchParams = request.nextUrl.searchParams;
    const depth = parseInt(searchParams.get('depth') || '2', 10);

    // Get the node
    const node = await prisma.lineageNode.findFirst({
      where: {
        id: nodeId,
        organizationId,
      },
      include: {
        integration: {
          select: {
            id: true,
            name: true,
            type: true,
          },
        },
      },
    });

    if (!node) {
      return NextResponse.json({ error: 'Node not found' }, { status: 404 });
    }

    // Get all edges for traversal
    const allEdges = await prisma.lineageEdge.findMany({
      where: { organizationId },
      select: {
        sourceId: true,
        targetId: true,
        edgeType: true,
        columns: true,
      },
    });

    // Get upstream nodes (nodes that this node depends on)
    const upstreamIds = new Set<string>();
    const upstreamEdges: typeof allEdges = [];
    
    function getUpstream(id: string, currentDepth: number) {
      if (currentDepth > depth) return;
      
      const edges = allEdges.filter(e => e.targetId === id);
      for (const edge of edges) {
        if (!upstreamIds.has(edge.sourceId)) {
          upstreamIds.add(edge.sourceId);
          upstreamEdges.push(edge);
          getUpstream(edge.sourceId, currentDepth + 1);
        }
      }
    }
    getUpstream(nodeId, 1);

    // Get downstream nodes (nodes that depend on this node)
    const downstreamIds = new Set<string>();
    const downstreamEdges: typeof allEdges = [];
    
    function getDownstream(id: string, currentDepth: number) {
      if (currentDepth > depth) return;
      
      const edges = allEdges.filter(e => e.sourceId === id);
      for (const edge of edges) {
        if (!downstreamIds.has(edge.targetId)) {
          downstreamIds.add(edge.targetId);
          downstreamEdges.push(edge);
          getDownstream(edge.targetId, currentDepth + 1);
        }
      }
    }
    getDownstream(nodeId, 1);

    // Fetch the actual node data
    const upstreamNodes = await prisma.lineageNode.findMany({
      where: {
        id: { in: Array.from(upstreamIds) },
        organizationId,
      },
      include: {
        integration: {
          select: {
            id: true,
            name: true,
            type: true,
          },
        },
      },
    });

    const downstreamNodes = await prisma.lineageNode.findMany({
      where: {
        id: { in: Array.from(downstreamIds) },
        organizationId,
      },
      include: {
        integration: {
          select: {
            id: true,
            name: true,
            type: true,
          },
        },
      },
    });

    return NextResponse.json({
      node: {
        id: node.id,
        name: node.name,
        database: node.database,
        schema: node.schema,
        tableName: node.tableName,
        nodeType: node.nodeType,
        description: node.description,
        owner: node.owner,
        tags: node.tags,
        criticality: node.criticality,
        businessDomain: node.businessDomain,
        rowCount: node.rowCount,
        lastUpdated: node.lastUpdated,
        upstreamCount: node.upstreamCount,
        downstreamCount: node.downstreamCount,
        integration: node.integration,
      },
      upstream: {
        nodes: upstreamNodes.map(n => ({
          id: n.id,
          name: n.name,
          nodeType: n.nodeType,
          criticality: n.criticality,
          integration: n.integration,
        })),
        edges: upstreamEdges,
      },
      downstream: {
        nodes: downstreamNodes.map(n => ({
          id: n.id,
          name: n.name,
          nodeType: n.nodeType,
          criticality: n.criticality,
          integration: n.integration,
        })),
        edges: downstreamEdges,
      },
    });
  } catch (error) {
    console.error('Error fetching lineage node:', error);
    return NextResponse.json(
      { error: 'Failed to fetch lineage node' },
      { status: 500 }
    );
  }
}
