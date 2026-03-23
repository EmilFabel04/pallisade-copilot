import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// Resolve credentials for a node — prefers Integration table, falls back to PipelineNode.config
function resolveNodeConfig(node: any): Record<string, any> | null {
  let config: Record<string, any> | null = null;

  // Prefer Integration table (credentials JSON blob)
  if (node.integrationId && node.integration?.credentials) {
    try {
      const creds = node.integration.credentials as any;
      if (creds.encrypted) {
        config = JSON.parse(decrypt(creds.encrypted));
      } else {
        config = creds;
      }
    } catch (e) {
      console.error(`[LINEAGE] Failed to decrypt integration creds for ${node.name}:`, e);
    }
  }

  // Legacy fallback: PipelineNode.config
  if (!config && node.config) {
    try {
      if (node.config.encrypted) {
        config = JSON.parse(decrypt(node.config.encrypted));
      } else {
        config = node.config as Record<string, any>;
      }
    } catch (e) {
      console.error('[LINEAGE] Failed to decrypt config:', e);
    }
  }

  if (!config) return null;

  // GitHub OAuth stores token in Integration.accessToken (not in credentials JSON).
  // Merge it into config so downstream code can find it as access_token.
  if (node.integration?.accessToken && !config.access_token) {
    try {
      config.access_token = decrypt(node.integration.accessToken);
    } catch (e) {
      console.error(`[LINEAGE] Failed to decrypt integration accessToken for ${node.name}:`, e);
    }
  }

  // GitHub OAuth stores owner in Integration.metadata.username
  if (!config.owner && !config.org && node.integration?.metadata) {
    const meta = node.integration.metadata as any;
    if (meta.username) {
      config.owner = meta.username;
    }
  }

  return config;
}

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
    const { nodeId, options = {} } = body;

    // Get the pipeline stack
    const stack = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
      include: {
        nodes: { include: { integration: true } },
      },
    });

    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    // All connected nodes that can participate in investigation
    const connectedNodes = stack.nodes.filter(
      (n) => n.status === 'CONNECTED' || n.status === 'HEALTHY' || n.status === 'WARNING'
    );

    if (connectedNodes.length === 0) {
      return NextResponse.json({
        error: 'No connected nodes found in pipeline stack'
      }, { status: 400 });
    }

    // Fetch user-drawn PipelineEdge records for CP evidence
    const pipelineEdges = await prisma.pipelineEdge.findMany({
      where: {
        OR: [
          { sourceId: { in: connectedNodes.map((n) => n.id) } },
          { targetId: { in: connectedNodes.map((n) => n.id) } },
        ],
      },
      select: { sourceId: true, targetId: true, label: true, dataFlow: true },
    });

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
      const ghConfig = resolveNodeConfig(githubNode);
      if (ghConfig?.access_token && ghConfig?.owner) {
        githubAttachment = {
          repo: ghConfig.repo ? `${ghConfig.owner}/${ghConfig.repo}` : ghConfig.owner,
          token: ghConfig.access_token,
          branch: ghConfig.branch || 'main',
        };
      }
    }

    for (const node of nodesToProcess) {
      const decryptedConfig = resolveNodeConfig(node);
      // Airflow nodes may have empty config (GitHub-only mode)
      if (!decryptedConfig && node.toolType?.toLowerCase() !== 'airflow') {
        console.warn(`[LINEAGE] Skipping ${node.name}: could not decrypt config`);
        continue;
      }

      const extractConfig: Record<string, any> = { ...(decryptedConfig || {}) };

      // Attach GitHub config for transform/orchestration nodes —
      // only inject from VERSION_CONTROL node if the tool doesn't have its own github_token
      if ((node.layer === 'TRANSFORMATION' || node.layer === 'ORCHESTRATION') && !extractConfig.github_token && githubAttachment) {
        const isAirflow = node.toolType?.toLowerCase() === 'airflow';
        extractConfig.github = {
          ...githubAttachment,
          ...(isAirflow
            ? { dag_directory: extractConfig.dag_directory || 'dags' }
            : { dbt_root: extractConfig.dbt_project_path || (githubAttachment as any).dbt_root || '' }),
        };
        // For dbt_core GitHub mode, also set github_token directly for manifest fetch
        const isDbtCoreGithub = node.toolType?.toLowerCase() === 'dbt_core' && extractConfig.source_mode === 'github';
        if (isDbtCoreGithub) {
          extractConfig.github_token = githubAttachment.token;
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

    // Enrich GitHub tool_config with the tools it manages.
    // The frontend knows exactly which tools got GitHub attachments injected —
    // those are the tools whose code lives in this GitHub integration.
    if (githubAttachment) {
      const managedToolTypes = toolConfigs
        .filter(tc => {
          if (tc.layer === 'VERSION_CONTROL') return false;
          const cfg = tc.config || {};
          // Tool got a GitHub attachment if its config has a github object
          // with a matching repo/token, or github_repo was set from the attachment
          return cfg.github?.token === githubAttachment.token
            || cfg.github_token === githubAttachment.token
            || cfg.github_repo === githubAttachment.repo;
        })
        .map(tc => tc.tool_type.toLowerCase());

      if (managedToolTypes.length > 0) {
        // Collect repos explicitly referenced by managed tools
        const managedRepos = new Set<string>();
        for (const tc of toolConfigs) {
          if (tc.layer === 'VERSION_CONTROL') continue;
          const cfg = tc.config || {};
          if (cfg.github_repo && cfg.github_repo.includes('/')) {
            managedRepos.add(cfg.github_repo);
          }
        }

        const ghConfig = toolConfigs.find(tc => tc.layer === 'VERSION_CONTROL');
        if (ghConfig) {
          ghConfig.config = {
            ...ghConfig.config,
            managed_tools: managedToolTypes,
            ...(managedRepos.size > 0 ? { repos: [...managedRepos] } : {}),
          };
        }
      }
    }

    if (toolConfigs.length === 0) {
      return NextResponse.json({
        error: 'No extractable tool configurations found'
      }, { status: 400 });
    }

    console.log(`[LINEAGE] Starting LLM-enhanced investigation with ${toolConfigs.length} tools: ${toolConfigs.map(t => t.tool_type).join(', ')}`);

    // --- Call the LLM-enhanced Investigator (adapters + planner + reconciler) ---
    const investigateResponse = await fetch(`${SCANNER_API_URL}/api/v1/lineage/investigate-llm?stack_id=${stackId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool_configs: toolConfigs,
        use_llm_planner: true,
        use_llm_reconciler: false,
        llm_provider: 'openai',
        pipeline_edges: pipelineEdges,
      }),
      signal: AbortSignal.timeout(600000), // 10 minute timeout (LLM reconciler needs more time)
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
            platform: lineageNode.platform || null,
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
            platform: lineageNode.platform || undefined,
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
      const snapshotRes = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/snapshot?stack_id=${stackId}`, {
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
    const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';
    try {
      const { stackId: delStackId } = await params;
      await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/clear-cache?stack_id=${delStackId}`, {
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
