import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { generateInviteHtml, sendInviteEmail } from '../email/invite';
import type { InviteEmailParams } from '../email/invite';

const baseParams: InviteEmailParams = {
  recipientEmail: 'new@example.com',
  inviterName: 'Alice Smith',
  organizationName: 'Acme Corp',
  role: 'ENGINEER',
  inviteLink: 'https://app.pallisade.dev/signup?invite=abc123',
};

describe('generateInviteHtml', () => {
  it('renders all fields into the HTML', () => {
    const html = generateInviteHtml({ ...baseParams, personalNote: 'Welcome aboard!' });
    expect(html).toContain('Alice Smith');
    expect(html).toContain('Acme Corp');
    expect(html).toContain('Engineer');
    expect(html).toContain('Welcome aboard!');
    expect(html).toContain('https://app.pallisade.dev/signup?invite=abc123');
    expect(html).toContain('Accept Invite');
  });

  it('omits personal note block when not provided', () => {
    const html = generateInviteHtml(baseParams);
    expect(html).not.toContain('border-left: 3px solid');
    expect(html).toContain('Alice Smith');
  });

  it('escapes HTML in user-provided strings', () => {
    const html = generateInviteHtml({
      ...baseParams,
      inviterName: '<script>alert("xss")</script>',
      personalNote: '<img src=x onerror=alert(1)>',
    });
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<img src=x');
  });

  it('handles unknown role gracefully', () => {
    const html = generateInviteHtml({ ...baseParams, role: 'CUSTOM_ROLE' });
    expect(html).toContain('CUSTOM_ROLE');
  });
});

describe('sendInviteEmail', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it('returns false and warns when RESEND_API_KEY is not set', async () => {
    delete process.env.RESEND_API_KEY;
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const result = await sendInviteEmail(baseParams);
    expect(result).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('RESEND_API_KEY not set'));
  });

  it('calls Resend API with correct payload when API key is set', async () => {
    process.env.RESEND_API_KEY = 'test-key-123';
    process.env.EMAIL_FROM = 'noreply@test.dev';

    const mockFetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'email-id' }), { status: 200 }),
    );

    const result = await sendInviteEmail(baseParams);
    expect(result).toBe(true);
    expect(mockFetch).toHaveBeenCalledOnce();

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('https://api.resend.com/emails');
    expect(opts?.method).toBe('POST');

    const headers = opts?.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-key-123');

    const body = JSON.parse(opts?.body as string);
    expect(body.to).toEqual(['new@example.com']);
    expect(body.from).toContain('noreply@test.dev');
    expect(body.subject).toContain('Alice Smith');
    expect(body.html).toBeTruthy();
    expect(body.text).toBeTruthy();
  });

  it('returns false on Resend API failure', async () => {
    process.env.RESEND_API_KEY = 'test-key-123';
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('rate limited', { status: 429 }),
    );
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const result = await sendInviteEmail(baseParams);
    expect(result).toBe(false);
    expect(errorSpy).toHaveBeenCalled();
  });
});
