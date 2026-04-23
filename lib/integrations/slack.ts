/**
 * Slack Integration — Bot Token + Web API
 *
 * Uses chat.postMessage (not webhooks) for rich Block Kit notifications.
 * Requires a Bot Token (xoxb-...) with scopes: chat:write, channels:read, groups:read
 */

const SLACK_API = 'https://slack.com/api';

export interface SlackConfig {
  bot_token: string;
  channel?: string;
}

export interface SlackMessage {
  title: string;
  text: string;
  severity?: 'critical' | 'high' | 'medium' | 'low';
  fields?: Array<{ label: string; value: string }>;
  actions?: Array<{ text: string; url: string }>;
  footer?: string;
  channel?: string;
}

export interface SlackChannel {
  id: string;
  name: string;
  is_private: boolean;
}

const SEVERITY_EMOJI = {
  critical: '🔴',
  high: '🟠',
  medium: '🟡',
  low: '🟢',
} as const;

export class SlackClient {
  private token: string;
  private defaultChannel?: string;

  constructor(config: SlackConfig) {
    this.token = config.bot_token;
    this.defaultChannel = config.channel;
  }

  private async api(method: string, body?: Record<string, any>): Promise<any> {
    const res = await fetch(`${SLACK_API}/${method}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.token}`,
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    const data = await res.json();
    if (!data.ok) {
      throw new Error(`Slack API error (${method}): ${data.error || 'unknown'}`);
    }
    return data;
  }

  /**
   * Send a message using Block Kit via chat.postMessage
   */
  async sendMessage(message: SlackMessage): Promise<void> {
    const channel = message.channel || this.defaultChannel;
    if (!channel) {
      throw new Error('No Slack channel specified');
    }

    const emoji = SEVERITY_EMOJI[message.severity || 'medium'];

    const blocks: any[] = [
      {
        type: 'header',
        text: { type: 'plain_text', text: `${emoji} ${message.title}`, emoji: true },
      },
      {
        type: 'section',
        text: { type: 'mrkdwn', text: message.text },
      },
    ];

    if (message.fields && message.fields.length > 0) {
      blocks.push({
        type: 'section',
        fields: message.fields.map(f => ({
          type: 'mrkdwn',
          text: `*${f.label}:*\n${f.value}`,
        })),
      });
    }

    if (message.actions && message.actions.length > 0) {
      blocks.push({ type: 'divider' });
      blocks.push({
        type: 'actions',
        elements: message.actions.map(action => ({
          type: 'button',
          text: { type: 'plain_text', text: action.text, emoji: true },
          url: action.url,
        })),
      });
    }

    if (message.footer) {
      blocks.push({
        type: 'context',
        elements: [{ type: 'mrkdwn', text: message.footer }],
      });
    }

    await this.api('chat.postMessage', {
      channel,
      blocks,
      text: `${emoji} ${message.title}: ${message.text}`,
    });
  }

  /**
   * List channels the bot can post to
   */
  async listChannels(): Promise<SlackChannel[]> {
    const channels: SlackChannel[] = [];
    let cursor: string | undefined;

    do {
      const params: Record<string, any> = {
        types: 'public_channel,private_channel',
        exclude_archived: true,
        limit: 200,
      };
      if (cursor) params.cursor = cursor;

      const data = await this.api('conversations.list', params);
      for (const ch of data.channels || []) {
        channels.push({ id: ch.id, name: ch.name, is_private: ch.is_private });
      }
      cursor = data.response_metadata?.next_cursor || undefined;
    } while (cursor);

    return channels.sort((a, b) => a.name.localeCompare(b.name));
  }

  /**
   * Test authentication — returns workspace + bot user info
   */
  async testAuth(): Promise<{ ok: boolean; team: string; user: string; teamId: string }> {
    const data = await this.api('auth.test');
    return { ok: true, team: data.team, user: data.user, teamId: data.team_id };
  }

  /**
   * Send scan results summary
   */
  async sendScanResults(results: {
    title: string;
    score: number;
    findingsCount: number;
    criticalCount: number;
    highCount: number;
    reportUrl?: string;
    tables?: string[];
  }): Promise<void> {
    const severity = results.criticalCount > 0 ? 'critical' :
                     results.score < 60 ? 'high' :
                     results.score < 80 ? 'medium' : 'low';

    const scoreEmoji = results.score >= 80 ? '✅' : results.score >= 60 ? '⚠️' : '❌';

    await this.sendMessage({
      title: results.title,
      text: `Scan completed with score *${results.score}/100* ${scoreEmoji}`,
      severity,
      fields: [
        { label: 'Total Findings', value: String(results.findingsCount) },
        { label: 'Critical', value: String(results.criticalCount) },
        { label: 'High', value: String(results.highCount) },
        { label: 'Tables Scanned', value: String(results.tables?.length || 'N/A') },
      ],
      actions: results.reportUrl ? [
        { text: '📊 View Full Report', url: results.reportUrl },
      ] : undefined,
      footer: `Pallisade • ${new Date().toLocaleString()}`,
    });
  }

  /**
   * Send incident notification
   */
  async sendIncidentAlert(incident: {
    title: string;
    description: string;
    severity: string;
    table?: string;
    incidentUrl?: string;
  }): Promise<void> {
    await this.sendMessage({
      title: `🚨 Incident: ${incident.title}`,
      text: incident.description,
      severity: incident.severity as any,
      fields: incident.table ? [
        { label: 'Affected Table', value: incident.table },
        { label: 'Severity', value: incident.severity.toUpperCase() },
      ] : undefined,
      actions: incident.incidentUrl ? [
        { text: '🔍 View Incident', url: incident.incidentUrl },
      ] : undefined,
    });
  }

  /**
   * Test the connection by calling auth.test
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      const info = await this.testAuth();
      return { success: true, message: `Connected to workspace "${info.team}" as @${info.user}` };
    } catch (error: any) {
      return { success: false, message: error.message };
    }
  }
}
