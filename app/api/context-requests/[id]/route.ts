/**
 * GET /api/context-requests/{id}
 *
 * Fetch a single ContextRequest by id. Used by the popup chat to render
 * a specific clarification's payload + status.
 */
import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const organizationId = (session.user as any).organizationId as string | undefined;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    const { id } = await params;
    if (!id) {
      return NextResponse.json({ error: 'id required' }, { status: 400 });
    }

    const row = await prisma.contextRequest.findUnique({
      where: { id },
      select: {
        id: true,
        pipelineStackId: true,
        kind: true,
        scopeType: true,
        scopeRef: true,
        payload: true,
        status: true,
        priority: true,
        createdAt: true,
        resolvedAt: true,
        dismissedUntil: true,
        resolutionId: true,
        resolution: { select: { answer: true } },
        pipelineStack: { select: { organizationId: true } },
      },
    });

    if (!row) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    // Org-scope: don't leak rows that belong to a different organization.
    if (row.pipelineStack?.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }

    return NextResponse.json({
      id: row.id,
      pipeline_stack_id: row.pipelineStackId,
      kind: row.kind,
      scope_type: row.scopeType,
      scope_ref: row.scopeRef,
      payload: row.payload,
      status: row.status,
      priority: row.priority,
      created_at: row.createdAt.toISOString(),
      resolved_at: row.resolvedAt ? row.resolvedAt.toISOString() : null,
      dismissed_until: row.dismissedUntil ? row.dismissedUntil.toISOString() : null,
      resolution_id: row.resolutionId,
      answer: row.resolution?.answer ?? null,
    });
  } catch (err) {
    console.error('[context-requests/[id]] get failed', err);
    return NextResponse.json(
      { error: 'failed to fetch context request', detail: String((err as Error).message ?? err) },
      { status: 500 },
    );
  }
}
