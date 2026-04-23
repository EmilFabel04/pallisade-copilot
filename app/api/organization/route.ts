import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function PATCH(request: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;
  const body = await request.json();
  const { name, companySize, industry, dataTeamSize, authPolicy, authPolicyGraceUntil } = body;

  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { organizationId: true },
  });

  if (body.authPolicy !== undefined) {
    const member = await prisma.teamMember.findFirst({
      where: {
        userId: (session.user as any).id,
        organizationId: (session.user as any).organizationId,
        role: 'OWNER',
      },
    });
    if (!member) {
      return NextResponse.json({ error: 'Only owners can change auth policy' }, { status: 403 });
    }

    // If enabling SSO_ONLY, check that owner has an OAuth account
    if (body.authPolicy === 'SSO_ONLY') {
      const ownerAccounts = await prisma.account.count({
        where: { userId: (session.user as any).id },
      });
      if (ownerAccounts === 0) {
        return NextResponse.json(
          { error: 'You must have a linked OAuth account before enabling SSO-only' },
          { status: 400 }
        );
      }
    }
  }

  let organization;

  if (user?.organizationId) {
    // Update existing organization
    const data: Record<string, any> = {};
    if (name !== undefined) data.name = name;
    if (companySize !== undefined) data.companySize = companySize;
    if (industry !== undefined) data.industry = industry;
    if (dataTeamSize !== undefined) data.dataTeamSize = dataTeamSize;
    if (authPolicy !== undefined) data.authPolicy = authPolicy;
    if (authPolicyGraceUntil !== undefined) data.authPolicyGraceUntil = authPolicyGraceUntil;

    organization = await prisma.organization.update({
      where: { id: user.organizationId },
      data,
    });
  } else {
    // Create new organization + team membership (replicates signup pattern)
    if (!name) {
      return NextResponse.json({ error: 'Company name is required' }, { status: 400 });
    }

    organization = await prisma.$transaction(async (tx) => {
      const org = await tx.organization.create({
        data: { name, companySize, industry, dataTeamSize },
      });

      await tx.teamMember.create({
        data: {
          userId,
          organizationId: org.id,
          role: 'OWNER',
          status: 'ACTIVE',
          joinedAt: new Date(),
        },
      });

      await tx.user.update({
        where: { id: userId },
        data: { organizationId: org.id },
      });

      return org;
    });
  }

  return NextResponse.json({ organization });
}

export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: {
      organization: {
        select: {
          id: true,
          name: true,
          companySize: true,
          industry: true,
          dataTeamSize: true,
          authPolicy: true,
          authPolicyGraceUntil: true,
        },
      },
    },
  });

  const member = await prisma.teamMember.findFirst({
    where: {
      userId: (session.user as any).id,
      organizationId: (session.user as any).organizationId,
    },
    select: { role: true },
  });

  return NextResponse.json({
    organization: user?.organization
      ? { ...user.organization, userRole: member?.role || null }
      : null,
  });
}
