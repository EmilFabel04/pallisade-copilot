# Team Invite Emails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send branded invite emails via Resend when admins invite team members, and allow resending invites from the team page.

**Architecture:** New `lib/email/invite.ts` module handles template generation and Resend API calls using `RESEND_API_KEY` env var. The invite API route fires the email asynchronously (fire-and-forget) after creating the invite record. A new PATCH endpoint supports resending. The team page gets a resend button on invite rows.

**Tech Stack:** Resend API (REST), Next.js API routes, inline HTML email templates, Vitest

**Spec:** `docs/superpowers/specs/2026-03-27-team-invite-emails-design.md`

---

### Task 1: Create `lib/email/invite.ts` — HTML template + send function

**Files:**
- Create: `lib/email/invite.ts`

- [ ] **Step 1: Create `lib/email/invite.ts` with `generateInviteHtml` and `sendInviteEmail`**

```typescript
/**
 * Team invite email — generates HTML and sends via Resend.
 *
 * Platform-level email (uses global RESEND_API_KEY), separate from the
 * per-org integration EmailClient in lib/integrations/email.ts.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InviteEmailParams {
  recipientEmail: string;
  inviterName: string;
  organizationName: string;
  role: string;
  personalNote?: string;
  inviteLink: string;
}

// ---------------------------------------------------------------------------
// HTML template
// ---------------------------------------------------------------------------

const ROLE_LABELS: Record<string, string> = {
  OWNER: 'Owner',
  ADMIN: 'Admin',
  MANAGER: 'Manager',
  ENGINEER: 'Engineer',
  VIEWER: 'Viewer',
};

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function generateInviteHtml(params: InviteEmailParams): string {
  const { inviterName, organizationName, role, personalNote, inviteLink } = params;
  const roleLabel = ROLE_LABELS[role] || role;
  const safeName = escapeHtml(inviterName);
  const safeOrg = escapeHtml(organizationName);

  const noteBlock = personalNote
    ? `<div style="margin: 20px 0; padding: 16px; background: #f9fafb; border-left: 3px solid #8b5cf6; border-radius: 0 6px 6px 0;">
        <p style="margin: 0; color: #6b7280; font-size: 13px; font-style: italic;">"${escapeHtml(personalNote)}"</p>
        <p style="margin: 6px 0 0; color: #9ca3af; font-size: 12px;">— ${safeName}</p>
      </div>`
    : '';

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f3f4f6; padding: 20px; margin: 0;">
  <div style="max-width: 560px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
    <!-- Header -->
    <div style="background: linear-gradient(135deg, #7c3aed, #6d28d9); padding: 32px 24px; text-align: center;">
      <h1 style="margin: 0; font-size: 22px; color: white; font-weight: 600;">You're invited to join ${safeOrg}</h1>
    </div>

    <!-- Body -->
    <div style="padding: 32px 24px;">
      <p style="color: #374151; line-height: 1.6; margin: 0 0 8px; font-size: 15px;">
        <strong>${safeName}</strong> has invited you to join <strong>${safeOrg}</strong> on Pallisade.
      </p>

      <p style="color: #6b7280; font-size: 14px; margin: 0 0 20px;">
        You've been invited as
        <span style="display: inline-block; padding: 2px 10px; background: #f3f0ff; color: #7c3aed; border-radius: 12px; font-weight: 500; font-size: 13px;">${roleLabel}</span>
      </p>

      ${noteBlock}

      <!-- CTA -->
      <div style="text-align: center; margin: 28px 0;">
        <a href="${inviteLink}" style="display: inline-block; background: linear-gradient(135deg, #7c3aed, #6d28d9); color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px;">
          Accept Invite
        </a>
      </div>

      <p style="color: #9ca3af; font-size: 12px; text-align: center; margin: 0;">
        This invite expires in 7 days. If the button doesn't work, copy this link:<br>
        <a href="${inviteLink}" style="color: #7c3aed; word-break: break-all;">${inviteLink}</a>
      </p>
    </div>

    <!-- Footer -->
    <div style="background: #f9fafb; padding: 16px 24px; border-top: 1px solid #e5e7eb;">
      <p style="margin: 0; font-size: 12px; color: #9ca3af; text-align: center;">
        Sent by <a href="https://pallisade.dev" style="color: #7c3aed; text-decoration: none;">Pallisade</a> — Data Reliability Platform
      </p>
    </div>
  </div>
</body>
</html>`.trim();
}

// ---------------------------------------------------------------------------
// Plain-text fallback
// ---------------------------------------------------------------------------

function generateInviteText(params: InviteEmailParams): string {
  const { inviterName, organizationName, role, personalNote, inviteLink } = params;
  const roleLabel = ROLE_LABELS[role] || role;
  let text = `${inviterName} invited you to join ${organizationName} on Pallisade as ${roleLabel}.\n\n`;
  if (personalNote) {
    text += `"${personalNote}"\n— ${inviterName}\n\n`;
  }
  text += `Accept the invite: ${inviteLink}\n\nThis invite expires in 7 days.`;
  return text;
}

