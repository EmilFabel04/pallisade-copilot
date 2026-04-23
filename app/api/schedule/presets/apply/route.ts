import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { createWatchInTransaction, type CreateWatchParams } from '@/lib/watch-helpers';

// POST /api/schedule/presets/apply - Create all watches for a preset in one transaction
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
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
      presetKey,
      watches = [],
      schedule,
      timezone = 'UTC',
      alertChannels = [],
      alertOnStatus = ['FAIL', 'WARN', 'ERROR'],
    } = body;

    if (!presetKey) {
      return NextResponse.json({ error: 'presetKey is required' }, { status: 400 });
    }
    if (!watches.length) {
      return NextResponse.json({ error: 'At least one watch is required' }, { status: 400 });
    }

    // Generate shared preset group ID
    const presetGroupId = crypto.randomUUID();

    const result = await prisma.$transaction(async (tx) => {
      const createdWatches = [];

      for (const watch of watches) {
        if (!watch.monitors?.length) continue;

        const params: CreateWatchParams = {
          name: watch.name || `${presetKey}: ${watch.anchorName || 'Watch'}`,
          description: watch.description,
          watchType: watch.watchType,
          anchorFqn: watch.anchorFqn,
          anchorNodeId: watch.anchorNodeId,
          anchorNodeType: watch.anchorNodeType,
          anchorPlatform: watch.anchorPlatform,
          scopeConfig: watch.scopeConfig,
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
          presetGroupId,
          presetKey,
          monitors: watch.monitors,
          organizationId,
          userId,
        };

        const watchResult = await createWatchInTransaction(tx, params);
        createdWatches.push({
          id: watchResult.group.id,
          name: watchResult.group.name,
          watchType: watchResult.group.watchType,
          anchorFqn: watchResult.group.anchorFqn,
          monitorCount: watchResult.monitors.length,
        });
      }

      return createdWatches;
    }, { maxWait: 15000, timeout: 60000 });

    return NextResponse.json(
      {
        presetGroupId,
        presetKey,
        watches: result,
        totalWatches: result.length,
        totalMonitors: result.reduce((sum, w) => sum + w.monitorCount, 0),
      },
      { status: 201 },
    );
  } catch (error: any) {
    console.error('[Presets] Apply error:', error?.message || error, error?.stack);
    return NextResponse.json({ error: error?.message || String(error) }, { status: 500 });
  }
}
