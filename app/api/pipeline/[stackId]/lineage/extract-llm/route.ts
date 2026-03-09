import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { notifyEvents } from '@/lib/notifications';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// Resolve credentials for a node — prefers Integration table, falls back to PipelineNode.config
function resolveNodeConfig(node: any): Record<string, any> | null {
  // Prefer Integration table
  if (node.integrationId && node.integration?.credentials) {
    try {
      const creds = node.integration.credentials as any;
      if (creds.encrypted) {
        return JSON.parse(decrypt(creds.encrypted));
      }
      return creds;
    } catch (e) {
      console.error(`[LLM-EXTRACT] Failed to decrypt integration creds for ${node.name}:`, e);
    }
  }
  // Legacy fallback: PipelineNode.config
  if (!node.config) return null;
  try {
    if (node.config.encrypted) {
      return JSON.parse(decrypt(node.config.encrypted));
    }
    return node.config as Record<string, any>;
  } catch (e) {
    console.error('[LLM-EXTRACT] Failed to decrypt config:', e);
    return null;
  }
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

    // Build tool_nodes for view builder
    const toolNodes = connectedNodes.map((n) => ({
      id: n.id,
      name: n.name,
      toolType: n.toolType,
      layer: n.layer,
      status: n.status,
      integrationId: n.integrationId,
    }));

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
