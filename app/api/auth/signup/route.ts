import { NextRequest, NextResponse } from 'next/server';
import prisma from '../../../../lib/db';
import { hashPassword } from '../../../../lib/passwords';

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

    // Create user and organization in a transaction
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

      // Create organization if name provided
      let organization = null;
      if (organizationName) {
        organization = await tx.organization.create({
          data: {
            name: organizationName,
          },
        });

        // Create team membership as OWNER
        await tx.teamMember.create({
          data: {
            userId: user.id,
            organizationId: organization.id,
            role: 'OWNER',
            status: 'ACTIVE',
            joinedAt: new Date(),
          },
        });

        // Update user with organizationId
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

