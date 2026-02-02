// ============================================
// TEAM MANAGEMENT HELPERS
// ============================================

import prisma from './db';
import { TeamRole } from '@prisma/client';
import { hasPermission, Permission, canManageRole, getAssignableRoles } from './permissions';

// Get a user's role in an organization
export async function getUserRole(
  userId: string,
  organizationId: string
): Promise<TeamRole | null> {
  const membership = await prisma.teamMember.findUnique({
    where: {
      userId_organizationId: {
        userId,
        organizationId,
      },
    },
    select: { role: true, status: true },
  });

  if (!membership || membership.status !== 'ACTIVE') {
    return null;
  }

  return membership.role;
}

// Check if user has permission in an organization
export async function checkPermission(
  userId: string,
  organizationId: string,
  permission: Permission
): Promise<boolean> {
  const role = await getUserRole(userId, organizationId);
  if (!role) return false;
  return hasPermission(role, permission);
}

// Check multiple permissions (AND)
export async function checkAllPermissions(
  userId: string,
  organizationId: string,
  permissions: Permission[]
): Promise<boolean> {
  const role = await getUserRole(userId, organizationId);
  if (!role) return false;
  return permissions.every(p => hasPermission(role, p));
}

// Check multiple permissions (OR)
export async function checkAnyPermission(
  userId: string,
  organizationId: string,
  permissions: Permission[]
): Promise<boolean> {
  const role = await getUserRole(userId, organizationId);
  if (!role) return false;
  return permissions.some(p => hasPermission(role, p));
}

// Get user's team membership details
export async function getTeamMembership(userId: string, organizationId: string) {
  return prisma.teamMember.findUnique({
    where: {
      userId_organizationId: {
        userId,
        organizationId,
      },
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
      organization: {
        select: {
          id: true,
          name: true,
          logo: true,
          plan: true,
        },
      },
    },
  });
}

// Get all team members for an organization
export async function getTeamMembers(organizationId: string) {
  return prisma.teamMember.findMany({
    where: { organizationId },
    include: {
      user: {
        select: {
          id: true,
          email: true,
          name: true,
          image: true,
          createdAt: true,
        },
      },
    },
    orderBy: [
      { role: 'asc' }, // Owner first, then Admin, etc.
      { joinedAt: 'asc' },
    ],
  });
}

// Get pending invites for an organization
export async function getPendingInvites(organizationId: string) {
  return prisma.teamInvite.findMany({
    where: {
      organizationId,
      status: 'PENDING',
      expiresAt: { gt: new Date() },
    },
    orderBy: { createdAt: 'desc' },
  });
}

// Create invite (returns the full invite with token)
export async function createInvite(params: {
  email: string;
  organizationId: string;
  role: TeamRole;
  invitedById: string;
  inviterName?: string;
  personalNote?: string;
  title?: string;
  department?: string;
  expiresInDays?: number;
}) {
  const expiresAt = new Date();
  expiresAt.setDate(expiresAt.getDate() + (params.expiresInDays ?? 7));

  return prisma.teamInvite.create({
    data: {
      email: params.email.toLowerCase(),
      organizationId: params.organizationId,
      role: params.role,
      invitedById: params.invitedById,
      inviterName: params.inviterName,
      personalNote: params.personalNote,
      title: params.title,
      department: params.department,
      expiresAt,
    },
    include: {
      organization: {
        select: {
          name: true,
          logo: true,
        },
      },
    },
  });
}

// Accept an invite
export async function acceptInvite(token: string, userId: string) {
  const invite = await prisma.teamInvite.findUnique({
    where: { token },
    include: {
      organization: true,
    },
  });

  if (!invite) {
    throw new Error('Invite not found');
  }

  if (invite.status !== 'PENDING') {
    throw new Error(`Invite is ${invite.status.toLowerCase()}`);
  }

  if (invite.expiresAt < new Date()) {
    await prisma.teamInvite.update({
      where: { id: invite.id },
      data: { status: 'EXPIRED' },
    });
    throw new Error('Invite has expired');
  }

  // Create team membership and update invite in a transaction
  const result = await prisma.$transaction(async (tx) => {
    // Update invite status
    await tx.teamInvite.update({
      where: { id: invite.id },
      data: {
        status: 'ACCEPTED',
        respondedAt: new Date(),
      },
    });

    // Create team membership
    const membership = await tx.teamMember.create({
      data: {
        userId,
        organizationId: invite.organizationId,
        role: invite.role,
        title: invite.title,
        department: invite.department,
        joinedAt: new Date(),
      },
      include: {
        organization: {
          select: {
            id: true,
            name: true,
          },
        },
      },
    });

    // Update user's organizationId for easy access
    await tx.user.update({
      where: { id: userId },
      data: { organizationId: invite.organizationId },
    });

    return membership;
  });

  return result;
}

