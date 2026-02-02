/**
 * PagerDuty Integration
 * 
 * Create incidents and manage alerts via PagerDuty Events API v2
 */

interface PagerDutyConfig {
  api_key: string;
  service_id: string;
  routing_key: string;
}

interface PagerDutyIncident {
  title: string;
  description: string;
  severity: 'critical' | 'error' | 'warning' | 'info';
  source?: string;
  dedup_key?: string;
  custom_details?: Record<string, any>;
}

// Severity mapping
const SEVERITY_MAP = {
  critical: 'critical',
  high: 'error',
  medium: 'warning',
  low: 'info',
} as const;

export class PagerDutyClient {
  private config: PagerDutyConfig;
  private eventsUrl = 'https://events.pagerduty.com/v2/enqueue';
  private apiUrl = 'https://api.pagerduty.com';

  constructor(config: PagerDutyConfig) {
    this.config = config;
  }

  /**
   * Create a new incident (trigger event)
   */
  async createIncident(incident: PagerDutyIncident): Promise<{ dedup_key: string; status: string }> {
    const payload = {
      routing_key: this.config.routing_key,
      event_action: 'trigger',
      dedup_key: incident.dedup_key || `pallisade-${Date.now()}`,
      payload: {
        summary: incident.title,
        severity: SEVERITY_MAP[incident.severity as keyof typeof SEVERITY_MAP] || 'warning',
        source: incident.source || 'Pallisade',
        custom_details: {
          description: incident.description,
          ...incident.custom_details,
        },
      },
      links: incident.custom_details?.report_url ? [{
        href: incident.custom_details.report_url,
        text: 'View in Pallisade',
      }] : undefined,
    };

    const response = await fetch(this.eventsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`PagerDuty error: ${response.status} ${await response.text()}`);
    }

    const result = await response.json();
    return {
      dedup_key: result.dedup_key,
      status: result.status,
    };
  }

  /**
   * Resolve an incident
   */
  async resolveIncident(dedup_key: string): Promise<void> {
    const payload = {
      routing_key: this.config.routing_key,
      event_action: 'resolve',
      dedup_key,
    };

    const response = await fetch(this.eventsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`PagerDuty error: ${response.status}`);
    }
  }

  /**
   * Acknowledge an incident
   */
  async acknowledgeIncident(dedup_key: string): Promise<void> {
    const payload = {
      routing_key: this.config.routing_key,
      event_action: 'acknowledge',
      dedup_key,
    };

    const response = await fetch(this.eventsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`PagerDuty error: ${response.status}`);
    }
  }

  /**
   * Get on-call users for the service
   */
  async getOnCall(): Promise<any[]> {
    const response = await fetch(
      `${this.apiUrl}/services/${this.config.service_id}/oncalls`,
      {
        headers: {
          'Authorization': `Token token=${this.config.api_key}`,
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      throw new Error(`PagerDuty API error: ${response.status}`);
    }

    const data = await response.json();
    return data.oncalls || [];
  }

  /**
   * Test the connection
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetch(
        `${this.apiUrl}/services/${this.config.service_id}`,
        {
          headers: {
            'Authorization': `Token token=${this.config.api_key}`,
            'Content-Type': 'application/json',
          },
        }
      );

      if (response.ok) {
        const data = await response.json();
        return {
          success: true,
          message: `Connected to service: ${data.service?.name}`,
        };
      } else {
        return {
          success: false,
          message: `API error: ${response.status}`,
        };
      }
    } catch (error: any) {
      return {
        success: false,
        message: error.message,
      };
    }
  }
}

// Convenience function for sending alerts
export async function sendPagerDutyAlert(
  config: PagerDutyConfig,
  title: string,
  description: string,
  severity: string,
  metadata?: Record<string, any>
): Promise<string> {
  const client = new PagerDutyClient(config);
  
  const result = await client.createIncident({
    title,
    description,
    severity: severity as any,
    custom_details: metadata,
  });
  
  return result.dedup_key;
}

