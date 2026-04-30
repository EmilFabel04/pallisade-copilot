/**
 * GET /api/pipeline-context/[stackId]/conventions
 *
 * Returns the pipeline's `conventionsContext` JSON. Used by FastAPI-side
 * monitor evaluation to enforce dampening rules written by the
 * failure_review clarification kind. Dual-auth like
 * /api/clarifications/resolve: session OR internal-secret.
 */
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

async function resolveOrgId(request: NextRequest): Promise<{ ok: true; organizationId: string } | { ok: false; status: number; error: string }> {
  const internalSecret = request.headers.get('X-Internal-Secret');
  const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

  if (internalSecret && internalSecret === expectedSecret) {
    const organizationId = request.headers.get('X-Organization-Id') || undefined;
    if (!organizationId) return { ok: false, status: 400, error: 'missing X-Organization-Id' };
    return { ok: true, organizationId };
  }

  const session = await auth();
  if (!session?.user) return { ok: false, status: 401, error: 'Unauthorized' };
  const organizationId = (session.user as any).organizationId as string | undefined;
  if (!organizationId) return { ok: false, status: 400, error: 'No organization' };
  return { ok: true, organizationId };
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> },
) {
  const authResult = await resolveOrgId(request);
  if (!authResult.ok) {
    return NextResponse.json({ error: authResult.error }, { status: authResult.status });
  }
  const { organizationId } = authResult;
  const { stackId } = await params;

  const stack = await prisma.pipelineStack.findFirst({
    where: { id: stackId, organizationId },
    select: { id: true },
  });
  if (!stack) {
    return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
  }

  const ctx = await prisma.pipelineContext.findUnique({
    where: { pipelineStackId: stackId },
    select: { conventionsContext: true },
  });

  return NextResponse.json({
    conventions: (ctx?.conventionsContext as Record<string, unknown> | null) ?? {},
  });
}
