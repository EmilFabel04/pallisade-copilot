import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/schedule/tasks/[taskId]/runs - Get run history
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

    // Verify task belongs to org
    const task = await prisma.monitor.findFirst({
      where: { id: taskId, organizationId },
      select: { id: true },
    });

    if (!task) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '25', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);

    const [runs, total] = await Promise.all([
      prisma.monitorRun.findMany({
        where: { monitorId: taskId },
        orderBy: { startedAt: 'desc' },
        take: limit,
        skip: offset,
      }),
      prisma.monitorRun.count({ where: { monitorId: taskId } }),
    ]);

    return NextResponse.json({
      runs,
      pagination: { total, limit, offset },
    });
  } catch (error: any) {
    console.error('[Schedule] Get runs error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
