import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/pipeline/nodes - Get all pipeline nodes for the organization
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ nodes: [], stacks: [] });
    }

    // Get layer filter from query params
    const { searchParams } = new URL(request.url);
    const layer = searchParams.get('layer');
    const status = searchParams.get('status');

    // Get all pipeline stacks for the organization
    const stacks = await prisma.pipelineStack.findMany({
      where: { organizationId: user.organizationId },
      include: {
        nodes: {
          where: {
            ...(layer && { layer: layer as any }),
            ...(status && { status: status as any }),
          },
          orderBy: { createdAt: 'desc' },
        },
      },
      orderBy: { updatedAt: 'desc' },
    });

    // Flatten nodes from all stacks for easier access
    const allNodes = stacks.flatMap(stack => 
      stack.nodes.map(node => ({
        ...node,
        stackId: stack.id,
        stackName: stack.name,
      }))
    );

    // Get counts by layer
    const layerCounts = {
      INGESTION: allNodes.filter(n => n.layer === 'INGESTION').length,
      TRANSFORMATION: allNodes.filter(n => n.layer === 'TRANSFORMATION').length,
      WAREHOUSE: allNodes.filter(n => n.layer === 'WAREHOUSE').length,
      REPORTING: allNodes.filter(n => n.layer === 'REPORTING').length,
    };

    // Get counts by status
    const statusCounts = {
      CONNECTED: allNodes.filter(n => n.status === 'CONNECTED').length,
      HEALTHY: allNodes.filter(n => n.status === 'HEALTHY').length,
      WARNING: allNodes.filter(n => n.status === 'WARNING').length,
      ERROR: allNodes.filter(n => n.status === 'ERROR').length,
      PENDING: allNodes.filter(n => n.status === 'PENDING').length,
    };

    return NextResponse.json({
      nodes: allNodes,
      stacks: stacks.map(s => ({
        id: s.id,
        name: s.name,
        status: s.status,
        nodeCount: s.nodes.length,
        lastScanAt: s.lastScanAt,
      })),
      counts: {
        total: allNodes.length,
        byLayer: layerCounts,
        byStatus: statusCounts,
      },
    });
  } catch (error: any) {
    console.error('Error fetching pipeline nodes:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
