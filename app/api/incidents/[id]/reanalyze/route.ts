import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { diagnoseIncident } from '@/lib/incidents/diagnose';

// POST /api/incidents/[id]/reanalyze — kick off a fresh LLM diagnosis.
// The scanner LLM call typically takes 10-30s; running it inline blocked the
// request handler and the user's UI for that long, encouraging repeat
// clicks. Now we fire-and-forget: queue the work and return 202 Accepted
// immediately. The frontend polls /api/incidents to pick up the new
// llmHypothesis when it lands.
export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  void diagnoseIncident(id, prisma).catch((err) => {
    console.error('[reanalyze] diagnose failed', { incidentId: id, err });
  });

  return NextResponse.json({ incident, status: 'queued' }, { status: 202 });
}
