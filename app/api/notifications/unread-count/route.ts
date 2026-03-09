import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/notifications/unread-count — get unread notification count for user
export async function GET() {
  try {
    const session = await getServerSession(authOptions);
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

    const count = await prisma.notificationEvent.count({
      where: {
        organizationId: user.organizationId,
        reads: { none: { userId: user.id } },
      },
    });

    return NextResponse.json({ count });
  } catch (error) {
    console.error('Failed to get unread count:', error);
    return NextResponse.json({ count: 0 });
  }
}
