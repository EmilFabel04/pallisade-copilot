import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { getSlackOrgConfig, getSlackClient } from '@/lib/slack-helpers';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

export async function POST(request: Request) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    const body = await request.json();
    const { plan_id, base_branch } = body;
    let { repo_owner, repo_name } = body;

    if (!plan_id) {
      return NextResponse.json({ error: 'plan_id is required' }, { status: 400 });
    }

    // ── 1. Find the GitHub token ──────────────────────────────────
    let accessToken = '';

    // Check OAuth integrations table first
    const oauthIntegration = await prisma.integration.findFirst({
      where: {
        organizationId: user.organizationId,
        type: 'GITHUB',
        status: 'ACTIVE',
      },
      select: { accessToken: true, metadata: true },
    });

    if (oauthIntegration?.accessToken) {
      try {
        accessToken = decrypt(oauthIntegration.accessToken);
      } catch (e) {
        console.error('[apply-plan] Failed to decrypt GitHub token:', e);
      }
    }

    // Fallback: check pipeline nodes
    if (!accessToken) {
      const pipelineStack = await prisma.pipelineStack.findFirst({
        where: { organizationId: user.organizationId },
        include: {
          nodes: {
            where: { toolType: { in: ['GITHUB', 'github'] }, status: { notIn: ['ERROR'] } },
            select: { config: true },
            take: 1,
          },
        },
      });
      const node = pipelineStack?.nodes?.[0];
      if (node?.config) {
        try {
          const cfg = node.config as { encrypted?: string; [k: string]: any };
          const creds = cfg.encrypted ? JSON.parse(decrypt(cfg.encrypted)) : cfg;
          accessToken = creds.access_token || creds.token || '';
        } catch { /* skip */ }
      }
    }

    if (!accessToken) {
      return NextResponse.json(
        { error: 'GitHub is not connected. Please connect GitHub in Settings > Integrations.' },
        { status: 400 },
      );
    }

    // ── 1.5. Validate token before proceeding ──────────────────────
    try {
      const ghValidation = await fetch('https://api.github.com/user', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Accept': 'application/vnd.github+json',
          'User-Agent': 'Pallisade-Scout/1.0',
        },
      });
      if (ghValidation.status === 401) {
        console.error('[apply-plan] GitHub token is invalid (401). User needs to reconnect.');
        return NextResponse.json(
          { error: 'GitHub token is invalid or expired. Please reconnect GitHub in Settings > Integrations.' },
          { status: 401 },
        );
      }
      if (ghValidation.status === 403) {
        console.error('[apply-plan] GitHub token lacks permissions (403).');
        return NextResponse.json(
          { error: 'GitHub token lacks required permissions. Please reconnect GitHub with repo access.' },
          { status: 403 },
        );
      }
    } catch (e) {
      console.error('[apply-plan] Failed to validate GitHub token:', e);
      // Don't block — let the backend handle it
    }

    // ── 2. Resolve the target repo ────────────────────────────────
    // If the frontend didn't provide repo_owner/repo_name, resolve it here
    // from the Integration metadata (where the OAuth callback stores the repo list).
    if (!repo_owner || !repo_name) {
      const metadata = (oauthIntegration?.metadata as Record<string, any>) || {};
      const repos: Array<{ name: string }> = metadata.repos || [];

      console.log('[apply-plan] Resolving repo from metadata. repos count:', repos.length,
        'first:', repos[0]?.name);

      if (repos.length > 0) {
        // repos[].name is full_name format: "owner/repo"
        const parts = repos[0].name.split('/');
        if (parts.length === 2) {
          repo_owner = repo_owner || parts[0];
          repo_name = repo_name || parts[1];
        }
      }
    }

    if (!repo_owner || !repo_name) {
      return NextResponse.json(
        { error: 'Could not determine target repository. Please connect a GitHub repo.' },
        { status: 400 },
      );
    }

    console.log('[apply-plan] Calling FastAPI:', { plan_id, repo_owner, repo_name });

    // ── 3. Call FastAPI with token + repo resolved ────────────────
    const response = await fetch(`${SCANNER_API_URL}/api/v1/copilot/apply-plan`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Organization-Id': user.organizationId,
      },
      body: JSON.stringify({
        plan_id,
        repo_owner,
        repo_name,
        base_branch: base_branch || 'main',
        integrations: [{
          id: 'github',
          name: 'GitHub',
          type: 'GITHUB',
          layer: 'version_control',
          status: 'ACTIVE',
          config: { access_token: accessToken, token: accessToken },
        }],
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      console.error('[apply-plan] FastAPI error:', data);
      return NextResponse.json(
        { error: data.detail || 'Failed to apply plan' },
        { status: response.status },
      );
    }

    // Fire-and-forget Slack notification for PR creation
    if (data.pr_url || data.pull_request_url) {
      const prUrl = data.pr_url || data.pull_request_url;
      getSlackOrgConfig(user.organizationId!).then(async (cfg) => {
        if (!cfg.connected || !cfg.preferences.alertOnPrCreated) return;
        const client = await getSlackClient(user.organizationId!);
        if (!client) return;
        await client.sendMessage({
          title: 'Change Plan PR Created',
          text: `A new pull request was opened in *${repo_owner}/${repo_name}*`,
          severity: 'low',
          fields: [
            { label: 'Repository', value: `${repo_owner}/${repo_name}` },
            { label: 'Branch', value: data.branch || base_branch || 'main' },
            ...(data.files_changed ? [{ label: 'Files Changed', value: String(data.files_changed) }] : []),
          ],
          actions: [{ text: 'View Pull Request', url: prUrl }],
          footer: `Pallisade Change Plan`,
        });
      }).catch(err => console.error('[apply-plan] Slack notification failed:', err));
    }

    return NextResponse.json(data);
  } catch (error: any) {
    console.error('[apply-plan] Error:', error);
    return NextResponse.json(
      { error: error.message || 'Internal server error' },
      { status: 500 },
    );
  }
}
