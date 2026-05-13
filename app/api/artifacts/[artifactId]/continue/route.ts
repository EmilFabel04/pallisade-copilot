import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

/**
 * Returns the artefact's agentSessionId so the frontend can route to
 * /dashboard/artifacts/[id] and reconnect to that session. Streaming and
 * turn-loop rehydration are wired in the frontend plan.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ artifactId: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const userId = (session.user as any).id;
  const organizationId = (session.user as any).organizationId;
  const { artifactId } = await params;

  const artefact = await prisma.artifact.findFirst({
    where: { id: artifactId, organizationId, userId },
    include: { agentSession: { select: { id: true, title: true } } },
  });
  if (!artefact) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (!artefact.agentSessionId) {
    return NextResponse.json({ error: 'Artefact has no agent session' }, { status: 409 });
  }

  return NextResponse.json({
    artefactId: artefact.id,
    agentSessionId: artefact.agentSessionId,
    sessionTitle: artefact.agentSession?.title,
    kind: artefact.kind,
    status: artefact.status,
  });
}
