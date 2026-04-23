import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// POST /api/notifications/mark-read — mark specific notifications as read
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    const body = await request.json();
    const { notificationIds } = body as { notificationIds: string[] };

    if (!Array.isArray(notificationIds) || notificationIds.length === 0) {
      return NextResponse.json({ error: 'notificationIds required' }, { status: 400 });
    }

    // Only mark notifications that belong to user's org
    const valid = await prisma.notificationEvent.findMany({
      where: {
        id: { in: notificationIds },
        organizationId: user.organizationId,
      },
      select: { id: true },
    });

    const validIds = valid.map((n) => n.id);

    if (validIds.length > 0) {
      await prisma.notificationRead.createMany({
        data: validIds.map((nid) => ({
          userId: user.id,
          notificationEventId: nid,
        })),
        skipDuplicates: true,
      });
    }

    return NextResponse.json({ marked: validIds.length });
  } catch (error) {
    console.error('Failed to mark notifications as read:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
