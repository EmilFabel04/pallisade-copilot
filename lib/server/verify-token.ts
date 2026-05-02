/**
 * Verify-token helpers — TypeScript counterpart to scanner/api/security/verify_token.py.
 *
 * After the /verify SSE stream completes with all_pass=true the FastAPI layer
 * issues a short-lived HMAC-SHA256 signed token.  The Next.js persist route
 * (/api/integrations POST) must validate this token before writing an Integration
 * row — this is the server-side verify gate for CUSTOM_SOURCE integrations.
 *
 * Token format (same as Python side):
 *   <base64url_payload>.<hex_hmac_sha256>
 *
 * Payload shape:
 *   { org_id: string; config_hash: string; exp: number }
 *
 * HMAC secret:
 *   Read from SOURCES_VERIFY_HMAC_SECRET env var.  If unset, an Error is thrown
 *   at call-time — this is a deploy-time misconfiguration on the Next.js side.
 *
 * Config hash canonicalization:
 *   ``computeConfigHash(obj)`` produces the SHA-256 hex digest of the canonical
 *   JSON (recursively sorted keys, no whitespace).  Must match the Python
 *   ``compute_config_hash`` in verify_token.py byte-for-byte.
 */

import crypto from 'crypto';

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function getHmacSecret(): Buffer {
  const raw = process.env.SOURCES_VERIFY_HMAC_SECRET;
  if (!raw) {
    throw new Error(
      'SOURCES_VERIFY_HMAC_SECRET is not set. ' +
        'This env var is required by the Next.js verify-token gate. ' +
        'Generate with: openssl rand -hex 32',
    );
  }
  return Buffer.from(raw, 'utf-8');
}

/**
 * Recursively sort the keys of an object (deep) so that JSON.stringify
 * produces a deterministic, canonical representation identical to Python's
 * ``json.dumps(d, sort_keys=True, separators=(",", ":")))``.
 */
function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortKeysDeep);
  }
  if (value !== null && typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    return Object.keys(obj)
      .sort()
      .reduce<Record<string, unknown>>((acc, k) => {
        acc[k] = sortKeysDeep(obj[k]);
        return acc;
      }, {});
  }
  return value;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Compute the SHA-256 hex digest of the canonical JSON representation of
 * ``verifyBody``.  Canonical = recursively sorted keys, no whitespace.
 *
 * Must produce the same hash as Python's ``compute_config_hash`` for the
 * same input — both sides use JSON with sorted keys and no separators.
 */
export function computeConfigHash(verifyBody: object): string {
  const canonical = JSON.stringify(sortKeysDeep(verifyBody));
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

export interface ValidateResult {
  valid: boolean;
  reason?: string;
}

/**
 * Validate a verify token issued by the FastAPI /verify endpoint.
 *
 * Returns ``{ valid: true }`` on success, or ``{ valid: false, reason }``
 * on any failure (malformed, expired, signature mismatch, wrong org / hash).
 */
export function validateVerifyToken(
  token: string,
  expectedOrgId: string,
  expectedConfigHash: string,
): ValidateResult {
  const secret = getHmacSecret();

  // 1. Parse structure.
  const dotIdx = token.lastIndexOf('.');
  if (dotIdx <= 0) {
    return { valid: false, reason: 'malformed token' };
  }
  const b64Part = token.slice(0, dotIdx);
  const providedSig = token.slice(dotIdx + 1);

  // 2. Verify signature (constant-time).
  const expectedSig = crypto
    .createHmac('sha256', secret)
    .update(b64Part, 'ascii')
    .digest('hex');
  try {
    if (!crypto.timingSafeEqual(Buffer.from(providedSig, 'hex'), Buffer.from(expectedSig, 'hex'))) {
      return { valid: false, reason: 'signature mismatch' };
    }
  } catch {
    // timingSafeEqual throws if buffers have different lengths — means sig is wrong.
    return { valid: false, reason: 'signature mismatch' };
  }

  // 3. Decode payload.
  let payload: Record<string, unknown>;
  try {
    // base64url with stripped padding — re-add padding.
    const padded = b64Part + '='.repeat((4 - (b64Part.length % 4)) % 4);
    const json = Buffer.from(padded, 'base64url').toString('utf-8');
    payload = JSON.parse(json);
  } catch {
    return { valid: false, reason: 'payload decode error' };
  }

  // 4. Expiry.
  const exp = typeof payload['exp'] === 'number' ? payload['exp'] : null;
  if (exp === null || Math.floor(Date.now() / 1000) > exp) {
    return { valid: false, reason: 'token expired' };
  }

  // 5. Org check.
  if (payload['org_id'] !== expectedOrgId) {
    return { valid: false, reason: 'org_id mismatch' };
  }

  // 6. Config hash.
  if (payload['config_hash'] !== expectedConfigHash) {
    return { valid: false, reason: 'config_hash mismatch' };
  }

  return { valid: true };
}
