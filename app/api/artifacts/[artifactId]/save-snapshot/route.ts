import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

/**
 * Marks an artefact as user-saved (isSaved=true). Idempotent — calling on an
 * already-saved artefact is a no-op. Used by the chat-side "Save to artefacts"
 * button to promote a draft artefact onto the /artefacts page.
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

  const existing = await prisma.artifact.findFirst({
    where: { id: artifactId, organizationId, userId },
  });
  if (!existing) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  if (existing.isSaved) {
    return NextResponse.json(existing, { status: 200 });
  }

  const updated = await prisma.artifact.update({
    where: { id: artifactId },
    data: { isSaved: true },
  });
  return NextResponse.json(updated, { status: 200 });
}
