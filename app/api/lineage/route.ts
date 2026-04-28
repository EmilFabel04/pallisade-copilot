import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// GET /api/lineage - Get lineage graph for the organization
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Get query params for filtering
    const searchParams = request.nextUrl.searchParams;
    const nodeType = searchParams.get('nodeType');
    const searchQuery = searchParams.get('search');
    const integrationId = searchParams.get('integrationId');

    // Build where clause for nodes
    const nodeWhere: any = { organizationId };
    if (nodeType && nodeType !== 'all') {
      nodeWhere.nodeType = nodeType;
    }
    if (integrationId) {
      nodeWhere.integrationId = integrationId;
    }
    if (searchQuery) {
      nodeWhere.OR = [
        { name: { contains: searchQuery, mode: 'insensitive' } },
        { tableName: { contains: searchQuery, mode: 'insensitive' } },
        { description: { contains: searchQuery, mode: 'insensitive' } },
      ];
    }

    // Get all lineage nodes
    const nodes = await prisma.lineageNode.findMany({
      where: nodeWhere,
      include: {
        integration: {
          select: {
            id: true,
            name: true,
            type: true,
          },
        },
      },
      orderBy: { name: 'asc' },
    });

    // Get all lineage edges
    const edges = await prisma.lineageEdge.findMany({
      where: { organizationId },
      select: {
        id: true,
        sourceId: true,
        targetId: true,
        edgeType: true,
        columns: true,
        transformation: true,
      },
    });

    // Calculate stats
    const nodeIds = new Set(nodes.map(n => n.id));
    const rootNodes = nodes.filter(n => 
      !edges.some(e => e.targetId === n.id && nodeIds.has(e.sourceId))
    );
    const leafNodes = nodes.filter(n => 
      !edges.some(e => e.sourceId === n.id && nodeIds.has(e.targetId))
    );

    // Get latest snapshot info
    const latestSnapshot = await prisma.lineageSnapshot.findFirst({
      where: { organizationId },
      orderBy: { createdAt: 'desc' },
      select: {
        id: true,
        source: true,
        dialect: true,
        nodeCount: true,
        edgeCount: true,
        status: true,
        createdAt: true,
      },
    });

    return NextResponse.json({
      nodes: nodes.map(n => ({
        id: n.id,
        name: n.name,
        database: n.database,
        schema: n.schema,
        tableName: n.tableName,
        nodeType: n.nodeType,
        description: n.description,
        owner: n.owner,
        tags: n.tags,
        criticality: n.criticality,
        businessDomain: n.businessDomain,
        rowCount: n.rowCount,
        lastUpdated: n.lastUpdated,
        upstreamCount: n.upstreamCount,
        downstreamCount: n.downstreamCount,
        integration: n.integration,
      })),
      edges: edges.map(e => ({
        id: e.id,
        source: e.sourceId,
        target: e.targetId,
        edgeType: e.edgeType,
        columns: e.columns,
        transformation: e.transformation,
      })),
      stats: {
        totalNodes: nodes.length,
        totalEdges: edges.length,
        rootNodes: rootNodes.length,
        leafNodes: leafNodes.length,
        byType: nodes.reduce((acc, n) => {
          acc[n.nodeType] = (acc[n.nodeType] || 0) + 1;
          return acc;
        }, {} as Record<string, number>),
      },
      snapshot: latestSnapshot,
    });
  } catch (error) {
    console.error('Error fetching lineage:', error);
    return NextResponse.json(
      { error: 'Failed to fetch lineage' },
      { status: 500 }
    );
  }
}

// POST /api/lineage — DEPRECATED.
// This endpoint pre-dated per-pipeline isolation and wrote lineage rows scoped
// only to the org (no pipelineStackId). It is no longer reachable from the UI;
// extraction now goes through POST /api/pipeline/[stackId]/lineage. With the
// per-stack migration, every lineage write requires a stackId, which this
// endpoint does not accept.
export async function POST() {
  return NextResponse.json(
    {
      error: 'deprecated',
      message: 'Use POST /api/pipeline/[stackId]/lineage to extract lineage for a specific pipeline.',
    },
    { status: 410 },
  );
}
