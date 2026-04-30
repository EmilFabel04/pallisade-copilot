/**
 * One-time repair: re-enable MonitorGroups that are visibly active but have
 * `enabled=false`.
 *
 * After the per-asset dedupe migration (scripts/dedupe-monitor-groups.ts),
 * the surviving "winner" group can be in `enabled=false` state if the
 * older group had been disabled at some point. The merged monitors then
 * appear active (passes, recent runs) but the group toggle shows off.
 *
 * Heuristic: a group is "visibly active" if it owns at least one monitor
 * whose `enabled=true`. If so AND the group's `enabled=false`, flip the
 * group to `enabled=true`.
 *
 * Run dry-run:
 *   npx tsx scripts/reenable-active-monitor-groups.ts
 *
 * Apply:
 *   npx tsx scripts/reenable-active-monitor-groups.ts --apply
 *
 * Safe to re-run.
 */

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  const apply = process.argv.includes('--apply');

  console.log(`Mode: ${apply ? 'APPLY (will mutate)' : 'DRY RUN (no writes)'}`);
  console.log('');

  // Find disabled groups whose member monitors include at least one enabled.
  const groups = await prisma.monitorGroup.findMany({
    where: {
      enabled: false,
      monitors: { some: { enabled: true } },
    },
    select: {
      id: true,
      anchorFqn: true,
      _count: { select: { monitors: true } },
      monitors: { where: { enabled: true }, select: { id: true } },
    },
  });

  if (groups.length === 0) {
    console.log('No disabled groups with active monitors found.');
    return;
  }

  console.log(`Found ${groups.length} disabled groups with active monitors:`);
  for (const g of groups) {
    console.log(
      `  anchor=${g.anchorFqn ?? '(none)'}  total=${g._count.monitors}  active=${g.monitors.length}  id=${g.id}`,
    );
  }
  console.log('');

  if (apply) {
    const updated = await prisma.monitorGroup.updateMany({
      where: { id: { in: groups.map((g) => g.id) } },
      data: { enabled: true },
    });
    console.log(`Re-enabled ${updated.count} groups.`);
  } else {
    console.log(`Would re-enable ${groups.length} groups. Re-run with --apply.`);
  }
}

main()
  .catch((e) => {
    console.error('Repair failed:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
