/**
 * POST /api/clarifications/resolve
 *
 * Production write path for ContextRequest answers. Two callers:
 *
 *   1. The copilot tool executor (record_clarification_answer tool, see
 *      scanner/copilot/tool_executor.py:5532). It POSTs with internal
 *      shared-secret auth (X-Internal-Secret + X-Organization-Id) and
 *      expects {kind, scopeType, scopeRef, conventionUpdated} back.
 *
 *   2. The popup chat (Task 15). It POSTs with the user's session
 *      cookie. Session auth happens via auth().
 *
 * Flow:
 *
 *   - Load the ContextRequest from Prisma + verify org-scope.
 *   - Forward the row + answer to FastAPI POST
 *     /api/v1/context-requests/compute-resolution. FastAPI runs the kind
 *     handler's validate_answer + on_resolve, returns the populated
 *     conventions/overrides + a conventionUpdated flag, and emits the
 *     in-process BUS event for guessers.
 *   - Persist sequentially (no Prisma transaction wrapper here — the spec
 *     accepts that the resolution + status update aren't strictly atomic
 *     in v1, see Task 12 brief):
 *       a. Create ContextResolution
 *       b. Update ContextRequest (status="answered", resolvedAt, resolutionId)
 *       c. Merge conventions into PipelineContext.conventionsContext
 *       d. Merge per-node overrides into matching PolicyAssignment.overrides
 *
 * The shape returned to the tool executor matches what it expects in
 * scanner/copilot/tool_executor.py:5615-5627.
 */
import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { Prisma } from '@prisma/client';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';

interface ResolveBody {
  requestId?: string;
  answer?: Record<string, unknown>;
  proposeConvention?: boolean;
  transcript?: Array<{ role: string; content: string }>;
}

type AuthContext =
  | { ok: true; session: Session; organizationId: string; userId: string; via: 'session' | 'internal' }
  | { ok: false; status: number; error: string };

async function resolveCaller(request: NextRequest): Promise<AuthContext> {
  const internalSecret = request.headers.get('X-Internal-Secret');
  const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

  if (internalSecret && internalSecret === expectedSecret) {
    const organizationId = request.headers.get('X-Organization-Id') || undefined;
    if (!organizationId) {
      return { ok: false, status: 400, error: 'missing X-Organization-Id' };
    }
    const userId = 'copilot-system';
    const session = {
      user: { id: userId, organizationId },
      expires: '',
    } as unknown as Session;
    return { ok: true, session, organizationId, userId, via: 'internal' };
  }

  const session = await auth();
  if (!session?.user) {
    return { ok: false, status: 401, error: 'Unauthorized' };
  }
  const organizationId = (session.user as any).organizationId as string | undefined;
  const userId = (session.user as any).id as string | undefined;
  if (!organizationId || !userId) {
    return { ok: false, status: 400, error: 'No organization' };
  }
  return { ok: true, session, organizationId, userId, via: 'session' };
}

