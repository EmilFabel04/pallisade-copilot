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
    ? `<tr><td style="padding: 0 40px;">
        <div style="margin: 0 0 24px; padding: 16px 20px; background: #fef2f2; border-left: 3px solid #a51a1f; border-radius: 0 6px 6px 0;">
          <p style="margin: 0; color: #555; font-size: 14px; line-height: 1.5; font-style: italic;">"${escapeHtml(personalNote)}"</p>
          <p style="margin: 8px 0 0; color: #999; font-size: 12px;">— ${safeName}</p>
        </div>
      </td></tr>`
    : '';

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Team Invite</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: #f0f0f0; margin: 0; padding: 0;">
  <!-- Outer wrapper -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #f0f0f0; padding: 40px 20px;">
    <tr><td align="center">
      <!-- Card -->
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width: 560px; width: 100%; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header with logo -->
        <tr><td style="background: linear-gradient(135deg, #7a0a0e 0%, #a51a1f 100%); padding: 36px 40px 32px; text-align: center;">
          <!-- Pallisade emblem (inline SVG as img) -->
          <div style="margin: 0 0 16px;">
            <img src="https://pallisade.dev/pallisade_emblem.svg" alt="Pallisade" width="44" height="44" style="display: inline-block; width: 44px; height: 44px; filter: brightness(0) invert(1);" />
          </div>
          <h1 style="margin: 0; font-size: 21px; color: #ffffff; font-weight: 600; line-height: 1.3;">You're invited to join<br>${safeOrg}</h1>
        </td></tr>

        <!-- Divider accent line -->
        <tr><td style="height: 3px; background: linear-gradient(90deg, #7a0a0e, #a51a1f, #7a0a0e);"></td></tr>

        <!-- Body -->
        <tr><td style="padding: 36px 40px 0;">
          <p style="color: #1a1a1a; line-height: 1.6; margin: 0 0 6px; font-size: 15px;">
            <strong>${safeName}</strong> has invited you to join <strong>${safeOrg}</strong> on Pallisade.
          </p>
          <p style="color: #666; font-size: 14px; margin: 0 0 28px; line-height: 1.5;">
            You've been invited as
            <span style="display: inline-block; padding: 3px 12px; background: #fef2f2; color: #a51a1f; border-radius: 12px; font-weight: 600; font-size: 12px; letter-spacing: 0.02em;">${roleLabel}</span>
          </p>
        </td></tr>

        <!-- Personal note (conditional) -->
        ${noteBlock}

        <!-- CTA Button -->
        <tr><td style="padding: 4px 40px 32px; text-align: center;">
          <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 0 auto;">
            <tr><td style="border-radius: 8px; background: linear-gradient(135deg, #7a0a0e, #a51a1f);">
              <a href="${inviteLink}" style="display: inline-block; padding: 14px 36px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 15px; letter-spacing: 0.02em;">
                Accept Invite
              </a>
            </td></tr>
          </table>
        </td></tr>

        <!-- Subtle divider -->
        <tr><td style="padding: 0 40px;">
          <div style="height: 1px; background: #eee;"></div>
        </td></tr>

        <!-- Link fallback -->
        <tr><td style="padding: 20px 40px 28px; text-align: center;">
          <p style="color: #aaa; font-size: 12px; margin: 0; line-height: 1.5;">
            This invite expires in 7 days.<br>
            If the button doesn't work, copy this link:
          </p>
          <p style="margin: 8px 0 0;">
            <a href="${inviteLink}" style="color: #a51a1f; font-size: 11px; word-break: break-all; text-decoration: none;">${inviteLink}</a>
          </p>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background: #fafafa; padding: 20px 40px; border-top: 1px solid #f0f0f0; text-align: center;">
          <p style="margin: 0; font-size: 12px; color: #bbb;">
            <a href="https://pallisade.dev" style="color: #a51a1f; text-decoration: none; font-weight: 500;">Pallisade</a>
            <span style="color: #ddd; margin: 0 6px;">|</span>
            Data Reliability Platform
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
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
