import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';
import { JiraClient } from '@/lib/integrations/jira';
import { formatPlanForSlack, formatPlanForJira, formatPlanForGitHubIssue } from '@/lib/integrations/share-plan';
import type { ChangePlan } from '@/types/change-plan';

interface SharePlanRequest {
  plan: ChangePlan;
  target: {
    type: 'slack' | 'jira' | 'github_issue';
    integrationId: string;
    channel?: string;
    projectKey?: string;
    repository?: string;
  };
}

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body: SharePlanRequest = await request.json();
    const { plan, target } = body;

    if (!plan || !target?.type || !target?.integrationId) {
      return NextResponse.json(
        { error: 'Plan and target (type, integrationId) are required' },
        { status: 400 }
      );
    }

    // Fetch the integration with credentials
    const integration = await prisma.integration.findFirst({
      where: {
        id: target.integrationId,
        organizationId: user.organizationId,
      },
      select: {
        id: true,
        type: true,
        credentials: true,
        config: true,
        accessToken: true,
      },
    });

    if (!integration) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    // Decrypt credentials
    let credentials: Record<string, any> = {};
    if (integration.credentials) {
      const credentialsJson = integration.credentials as { encrypted?: string };
      if (credentialsJson.encrypted) {
        try {
          credentials = JSON.parse(decrypt(credentialsJson.encrypted));
        } catch (e) {
          console.error('Failed to decrypt credentials:', e);
          return NextResponse.json({ error: 'Failed to decrypt integration credentials' }, { status: 500 });
        }
      }
    }

    const config = (integration.config as Record<string, any>) || {};

    // Handle based on target type
    switch (target.type) {
      case 'slack': {
        let botToken = '';
        if (integration.accessToken) {
          try { botToken = decrypt(integration.accessToken); } catch {}
        }
        if (!botToken) {
          return NextResponse.json({ error: 'Slack bot token not configured' }, { status: 400 });
        }

        const slackCreds = integration.credentials
          ? (typeof integration.credentials === 'string' ? JSON.parse(integration.credentials as string) : integration.credentials) as Record<string, any>
          : {};
        const slackClient = new SlackClient({
          bot_token: botToken,
          channel: target.channel || slackCreds.channel || config.channel,
        });

        const message = formatPlanForSlack(plan);
        await slackClient.sendMessage(message);

        return NextResponse.json({
          success: true,
          message: 'Plan shared to Slack successfully',
        });
      }

      case 'jira': {
        const siteUrl = credentials.site_url || credentials.siteUrl || config.site_url;
        const email = credentials.email;
        const apiToken = credentials.api_token || credentials.apiToken;
        const projectKey = target.projectKey || config.project_key || config.projectKey;

        if (!siteUrl || !email || !apiToken) {
          return NextResponse.json({ error: 'Jira credentials not fully configured' }, { status: 400 });
        }

        if (!projectKey) {
          return NextResponse.json({ error: 'Jira project key is required' }, { status: 400 });
        }

        const jiraClient = new JiraClient({
          site_url: siteUrl,
          email,
          api_token: apiToken,
          project_key: projectKey,
          issue_type: config.issue_type || 'Task',
        });

        const issue = formatPlanForJira(plan);
        const result = await jiraClient.createIssue(issue);

        return NextResponse.json({
          success: true,
          message: 'Jira issue created successfully',
          url: result.url,
          key: result.key,
        });
      }

      case 'github_issue': {
        const token = credentials.access_token || credentials.token || credentials.accessToken;
        const repo = target.repository || config.default_repo || config.defaultRepo;

        if (!token) {
          return NextResponse.json({ error: 'GitHub token not configured' }, { status: 400 });
        }

        if (!repo) {
          return NextResponse.json({ error: 'GitHub repository is required' }, { status: 400 });
        }

        // Parse owner/repo
        const [owner, repoName] = repo.includes('/') ? repo.split('/') : [null, repo];
        if (!owner || !repoName) {
          return NextResponse.json({ error: 'Repository must be in owner/repo format' }, { status: 400 });
        }

        const issue = formatPlanForGitHubIssue(plan);

        // Create GitHub issue via API
        const response = await fetch(`https://api.github.com/repos/${owner}/${repoName}/issues`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            title: issue.title,
            body: issue.body,
            labels: issue.labels,
          }),
        });

        if (!response.ok) {
          const errorText = await response.text();
          console.error('GitHub API error:', errorText);
          return NextResponse.json(
            { error: `GitHub API error: ${response.status}` },
            { status: response.status }
          );
        }

        const githubIssue = await response.json();

        return NextResponse.json({
          success: true,
          message: 'GitHub issue created successfully',
          url: githubIssue.html_url,
          number: githubIssue.number,
        });
      }

      default:
        return NextResponse.json({ error: `Unsupported target type: ${target.type}` }, { status: 400 });
    }
  } catch (error: any) {
    console.error('Error sharing plan:', error);
    return NextResponse.json(
      { error: error.message || 'Failed to share plan' },
      { status: 500 }
    );
  }
}

// GET endpoint to list available integrations for sharing
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ integrations: [] });
    }

    // Fetch integrations that support sharing (Slack, Jira, GitHub)
    const integrations = await prisma.integration.findMany({
      where: {
        organizationId: user.organizationId,
        type: {
          in: ['SLACK', 'JIRA', 'GITHUB', 'TEAMS', 'PAGERDUTY'],
        },
        status: 'ACTIVE',
      },
      select: {
        id: true,
        name: true,
        type: true,
        connectionInfo: true,
        config: true,
      },
      orderBy: { type: 'asc' },
    });

    // Map to a simpler format for the frontend
    const shareableIntegrations = integrations.map(int => ({
      id: int.id,
      name: int.name,
      type: int.type.toLowerCase() as 'slack' | 'jira' | 'github',
      connectionInfo: int.connectionInfo,
      // Include non-sensitive config for display
      config: {
        channel: (int.config as any)?.channel,
        project_key: (int.config as any)?.project_key || (int.config as any)?.projectKey,
        default_repo: (int.config as any)?.default_repo || (int.config as any)?.defaultRepo,
      },
    }));

    return NextResponse.json({ integrations: shareableIntegrations });
  } catch (error: any) {
    console.error('Error fetching shareable integrations:', error);
    return NextResponse.json({ error: 'Failed to fetch integrations' }, { status: 500 });
  }
}
