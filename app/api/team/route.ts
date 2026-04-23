/**
 * Team API
 * 
 * GET - Fetch team members, pending invites, and permissions
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const userId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Get current user's role
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId,
          organizationId,
        },
      },
    });

    const isAdmin = currentMember?.role === 'OWNER' || currentMember?.role === 'ADMIN';

    // Fetch organization details
    const organization = await prisma.organization.findUnique({
      where: { id: organizationId },
      select: {
        id: true,
        name: true,
        logo: true,
        plan: true,
        createdAt: true,
      },
    });

    // Fetch team members
    const teamMembers = await prisma.teamMember.findMany({
      where: { organizationId },
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
      orderBy: [
        { role: 'asc' },
        { joinedAt: 'asc' },
      ],
    });

    // Fetch pipeline access for each member
    const memberIds = teamMembers.map(m => m.user.id);
    const allPipelineAccess = await prisma.pipelineAccess.findMany({
      where: { userId: { in: memberIds } },
      include: {
        pipeline: {
          select: { id: true, name: true },
        },
      },
    });

    // Group access by user
    const accessByUser = new Map<string, typeof allPipelineAccess>();
    for (const access of allPipelineAccess) {
      const existing = accessByUser.get(access.userId) || [];
      existing.push(access);
      accessByUser.set(access.userId, existing);
    }

    // Format members
    const members = teamMembers.map(member => ({
      id: member.id,
      userId: member.user.id,
      email: member.user.email,
      name: member.user.name,
      image: member.user.image,
      role: member.role,
      status: member.status,
      title: member.title,
      department: member.department,
      joinedAt: member.joinedAt.toISOString(),
      lastActiveAt: member.lastActiveAt?.toISOString() || null,
      pipelineAccess: (accessByUser.get(member.user.id) || []).map(a => ({
        pipelineId: a.pipelineId,
        pipelineName: a.pipeline.name,
        accessLevel: a.accessLevel,
        tokensUsed: a.tokensUsed,
      })),
    }));

    // Fetch pending invites
    const pendingInvites = await prisma.teamInvite.findMany({
      where: {
        organizationId,
        status: 'PENDING',
        expiresAt: { gt: new Date() },
      },
      orderBy: { createdAt: 'desc' },
    });

    const invites = pendingInvites.map(invite => ({
      id: invite.id,
      email: invite.email,
      role: invite.role,
      inviterName: invite.inviterName,
      createdAt: invite.createdAt.toISOString(),
      expiresAt: invite.expiresAt.toISOString(),
      emailSentAt: invite.emailSentAt?.toISOString() || null,
    }));

    // Calculate activity stats
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    const activeMembers = members.filter(m => {
      if (!m.lastActiveAt) return false;
      return new Date(m.lastActiveAt) > thirtyDaysAgo;
    }).length;

    return NextResponse.json({
      organization,
      members,
      pendingInvites: invites,
      activity: {
        totalMembers: members.length,
        activeMembers,
        scansLast30Days: 0, // TODO: implement
        fixesLast30Days: 0, // TODO: implement
      },
      permissions: {
        canInvite: isAdmin,
        canRemove: isAdmin,
        canEditRoles: isAdmin,
      },
    });

  } catch (error) {
    console.error('Failed to fetch team:', error);
    return NextResponse.json(
      { error: 'Failed to fetch team' },
      { status: 500 }
    );
  }
}
