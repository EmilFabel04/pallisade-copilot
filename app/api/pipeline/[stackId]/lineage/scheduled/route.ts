import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';
import { extractLineageForStack } from '../extract-lineage';

const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY || 'dev-internal-key-not-for-production';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  // Authenticate via internal API key
  const apiKey = request.headers.get('x-internal-api-key');
  if (apiKey !== INTERNAL_API_KEY) {
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

  console.log(`[LINEAGE-SCHEDULED] Starting auto-extraction for stack ${stackId}`);
  const start = Date.now();

  try {
    const result = await extractLineageForStack(stackId, stack.organizationId, {});
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
