import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

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
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { taskId } = await params;
    const organizationId = (session.user as any).organizationId;

    const task = await prisma.monitor.findFirst({
      where: { id: taskId, organizationId },
    });

    if (!task) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    // Resolve warehouse config — prefer task's specific integration, fallback to auto-discover
    let integrationConfig: Record<string, any> | null = null;
    const taskConfig = (task.config as Record<string, any>) || {};

    // 1. Try task's explicit integrationId (FK to Integration → find its PipelineNode)
    if (task.integrationId) {
      const linkedNode = await prisma.pipelineNode.findFirst({
        where: {
          integrationId: task.integrationId,
          toolType: { in: WAREHOUSE_TOOL_TYPES },
          status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
        },
        select: { id: true, name: true, toolType: true, config: true },
      });
      if (linkedNode) {
        integrationConfig = resolveNodeConfig(linkedNode);
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
        select: { id: true, name: true, toolType: true, config: true },
      });
      if (specificNode) {
        integrationConfig = resolveNodeConfig(specificNode);
        console.log(`[Schedule] Resolved warehouse from config.nodeId: ${specificNode.name} (${specificNode.toolType})`);
      }
    }

    // 3. Fallback: auto-discover first warehouse node in the org's pipeline stack
    if (!integrationConfig) {
      const pipelineStack = await prisma.pipelineStack.findFirst({
        where: { organizationId },
        include: {
          nodes: {
            where: {
              toolType: { in: WAREHOUSE_TOOL_TYPES },
              status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
            },
            select: { id: true, name: true, toolType: true, config: true },
            take: 1,
          },
        },
      });

      const warehouseNode = pipelineStack?.nodes[0];
      if (warehouseNode) {
        integrationConfig = resolveNodeConfig(warehouseNode);
        console.log(`[Schedule] Auto-discovered warehouse: ${warehouseNode.name} (${warehouseNode.toolType})`);
      } else {
        console.warn('[Schedule] No warehouse pipeline node found for org:', organizationId);
      }
    }

    // For infrastructure monitors, resolve server connection config
    const INFRA_MONITOR_TYPES = ['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS'];
    if (INFRA_MONITOR_TYPES.includes(task.monitorType || '')) {
      const taskConfig = (task.config as Record<string, any>) || {};
      const serverNodeId = taskConfig.serverNodeId;

      const serverStack = await prisma.pipelineStack.findFirst({
        where: { organizationId },
        include: {
          nodes: {
            where: {
              toolType: 'linux_server',
              ...(serverNodeId ? { id: serverNodeId } : {}),
            },
            select: { id: true, name: true, toolType: true, config: true },
            take: 1,
          },
        },
      });

      const serverNode = serverStack?.nodes[0];
      if (serverNode) {
        integrationConfig = resolveNodeConfig(serverNode);
        console.log(`[Schedule] Resolved server: ${serverNode.name}`);
      } else {
        console.warn('[Schedule] No linux_server node found for infra monitor');
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

    // Call the Python backend to execute
    const startedAt = new Date();

    const executeResponse = await fetch(`${SCANNER_API_URL}/api/v1/schedule/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: task.id,
        name: task.name,
        task_mode: task.taskMode || 'structured',
        prompt: task.prompt,
        monitor_type: task.monitorType,
        target_fqn: task.targetFqn,
        config: monitorConfig,
        integration_config: integrationConfig,
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

    return NextResponse.json({ run, result });
  } catch (error: any) {
    console.error('[Schedule] Run task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
