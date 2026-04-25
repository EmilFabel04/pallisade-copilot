import { NextRequest, NextResponse } from 'next/server';
import { SlackClient } from '@/lib/integrations/slack';
import { PagerDutyClient } from '@/lib/integrations/pagerduty';
import { EmailClient } from '@/lib/integrations/email';
import { TeamsClient } from '@/lib/integrations/teams';
import { OpsgenieClient } from '@/lib/integrations/opsgenie';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { notify } from '@/lib/notifications';
import { verifyInternalApiKey, INTERNAL_API_KEY_HEADER } from '@/lib/internal-api-key';

/**
 * Dispatch alert notifications for a monitor run.
 *
 * Routing precedence (first match wins):
 *   1. Monitor.alertConfig.destinations — per-destination integration IDs,
 *      each with its own triggerOn states and optional config overrides.
 *   2. MonitorGroup.alertConfig.destinations — inherited group defaults.
 *   3. Monitor.alertChannels / Group.alertChannels — legacy channel-type fanout
 *      (picks the first ACTIVE integration of each type in the org).
 *
 * A destination only fires if the run status is in its triggerOn set. The
 * special "RECOVERED" state fires when `recovered === true` in the request
 * body (set by the alert engine when a monitor transitions back to PASS).
 */

interface DestinationSpec {
  integrationId: string;
  channelType: string;
  triggerOn: string[];
  config?: Record<string, any>;
}

