import type { Session } from 'next-auth';
import { randomUUID } from 'crypto';

function getBaseUrl(): string {
  return process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';
}

function getSharedSecret(): string {
  const secret = process.env.SCANNER_SHARED_SECRET;
  if (!secret) {
    throw new Error(
      'SCANNER_SHARED_SECRET is not set. Add it to .env — generate with: openssl rand -hex 32'
    );
  }
  return secret;
}

function extractPrincipal(session: Session): { userId: string; orgId: string } {
  const userId = (session.user as any)?.id as string | undefined;
  const orgId = (session.user as any)?.organizationId as string | undefined;
  if (!userId) {
    throw new Error('scannerClient.fetch: session is missing user id');
  }
  if (!orgId) {
    throw new Error('scannerClient.fetch: session is missing organization id');
  }
  return { userId, orgId };
}

export const scannerClient = {
  async fetch(session: Session, path: string, init: RequestInit = {}): Promise<Response> {
    const { userId, orgId } = extractPrincipal(session);
    const secret = getSharedSecret();

    const url = `${getBaseUrl()}${path}`;

    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
      'X-Internal-Auth': secret,
      'X-Acting-User': userId,
      'X-Acting-Org': orgId,
      'X-Request-Id': randomUUID(),
    };

    return fetch(url, { ...init, headers });
  },
};