// ---------------------------------------------------------------------------
// Send via Resend
// ---------------------------------------------------------------------------

/**
 * Send an invite email via Resend.
 * Returns true if sent, false if skipped (no API key) or failed.
 */
export async function sendInviteEmail(params: InviteEmailParams): Promise<boolean> {
  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    console.warn('[invite-email] RESEND_API_KEY not set — skipping email');
    return false;
  }

  const fromEmail = process.env.EMAIL_FROM || 'team@pallisade.dev';
  const html = generateInviteHtml(params);
  const text = generateInviteText(params);

  const response = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: `Pallisade <${fromEmail}>`,
      to: [params.recipientEmail],
      subject: `${params.inviterName} invited you to ${params.organizationName} on Pallisade`,
      html,
      text,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    console.error(`[invite-email] Resend API error ${response.status}: ${error}`);
    return false;
  }

  return true;
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/email/invite.ts
git commit -m "feat: add invite email template and Resend send function"
```

---

### Task 2: Write tests for `lib/email/invite.ts`

**Files:**
- Create: `lib/__tests__/invite-email.test.ts`

- [ ] **Step 1: Create test file**

```typescript
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
```

- [ ] **Step 2: Run tests**

Run: `npx vitest run lib/__tests__/invite-email.test.ts`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add lib/__tests__/invite-email.test.ts
git commit -m "test: add unit tests for invite email template and send function"
```

---

### Task 3: Wire email send into POST `/api/team/invite`

**Files:**
- Modify: `app/api/team/invite/route.ts`

- [ ] **Step 1: Add organization include to the currentMember query**

In `app/api/team/invite/route.ts`, find the `currentMember` query (around line 30) and add the organization include:

Replace:
```typescript
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId: currentUserId,
          organizationId,
        },
      },
      include: { user: true },
    });
```

With:
```typescript
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId: currentUserId,
          organizationId,
        },
      },
      include: {
        user: true,
        organization: { select: { name: true } },
      },
    });
```

- [ ] **Step 2: Add import and wire the email send**

Add the import at the top of the file (after existing imports):

```typescript
import { sendInviteEmail } from '@/lib/email/invite';
```

Replace the TODO block (lines 136-137):

```typescript
    // TODO: Send invite email
    // await sendInviteEmail(email, inviteLink, currentMember.user.name || 'Your team', personalNote);
```

With:

```typescript
    // Fire-and-forget email send (don't block the API response)
    sendInviteEmail({
      recipientEmail: email,
      inviterName: currentMember.user.name || currentMember.user.email,
      organizationName: currentMember.organization?.name || 'your team',
      role,
      personalNote: personalNote || undefined,
      inviteLink,
    }).then((sent) => {
      if (sent) {
        prisma.teamInvite.update({
          where: { id: invite.id },
          data: { emailSentAt: new Date() },
        }).catch((err) => console.error('[invite-email] Failed to update emailSentAt:', err));
      }
    }).catch((err) => console.error('[invite-email] Failed to send:', err));
```

- [ ] **Step 3: Commit**

```bash
git add app/api/team/invite/route.ts
git commit -m "feat: wire invite email send into POST /api/team/invite"
```

---

### Task 4: Add PATCH handler for resending invites

**Files:**
- Modify: `app/api/team/invite/route.ts`

- [ ] **Step 1: Add PATCH handler after the existing DELETE handler**

Append this to the end of `app/api/team/invite/route.ts`:

```typescript
// PATCH - Resend invite email
export async function PATCH(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const currentUserId = session.user.id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Check if user is admin
    const currentMember = await prisma.teamMember.findUnique({
      where: {
        userId_organizationId: {
          userId: currentUserId,
          organizationId,
        },
      },
      include: {
        user: true,
        organization: { select: { name: true } },
      },
    });

    if (!currentMember || (currentMember.role !== 'OWNER' && currentMember.role !== 'ADMIN')) {
      return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
    }

    const body = await request.json();
    const { inviteId } = body;

    if (!inviteId) {
      return NextResponse.json({ error: 'inviteId is required' }, { status: 400 });
    }

    // Verify invite belongs to org and is resendable
    const invite = await prisma.teamInvite.findUnique({
      where: { id: inviteId },
    });

    if (!invite || invite.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Invite not found' }, { status: 404 });
    }

    if (invite.status !== 'PENDING') {
      return NextResponse.json({ error: 'Can only resend pending invites' }, { status: 400 });
    }

    // Reset expiry to 7 days from now
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7);

    await prisma.teamInvite.update({
      where: { id: inviteId },
      data: { expiresAt, status: 'PENDING' },
    });

    // Generate invite link and send email
    const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
    const inviteLink = `${baseUrl}/signup?invite=${invite.token}`;

    const sent = await sendInviteEmail({
      recipientEmail: invite.email,
      inviterName: currentMember.user.name || currentMember.user.email,
      organizationName: currentMember.organization?.name || 'your team',
      role: invite.role,
      inviteLink,
    });

    if (sent) {
      await prisma.teamInvite.update({
        where: { id: inviteId },
        data: { emailSentAt: new Date() },
      });
    }

    return NextResponse.json({ success: true, emailSent: sent });

  } catch (error) {
    console.error('Failed to resend invite:', error);
    return NextResponse.json(
      { error: 'Failed to resend invite' },
      { status: 500 },
    );
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/team/invite/route.ts
git commit -m "feat: add PATCH endpoint to resend invite emails"
```

