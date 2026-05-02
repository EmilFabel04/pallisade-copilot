/**
 * POST /api/context-requests/create
 *
 * Creates a ContextRequest row on behalf of a guesser running inside FastAPI
 * (today: SLA discovery's timestamp picker — see
 *  scanner/lineage/sla_discovery.py:_call_nextjs_create_context_request).
 *
 * FastAPI has no Prisma client in this project, so all DB writes for
 * ContextRequest live in Next.js. The matching answer-side endpoint is
 * /api/clarifications/resolve.
 *
 * Auth: dual — session cookie OR internal shared-secret
 *   (X-Internal-Secret + X-Organization-Id), mirroring the dual-auth in
 *   /api/clarifications/resolve.
 *
 * Body: {
 *   pipelineStackId: string,
 *   kind: string,
 *   scopeType: string,
 *   scopeRef: string,
 *   payload: object,
 *   priority?: 'low' | 'normal' | 'high'
 * }
 *
 * Behaviour:
 *   1. Org-scope the pipelineStackId.
 *   2. Dedupe: if an OPEN request exists for the same
 *      (pipelineStackId, kind, scopeType, scopeRef), return its id —
 *      do not create a duplicate.
 *   3. Suppress: if a recently-DISMISSED request has dismissedUntil > now,
 *      return { suppressed: true } and create nothing.
 *   4. Otherwise create the row and return { id, created: true }.
 */
import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { Prisma } from '@prisma/client';
import { auth } from '@/auth';
import prisma from '@/lib/db';

interface CreateBody {
  pipelineStackId?: string;
  kind?: string;
  scopeType?: string;
  scopeRef?: string;
  payload?: unknown;
  priority?: string;
}

type AuthContext =
  | { ok: true; session: Session; organizationId: string; via: 'session' | 'internal' }
  | { ok: false; status: number; error: string };

async function resolveCaller(request: NextRequest): Promise<AuthContext> {
  const internalSecret = request.headers.get('X-Internal-Secret');
  const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

  if (internalSecret && internalSecret === expectedSecret) {
    const organizationId = request.headers.get('X-Organization-Id') || undefined;
    if (!organizationId) {
      return { ok: false, status: 400, error: 'missing X-Organization-Id' };
    }
    const session = {
      user: { id: 'copilot-system', organizationId },
      expires: '',
    } as unknown as Session;
    return { ok: true, session, organizationId, via: 'internal' };
  }

  const session = await auth();
  if (!session?.user) {
    return { ok: false, status: 401, error: 'Unauthorized' };
  }
  const organizationId = (session.user as any).organizationId as string | undefined;
  if (!organizationId) {
    return { ok: false, status: 400, error: 'No organization' };
  }
  return { ok: true, session, organizationId, via: 'session' };
}

const VALID_PRIORITIES = new Set(['low', 'normal', 'high']);

export async function POST(request: NextRequest) {
  try {
    const authCtx = await resolveCaller(request);
    if (!authCtx.ok) {
      return NextResponse.json({ error: authCtx.error }, { status: authCtx.status });
    }
    const { organizationId } = authCtx;

    let body: CreateBody;
    try {
      body = (await request.json()) as CreateBody;
    } catch {
      return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
    }

    const pipelineStackId = typeof body.pipelineStackId === 'string' ? body.pipelineStackId : '';
    const kind = typeof body.kind === 'string' ? body.kind : '';
    const scopeType = typeof body.scopeType === 'string' ? body.scopeType : '';
    const scopeRef = typeof body.scopeRef === 'string' ? body.scopeRef : '';
    const payloadRaw = body.payload;
    const priority =
      typeof body.priority === 'string' && VALID_PRIORITIES.has(body.priority)
        ? body.priority
        : 'normal';

    if (!pipelineStackId) {
      return NextResponse.json({ error: 'pipelineStackId required' }, { status: 400 });
    }
    if (!kind) {
      return NextResponse.json({ error: 'kind required' }, { status: 400 });
    }
    if (!scopeType) {
      return NextResponse.json({ error: 'scopeType required' }, { status: 400 });
    }
    if (!scopeRef) {
      return NextResponse.json({ error: 'scopeRef required' }, { status: 400 });
    }
    if (
      payloadRaw === null ||
      payloadRaw === undefined ||
      typeof payloadRaw !== 'object' ||
      Array.isArray(payloadRaw)
    ) {
      return NextResponse.json({ error: 'payload (object) required' }, { status: 400 });
    }

    // Org-scope the pipeline stack — refuse to create a request on a stack
    // outside the caller's organization.
    const stack = await prisma.pipelineStack.findFirst({
      where: { id: pipelineStackId, organizationId },
      select: { id: true },
    });
    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    // Suppress if the user recently dismissed an identical request — we honour
    // the dismissedUntil cooldown for the same scope so guessers do not
    // re-pop the same popup the user just closed.
    const now = new Date();
    const dismissed = await prisma.contextRequest.findFirst({
      where: {
        pipelineStackId,
        kind,
        scopeType,
        scopeRef,
        status: 'dismissed',
        dismissedUntil: { gt: now },
      },
      orderBy: { createdAt: 'desc' },
      select: { id: true, dismissedUntil: true },
    });
    if (dismissed) {
      return NextResponse.json({
        suppressed: true,
        reason: 'recently_dismissed',
        dismissedUntil: dismissed.dismissedUntil ? dismissed.dismissedUntil.toISOString() : null,
      });
    }

    // Dedupe: if an OPEN request already exists for the same scope, return it.
    const existing = await prisma.contextRequest.findFirst({
      where: {
        pipelineStackId,
        kind,
        scopeType,
        scopeRef,
        status: 'open',
      },
      orderBy: { createdAt: 'desc' },
      select: {
        id: true,
        kind: true,
        scopeType: true,
        scopeRef: true,
        payload: true,
        status: true,
        priority: true,
        createdAt: true,
      },
    });
    if (existing) {
      return NextResponse.json({
        id: existing.id,
        created: false,
        deduped: true,
        kind: existing.kind,
        scope_type: existing.scopeType,
        scope_ref: existing.scopeRef,
        status: existing.status,
        priority: existing.priority,
        created_at: existing.createdAt.toISOString(),
      });
    }

    // Otherwise create a fresh row.
    const created = await prisma.contextRequest.create({
      data: {
        pipelineStackId,
        kind,
        scopeType,
        scopeRef,
        payload: payloadRaw as Prisma.InputJsonValue,
        priority,
        status: 'open',
      },
      select: {
        id: true,
        kind: true,
        scopeType: true,
        scopeRef: true,
        status: true,
        priority: true,
        createdAt: true,
      },
    });

    return NextResponse.json(
      {
        id: created.id,
        created: true,
        deduped: false,
        kind: created.kind,
        scope_type: created.scopeType,
        scope_ref: created.scopeRef,
        status: created.status,
        priority: created.priority,
        created_at: created.createdAt.toISOString(),
      },
      { status: 201 },
    );
  } catch (err) {
    console.error('[context-requests/create] failed', err);
    return NextResponse.json(
      { error: 'failed to create context request', detail: String((err as Error).message ?? err) },
      { status: 500 },
    );
  }
}
