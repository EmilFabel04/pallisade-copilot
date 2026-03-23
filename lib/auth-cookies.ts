import { cookies } from 'next/headers';
import crypto from 'crypto';

const COOKIE_NAME = 'oidc_org_id';
const COOKIE_MAX_AGE = 300; // 5 minutes

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

export async function setOidcOrgCookie(orgId: string): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(COOKIE_NAME, sign(orgId), {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: COOKIE_MAX_AGE,
    path: '/',
  });
}

export async function getOidcOrgId(): Promise<string | null> {
  const cookieStore = await cookies();
  const cookie = cookieStore.get(COOKIE_NAME);
  if (!cookie?.value) return null;
  return verify(cookie.value);
}

export async function clearOidcOrgCookie(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(COOKIE_NAME);
}