export async function POST(request: NextRequest) {
  // Trusted server-to-server only (Python scheduler, internal route hops).
  // No browser/user calls — auth via static shared secret.
  if (!verifyInternalApiKey(request.headers.get(INTERNAL_API_KEY_HEADER))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  try {
    const body = await request.json();
    const {
      taskId, // Monitor.id — used to resolve per-monitor destinations
      taskName,
      status,
      message,
      channels, // legacy: array of channel-type strings (e.g. ["slack", "email"])
      config: legacyAlertConfig, // legacy: { slack: {...}, email: {...} }
      organizationId,
      recovered, // optional: set by alert engine when monitor transitions back to PASS
    } = body;

    // --- Resolve destinations ------------------------------------------------
    let destinations: DestinationSpec[] = [];

    if (taskId) {
      // Try Monitor first, then fall back to MonitorGroup (group summary alerts
      // from the scanner send the MonitorGroup.id as taskId).
      const monitor = await prisma.monitor.findUnique({
        where: { id: taskId },
        include: { monitorGroup: true },
      });

      if (monitor) {
        const monitorDest = (monitor.alertConfig as any)?.destinations;
        const groupDest = (monitor.monitorGroup?.alertConfig as any)?.destinations;
        if (Array.isArray(monitorDest) && monitorDest.length > 0) {
          destinations = monitorDest;
        } else if (Array.isArray(groupDest) && groupDest.length > 0) {
          destinations = groupDest;
        }
      } else {
        // taskId might be a MonitorGroup.id (scanner group summary alerts)
        const group = await prisma.monitorGroup.findUnique({
          where: { id: taskId },
        });
        const groupDest = (group?.alertConfig as any)?.destinations;
        if (Array.isArray(groupDest) && groupDest.length > 0) {
          destinations = groupDest;
        }
      }
    }

    // Org-wide defaults fallback: read from NotificationRoute.ORG_DEFAULTS
    if (destinations.length === 0 && organizationId) {
      const orgRoute = await prisma.notificationRoute.findUnique({
        where: {
          organizationId_severity: {
            organizationId,
            severity: 'ORG_DEFAULTS',
          },
        },
      });
      const orgDest = (orgRoute?.destinations as any);
      if (orgRoute?.enabled && Array.isArray(orgDest) && orgDest.length > 0) {
        destinations = orgDest;
      }
    }

    // Legacy fallback: build destinations from the old channels array by
    // picking the first active integration of each requested channel type.
    if (destinations.length === 0 && Array.isArray(channels) && channels.length > 0) {
      const channelTypesUpper = (channels as string[]).map((c: string) => c.toUpperCase());
      const integrations = await prisma.integration.findMany({
        where: {
          organizationId,
          type: { in: channelTypesUpper as any },
          status: 'ACTIVE',
        },
      });
      destinations = integrations.map((i) => ({
        integrationId: i.id,
        channelType: i.type.toLowerCase(),
        triggerOn: ['FAIL', 'WARN', 'ERROR'],
        config: legacyAlertConfig?.[i.type.toLowerCase()] || {},
      }));
    }

    // --- In-app notification (always, independent of external destinations) --
    // The Python scheduler / alert engine hits this endpoint when a scheduled
    // monitor run produces FAIL / WARN / ERROR / RECOVERED. We want those to
    // appear in the bell dropdown regardless of whether Slack / PagerDuty /
    // etc. are configured. Must run BEFORE the `destinations.length === 0`
    // early return so orgs with no external channels still get the bell alert.
    if (organizationId) {
      const inAppState: string = recovered ? 'RECOVERED' : (status || 'INFO');
      const severity: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL' =
        inAppState === 'FAIL' ? 'ERROR'
        : inAppState === 'ERROR' ? 'ERROR'
        : inAppState === 'WARN' ? 'WARN'
        : 'INFO';
      const title = recovered
        ? `Recovered: ${taskName || 'Monitor'}`
        : `${taskName || 'Monitor'}: ${inAppState}`;
      const inAppMessage = message || `Monitor "${taskName || 'unknown'}" is now in state ${inAppState}`;
      notify({
        organizationId,
        eventType: recovered ? 'monitor.recovered' : 'monitor.alert',
        severity,
        title,
        message: inAppMessage,
        entityType: 'monitor',
        entityId: taskId || undefined,
        // Dedupe identical alerts within the 15-min window so the bell doesn't
        // get spammed by back-to-back retries.
        dedupeKey: taskId ? `monitor.alert:${taskId}:${inAppState}` : undefined,
        actionUrl: taskId ? `/dashboard/monitors?monitorId=${taskId}` : undefined,
      }).catch(() => {});
    }

    if (destinations.length === 0) {
      return NextResponse.json({ message: 'No destinations configured' });
    }

    // --- Filter by triggerOn -------------------------------------------------
    const triggerState = recovered ? 'RECOVERED' : status;
    const firing = destinations.filter((d) => {
      const triggers = Array.isArray(d.triggerOn) && d.triggerOn.length > 0
        ? d.triggerOn
        : ['FAIL', 'ERROR'];
      return triggers.includes(triggerState);
    });

    if (firing.length === 0) {
      return NextResponse.json({
        message: `No destinations listen for state ${triggerState}`,
        skipped: destinations.length,
      });
    }

    // --- Load the exact integration rows for firing destinations -------------
    const integrationIds = firing.map((d) => d.integrationId);
    const integrations = await prisma.integration.findMany({
      where: { id: { in: integrationIds }, organizationId, status: 'ACTIVE' },
    });
    const integrationMap = new Map(integrations.map((i) => [i.id, i]));

    const slackSeverity = (triggerState === 'FAIL' ? 'critical'
      : triggerState === 'WARN' ? 'high'
      : triggerState === 'RECOVERED' ? 'low'
      : 'medium') as 'critical' | 'high' | 'medium' | 'low';
    const pdSeverity = (triggerState === 'FAIL' ? 'critical'
      : triggerState === 'WARN' ? 'warning'
      : 'info') as 'critical' | 'error' | 'warning' | 'info';

    const results: Array<{ integrationId: string; channel: string; success: boolean; error?: string }> = [];

    for (const dest of firing) {
      const integration = integrationMap.get(dest.integrationId);
      if (!integration) {
        results.push({
          integrationId: dest.integrationId,
          channel: dest.channelType,
          success: false,
          error: 'Integration not found or inactive',
        });
        continue;
      }

      const channelType = (dest.channelType || integration.type).toLowerCase();
      const cfg = dest.config || {};
      const title = recovered ? `Recovered: ${taskName}` : `Task Alert: ${taskName}`;
      const text = message || `Monitor "${taskName}" is now in state ${triggerState}`;

      try {
        if (channelType === 'slack') {
          let botToken = '';
          if (integration.accessToken) {
            try { botToken = decrypt(integration.accessToken); } catch {}
          }
          const creds = integration.credentials
            ? (typeof integration.credentials === 'string'
              ? JSON.parse(integration.credentials)
              : integration.credentials) as Record<string, any>
            : {};
          const slackChannel = cfg.channel || creds.channel;
          if (!botToken) {
            results.push({ integrationId: dest.integrationId, channel: 'slack', success: false, error: 'No bot token configured' });
            continue;
          }
          const client = new SlackClient({ bot_token: botToken, channel: slackChannel });
          await client.sendMessage({
            title,
            text,
            severity: slackSeverity,
            fields: [
              { label: 'Status', value: triggerState },
              { label: 'Monitor', value: taskName },
            ],
          });
          results.push({ integrationId: dest.integrationId, channel: 'slack', success: true });
        } else if (channelType === 'email') {
          const recipients =
            cfg.to ||
            cfg.recipients ||
            (integration.config as any)?.recipients;
          if (!recipients) {
            results.push({ integrationId: dest.integrationId, channel: 'email', success: false, error: 'No recipients' });
            continue;
          }
          const client = new EmailClient({
            recipients,
            smtp_host: cfg.smtp_host || (integration.config as any)?.smtp_host,
            smtp_port: cfg.smtp_port || (integration.config as any)?.smtp_port,
          });
          await client.sendEmail({
            subject: `${title} — ${triggerState}`,
            text,
            html: `<p><strong>${taskName}</strong> is in state <strong>${triggerState}</strong></p><p>${text}</p>`,
            severity: slackSeverity,
          });
          results.push({ integrationId: dest.integrationId, channel: 'email', success: true });
        } else if (channelType === 'pagerduty') {
          const routingKey =
            cfg.routingKey ||
            cfg.routing_key ||
            (integration.config as any)?.routing_key;
          if (!routingKey) {
            results.push({ integrationId: dest.integrationId, channel: 'pagerduty', success: false, error: 'No routing key' });
            continue;
          }
          const client = new PagerDutyClient({
            api_key: (integration.config as any)?.api_key || '',
            service_id: (integration.config as any)?.service_id || '',
            routing_key: routingKey,
          });
          await client.createIncident({
            title,
            description: text,
            severity: pdSeverity,
          });
          results.push({ integrationId: dest.integrationId, channel: 'pagerduty', success: true });
        } else if (channelType === 'teams') {
          const webhookUrl =
            cfg.webhookUrl ||
            cfg.webhook_url ||
            (integration.config as any)?.webhook_url;
          if (!webhookUrl) {
            results.push({ integrationId: dest.integrationId, channel: 'teams', success: false, error: 'No webhook URL' });
            continue;
          }
          const client = new TeamsClient({ webhook_url: webhookUrl });
          await client.sendMessage({ title, text, severity: slackSeverity });
          results.push({ integrationId: dest.integrationId, channel: 'teams', success: true });
        } else if (channelType === 'opsgenie') {
          const apiKey =
            cfg.apiKey ||
            cfg.api_key ||
            (integration.config as any)?.api_key;
          if (!apiKey) {
            results.push({ integrationId: dest.integrationId, channel: 'opsgenie', success: false, error: 'No API key' });
            continue;
          }
          const ogPriority = (cfg.priority ||
            (triggerState === 'FAIL' ? 'P1' : triggerState === 'WARN' ? 'P2' : 'P3')) as 'P1' | 'P2' | 'P3' | 'P4' | 'P5';
          const client = new OpsgenieClient({ api_key: apiKey });
          await client.createAlert({
            message: title,
            description: text,
            priority: ogPriority,
            tags: ['pallisade', 'monitor', ...(cfg.team ? [`team:${cfg.team}`] : [])],
          });
          results.push({ integrationId: dest.integrationId, channel: 'opsgenie', success: true });
        } else {
          results.push({
            integrationId: dest.integrationId,
            channel: channelType,
            success: false,
            error: `Unsupported channel type: ${channelType}`,
          });
        }
      } catch (err: any) {
        console.error(`[Alert] Failed to send to ${channelType} (${dest.integrationId}):`, err);
        results.push({ integrationId: dest.integrationId, channel: channelType, success: false, error: err.message });
      }
    }

    return NextResponse.json({ results, dispatched: firing.length });
  } catch (error: any) {
    console.error('[Alert] Dispatch error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
