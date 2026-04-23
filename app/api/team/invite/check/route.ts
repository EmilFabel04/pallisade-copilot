import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token');
  if (!token) {
    return NextResponse.json({ error: 'Token required' }, { status: 400 });
  }

  const invite = await prisma.teamInvite.findUnique({
    where: { token },
    include: {
      organization: {
        select: { authPolicy: true },
      },
    },
  });

  if (!invite || invite.status !== 'PENDING') {
    return NextResponse.json({ error: 'Invalid invite' }, { status: 404 });
  }

  return NextResponse.json({
    authPolicy: invite.organization.authPolicy,
  });
}
