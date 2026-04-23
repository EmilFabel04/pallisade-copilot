import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

// POST /api/pipeline/[stackId]/nodes/[nodeId]/github-repos
// Returns repositories configured in the GitHub connector node for this stack.
// Used by dbt and Airflow nodes to pick a repo from the GitHub connector's saved repos.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; nodeId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    // Find the GitHub node in this stack
    const githubNode = await prisma.pipelineNode.findFirst({
      where: {
        stackId,
        toolType: 'github',
        stack: { organizationId: user.organizationId },
      },
      include: { integration: true },
    });

    if (!githubNode) {
      return NextResponse.json({
        error: 'No GitHub connector configured. Add and configure a GitHub connector first.',
        options: [],
      }, { status: 400 });
    }

    // Resolve the GitHub node's config to get the repos list
    let config: Record<string, any> = {};

    if ((githubNode as any).integrationId && (githubNode as any).integration?.credentials) {
      try {
        const intCreds = (githubNode as any).integration.credentials as any;
        config = intCreds.encrypted
          ? JSON.parse(decrypt(intCreds.encrypted))
          : intCreds;
      } catch {
        return NextResponse.json({ error: 'Failed to read GitHub credentials' }, { status: 500 });
      }
    } else if (githubNode.config) {
      const configJson = githubNode.config as any;
      try {
        config = configJson.encrypted
          ? JSON.parse(decrypt(configJson.encrypted))
          : configJson;
      } catch {
        return NextResponse.json({ error: 'Failed to read GitHub config' }, { status: 500 });
      }
    }

    const repos: string[] = config.repos || [];
    const owner = config.owner || '';

    if (repos.length === 0) {
      return NextResponse.json({
        error: 'No repositories selected in the GitHub connector. Configure the GitHub connector and select repositories first.',
        options: [],
      }, { status: 400 });
    }

    // Return as owner/repo format for display
    const options = repos.map((repo: string) =>
      repo.includes('/') ? repo : owner ? `${owner}/${repo}` : repo
    );

    return NextResponse.json({ options });
  } catch (error: any) {
    console.error('[GITHUB-REPOS] Error:', error);
    return NextResponse.json({ error: error.message || 'Failed to fetch repos' }, { status: 500 });
  }
}
