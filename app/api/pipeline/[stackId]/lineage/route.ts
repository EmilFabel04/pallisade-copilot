import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// Helper to decrypt node config
function decryptNodeConfig(config: any): Record<string, any> | null {
  if (!config) return null;
  try {
    if (config.encrypted) {
      const decrypted = decrypt(config.encrypted);
      return JSON.parse(decrypted);
    }
    // Config is not encrypted (legacy data), return as-is
    return config as Record<string, any>;
  } catch (e) {
    console.error('[LINEAGE] Failed to decrypt config:', e);
    return null;
  }
}

// POST /api/pipeline/[stackId]/lineage - Extract lineage from warehouse nodes
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
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

    const { stackId } = await params;
    const body = await request.json().catch(() => ({}));
    const { nodeId, options = {} } = body;

    // Get the pipeline stack
    const stack = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
      include: {
        nodes: true,
      },
    });

    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    // Find extractable nodes (warehouse + transformation layers)
    // Valid statuses: CONNECTED (just connected) or HEALTHY (connected and healthy)
    const extractableNodes = stack.nodes.filter(
      (n) => (n.layer === 'WAREHOUSE' || n.layer === 'TRANSFORMATION')
          && (n.status === 'CONNECTED' || n.status === 'HEALTHY')
    );

    if (extractableNodes.length === 0) {
      return NextResponse.json({
        error: 'No connected warehouse or transformation nodes found'
      }, { status: 400 });
    }

    // If nodeId specified, only extract from that node
    const nodesToProcess = nodeId
      ? extractableNodes.filter(n => n.id === nodeId)
      : extractableNodes;

    if (nodesToProcess.length === 0) {
      return NextResponse.json({
        error: 'Specified node not found or not a connected extractable node'
      }, { status: 400 });
    }

    const results: any[] = [];
    let totalNodes = 0;
    let totalEdges = 0;

    for (const node of nodesToProcess) {
      try {
        console.log(`[LINEAGE] Extracting lineage from ${node.name} (${node.toolType})`);

        // Decrypt the config before sending to scanner
        const decryptedConfig = decryptNodeConfig(node.config);
        if (!decryptedConfig) {
          console.error(`[LINEAGE] Failed to decrypt config for ${node.name}`);
          results.push({
            nodeId: node.id,
            nodeName: node.name,
            success: false,
            error: 'Failed to decrypt node configuration',
          });
          continue;
        }

        // For TRANSFORMATION (dbt) nodes, attach GitHub config from any connected VERSION_CONTROL node
        const extractConfig = { ...decryptedConfig };
        if (node.layer === 'TRANSFORMATION') {
          const githubNode = stack.nodes.find(
            (n) => n.layer === 'VERSION_CONTROL' && n.toolType === 'github' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')
          );
          if (githubNode) {
            const ghConfig = decryptNodeConfig(githubNode.config);
            if (ghConfig?.access_token && ghConfig?.owner) {
              extractConfig.github = {
                repo: ghConfig.repo
                  ? `${ghConfig.owner}/${ghConfig.repo}`
                  : ghConfig.owner,
                token: ghConfig.access_token,
                branch: ghConfig.branch || 'main',
                dbt_root: ghConfig.dbt_root || '',
              };
              console.log(`[LINEAGE] Attached GitHub config from ${githubNode.name} for dbt schema enrichment`);
            }
          }
        }

        // Call scanner API to extract lineage
        const response = await fetch(`${SCANNER_API_URL}/api/v1/lineage/extract`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            integration_type: node.toolType.toUpperCase(),
            config: extractConfig,
            integration_id: node.integrationId || undefined,
            options: {
              region: options.region || 'auto',
              days_back: options.days_back || 30,
              enable_data_catalog: options.enable_data_catalog || false,
            },
          }),
          signal: AbortSignal.timeout(120000), // 2 minute timeout
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          console.error(`[LINEAGE] Scanner error for ${node.name}:`, errorData);
          results.push({
            nodeId: node.id,
            nodeName: node.name,
            success: false,
            error: errorData.error || 'Scanner request failed',
          });
          continue;
        }

        const lineageData = await response.json();
        
        if (!lineageData.success) {
          results.push({
            nodeId: node.id,
            nodeName: node.name,
            success: false,
            error: lineageData.errors?.join(', ') || 'Lineage extraction failed',
          });
          continue;
        }

        console.log(`[LINEAGE] Got ${lineageData.nodes?.length || 0} nodes, ${lineageData.edges?.length || 0} edges from ${node.name}`);

        // Store nodes in database
        const nodeMap = new Map<string, string>(); // fqn -> db id

        for (const lineageNode of lineageData.nodes || []) {
          const fqn = lineageNode.fqn || lineageNode.name;
          const parts = fqn.split('.');
          const tableName = parts[parts.length - 1];
          const schema = parts.length > 1 ? parts[parts.length - 2] : null;
          const database = parts.length > 2 ? parts[parts.length - 3] : null;

          try {
            const dbNode = await prisma.lineageNode.upsert({
              where: {
                organizationId_name: {
                  organizationId,
                  name: fqn,
                },
              },
              create: {
                name: fqn,
                database: database || lineageNode.database,
                schema: schema || lineageNode.schema,
                tableName: tableName,
                nodeType: lineageNode.node_type || 'table',
                description: lineageNode.description,
                criticality: lineageNode.criticality?.toUpperCase() || 'MEDIUM',
                rowCount: lineageNode.row_count,
                upstreamCount: lineageNode.upstream_count || 0,
                downstreamCount: lineageNode.downstream_count || 0,
                organizationId,
                integrationId: node.integrationId,
              },
              update: {
                nodeType: lineageNode.node_type || 'table',
                description: lineageNode.description,
                rowCount: lineageNode.row_count,
                upstreamCount: lineageNode.upstream_count || 0,
                downstreamCount: lineageNode.downstream_count || 0,
                integrationId: node.integrationId,
              },
            });
            
            nodeMap.set(lineageNode.id, dbNode.id);
          } catch (err) {
            console.error(`[LINEAGE] Failed to upsert node ${fqn}:`, err);
          }
        }

        // Store edges in database
        let edgesCreated = 0;
        for (const lineageEdge of lineageData.edges || []) {
          const sourceDbId = nodeMap.get(lineageEdge.source_id);
          const targetDbId = nodeMap.get(lineageEdge.target_id);

          if (sourceDbId && targetDbId) {
            try {
              await prisma.lineageEdge.upsert({
                where: {
                  sourceId_targetId: {
                    sourceId: sourceDbId,
                    targetId: targetDbId,
                  },
                },
                create: {
                  sourceId: sourceDbId,
                  targetId: targetDbId,
                  edgeType: lineageEdge.edge_type || 'depends_on',
                  columns: lineageEdge.columns?.map((c: any) => 
                    typeof c === 'string' ? c : `${c.source} -> ${c.target}`
                  ) || [],
                  transformation: lineageEdge.transformation,
                  organizationId,
                },
                update: {
                  edgeType: lineageEdge.edge_type || 'depends_on',
                  columns: lineageEdge.columns?.map((c: any) => 
                    typeof c === 'string' ? c : `${c.source} -> ${c.target}`
                  ) || [],
                  transformation: lineageEdge.transformation,
                },
              });
              edgesCreated++;
            } catch (err) {
              console.error(`[LINEAGE] Failed to upsert edge:`, err);
            }
          }
        }

        // Create a lineage snapshot record
        await prisma.lineageSnapshot.create({
          data: {
            organizationId,
            integrationId: node.integrationId,
            source: 'warehouse_scan',
            dialect: node.toolType.toLowerCase(),
            status: 'ready',
            nodeCount: nodeMap.size,
            edgeCount: edgesCreated,
            rootCount: lineageData.stats?.root_count || 0,
            leafCount: lineageData.stats?.leaf_count || 0,
          },
        });

        totalNodes += nodeMap.size;
        totalEdges += edgesCreated;

        results.push({
          nodeId: node.id,
          nodeName: node.name,
          success: true,
          nodesExtracted: nodeMap.size,
          edgesExtracted: edgesCreated,
        });

      } catch (err) {
        console.error(`[LINEAGE] Error processing ${node.name}:`, err);
        results.push({
          nodeId: node.id,
          nodeName: node.name,
          success: false,
          error: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    }

    return NextResponse.json({
      success: results.some(r => r.success),
      results,
      stats: {
        totalNodes,
        totalEdges,
        nodesProcessed: nodesToProcess.length,
      },
    });

  } catch (error) {
    console.error('[LINEAGE] Error extracting lineage:', error);
    return NextResponse.json(
      { error: 'Failed to extract lineage' },
      { status: 500 }
    );
  }
}

// GET /api/pipeline/[stackId]/lineage - Get stored lineage for this stack
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
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
    const session = await getServerSession(authOptions);
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