export async function POST(request: NextRequest) {
  try {
    const authCtx = await resolveCaller(request);
    if (!authCtx.ok) {
      return NextResponse.json({ error: authCtx.error }, { status: authCtx.status });
    }
    const { session, organizationId, userId } = authCtx;

    let body: ResolveBody;
    try {
      body = (await request.json()) as ResolveBody;
    } catch {
      return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
    }

    const requestId = typeof body.requestId === 'string' ? body.requestId : undefined;
    const answer = body.answer;
    if (!requestId) {
      return NextResponse.json({ error: 'requestId required' }, { status: 400 });
    }
    if (!answer || typeof answer !== 'object' || Array.isArray(answer)) {
      return NextResponse.json({ error: 'answer (object) required' }, { status: 400 });
    }
    const transcript = Array.isArray(body.transcript) ? body.transcript : [];
    const proposeConvention = body.proposeConvention === true;

    // 1. Load + org-scope the request.
    const row = await prisma.contextRequest.findUnique({
      where: { id: requestId },
      select: {
        id: true,
        pipelineStackId: true,
        kind: true,
        scopeType: true,
        scopeRef: true,
        payload: true,
        status: true,
        priority: true,
        pipelineStack: { select: { organizationId: true } },
      },
    });
    if (!row) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    if (row.pipelineStack?.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    if (row.status !== 'open') {
      return NextResponse.json(
        { error: `request is ${row.status}, not open` },
        { status: 409 },
      );
    }

    // 2. Forward to FastAPI for validation + on_resolve. This is where the
    //    Python kind handler runs and decides what conventions/overrides
    //    to persist.
    const fastapiResp = await scannerClient.fetch(session, '/api/v1/context-requests/compute-resolution', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request: {
          id: row.id,
          pipelineStackId: row.pipelineStackId,
          kind: row.kind,
          scopeType: row.scopeType,
          scopeRef: row.scopeRef,
          payload: row.payload ?? {},
          status: row.status,
          priority: row.priority,
        },
        answer,
        transcript,
        proposeConvention,
      }),
    });

    if (!fastapiResp.ok) {
      const text = await fastapiResp.text();
      console.error('[clarifications/resolve] FastAPI compute-resolution failed', fastapiResp.status, text);
      // Surface 4xx (validation/conflict) directly so the LLM can repair the
      // answer; collapse 5xx into a 502 so callers know it's upstream.
      const status = fastapiResp.status >= 400 && fastapiResp.status < 500 ? fastapiResp.status : 502;
      return NextResponse.json(
        { error: 'compute-resolution failed', detail: text },
        { status },
      );
    }

    const computed = (await fastapiResp.json()) as {
      ok: boolean;
      kind: string;
      scopeType: string;
      scopeRef: string;
      conventionUpdated: boolean;
      conventions: Record<string, unknown>;
      overrides: Record<string, Record<string, unknown>>;
    };

    // 3a. Create the ContextResolution row.
    const resolution = await prisma.contextResolution.create({
      data: {
        requestId: row.id,
        answer: answer as Prisma.InputJsonValue,
        transcript: transcript as unknown as Prisma.InputJsonValue,
        conventionUpdate: computed.conventionUpdated
          ? (computed.conventions as Prisma.InputJsonValue)
          : Prisma.JsonNull,
        answeredBy: userId,
      },
      select: { id: true },
    });

    // 3b. Mark the request as answered and link the resolution.
    await prisma.contextRequest.update({
      where: { id: row.id },
      data: {
        status: 'answered',
        resolvedAt: new Date(),
        resolutionId: resolution.id,
      },
    });

    // 3c. Merge conventions into PipelineContext.conventionsContext for the
    //     pipeline stack. Upsert so a stack without a context row still
    //     ends up with the convention persisted.
    let conventionUpdated = false;
    if (
      computed.conventionUpdated &&
      computed.conventions &&
      Object.keys(computed.conventions).length > 0
    ) {
      const existing = await prisma.pipelineContext.findUnique({
        where: { pipelineStackId: row.pipelineStackId },
        select: { id: true, conventionsContext: true },
      });
      const merged = {
        ...((existing?.conventionsContext as Record<string, unknown>) ?? {}),
        ...computed.conventions,
      };
      if (existing) {
        await prisma.pipelineContext.update({
          where: { pipelineStackId: row.pipelineStackId },
          data: { conventionsContext: merged as Prisma.InputJsonValue },
        });
      } else {
        await prisma.pipelineContext.create({
          data: {
            pipelineStackId: row.pipelineStackId,
            conventionsContext: merged as Prisma.InputJsonValue,
          },
        });
      }
      conventionUpdated = true;
    }

    // 3d. Merge per-node overrides into PolicyAssignment.overrides where
    //     a direct assignment for that nodeFqn exists. If no PolicyAssignment
    //     is in place yet the override is dropped silently — the matching
    //     assignment will be created later by the policies UI, and the
    //     convention layer (3c) is the durable record. This matches the
    //     "skip silently" guidance in the Task 12 brief.
    if (computed.overrides && typeof computed.overrides === 'object') {
      for (const [nodeFqn, payload] of Object.entries(computed.overrides)) {
        if (!payload || typeof payload !== 'object') continue;
        const assignment = await prisma.policyAssignment.findFirst({
          where: {
            organizationId,
            assignmentType: 'direct',
            nodeFqn,
          },
          select: { id: true, overrides: true },
        });
        if (!assignment) continue;
        const mergedOverrides = {
          ...((assignment.overrides as Record<string, unknown>) ?? {}),
          ...(payload as Record<string, unknown>),
        };
        await prisma.policyAssignment.update({
          where: { id: assignment.id },
          data: { overrides: mergedOverrides as Prisma.InputJsonValue },
        });
      }
    }

    // The shape here matches what the copilot tool executor reads at
    // scanner/copilot/tool_executor.py:5615-5627.
    return NextResponse.json({
      ok: true,
      kind: computed.kind,
      scopeType: computed.scopeType,
      scopeRef: computed.scopeRef,
      conventionUpdated,
      resolutionId: resolution.id,
    });
  } catch (err) {
    console.error('[clarifications/resolve] failed', err);
    return NextResponse.json(
      { error: 'failed to resolve clarification', detail: String((err as Error).message ?? err) },
      { status: 500 },
    );
  }
}
