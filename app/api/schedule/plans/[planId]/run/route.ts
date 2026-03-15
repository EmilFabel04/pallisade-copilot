import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// POST /api/schedule/plans/[planId]/run - Trigger run for all child groups
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { planId } = await params;

    const plan = await prisma.monitoringPlan.findFirst({
      where: { id: planId, organizationId },
      include: {
        monitorGroups: {
          where: { enabled: true },
          select: { id: true, name: true },
        },
      },
    });

    if (!plan) {
      return NextResponse.json({ error: 'Plan not found' }, { status: 404 });
    }

    if (!plan.monitorGroups.length) {
      return NextResponse.json(
        { error: 'No enabled monitor groups in this plan' },
        { status: 400 },
      );
    }

    // Fan-out: trigger run for each child group
    // Each group's monitors are enqueued via the existing group run endpoint
    const SCANNER_URL = process.env.SCANNER_URL || 'http://localhost:8000';
    const results = [];

    for (const group of plan.monitorGroups) {
      try {
        const res = await fetch(
          `${SCANNER_URL}/api/v1/monitors/groups/${group.id}/run`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ organization_id: organizationId }),
          },
        );
        results.push({
          groupId: group.id,
          groupName: group.name,
          status: res.ok ? 'triggered' : 'failed',
          statusCode: res.status,
        });
      } catch (err: any) {
        results.push({
          groupId: group.id,
          groupName: group.name,
          status: 'error',
          error: err.message,
        });
      }
    }

    return NextResponse.json({
      planId: plan.id,
      groupsTriggered: results.filter((r) => r.status === 'triggered').length,
      groupsFailed: results.filter((r) => r.status !== 'triggered').length,
      results,
    });
  } catch (error: any) {
    console.error('[Plans] Run error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
