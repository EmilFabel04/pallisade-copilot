/**
 * Slack Integration
 * 
 * Send rich notifications using Block Kit
 */

interface SlackConfig {
  webhook_url: string;
  channel?: string;
}

interface SlackMessage {
  title: string;
  text: string;
  severity?: 'critical' | 'high' | 'medium' | 'low';
  fields?: Array<{ label: string; value: string }>;
  actions?: Array<{ text: string; url: string }>;
  footer?: string;
}

// Severity to emoji mapping
const SEVERITY_EMOJI = {
  critical: '🔴',
  high: '🟠',
  medium: '🟡',
  low: '🟢',
} as const;

// Severity to color mapping (for attachments fallback)
const SEVERITY_COLORS = {
  critical: '#dc2626',
  high: '#f59e0b',
  medium: '#3b82f6',
  low: '#10b981',
} as const;

export class SlackClient {
  private config: SlackConfig;

  constructor(config: SlackConfig) {
    this.config = config;
  }

  /**
   * Send a message using Block Kit
   */
  async sendMessage(message: SlackMessage): Promise<void> {
    const emoji = SEVERITY_EMOJI[message.severity || 'medium'];
    
    const blocks: any[] = [
      // Header
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: `${emoji} ${message.title}`,
          emoji: true,
        },
      },
      // Main text
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: message.text,
        },
      },
    ];

    // Add fields if provided
    if (message.fields && message.fields.length > 0) {
      blocks.push({
        type: 'section',
        fields: message.fields.map(f => ({
          type: 'mrkdwn',
          text: `*${f.label}:*\n${f.value}`,
        })),
      });
    }

    // Add divider before actions
    if (message.actions && message.actions.length > 0) {
      blocks.push({ type: 'divider' });
      blocks.push({
        type: 'actions',
        elements: message.actions.map(action => ({
          type: 'button',
          text: {
            type: 'plain_text',
            text: action.text,
            emoji: true,
          },
          url: action.url,
        })),
      });
    }

    // Add footer if provided
    if (message.footer) {
      blocks.push({
        type: 'context',
        elements: [
          {
            type: 'mrkdwn',
            text: message.footer,
          },
        ],
      });
    }

    const payload: any = {
      blocks,
      // Fallback for notifications
      text: `${emoji} ${message.title}: ${message.text}`,
    };

    if (this.config.channel) {
      payload.channel = this.config.channel;
    }

    const response = await fetch(this.config.webhook_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Slack webhook error: ${response.status} - ${errorText}`);
    }
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
   * Test the connection
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      await this.sendMessage({
        title: 'Pallisade Connected',
        text: 'Your Slack integration is working! 🎉',
        severity: 'low',
        footer: 'This is a test message from Pallisade',
      });
      return {
        success: true,
        message: 'Test message sent successfully',
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.message,
      };
    }
  }
}

// Convenience function (backwards compatible with existing code)
export async function sendSlackAlert(
  webhookUrl: string,
  message: {
    title: string;
    text?: string;
    severity?: string;
    score?: number;
    reportUrl?: string;
    table?: string;
  }
): Promise<void> {
  const client = new SlackClient({ webhook_url: webhookUrl });
  
  await client.sendMessage({
    title: message.title,
    text: message.text || '',
    severity: message.severity as any,
    fields: [
      ...(message.score !== undefined ? [{ label: 'Score', value: String(message.score) }] : []),
      ...(message.table ? [{ label: 'Table', value: message.table }] : []),
    ],
    actions: message.reportUrl ? [{ text: 'View Report', url: message.reportUrl }] : undefined,
  });
}

