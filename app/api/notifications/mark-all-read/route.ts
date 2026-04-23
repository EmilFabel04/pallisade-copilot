import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// POST /api/notifications/mark-all-read — mark all org notifications as read for user
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

    const body = await request.json().catch(() => ({}));
    const { pipelineStackId } = body as { pipelineStackId?: string };

    // Find all unread notification IDs for this user's org
    const where: any = {
      organizationId: user.organizationId,
      reads: { none: { userId: user.id } },
    };
    if (pipelineStackId) where.pipelineStackId = pipelineStackId;

    const unread = await prisma.notificationEvent.findMany({
      where,
      select: { id: true },
      take: 1000, // cap to prevent huge batch
    });

    if (unread.length > 0) {
      await prisma.notificationRead.createMany({
        data: unread.map((n) => ({
          userId: user.id,
          notificationEventId: n.id,
        })),
        skipDuplicates: true,
      });
    }

    return NextResponse.json({ marked: unread.length });
  } catch (error) {
    console.error('Failed to mark all notifications as read:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
