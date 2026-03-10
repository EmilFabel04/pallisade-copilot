import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { notifyEvents } from '@/lib/notifications';

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
      console.error(`[LLM-EXTRACT] Failed to decrypt integration creds for ${node.name}:`, e);
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
      console.error('[LLM-EXTRACT] Failed to decrypt config:', e);
    }
  }

  if (!config) return null;

  // GitHub OAuth stores token in Integration.accessToken (not in credentials JSON).
  // Merge it into config so downstream code can find it as access_token.
  if (node.integration?.accessToken && !config.access_token) {
    try {
      config.access_token = decrypt(node.integration.accessToken);
    } catch (e) {
      console.error(`[LLM-EXTRACT] Failed to decrypt integration accessToken for ${node.name}:`, e);
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

// POST /api/pipeline/[stackId]/lineage/extract-llm — LLM-powered extraction with SSE
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
    const { llmProvider = 'anthropic', llmModel } = body;

    // Get the pipeline stack with nodes
    const stack = await prisma.pipelineStack.findFirst({
      where: { id: stackId, organizationId },
      include: { nodes: { include: { integration: true } } },
    });

    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    const connectedNodes = stack.nodes.filter(
      (n) => n.status === 'CONNECTED' || n.status === 'HEALTHY' || n.status === 'WARNING'
    );

    if (connectedNodes.length === 0) {
      return NextResponse.json({
        error: 'No connected nodes found in pipeline stack',
      }, { status: 400 });
    }

    // Build tool configs (same pattern as lineage/route.ts)
    const toolConfigs: Array<{
      tool_type: string;
      config: Record<string, any>;
      integration_id?: string;
      layer?: string;
    }> = [];

    // GitHub config for injection
    const githubNode = stack.nodes.find(
      (n: any) =>
        n.layer === 'VERSION_CONTROL' &&
        n.toolType === 'github' &&
        (n.status === 'CONNECTED' || n.status === 'HEALTHY')
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

    for (const node of connectedNodes) {
      const decryptedConfig = resolveNodeConfig(node);
      if (!decryptedConfig && node.toolType?.toLowerCase() !== 'airflow') {
        console.warn(`[LLM-EXTRACT] Skipping ${node.name}: could not decrypt config`);
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

    // Inject managed_tools into GitHub tool config — the frontend knows
    // which tools received GitHub attachments (relational knowledge that
    // drivers can't discover on their own).
    if (githubAttachment) {
      const managedToolTypes = toolConfigs
        .filter(tc => {
          if (tc.layer === 'VERSION_CONTROL') return false;
          const cfg = tc.config || {};
          return cfg.github?.token === githubAttachment!.token
            || cfg.github_token === githubAttachment!.token
            || cfg.github_repo === githubAttachment!.repo;
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

    // Build tool_nodes for view builder — safe metadata only.
    // CP relationship metadata (orchestrated_tools, managed_repos, etc.)
    // is now emitted by drivers directly on graph nodes, not derived here.
    const toolNodes = connectedNodes.map((n) => {
      const base: Record<string, any> = {
        id: n.id,
        name: n.name,
        toolType: n.toolType,
        layer: n.layer,
        status: n.status,
        integrationId: n.integrationId,
      };

      // For VCS tools, use the enriched toolConfig (which has managed_tools + repos)
      // rather than the raw node config, so managed repo references are included.
      if (n.layer === 'VERSION_CONTROL') {
        const enrichedTc = toolConfigs.find(tc => tc.layer === 'VERSION_CONTROL' && tc.config);
        const cfg = enrichedTc?.config || resolveNodeConfig(n) || {};
        base.config = {
          owner: cfg.owner || cfg.org || cfg.organization || '',
          repo: cfg.repo || '',
          repos: cfg.repos || cfg.repositories || [],
          org: cfg.owner || cfg.org || cfg.organization || '',
          branch: cfg.branch || 'main',
        };
      }

      return base;
    });

    // Fetch PipelineEdge records for structural CP evidence
    const pipelineEdges = await prisma.pipelineEdge.findMany({
      where: {
        OR: [
          { sourceId: { in: connectedNodes.map((cn) => cn.id) } },
          { targetId: { in: connectedNodes.map((cn) => cn.id) } },
        ],
      },
      select: { sourceId: true, targetId: true, label: true, dataFlow: true },
    });

    if (toolConfigs.length === 0) {
      return NextResponse.json({
        error: 'No extractable tool configurations found',
      }, { status: 400 });
    }

    console.log(
      `[LLM-EXTRACT] Starting LLM extraction with ${toolConfigs.length} tools: ${toolConfigs.map((t) => t.tool_type).join(', ')}`
    );

    // Call the FastAPI LLM extraction SSE endpoint
    const scannerResponse = await fetch(`${SCANNER_API_URL}/api/v1/lineage/extract-llm?stack_id=${stackId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool_configs: toolConfigs,
        llm_provider: llmProvider,
        llm_model: llmModel || undefined,
        tool_nodes: toolNodes,
        pipeline_edges: pipelineEdges,
      }),
      signal: AbortSignal.timeout(600000), // 10 minute timeout for LLM extraction
    });

    if (!scannerResponse.ok) {
      const errorText = await scannerResponse.text().catch(() => 'Unknown error');
      console.error(`[LLM-EXTRACT] Scanner API error: ${scannerResponse.status} ${errorText}`);

      notifyEvents.lineageExtractionFailed(
        organizationId, stackId, (session.user as any).id,
        toolConfigs.map((t: any) => t.tool_type).join(', '),
        errorText.slice(0, 200),
      );

      return NextResponse.json(
        { error: `LLM extraction failed: ${errorText}` },
        { status: scannerResponse.status }
      );
    }

    // Proxy the SSE stream to the frontend
    const stream = scannerResponse.body;
    if (!stream) {
      return NextResponse.json({ error: 'No stream from scanner' }, { status: 500 });
    }

    return new Response(stream as any, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error: any) {
    console.error('[LLM-EXTRACT] Error:', error);
    return NextResponse.json(
      { error: error.message || 'LLM extraction failed' },
      { status: 500 }
    );
  }
}