// Update member role
export async function updateMemberRole(
  memberId: string,
  newRole: TeamRole,
  updatedById: string,
  organizationId: string
) {
  // Get the updater's role
  const updaterRole = await getUserRole(updatedById, organizationId);
  if (!updaterRole) {
    throw new Error('You are not a member of this organization');
  }

  // Get the target member
  const targetMember = await prisma.teamMember.findUnique({
    where: { id: memberId },
    select: { role: true, userId: true },
  });

  if (!targetMember) {
    throw new Error('Member not found');
  }

  // Can't demote yourself if you're the only owner
  if (targetMember.role === 'OWNER' && newRole !== 'OWNER') {
    const ownerCount = await prisma.teamMember.count({
      where: {
        organizationId,
        role: 'OWNER',
      },
    });
    if (ownerCount <= 1) {
      throw new Error('Cannot demote the only owner. Transfer ownership first.');
    }
  }

  // Check if updater can manage the target's current role and the new role
  if (!canManageRole(updaterRole, targetMember.role)) {
    throw new Error('You cannot modify this member');
  }
  if (!canManageRole(updaterRole, newRole)) {
    throw new Error('You cannot assign this role');
  }

  return prisma.teamMember.update({
    where: { id: memberId },
    data: { role: newRole },
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
}

// Remove member from team
export async function removeMember(
  memberId: string,
  removedById: string,
  organizationId: string
) {
  // Get the remover's role
  const removerRole = await getUserRole(removedById, organizationId);
  if (!removerRole) {
    throw new Error('You are not a member of this organization');
  }

  // Get the target member
  const targetMember = await prisma.teamMember.findUnique({
    where: { id: memberId },
    select: { role: true, userId: true },
  });

  if (!targetMember) {
    throw new Error('Member not found');
  }

  // Can't remove the last owner
  if (targetMember.role === 'OWNER') {
    const ownerCount = await prisma.teamMember.count({
      where: {
        organizationId,
        role: 'OWNER',
      },
    });
    if (ownerCount <= 1) {
      throw new Error('Cannot remove the only owner. Transfer ownership first.');
    }
  }

  // Check if remover can manage the target's role
  if (!canManageRole(removerRole, targetMember.role) && targetMember.userId !== removedById) {
    throw new Error('You cannot remove this member');
  }

  return prisma.$transaction(async (tx) => {
    // Remove membership
    await tx.teamMember.delete({
      where: { id: memberId },
    });

    // Clear user's organizationId
    await tx.user.update({
      where: { id: targetMember.userId },
      data: { organizationId: null },
    });
  });
}

// Transfer ownership
export async function transferOwnership(
  targetMemberId: string,
  currentOwnerId: string,
  organizationId: string
) {
  // Verify current owner
  const currentOwnerRole = await getUserRole(currentOwnerId, organizationId);
  if (currentOwnerRole !== 'OWNER') {
    throw new Error('Only owners can transfer ownership');
  }

  // Get target member
  const targetMember = await prisma.teamMember.findUnique({
    where: { id: targetMemberId },
    select: { userId: true, role: true },
  });

  if (!targetMember) {
    throw new Error('Target member not found');
  }

  // Get current owner's membership
  const currentOwnerMembership = await prisma.teamMember.findUnique({
    where: {
      userId_organizationId: {
        userId: currentOwnerId,
        organizationId,
      },
    },
  });

  if (!currentOwnerMembership) {
    throw new Error('Current owner membership not found');
  }

  // Transfer ownership
  return prisma.$transaction(async (tx) => {
    // Make target the new owner
    await tx.teamMember.update({
      where: { id: targetMemberId },
      data: { role: 'OWNER' },
    });

    // Demote current owner to admin
    await tx.teamMember.update({
      where: { id: currentOwnerMembership.id },
      data: { role: 'ADMIN' },
    });
  });
}

// Create organization with owner
export async function createOrganizationWithOwner(
  userId: string,
  organizationName: string,
  domain?: string
) {
  return prisma.$transaction(async (tx) => {
    // Create organization
    const org = await tx.organization.create({
      data: {
        name: organizationName,
        domain: domain?.toLowerCase(),
      },
    });

    // Create owner membership
    const membership = await tx.teamMember.create({
      data: {
        userId,
        organizationId: org.id,
        role: 'OWNER',
        status: 'ACTIVE',
      },
    });

    // Update user's organizationId
    await tx.user.update({
      where: { id: userId },
      data: { organizationId: org.id },
    });

    return { organization: org, membership };
  });
}

// Get team activity summary
export async function getTeamActivitySummary(organizationId: string) {
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

  const [members, recentScans, recentFixes, activeMembers] = await Promise.all([
    prisma.teamMember.count({ where: { organizationId } }),
    prisma.report.count({
      where: {
        organizationId,
        createdAt: { gte: thirtyDaysAgo },
      },
    }),
    prisma.appliedFix.count({
      where: {
        organizationId,
        appliedAt: { gte: thirtyDaysAgo },
      },
    }),
    prisma.teamMember.count({
      where: {
        organizationId,
        lastActiveAt: { gte: thirtyDaysAgo },
      },
    }),
  ]);

  return {
    totalMembers: members,
    activeMembers,
    scansLast30Days: recentScans,
    fixesLast30Days: recentFixes,
  };
}
