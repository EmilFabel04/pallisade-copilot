import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function PATCH(request: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const body = await request.json();
  const { name, timezone, role } = body;

  const data: Record<string, any> = {};
  if (name !== undefined) data.name = name;
  if (timezone !== undefined) data.timezone = timezone;
  if (role !== undefined) data.role = role;

  const user = await prisma.user.update({
    where: { id: (session.user as any).id },
    data,
    select: { id: true, name: true, timezone: true, role: true },
  });

  return NextResponse.json({ user });
}
