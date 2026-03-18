import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// PUT /api/schedule/watches/[watchId]/monitors/[monitorId]
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string; monitorId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { watchId, monitorId } = await params;

    // Verify monitor belongs to this watch and org
    const monitor = await prisma.monitor.findFirst({
      where: {
        id: monitorId,
        monitorGroupId: watchId,
        organizationId,
      },
    });

    if (!monitor) {
      return NextResponse.json(
        { error: 'Monitor not found in this watch' },
        { status: 404 },
      );
    }

    const body = await request.json();
    const { config, policyOverrides } = body;

    const updateData: Record<string, any> = {};

    if (config !== undefined) {
      updateData.config = config;
    }

    // Store policyOverrides if the column exists (requires migration)
    if (policyOverrides !== undefined) {
      if (
        !Array.isArray(policyOverrides) ||
        !policyOverrides.every((k: any) => typeof k === 'string')
      ) {
        return NextResponse.json(
          { error: 'policyOverrides must be an array of strings' },
          { status: 400 },
        );
      }
      updateData.policyOverrides = policyOverrides;
    }

    // Try update — if policyOverrides column doesn't exist yet, retry without it
    let updated;
    try {
      updated = await prisma.monitor.update({
        where: { id: monitorId },
        data: updateData,
      });
    } catch (err: any) {
      if (updateData.policyOverrides !== undefined && err?.message?.includes('policyOverrides')) {
        delete updateData.policyOverrides;
        updated = await prisma.monitor.update({
          where: { id: monitorId },
          data: updateData,
        });
      } else {
        throw err;
      }
    }

    return NextResponse.json({ monitor: updated });
  } catch (error: any) {
    console.error('[Monitors] Update error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
