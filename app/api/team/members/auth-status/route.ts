import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const orgId = (session.user as any).organizationId;
  if (!orgId) {
    return NextResponse.json({ members: [] });
  }

  const teamMembers = await prisma.teamMember.findMany({
    where: { organizationId: orgId, status: 'ACTIVE' },
    include: {
      user: {
        select: {
          id: true,
          email: true,
          name: true,
          passwordHash: true,
          accounts: {
            select: { provider: true },
          },
        },
      },
    },
  });

  const members = teamMembers.map((tm) => ({
    id: tm.id,
    name: tm.user.name,
    email: tm.user.email,
    role: tm.role,
    providers: tm.user.accounts.map((a) => a.provider),
    hasPassword: !!tm.user.passwordHash,
  }));

  return NextResponse.json({ members });
}
