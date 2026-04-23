import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

// POST /api/pipeline/[stackId]/nodes/[nodeId]/repos
// Fetches repositories from GitHub using the node's PAT + owner config.
// Used by the GitHub connector's multi-select repos field.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId, nodeId } = await params;
    const body = await request.json().catch(() => ({}));

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Resolve credentials: prefer body config (unsaved), then Integration, then legacy node config
    let credentials: Record<string, any> = {};

    if (body.config && Object.keys(body.config).length > 0) {
      // Strip internal keys
      const { _cached, _autoDiscovered, repos, ...creds } = body.config;
      credentials = creds;
    } else {
      const node = await prisma.pipelineNode.findFirst({
        where: { id: nodeId, stackId, stack: { organizationId: user.organizationId } },
        include: { integration: true },
      });

      if (!node) {
        return NextResponse.json({ error: 'Node not found' }, { status: 404 });
      }

      if ((node as any).integrationId && (node as any).integration?.credentials) {
        try {
          const intCreds = (node as any).integration.credentials as any;
          credentials = intCreds.encrypted
            ? JSON.parse(decrypt(intCreds.encrypted))
            : intCreds;
        } catch {
          return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
        }
      } else if (node.config) {
        const configJson = node.config as any;
        try {
          credentials = configJson.encrypted
            ? JSON.parse(decrypt(configJson.encrypted))
            : configJson;
        } catch {
          return NextResponse.json({ error: 'Failed to decrypt credentials' }, { status: 500 });
        }
      }
    }

    const token = credentials.access_token;
    const owner = credentials.owner;

    if (!token) {
      return NextResponse.json({ error: 'No access token configured' }, { status: 400 });
    }

    // Fetch repos from GitHub API
    const allRepos: string[] = [];
    let page = 1;
    const perPage = 100;

    while (true) {
      const url = owner
        ? `https://api.github.com/orgs/${owner}/repos?per_page=${perPage}&page=${page}&sort=name`
        : `https://api.github.com/user/repos?per_page=${perPage}&page=${page}&sort=full_name`;

      const res = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/vnd.github+json',
        },
        signal: AbortSignal.timeout(15000),
      });

      if (!res.ok) {
        // If org endpoint fails, try user repos filtered by owner
        if (owner && page === 1) {
          const userRes = await fetch(
            `https://api.github.com/user/repos?per_page=${perPage}&sort=full_name&affiliation=owner,collaborator,organization_member`,
            {
              headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' },
              signal: AbortSignal.timeout(15000),
            }
          );
          if (userRes.ok) {
            const repos = await userRes.json();
            for (const repo of repos) {
              if (repo.full_name.startsWith(`${owner}/`)) {
                allRepos.push(repo.name);
              }
            }
            break;
          }
        }
        const errBody = await res.json().catch(() => ({}));
        return NextResponse.json({
          error: errBody.message || 'Failed to fetch repositories from GitHub',
          options: [],
        }, { status: 400 });
      }

      const repos = await res.json();
      for (const repo of repos) {
        allRepos.push(repo.name);
      }

      if (repos.length < perPage) break;
      page++;
      if (page > 10) break; // Safety limit
    }

    return NextResponse.json({ options: allRepos });
  } catch (error: any) {
    console.error('[REPOS] Error:', error);
    return NextResponse.json({ error: error.message || 'Failed to fetch repos' }, { status: 500 });
  }
}
