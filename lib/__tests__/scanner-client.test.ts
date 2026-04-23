import { scannerClient } from '@/lib/scanner-client';

describe('scannerClient.fetch', () => {
  const realFetch = global.fetch;

  beforeEach(() => {
    process.env.SCANNER_API_URL = 'http://127.0.0.1:8000';
    process.env.SCANNER_SHARED_SECRET = 'test-secret-64-bytes-' + 'x'.repeat(44);
    global.fetch = jest.fn(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    ) as jest.Mock;
  });

  afterEach(() => {
    global.fetch = realFetch;
  });

  const session = {
    user: { id: 'user_123', organizationId: 'org_456', email: 'x@y.z', name: 'X', image: null },
    expires: '2099-01-01',
  } as any;

  it('injects all three headers on every call', async () => {
    await scannerClient.fetch(session, '/api/v1/ping');
    const call = (global.fetch as jest.Mock).mock.calls[0];
    const [url, init] = call;
    expect(url).toBe('http://127.0.0.1:8000/api/v1/ping');
    expect(init.headers['X-Internal-Auth']).toBe(process.env.SCANNER_SHARED_SECRET);
    expect(init.headers['X-Acting-User']).toBe('user_123');
    expect(init.headers['X-Acting-Org']).toBe('org_456');
    expect(init.headers['X-Request-Id']).toMatch(/^[0-9a-f-]+$/);
  });

  it('preserves caller-provided headers', async () => {
    await scannerClient.fetch(session, '/api/v1/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ foo: 1 }),
    });
    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.headers['X-Internal-Auth']).toBeDefined();
  });

  it('throws if session has no user id', async () => {
    const badSession = { user: { organizationId: 'org_456' }, expires: '2099-01-01' } as any;
    await expect(scannerClient.fetch(badSession, '/api/v1/ping')).rejects.toThrow(/user id/i);
  });

  it('throws if session has no organizationId', async () => {
    const badSession = { user: { id: 'user_123' }, expires: '2099-01-01' } as any;
    await expect(scannerClient.fetch(badSession, '/api/v1/ping')).rejects.toThrow(/organization/i);
  });

  it('throws if SCANNER_SHARED_SECRET is not set', async () => {
    delete process.env.SCANNER_SHARED_SECRET;
    await expect(scannerClient.fetch(session, '/api/v1/ping')).rejects.toThrow(/SCANNER_SHARED_SECRET/);
  });
});
