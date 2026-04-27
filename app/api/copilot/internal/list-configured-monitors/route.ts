import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

const VALID_STATUSES = new Set(['PASS', 'WARN', 'FAIL', 'ERROR', 'SKIPPED', 'RUNNING']);

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

function normalizeList(value: unknown): string[] | undefined {
  if (value == null) return undefined;
  const arr = Array.isArray(value) ? value : [value];
  return arr.filter((v): v is string => typeof v === 'string' && v.length > 0)
            .map((v) => v.toUpperCase());
}

export async function POST(request: NextRequest) {
  const auth = authorize(request);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    /* empty body is fine */
  }

  const monitorTypes = normalizeList(body?.monitor_type);
  const statuses = normalizeList(body?.status)?.filter((s) => VALID_STATUSES.has(s));
  const targetFqn: string | undefined = typeof body?.target_fqn === 'string' ? body.target_fqn : undefined;
  const enabled: boolean | undefined = typeof body?.enabled === 'boolean' ? body.enabled : undefined;

  const limitRaw = Number.isFinite(body?.limit) ? Number(body.limit) : 50;
  const limit = Math.max(1, Math.min(200, Math.trunc(limitRaw)));

  const where: Record<string, any> = { organizationId: auth.orgId };
  if (monitorTypes && monitorTypes.length > 0) where.monitorType = { in: monitorTypes };
  if (statuses && statuses.length > 0) where.lastStatus = { in: statuses };
  if (targetFqn) where.targetFqn = targetFqn;
  if (typeof enabled === 'boolean') where.enabled = enabled;

  const monitors = await prisma.monitor.findMany({
    where,
    select: {
      id: true,
      name: true,
      monitorType: true,
      targetFqn: true,
      targetDatabase: true,
      targetSchema: true,
      targetTable: true,
      enabled: true,
      schedule: true,
      lastRunAt: true,
      lastStatus: true,
      nextRunAt: true,
      description: true,
    },
    orderBy: [
      { lastStatus: 'desc' },
      { lastRunAt: 'desc' },
    ],
    take: limit,
  });

  return NextResponse.json({
    monitors: monitors.map((m) => ({
      ...m,
      lastRunAt: m.lastRunAt ? m.lastRunAt.toISOString() : null,
      nextRunAt: m.nextRunAt ? m.nextRunAt.toISOString() : null,
    })),
    total: monitors.length,
  });
}
