/**
 * Microsoft Teams Integration
 * 
 * Send notifications via incoming webhooks
 */

interface TeamsConfig {
  webhook_url: string;
}

interface TeamsMessage {
  title: string;
  text: string;
  severity?: 'critical' | 'high' | 'medium' | 'low';
  facts?: Array<{ name: string; value: string }>;
  actions?: Array<{ name: string; url: string }>;
}

// Severity to color mapping
const SEVERITY_COLORS = {
  critical: '#dc2626',
  high: '#f59e0b',
  medium: '#3b82f6',
  low: '#10b981',
} as const;

export class TeamsClient {
  private config: TeamsConfig;

  constructor(config: TeamsConfig) {
    this.config = config;
  }

  /**
   * Send a message card to Teams
   */
  async sendMessage(message: TeamsMessage): Promise<void> {
    const color = SEVERITY_COLORS[message.severity || 'medium'];
    
    const payload = {
      '@type': 'MessageCard',
      '@context': 'http://schema.org/extensions',
      themeColor: color.replace('#', ''),
      summary: message.title,
      sections: [
        {
          activityTitle: message.title,
          facts: message.facts || [],
          text: message.text,
          markdown: true,
        },
      ],
      potentialAction: message.actions?.map(action => ({
        '@type': 'OpenUri',
        name: action.name,
        targets: [{ os: 'default', uri: action.url }],
      })),
    };

    const response = await fetch(this.config.webhook_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Teams webhook error: ${response.status}`);
    }
  }

  /**
   * Send an adaptive card (more modern format)
   */
  async sendAdaptiveCard(message: TeamsMessage): Promise<void> {
    const payload = {
      type: 'message',
      attachments: [
        {
          contentType: 'application/vnd.microsoft.card.adaptive',
          content: {
            type: 'AdaptiveCard',
            $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
            version: '1.4',
            body: [
              {
                type: 'TextBlock',
                size: 'Large',
                weight: 'Bolder',
                text: message.title,
                color: message.severity === 'critical' ? 'Attention' : 
                       message.severity === 'high' ? 'Warning' : 'Default',
              },
              {
                type: 'TextBlock',
                text: message.text,
                wrap: true,
              },
              ...(message.facts ? [{
                type: 'FactSet',
                facts: message.facts.map(f => ({
                  title: f.name,
                  value: f.value,
                })),
              }] : []),
            ],
            actions: message.actions?.map(action => ({
              type: 'Action.OpenUrl',
              title: action.name,
              url: action.url,
            })),
          },
        },
      ],
    };

    const response = await fetch(this.config.webhook_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Teams webhook error: ${response.status}`);
    }
  }

  /**
   * Test the connection
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      await this.sendMessage({
        title: '✅ Pallisade Connected',
        text: 'Your Microsoft Teams integration is working!',
        severity: 'low',
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

// Convenience function for sending alerts
export async function sendTeamsAlert(
  webhookUrl: string,
  title: string,
  description: string,
  severity: string,
  metadata?: {
    table?: string;
    score?: number;
    report_url?: string;
  }
): Promise<void> {
  const client = new TeamsClient({ webhook_url: webhookUrl });
  
  const facts = [];
  if (metadata?.table) facts.push({ name: 'Table', value: metadata.table });
  if (metadata?.score !== undefined) facts.push({ name: 'Score', value: String(metadata.score) });
  facts.push({ name: 'Severity', value: severity });
  
  const actions = [];
  if (metadata?.report_url) {
    actions.push({ name: 'View Report', url: metadata.report_url });
  }

  await client.sendMessage({
    title,
    text: description,
    severity: severity as any,
    facts,
    actions,
  });
}

