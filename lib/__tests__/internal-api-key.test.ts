import {
  getInternalApiKey,
  verifyInternalApiKey,
  INTERNAL_API_KEY_HEADER,
} from '@/lib/internal-api-key';

describe('internal-api-key', () => {
  const originalKey = process.env.INTERNAL_API_KEY;
  const originalNodeEnv = process.env.NODE_ENV;

  beforeEach(() => {
    delete process.env.INTERNAL_API_KEY;
    Object.defineProperty(process.env, 'NODE_ENV', { value: 'test', configurable: true });
    jest.resetModules();
  });

  afterAll(() => {
    if (originalKey !== undefined) process.env.INTERNAL_API_KEY = originalKey;
    Object.defineProperty(process.env, 'NODE_ENV', {
      value: originalNodeEnv,
      configurable: true,
    });
  });

  test('header constant is the expected name', () => {
    expect(INTERNAL_API_KEY_HEADER).toBe('x-internal-api-key');
  });

  describe('getInternalApiKey', () => {
    test('returns env var when set', () => {
      jest.isolateModules(() => {
        process.env.INTERNAL_API_KEY = 'my-real-key-abc123';
        const { getInternalApiKey: get } = require('@/lib/internal-api-key');
        expect(get()).toBe('my-real-key-abc123');
      });
    });

    test('returns dev fallback in non-production when env unset', () => {
      jest.isolateModules(() => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        const { getInternalApiKey: get } = require('@/lib/internal-api-key');
        expect(get()).toBe('dev-internal-key-not-for-production');
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('INTERNAL_API_KEY is unset'));
        warn.mockRestore();
      });
    });

    test('warns only once even after repeated calls', () => {
      jest.isolateModules(() => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        const { getInternalApiKey: get } = require('@/lib/internal-api-key');
        get();
        get();
        get();
        expect(warn).toHaveBeenCalledTimes(1);
        warn.mockRestore();
      });
    });

    test('throws in production when env unset', () => {
      jest.isolateModules(() => {
        Object.defineProperty(process.env, 'NODE_ENV', { value: 'production', configurable: true });
        const { getInternalApiKey: get } = require('@/lib/internal-api-key');
        expect(() => get()).toThrow(/INTERNAL_API_KEY is not set/);
      });
    });

    test('treats empty string env var as unset', () => {
      jest.isolateModules(() => {
        process.env.INTERNAL_API_KEY = '';
        Object.defineProperty(process.env, 'NODE_ENV', { value: 'production', configurable: true });
        const { getInternalApiKey: get } = require('@/lib/internal-api-key');
        expect(() => get()).toThrow(/INTERNAL_API_KEY is not set/);
      });
    });
  });

  describe('verifyInternalApiKey', () => {
    test('returns false for null / undefined / empty', () => {
      jest.isolateModules(() => {
        process.env.INTERNAL_API_KEY = 'expected-key';
        const { verifyInternalApiKey: verify } = require('@/lib/internal-api-key');
        expect(verify(null)).toBe(false);
        expect(verify(undefined)).toBe(false);
        expect(verify('')).toBe(false);
      });
    });

    test('returns false for mismatched key', () => {
      jest.isolateModules(() => {
        process.env.INTERNAL_API_KEY = 'expected-key';
        const { verifyInternalApiKey: verify } = require('@/lib/internal-api-key');
        expect(verify('wrong-key-x')).toBe(false);
      });
    });

    test('returns false when lengths differ (no timingSafeEqual crash)', () => {
      jest.isolateModules(() => {
        process.env.INTERNAL_API_KEY = 'expected-key';
        const { verifyInternalApiKey: verify } = require('@/lib/internal-api-key');
        expect(verify('shorter')).toBe(false);
        expect(verify('much-much-longer-than-expected-key')).toBe(false);
      });
    });

    test('returns true for exact match', () => {
      jest.isolateModules(() => {
        process.env.INTERNAL_API_KEY = 'expected-key-with-some-length';
        const { verifyInternalApiKey: verify } = require('@/lib/internal-api-key');
        expect(verify('expected-key-with-some-length')).toBe(true);
      });
    });
  });
});
