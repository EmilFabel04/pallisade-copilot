import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';
import { PagerDutyClient } from '@/lib/integrations/pagerduty';
import { TeamsClient } from '@/lib/integrations/teams';
import { OpsgenieClient } from '@/lib/integrations/opsgenie';
import { EmailClient } from '@/lib/integrations/email';
import { JiraClient } from '@/lib/integrations/jira';

// POST /api/notifications/[id]/forward
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { id } = await params;
    const { integrationId, channel, config } = await request.json();

    if (!integrationId) {
      return NextResponse.json({ error: 'integrationId is required' }, { status: 400 });
    }

    const notification = await prisma.notificationEvent.findFirst({
      where: { id, organizationId: user.organizationId },
    });
    if (!notification) {
      return NextResponse.json({ error: 'Notification not found' }, { status: 404 });
    }

    const integration = await prisma.integration.findFirst({
      where: { id: integrationId, organizationId: user.organizationId, status: 'ACTIVE' },
    });
    if (!integration) {
      return NextResponse.json({ error: 'Integration not found or inactive' }, { status: 404 });
    }

    const type = integration.type.toLowerCase();
    const creds = integration.credentials
      ? (typeof integration.credentials === 'string'
          ? JSON.parse(integration.credentials)
          : integration.credentials) as Record<string, any>
      : {};
    const intConfig = (integration.config || {}) as Record<string, any>;

    const severityMap: Record<string, 'critical' | 'high' | 'medium' | 'low'> = {
      CRITICAL: 'critical', ERROR: 'high', WARN: 'medium', INFO: 'low',
    };
    const severity = severityMap[notification.severity] || 'medium';

    if (type === 'slack') {
      let botToken = '';
      if (integration.accessToken) {
        try { botToken = decrypt(integration.accessToken); } catch {}
      }
      if (!botToken) return NextResponse.json({ error: 'No Slack bot token' }, { status: 400 });
      const client = new SlackClient({ bot_token: botToken, channel: channel || creds.channel });
      await client.sendMessage({
        title: notification.title,
        text: notification.message || '',
        severity,
        fields: notification.actionUrl ? [{ label: 'Link', value: notification.actionUrl }] : undefined,
      });
    } else if (type === 'pagerduty') {
      const routingKey = config?.routing_key || intConfig.routing_key;
      if (!routingKey) return NextResponse.json({ error: 'No PagerDuty routing key' }, { status: 400 });
      const pdSev: Record<string, 'critical' | 'error' | 'warning' | 'info'> = {
        CRITICAL: 'critical', ERROR: 'error', WARN: 'warning', INFO: 'info',
      };
      const client = new PagerDutyClient({
        api_key: intConfig.api_key || '', service_id: intConfig.service_id || '', routing_key: routingKey,
      });
      await client.createIncident({
        title: notification.title,
        description: notification.message || '',
        severity: pdSev[notification.severity] || 'info',
      });
    } else if (type === 'teams') {
      const webhookUrl = config?.webhook_url || intConfig.webhook_url;
      if (!webhookUrl) return NextResponse.json({ error: 'No Teams webhook URL' }, { status: 400 });
      const client = new TeamsClient({ webhook_url: webhookUrl });
      await client.sendMessage({ title: notification.title, text: notification.message || '', severity });
    } else if (type === 'opsgenie') {
      const apiKey = config?.api_key || intConfig.api_key;
      if (!apiKey) return NextResponse.json({ error: 'No OpsGenie API key' }, { status: 400 });
      const ogPriority: Record<string, 'P1' | 'P2' | 'P3' | 'P4'> = {
        CRITICAL: 'P1', ERROR: 'P2', WARN: 'P3', INFO: 'P4',
      };
      const client = new OpsgenieClient({ api_key: apiKey });
      await client.createAlert({
        message: notification.title,
        description: notification.message || '',
        priority: ogPriority[notification.severity] || 'P3',
        tags: ['pallisade', 'forwarded'],
      });
    } else if (type === 'email') {
      const recipients = config?.recipients || intConfig.recipients;
      if (!recipients) return NextResponse.json({ error: 'No email recipients' }, { status: 400 });
      const client = new EmailClient({ recipients, smtp_host: intConfig.smtp_host, smtp_port: intConfig.smtp_port });
      await client.sendEmail({
        subject: notification.title,
        text: notification.message || '',
        html: `<p><strong>${notification.title}</strong></p><p>${notification.message || ''}</p>`,
        severity,
      });
    } else if (type === 'jira') {
      const client = new JiraClient({
        base_url: intConfig.base_url || creds.base_url,
        email: intConfig.email || creds.email,
        api_token: intConfig.api_token || creds.api_token,
      });
      const priorityMap: Record<string, string> = {
        CRITICAL: 'Highest', ERROR: 'High', WARN: 'Medium', INFO: 'Low',
      };
      const issue = await client.createIssue({
        summary: notification.title,
        description: notification.message || '',
        priority: priorityMap[notification.severity] || 'Medium',
        labels: ['pallisade', 'notification'],
        project_key: config?.project_key || intConfig.project_key,
      });
      return NextResponse.json({ success: true, platform: type, issue });
    } else {
      return NextResponse.json({ error: `Unsupported platform: ${type}` }, { status: 400 });
    }

    return NextResponse.json({ success: true, platform: type });
  } catch (error: any) {
    console.error('[NotificationForward] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
