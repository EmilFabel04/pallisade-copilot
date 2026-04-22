import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';
import { extractLineageForStack } from './extract-lineage';

// POST /api/pipeline/[stackId]/lineage - Extract lineage from warehouse nodes
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
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
    const { stackId } = await params;
    const body = await request.json().catch(() => ({}));
    return extractLineageForStack(stackId, organizationId, body, session);
  } catch (error) {
    console.error('[LINEAGE] Error extracting lineage:', error);
    return NextResponse.json({ error: 'Failed to extract lineage' }, { status: 500 });
  }
}

// GET /api/pipeline/[stackId]/lineage - Get stored lineage for this stack
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
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

    const { stackId } = await params;

    // Get the pipeline stack
    const stack = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
      include: {
        nodes: {
          select: {
            id: true,
            integrationId: true,
          },
        },
      },
    });

    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    // Get integration IDs from stack nodes
    const integrationIds = stack.nodes
      .map(n => n.integrationId)
      .filter((id): id is string => id !== null);

    // Get lineage nodes for these integrations
    const allNodes = await prisma.lineageNode.findMany({
      where: {
        organizationId,
        ...(integrationIds.length > 0
          ? { integrationId: { in: integrationIds } }
          : {}
        ),
      },
      orderBy: { name: 'asc' },
    });

    // Deduplicate nodes by name (keep first occurrence)
    const seenNames = new Set<string>();
    const nodes = allNodes.filter(n => {
      const normalizedName = n.name.toLowerCase();
      if (seenNames.has(normalizedName)) {
        return false;
      }
      seenNames.add(normalizedName);
      return true;
    });

    // Get edges between these nodes
    const nodeIds = nodes.map(n => n.id);
    const edges = await prisma.lineageEdge.findMany({
      where: {
        organizationId,
        sourceId: { in: nodeIds },
        targetId: { in: nodeIds },
      },
    });

    // Get latest snapshot
    const latestSnapshot = await prisma.lineageSnapshot.findFirst({
      where: {
        organizationId,
        ...(integrationIds.length > 0
          ? { integrationId: { in: integrationIds } }
          : {}
        ),
      },
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({
      nodes: nodes.map(n => ({
        id: n.id,
        name: n.name,
        database: n.database,
        schema: n.schema,
        tableName: n.tableName,
        nodeType: n.nodeType,
        platform: n.platform,
        description: n.description,
        criticality: n.criticality,
        rowCount: n.rowCount,
        upstreamCount: n.upstreamCount,
        downstreamCount: n.downstreamCount,
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
      },
      lastExtracted: latestSnapshot?.createdAt || null,
    });

  } catch (error) {
    console.error('[LINEAGE] Error fetching lineage:', error);
    return NextResponse.json(
      { error: 'Failed to fetch lineage' },
      { status: 500 }
    );
  }
}

// DELETE /api/pipeline/[stackId]/lineage - Clear lineage data
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
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

    // Delete all edges first (due to foreign key constraints)
    const deletedEdges = await prisma.lineageEdge.deleteMany({
      where: { organizationId },
    });

    // Then delete all nodes
    const deletedNodes = await prisma.lineageNode.deleteMany({
      where: { organizationId },
    });

    // Delete snapshots
    const deletedSnapshots = await prisma.lineageSnapshot.deleteMany({
      where: { organizationId },
    });

    // Clear in-memory engine graph and run registry so stale views aren't served
    try {
      const { stackId: delStackId } = await params;
      await scannerClient.fetch(session, `/api/v1/lineage/engine/clear-cache?stack_id=${delStackId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(5000),
      });
    } catch {
      console.warn('[LINEAGE] Failed to clear engine cache (non-fatal)');
    }

    console.log(`[LINEAGE] Cleared: ${deletedNodes.count} nodes, ${deletedEdges.count} edges, ${deletedSnapshots.count} snapshots`);

    return NextResponse.json({
      success: true,
      deleted: {
        nodes: deletedNodes.count,
        edges: deletedEdges.count,
        snapshots: deletedSnapshots.count,
      },
    });

  } catch (error) {
    console.error('[LINEAGE] Error clearing lineage:', error);
    return NextResponse.json(
      { error: 'Failed to clear lineage' },
      { status: 500 }
    );
  }
}
