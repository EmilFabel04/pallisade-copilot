import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// POST /api/notifications/mutes — create a mute rule
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
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { eventType, entityType, entityId } = await request.json();
    if (!eventType) {
      return NextResponse.json({ error: 'eventType is required' }, { status: 400 });
    }

    const mute = await prisma.notificationMute.create({
      data: {
        organizationId: user.organizationId,
        userId: user.id,
        eventType,
        entityType: entityType || null,
        entityId: entityId || null,
      },
    });

    return NextResponse.json({ mute });
  } catch (error: any) {
    console.error('[NotificationMute] POST error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// GET /api/notifications/mutes — list active mutes for current user
export async function GET(request: NextRequest) {
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
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const mutes = await prisma.notificationMute.findMany({
      where: {
        organizationId: user.organizationId,
        userId: user.id,
      },
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({ mutes });
  } catch (error: any) {
    console.error('[NotificationMute] GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
