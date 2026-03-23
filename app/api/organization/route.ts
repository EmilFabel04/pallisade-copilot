import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../lib/auth';
import prisma from '@/lib/db';

export async function PATCH(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;
  const body = await request.json();
  const { name, companySize, industry, dataTeamSize } = body;

  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { organizationId: true },
  });

  let organization;

  if (user?.organizationId) {
    // Update existing organization
    const data: Record<string, any> = {};
    if (name !== undefined) data.name = name;
    if (companySize !== undefined) data.companySize = companySize;
    if (industry !== undefined) data.industry = industry;
    if (dataTeamSize !== undefined) data.dataTeamSize = dataTeamSize;

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
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: {
      organization: {
        select: { id: true, name: true, companySize: true, industry: true, dataTeamSize: true },
      },
    },
  });

  return NextResponse.json({ organization: user?.organization || null });
}
