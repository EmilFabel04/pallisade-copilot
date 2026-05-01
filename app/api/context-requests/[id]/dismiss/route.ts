/**
 * POST /api/context-requests/{id}/dismiss
 *
 * Marks an open ContextRequest as dismissed and sets dismissedUntil to
 * now + CONFIG.dismiss_decay_days (14 days). The clarification engine's
 * suppression check reads this window to avoid re-asking the same
 * question for that period.
 */
import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// Mirrors copilot.clarifications.config.CONFIG.dismiss_decay_days. Hard-coded
// here so the Next.js layer doesn't need to round-trip to FastAPI for a
// constant. If the Python value ever changes, update this in lockstep.
const DISMISS_DECAY_DAYS = 14;

export async function POST(
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

    const existing = await prisma.contextRequest.findUnique({
      where: { id },
      select: {
        id: true,
        status: true,
        pipelineStack: { select: { organizationId: true } },
      },
    });
    if (!existing) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    if (existing.pipelineStack?.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    if (existing.status !== 'open') {
      return NextResponse.json(
        { error: `cannot dismiss request in status ${existing.status}` },
        { status: 409 },
      );
    }

    const dismissedUntil = new Date(Date.now() + DISMISS_DECAY_DAYS * 24 * 60 * 60 * 1000);

    await prisma.contextRequest.update({
      where: { id },
      data: {
        status: 'dismissed',
        dismissedUntil,
      },
    });

    return NextResponse.json({
      ok: true,
      id,
      dismissed_until: dismissedUntil.toISOString(),
    });
  } catch (err) {
    console.error('[context-requests/[id]/dismiss] failed', err);
    return NextResponse.json(
      { error: 'failed to dismiss context request', detail: String((err as Error).message ?? err) },
      { status: 500 },
    );
  }
}
