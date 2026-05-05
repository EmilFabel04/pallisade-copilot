import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const DAY_MS = 24 * 60 * 60 * 1000;

function dayBuckets(start: Date, end: Date): Date[] {
  const out: Date[] = [];
  const d0 = new Date(start);
  d0.setUTCHours(0, 0, 0, 0);
  while (d0.getTime() <= end.getTime()) {
    out.push(new Date(d0));
    d0.setUTCDate(d0.getUTCDate() + 1);
  }
  return out;
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const url = new URL(request.url);
  const stackId = url.searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });
  const windowDays = Number(url.searchParams.get('window')?.replace('d', '') ?? 7);

  const now = new Date();
  const windowStart = new Date(now.getTime() - windowDays * DAY_MS);
  const priorStart = new Date(windowStart.getTime() - windowDays * DAY_MS);

  // Pass rate uses MonitorRun rows joined to Monitor → MonitorGroup → pipelineStackId
  // For simplicity (and to keep SQL-via-Prisma ergonomic) we fetch monitors first.
  const monitorIds = (await prisma.monitor.findMany({
    where: { organizationId, monitorGroup: { pipelineStackId: stackId } },
    select: { id: true },
  })).map((m) => m.id);

  async function passRate(from: Date, to: Date) {
    if (monitorIds.length === 0) return null;
    const total = await prisma.monitorRun.count({
      where: { monitorId: { in: monitorIds }, startedAt: { gte: from, lt: to } },
    });
    if (total === 0) return null;
    const passing = await prisma.monitorRun.count({
      where: { monitorId: { in: monitorIds }, startedAt: { gte: from, lt: to }, status: 'PASS' },
    });
    return passing / total;
  }

  const [openedNow, openedPrior, resolvedNow, resolvedPrior, currentPass, priorPass] = await Promise.all([
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, openedAt: { gte: windowStart, lt: now } } }),
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, openedAt: { gte: priorStart, lt: windowStart } } }),
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: windowStart, lt: now } } }),
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: priorStart, lt: windowStart } } }),
    passRate(windowStart, now),
    passRate(priorStart, windowStart),
  ]);

  // MTTR: avg(resolvedAt - openedAt) over incidents resolved in window
  const resolvedIncidents = await prisma.incident.findMany({
    where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: windowStart, lt: now } },
    select: { openedAt: true, resolvedAt: true },
  });
  const mttrMs = resolvedIncidents.length === 0
    ? null
    : resolvedIncidents.reduce((s, i) => s + (i.resolvedAt!.getTime() - i.openedAt.getTime()), 0) / resolvedIncidents.length;

  const priorResolved = await prisma.incident.findMany({
    where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: priorStart, lt: windowStart } },
    select: { openedAt: true, resolvedAt: true },
  });
  const priorMttrMs = priorResolved.length === 0
    ? null
    : priorResolved.reduce((s, i) => s + (i.resolvedAt!.getTime() - i.openedAt.getTime()), 0) / priorResolved.length;

  // Daily sparkline: 1 bucket per day, count of incidents opened
  const buckets = dayBuckets(windowStart, now);
  const opened = await prisma.incident.findMany({
    where: { organizationId, pipelineStackId: stackId, openedAt: { gte: windowStart, lt: now } },
    select: { openedAt: true },
  });
  const openedByDay = buckets.map((day, i) => {
    const next = buckets[i + 1] ?? now;
    return opened.filter((o) => o.openedAt >= day && o.openedAt < next).length;
  });

  return NextResponse.json({
    windowDays,
    passRate: { current: currentPass, prior: priorPass },
    mttrMs:    { current: mttrMs,     prior: priorMttrMs },
    opened:    { current: openedNow,  prior: openedPrior, sparkline: openedByDay },
    recovered: { current: resolvedNow, prior: resolvedPrior, ratio: openedNow === 0 ? null : resolvedNow / openedNow },
  });
}
