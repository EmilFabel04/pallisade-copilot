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
