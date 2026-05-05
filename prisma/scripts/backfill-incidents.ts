/**
 * One-shot backfill: open an Incident for each currently-failing monitor
 * that has no existing Incident. Run once after deploy.
 *
 * Run with: npx tsx prisma/scripts/backfill-incidents.ts
 */
import prisma from '@/lib/db';

async function main() {
  const failing = await prisma.monitor.findMany({
    where: { lastStatus: { in: ['FAIL', 'WARN', 'ERROR'] } },
    include: { monitorGroup: true, runs: { take: 1, orderBy: { startedAt: 'desc' } } },
  });
  let opened = 0;
  for (const m of failing) {
    const existing = await prisma.incident.findFirst({
      where: { monitorId: m.id, status: { in: ['OPEN', 'ACKNOWLEDGED'] } },
    });
    if (existing) continue;
    const run = m.runs[0];
    if (!run || !m.monitorGroup) continue;
    const severity = m.lastStatus === 'WARN' ? 'WARN' : 'FAIL';
    await prisma.incident.create({
      data: {
        organizationId: m.organizationId ?? m.monitorGroup.organizationId,
        pipelineStackId: m.pipelineStackId,
        monitorId: m.id,
        monitorGroupId: m.monitorGroupId ?? null,
        targetFqn: m.targetFqn ?? 'unknown',
        status: 'OPEN',
        severity,
        openedAt: run.startedAt,
        openingRunId: run.id,
        signature: 'backfilled',
        consecutiveCount: 1,
        llmHypothesis: 'Backfilled — analysis pending. Click "Open in Co-pilot" to investigate.',
      },
    });
    opened += 1;
  }
  console.log(`Backfill complete. Opened ${opened} incident(s).`);
  await prisma.$disconnect();
}

main().catch((e) => { console.error(e); process.exit(1); });
