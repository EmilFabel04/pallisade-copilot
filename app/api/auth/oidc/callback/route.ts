import { NextResponse, type NextRequest } from 'next/server';
import crypto from 'crypto';
import { SignJWT } from 'jose';
import { prisma } from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const STATE_COOKIE = 'oidc_state';

function getSigningKey(): string {
  const secret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
  if (!secret) throw new Error('AUTH_SECRET or NEXTAUTH_SECRET must be set');
  return secret;
}

function verify(signedValue: string): string | null {
  const lastDot = signedValue.lastIndexOf('.');
  if (lastDot === -1) return null;

  const value = signedValue.substring(0, lastDot);
  const signature = signedValue.substring(lastDot + 1);

  const key = getSigningKey();
  const hmac = crypto.createHmac('sha256', key);
  hmac.update(value);
  const expected = hmac.digest('hex');

  if (signature.length !== expected.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {
    return null;
  }

  return value;
}

function getSessionCookieName(): string {
  return process.env.NODE_ENV === 'production'
    ? '__Secure-authjs.session-token'
    : 'authjs.session-token';
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const error = searchParams.get('error');

    // Handle IdP-side errors
    if (error) {
      console.error('[OIDC] IdP returned error:', error, searchParams.get('error_description'));
      return NextResponse.redirect(
        new URL(`/login?error=SSOError&detail=${encodeURIComponent(error)}`, request.url)
      );
    }

    if (!code || !state) {
      return NextResponse.redirect(
        new URL('/login?error=SSOInvalidCallback', request.url)
      );
    }

    // 2. Read and verify oidc_state cookie
    const stateCookie = request.cookies.get(STATE_COOKIE);
    if (!stateCookie?.value) {
      return NextResponse.redirect(
        new URL('/login?error=SSOStateMissing', request.url)
      );
    }

    const verifiedPayload = verify(stateCookie.value);
    if (!verifiedPayload) {
      return NextResponse.redirect(
        new URL('/login?error=SSOStateInvalid', request.url)
      );
    }

    const stateData = JSON.parse(verifiedPayload) as {
      state: string;
      orgId: string;
      nonce: string;
    };

    // Compare state values
    if (state !== stateData.state) {
      return NextResponse.redirect(
        new URL('/login?error=SSOStateMismatch', request.url)
      );
    }

    const { orgId } = stateData;

    // 3. Load OIDC config from DB
    const oidcConfig = await prisma.orgOidcConfig.findUnique({
      where: { organizationId: orgId },
    });

    if (!oidcConfig || !oidcConfig.enabled) {
      return NextResponse.redirect(
        new URL('/login?error=SSONotConfigured', request.url)
      );
    }

    // 4. Fetch OIDC discovery for token endpoint
    const discoveryUrl = `${oidcConfig.issuerUrl.replace(/\/$/, '')}/.well-known/openid-configuration`;
    const discoveryRes = await fetch(discoveryUrl);
    if (!discoveryRes.ok) {
      console.error(`[OIDC] Discovery fetch failed: ${discoveryRes.status}`);
      return NextResponse.redirect(
        new URL('/login?error=SSODiscoveryFailed', request.url)
      );
    }
    const discovery = await discoveryRes.json();

    const tokenEndpoint = discovery.token_endpoint;
    const userinfoEndpoint = discovery.userinfo_endpoint;

    if (!tokenEndpoint) {
      console.error('[OIDC] No token_endpoint in discovery document');
      return NextResponse.redirect(
        new URL('/login?error=SSODiscoveryFailed', request.url)
      );
    }

    // 5. Exchange code for tokens
    const baseUrl = process.env.NEXTAUTH_URL || process.env.AUTH_URL;
    if (!baseUrl) {
      throw new Error('NEXTAUTH_URL or AUTH_URL must be set');
    }
    const redirectUri = `${baseUrl}/api/auth/oidc/callback`;
    const clientSecret = decrypt(oidcConfig.clientSecret);

    const tokenRes = await fetch(tokenEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: oidcConfig.clientId,
        client_secret: clientSecret,
        code,
        redirect_uri: redirectUri,
      }),
    });

    if (!tokenRes.ok) {
      const errorBody = await tokenRes.text();
      console.error('[OIDC] Token exchange failed:', tokenRes.status, errorBody);
      return NextResponse.redirect(
        new URL('/login?error=SSOTokenExchangeFailed', request.url)
      );
    }

    const tokens = await tokenRes.json();
    const accessToken: string = tokens.access_token;
    const idToken: string | undefined = tokens.id_token;
    const refreshToken: string | undefined = tokens.refresh_token;
    const expiresIn: number | undefined = tokens.expires_in;

    // 6. Fetch userinfo
    if (!userinfoEndpoint) {
      console.error('[OIDC] No userinfo_endpoint in discovery document');
      return NextResponse.redirect(
        new URL('/login?error=SSODiscoveryFailed', request.url)
      );
    }

    const userinfoRes = await fetch(userinfoEndpoint, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (!userinfoRes.ok) {
      console.error('[OIDC] Userinfo fetch failed:', userinfoRes.status);
      return NextResponse.redirect(
        new URL('/login?error=SSOUserinfoFailed', request.url)
      );
    }

    const userinfo = await userinfoRes.json();
    const email: string | undefined = userinfo.email;
    const name: string | undefined = userinfo.name;
    const sub: string = userinfo.sub;

    if (!email) {
      console.error('[OIDC] No email in userinfo response');
      return NextResponse.redirect(
        new URL('/login?error=SSONoEmail', request.url)
      );
    }

    // 7. Find or create user
    const providerName = `oidc-${orgId}`;
    let user = await prisma.user.findUnique({ where: { email } });

    if (user) {
      if (user.organizationId === orgId) {
        // User exists and belongs to this org - upsert Account
        await prisma.account.upsert({
          where: {
            provider_providerAccountId: {
              provider: providerName,
              providerAccountId: sub,
            },
          },
          update: {
            access_token: accessToken,
            refresh_token: refreshToken ?? null,
            id_token: idToken ?? null,
            expires_at: expiresIn
              ? Math.floor(Date.now() / 1000) + expiresIn
              : null,
          },
          create: {
            userId: user.id,
            type: 'oidc',
            provider: providerName,
            providerAccountId: sub,
            access_token: accessToken,
            refresh_token: refreshToken ?? null,
            id_token: idToken ?? null,
            expires_at: expiresIn
              ? Math.floor(Date.now() / 1000) + expiresIn
              : null,
          },
        });
      } else if (!user.organizationId) {
        // User exists but has no org - check for invite
        const invite = await prisma.teamInvite.findFirst({
          where: {
            email,
            organizationId: orgId,
            status: 'PENDING',
            expiresAt: { gt: new Date() },
          },
        });

        if (!invite) {
          return NextResponse.redirect(
            new URL('/login?error=NoInvite', request.url)
          );
        }

        // Redeem invite and link user to org
        await prisma.$transaction([
          prisma.user.update({
            where: { id: user.id },
            data: {
              organizationId: orgId,
              role: invite.role,
              name: name || user.name,
            },
          }),
          prisma.teamInvite.update({
            where: { id: invite.id },
            data: { status: 'ACCEPTED', respondedAt: new Date() },
          }),
          prisma.account.upsert({
            where: {
              provider_providerAccountId: {
                provider: providerName,
                providerAccountId: sub,
              },
            },
            update: {
              access_token: accessToken,
              refresh_token: refreshToken ?? null,
              id_token: idToken ?? null,
              expires_at: expiresIn
                ? Math.floor(Date.now() / 1000) + expiresIn
                : null,
            },
            create: {
              userId: user.id,
              type: 'oidc',
              provider: providerName,
              providerAccountId: sub,
              access_token: accessToken,
              refresh_token: refreshToken ?? null,
              id_token: idToken ?? null,
              expires_at: expiresIn
                ? Math.floor(Date.now() / 1000) + expiresIn
                : null,
            },
          }),
        ]);

        // Refresh user after update
        user = await prisma.user.findUnique({ where: { email } });
      } else {
        // User belongs to a different org
        return NextResponse.redirect(
          new URL('/login?error=WrongOrganization', request.url)
        );
      }
    } else {
      // New user - check for invite
      const invite = await prisma.teamInvite.findFirst({
        where: {
          email,
          organizationId: orgId,
          status: 'PENDING',
          expiresAt: { gt: new Date() },
        },
      });

      if (!invite) {
        return NextResponse.redirect(
          new URL('/login?error=NoInvite', request.url)
        );
      }

      // Create user and redeem invite in a transaction
      user = await prisma.$transaction(async (tx) => {
        const newUser = await tx.user.create({
          data: {
            email,
            name: name || null,
            organizationId: orgId,
            role: invite.role,
            emailVerified: new Date(),
          },
        });

        await tx.teamInvite.update({
          where: { id: invite.id },
          data: { status: 'ACCEPTED', respondedAt: new Date() },
        });

        await tx.account.create({
          data: {
            userId: newUser.id,
            type: 'oidc',
            provider: providerName,
            providerAccountId: sub,
            access_token: accessToken,
            refresh_token: refreshToken ?? null,
            id_token: idToken ?? null,
            expires_at: expiresIn
              ? Math.floor(Date.now() / 1000) + expiresIn
              : null,
          },
        });

        return newUser;
      });
    }

    if (!user) {
      return NextResponse.redirect(
        new URL('/login?error=SSOError', request.url)
      );
    }

    // 8. Create session JWT and set cookie
    const secret = new TextEncoder().encode(
      process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET
    );
    const token = await new SignJWT({
      id: user.id,
      email: user.email,
      name: user.name,
      organizationId: user.organizationId,
      timezone: user.timezone,
      sub: user.id,
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setIssuedAt()
      .setExpirationTime('30d')
      .sign(secret);

    const response = NextResponse.redirect(
      new URL('/dashboard', request.url)
    );
    response.cookies.set(getSessionCookieName(), token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: 30 * 24 * 60 * 60, // 30 days
    });
    response.cookies.delete(STATE_COOKIE);

    return response;
  } catch (error) {
    console.error('[OIDC] Callback error:', error);
    return NextResponse.redirect(
      new URL('/login?error=SSOError', request.url)
    );
  }
}
