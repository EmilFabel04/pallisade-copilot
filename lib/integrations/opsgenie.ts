/**
 * Opsgenie Integration
 * 
 * Create alerts and manage incident response
 */

interface OpsgenieConfig {
  api_key: string;
  team?: string;
  region?: 'us' | 'eu';
}

interface OpsgenieAlert {
  message: string;
  description?: string;
  priority?: 'P1' | 'P2' | 'P3' | 'P4' | 'P5';
  alias?: string;
  tags?: string[];
  entity?: string;
  details?: Record<string, string>;
}

// Severity to priority mapping
const PRIORITY_MAP = {
  critical: 'P1',
  high: 'P2',
  medium: 'P3',
  low: 'P4',
} as const;

export class OpsgenieClient {
  private config: OpsgenieConfig;
  private baseUrl: string;

  constructor(config: OpsgenieConfig) {
    this.config = config;
    // Opsgenie has different API endpoints for US and EU
    this.baseUrl = config.region === 'eu' 
      ? 'https://api.eu.opsgenie.com/v2'
      : 'https://api.opsgenie.com/v2';
  }

  private async request(endpoint: string, options: RequestInit = {}) {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: {
        'Authorization': `GenieKey ${this.config.api_key}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Opsgenie API error: ${response.status} - ${error}`);
    }

    return response.json();
  }

  /**
   * Create a new alert
   */
  async createAlert(alert: OpsgenieAlert): Promise<{ requestId: string; result: string }> {
    const payload: any = {
      message: alert.message,
      description: alert.description,
      priority: alert.priority || 'P3',
      alias: alert.alias || `pallisade-${Date.now()}`,
      source: 'Pallisade',
      tags: ['pallisade', 'data-quality', ...(alert.tags || [])],
      entity: alert.entity,
      details: alert.details,
    };

    if (this.config.team) {
      payload.responders = [{ type: 'team', name: this.config.team }];
    }

    const result = await this.request('/alerts', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    return {
      requestId: result.requestId,
      result: result.result,
    };
  }

  /**
   * Close an alert
   */
  async closeAlert(alias: string, note?: string): Promise<void> {
    await this.request(`/alerts/${alias}/close?identifierType=alias`, {
      method: 'POST',
      body: JSON.stringify({
        source: 'Pallisade',
        note: note || 'Closed by Pallisade',
      }),
    });
  }

  /**
   * Acknowledge an alert
   */
  async acknowledgeAlert(alias: string, note?: string): Promise<void> {
    await this.request(`/alerts/${alias}/acknowledge?identifierType=alias`, {
      method: 'POST',
      body: JSON.stringify({
        source: 'Pallisade',
        note: note || 'Acknowledged by Pallisade',
      }),
    });
  }

  /**
   * Add note to alert
   */
  async addNote(alias: string, note: string): Promise<void> {
    await this.request(`/alerts/${alias}/notes?identifierType=alias`, {
      method: 'POST',
      body: JSON.stringify({
        note,
        source: 'Pallisade',
      }),
    });
  }

  /**
   * Get alert details
   */
  async getAlert(alias: string): Promise<any> {
    const result = await this.request(`/alerts/${alias}?identifierType=alias`);
    return result.data;
  }

  /**
   * List recent alerts
   */
  async listAlerts(query?: string): Promise<any[]> {
    const params = new URLSearchParams({
      limit: '50',
      sort: 'createdAt',
      order: 'desc',
    });
    if (query) params.set('query', query);

    const result = await this.request(`/alerts?${params}`);
    return result.data || [];
  }

  /**
   * Get on-call schedule
   */
  async getOnCall(scheduleName: string): Promise<any> {
    const result = await this.request(`/schedules/${scheduleName}/on-calls`);
    return result.data;
  }

  /**
   * Test the connection
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      // Try to list alerts (will fail if API key is invalid)
      await this.request('/alerts?limit=1');
      return {
        success: true,
        message: 'Connected to Opsgenie successfully',
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
export async function sendOpsgenieAlert(
  config: OpsgenieConfig,
  title: string,
  description: string,
  severity: string,
  metadata?: {
    table?: string;
    score?: number;
    report_url?: string;
  }
): Promise<string> {
  const client = new OpsgenieClient(config);
  
  const details: Record<string, string> = {};
  if (metadata?.table) details.table = metadata.table;
  if (metadata?.score !== undefined) details.score = String(metadata.score);
  if (metadata?.report_url) details.report_url = metadata.report_url;
  
  const result = await client.createAlert({
    message: title,
    description,
    priority: PRIORITY_MAP[severity as keyof typeof PRIORITY_MAP] || 'P3',
    tags: [severity, 'data-quality'],
    details,
  });
  
  return result.requestId;
}

