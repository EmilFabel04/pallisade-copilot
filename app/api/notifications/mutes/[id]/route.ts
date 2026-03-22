import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// DELETE /api/notifications/mutes/[id] — remove a mute rule
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true },
    });
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { id } = await params;

    const mute = await prisma.notificationMute.findFirst({
      where: { id, userId: user.id },
    });
    if (!mute) {
      return NextResponse.json({ error: 'Mute rule not found' }, { status: 404 });
    }

    await prisma.notificationMute.delete({ where: { id } });

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('[NotificationMute] DELETE error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
