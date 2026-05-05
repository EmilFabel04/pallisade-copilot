import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { diagnoseIncident } from '@/lib/incidents/diagnose';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  await diagnoseIncident(id, prisma);
  const refreshed = await prisma.incident.findUnique({ where: { id } });
  return NextResponse.json({ incident: refreshed });
}
