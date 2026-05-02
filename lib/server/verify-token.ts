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
 *   ``computeConfigHash(obj)`` normalises the input to a canonical shape via
 *   ``canonicalizeForHash`` before hashing.  This ensures that wizard-style
 *   camelCase payloads and Pydantic snake_case model_dump() outputs produce the
 *   same SHA-256 digest.  Must match Python ``compute_config_hash`` byte-for-byte.
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
// Canonical projection — mirrors canonicalize_for_hash() in verify_token.py
// ---------------------------------------------------------------------------

interface CanonicalDataset {
  id: string;
  endpoint: string;
  json_root: string | null;
  timestamp_column: string;
  lands_in: string | null;
  cursor_param: string | null;
}

interface CanonicalAuth {
  kind: string;
  header_name: string | null;
  username: string | null;
  secret_ref: string;
}

interface CanonicalConfig {
  base_url: string;
  schedule: string;
  platform_label: string;
  auth: CanonicalAuth;
  datasets: CanonicalDataset[];
}

/**
 * Produce a canonical, shape-normalised representation of a source config.
 *
 * Accepts either:
 * - Wizard-style camelCase payload (``headerName``, optional fields omitted)
 * - Pydantic snake_case model_dump() (``header_name``, optional fields as null)
 *
 * Both inputs are mapped to the same projected shape so that
 * ``computeConfigHash`` returns the same digest for equivalent configs.
 * Mirrors the Python ``canonicalize_for_hash`` in verify_token.py exactly.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function canonicalizeForHash(config: any): CanonicalConfig {
  const rawAuth = config?.auth ?? {};
  const auth: CanonicalAuth = {
    kind: rawAuth.kind ?? '',
    // Accept camelCase (wizard) or snake_case (Pydantic model_dump)
    header_name: rawAuth.header_name ?? rawAuth.headerName ?? null,
    username: rawAuth.username ?? null,
    secret_ref: rawAuth.secret_ref ?? rawAuth.secretRef ?? '',
  };

  // Treat falsy values (empty string, undefined) as null to match Python's
  // ``or None`` coercion in canonicalize_for_hash.
  const norm = (v: unknown): string | null =>
    v != null && v !== '' ? String(v) : null;

  auth.header_name = norm(auth.header_name);
  auth.username = norm(auth.username);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rawDatasets: any[] = Array.isArray(config?.datasets) ? config.datasets : [];
  const datasets: CanonicalDataset[] = rawDatasets.map(ds => ({
    id: ds.id ?? '',
    endpoint: ds.endpoint ?? '',
    json_root: norm(ds.json_root ?? ds.jsonRoot),
    timestamp_column: ds.timestamp_column ?? ds.timestampColumn ?? '',
    lands_in: norm(ds.lands_in ?? ds.landsIn),
    cursor_param: norm(ds.cursor_param ?? ds.cursorParam),
  }));

  return {
    base_url: config?.base_url ?? config?.baseUrl ?? '',
    schedule: config?.schedule ?? '',
    platform_label: config?.platform_label ?? config?.platformLabel ?? '',
    auth,
    datasets,
  };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Compute the SHA-256 hex digest of the canonical JSON representation of
 * ``config``.  Normalises via ``canonicalizeForHash`` first, then sorts keys
 * recursively and serialises with no whitespace.
 *
 * Must produce the same hash as Python's ``compute_config_hash`` for the
 * same logical input (wizard camelCase OR Pydantic snake_case).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function computeConfigHash(config: any): string {
  const canonical = canonicalizeForHash(config);
  const serialized = JSON.stringify(sortKeysDeep(canonical));
  return crypto.createHash('sha256').update(serialized, 'utf8').digest('hex');
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
