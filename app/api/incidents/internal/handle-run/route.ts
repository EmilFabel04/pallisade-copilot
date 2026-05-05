import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';
import { verifyInternalApiKey, INTERNAL_API_KEY_HEADER } from '@/lib/internal-api-key';
import { handleRun } from '@/lib/incidents/lifecycle';
import { diagnoseIncident } from '@/lib/incidents/diagnose';

/**
 * Server-to-server endpoint called by the Python scheduler after it persists
 * a MonitorRun row directly via SQL. Runs the same incident lifecycle and LLM
 * diagnosis fan-out that app/api/schedule/tasks/[taskId]/run/route.ts runs
 * for manual triggers, so scheduled monitor runs also produce incidents.
 */
export async function POST(request: NextRequest) {
  if (!verifyInternalApiKey(request.headers.get(INTERNAL_API_KEY_HEADER))) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  let body: { runId?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const runId = body.runId;
  if (!runId || typeof runId !== 'string') {
    return NextResponse.json({ error: 'runId is required' }, { status: 400 });
  }

  const run = await prisma.monitorRun.findUnique({ where: { id: runId } });
  if (!run) {
    return NextResponse.json({ error: 'run not found' }, { status: 404 });
  }

  let lc;
  try {
    lc = await handleRun(run, prisma);
  } catch (err) {
    console.error('[incidents.internal] lifecycle.handleRun failed', {
      runId,
      error: err instanceof Error ? `${err.name}: ${err.message}` : String(err),
    });
    return NextResponse.json({ error: 'lifecycle failed' }, { status: 500 });
  }

  if (lc.shouldDiagnose && lc.incidentId) {
    void diagnoseIncident(lc.incidentId, prisma).catch((err) => {
      console.error('[incidents.internal] diagnose failed', {
        incidentId: lc.incidentId,
        error: err instanceof Error ? `${err.name}: ${err.message}` : String(err),
      });
    });
  }

  return NextResponse.json({
    action: lc.action,
    incidentId: lc.incidentId ?? null,
    diagnosing: !!(lc.shouldDiagnose && lc.incidentId),
  });
}
