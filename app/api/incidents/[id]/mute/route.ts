import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const { until, reason } = body as { until?: string; reason?: string };

  if (!until) return NextResponse.json({ error: 'until (ISO8601) required' }, { status: 400 });
  const untilDate = new Date(until);
  if (isNaN(untilDate.getTime()) || untilDate.getTime() <= Date.now()) {
    return NextResponse.json({ error: 'until must be a future ISO8601 timestamp' }, { status: 400 });
  }

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (incident.status === 'RESOLVED') return NextResponse.json({ error: 'Cannot mute a resolved incident' }, { status: 400 });

  const updated = await prisma.incident.update({
    where: { id },
    data: {
      mutedUntil: untilDate,
      mutedBy: (session.user as any).id ?? session.user.email,
      mutedReason: reason ?? null,
    },
  });
  return NextResponse.json({ incident: updated });
}
