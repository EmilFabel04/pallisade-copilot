/**
 * Enhanced Slack Integration
 * 
 * Sends beautiful, interactive alerts to Slack with:
 * - Rich formatting with Block Kit
 * - Interactive buttons (acknowledge, snooze, view, escalate)
 * - Severity-based styling
 * - Threaded responses for related alerts
 */

export interface SlackAlertConfig {
  webhookUrl: string;
  channel?: string;
}

export interface Finding {
  id?: string;
  title: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  category: string;
  table?: string;
  description?: string;
  staleness_hours?: number;
  has_auto_fix?: boolean;
}

export interface SlackAlertPayload {
  reportId: string;
  reportTitle: string;
  scanType: string;
  score: number;
  findings: Finding[];
  reportUrl: string;
  timestamp?: Date;
}

const SEVERITY_EMOJI = {
  critical: '🔴',
  high: '🟠',
  medium: '🟡',
  low: '🔵',
};

const SEVERITY_COLOR = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#ca8a04',
  low: '#2563eb',
};

const SCAN_TYPE_EMOJI = {
  freshness: '⏰',
  quality: '✨',
  volume: '📊',
  schema: '🔧',
  secrets: '🔐',
  pii: '👤',
};

/**
 * Build Slack Block Kit message for scan results
 */
export function buildSlackBlocks(payload: SlackAlertPayload) {
  const { reportId, reportTitle, scanType, score, findings, reportUrl } = payload;
  
  const criticalCount = findings.filter(f => f.severity === 'critical').length;
  const highCount = findings.filter(f => f.severity === 'high').length;
  const hasAutoFix = findings.some(f => f.has_auto_fix);
  
  // Determine overall status
  const isHealthy = score >= 80 && criticalCount === 0;
  const statusEmoji = isHealthy ? '✅' : criticalCount > 0 ? '🚨' : '⚠️';
  const statusText = isHealthy ? 'All Clear' : criticalCount > 0 ? 'Critical Issues Found' : 'Issues Found';
  
  const blocks: any[] = [
    // Header
    {
      type: 'header',
      text: {
        type: 'plain_text',
        text: `${statusEmoji} ${reportTitle}`,
        emoji: true,
      },
    },
    
    // Summary section
    {
      type: 'section',
      fields: [
        {
          type: 'mrkdwn',
          text: `*Scan Type:*\n${SCAN_TYPE_EMOJI[scanType as keyof typeof SCAN_TYPE_EMOJI] || '📋'} ${scanType.charAt(0).toUpperCase() + scanType.slice(1)}`,
        },
        {
          type: 'mrkdwn',
          text: `*Score:*\n${score >= 80 ? '🟢' : score >= 60 ? '🟡' : '🔴'} ${score}/100`,
        },
        {
          type: 'mrkdwn',
          text: `*Findings:*\n${findings.length} issue${findings.length !== 1 ? 's' : ''}`,
        },
        {
          type: 'mrkdwn',
          text: `*Auto-Fixes:*\n${hasAutoFix ? '✅ Available' : '❌ None'}`,
        },
      ],
    },
    
    { type: 'divider' },
  ];
  
  // Add top findings (max 5)
  if (findings.length > 0) {
    const topFindings = findings
      .sort((a, b) => {
        const order = { critical: 0, high: 1, medium: 2, low: 3 };
        return order[a.severity] - order[b.severity];
      })
      .slice(0, 5);
    
    blocks.push({
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: `*Top Issues:*`,
      },
    });
    
    for (const finding of topFindings) {
      const emoji = SEVERITY_EMOJI[finding.severity];
      const tableInfo = finding.table ? ` • \`${finding.table.split('.').pop()}\`` : '';
      const staleness = finding.staleness_hours 
        ? ` (${finding.staleness_hours}h stale)`
        : '';
      
      blocks.push({
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `${emoji} *${finding.title}*${tableInfo}${staleness}\n${finding.description || ''}`,
        },
      });
    }
    
    if (findings.length > 5) {
      blocks.push({
        type: 'context',
        elements: [
          {
            type: 'mrkdwn',
            text: `_+${findings.length - 5} more findings..._`,
          },
        ],
      });
    }
    
    blocks.push({ type: 'divider' });
  }
  
  // Action buttons
  const actions: any[] = [
    {
      type: 'button',
      text: { type: 'plain_text', text: '📋 View Report', emoji: true },
      url: reportUrl,
      style: 'primary',
    },
  ];
  
  if (!isHealthy) {
    actions.push({
      type: 'button',
      text: { type: 'plain_text', text: '✓ Acknowledge', emoji: true },
      action_id: 'acknowledge_alert',
      value: JSON.stringify({ reportId }),
    });
    
    actions.push({
      type: 'button',
      text: { type: 'plain_text', text: '😴 Snooze 1h', emoji: true },
      action_id: 'snooze_alert',
      value: JSON.stringify({ reportId, duration: '1h' }),
    });
  }
  
  if (criticalCount > 0) {
    const criticalFinding = findings.find(f => f.severity === 'critical') || findings[0];
    actions.push({
      type: 'button',
      text: { type: 'plain_text', text: '🚨 Create Incident', emoji: true },
      action_id: 'create_incident',
      value: JSON.stringify({ 
        reportId, 
        title: `${scanType} issue: ${criticalFinding?.title || 'Critical Issue'}`,
        severity: 'high',
      }),
      style: 'danger',
    });
  }
  
  blocks.push({
    type: 'actions',
    elements: actions,
  });
  
  // Footer
  blocks.push({
    type: 'context',
    elements: [
      {
        type: 'mrkdwn',
        text: `Pallisade • ${new Date().toLocaleString()} • <${process.env.NEXTAUTH_URL}/dashboard|Dashboard>`,
      },
    ],
  });
  
  return blocks;
}

/**
 * Send alert to Slack
 */
export async function sendSlackAlert(
  config: SlackAlertConfig,
  payload: SlackAlertPayload
): Promise<{ success: boolean; error?: string }> {
  try {
    const blocks = buildSlackBlocks(payload);
    
    const response = await fetch(config.webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        blocks,
        text: `${payload.reportTitle} - Score: ${payload.score}/100`, // Fallback text
      }),
    });
    
    if (!response.ok) {
      const text = await response.text();
      return { success: false, error: text };
    }
    
    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

/**
 * Send a simple text message to Slack
 */
export async function sendSlackMessage(
  webhookUrl: string,
  message: string
): Promise<{ success: boolean; error?: string }> {
  try {
    const response = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: message }),
    });
    
    if (!response.ok) {
      return { success: false, error: await response.text() };
    }
    
    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

/**
 * Build a fix suggestion message
 */
export function buildFixSuggestionBlocks(
  finding: Finding,
  fix: { title: string; code: string; language: string }
) {
  return [
    {
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: `🔧 *Auto-Fix Available*\n\nFor: *${finding.title}*\nFix: ${fix.title}`,
      },
    },
    {
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: '```' + fix.code.slice(0, 500) + (fix.code.length > 500 ? '\n...' : '') + '```',
      },
    },
    {
      type: 'actions',
      elements: [
        {
          type: 'button',
          text: { type: 'plain_text', text: '📋 Copy Fix', emoji: true },
          action_id: 'copy_fix',
          value: JSON.stringify({ code: fix.code }),
        },
        {
          type: 'button',
          text: { type: 'plain_text', text: '🚀 Apply Now', emoji: true },
          action_id: 'run_fix',
          value: JSON.stringify({ findingId: finding.id }),
          style: 'primary',
        },
      ],
    },
  ];
}

