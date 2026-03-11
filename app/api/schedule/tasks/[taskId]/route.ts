import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { computeNextRun } from '@/lib/cron';

// GET /api/schedule/tasks/[taskId] - Get task detail
export async function GET(
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
      include: {
        integration: {
          select: { id: true, name: true, type: true },
        },
        runs: {
          orderBy: { startedAt: 'desc' },
          take: 10,
        },
      },
    });

    if (!task) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    return NextResponse.json({ task });
  } catch (error: any) {
    console.error('[Schedule] Get task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PATCH /api/schedule/tasks/[taskId] - Update task
export async function PATCH(
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
    const body = await request.json();

    // Verify task belongs to org
    const existing = await prisma.monitor.findFirst({
      where: { id: taskId, organizationId },
    });

    if (!existing) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    const allowedFields = [
      'name', 'taskMode', 'prompt', 'description', 'monitorType',
      'targetFqn', 'config', 'schedule', 'timezone', 'enabled',
      'alertChannels', 'alertConfig', 'alertOnStatus', 'integrationId',
    ];

    const data: any = {};
    for (const field of allowedFields) {
      if (body[field] !== undefined) {
        data[field] = body[field];
      }
    }

    // Recompute nextRunAt when schedule or timezone changes
    if (data.schedule || data.timezone) {
      const cronExpr = data.schedule || existing.schedule;
      const tz = data.timezone || existing.timezone || 'UTC';
      if (cronExpr) {
        data.nextRunAt = computeNextRun(cronExpr, tz);
      }
    }

    const task = await prisma.monitor.update({
      where: { id: taskId },
      data,
    });

    return NextResponse.json({ task });
  } catch (error: any) {
    console.error('[Schedule] Update task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// DELETE /api/schedule/tasks/[taskId] - Delete task
export async function DELETE(
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

    const existing = await prisma.monitor.findFirst({
      where: { id: taskId, organizationId },
    });

    if (!existing) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    await prisma.monitor.delete({ where: { id: taskId } });

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('[Schedule] Delete task error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
