import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';
import { rateLimit } from '@/lib/rate-limit';
import { setOidcOrgCookie } from '@/lib/auth-cookies';

export async function POST(request: NextRequest) {
  // Rate limit by IP
  const ip = request.headers.get('x-forwarded-for') || 'unknown';
  if (!rateLimit(ip, 10, 60_000)) {
    return NextResponse.json(
      { error: 'Too many requests' },
      { status: 429 }
    );
  }

  try {
    const { email } = await request.json();
    if (!email || typeof email !== 'string' || !email.includes('@')) {
      return NextResponse.json({ hasOidc: false });
    }

    const domain = email.split('@')[1].toLowerCase();

    const org = await prisma.organization.findFirst({
      where: { domain },
      include: {
        oidcConfig: {
          select: { enabled: true, displayName: true },
        },
      },
    });

    if (!org?.oidcConfig?.enabled) {
      // Always return same shape — don't reveal org existence
      return NextResponse.json({ hasOidc: false });
    }

    // Set signed cookie for the OIDC auth flow
    await setOidcOrgCookie(org.id);

    return NextResponse.json({
      hasOidc: true,
      displayName: org.oidcConfig.displayName,
    });
  } catch {
    return NextResponse.json({ hasOidc: false });
  }
}
