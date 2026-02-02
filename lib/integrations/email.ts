/**
 * Email Integration
 * 
 * Send email notifications via SMTP or transactional email services
 */

interface EmailConfig {
  // For SMTP
  smtp_host?: string;
  smtp_port?: number;
  smtp_user?: string;
  smtp_password?: string;
  smtp_secure?: boolean;
  
  // For Resend/SendGrid/etc
  api_key?: string;
  provider?: 'smtp' | 'resend' | 'sendgrid';
  
  // Common
  from_email?: string;
  from_name?: string;
  recipients: string[];
}

interface EmailMessage {
  to?: string[];
  subject: string;
  text?: string;
  html?: string;
  severity?: 'critical' | 'high' | 'medium' | 'low';
}

// Severity to color mapping for HTML emails
const SEVERITY_COLORS = {
  critical: '#dc2626',
  high: '#f59e0b',
  medium: '#3b82f6',
  low: '#10b981',
} as const;

export class EmailClient {
  private config: EmailConfig;

  constructor(config: EmailConfig) {
    this.config = config;
  }

  /**
   * Send an email via Resend API
   */
  private async sendViaResend(message: EmailMessage): Promise<void> {
    const response = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.config.api_key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: `${this.config.from_name || 'Pallisade'} <${this.config.from_email || 'alerts@pallisade.dev'}>`,
        to: message.to || this.config.recipients,
        subject: message.subject,
        html: message.html,
        text: message.text,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Resend API error: ${response.status} - ${error}`);
    }
  }

  /**
   * Send an email via SendGrid API
   */
  private async sendViaSendGrid(message: EmailMessage): Promise<void> {
    const recipients = message.to || this.config.recipients;
    
    const response = await fetch('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.config.api_key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        personalizations: [{ to: recipients.map(email => ({ email })) }],
        from: {
          email: this.config.from_email || 'alerts@pallisade.dev',
          name: this.config.from_name || 'Pallisade',
        },
        subject: message.subject,
        content: [
          ...(message.text ? [{ type: 'text/plain', value: message.text }] : []),
          ...(message.html ? [{ type: 'text/html', value: message.html }] : []),
        ],
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`SendGrid API error: ${response.status} - ${error}`);
    }
  }

  /**
   * Send an email
   */
  async sendEmail(message: EmailMessage): Promise<void> {
    const provider = this.config.provider || 'resend';
    
    switch (provider) {
      case 'resend':
        await this.sendViaResend(message);
        break;
      case 'sendgrid':
        await this.sendViaSendGrid(message);
        break;
      case 'smtp':
        // Note: For SMTP, you'd typically use nodemailer
        // This is a placeholder - in production, use nodemailer
        throw new Error('SMTP not implemented - use Resend or SendGrid');
      default:
        throw new Error(`Unknown email provider: ${provider}`);
    }
  }

  /**
   * Generate HTML email template
   */
  generateAlertHtml(alert: {
    title: string;
    description: string;
    severity: string;
    table?: string;
    score?: number;
    reportUrl?: string;
    findings?: Array<{ title: string; severity: string }>;
  }): string {
    const color = SEVERITY_COLORS[alert.severity as keyof typeof SEVERITY_COLORS] || '#3b82f6';
    
    return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f3f4f6; padding: 20px;">
  <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
    <!-- Header -->
    <div style="background: ${color}; padding: 24px; color: white;">
      <h1 style="margin: 0; font-size: 20px;">${alert.title}</h1>
      <p style="margin: 8px 0 0; opacity: 0.9;">${alert.severity.toUpperCase()} ALERT</p>
    </div>
    
    <!-- Body -->
    <div style="padding: 24px;">
      <p style="color: #374151; line-height: 1.6; margin: 0 0 20px;">${alert.description}</p>
      
      <!-- Stats -->
      <div style="display: flex; gap: 16px; margin-bottom: 20px;">
        ${alert.score !== undefined ? `
        <div style="flex: 1; background: #f9fafb; padding: 16px; border-radius: 6px; text-align: center;">
          <div style="font-size: 24px; font-weight: bold; color: ${color};">${alert.score}</div>
          <div style="font-size: 12px; color: #6b7280;">Score</div>
        </div>
        ` : ''}
        ${alert.table ? `
        <div style="flex: 1; background: #f9fafb; padding: 16px; border-radius: 6px; text-align: center;">
          <div style="font-size: 14px; font-weight: 600; color: #374151;">${alert.table}</div>
          <div style="font-size: 12px; color: #6b7280;">Table</div>
        </div>
        ` : ''}
      </div>
      
      ${alert.findings && alert.findings.length > 0 ? `
      <!-- Findings -->
      <h3 style="font-size: 14px; color: #374151; margin: 0 0 12px;">Top Findings</h3>
      <ul style="margin: 0; padding: 0; list-style: none;">
        ${alert.findings.slice(0, 5).map(f => `
        <li style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; display: flex; align-items: center;">
          <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${SEVERITY_COLORS[f.severity as keyof typeof SEVERITY_COLORS] || '#3b82f6'}; margin-right: 12px;"></span>
          <span style="color: #374151;">${f.title}</span>
        </li>
        `).join('')}
      </ul>
      ` : ''}
      
      ${alert.reportUrl ? `
      <!-- CTA -->
      <div style="margin-top: 24px; text-align: center;">
        <a href="${alert.reportUrl}" style="display: inline-block; background: ${color}; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 500;">
          View Full Report
        </a>
      </div>
      ` : ''}
    </div>
    
    <!-- Footer -->
    <div style="background: #f9fafb; padding: 16px 24px; border-top: 1px solid #e5e7eb;">
      <p style="margin: 0; font-size: 12px; color: #6b7280; text-align: center;">
        Sent by <a href="https://pallisade.dev" style="color: ${color}; text-decoration: none;">Pallisade</a> • Data Reliability Platform
      </p>
    </div>
  </div>
</body>
</html>
    `.trim();
  }

