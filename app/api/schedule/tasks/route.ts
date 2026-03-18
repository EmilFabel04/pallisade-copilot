import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { computeNextRun } from '@/lib/cron';

// GET /api/schedule/tasks - List all scheduled tasks
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

    const { searchParams } = new URL(request.url);
    const status = searchParams.get('status'); // all, passing, failing, disabled
    const due = searchParams.get('due'); // "true" — for scheduler to get due tasks

    const where: any = { organizationId };

    if (due === 'true') {
      // Scheduler needs ALL due monitors including watch-grouped ones
      where.enabled = true;
      where.nextRunAt = { lte: new Date() };
    } else {
      // Display queries: exclude monitors that belong to a watch group
      // (they're shown under their parent watch, not as standalone tasks)
      where.monitorGroupId = null;
    }

    if (status === 'disabled') {
      where.enabled = false;
    } else if (status === 'passing') {
      where.enabled = true;
      where.lastStatus = 'PASS';
    } else if (status === 'failing') {
      where.enabled = true;
      where.lastStatus = { in: ['FAIL', 'WARN', 'ERROR'] };
    }

    const tasks = await prisma.monitor.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      include: {
        integration: {
          select: { id: true, name: true, type: true },
        },
        monitorGroup: {
          select: { id: true, name: true },
        },
        _count: {
          select: { runs: true },
        },
      },
    });

    return NextResponse.json({ tasks });
  } catch (error: any) {
    console.error('[Schedule] List tasks error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// POST /api/schedule/tasks - Create a new scheduled task
export async function POST(request: NextRequest) {
  try {
    // Support both session auth (browser) and internal auth (copilot executor)
    let organizationId: string | undefined;
    let userId: string | undefined;

    const internalSecret = request.headers.get('X-Internal-Secret');
    const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

    if (internalSecret && internalSecret === expectedSecret) {
      organizationId = request.headers.get('X-Organization-Id') || undefined;
      userId = 'copilot-system';
    } else {
      const session = await getServerSession(authOptions);
      if (!session?.user) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
      }
      organizationId = (session.user as any).organizationId;
      userId = (session.user as any).id;
    }

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const {
      name,
      taskMode,
      prompt,
      description,
      monitorType,
      targetFqn,
      config,
      schedule,
      timezone = 'UTC',
      alertChannels = [],
      alertConfig,
      alertOnStatus = ['FAIL', 'WARN', 'ERROR'],
      integrationId,
    } = body;

    if (!name || !schedule) {
      return NextResponse.json(
        { error: 'name and schedule are required' },
        { status: 400 }
      );
    }

    // Compute next run time from cron expression
    const nextRunAt = computeNextRun(schedule, timezone);

    // For infrastructure monitors, the integrationId is a PipelineNode ID — store in config.
    // For tool monitors, store integrationId as toolNodeId in config.
    // For other monitors, validate integrationId is a real Integration before using as FK.
    const isInfraMonitor = ['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS'].includes(monitorType);
    const TOOL_MONITOR_KINDS = [
      'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
      'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
      'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
    ];
    const isToolMonitor = TOOL_MONITOR_KINDS.includes(monitorType);

    let validIntegrationId: string | undefined;
    if (integrationId && !isInfraMonitor && !isToolMonitor) {
      const integration = await prisma.integration.findUnique({
        where: { id: integrationId },
        select: { id: true },
      });
      if (integration) {
        validIntegrationId = integrationId;
      } else {
        console.warn(`[Schedule] integrationId ${integrationId} is not a valid Integration — storing in config`);
      }
    }

    // Build config with the appropriate node ID key
    let taskConfig = config || {};
    if (isInfraMonitor && integrationId) {
      taskConfig = { ...taskConfig, serverNodeId: integrationId };
    } else if (isToolMonitor && integrationId) {
      taskConfig = { ...taskConfig, toolNodeId: integrationId };
    } else if (!validIntegrationId && integrationId) {
      taskConfig = { ...taskConfig, nodeId: integrationId };
    }

    const task = await prisma.monitor.create({
      data: {
        name,
        taskMode,
        prompt,
        description,
        monitorType: monitorType || null,
        targetFqn: targetFqn || null,
        config: Object.keys(taskConfig).length > 0 ? taskConfig : undefined,
        schedule,
        timezone,
        enabled: true,
        alertChannels,
        alertConfig: alertConfig || undefined,
        alertOnStatus,
        nextRunAt,
        createdBy: userId,
        source: 'pallisade',
        organizationId,
        ...(validIntegrationId ? { integrationId: validIntegrationId } : {}),
      },
    });

    return NextResponse.json({ task }, { status: 201 });
  } catch (error: any) {
    console.error('[Schedule] Create task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
