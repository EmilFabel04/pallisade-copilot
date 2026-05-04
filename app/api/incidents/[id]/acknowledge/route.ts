import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (incident.status !== 'OPEN') return NextResponse.json({ error: 'Only OPEN incidents can be acknowledged' }, { status: 400 });

  const updated = await prisma.incident.update({
    where: { id },
    data: {
      status: 'ACKNOWLEDGED',
      acknowledgedAt: new Date(),
      acknowledgedBy: (session.user as any).id ?? session.user.email,
    },
  });
  return NextResponse.json({ incident: updated });
}
