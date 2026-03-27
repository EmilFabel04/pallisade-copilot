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
