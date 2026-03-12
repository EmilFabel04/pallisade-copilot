import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// POST /api/schedule/bundles/[groupId]/run - Run all monitors in the bundle
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ groupId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { groupId } = await params;
    const organizationId = (session.user as any).organizationId;

    const group = await prisma.monitorGroup.findFirst({
      where: { id: groupId, organizationId },
      include: {
        monitors: {
          where: { enabled: true },
          select: { id: true, name: true, monitorType: true, targetFqn: true },
        },
      },
    });

    if (!group) {
      return NextResponse.json({ error: 'Bundle not found' }, { status: 404 });
    }

    if (group.monitors.length === 0) {
      return NextResponse.json({ error: 'No enabled monitors in this bundle' }, { status: 400 });
    }

    // Run each monitor by calling the existing single-task run endpoint
    const baseUrl = request.nextUrl.origin;
    const cookie = request.headers.get('cookie') || '';

    const results: Array<{
      monitorId: string;
      monitorName: string;
      targetFqn: string | null;
      status: string;
      message: string | null;
    }> = [];

    for (const monitor of group.monitors) {
      try {
        const runRes = await fetch(`${baseUrl}/api/schedule/tasks/${monitor.id}/run`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Cookie: cookie,
          },
        });

        const runData = await runRes.json();
        const resultStatus = runData.result?.status || runData.run?.status || 'ERROR';
        const resultMessage = runData.result?.message || runData.run?.message || null;

        results.push({
          monitorId: monitor.id,
          monitorName: monitor.name,
          targetFqn: monitor.targetFqn,
          status: resultStatus,
          message: resultMessage,
        });
      } catch (err: any) {
        results.push({
          monitorId: monitor.id,
          monitorName: monitor.name,
          targetFqn: monitor.targetFqn,
          status: 'ERROR',
          message: `Failed to execute: ${err.message}`,
        });
      }
    }

    // Compute aggregate status: FAIL > ERROR > WARN > PASS > SKIPPED
    const statusPriority: Record<string, number> = {
      FAIL: 0, ERROR: 1, WARN: 2, PASS: 3, SKIPPED: 4,
    };
    const worstStatus = results.reduce((worst, r) => {
      const rp = statusPriority[r.status] ?? 1;
      const wp = statusPriority[worst] ?? 1;
      return rp < wp ? r.status : worst;
    }, 'PASS');

    // Update group aggregate status
    await prisma.monitorGroup.update({
      where: { id: groupId },
      data: {
        lastStatus: worstStatus as any,
        lastRunAt: new Date(),
      },
    });

    return NextResponse.json({
      groupId,
      aggregateStatus: worstStatus,
      totalMonitors: results.length,
      passCount: results.filter((r) => r.status === 'PASS').length,
      failCount: results.filter((r) => r.status === 'FAIL' || r.status === 'ERROR').length,
      warnCount: results.filter((r) => r.status === 'WARN').length,
      results,
    });
  } catch (error: any) {
    console.error('[Bundles] Run all error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
