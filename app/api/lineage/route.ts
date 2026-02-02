import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/lineage - Get lineage graph for the organization
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
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

// POST /api/lineage - Build lineage from various sources
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const { source, integrationId, data } = body;

    // Validate source
    const validSources = ['dbt_manifest', 'query_history', 'openlineage', 'manual'];
    if (!validSources.includes(source)) {
      return NextResponse.json(
        { error: `Invalid source. Must be one of: ${validSources.join(', ')}` },
        { status: 400 }
      );
    }

    // Create a new snapshot to track this build
    const snapshot = await prisma.lineageSnapshot.create({
      data: {
        organizationId,
        integrationId,
        source,
        dialect: data?.dialect || 'unknown',
        status: 'building',
        nodeCount: 0,
        edgeCount: 0,
        rootCount: 0,
        leafCount: 0,
      },
    });

    // For now, return the snapshot ID and let the Python backend handle the actual processing
    // In a full implementation, this would call the Python lineage parser
    
    // If data is provided directly (e.g., from dbt manifest upload), process it
    if (source === 'dbt_manifest' && data?.manifest) {
      // Parse dbt manifest and create nodes/edges
      const manifest = data.manifest;
      const nodes: any[] = [];
      const edges: any[] = [];

      // Process models from manifest
      if (manifest.nodes) {
        for (const [key, node] of Object.entries(manifest.nodes as Record<string, any>)) {
          if (node.resource_type === 'model' || node.resource_type === 'source') {
            const fullName = `${node.database || 'default'}.${node.schema}.${node.name}`;
            
            nodes.push({
              name: fullName,
              database: node.database || 'default',
              schema: node.schema,
              tableName: node.name,
              nodeType: node.resource_type === 'source' ? 'source' : 'model',
              description: node.description || null,
              owner: node.meta?.owner || null,
              tags: node.tags || [],
              organizationId,
              integrationId,
            });

            // Add edges for dependencies
            if (node.depends_on?.nodes) {
              for (const dep of node.depends_on.nodes) {
                const depNode = manifest.nodes[dep] || manifest.sources?.[dep];
                if (depNode) {
                  const depFullName = `${depNode.database || 'default'}.${depNode.schema}.${depNode.name}`;
                  edges.push({
                    sourceName: depFullName,
                    targetName: fullName,
                  });
                }
              }
            }
          }
        }
      }

      // Process sources
      if (manifest.sources) {
        for (const [key, source] of Object.entries(manifest.sources as Record<string, any>)) {
          const fullName = `${source.database || 'default'}.${source.schema}.${source.name}`;
          
          if (!nodes.find(n => n.name === fullName)) {
            nodes.push({
              name: fullName,
              database: source.database || 'default',
              schema: source.schema,
              tableName: source.name,
              nodeType: 'source',
              description: source.description || null,
              tags: source.tags || [],
              organizationId,
              integrationId,
            });
          }
        }
      }

      // Upsert nodes
      let createdNodes = 0;
      let createdEdges = 0;

      for (const node of nodes) {
        await prisma.lineageNode.upsert({
          where: {
            organizationId_name: {
              organizationId,
              name: node.name,
            },
          },
          create: node,
          update: {
            database: node.database,
            schema: node.schema,
            tableName: node.tableName,
            nodeType: node.nodeType,
            description: node.description,
            owner: node.owner,
            tags: node.tags,
            integrationId: node.integrationId,
          },
        });
        createdNodes++;
      }

      // Create edges
      for (const edge of edges) {
        const sourceNode = await prisma.lineageNode.findFirst({
          where: { organizationId, name: edge.sourceName },
        });
        const targetNode = await prisma.lineageNode.findFirst({
          where: { organizationId, name: edge.targetName },
        });

        if (sourceNode && targetNode) {
          await prisma.lineageEdge.upsert({
            where: {
              sourceId_targetId: {
                sourceId: sourceNode.id,
                targetId: targetNode.id,
              },
            },
            create: {
              sourceId: sourceNode.id,
              targetId: targetNode.id,
              organizationId,
              edgeType: 'depends_on',
            },
            update: {},
          });
          createdEdges++;
        }
      }

      // Update node counts
      const allNodes = await prisma.lineageNode.findMany({
        where: { organizationId },
        select: { id: true },
      });
      const allEdges = await prisma.lineageEdge.findMany({
        where: { organizationId },
        select: { sourceId: true, targetId: true },
      });

      // Calculate upstream/downstream counts for each node
      for (const node of allNodes) {
        const upstreamCount = allEdges.filter(e => e.targetId === node.id).length;
        const downstreamCount = allEdges.filter(e => e.sourceId === node.id).length;
        
        await prisma.lineageNode.update({
          where: { id: node.id },
          data: { upstreamCount, downstreamCount },
        });
      }

      // Calculate root and leaf counts
      const nodeIds = new Set(allNodes.map(n => n.id));
      const rootCount = allNodes.filter(n => 
        !allEdges.some(e => e.targetId === n.id && nodeIds.has(e.sourceId))
      ).length;
      const leafCount = allNodes.filter(n => 
        !allEdges.some(e => e.sourceId === n.id && nodeIds.has(e.targetId))
      ).length;

      // Update snapshot
      await prisma.lineageSnapshot.update({
        where: { id: snapshot.id },
        data: {
          status: 'ready',
          nodeCount: allNodes.length,
          edgeCount: allEdges.length,
          rootCount,
          leafCount,
        },
      });

      return NextResponse.json({
        success: true,
        snapshotId: snapshot.id,
        stats: {
          nodesCreated: createdNodes,
          edgesCreated: createdEdges,
          totalNodes: allNodes.length,
          totalEdges: allEdges.length,
          rootCount,
          leafCount,
        },
      });
    }

    // For other sources, the Python backend would handle the processing
    return NextResponse.json({
      success: true,
      snapshotId: snapshot.id,
      message: `Lineage build initiated from ${source}. Processing in background.`,
    });
  } catch (error) {
    console.error('Error building lineage:', error);
    return NextResponse.json(
      { error: 'Failed to build lineage' },
      { status: 500 }
    );
  }
}