---

### Task 5: Add resend button to team page invite rows

**Files:**
- Modify: `app/(dashboard)/dashboard/team/page.tsx`

- [ ] **Step 1: Add `emailSentAt` to the `PendingInvite` interface**

In `app/(dashboard)/dashboard/team/page.tsx`, find the `PendingInvite` interface (line 52) and add the field:

Replace:
```typescript
interface PendingInvite {
  id: string;
  email: string;
  role: string;
  inviterName: string | null;
  createdAt: string;
  expiresAt: string;
}
```

With:
```typescript
interface PendingInvite {
  id: string;
  email: string;
  role: string;
  inviterName: string | null;
  createdAt: string;
  expiresAt: string;
  emailSentAt: string | null;
}
```

- [ ] **Step 2: Add `RefreshCw` to the lucide-react imports**

In `app/(dashboard)/dashboard/team/page.tsx`, find the import block (lines 8-25):

```typescript
import {
  Users,
  UserPlus,
  Shield,
  Crown,
  Briefcase,
  Code2,
  Eye,
  Search,
  Pencil,
  Trash2,
  X,
  Mail,
  Clock,
  Workflow,
  Activity,
  KeyRound,
} from 'lucide-react';
```

Add `RefreshCw` to the list (e.g. after `KeyRound`).

- [ ] **Step 3: Add resend handler function**

Add this function after the `handleRevokeInvite` function (around line 330):

```typescript
  // Handle resend invite
  const handleResendInvite = async (inviteId: string) => {
    try {
      const res = await fetch('/api/team/invite', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inviteId }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to resend invite');
      }
      fetchTeamData(); // Refresh to show updated emailSentAt
    } catch (err: any) {
      console.error('Resend invite failed:', err);
    }
  };
```

- [ ] **Step 4: Add resend button and email sent info to invite rows**

In the invite row rendering (around line 713, inside the `<div className="flex items-center gap-3">` that contains the role badge and revoke button), add the resend button before the revoke button.

Replace the block:
```typescript
                      {isAdmin && (
                        <button
                          onClick={() => handleRevokeInvite(invite.id)}
                          className="p-2 rounded-lg text-[var(--text-faint)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Revoke invite"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
```

With:
```typescript
                      {invite.emailSentAt && (
                        <span className="text-[10px] text-[var(--text-faint)]">
                          Emailed {formatDate(invite.emailSentAt)}
                        </span>
                      )}
                      {isAdmin && (
                        <button
                          onClick={() => handleResendInvite(invite.id)}
                          className="p-2 rounded-lg text-[var(--text-faint)] hover:text-violet-400 hover:bg-violet-500/10 transition-colors"
                          title="Resend invite email"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {isAdmin && (
                        <button
                          onClick={() => handleRevokeInvite(invite.id)}
                          className="p-2 rounded-lg text-[var(--text-faint)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Revoke invite"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
```

- [ ] **Step 5: Commit**

```bash
git add app/(dashboard)/dashboard/team/page.tsx
git commit -m "feat: add resend invite button and email sent timestamp to team page"
```

---

### Task 6: Add `emailSentAt` to the team API response

**Files:**
- Modify: `app/api/team/route.ts`

- [ ] **Step 1: Add `emailSentAt` to the pending invites response mapping**

In `app/api/team/route.ts`, find the invite mapping (line 118-125):

```typescript
    const invites = pendingInvites.map(invite => ({
      id: invite.id,
      email: invite.email,
      role: invite.role,
      inviterName: invite.inviterName,
      createdAt: invite.createdAt.toISOString(),
      expiresAt: invite.expiresAt.toISOString(),
    }));
```

Replace with:

```typescript
    const invites = pendingInvites.map(invite => ({
      id: invite.id,
      email: invite.email,
      role: invite.role,
      inviterName: invite.inviterName,
      createdAt: invite.createdAt.toISOString(),
      expiresAt: invite.expiresAt.toISOString(),
      emailSentAt: invite.emailSentAt?.toISOString() || null,
    }));
```

- [ ] **Step 2: Commit**

```bash
git add app/api/team/route.ts
git commit -m "feat: include emailSentAt in team API invite response"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run all tests**

Run: `npx vitest run lib/__tests__/invite-email.test.ts`
Expected: All tests pass.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors in the changed files.

- [ ] **Step 3: Commit any fixes if needed**

- [ ] **Step 4: Final commit with all changes**

```bash
git add -A
git status
```

Verify only expected files are staged. If clean, no additional commit needed.
