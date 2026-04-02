import { NextRequest, NextResponse } from 'next/server';
import prisma from '../../../../lib/db';
import { hashPassword } from '../../../../lib/passwords';

/**
 * Parse pipeline access from a TeamInvite's personalNote field.
 * Returns the array if valid, null otherwise.
 */
function parsePipelineAccess(
  personalNote: string | null,
): Array<{ pipelineId: string; accessLevel: string }> | null {
  if (!personalNote) return null;
  try {
    const parsed = JSON.parse(personalNote);
    if (parsed?.pipelineAccess && Array.isArray(parsed.pipelineAccess)) {
      return parsed.pipelineAccess;
    }
  } catch {
    // Plain text note, not JSON
  }
  return null;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password, name, organizationName } = body;

    // Validation
    if (!email || !password) {
      return NextResponse.json(
        { error: 'Email and password are required' },
        { status: 400 }
      );
    }

    if (password.length < 8) {
      return NextResponse.json(
        { error: 'Password must be at least 8 characters' },
        { status: 400 }
      );
    }

    // Check if user already exists
    const existingUser = await prisma.user.findUnique({
      where: { email },
    });

    if (existingUser) {
      return NextResponse.json(
        { error: 'An account with this email already exists' },
        { status: 400 }
      );
    }

    // Hash password
    const passwordHash = await hashPassword(password);

    // Check for a pending invite matching this email
    const invite = await prisma.teamInvite.findFirst({
      where: {
        email: email.toLowerCase(),
        status: 'PENDING',
        expiresAt: { gt: new Date() },
      },
    });

    // Create user and handle org/invite in a transaction
    const result = await prisma.$transaction(async (tx) => {
      // Create user first
      const user = await tx.user.create({
        data: {
          email: email.toLowerCase(),
          name,
          passwordHash,
        },
        select: {
          id: true,
          email: true,
          name: true,
          createdAt: true,
        },
      });

      let organization = null;

      if (invite) {
        // ---- Invite path: join existing org ----
        await tx.teamMember.create({
          data: {
            userId: user.id,
            organizationId: invite.organizationId,
            role: invite.role,
            status: 'ACTIVE',
            joinedAt: new Date(),
          },
        });

        await tx.user.update({
          where: { id: user.id },
          data: { organizationId: invite.organizationId },
        });

        await tx.teamInvite.update({
          where: { id: invite.id },
          data: { status: 'ACCEPTED', respondedAt: new Date() },
        });

        // Grant pipeline access
        const pipelineAccess = parsePipelineAccess(invite.personalNote);
        if (pipelineAccess && pipelineAccess.length > 0) {
          // Use admin-specified pipelines
          for (const pa of pipelineAccess) {
            await tx.pipelineAccess.create({
              data: {
                userId: user.id,
                pipelineId: pa.pipelineId,
                accessLevel: pa.accessLevel === 'EDITOR' ? 'EDITOR' : pa.accessLevel === 'OWNER' ? 'OWNER' : 'VIEWER',
                grantedBy: invite.invitedById || user.id,
              },
            });
          }
        } else {
          // Default: VIEWER access to all org pipelines
          const orgPipelines = await tx.pipelineStack.findMany({
            where: { organizationId: invite.organizationId },
            select: { id: true },
          });
          for (const pipeline of orgPipelines) {
            await tx.pipelineAccess.create({
              data: {
                userId: user.id,
                pipelineId: pipeline.id,
                accessLevel: 'VIEWER',
                grantedBy: invite.invitedById || user.id,
              },
            });
          }
        }

        organization = await tx.organization.findUnique({
          where: { id: invite.organizationId },
          select: { id: true, name: true },
        });
      } else if (organizationName) {
        // ---- Normal path: create new org ----
        organization = await tx.organization.create({
          data: { name: organizationName },
        });

        await tx.teamMember.create({
          data: {
            userId: user.id,
            organizationId: organization.id,
            role: 'OWNER',
            status: 'ACTIVE',
            joinedAt: new Date(),
          },
        });

        await tx.user.update({
          where: { id: user.id },
          data: { organizationId: organization.id },
        });
      }

      return { user, organization };
    });

    return NextResponse.json({
      message: 'Account created successfully',
      user: result.user,
      organization: result.organization
        ? { id: result.organization.id, name: result.organization.name }
        : null,
    });
  } catch (error) {
    console.error('Signup error:', error);
    return NextResponse.json(
      { error: 'An error occurred during signup' },
      { status: 500 }
    );
  }
}
