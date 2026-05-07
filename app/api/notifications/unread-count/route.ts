import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// GET /api/notifications/unread-count — unread count for the active user.
// Optionally scoped to ?pipelineStackId so the header badge in pipeline-aware
// pages doesn't tally events from other profiles.
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ count: 0 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ count: 0 });
    }

    // Fetch user's mute rules to exclude muted notifications (graceful fallback)
    let muteExclusions: any[] = [];
    try {
      const mutes = await prisma.notificationMute.findMany({
        where: {
          organizationId: user.organizationId,
          userId: user.id,
        },
      });
      muteExclusions = mutes.map((m) => ({
        AND: [
          { eventType: m.eventType },
          ...(m.entityType ? [{ entityType: m.entityType }] : []),
          ...(m.entityId ? [{ entityId: m.entityId }] : []),
        ],
      }));
    } catch (err) {
      console.warn('[Notifications] Mute query failed, skipping mute filter:', err);
    }

    const pipelineStackId = new URL(request.url).searchParams.get('pipelineStackId');

    const count = await prisma.notificationEvent.count({
      where: {
        organizationId: user.organizationId,
        ...(pipelineStackId ? { pipelineStackId } : {}),
        reads: { none: { userId: user.id } },
        ...(muteExclusions.length > 0 ? { NOT: { OR: muteExclusions } } : {}),
      },
    });

    return NextResponse.json({ count });
  } catch (error) {
    console.error('Failed to get unread count:', error);
    return NextResponse.json({ count: 0 });
  }
}
