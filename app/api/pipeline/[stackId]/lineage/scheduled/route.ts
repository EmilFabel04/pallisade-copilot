import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import prisma from '@/lib/db';
import { extractLineageForStack } from '../extract-lineage';
import { verifyInternalApiKey, INTERNAL_API_KEY_HEADER } from '@/lib/internal-api-key';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  // Authenticate via internal API key
  if (!verifyInternalApiKey(request.headers.get(INTERNAL_API_KEY_HEADER))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { stackId } = await params;

  // Look up the stack to get its organizationId
  const stack = await prisma.pipelineStack.findUnique({
    where: { id: stackId },
    select: { organizationId: true },
  });

  if (!stack) {
    return NextResponse.json({ error: 'Stack not found' }, { status: 404 });
  }

  // Build a synthetic session for scanner API calls. Use any user in the org
  // as the acting principal — this is an internal system trigger, not a user action.
  const actingUser = await prisma.user.findFirst({
    where: { organizationId: stack.organizationId },
    select: { id: true },
  });

  if (!actingUser) {
    return NextResponse.json(
      { error: 'No user found in organization to act as principal' },
      { status: 500 },
    );
  }

  const syntheticSession = {
    user: {
      id: actingUser.id,
      organizationId: stack.organizationId,
    },
    expires: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  } as unknown as Session;

  console.log(`[LINEAGE-SCHEDULED] Starting auto-extraction for stack ${stackId}`);
  const start = Date.now();

  try {
    const result = await extractLineageForStack(stackId, stack.organizationId, {}, syntheticSession);
    const duration = Date.now() - start;

    if (result.status === 200) {
      const data = await result.json();
      console.log(
        `[LINEAGE-SCHEDULED] Completed for stack ${stackId}: ` +
        `${data.stats?.totalNodes || 0} nodes, ${data.stats?.totalEdges || 0} edges, ${duration}ms`
      );
      return NextResponse.json({
        success: true,
        nodes: data.stats?.totalNodes || 0,
        edges: data.stats?.totalEdges || 0,
        durationMs: duration,
      });
    } else {
      console.warn(`[LINEAGE-SCHEDULED] Failed for stack ${stackId}: HTTP ${result.status}, ${duration}ms`);
      return NextResponse.json(
        { error: `Extraction failed with status ${result.status}` },
        { status: 500 }
      );
    }
  } catch (error) {
    const duration = Date.now() - start;
    console.error(`[LINEAGE-SCHEDULED] Error for stack ${stackId}: ${error}, ${duration}ms`);
    return NextResponse.json({ error: 'Internal error during extraction' }, { status: 500 });
  }
}
