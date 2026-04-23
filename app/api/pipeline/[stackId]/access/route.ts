/**
 * Pipeline Access Management API (Admin Only)
 * 
 * GET - List users with access to this pipeline
 * POST - Grant access to a user
 * DELETE - Revoke access from a user
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// Helper to check if user is org admin
async function checkOrgAdmin(userId: string, organizationId: string) {
  const teamMember = await prisma.teamMember.findUnique({
    where: {
      userId_organizationId: {
        userId,
        organizationId,
      },
    },
  });

  return teamMember?.role === 'OWNER' || teamMember?.role === 'ADMIN';
}

// GET - List users with access
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

    // Check if admin
    const isAdmin = await checkOrgAdmin(userId, organizationId);
    if (!isAdmin) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    // Verify pipeline belongs to org
    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      select: { organizationId: true, name: true },
    });

    if (!pipeline || pipeline.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    // Get access list with user details
    const accessList = await prisma.pipelineAccess.findMany({
      where: { pipelineId: stackId },
      orderBy: { grantedAt: 'desc' },
    });

    // Get user details
    const userIds = accessList.map(a => a.userId);
    const users = await prisma.user.findMany({
      where: { id: { in: userIds } },
      select: { id: true, name: true, email: true, image: true },
    });
    const userMap = new Map(users.map(u => [u.id, u]));

    // Get all team members for adding new users
    const teamMembers = await prisma.teamMember.findMany({
      where: { 
        organizationId,
        status: 'ACTIVE',
      },
      include: {
        user: {
          select: { id: true, name: true, email: true, image: true },
        },
      },
    });

    // Filter out users who already have access
    const existingUserIds = new Set(userIds);
    const availableUsers = teamMembers
      .filter(tm => !existingUserIds.has(tm.userId))
      .map(tm => ({
        id: tm.user.id,
        name: tm.user.name,
        email: tm.user.email,
        image: tm.user.image,
        role: tm.role,
      }));

    return NextResponse.json({
      accessList: accessList.map(access => ({
        id: access.id,
        userId: access.userId,
        accessLevel: access.accessLevel,
        tokensUsed: access.tokensUsed,
        grantedAt: access.grantedAt,
        user: userMap.get(access.userId) || null,
      })),
      availableUsers,
    });

  } catch (error) {
    console.error('Failed to fetch access list:', error);
    return NextResponse.json(
      { error: 'Failed to fetch access list' },
      { status: 500 }
    );
  }
}

// POST - Grant access to a user
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;
    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if admin
    const isAdmin = await checkOrgAdmin(currentUserId, organizationId);
    if (!isAdmin) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    // Verify pipeline belongs to org
    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      select: { organizationId: true },
    });

    if (!pipeline || pipeline.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    const body = await request.json();
    const { userId, accessLevel = 'VIEWER' } = body;

    if (!userId) {
      return NextResponse.json({ error: 'userId is required' }, { status: 400 });
    }

    // Verify user is in the organization
    const targetMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId,
          organizationId,
        },
      },
    });

    if (!targetMember) {
      return NextResponse.json(
        { error: 'User is not a member of this organization' },
        { status: 400 }
      );
    }

    // Create or update access
    const access = await prisma.pipelineAccess.upsert({
      where: {
        userId_pipelineId: {
          userId,
          pipelineId: stackId,
        },
      },
      create: {
        userId,
        pipelineId: stackId,
        accessLevel,
        grantedBy: currentUserId,
      },
      update: {
        accessLevel,
        grantedBy: currentUserId,
        grantedAt: new Date(),
      },
    });

    // Get user details
    const user = await prisma.user.findUnique({
      where: { id: userId },
      select: { id: true, name: true, email: true, image: true },
    });

    return NextResponse.json({
      access: {
        ...access,
        user,
      },
    });

  } catch (error) {
    console.error('Failed to grant access:', error);
    return NextResponse.json(
      { error: 'Failed to grant access' },
      { status: 500 }
    );
  }
}

// DELETE - Revoke access from a user
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
    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if admin
    const isAdmin = await checkOrgAdmin(currentUserId, organizationId);
    if (!isAdmin) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    const { searchParams } = new URL(request.url);
    const userId = searchParams.get('userId');

    if (!userId) {
      return NextResponse.json({ error: 'userId is required' }, { status: 400 });
    }

    // Verify pipeline belongs to org
    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      select: { organizationId: true },
    });

    if (!pipeline || pipeline.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    // Delete access
    await prisma.pipelineAccess.deleteMany({
      where: {
        userId,
        pipelineId: stackId,
      },
    });

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Failed to revoke access:', error);
    return NextResponse.json(
      { error: 'Failed to revoke access' },
      { status: 500 }
    );
  }
}
