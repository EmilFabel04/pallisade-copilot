import { timingSafeEqual } from 'crypto';

const DEV_FALLBACK = 'dev-internal-key-not-for-production';

let warned = false;

export function getInternalApiKey(): string {
  const key = process.env.INTERNAL_API_KEY;
  if (key && key.length > 0) return key;

  if (process.env.NODE_ENV === 'production') {
    throw new Error(
      'INTERNAL_API_KEY is not set. Refusing to use the dev fallback in production.',
    );
  }
  if (!warned) {
    console.warn(
      '[security] INTERNAL_API_KEY is unset — using insecure dev fallback. ' +
        'Set INTERNAL_API_KEY (e.g. `openssl rand -hex 32`) before deploying.',
    );
    warned = true;
  }
  return DEV_FALLBACK;
}

export function verifyInternalApiKey(provided: string | null | undefined): boolean {
  if (!provided) return false;
  const expected = getInternalApiKey();
  if (provided.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(provided), Buffer.from(expected));
}

export const INTERNAL_API_KEY_HEADER = 'x-internal-api-key';
