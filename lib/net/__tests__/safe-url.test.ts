import { assertExternalUrl } from '@/lib/net/safe-url';

jest.mock('node:dns/promises', () => ({
  lookup: jest.fn(),
}));

import { lookup } from 'node:dns/promises';
const mockedLookup = lookup as unknown as jest.Mock;

describe('assertExternalUrl', () => {
  beforeEach(() => {
    mockedLookup.mockReset();
    // Default: any hostname resolves to a public IP.
    mockedLookup.mockResolvedValue([{ address: '93.184.216.34', family: 4 }]);
  });

  describe('input validation', () => {
    test.each([
      [null, 'URL is required'],
      [undefined, 'URL is required'],
      ['', 'URL is required'],
      ['not a url', 'Invalid URL'],
    ])('rejects %p', async (raw, msg) => {
      await expect(assertExternalUrl(raw as any)).rejects.toThrow(msg);
    });
  });

  describe('protocol policy', () => {
    test('rejects http:// by default (https-only)', async () => {
      await expect(assertExternalUrl('http://example.com')).rejects.toThrow(
        'Protocol http: not allowed',
      );
    });
    test('rejects file://', async () => {
      await expect(assertExternalUrl('file:///etc/passwd')).rejects.toThrow(
        'Protocol file: not allowed',
      );
    });
    test('allows http:// when policy opts in', async () => {
      await expect(
        assertExternalUrl('http://example.com', {
          allowedProtocols: ['http:', 'https:'],
        }),
      ).resolves.toBeInstanceOf(URL);
    });
  });

  describe('credentials in URL', () => {
    test('rejects userinfo', async () => {
      await expect(
        assertExternalUrl('https://attacker:x@example.com/'),
      ).rejects.toThrow('Credentials in URL are not allowed');
    });
  });

  describe('IPv4 private ranges (no DNS)', () => {
    test.each([
      'https://127.0.0.1/',
      'https://10.0.0.1/',
      'https://172.16.0.1/',
      'https://192.168.1.1/',
      'https://169.254.169.254/', // cloud metadata
      'https://0.0.0.0/',
      'https://100.64.0.1/', // CG-NAT
    ])('rejects %s', async (url) => {
      await expect(assertExternalUrl(url)).rejects.toThrow('Private IP not allowed');
    });
    test('allows public IPv4', async () => {
      await expect(assertExternalUrl('https://8.8.8.8/')).resolves.toBeInstanceOf(URL);
    });
  });

  describe('IPv6 private ranges (no DNS)', () => {
    test.each([
      'https://[::1]/',
      'https://[fe80::1]/',
      'https://[fc00::1]/',
      'https://[::ffff:127.0.0.1]/',
      'https://[::]/',
    ])('rejects %s', async (url) => {
      await expect(assertExternalUrl(url)).rejects.toThrow('Private IP not allowed');
    });

    test.each([
      'https://[::ffff:7f00:1]/',      // hex form of ::ffff:127.0.0.1
      'https://[::ffff:a9fe:a9fe]/',   // hex form of ::ffff:169.254.169.254 (IMDS)
    ])('rejects IPv4-mapped hex form %s', async (url) => {
      await expect(assertExternalUrl(url)).rejects.toThrow('Private IP not allowed');
    });
  });

  describe('hostname DNS resolution', () => {
    test('rejects when all records are private (DNS rebinding)', async () => {
      mockedLookup.mockResolvedValue([{ address: '169.254.169.254', family: 4 }]);
      await expect(assertExternalUrl('https://rebind.evil.example/')).rejects.toThrow(
        /resolves to private IP/,
      );
    });
    test('rejects when any record is private (dual-stack rebinding)', async () => {
      mockedLookup.mockResolvedValue([
        { address: '93.184.216.34', family: 4 },
        { address: '10.0.0.1', family: 4 },
      ]);
      await expect(assertExternalUrl('https://mixed.evil.example/')).rejects.toThrow(
        /resolves to private IP/,
      );
    });
    test('rejects unresolvable hostname', async () => {
      mockedLookup.mockRejectedValue(new Error('ENOTFOUND'));
      await expect(assertExternalUrl('https://nope.invalid/')).rejects.toThrow(
        'Hostname does not resolve',
      );
    });
    test('accepts public hostname', async () => {
      mockedLookup.mockResolvedValue([{ address: '93.184.216.34', family: 4 }]);
      await expect(assertExternalUrl('https://example.com/')).resolves.toBeInstanceOf(URL);
    });
  });

  describe('host allow-list', () => {
    test('accepts exact match', async () => {
      mockedLookup.mockResolvedValue([{ address: '1.2.3.4', family: 4 }]);
      await expect(
        assertExternalUrl('https://hooks.slack.com/x', {
          allowedHostSuffixes: ['hooks.slack.com'],
        }),
      ).resolves.toBeInstanceOf(URL);
    });
    test('accepts subdomain of suffix', async () => {
      mockedLookup.mockResolvedValue([{ address: '1.2.3.4', family: 4 }]);
      await expect(
        assertExternalUrl('https://api.slack.com/x', {
          allowedHostSuffixes: ['slack.com'],
        }),
      ).resolves.toBeInstanceOf(URL);
    });
    test('rejects off-list host', async () => {
      await expect(
        assertExternalUrl('https://attacker.com/', {
          allowedHostSuffixes: ['slack.com'],
        }),
      ).rejects.toThrow('is not in the allow-list');
    });
    test('rejects host that merely contains the suffix substring', async () => {
      // "evilslack.com" contains "slack.com" as a substring but is not a subdomain.
      await expect(
        assertExternalUrl('https://evilslack.com/', {
          allowedHostSuffixes: ['slack.com'],
        }),
      ).rejects.toThrow('is not in the allow-list');
    });
  });
});
