import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

function authorize(request: NextRequest): { ok: true; orgId: string } | { ok: false; status: number; error: string } {
  const secret = request.headers.get('X-Internal-Secret');
  const expected = process.env.INTERNAL_API_SECRET || 'pallisade-internal';
  if (!secret || secret !== expected) {
    return { ok: false, status: 401, error: 'invalid internal secret' };
  }
  const orgId = request.headers.get('X-Organization-Id');
  if (!orgId) {
    return { ok: false, status: 400, error: 'missing X-Organization-Id' };
  }
  return { ok: true, orgId };
}

export async function POST(request: NextRequest) {
  const auth = authorize(request);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    /* empty body */
  }

  const monitorId: string | undefined = typeof body?.monitor_id === 'string' ? body.monitor_id : undefined;
  if (!monitorId) {
    return NextResponse.json({ error: 'monitor_id is required' }, { status: 400 });
  }

  try {
    const monitor = await prisma.monitor.findFirst({
      where: { id: monitorId, organizationId: auth.orgId },
      select: { id: true, name: true, monitorType: true, targetFqn: true },
    });
    if (!monitor) {
      return NextResponse.json({ error: 'monitor not found' }, { status: 404 });
    }

    const limitRaw = Number.isFinite(body?.limit) ? Number(body.limit) : 10;
    const limit = Math.max(1, Math.min(50, Math.trunc(limitRaw)));

    const runs = await prisma.monitorRun.findMany({
      where: { monitorId: monitor.id },
      select: {
        id: true,
        status: true,
        value: true,
        threshold: true,
        message: true,
        details: true,
        sqlExecuted: true,
        startedAt: true,
        completedAt: true,
        durationMs: true,
      },
      orderBy: { startedAt: 'desc' },
      take: limit,
    });

    return NextResponse.json({
      monitor,
      runs: runs.map((r) => ({
        ...r,
        startedAt: r.startedAt.toISOString(),
        completedAt: r.completedAt ? r.completedAt.toISOString() : null,
      })),
      total: runs.length,
    });
  } catch (err) {
    console.error('[get-monitor-run-history] prisma query failed', { monitorId, err });
    return NextResponse.json(
      { error: 'failed to query monitor history', detail: String((err as Error).message ?? err) },
      { status: 500 },
    );
  }
}
