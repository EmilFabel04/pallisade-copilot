import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/notifications — list notifications for the user's org with cursor pagination
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ notifications: [], nextCursor: null });
    }

    const params = request.nextUrl.searchParams;
    const severity = params.get('severity');
    const eventType = params.get('eventType');
    const pipelineStackId = params.get('pipelineStackId');
    const unreadOnly = params.get('unreadOnly') === 'true';
    const cursor = params.get('cursor'); // ISO datetime
    const cursorId = params.get('cursorId');
    const limit = Math.min(parseInt(params.get('limit') || '25', 10), 100);

    // Build where clause
    const where: any = { organizationId: user.organizationId };

    if (severity) where.severity = severity;
    if (eventType) where.eventType = { startsWith: eventType };
    if (pipelineStackId) where.pipelineStackId = pipelineStackId;
    if (unreadOnly) {
      where.reads = { none: { userId: user.id } };
    }

    // Cursor pagination: get items older than cursor
    if (cursor) {
      where.OR = [
        { createdAt: { lt: new Date(cursor) } },
        ...(cursorId
          ? [{ createdAt: new Date(cursor), id: { lt: cursorId } }]
          : []),
      ];
    }

    const events = await prisma.notificationEvent.findMany({
      where,
      orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
      take: limit + 1, // fetch one extra to detect hasMore
      include: {
        reads: { where: { userId: user.id }, select: { readAt: true } },
        actorUser: { select: { name: true, email: true, image: true } },
      },
    });

    const hasMore = events.length > limit;
    const page = hasMore ? events.slice(0, limit) : events;

    const notifications = page.map((e) => ({
      id: e.id,
      eventType: e.eventType,
      severity: e.severity,
      title: e.title,
      message: e.message,
      entityType: e.entityType,
      entityId: e.entityId,
      actionUrl: e.actionUrl,
      metadata: e.metadata,
      pipelineStackId: e.pipelineStackId,
      createdAt: e.createdAt.toISOString(),
      isRead: e.reads.length > 0,
      readAt: e.reads[0]?.readAt?.toISOString() || null,
      actor: e.actorUser
        ? { name: e.actorUser.name, email: e.actorUser.email, image: e.actorUser.image }
        : null,
    }));

    const last = page[page.length - 1];
    return NextResponse.json({
      notifications,
      nextCursor: hasMore && last ? last.createdAt.toISOString() : null,
      nextCursorId: hasMore && last ? last.id : null,
    });
  } catch (error) {
    console.error('Failed to fetch notifications:', error);
    return NextResponse.json({ notifications: [], nextCursor: null, nextCursorId: null });
  }
}
