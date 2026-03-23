import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(request: NextRequest) {
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
    return NextResponse.json({ error: 'Only owners can test OIDC' }, { status: 403 });
  }

  const { issuerUrl } = await request.json();

  if (!issuerUrl) {
    return NextResponse.json({ error: 'Issuer URL is required' }, { status: 400 });
  }

  try {
    const wellKnownUrl = `${issuerUrl.replace(/\/$/, '')}/.well-known/openid-configuration`;
    const res = await fetch(wellKnownUrl, { signal: AbortSignal.timeout(10_000) });

    if (!res.ok) {
      return NextResponse.json({
        success: false,
        error: `Discovery endpoint returned ${res.status}`,
      });
    }

    const discovery = await res.json();

    const required = ['issuer', 'authorization_endpoint', 'token_endpoint'];
    const missing = required.filter((f) => !discovery[f]);

    if (missing.length > 0) {
      return NextResponse.json({
        success: false,
        error: `Discovery document missing: ${missing.join(', ')}`,
      });
    }

    return NextResponse.json({
      success: true,
      issuer: discovery.issuer,
      endpoints: {
        authorization: discovery.authorization_endpoint,
        token: discovery.token_endpoint,
        userinfo: discovery.userinfo_endpoint,
      },
    });
  } catch (err: any) {
    return NextResponse.json({
      success: false,
      error: err.message || 'Failed to connect to OIDC provider',
    });
  }
}
