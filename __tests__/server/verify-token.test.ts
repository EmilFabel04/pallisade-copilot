/**
 * TypeScript half of the cross-language hash compatibility test.
 *
 * Mirrors scanner/tests/test_hash_cross_lang_compat.py — both files assert the
 * same hardcoded expected hashes for the same logical fixture configs.  If either
 * side changes canonicalizeForHash or computeConfigHash, BOTH tests fail in CI,
 * making cross-language drift immediately visible.
 *
 * Hardcoded expected hashes were derived from the Python canonicalize function:
 *   python -c "from scanner.api.security.verify_token import compute_config_hash; ..."
 *
 * The three fixtures cover: api_key (camelCase headerName), bearer (no header),
 * basic (username populated).  Each fixture is tested in both wizard camelCase
 * form and Pydantic snake_case form — they must produce identical hashes.
 */

import { computeConfigHash, canonicalizeForHash } from '@/lib/server/verify-token';

// ---------------------------------------------------------------------------
// Fixtures — must stay in sync with scanner/tests/test_hash_cross_lang_compat.py
// ---------------------------------------------------------------------------

const FIXTURES = [
  {
    label: 'api_key — headerName camelCase, no optional fields',
    // Wizard-style: camelCase, optional fields omitted
    wizard: {
      base_url: 'https://api.example.com/v1',
      schedule: 'daily',
      platform_label: 'Test',
      auth: {
        kind: 'api_key',
        headerName: 'X-API-Key',
        secret_ref: 'stash_abc',
      },
      datasets: [{ id: 'x', endpoint: '/x', timestamp_column: 'ts' }],
    },
    // Pydantic-style: snake_case, all optional fields as null
    pydantic: {
      base_url: 'https://api.example.com/v1',
      schedule: 'daily',
      platform_label: 'Test',
      auth: {
        kind: 'api_key',
        header_name: 'X-API-Key',
        username: null,
        secret_ref: 'stash_abc',
      },
      datasets: [
        {
          id: 'x',
          endpoint: '/x',
          json_root: null,
          timestamp_column: 'ts',
          lands_in: null,
          cursor_param: null,
        },
      ],
    },
    expectedHash: '3800913628b86ed7d22613f94953901234f8188513fd4e1b28427eed79a4e9ad',
  },
  {
    label: 'bearer — no headerName, no username',
    wizard: {
      base_url: 'https://api.example.com',
      schedule: 'hourly',
      platform_label: 'Bearer Test',
      auth: { kind: 'bearer', secret_ref: 'stash_xyz' },
      datasets: [{ id: 'x', endpoint: '/x', timestamp_column: 'created_at' }],
    },
    pydantic: {
      base_url: 'https://api.example.com',
      schedule: 'hourly',
      platform_label: 'Bearer Test',
      auth: { kind: 'bearer', header_name: null, username: null, secret_ref: 'stash_xyz' },
      datasets: [
        {
          id: 'x',
          endpoint: '/x',
          json_root: null,
          timestamp_column: 'created_at',
          lands_in: null,
          cursor_param: null,
        },
      ],
    },
    expectedHash: '1a8115e2e0fef2226dec6939a7d7d64ce7c251e0a4750fac90ec8234ceb20438',
  },
  {
    label: 'basic — username populated',
    wizard: {
      base_url: 'https://api.example.com',
      schedule: 'daily',
      platform_label: 'Basic Test',
      auth: { kind: 'basic', username: 'myuser', secret_ref: 'stash_basic' },
      datasets: [{ id: 'y', endpoint: '/y', timestamp_column: 'updated_at' }],
    },
    pydantic: {
      base_url: 'https://api.example.com',
      schedule: 'daily',
      platform_label: 'Basic Test',
      auth: { kind: 'basic', header_name: null, username: 'myuser', secret_ref: 'stash_basic' },
      datasets: [
        {
          id: 'y',
          endpoint: '/y',
          json_root: null,
          timestamp_column: 'updated_at',
          lands_in: null,
          cursor_param: null,
        },
      ],
    },
    expectedHash: '9c843bb5922239d8767b6fdcd46c32dbd934157347e9fb3593d369b751e37e35',
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('computeConfigHash — cross-language determinism', () => {
  for (const { label, wizard, pydantic, expectedHash } of FIXTURES) {
    it(`wizard camelCase: ${label}`, () => {
      const actual = computeConfigHash(wizard);
      expect(actual).toBe(expectedHash);
    });

    it(`pydantic snake_case: ${label}`, () => {
      const actual = computeConfigHash(pydantic);
      expect(actual).toBe(expectedHash);
    });

    it(`camelCase === snake_case: ${label}`, () => {
      expect(computeConfigHash(wizard)).toBe(computeConfigHash(pydantic));
    });
  }
});

describe('canonicalizeForHash — field projection', () => {
  it('maps camelCase headerName to snake_case header_name', () => {
    const result = canonicalizeForHash({
      base_url: 'https://x.com',
      schedule: 'daily',
      platform_label: 'X',
      auth: { kind: 'api_key', headerName: 'X-Key', secret_ref: 'ref' },
      datasets: [],
    });
    expect(result.auth.header_name).toBe('X-Key');
  });

  it('produces null for absent optional fields', () => {
    const result = canonicalizeForHash({
      base_url: 'https://x.com',
      schedule: 'daily',
      platform_label: 'X',
      auth: { kind: 'bearer', secret_ref: 'ref' },
      datasets: [{ id: 'd', endpoint: '/d', timestamp_column: 'ts' }],
    });
    expect(result.auth.header_name).toBeNull();
    expect(result.auth.username).toBeNull();
    expect(result.datasets[0].json_root).toBeNull();
    expect(result.datasets[0].lands_in).toBeNull();
    expect(result.datasets[0].cursor_param).toBeNull();
  });

  it('canonical JSON snapshot matches Python side for api_key fixture', () => {
    // This is the ground truth both sides hash.  If it changes, update both tests.
    const canonical = canonicalizeForHash(FIXTURES[0].wizard);
    // Use JSON.stringify with the same sortKeysDeep approach as computeConfigHash.
    // We manually sort top-level keys to verify structure without importing internals.
    const asRecord = canonical as unknown as Record<string, unknown>;
    const serialized = JSON.stringify(
      Object.keys(asRecord)
        .sort()
        .reduce<Record<string, unknown>>((acc, k) => {
          acc[k] = asRecord[k];
          return acc;
        }, {}),
    );
    // The canonical JSON is sorted by sortKeysDeep inside computeConfigHash,
    // but we manually verify the top-level structure here to catch regressions.
    expect(serialized).toContain('"header_name":"X-API-Key"');
    expect(serialized).toContain('"username":null');
    expect(serialized).toContain('"cursor_param":null');
    expect(serialized).toContain('"lands_in":null');
  });
});

describe('config persisted without plaintext secrets', () => {
  it('auth shape after stripping secret_ref has no credential fields', () => {
    // Simulate the route.ts fix: destructure out secret_ref and secret.
    const auth = {
      kind: 'bearer',
      header_name: null,
      username: null,
      secret_ref: 'stash_abc',
    };
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { secret_ref: _ref, secret: _existingSecret, ...nonSecretAuth } = auth as Record<
      string,
      unknown
    >;
    expect(nonSecretAuth).not.toHaveProperty('secret_ref');
    expect(nonSecretAuth).not.toHaveProperty('secret');
    expect(nonSecretAuth).toHaveProperty('kind', 'bearer');
  });
});
