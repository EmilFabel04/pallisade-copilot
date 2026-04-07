import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { notifyEvents } from '@/lib/notifications';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

const WAREHOUSE_TOOL_TYPES = ['bigquery', 'snowflake', 'postgres', 'redshift'];

/**
 * Resolve warehouse connection config from a PipelineNode.
 * Follows the same decryption + field-mapping pattern as copilot/chat/route.ts.
 */
function resolveNodeConfig(node: {
  id: string;
  name: string;
  toolType: string;
  config: any;
}): Record<string, any> | null {
  if (!node.config) return null;

  let credentials: Record<string, any> = {};
  try {
    const configJson = node.config as { encrypted?: string; _cached?: any; [key: string]: any };
    if (configJson.encrypted) {
      const decrypted = decrypt(configJson.encrypted);
      credentials = JSON.parse(decrypted);
    } else {
      const { _cached, ...creds } = configJson;
      credentials = creds;
    }
  } catch {
    return null;
  }

  const config = { ...credentials };
  const toolType = node.toolType.toUpperCase();

  // username → user (same mapping as copilot chat route)
  const usernameToUserTypes = ['SNOWFLAKE', 'POSTGRES', 'REDSHIFT'];
  if (usernameToUserTypes.includes(toolType) && config.username && !config.user) {
    config.user = config.username;
    delete config.username;
  }

  return {
    id: node.id,
    name: node.name,
    type: node.toolType,
    ...config,
  };
}

