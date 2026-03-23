import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { encrypt } from '@/lib/crypto';

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: { organizationId: true },
  });

  if (!user?.organizationId) {
    return NextResponse.json({ config: null });
  }

  const config = await prisma.orgOidcConfig.findUnique({
    where: { organizationId: user.organizationId },
  });

  if (!config) {
    return NextResponse.json({ config: null });
  }

  return NextResponse.json({
    config: {
      id: config.id,
      issuerUrl: config.issuerUrl,
      clientId: config.clientId,
      clientSecret: '••••••••',
      scopes: config.scopes,
      displayName: config.displayName,
      enabled: config.enabled,
    },
  });
}

export async function PUT(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const member = await prisma.teamMember.findFirst({
    where: {
      userId: (session.user as any).id,
      organizationId: (session.user as any).organizationId,
      role: 'OWNER',
    },
  });

  if (!member) {
    return NextResponse.json({ error: 'Only owners can configure OIDC' }, { status: 403 });
  }

  const org = await prisma.organization.findUnique({
    where: { id: member.organizationId },
    select: { domain: true },
  });

  if (!org?.domain) {
    return NextResponse.json(
      { error: 'Organization must have a domain set before enabling OIDC' },
      { status: 400 }
    );
  }

  const body = await request.json();
  const { issuerUrl, clientId, clientSecret, scopes, displayName, enabled } = body;

  if (!issuerUrl || !clientId) {
    return NextResponse.json({ error: 'Missing required fields' }, { status: 400 });
  }

  const existing = await prisma.orgOidcConfig.findUnique({
    where: { organizationId: member.organizationId },
  });

  if (!existing && !clientSecret) {
    return NextResponse.json({ error: 'Client secret is required' }, { status: 400 });
  }

  const updateData: any = {
    issuerUrl,
    clientId,
    scopes: scopes || 'openid email profile',
    displayName: displayName || 'SSO',
    enabled: enabled ?? true,
  };

  if (clientSecret) {
    updateData.clientSecret = encrypt(clientSecret);
  }

  const config = await prisma.orgOidcConfig.upsert({
    where: { organizationId: member.organizationId },
    create: {
      organizationId: member.organizationId,
      ...updateData,
      clientSecret: clientSecret ? encrypt(clientSecret) : '',
    },
    update: updateData,
  });

  return NextResponse.json({
    config: {
      id: config.id,
      issuerUrl: config.issuerUrl,
      clientId: config.clientId,
      clientSecret: '••••••••',
      scopes: config.scopes,
      displayName: config.displayName,
      enabled: config.enabled,
    },
  });
}

export async function DELETE() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const member = await prisma.teamMember.findFirst({
    where: {
      userId: (session.user as any).id,
      organizationId: (session.user as any).organizationId,
      role: 'OWNER',
    },
  });

  if (!member) {
    return NextResponse.json({ error: 'Only owners can delete OIDC config' }, { status: 403 });
  }

  await prisma.orgOidcConfig.deleteMany({
    where: { organizationId: member.organizationId },
  });

  return NextResponse.json({ success: true });
}
