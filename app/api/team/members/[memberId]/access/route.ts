/**
 * Team Member Pipeline Access API
 * 
 * GET - Get a member's pipeline access
 * POST - Update a member's pipeline access (admin only)
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET - Get member's pipeline access
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ memberId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { memberId } = await params;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Get the team member
    const teamMember = await prisma.teamMember.findUnique({
      where: { id: memberId },
      include: { user: true },
    });

    if (!teamMember || teamMember.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Member not found' }, { status: 404 });
    }

    // Get pipeline access for this user
    const access = await prisma.pipelineAccess.findMany({
      where: { userId: teamMember.userId },
      include: {
        pipeline: {
          select: { id: true, name: true, status: true },
        },
      },
    });

    return NextResponse.json({
      access: access.map(a => ({
        id: a.id,
        pipelineId: a.pipelineId,
        pipelineName: a.pipeline.name,
        pipelineStatus: a.pipeline.status,
        accessLevel: a.accessLevel,
        tokensUsed: a.tokensUsed,
        grantedAt: a.grantedAt,
      })),
    });

  } catch (error) {
    console.error('Failed to fetch member access:', error);
    return NextResponse.json(
      { error: 'Failed to fetch member access' },
      { status: 500 }
    );
  }
}

// POST - Update member's pipeline access (bulk update)
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ memberId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { memberId } = await params;
    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if current user is admin
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId: currentUserId,
          organizationId,
        },
      },
    });

    if (!currentMember || (currentMember.role !== 'OWNER' && currentMember.role !== 'ADMIN')) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    // Get the team member to update
    const teamMember = await prisma.teamMember.findUnique({
      where: { id: memberId },
    });

    if (!teamMember || teamMember.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Member not found' }, { status: 404 });
    }

    const body = await request.json();
    const { pipelineAccess } = body; // Array of { pipelineId, accessLevel }

    if (!Array.isArray(pipelineAccess)) {
      return NextResponse.json({ error: 'pipelineAccess must be an array' }, { status: 400 });
    }

    // Get current access to determine what to delete
    const currentAccess = await prisma.pipelineAccess.findMany({
      where: { userId: teamMember.userId },
    });
    const currentPipelineIds = currentAccess.map(a => a.pipelineId);
    const newPipelineIds = pipelineAccess.map((a: any) => a.pipelineId);

    // Delete access for pipelines not in new list
    const toDelete = currentPipelineIds.filter(id => !newPipelineIds.includes(id));
    if (toDelete.length > 0) {
      await prisma.pipelineAccess.deleteMany({
        where: {
          userId: teamMember.userId,
          pipelineId: { in: toDelete },
        },
      });
    }

    // Upsert access for each pipeline
    for (const access of pipelineAccess) {
      if (!access.pipelineId || !access.accessLevel) continue;

      await prisma.pipelineAccess.upsert({
        where: {
          userId_pipelineId: {
            userId: teamMember.userId,
            pipelineId: access.pipelineId,
          },
        },
        create: {
          userId: teamMember.userId,
          pipelineId: access.pipelineId,
          accessLevel: access.accessLevel,
          grantedBy: currentUserId,
        },
        update: {
          accessLevel: access.accessLevel,
          grantedBy: currentUserId,
          grantedAt: new Date(),
        },
      });
    }

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Failed to update member access:', error);
    return NextResponse.json(
      { error: 'Failed to update member access' },
      { status: 500 }
    );
  }
}
