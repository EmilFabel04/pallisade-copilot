import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/artifacts/[artifactId] - Get single artifact
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ artifactId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
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
        sourceSession: {
          select: {
            id: true,
            title: true,
          },
        },
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
  { params }: { params: Promise<{ artifactId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
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

    const body = await request.json();
    const { title, tags, isPinned, type, content } = body;

    const updateData: any = {};
    if (title !== undefined) updateData.title = title;
    if (tags !== undefined) updateData.tags = tags;
    if (isPinned !== undefined) updateData.isPinned = isPinned;
    if (type !== undefined) updateData.type = type;
    if (content !== undefined) updateData.content = content;

    const artifact = await prisma.artifact.update({
      where: { id: artifactId },
      data: updateData,
      include: {
        sourceSession: {
          select: {
            id: true,
            title: true,
          },
        },
      },
    });

    return NextResponse.json({ artifact });
  } catch (error) {
    console.error('[ARTIFACTS] Error updating artifact:', error);
    return NextResponse.json(
      { error: 'Failed to update artifact' },
      { status: 500 }
    );
  }
}

// DELETE /api/artifacts/[artifactId] - Delete artifact
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ artifactId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
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
