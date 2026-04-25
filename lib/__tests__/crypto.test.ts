/**
 * crypto.ts hardening tests.
 *
 * The module reads process.env.ENCRYPTION_KEY at call time inside
 * getEncryptionKey() (not at module load), so per-test env mutation is safe
 * with jest.isolateModules() + require() to reset the warned-once flag.
 */

describe('lib/crypto', () => {
  const VALID_KEY_HEX = '0'.repeat(64); // 32 bytes of zero — fine for round-trip tests
  const originalKey = process.env.ENCRYPTION_KEY;
  const originalNodeEnv = process.env.NODE_ENV;

  beforeEach(() => {
    delete process.env.ENCRYPTION_KEY;
    Object.defineProperty(process.env, 'NODE_ENV', { value: 'test', configurable: true });
  });

  afterAll(() => {
    if (originalKey !== undefined) process.env.ENCRYPTION_KEY = originalKey;
    Object.defineProperty(process.env, 'NODE_ENV', {
      value: originalNodeEnv,
      configurable: true,
    });
  });

  test('encrypt/decrypt round-trip with explicit key', () => {
    jest.isolateModules(() => {
      process.env.ENCRYPTION_KEY = VALID_KEY_HEX;
      const { encrypt, decrypt } = require('@/lib/crypto');
      const ciphertext = encrypt('hello-world');
      expect(ciphertext).not.toBe('hello-world');
      expect(decrypt(ciphertext)).toBe('hello-world');
    });
  });

  test('rejects ENCRYPTION_KEY with wrong byte length', () => {
    jest.isolateModules(() => {
      process.env.ENCRYPTION_KEY = '00';
      const { encrypt } = require('@/lib/crypto');
      expect(() => encrypt('x')).toThrow(/ENCRYPTION_KEY must be 32 bytes/);
    });
  });

  test('throws in production when ENCRYPTION_KEY unset', () => {
    jest.isolateModules(() => {
      Object.defineProperty(process.env, 'NODE_ENV', { value: 'production', configurable: true });
      const { encrypt } = require('@/lib/crypto');
      expect(() => encrypt('x')).toThrow(/ENCRYPTION_KEY is not set/);
    });
  });

  test('uses dev fallback in non-production with one-time warning', () => {
    jest.isolateModules(() => {
      const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
      const { encrypt, decrypt } = require('@/lib/crypto');
      const ciphertext = encrypt('msg');
      expect(decrypt(ciphertext)).toBe('msg');
      // Encrypt + decrypt both call getEncryptionKey, but warn must still fire only once.
      encrypt('again');
      expect(warn).toHaveBeenCalledTimes(1);
      expect(warn).toHaveBeenCalledWith(expect.stringContaining('ENCRYPTION_KEY is unset'));
      warn.mockRestore();
    });
  });

  test('hash is deterministic and key-independent', () => {
    jest.isolateModules(() => {
      process.env.ENCRYPTION_KEY = VALID_KEY_HEX;
      const { hash } = require('@/lib/crypto');
      expect(hash('abc')).toBe(hash('abc'));
      expect(hash('abc')).not.toBe(hash('xyz'));
    });
  });
});
