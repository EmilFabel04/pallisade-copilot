import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { resolveStackIntegrations } from '@/lib/integration-credentials';

// GET /api/copilot/integrations — returns the integrations the LLM can see (no secrets)
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ integrations: [] });
    }

    const pipelineStackId = request.nextUrl.searchParams.get('pipelineStackId');

    const resolved = await resolveStackIntegrations(
      pipelineStackId,
      user.organizationId,
    );

    // Strip secrets — only return safe metadata
    const integrations = resolved.map((i) => ({
      id: i.id,
      name: i.name,
      type: i.type,
      layer: i.layer,
      status: i.status,
      // Show which config keys are present (not values)
      capabilities: Object.keys(i.config).filter(
        (k) => !['password', 'token', 'access_token', 'api_key', 'api_token',
                  'secret', 'private_key', 'credentials', 'bot_token',
                  'refresh_token', 'encrypted'].includes(k)
      ),
      hasCredentials: Object.keys(i.config).length > 0,
      metadata: {
        // Only safe metadata — repo names, project names, etc.
        repos: (i.metadata as any)?.repos?.map((r: any) => r.name) || [],
        project: (i.metadata as any)?.project || undefined,
      },
    }));

    return NextResponse.json({ integrations });
  } catch (error) {
    console.error('Failed to fetch copilot integrations:', error);
    return NextResponse.json({ integrations: [] });
  }
}
