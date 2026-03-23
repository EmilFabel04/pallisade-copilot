import { NextResponse } from 'next/server';
import crypto from 'crypto';
import { getOidcOrgId } from '@/lib/auth-cookies';
import { prisma } from '@/lib/db';

const STATE_COOKIE = 'oidc_state';
const STATE_MAX_AGE = 300; // 5 minutes

function getSigningKey(): string {
  const secret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
  if (!secret) throw new Error('AUTH_SECRET or NEXTAUTH_SECRET must be set');
  return secret;
}

function sign(value: string): string {
  const key = getSigningKey();
  const hmac = crypto.createHmac('sha256', key);
  hmac.update(value);
  return `${value}.${hmac.digest('hex')}`;
}

export async function GET(request: Request) {
  try {
    // 1. Read org ID from signed cookie
    const orgId = await getOidcOrgId();
    if (!orgId) {
      return NextResponse.redirect(
        new URL('/login?error=NoOrgCookie', request.url)
      );
    }

    // 2. Load OIDC config from DB
    const oidcConfig = await prisma.orgOidcConfig.findUnique({
      where: { organizationId: orgId },
    });

    if (!oidcConfig || !oidcConfig.enabled) {
      return NextResponse.redirect(
        new URL('/login?error=SSONotConfigured', request.url)
      );
    }

    // 3. Fetch OIDC discovery document
    const discoveryUrl = `${oidcConfig.issuerUrl.replace(/\/$/, '')}/.well-known/openid-configuration`;
    const discoveryRes = await fetch(discoveryUrl);
    if (!discoveryRes.ok) {
      console.error(
        `[OIDC] Discovery fetch failed: ${discoveryRes.status} ${discoveryRes.statusText}`
      );
      return NextResponse.redirect(
        new URL('/login?error=SSODiscoveryFailed', request.url)
      );
    }
    const discovery = await discoveryRes.json();

    const authorizationEndpoint = discovery.authorization_endpoint;
    if (!authorizationEndpoint) {
      console.error('[OIDC] No authorization_endpoint in discovery document');
      return NextResponse.redirect(
        new URL('/login?error=SSODiscoveryFailed', request.url)
      );
    }

    // 4. Generate random state and nonce
    const state = crypto.randomBytes(32).toString('hex');
    const nonce = crypto.randomBytes(32).toString('hex');

    // 5. Build redirect URI
    const baseUrl = process.env.NEXTAUTH_URL || process.env.AUTH_URL;
    if (!baseUrl) {
      throw new Error('NEXTAUTH_URL or AUTH_URL must be set');
    }
    const redirectUri = `${baseUrl}/api/auth/oidc/callback`;

    // 6. Build authorization URL
    const authUrl = new URL(authorizationEndpoint);
    authUrl.searchParams.set('client_id', oidcConfig.clientId);
    authUrl.searchParams.set('redirect_uri', redirectUri);
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('scope', oidcConfig.scopes);
    authUrl.searchParams.set('state', state);
    authUrl.searchParams.set('nonce', nonce);

    // 7. Store state in signed cookie
    const statePayload = JSON.stringify({ state, orgId, nonce });
    const response = NextResponse.redirect(authUrl.toString());
    response.cookies.set(STATE_COOKIE, sign(statePayload), {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: STATE_MAX_AGE,
      path: '/',
    });

    return response;
  } catch (error) {
    console.error('[OIDC] Authorize error:', error);
    return NextResponse.redirect(
      new URL('/login?error=SSOError', request.url)
    );
  }
}
