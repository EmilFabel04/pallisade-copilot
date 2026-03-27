/**
 * Team Invite API
 * 
 * POST - Send an invite to join the organization
 * DELETE - Revoke a pending invite
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { getSlackOrgConfig, getSlackClient } from '@/lib/slack-helpers';
import { notifyEvents } from '@/lib/notifications';
import { sendInviteEmail } from '@/lib/email/invite';

// POST - Send invite
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if user is admin
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId: currentUserId,
          organizationId,
        },
      },
      include: {
        user: true,
        organization: { select: { name: true } },
      },
    });

    if (!currentMember || (currentMember.role !== 'OWNER' && currentMember.role !== 'ADMIN')) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    const body = await request.json();
    const { email, role = 'ENGINEER', personalNote, pipelineAccess = [] } = body;

    if (!email) {
      return NextResponse.json({ error: 'Email is required' }, { status: 400 });
    }

    // Check if email is already a member
    const existingUser = await prisma.user.findUnique({
      where: { email },
      include: {
        teamMemberships: {
          where: { organizationId },
        },
      },
    });

    if (existingUser?.teamMemberships.length) {
      return NextResponse.json(
        { error: 'This user is already a member of your organization' },
        { status: 400 }
      );
    }

    // Check for existing pending invite
    const existingInvite = await prisma.teamInvite.findUnique({
      where: {
        email_organizationId: {
          email,
          organizationId,
        },
      },
    });

    if (existingInvite && existingInvite.status === 'PENDING' && existingInvite.expiresAt > new Date()) {
      return NextResponse.json(
        { error: 'A pending invite already exists for this email' },
        { status: 400 }
      );
    }

    // Create or update invite
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7); // 7 days expiry

    const invite = await prisma.teamInvite.upsert({
      where: {
        email_organizationId: {
          email,
          organizationId,
        },
      },
      create: {
        email,
        role,
        personalNote,
        organizationId,
        invitedById: currentUserId,
        inviterName: currentMember.user.name || currentMember.user.email,
        expiresAt,
      },
      update: {
        role,
        personalNote,
        status: 'PENDING',
        invitedById: currentUserId,
        inviterName: currentMember.user.name || currentMember.user.email,
        expiresAt,
        emailSentAt: null,
        viewedAt: null,
        respondedAt: null,
      },
    });

    // Store pipeline access preferences in invite (we'll apply when user joins)
    // For now, store in personalNote as JSON since we don't have a dedicated field
    if (pipelineAccess.length > 0) {
      await prisma.teamInvite.update({
        where: { id: invite.id },
        data: {
          personalNote: JSON.stringify({
            note: personalNote,
            pipelineAccess,
          }),
        },
      });
    }

    // Generate invite link
    const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
    const inviteLink = `${baseUrl}/signup?invite=${invite.token}`;

    // Fire-and-forget email send (don't block the API response)
    sendInviteEmail({
      recipientEmail: email,
      inviterName: currentMember.user.name || currentMember.user.email,
      organizationName: currentMember.organization?.name || 'your team',
      role,
      personalNote: personalNote || undefined,
      inviteLink,
    }).then((sent) => {
      if (sent) {
        prisma.teamInvite.update({
          where: { id: invite.id },
          data: { emailSentAt: new Date() },
        }).catch((err) => console.error('[invite-email] Failed to update emailSentAt:', err));
      }
    }).catch((err) => console.error('[invite-email] Failed to send:', err));

    // Fire-and-forget notification
    notifyEvents.teamInviteSent(organizationId, currentUserId, email);

    // Fire-and-forget Slack notification
    const inviterName = currentMember.user.name || currentMember.user.email;
    getSlackOrgConfig(organizationId).then(async (cfg) => {
      if (!cfg.connected || !cfg.preferences.alertOnTeamInvite) return;
      const client = await getSlackClient(organizationId);
      if (!client) return;
      await client.sendMessage({
        title: 'Team Invite Sent',
        text: `*${inviterName}* invited *${email}* to join the team as *${role}*`,
        severity: 'low',
        footer: `Pallisade Team`,
      });
    }).catch(err => console.error('[team-invite] Slack notification failed:', err));

    return NextResponse.json({
      success: true,
      inviteId: invite.id,
      inviteLink,
    });

  } catch (error) {
    console.error('Failed to send invite:', error);
    return NextResponse.json(
      { error: 'Failed to send invite' },
      { status: 500 }
    );
  }
}

// DELETE - Revoke invite
export async function DELETE(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if user is admin
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

    const { searchParams } = new URL(request.url);
    const inviteId = searchParams.get('id');

    if (!inviteId) {
      return NextResponse.json({ error: 'Invite ID is required' }, { status: 400 });
    }

    // Verify invite belongs to org
    const invite = await prisma.teamInvite.findUnique({
      where: { id: inviteId },
    });

    if (!invite || invite.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Invite not found' }, { status: 404 });
    }

    // Update invite status to revoked
    await prisma.teamInvite.update({
      where: { id: inviteId },
      data: {
        status: 'REVOKED',
        respondedAt: new Date(),
      },
    });

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Failed to revoke invite:', error);
    return NextResponse.json(
      { error: 'Failed to revoke invite' },
      { status: 500 }
    );
  }
}

// PATCH - Resend invite email
export async function PATCH(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if user is admin
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId: currentUserId,
          organizationId,
        },
      },
      include: {
        user: true,
        organization: { select: { name: true } },
      },
    });

    if (!currentMember || (currentMember.role !== 'OWNER' && currentMember.role !== 'ADMIN')) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    const body = await request.json();
    const { inviteId } = body;

    if (!inviteId) {
      return NextResponse.json({ error: 'inviteId is required' }, { status: 400 });
    }

    // Verify invite belongs to org and is resendable
    const invite = await prisma.teamInvite.findUnique({
      where: { id: inviteId },
    });

    if (!invite || invite.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Invite not found' }, { status: 404 });
    }

    if (invite.status !== 'PENDING') {
      return NextResponse.json({ error: 'Can only resend pending invites' }, { status: 400 });
    }

    // Reset expiry to 7 days from now
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7);

    await prisma.teamInvite.update({
      where: { id: inviteId },
      data: { expiresAt, status: 'PENDING' },
    });

    // Generate invite link and send email
    const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
    const inviteLink = `${baseUrl}/signup?invite=${invite.token}`;

    const sent = await sendInviteEmail({
      recipientEmail: invite.email,
      inviterName: currentMember.user.name || currentMember.user.email,
      organizationName: currentMember.organization?.name || 'your team',
      role: invite.role,
      inviteLink,
    });

    if (sent) {
      await prisma.teamInvite.update({
        where: { id: inviteId },
        data: { emailSentAt: new Date() },
      });
    }

    return NextResponse.json({ success: true, emailSent: sent });

  } catch (error) {
    console.error('Failed to resend invite:', error);
    return NextResponse.json(
      { error: 'Failed to resend invite' },
      { status: 500 },
    );
  }
}
