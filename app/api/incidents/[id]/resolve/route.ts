import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const VALID = ['FIXED', 'EXPECTED', 'FALSE_POSITIVE', 'WONT_FIX'] as const;

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const { reason, note } = body as { reason?: string; note?: string };

  if (!reason || !VALID.includes(reason as any)) {
    return NextResponse.json({ error: `reason must be one of ${VALID.join(', ')}` }, { status: 400 });
  }

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (incident.status === 'RESOLVED') return NextResponse.json({ incident }, { status: 200 });

  const updated = await prisma.incident.update({
    where: { id },
    data: {
      status: 'RESOLVED',
      resolvedAt: new Date(),
      resolvedBy: (session.user as any).id ?? session.user.email,
      resolutionType: reason as any,
      resolutionNote: note ?? null,
    },
  });
  return NextResponse.json({ incident: updated });
}
