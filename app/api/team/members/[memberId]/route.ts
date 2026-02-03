/**
 * Team Member API
 * 
 * PATCH - Update a member's role
 * DELETE - Remove a member from the organization
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// PATCH - Update member role
export async function PATCH(
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

    // Get the member to update
    const member = await prisma.teamMember.findUnique({
      where: { id: memberId },
    });

    if (!member || member.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Member not found' }, { status: 404 });
    }

    // Can't edit owner
    if (member.role === 'OWNER') {
      return NextResponse.json({ error: 'Cannot modify owner role' }, { status: 403 });
    }

    // Only owner can make someone admin
    const body = await request.json();
    const { role, title, department } = body;

    if (role === 'ADMIN' && currentMember.role !== 'OWNER') {
      return NextResponse.json({ error: 'Only owners can assign admin role' }, { status: 403 });
    }

    // Can't set owner role
    if (role === 'OWNER') {
      return NextResponse.json({ error: 'Cannot assign owner role' }, { status: 403 });
    }

    // Update member
    const updated = await prisma.teamMember.update({
      where: { id: memberId },
      data: {
        ...(role ? { role } : {}),
        ...(title !== undefined ? { title } : {}),
        ...(department !== undefined ? { department } : {}),
      },
      include: {
        user: {
          select: {
            id: true,
            email: true,
            name: true,
            image: true,
          },
        },
      },
    });

    return NextResponse.json({
      member: {
        id: updated.id,
        userId: updated.user.id,
        email: updated.user.email,
        name: updated.user.name,
        image: updated.user.image,
        role: updated.role,
        status: updated.status,
        title: updated.title,
        department: updated.department,
      },
    });

  } catch (error) {
    console.error('Failed to update member:', error);
    return NextResponse.json(
      { error: 'Failed to update member' },
      { status: 500 }
    );
  }
}

// DELETE - Remove member
export async function DELETE(
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

    // Get the member to remove
    const member = await prisma.teamMember.findUnique({
      where: { id: memberId },
    });

    if (!member || member.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Member not found' }, { status: 404 });
    }

    // Can't remove owner
    if (member.role === 'OWNER') {
      return NextResponse.json({ error: 'Cannot remove owner' }, { status: 403 });
    }

    // Can't remove yourself
    if (member.userId === currentUserId) {
      return NextResponse.json({ error: 'Cannot remove yourself' }, { status: 403 });
    }

    // Admins can't remove other admins (only owner can)
    if (member.role === 'ADMIN' && currentMember.role !== 'OWNER') {
      return NextResponse.json({ error: 'Only owners can remove admins' }, { status: 403 });
    }

    // Remove all pipeline access for this user
    await prisma.pipelineAccess.deleteMany({
      where: { userId: member.userId },
    });

    // Remove team membership
    await prisma.teamMember.delete({
      where: { id: memberId },
    });

    // Optionally: Remove user from organization
    await prisma.user.update({
      where: { id: member.userId },
      data: { organizationId: null },
    });

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Failed to remove member:', error);
    return NextResponse.json(
      { error: 'Failed to remove member' },
      { status: 500 }
    );
  }
}
