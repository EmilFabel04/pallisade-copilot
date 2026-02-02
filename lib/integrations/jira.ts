/**
 * Jira Integration
 * 
 * Create issues, link to incidents, and sync status
 */

interface JiraConfig {
  site_url: string;
  email: string;
  api_token: string;
  project_key: string;
  issue_type?: string;
}

interface JiraIssue {
  summary: string;
  description: string;
  priority?: 'Highest' | 'High' | 'Medium' | 'Low' | 'Lowest';
  labels?: string[];
  components?: string[];
  assignee?: string;
  custom_fields?: Record<string, any>;
}

// Severity to Jira priority mapping
const PRIORITY_MAP = {
  critical: 'Highest',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
} as const;

export class JiraClient {
  private config: JiraConfig;
  private baseUrl: string;
  private auth: string;

  constructor(config: JiraConfig) {
    this.config = config;
    this.baseUrl = `${config.site_url}/rest/api/3`;
    this.auth = Buffer.from(`${config.email}:${config.api_token}`).toString('base64');
  }

  private async request(endpoint: string, options: RequestInit = {}) {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: {
        'Authorization': `Basic ${this.auth}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Jira API error: ${response.status} - ${error}`);
    }

    return response.json();
  }

  /**
   * Create a new issue
   */
  async createIssue(issue: JiraIssue): Promise<{ key: string; id: string; url: string }> {
    const payload = {
      fields: {
        project: { key: this.config.project_key },
        summary: issue.summary,
        description: {
          type: 'doc',
          version: 1,
          content: [
            {
              type: 'paragraph',
              content: [{ type: 'text', text: issue.description }],
            },
          ],
        },
        issuetype: { name: this.config.issue_type || 'Bug' },
        priority: issue.priority ? { name: issue.priority } : undefined,
        labels: issue.labels || ['pallisade', 'data-quality'],
        ...issue.custom_fields,
      },
    };

    const result = await this.request('/issue', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    return {
      key: result.key,
      id: result.id,
      url: `${this.config.site_url}/browse/${result.key}`,
    };
  }

  /**
   * Update an issue
   */
  async updateIssue(issueKey: string, updates: Partial<JiraIssue>): Promise<void> {
    const payload: any = { fields: {} };
    
    if (updates.summary) payload.fields.summary = updates.summary;
    if (updates.description) {
      payload.fields.description = {
        type: 'doc',
        version: 1,
        content: [
          {
            type: 'paragraph',
            content: [{ type: 'text', text: updates.description }],
          },
        ],
      };
    }
    if (updates.priority) payload.fields.priority = { name: updates.priority };
    if (updates.labels) payload.fields.labels = updates.labels;

    await this.request(`/issue/${issueKey}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  /**
   * Transition issue to a new status
   */
  async transitionIssue(issueKey: string, transitionName: string): Promise<void> {
    // Get available transitions
    const { transitions } = await this.request(`/issue/${issueKey}/transitions`);
    
    const transition = transitions.find(
      (t: any) => t.name.toLowerCase() === transitionName.toLowerCase()
    );

    if (!transition) {
      throw new Error(`Transition "${transitionName}" not found. Available: ${transitions.map((t: any) => t.name).join(', ')}`);
    }

    await this.request(`/issue/${issueKey}/transitions`, {
      method: 'POST',
      body: JSON.stringify({ transition: { id: transition.id } }),
    });
  }

  /**
   * Add a comment to an issue
   */
  async addComment(issueKey: string, comment: string): Promise<void> {
    await this.request(`/issue/${issueKey}/comment`, {
      method: 'POST',
      body: JSON.stringify({
        body: {
          type: 'doc',
          version: 1,
          content: [
            {
              type: 'paragraph',
              content: [{ type: 'text', text: comment }],
            },
          ],
        },
      }),
    });
  }

  /**
   * Get issue details
   */
  async getIssue(issueKey: string): Promise<any> {
    return this.request(`/issue/${issueKey}`);
  }

  /**
   * Search for issues
   */
  async searchIssues(jql: string, maxResults: number = 50): Promise<any[]> {
    const result = await this.request('/search', {
      method: 'POST',
      body: JSON.stringify({
        jql,
        maxResults,
        fields: ['summary', 'status', 'priority', 'created', 'updated'],
      }),
    });
    return result.issues || [];
  }

  /**
   * Test the connection
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      const result = await this.request('/myself');
      return {
        success: true,
        message: `Connected as: ${result.displayName} (${result.emailAddress})`,
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.message,
      };
    }
  }
}

// Convenience function for creating issues from findings
export async function createJiraFromFinding(
  config: JiraConfig,
  finding: {
    title: string;
    description: string;
    severity: string;
    table?: string;
    report_url?: string;
  }
): Promise<{ key: string; url: string }> {
  const client = new JiraClient(config);
  
  const description = `
${finding.description}

---
*Table:* ${finding.table || 'N/A'}
*Severity:* ${finding.severity}
*Detected by:* Pallisade
*Report:* ${finding.report_url || 'N/A'}
  `.trim();

  const result = await client.createIssue({
    summary: `[Pallisade] ${finding.title}`,
    description,
    priority: PRIORITY_MAP[finding.severity as keyof typeof PRIORITY_MAP] || 'Medium',
    labels: ['pallisade', 'data-quality', finding.severity],
  });

  return {
    key: result.key,
    url: result.url,
  };
}

