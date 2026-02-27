import { NextRequest, NextResponse } from 'next/server';
import { SlackClient } from '@/lib/integrations/slack';
import { PagerDutyClient } from '@/lib/integrations/pagerduty';
import { EmailClient } from '@/lib/integrations/email';
import { TeamsClient } from '@/lib/integrations/teams';
import { OpsgenieClient } from '@/lib/integrations/opsgenie';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

// POST /api/schedule/alert - Dispatch alert notifications
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const {
      taskId,
      taskName,
      status,
      message,
      channels,
      config: alertConfig,
      organizationId,
    } = body;

    if (!channels || channels.length === 0) {
      return NextResponse.json({ message: 'No channels configured' });
    }

    // Fetch alert integration configs from the org
    // Channels come as lowercase (e.g. "slack") but Prisma IntegrationType is uppercase
    const channelTypesUpper = (channels as string[]).map((c: string) => c.toUpperCase());
    const integrations = await prisma.integration.findMany({
      where: {
        organizationId,
        type: { in: channelTypesUpper as any },
        status: 'ACTIVE',
      },
    });

    const slackSeverity = (status === 'FAIL' ? 'critical' : status === 'WARN' ? 'high' : 'medium') as 'critical' | 'high' | 'medium' | 'low';
    const pdSeverity = (status === 'FAIL' ? 'critical' : status === 'WARN' ? 'warning' : 'info') as 'critical' | 'error' | 'warning' | 'info';
    const results: Array<{ channel: string; success: boolean; error?: string }> = [];

    for (const channel of channels as string[]) {
      const integration = integrations.find((i) => i.type.toLowerCase() === channel.toLowerCase());
      const channelConfig = alertConfig?.[channel] || {};

      try {
        if (channel === 'slack') {
          let botToken = '';
          if (integration?.accessToken) {
            try { botToken = decrypt(integration.accessToken); } catch {}
          }
          const creds = integration?.credentials
            ? (typeof integration.credentials === 'string' ? JSON.parse(integration.credentials) : integration.credentials) as Record<string, any>
            : {};
          const slackChannel = channelConfig.channel || creds.channel;

          if (botToken) {
            const client = new SlackClient({ bot_token: botToken, channel: slackChannel });
            await client.sendMessage({
              title: `Task Alert: ${taskName}`,
              text: message || `Task "${taskName}" completed with status: ${status}`,
              severity: slackSeverity,
              fields: [
                { label: 'Status', value: status },
                { label: 'Task', value: taskName },
              ],
            });
            results.push({ channel: 'slack', success: true });
          } else {
            results.push({ channel: 'slack', success: false, error: 'No bot token configured' });
          }
        } else if (channel === 'email') {
          const recipients =
            channelConfig.recipients ||
            (integration?.config as any)?.recipients;
          if (recipients) {
            const client = new EmailClient({
              recipients,
              smtp_host: channelConfig.smtp_host || (integration?.config as any)?.smtp_host,
              smtp_port: channelConfig.smtp_port || (integration?.config as any)?.smtp_port,
            });
            const alertText = message || `Task "${taskName}" completed with status: ${status}`;
            await client.sendEmail({
              subject: `Task Alert: ${taskName} — ${status}`,
              text: alertText,
              html: `<p><strong>${taskName}</strong> completed with status: <strong>${status}</strong></p><p>${alertText}</p>`,
              severity: slackSeverity,
            });
            results.push({ channel: 'email', success: true });
          } else {
            results.push({ channel: 'email', success: false, error: 'No recipients' });
          }
        } else if (channel === 'pagerduty') {
          const routingKey =
            channelConfig.routing_key ||
            (integration?.config as any)?.routing_key;
          if (routingKey) {
            const client = new PagerDutyClient({
              api_key: (integration?.config as any)?.api_key || '',
              service_id: (integration?.config as any)?.service_id || '',
              routing_key: routingKey,
            });
            await client.createIncident({
              title: `Task Alert: ${taskName}`,
              description: message || `Task "${taskName}" completed with status: ${status}`,
              severity: pdSeverity,
            });
            results.push({ channel: 'pagerduty', success: true });
          } else {
            results.push({ channel: 'pagerduty', success: false, error: 'No routing key' });
          }
        } else if (channel === 'teams') {
          const webhookUrl =
            channelConfig.webhook_url ||
            (integration?.config as any)?.webhook_url;
          if (webhookUrl) {
            const client = new TeamsClient({ webhook_url: webhookUrl });
            await client.sendMessage({
              title: `Task Alert: ${taskName}`,
              text: message || `Task "${taskName}" completed with status: ${status}`,
              severity: slackSeverity,
            });
            results.push({ channel: 'teams', success: true });
          } else {
            results.push({ channel: 'teams', success: false, error: 'No webhook URL' });
          }
        } else if (channel === 'opsgenie') {
          const apiKey =
            channelConfig.api_key ||
            (integration?.config as any)?.api_key;
          if (apiKey) {
            const ogPriority = (status === 'FAIL' ? 'P1' : status === 'WARN' ? 'P2' : 'P3') as 'P1' | 'P2' | 'P3' | 'P4' | 'P5';
            const client = new OpsgenieClient({ api_key: apiKey });
            await client.createAlert({
              message: `Task Alert: ${taskName}`,
              description: message || `Task "${taskName}" completed with status: ${status}`,
              priority: ogPriority,
              tags: ['pallisade', 'scheduled-task'],
            });
            results.push({ channel: 'opsgenie', success: true });
          } else {
            results.push({ channel: 'opsgenie', success: false, error: 'No API key' });
          }
        }
      } catch (err: any) {
        console.error(`[Alert] Failed to send to ${channel}:`, err);
        results.push({ channel, success: false, error: err.message });
      }
    }

    return NextResponse.json({ results });
  } catch (error: any) {
    console.error('[Alert] Dispatch error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