  /**
   * Send a scan alert email
   */
  async sendScanAlert(alert: {
    title: string;
    description: string;
    severity: string;
    table?: string;
    score?: number;
    reportUrl?: string;
    findings?: Array<{ title: string; severity: string }>;
  }): Promise<void> {
    const html = this.generateAlertHtml(alert);
    const severityPrefix = alert.severity === 'critical' ? '🔴' : 
                          alert.severity === 'high' ? '🟠' : 
                          alert.severity === 'medium' ? '🟡' : '🟢';

    await this.sendEmail({
      subject: `${severityPrefix} [Pallisade] ${alert.title}`,
      html,
      text: `${alert.title}\n\n${alert.description}\n\nSeverity: ${alert.severity}\n${alert.table ? `Table: ${alert.table}\n` : ''}${alert.score !== undefined ? `Score: ${alert.score}\n` : ''}\n${alert.reportUrl || ''}`,
      severity: alert.severity as any,
    });
  }

  /**
   * Test the connection
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      await this.sendEmail({
        subject: '✅ Pallisade Email Integration Test',
        html: this.generateAlertHtml({
          title: 'Integration Test Successful',
          description: 'Your email integration is configured correctly!',
          severity: 'low',
        }),
        text: 'Your email integration is configured correctly!',
      });
      return {
        success: true,
        message: `Test email sent to ${this.config.recipients.join(', ')}`,
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.message,
      };
    }
  }
}

// Convenience function
export async function sendEmailAlert(
  config: EmailConfig,
  title: string,
  description: string,
  severity: string,
  metadata?: {
    table?: string;
    score?: number;
    report_url?: string;
  }
): Promise<void> {
  const client = new EmailClient(config);
  
  await client.sendScanAlert({
    title,
    description,
    severity,
    table: metadata?.table,
    score: metadata?.score,
    reportUrl: metadata?.report_url,
  });
}

