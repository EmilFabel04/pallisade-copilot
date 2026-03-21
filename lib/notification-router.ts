import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';
import { PagerDutyClient } from '@/lib/integrations/pagerduty';
import { TeamsClient } from '@/lib/integrations/teams';
import { OpsgenieClient } from '@/lib/integrations/opsgenie';
import { EmailClient } from '@/lib/integrations/email';

type Severity = 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';

interface RouteParams {
  organizationId: string;
  severity: Severity;
  title: string;
  message: string;
  metadata?: Record<string, unknown>;
  actionUrl?: string;
  isRecovery?: boolean;
}

interface Destination {
  integrationId: string;
  channel?: string;
  config?: Record<string, unknown>;
}

function toSlackSeverity(s: Severity): 'critical' | 'high' | 'medium' | 'low' {
  if (s === 'CRITICAL') return 'critical';
  if (s === 'ERROR') return 'high';
  if (s === 'WARN') return 'medium';
  return 'low';
}

function toPdSeverity(s: Severity): 'critical' | 'error' | 'warning' | 'info' {
  if (s === 'CRITICAL') return 'critical';
  if (s === 'ERROR') return 'error';
  if (s === 'WARN') return 'warning';
  return 'info';
}

function toOgPriority(s: Severity): 'P1' | 'P2' | 'P3' | 'P4' {
  if (s === 'CRITICAL') return 'P1';
  if (s === 'ERROR') return 'P2';
  if (s === 'WARN') return 'P3';
  return 'P4';
}

export async function routeNotification(params: RouteParams): Promise<void> {
  try {
    const route = await prisma.notificationRoute.findUnique({
      where: {
        organizationId_severity: {
          organizationId: params.organizationId,
          severity: params.severity,
        },
      },
    });

    if (!route || !route.enabled) return;
    if (params.isRecovery && !route.notifyOnRecovery) return;

    const destinations = (route.destinations || []) as Destination[];
    if (destinations.length === 0) return;

    const integrationIds = destinations.map((d) => d.integrationId);
    const integrations = await prisma.integration.findMany({
      where: { id: { in: integrationIds }, status: 'ACTIVE' },
    });

    const integrationMap = new Map(integrations.map((i) => [i.id, i]));

    for (const dest of destinations) {
      const integration = integrationMap.get(dest.integrationId);
      if (!integration) {
        console.warn(`[NotificationRouter] Integration ${dest.integrationId} not found or inactive, skipping`);
        continue;
      }

      try {
        const type = integration.type.toLowerCase();
        const creds = integration.credentials
          ? (typeof integration.credentials === 'string'
              ? JSON.parse(integration.credentials)
              : integration.credentials) as Record<string, any>
          : {};
        const config = (integration.config || {}) as Record<string, any>;

        if (type === 'slack') {
          let botToken = '';
          if (integration.accessToken) {
            try { botToken = decrypt(integration.accessToken); } catch {}
          }
          if (!botToken) continue;
          const channel = dest.channel || creds.channel;
          const client = new SlackClient({ bot_token: botToken, channel });
          await client.sendMessage({
            title: params.title,
            text: params.message,
            severity: toSlackSeverity(params.severity),
            fields: params.actionUrl
              ? [{ label: 'Link', value: params.actionUrl }]
              : undefined,
          });
        } else if (type === 'pagerduty') {
          const routingKey = (dest.config as any)?.routing_key || config.routing_key;
          if (!routingKey) continue;
          const client = new PagerDutyClient({
            api_key: config.api_key || '',
            service_id: config.service_id || '',
            routing_key: routingKey,
          });
          await client.createIncident({
            title: params.title,
            description: params.message,
            severity: toPdSeverity(params.severity),
          });
        } else if (type === 'teams') {
          const webhookUrl = (dest.config as any)?.webhook_url || config.webhook_url;
          if (!webhookUrl) continue;
          const client = new TeamsClient({ webhook_url: webhookUrl });
          await client.sendMessage({
            title: params.title,
            text: params.message,
            severity: toSlackSeverity(params.severity),
          });
        } else if (type === 'opsgenie') {
          const apiKey = (dest.config as any)?.api_key || config.api_key;
          if (!apiKey) continue;
          const client = new OpsgenieClient({ api_key: apiKey });
          await client.createAlert({
            message: params.title,
            description: params.message,
            priority: toOgPriority(params.severity),
            tags: ['pallisade', 'notification-router'],
          });
        } else if (type === 'email') {
          const recipients = (dest.config as any)?.recipients || config.recipients;
          if (!recipients) continue;
          const client = new EmailClient({
            recipients,
            smtp_host: config.smtp_host,
            smtp_port: config.smtp_port,
          });
          await client.sendEmail({
            subject: params.title,
            text: params.message,
            html: `<p><strong>${params.title}</strong></p><p>${params.message}</p>`,
            severity: toSlackSeverity(params.severity),
          });
        }
      } catch (err: any) {
        console.error(`[NotificationRouter] Failed to dispatch to ${integration.type}:`, err.message);
      }
    }
  } catch (err: any) {
    console.error('[NotificationRouter] Route lookup error:', err.message);
  }
}
