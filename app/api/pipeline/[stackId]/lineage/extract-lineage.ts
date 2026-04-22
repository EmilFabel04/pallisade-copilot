import { NextResponse } from 'next/server';
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

  // OAuth integrations (e.g. GitHub) store token in Integration.accessToken
  // rather than in the credentials JSON blob — bootstrap config from OAuth fields
  // so the node isn't skipped as "no config".
  if (!config && node.integration?.accessToken) {
    config = {};
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

/**
 * Shared lineage extraction logic — used by both the user-facing POST handler
 * and the internal scheduled endpoint.
 */
export async function extractLineageForStack(
  stackId: string,
  organizationId: string,
  body: { nodeId?: string; options?: any }
): Promise<NextResponse> {
  try {
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
      let ghConfig = resolveNodeConfig(githubNode);

      // OAuth tools (GitHub) may not have integrationId on the PipelineNode.
      // The link is stored as _integration_id in the node config instead.
      // Resolve the Integration to get the encrypted accessToken.
      if (ghConfig && !ghConfig.access_token && ghConfig._integration_id) {
        try {
          const linkedIntegration = await prisma.integration.findUnique({
            where: { id: ghConfig._integration_id },
            select: { accessToken: true, metadata: true },
          });
          if (linkedIntegration?.accessToken) {
            ghConfig.access_token = decrypt(linkedIntegration.accessToken);
          }
          if (!ghConfig.owner && !ghConfig.org && linkedIntegration?.metadata) {
            const meta = linkedIntegration.metadata as any;
            if (meta.username) ghConfig.owner = meta.username;
          }
        } catch (e) {
          console.error('[LINEAGE] Failed to resolve _integration_id for GitHub:', e);
        }
      }

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

      // Resolve OAuth _integration_id for nodes that lack a direct integrationId FK
      // (e.g. GitHub OAuth stores the link in node config, not as a PipelineNode FK)
      if (!extractConfig.access_token && extractConfig._integration_id && !node.integrationId) {
        try {
          const linkedInt = await prisma.integration.findUnique({
            where: { id: extractConfig._integration_id },
            select: { accessToken: true, metadata: true },
          });
          if (linkedInt?.accessToken) {
            extractConfig.access_token = decrypt(linkedInt.accessToken);
          }
          if (!extractConfig.owner && !extractConfig.org && linkedInt?.metadata) {
            const meta = linkedInt.metadata as any;
            if (meta.username) extractConfig.owner = meta.username;
          }
        } catch (e) {
          console.error(`[LINEAGE] Failed to resolve _integration_id for ${node.name}:`, e);
        }
      }

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

    // Ensure GitHub appears in tool_configs so the pipeline overview shows it.
    // GitHub is a control-plane tool (no lineage data) — it just needs to be
    // present in tool_nodes with managed_tools metadata for CP edge creation.
    if (githubNode && !toolConfigs.some(tc => tc.layer === 'VERSION_CONTROL')) {
      const ghNodeConfig = (githubNode as any).config || {};
      // A tool is "managed" by GitHub if it has GitHub credentials injected,
      // OR if it has a github_repo field set (user specified code location).
      const managedToolTypes = toolConfigs
        .filter(tc => {
          if (tc.layer === 'VERSION_CONTROL') return false;
          const cfg = tc.config || {};
          return cfg.github_repo || cfg.code_repo
            || (githubAttachment && (
              cfg.github?.token === githubAttachment.token
              || cfg.github_token === githubAttachment.token
            ));
        })
        .map(tc => tc.tool_type.toLowerCase());
      toolConfigs.push({
        tool_type: 'github',
        config: {
          owner: ghNodeConfig.owner || ghNodeConfig.org || '',
          repo: ghNodeConfig.repo || '',
          managed_tools: managedToolTypes,
          // Pass token so LiveGithubAdapter can fetch & classify repos
          ...(githubAttachment ? { access_token: githubAttachment.token } : {}),
        },
        integration_id: ghNodeConfig._integration_id || (githubNode as any).integrationId || undefined,
        layer: 'VERSION_CONTROL',
      });
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

    // Mark stack as extraction-enabled and record timestamp (resets 6h auto-timer).
    // Also stamp each integration attached to a node in this stack so the sources
    // list shows a real extraction status instead of "Never".
    const extractedAt = new Date();
    await prisma.$transaction([
      prisma.pipelineStack.update({
        where: { id: stackId },
        data: {
          lineageExtractionEnabled: true,
          lastLineageExtractedAt: extractedAt,
        },
      }),
      prisma.integration.updateMany({
        where: { pipelineNodes: { some: { stackId } } },
        data: {
          lastLineageExtractedAt: extractedAt,
          lastExtractedAt: extractedAt,
        },
      }),
    ]);

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
