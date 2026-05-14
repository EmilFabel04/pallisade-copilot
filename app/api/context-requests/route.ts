/**
 * GET /api/context-requests?pipeline_stack_id=...&status=open&limit=50
 *
 * Lists ContextRequest rows for the popup chat (Task 15). Reads directly
 * from Prisma — FastAPI has no DB client, so all reads/writes for
 * ContextRequest live here. The "answer" path is via
 * /api/clarifications/resolve, which is what the copilot tool executor
 * calls after the user answers.
 */
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 200;

const VALID_STATUSES = new Set(['open', 'answered', 'dismissed']);

export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const organizationId = (session.user as any).organizationId as string | undefined;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    const sp = request.nextUrl.searchParams;
    const pipelineStackId = sp.get('pipeline_stack_id') || sp.get('pipelineStackId');
    if (!pipelineStackId) {
      return NextResponse.json(
        { error: 'pipeline_stack_id required' },
        { status: 400 },
      );
    }

    // Verify the stack belongs to this org — prevents cross-org enumeration.
    const stack = await prisma.pipelineStack.findFirst({
      where: { id: pipelineStackId, organizationId },
      select: { id: true },
    });
    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    // Accept comma-separated list (e.g. "open,answered") so callers polling
    // for transitions (open → answered) can fetch both in one round-trip.
    const rawStatus = sp.get('status') || 'open';
    const statuses = rawStatus.split(',').map((s) => s.trim()).filter(Boolean);
    for (const s of statuses) {
      if (!VALID_STATUSES.has(s)) {
        return NextResponse.json(
          { error: `invalid status; expected one of ${[...VALID_STATUSES].join(', ')}` },
          { status: 400 },
        );
      }
    }

    const limitRaw = Number(sp.get('limit') ?? DEFAULT_LIMIT);
    const limit = Math.max(
      1,
      Math.min(MAX_LIMIT, Number.isFinite(limitRaw) ? Math.trunc(limitRaw) : DEFAULT_LIMIT),
    );

    const rows = await prisma.contextRequest.findMany({
      where: {
        pipelineStackId,
        status: statuses.length === 1 ? statuses[0] : { in: statuses },
      },
      orderBy: { createdAt: 'desc' },
      take: limit,
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
      },
    });

    return NextResponse.json({
      items: rows.map((r) => ({
        id: r.id,
        pipeline_stack_id: r.pipelineStackId,
        kind: r.kind,
        scope_type: r.scopeType,
        scope_ref: r.scopeRef,
        payload: r.payload,
        status: r.status,
        priority: r.priority,
        created_at: r.createdAt.toISOString(),
        resolved_at: r.resolvedAt ? r.resolvedAt.toISOString() : null,
        dismissed_until: r.dismissedUntil ? r.dismissedUntil.toISOString() : null,
      })),
    });
  } catch (err) {
    console.error('[context-requests] list failed', err);
    return NextResponse.json(
      { error: 'failed to list context requests', detail: String((err as Error).message ?? err) },
      { status: 500 },
    );
  }
}