// POST /api/schedule/tasks/[taskId]/run - Trigger immediate execution
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { taskId } = await params;
    const organizationId = (session.user as any).organizationId;
    const baseUrl = request.nextUrl?.origin || process.env.NEXTAUTH_URL || 'http://localhost:3000';
    const cookie = request.headers.get('cookie') || '';

    const task = await prisma.monitor.findFirst({
      where: { id: taskId, organizationId },
    });

    if (!task) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    // Classify the monitor type to decide which integration resolution path to use
    let integrationConfig: Record<string, any> | null = null;
    const taskConfig = (task.config as Record<string, any>) || {};

    const INFRA_MONITOR_TYPES = ['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS'];
    const TOOL_MONITOR_TYPES_LIST = [
      'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
      'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
      'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
    ];
    const isInfra = INFRA_MONITOR_TYPES.includes(task.monitorType || '');
    const isTool = TOOL_MONITOR_TYPES_LIST.includes(task.monitorType || '');

    // Resolve warehouse config — only for warehouse SQL monitors (not infra/tool)
    // Helper to pick the best config source: Integration.credentials (where pipeline save stores them)
    // or PipelineNode.config (legacy nodes that haven't been re-saved)
    const pickConfig = (node: { config: any; integration?: { credentials: any } | null }) =>
      node.integration?.credentials || node.config;
    const nodeSelect = { id: true, name: true, toolType: true, config: true, integration: { select: { credentials: true } } } as const;

    if (!isInfra && !isTool) {
      // 1. Try task's explicit integrationId (FK to Integration → find its PipelineNode)
      if (task.integrationId) {
        const linkedNode = await prisma.pipelineNode.findFirst({
          where: {
            integrationId: task.integrationId,
            toolType: { in: WAREHOUSE_TOOL_TYPES },
            status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
          },
          select: nodeSelect,
        });
        if (linkedNode) {
          integrationConfig = resolveNodeConfig({ ...linkedNode, config: pickConfig(linkedNode) });
          console.log(`[Schedule] Resolved warehouse from integrationId: ${linkedNode.name} (${linkedNode.toolType})`);
        }
      }

      // 2. Try config.nodeId (PipelineNode ID stored when integrationId wasn't a valid FK)
      if (!integrationConfig && taskConfig.nodeId) {
        const specificNode = await prisma.pipelineNode.findFirst({
          where: {
            id: taskConfig.nodeId,
            toolType: { in: WAREHOUSE_TOOL_TYPES },
            status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
          },
          select: nodeSelect,
        });
        if (specificNode) {
          integrationConfig = resolveNodeConfig({ ...specificNode, config: pickConfig(specificNode) });
          console.log(`[Schedule] Resolved warehouse from config.nodeId: ${specificNode.name} (${specificNode.toolType})`);
        }
      }

      // 3. Fallback: match target FQN database to a warehouse, or pick first
      if (!integrationConfig) {
        const pipelineStack = await prisma.pipelineStack.findFirst({
          where: { organizationId },
          include: {
            nodes: {
              where: {
                toolType: { in: WAREHOUSE_TOOL_TYPES },
                status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
              },
              select: nodeSelect,
            },
          },
        });

        const warehouseNodes = pipelineStack?.nodes || [];
        const fqnDb = (task.targetFqn || '').split('.')[0]?.toLowerCase();

        // Try to match the FQN database/project to a warehouse node's config
        let matchedNode = null;
        if (fqnDb) {
          for (const wn of warehouseNodes) {
            const cfg = pickConfig(wn) || {};
            const dbNames = [
              cfg.project_id, cfg.project, cfg.database, cfg.dbname,
              cfg.default_dataset, cfg.schema, wn.name,
            ].filter(Boolean).map((v: string) => v.toLowerCase());
            if (dbNames.includes(fqnDb)) {
              matchedNode = wn;
              break;
            }
          }
        }

        const warehouseNode = matchedNode || warehouseNodes[0];
        if (warehouseNode) {
          integrationConfig = resolveNodeConfig({ ...warehouseNode, config: pickConfig(warehouseNode) });
          console.log(`[Schedule] ${matchedNode ? 'Matched' : 'Auto-discovered'} warehouse: ${warehouseNode.name} (${warehouseNode.toolType}) for FQN db: ${fqnDb}`);
        } else {
          console.warn('[Schedule] No warehouse pipeline node found for org:', organizationId);
        }
      }
    }

    // For infrastructure monitors, resolve server connection config
    if (isInfra) {
      const serverNodeId = taskConfig.serverNodeId;
      console.log(`[Schedule] Infra monitor: serverNodeId=${serverNodeId}, integrationId=${task.integrationId}`);

      // 1. Direct lookup by serverNodeId (most reliable)
      if (serverNodeId) {
        const directNode = await prisma.pipelineNode.findFirst({
          where: { id: serverNodeId },
          select: { id: true, name: true, toolType: true, config: true },
        });
        if (directNode) {
          integrationConfig = resolveNodeConfig(directNode);
          console.log(`[Schedule] Resolved server by nodeId: ${directNode.name} (${directNode.toolType})`);
        }
      }

      // 2. Try integrationId → find the node linked to that integration
      if (!integrationConfig && task.integrationId) {
        const linkedNode = await prisma.pipelineNode.findFirst({
          where: { integrationId: task.integrationId, toolType: 'linux_server' },
          select: { id: true, name: true, toolType: true, config: true },
        });
        if (linkedNode) {
          integrationConfig = resolveNodeConfig(linkedNode);
          console.log(`[Schedule] Resolved server by integrationId: ${linkedNode.name}`);
        }
      }

      // 3. Fallback: find any linux_server in the org's pipeline stack
      if (!integrationConfig) {
        const serverStack = await prisma.pipelineStack.findFirst({
          where: { organizationId },
          include: {
            nodes: {
              where: { toolType: 'linux_server' },
              select: { id: true, name: true, toolType: true, config: true },
              take: 1,
            },
          },
        });

        const serverNode = serverStack?.nodes[0];
        if (serverNode) {
          integrationConfig = resolveNodeConfig(serverNode);
          console.log(`[Schedule] Resolved server from stack: ${serverNode.name}`);
        } else {
          console.warn('[Schedule] No linux_server node found for infra monitor');
        }
      }
    }

    // For tool monitors (Fivetran/Airflow/dbt), resolve integration config
    const TOOL_NODE_TYPE_MAP: Record<string, string[]> = {
      SYNC_LAG: ['fivetran', 'airbyte'],
      FAILED_SYNCS: ['fivetran', 'airbyte'],
      CONNECTOR_SCHEMA_DRIFT: ['fivetran', 'airbyte'],
      DAG_LAST_RUN: ['airflow', 'dagster'],
      DAG_SCHEDULE_LAG: ['airflow', 'dagster'],
      TASK_FAILURE_RATE: ['airflow', 'dagster'],
      DBT_TEST_FAILURES: ['dbt_cloud', 'dbt_core'],
      DBT_MODEL_FRESHNESS: ['dbt_cloud', 'dbt_core'],
      DBT_SOURCE_FRESHNESS: ['dbt_cloud', 'dbt_core'],
    };

    if (isTool) {
      const toolNodeId = taskConfig.toolNodeId;
      const requiredTypes = TOOL_NODE_TYPE_MAP[task.monitorType!] || [];

      // Find the raw tool node first (we need it for both config resolution and mode checks)
      // Include Integration.credentials since that's where the real config lives after pipeline save
      let rawToolNode: { id: string; name: string; toolType: string; config: any; integration?: { credentials: any } | null } | null = null;

      if (toolNodeId) {
        rawToolNode = await prisma.pipelineNode.findFirst({
          where: {
            id: toolNodeId,
            toolType: { in: requiredTypes },
            status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
          },
          select: { id: true, name: true, toolType: true, config: true, integration: { select: { credentials: true } } },
        });
      }

      // Auto-discover if no explicit node
      if (!rawToolNode) {
        const toolStack = await prisma.pipelineStack.findFirst({
          where: { organizationId },
          include: {
            nodes: {
              where: {
                toolType: { in: requiredTypes },
                status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
              },
              select: { id: true, name: true, toolType: true, config: true, integration: { select: { credentials: true } } },
              take: 1,
            },
          },
        });
        rawToolNode = toolStack?.nodes[0] ?? null;
      }

      if (rawToolNode) {
        // Prefer Integration credentials (where pipeline save stores them),
        // fall back to PipelineNode.config for legacy nodes
        const configSource = rawToolNode.integration?.credentials || rawToolNode.config;
        integrationConfig = resolveNodeConfig({ ...rawToolNode, config: configSource });
        console.log(`[Schedule] Resolved tool: ${rawToolNode.name} (${rawToolNode.toolType})`);
      } else {
        console.warn(`[Schedule] No ${requiredTypes.join('/')} node found for ${task.monitorType}`);
      }

      // Airflow/Dagster monitors require a live API — check after decryption
      const AIRFLOW_MONITORS = ['DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE'];
      if (integrationConfig && AIRFLOW_MONITORS.includes(task.monitorType!)) {
        const sourceMode = integrationConfig.source_mode;
        const hasHost = !!(integrationConfig.host || integrationConfig.base_url);
        if (sourceMode === 'github' || (!hasHost && integrationConfig.github_repo)) {
          return NextResponse.json({
            run: null,
            result: {
              status: 'ERROR',
              message: `Airflow integration "${rawToolNode?.name || 'unknown'}" is connected in GitHub DAG-file mode (static project files only). `
                + 'Airflow monitors require a live Airflow instance connection to check DAG run status. '
                + 'Go to the Pipeline page and switch the Airflow integration to API mode with a host URL (e.g. https://your-airflow.example.com).',
            },
          });
        }
      }

      // dbt monitors require dbt Cloud — check if integration is in static mode
      const DBT_MONITORS = ['DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS'];
      if (integrationConfig && DBT_MONITORS.includes(task.monitorType!)) {
        const sourceMode = integrationConfig.source_mode;
        const hasApiKey = !!(integrationConfig.api_key || integrationConfig.token);
        if (!hasApiKey && ['upload', 'project', 'github'].includes(sourceMode)) {
          return NextResponse.json({
            run: null,
            result: {
              status: 'ERROR',
              message: `dbt integration "${rawToolNode?.name || 'unknown'}" is connected in ${sourceMode} mode (static project files only). `
                + 'dbt monitors require a live dbt Cloud API connection to check job runs and test results. '
                + 'Go to the Pipeline page and switch to a dbt Cloud integration with an API key.',
            },
          });
        }
      }
    }

    // Inject stored baseline into config (so monitors can use it when
    // warehouse history is insufficient for Z-score computation)
    const monitorConfig = { ...(task.config as Record<string, any> || {}) };
    if (task.baselineMean !== null && task.baselineMean !== undefined) {
      monitorConfig.stored_baseline = {
        mean: task.baselineMean,
        stddev: task.baselineStddev,
        count: task.baselineCount,
      };
    }

    // --- Resolve policy for runtime enforcement ---
    let policyConfig: Record<string, any> | null = null;
    const policyOverrides: string[] = (task.policyOverrides as string[]) || [];

    if (task.targetFqn && !isInfra) {
      // Derive domain from monitor type for accurate policy resolution
      const MONITOR_DOMAIN_MAP: Record<string, string> = {
        SYNC_LAG: 'ingestion', FAILED_SYNCS: 'ingestion', CONNECTOR_SCHEMA_DRIFT: 'ingestion',
        DAG_LAST_RUN: 'orchestration', DAG_SCHEDULE_LAG: 'orchestration', TASK_FAILURE_RATE: 'orchestration',
        DBT_TEST_FAILURES: 'transform', DBT_MODEL_FRESHNESS: 'transform', DBT_SOURCE_FRESHNESS: 'transform',
        BI_FRESHNESS_PROXY: 'bi', BI_UPSTREAM_BREAK_RISK: 'bi', BI_CONTENT_HEALTH: 'bi', BI_REFRESH_FAILURE: 'bi',
        QUERY_PERFORMANCE: 'warehouse', COST_ANOMALY: 'warehouse', STORAGE_GROWTH: 'warehouse',
      };
      const resolvedDomain = MONITOR_DOMAIN_MAP[task.monitorType || ''] || 'warehouse';

      try {
        const policyRes = await fetch(`${baseUrl}/api/schedule/policies/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', cookie },
          body: JSON.stringify({
            nodes: [{ fqn: task.targetFqn, domain: resolvedDomain, criticality: 'medium' }],
            stackId: undefined,
          }),
        });
        if (policyRes.ok) {
          const policyData = await policyRes.json();
          const resolved = policyData.policies?.[task.targetFqn];
          if (resolved) {
            // Flatten policy sections into a single config dict
            policyConfig = {
              ...resolved.freshness,
              ...resolved.schema,
              ...resolved.volume,
              ...resolved.anomaly,
              ...resolved.quality,
              ...resolved.ingestion,
              ...resolved.bi,
              ...resolved.orchestration,
              ...resolved.transform,
              ...resolved.infrastructure,
            };
          }
        }
      } catch (err) {
        console.warn('[Schedule] Policy resolution failed (non-fatal):', err);
      }
    }

    // Call the Python backend to execute
    const startedAt = new Date();

    const executeResponse = await fetch(`${SCANNER_API_URL}/api/v1/schedule/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: task.id,
        name: task.name,
        task_mode: task.taskMode || (task.monitorType === 'AI_PROMPT' ? 'prompt' : 'structured'),
        prompt: task.prompt || (monitorConfig as any)?.prompt,
        monitor_type: task.monitorType,
        target_fqn: task.targetFqn,
        config: monitorConfig,
        integration_id: task.integrationId,
        organization_id: organizationId,
        integration_config: integrationConfig,
        policy_config: policyConfig,
        policy_overrides: policyOverrides,
      }),
    });

    const completedAt = new Date();
    const durationMs = completedAt.getTime() - startedAt.getTime();

    let result: any;
    if (executeResponse.ok) {
      result = await executeResponse.json();
    } else {
      const errorText = await executeResponse.text();
      result = {
        status: 'ERROR',
        message: `Execution failed: ${errorText}`,
      };
    }

    // Normalize status to uppercase (Python monitors return lowercase, Prisma enum is uppercase)
    const status = (result.status || 'ERROR').toUpperCase();

    // Save the run result
    const run = await prisma.monitorRun.create({
      data: {
        status,
        value: result.value ?? null,
        threshold: result.threshold ?? null,
        message: result.message || '',
        details: result.details || undefined,
        sqlExecuted: result.sql_executed || null,
        startedAt,
        completedAt,
        durationMs,
        monitorId: task.id,
      },
    });

    // Update the monitor's last run info + persist baseline stats
    const updateData: Record<string, any> = {
      lastRunAt: completedAt,
      lastStatus: status,
    };

    // Save baseline from result details (used on subsequent runs)
    const details = result.details || {};
    if (details.baseline_mean !== undefined) {
      updateData.baselineMean = details.baseline_mean;
      updateData.baselineStddev = details.baseline_stddev ?? 0;
      updateData.baselineCount = details.baseline_count ?? details.data_points ?? 0;
    }

    await prisma.monitor.update({
      where: { id: task.id },
      data: updateData,
    });

    // Fire-and-forget notification (skip when running as part of a group —
    // the bundle endpoint sends one collective notification instead)
    const isGrouped = request.nextUrl.searchParams.get('grouped') === 'true';
    if (!isGrouped) {
      const pipelineStack = await prisma.pipelineStack.findFirst({
        where: { organizationId },
        select: { id: true },
      });
      if (status === 'FAIL' || status === 'ERROR') {
        notifyEvents.monitorFailed(
          organizationId, pipelineStack?.id, (session.user as any).id,
          task.name, task.id, result.message || 'Monitor check failed',
        );
      } else if (status === 'PASS') {
        notifyEvents.monitorPassed(
          organizationId, pipelineStack?.id, task.name, task.id,
        );
      }
    }

    return NextResponse.json({ run, result });
  } catch (error: any) {
    console.error('[Schedule] Run task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
