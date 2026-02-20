import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

interface ScanAlert {
  scanType: string;
  score: number;
  criticalCount: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
  totalFindings: number;
  reportId: string;
  reportTitle: string;
}

const SLACK_API = 'https://slack.com/api/chat.postMessage';

// Send alert to Slack after scan completes
export async function sendScanAlert(organizationId: string, alert: ScanAlert) {
  try {
    // Get Slack integration
    const slackIntegration = await prisma.integration.findFirst({
      where: {
        organizationId,
        type: 'SLACK',
        status: 'ACTIVE',
      },
    });

    if (!slackIntegration?.accessToken) return;

    let botToken: string;
    try {
      botToken = decrypt(slackIntegration.accessToken);
    } catch {
      console.error('[alerts] Failed to decrypt Slack bot token');
      return;
    }

    const config = typeof slackIntegration.credentials === 'string'
      ? JSON.parse(slackIntegration.credentials)
      : (slackIntegration.credentials as Record<string, any> || {});
    const { channel, alertOnCritical, alertOnHigh, alertOnScanComplete } = config;

    if (!channel) return;

    // Check if we should send an alert
    const hasCritical = alert.criticalCount > 0;
    const hasHigh = alert.highCount > 0;

    const shouldAlert =
      alertOnScanComplete ||
      (alertOnCritical && hasCritical) ||
      (alertOnHigh && hasHigh);

    if (!shouldAlert) return;

    // Build message
    const emoji = hasCritical ? '🚨' : hasHigh ? '⚠️' : alert.score >= 90 ? '✅' : '📊';
    const status = hasCritical ? 'CRITICAL' : hasHigh ? 'WARNING' : alert.score >= 90 ? 'HEALTHY' : 'NEEDS ATTENTION';
    const color = hasCritical ? '#dc2626' : hasHigh ? '#f59e0b' : alert.score >= 90 ? '#10b981' : '#3b82f6';

    const scanTypeNames: Record<string, string> = {
      DATA_FRESHNESS: 'Freshness',
      DATA_QUALITY: 'Quality',
      SCHEMA_DRIFT: 'Schema',
      PERIMETER_SECURITY: 'Secrets',
      PIPELINE_HEALTH: 'Pipeline',
    };

    const scanName = scanTypeNames[alert.scanType] || alert.scanType;

    const payload = {
      channel,
      attachments: [
        {
          color,
          blocks: [
            {
              type: 'section',
              text: {
                type: 'mrkdwn',
                text: `${emoji} *${scanName} Scan Complete*\n*Status:* ${status} | *DRR Score:* ${alert.score}/100`,
              },
            },
            {
              type: 'section',
              fields: [
                { type: 'mrkdwn', text: `*Critical:* ${alert.criticalCount}` },
                { type: 'mrkdwn', text: `*High:* ${alert.highCount}` },
                { type: 'mrkdwn', text: `*Medium:* ${alert.mediumCount}` },
                { type: 'mrkdwn', text: `*Low:* ${alert.lowCount}` },
              ],
            },
            {
              type: 'actions',
              elements: [
                {
                  type: 'button',
                  text: { type: 'plain_text', text: 'View Report' },
                  url: `${process.env.NEXTAUTH_URL || 'http://localhost:3000'}/dashboard/reports/${alert.reportId}`,
                  style: hasCritical ? 'danger' : 'primary',
                },
              ],
            },
          ],
        },
      ],
      text: `${emoji} ${scanName} Scan Complete — ${status}`,
    };

    const res = await fetch(SLACK_API, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${botToken}`,
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (data.ok) {
      console.log(`Slack alert sent for ${alert.scanType} scan`);
    } else {
      console.error(`Slack API error: ${data.error}`);
    }
  } catch (error) {
    console.error('Failed to send Slack alert:', error);
    // Don't throw - alerts shouldn't break scans
  }
}

// Send alert for specific finding
export async function sendFindingAlert(
  organizationId: string,
  finding: {
    title: string;
    severity: string;
    table?: string;
    description?: string;
    reportId: string;
  }
) {
  try {
    const slackIntegration = await prisma.integration.findFirst({
      where: {
        organizationId,
        type: 'SLACK',
        status: 'ACTIVE',
      },
    });

    if (!slackIntegration?.accessToken) return;

    let botToken: string;
    try {
      botToken = decrypt(slackIntegration.accessToken);
    } catch {
      console.error('[alerts] Failed to decrypt Slack bot token');
      return;
    }

    const config = typeof slackIntegration.credentials === 'string'
      ? JSON.parse(slackIntegration.credentials)
      : (slackIntegration.credentials as Record<string, any> || {});
    const { channel, alertOnCritical, alertOnHigh } = config;

    if (!channel) return;

    // Only alert on critical/high based on settings
    if (finding.severity === 'critical' && !alertOnCritical) return;
    if (finding.severity === 'high' && !alertOnHigh) return;
    if (finding.severity !== 'critical' && finding.severity !== 'high') return;

    const emoji = finding.severity === 'critical' ? '🚨' : '⚠️';
    const color = finding.severity === 'critical' ? '#dc2626' : '#f59e0b';

    const payload = {
      channel,
      attachments: [
        {
          color,
          blocks: [
            {
              type: 'section',
              text: {
                type: 'mrkdwn',
                text: `${emoji} *${finding.severity.toUpperCase()} Issue Found*\n${finding.title}`,
              },
            },
            ...(finding.table ? [{
              type: 'context',
              elements: [
                { type: 'mrkdwn', text: `📊 Table: \`${finding.table}\`` },
              ],
            }] : []),
            {
              type: 'actions',
              elements: [
                {
                  type: 'button',
                  text: { type: 'plain_text', text: 'View Details' },
                  url: `${process.env.NEXTAUTH_URL || 'http://localhost:3000'}/dashboard/reports/${finding.reportId}`,
                  style: 'danger',
                },
              ],
            },
          ],
        },
      ],
      text: `${emoji} ${finding.severity.toUpperCase()} Issue Found: ${finding.title}`,
    };

    const res = await fetch(SLACK_API, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${botToken}`,
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!data.ok) {
      console.error(`Slack API error: ${data.error}`);
    }
  } catch (error) {
    console.error('Failed to send finding alert:', error);
  }
}
