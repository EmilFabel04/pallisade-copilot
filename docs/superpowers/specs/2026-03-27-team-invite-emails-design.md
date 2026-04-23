# Team Invite Emails — Design Spec

## Problem

When an admin invites a team member via the Invite modal, the system creates a `TeamInvite` record and generates an invite link — but **no email is sent**. The admin must manually copy the link and share it. Line 136 of `app/api/team/invite/route.ts` has a TODO for this.

## Goal

Wire up Resend to send a branded invite email when an admin creates or resends an invite. The email contains the invite link, inviter context, and role info so the recipient can accept with one click.

## Scope

### In scope
- `sendInviteEmail()` function using the existing `EmailClient` + Resend
- Branded HTML invite template (consistent with existing alert template style)
- Wire into POST `/api/team/invite` (new invites)
- Resend invite support: new PATCH endpoint + UI button on team page for pending/expired invites
- Update `emailSentAt` on the `TeamInvite` record after successful send
- Env vars: `RESEND_API_KEY`, `EMAIL_FROM` (optional, defaults to `team@pallisade.dev`)
- Graceful degradation: if no `RESEND_API_KEY` is set, skip email silently (invite link still works)

### Out of scope
- Acceptance confirmation email
- Email preferences / unsubscribe (one-off transactional emails)
- Bulk invite via CSV
- SendGrid / SMTP (Resend only for now; existing `EmailClient` multi-provider support remains)

## Architecture

### New file: `lib/email/invite.ts`

Single-purpose module with two exports:

```typescript
interface InviteEmailParams {
  recipientEmail: string;
  inviterName: string;
  organizationName: string;
  role: string;
  personalNote?: string;
  inviteLink: string;
}

// Sends the invite email via Resend. Returns silently if RESEND_API_KEY is not set.
export async function sendInviteEmail(params: InviteEmailParams): Promise<boolean>

// Generates the HTML template (exported for testing)
export function generateInviteHtml(params: InviteEmailParams): string
```

**Why a separate file instead of adding to `lib/integrations/email.ts`?**
The existing `EmailClient` is designed for alert-style emails tied to integration configs (per-org SMTP/Resend/SendGrid settings stored in the DB). Invite emails are a platform-level concern — they use a global Resend API key, not per-org integration configs. Keeping them separate avoids coupling invite delivery to the integration system.

### Email template

Inline HTML (same approach as `generateAlertHtml`). Structure:

1. **Header** — Pallisade logo/brand bar (violet gradient, matching app theme)
2. **Body** — "{inviterName} invited you to join {organizationName} on Pallisade"
3. **Role badge** — "You've been invited as an {role}"
4. **Personal note** — Blockquote if provided, omitted otherwise
5. **CTA button** — "Accept Invite" linking to `inviteLink` (`/signup?invite={token}`)
6. **Footer** — "This invite expires in 7 days" + Pallisade branding

Plain-text fallback included for email clients that don't render HTML.

### Wiring into invite API

**`app/api/team/invite/route.ts` POST handler** — after creating/upserting the invite:

```typescript
// Fire-and-forget email send (don't block the API response)
sendInviteEmail({
  recipientEmail: email,
  inviterName: currentMember.user.name || currentMember.user.email,
  organizationName: org.name,
  role,
  personalNote,
  inviteLink,
}).then(sent => {
  if (sent) {
    // Update emailSentAt
    prisma.teamInvite.update({
      where: { id: invite.id },
      data: { emailSentAt: new Date() },
    }).catch(err => console.error('[invite-email] Failed to update emailSentAt:', err));
  }
}).catch(err => console.error('[invite-email] Failed to send:', err));
```

This is fire-and-forget. The API response returns immediately with the invite link (existing behavior preserved). Email failure doesn't block the invite creation.

### Resend invite support

**New PATCH handler in `app/api/team/invite/route.ts`:**
- Accepts `{ inviteId: string }`
- Admin-only (same auth check as POST/DELETE)
- Validates invite belongs to org
- Resets `expiresAt` to 7 days from now
- Re-sends the email
- Updates `emailSentAt`
- Works for PENDING invites (including expired ones — resets expiry)

**Team page UI change (`app/(dashboard)/dashboard/team/page.tsx`):**
- Add a "Resend" button on pending/expired invite rows (next to existing Revoke button)
- Shows "Email sent" timestamp if `emailSentAt` is set
- Resend button calls PATCH `/api/team/invite`

### Env vars

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RESEND_API_KEY` | No | — | Resend API key. If not set, invite emails are skipped silently |
| `EMAIL_FROM` | No | `team@pallisade.dev` | Sender address (must be on a verified Resend domain) |

### Organization name lookup

The POST handler currently doesn't fetch the org name. We need to add an `organization` include to the existing query or do a separate lookup to get `organization.name` for the email template. Simplest: add `include: { organization: { select: { name: true } } }` to the `currentMember` query (line 30-38).

## Error Handling

- **No API key**: `sendInviteEmail` checks `process.env.RESEND_API_KEY`. If missing, logs a warning and returns `false`. No error thrown.
- **Resend API failure**: Caught in the fire-and-forget `.catch()`. Logged to console. Invite is still created; admin still gets the link.
- **Invalid email**: Resend validates the recipient. If it rejects, same as above — logged, not blocking.
- **Rate limiting**: Resend's free tier allows 100 emails/day. No app-level rate limiting needed for team invites (volume is naturally low).

## Testing

- Unit test for `generateInviteHtml`: verify template renders all fields, handles missing optional fields (no personalNote), escapes HTML in user-provided strings
- Unit test for `sendInviteEmail`: mock fetch, verify Resend API call shape, verify graceful skip when no API key
- Manual E2E: invite a real email, verify delivery and link works

## Files Changed

| File | Change |
|------|--------|
| `lib/email/invite.ts` | **New** — `sendInviteEmail()` + `generateInviteHtml()` |
| `app/api/team/invite/route.ts` | Wire email send in POST, add PATCH handler for resend |
| `app/(dashboard)/dashboard/team/page.tsx` | Add resend button on invite rows |
| `.env.example` | Add `RESEND_API_KEY`, `EMAIL_FROM` |
| `lib/email/invite.test.ts` | **New** — unit tests |
