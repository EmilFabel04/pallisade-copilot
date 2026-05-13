import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { ArtifactStatus } from '@prisma/client';

// GET /api/artifacts/[artifactId] - Get single artifact
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ artifactId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const userId = (session.user as any).id;
    const organizationId = (session.user as any).organizationId;
    const { artifactId } = await params;

    const artifact = await prisma.artifact.findFirst({
      where: {
        id: artifactId,
        organizationId,
        userId,
      },
      include: {
        sourceSession: { select: { id: true, title: true } },
        agentSession: { select: { id: true, title: true } },
        integration: { select: { id: true, type: true } },
      },
    });

    if (!artifact) {
      return NextResponse.json({ error: 'Artifact not found' }, { status: 404 });
    }

    return NextResponse.json({ artifact });
  } catch (error) {
    console.error('[ARTIFACTS] Error fetching artifact:', error);
    return NextResponse.json(
      { error: 'Failed to fetch artifact' },
      { status: 500 }
    );
  }
}

// PATCH /api/artifacts/[artifactId] - Update artifact
export async function PATCH(
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

  const body = await request.json();
  const { isPinned, isSaved, status, tags, title } = body as {
    isPinned?: boolean;
    isSaved?: boolean;
    status?: ArtifactStatus;
    tags?: string[];
    title?: string;
  };

  const existing = await prisma.artifact.findFirst({
    where: { id: artifactId, organizationId, userId },
  });
  if (!existing) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  // Only allow approve/reject/archive transitions from the public route.
  const allowedTransitions: Record<string, ArtifactStatus[]> = {
    proposed: ['approved', 'rejected', 'archived'],
    approved: ['archived'],
    applied: ['archived'],
    rejected: ['archived'],
    failed: ['archived'],
    open: ['resolved', 'archived'],
    resolved: ['archived'],
  };
  if (status && !(allowedTransitions[existing.status] ?? []).includes(status)) {
    return NextResponse.json(
      { error: `Cannot transition ${existing.status} → ${status} from public route` },
      { status: 400 },
    );
  }

  const updated = await prisma.artifact.update({
    where: { id: artifactId },
    data: {
      isPinned: isPinned ?? undefined,
      isSaved: isSaved ?? undefined,
      status: status ?? undefined,
      tags: tags ?? undefined,
      title: title ?? undefined,
      appliedAt: status === 'applied' ? new Date() : undefined,
    },
  });

  return NextResponse.json(updated);
}

// DELETE /api/artifacts/[artifactId] - Delete artifact
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ artifactId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const userId = (session.user as any).id;
    const organizationId = (session.user as any).organizationId;
    const { artifactId } = await params;

    // Check artifact exists and belongs to user
    const existing = await prisma.artifact.findFirst({
      where: {
        id: artifactId,
        organizationId,
        userId,
      },
    });

    if (!existing) {
      return NextResponse.json({ error: 'Artifact not found' }, { status: 404 });
    }

    await prisma.artifact.delete({
      where: { id: artifactId },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('[ARTIFACTS] Error deleting artifact:', error);
    return NextResponse.json(
      { error: 'Failed to delete artifact' },
      { status: 500 }
    );
  }
}
