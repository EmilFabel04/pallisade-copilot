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

    // All connected nodes that can participate in investigation
    const connectedNodes = stack.nodes.filter(
      (n) => n.status === 'CONNECTED' || n.status === 'HEALTHY'
    );

    if (connectedNodes.length === 0) {
      return NextResponse.json({
        error: 'No connected nodes found in pipeline stack'
      }, { status: 400 });
    }

    // If nodeId specified, only include that node
    const nodesToProcess = nodeId
      ? connectedNodes.filter(n => n.id === nodeId)
      : connectedNodes;

    if (nodesToProcess.length === 0) {
      return NextResponse.json({
        error: 'Specified node not found or not connected'
      }, { status: 400 });
    }

    // Build tool configs for all nodes
    const toolConfigs: Array<{
      tool_type: string;
      config: Record<string, any>;
      integration_id?: string;
      layer?: string;
    }> = [];

    // GitHub config for injection into transform/orchestration nodes
    const githubNode = stack.nodes.find(
      (n: any) => n.layer === 'VERSION_CONTROL' && n.toolType === 'github'
          && (n.status === 'CONNECTED' || n.status === 'HEALTHY')
    );
    let githubAttachment: Record<string, any> | null = null;
    if (githubNode) {
      const ghConfig = decryptNodeConfig(githubNode.config);
      if (ghConfig?.access_token && ghConfig?.owner) {
        githubAttachment = {
          repo: ghConfig.repo ? `${ghConfig.owner}/${ghConfig.repo}` : ghConfig.owner,
          token: ghConfig.access_token,
          branch: ghConfig.branch || 'main',
        };
      }
    }

    for (const node of nodesToProcess) {
      const decryptedConfig = decryptNodeConfig(node.config);
      // Airflow nodes may have empty config (GitHub-only mode)
      if (!decryptedConfig && node.toolType?.toLowerCase() !== 'airflow') {
        console.warn(`[LINEAGE] Skipping ${node.name}: could not decrypt config`);
        continue;
      }

      const extractConfig: Record<string, any> = { ...(decryptedConfig || {}) };

      // Attach GitHub config for transform/orchestration nodes
      if ((node.layer === 'TRANSFORMATION' || node.layer === 'ORCHESTRATION') && githubAttachment) {
        const isAirflow = node.toolType?.toLowerCase() === 'airflow';
        const isDbtCoreGithub = node.toolType?.toLowerCase() === 'dbt_core' && extractConfig.source_mode === 'github';
        extractConfig.github = {
          ...githubAttachment,
          ...(isAirflow
            ? { dag_directory: extractConfig.dag_directory || 'dags' }
            : { dbt_root: extractConfig.dbt_project_path || (githubAttachment as any).dbt_root || '' }),
        };
        // For dbt_core GitHub mode, also set github_token directly for manifest fetch
        if (isDbtCoreGithub) {
          extractConfig.github_token = githubAttachment.token;
          // Use user-specified repo if provided, otherwise fall back to GitHub node's repo
          if (!extractConfig.github_repo) {
            extractConfig.github_repo = githubAttachment.repo;
          }
        }
      }

      toolConfigs.push({
        tool_type: node.toolType,
        config: extractConfig,
        integration_id: node.integrationId || undefined,
        layer: node.layer,
      });
    }

    // Auto-add Airflow from GitHub if no explicit Airflow node
    const hasExplicitAirflow = nodesToProcess.some(n => n.toolType?.toLowerCase() === 'airflow');
    if (!hasExplicitAirflow && githubAttachment) {
      toolConfigs.push({
        tool_type: 'airflow',
        config: {
          dag_directory: 'dags',
          github: { ...githubAttachment, dag_directory: 'dags' },
        },
        layer: 'ORCHESTRATION',
      });
    }

    if (toolConfigs.length === 0) {
      return NextResponse.json({
        error: 'No extractable tool configurations found'
      }, { status: 400 });
    }

    console.log(`[LINEAGE] Starting investigation with ${toolConfigs.length} tools: ${toolConfigs.map(t => t.tool_type).join(', ')}`);

    // --- Call the Investigator endpoint (single request for all tools) ---
    const investigateResponse = await fetch(`${SCANNER_API_URL}/api/v1/lineage/investigate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        organization_id: organizationId,
        tool_configs: toolConfigs,
        options: {
          region: options.region || 'auto',
          days_back: options.days_back || 30,
        },
      }),
      signal: AbortSignal.timeout(300000), // 5 minute timeout
    });

    if (!investigateResponse.ok) {
      const errorData = await investigateResponse.json().catch(() => ({}));
      console.error('[LINEAGE] Investigator error:', errorData);
      return NextResponse.json({
        error: errorData.error || 'Investigation failed',
      }, { status: 500 });
    }

    const investigationData = await investigateResponse.json();
    const totalNodes = investigationData.stats?.total_nodes || 0;
    const totalEdges = investigationData.stats?.total_edges || 0;

    console.log(
      `[LINEAGE] Investigation complete: ${totalNodes} nodes, ${totalEdges} edges, ` +
      `${investigationData.stats?.connections_found || 0} tool connections, ` +
      `${investigationData.stats?.correlations_created || 0} correlation edges`
    );

    // Persist nodes to database
    const nodeMap = new Map<string, string>();
    for (const lineageNode of investigationData.nodes || []) {
      const fqn = lineageNode.fqn || lineageNode.name;
      const parts = fqn.split('.');
      const tableName = parts[parts.length - 1];
      const schema = parts.length > 1 ? parts[parts.length - 2] : null;
      const database = parts.length > 2 ? parts[parts.length - 3] : null;

      try {
        const dbNode = await prisma.lineageNode.upsert({
          where: {
            organizationId_name: { organizationId, name: fqn },
          },
          create: {
            name: fqn,
            database: database || lineageNode.database,
            schema: schema || lineageNode.schema_name,
            tableName,
            nodeType: lineageNode.node_type || 'table',
            description: lineageNode.description,
            criticality: lineageNode.criticality?.toUpperCase() || 'MEDIUM',
            rowCount: lineageNode.row_count,
            upstreamCount: lineageNode.upstream_count || 0,
            downstreamCount: lineageNode.downstream_count || 0,
            organizationId,
            integrationId: lineageNode.integration_id,
          },
          update: {
            nodeType: lineageNode.node_type || 'table',
            description: lineageNode.description,
            rowCount: lineageNode.row_count,
            upstreamCount: lineageNode.upstream_count || 0,
            downstreamCount: lineageNode.downstream_count || 0,
            integrationId: lineageNode.integration_id,
          },
        });
        nodeMap.set(lineageNode.id, dbNode.id);
      } catch (err) {
        console.error(`[LINEAGE] Failed to upsert node ${fqn}:`, err);
      }
    }

    // Persist edges to database
    let edgesCreated = 0;
    for (const lineageEdge of investigationData.edges || []) {
      const sourceDbId = nodeMap.get(lineageEdge.source_id);
      const targetDbId = nodeMap.get(lineageEdge.target_id);
      if (sourceDbId && targetDbId) {
        try {
          await prisma.lineageEdge.upsert({
            where: {
              sourceId_targetId: { sourceId: sourceDbId, targetId: targetDbId },
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
          console.error('[LINEAGE] Failed to upsert edge:', err);
        }
      }
    }

    // Create a snapshot record
    await prisma.lineageSnapshot.create({
      data: {
        organizationId,
        source: 'investigator',
        dialect: toolConfigs.map(t => t.tool_type).join(','),
        status: 'ready',
        nodeCount: nodeMap.size,
        edgeCount: edgesCreated,
        rootCount: 0,
        leafCount: 0,
      },
    });

    // Persist engine graph to snapshot for restart recovery
    try {
      const snapshotRes = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/snapshot`, {
        signal: AbortSignal.timeout(10000),
      });
      if (snapshotRes.ok) {
        const snapshotData = await snapshotRes.json();
        if (snapshotData.has_graph && snapshotData.graph_data) {
          const latestSnapshot = await prisma.lineageSnapshot.findFirst({
            where: { organizationId },
            orderBy: { createdAt: 'desc' },
          });
          if (latestSnapshot) {
            await prisma.lineageSnapshot.update({
              where: { id: latestSnapshot.id },
              data: { graphData: snapshotData.graph_data },
            });
            console.log(`[LINEAGE] Persisted engine graph to snapshot ${latestSnapshot.id}`);
          }
        }
      }
    } catch (e) {
      console.warn('[LINEAGE] Failed to persist engine graph snapshot (non-fatal):', e);
    }

    // Build results summary from investigation tool profiles
    const results = Object.entries(investigationData.investigation?.tool_profiles || {}).map(
      ([toolType, profile]: [string, any]) => ({
        nodeName: toolType,
        success: profile.success,
        nodesExtracted: profile.node_count,
        edgesExtracted: profile.edge_count,
        durationMs: profile.duration_ms,
        error: profile.error,
      })
    );

    return NextResponse.json({
      success: investigationData.success,
      run_id: investigationData.stats?.run_id || null,
      results,
      investigation: investigationData.investigation,
      stats: {
        totalNodes,
        totalEdges,
        toolsExamined: investigationData.stats?.tools_examined || 0,
        connectionsFound: investigationData.stats?.connections_found || 0,
        correlationsCreated: investigationData.stats?.correlations_created || 0,
        run_id: investigationData.stats?.run_id || null,
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

    // Clear in-memory engine graph and run registry so stale views aren't served
    const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';
    try {
      await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/clear-cache`, {
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
