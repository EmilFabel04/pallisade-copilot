/**
 * Pipeline Stack Settings API
 * 
 * PATCH - Update pipeline name, description, token limits
 * DELETE - Delete a pipeline stack
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// Helper to check if user has access to pipeline
async function checkPipelineAccess(
  userId: string,
  organizationId: string,
  pipelineId: string,
  requiredLevel: 'VIEWER' | 'EDITOR' | 'OWNER' = 'VIEWER'
) {
  // First check if pipeline belongs to user's organization
  const pipeline = await prisma.pipelineStack.findUnique({
    where: { id: pipelineId },
    include: {
      accessList: {
        where: { userId },
      },
    },
  });

  if (!pipeline) {
    return { allowed: false, error: 'Pipeline not found', status: 404 };
  }

  if (pipeline.organizationId !== organizationId) {
    return { allowed: false, error: 'Forbidden', status: 403 };
  }

  // Check user's role in organization
  const teamMember = await prisma.teamMember.findUnique({
    where: {
      userId_organizationId: {
        userId,
        organizationId,
      },
    },
  });

  // Owners and Admins have full access to all pipelines in org
  if (teamMember?.role === 'OWNER' || teamMember?.role === 'ADMIN') {
    return { allowed: true, pipeline, role: teamMember.role, isOrgAdmin: true };
  }

  // Check pipeline-specific access
  const access = pipeline.accessList[0];
  
  if (!access) {
    // No specific access and not an admin - check if creator
    if (pipeline.createdById === userId) {
      return { allowed: true, pipeline, role: 'OWNER', isOrgAdmin: false };
    }
    return { allowed: false, error: 'Access denied', status: 403 };
  }

  const levelHierarchy = { VIEWER: 1, EDITOR: 2, OWNER: 3 };
  const hasAccess = levelHierarchy[access.accessLevel] >= levelHierarchy[requiredLevel];

  if (!hasAccess) {
    return { allowed: false, error: 'Insufficient permissions', status: 403 };
  }

  return { allowed: true, pipeline, role: access.accessLevel, isOrgAdmin: false };
}

// PATCH - Update pipeline settings
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;
    const userId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check access (need EDITOR level to update)
    const accessCheck = await checkPipelineAccess(userId, organizationId, stackId, 'EDITOR');
    if (!accessCheck.allowed) {
      return NextResponse.json(
        { error: accessCheck.error },
        { status: accessCheck.status }
      );
    }

    const body = await request.json();
    const { name, description, tokenLimitMonthly } = body;

    // Only org admins can change token limits
    if (tokenLimitMonthly !== undefined && !accessCheck.isOrgAdmin) {
      return NextResponse.json(
        { error: 'Only admins can modify token limits' },
        { status: 403 }
      );
    }

    const updateData: any = {};
    if (name !== undefined) updateData.name = name;
    if (description !== undefined) updateData.description = description;
    if (tokenLimitMonthly !== undefined) updateData.tokenLimitMonthly = tokenLimitMonthly;

    const updated = await prisma.pipelineStack.update({
      where: { id: stackId },
      data: updateData,
      select: {
        id: true,
        name: true,
        description: true,
        status: true,
        tokenLimitMonthly: true,
        tokensUsedThisMonth: true,
        updatedAt: true,
      },
    });

    return NextResponse.json({ pipeline: updated });

  } catch (error) {
    console.error('Failed to update pipeline:', error);
    return NextResponse.json(
      { error: 'Failed to update pipeline' },
      { status: 500 }
    );
  }
}

// DELETE - Delete a pipeline
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;
    const userId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check access (need OWNER level to delete)
    const accessCheck = await checkPipelineAccess(userId, organizationId, stackId, 'OWNER');
    if (!accessCheck.allowed) {
      return NextResponse.json(
        { error: accessCheck.error },
        { status: accessCheck.status }
      );
    }

    // Delete the pipeline (cascades to nodes, edges, etc.)
    await prisma.pipelineStack.delete({
      where: { id: stackId },
    });

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Failed to delete pipeline:', error);
    return NextResponse.json(
      { error: 'Failed to delete pipeline' },
      { status: 500 }
    );
  }
}

// GET - Get pipeline details with access info
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;
    const userId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check basic access
    const accessCheck = await checkPipelineAccess(userId, organizationId, stackId, 'VIEWER');
    if (!accessCheck.allowed) {
      return NextResponse.json(
        { error: accessCheck.error },
        { status: accessCheck.status }
      );
    }

    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      include: {
        nodes: true,
        edges: true,
        accessList: accessCheck.isOrgAdmin ? {
          include: {
            // We need user info - fetch separately
          },
        } : false,
        _count: {
          select: {
            nodes: true,
            scans: true,
          },
        },
      },
    });

    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    // Get user info for access list if admin
    let accessListWithUsers: any[] = [];
    if (accessCheck.isOrgAdmin && pipeline.accessList) {
      const userIds = pipeline.accessList.map(a => a.userId);
      const users = await prisma.user.findMany({
        where: { id: { in: userIds } },
        select: { id: true, name: true, email: true, image: true },
      });
      const userMap = new Map(users.map(u => [u.id, u]));
      
      accessListWithUsers = pipeline.accessList.map(access => ({
        ...access,
        user: userMap.get(access.userId) || null,
      }));
    }

    return NextResponse.json({
      pipeline: {
        id: pipeline.id,
        name: pipeline.name,
        description: pipeline.description,
        status: pipeline.status,
        healthScore: pipeline.healthScore,
        tokenLimitMonthly: pipeline.tokenLimitMonthly,
        tokensUsedThisMonth: pipeline.tokensUsedThisMonth,
        tokenResetDate: pipeline.tokenResetDate,
        createdAt: pipeline.createdAt,
        updatedAt: pipeline.updatedAt,
        nodeCount: pipeline._count.nodes,
        scanCount: pipeline._count.scans,
        dataContractsEnabled: pipeline.dataContractsEnabled,
      },
      accessList: accessCheck.isOrgAdmin ? accessListWithUsers : undefined,
      userRole: accessCheck.role,
      isOrgAdmin: accessCheck.isOrgAdmin,
    });

  } catch (error) {
    console.error('Failed to fetch pipeline:', error);
    return NextResponse.json(
      { error: 'Failed to fetch pipeline' },
      { status: 500 }
    );
  }
}
