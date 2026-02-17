import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

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
      where.enabled = true;
      where.nextRunAt = { lte: new Date() };
    } else if (status === 'disabled') {
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
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const userId = (session.user as any).id;

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

    // Compute next run time
    let nextRunAt: Date | null = null;
    try {
      // Simple cron next-run computation (delegate to backend later if needed)
      nextRunAt = new Date(Date.now() + 60_000); // Default: run in 1 minute
    } catch {
      // Will be computed by the scheduler
    }

    const task = await prisma.monitor.create({
      data: {
        name,
        taskMode,
        prompt,
        description,
        monitorType: monitorType || null,
        targetFqn: targetFqn || null,
        config: config || undefined,
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
        integrationId: integrationId || undefined,
      },
    });

    return NextResponse.json({ task }, { status: 201 });
  } catch (error: any) {
    console.error('[Schedule] Create task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
