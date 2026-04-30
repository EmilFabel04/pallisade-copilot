/**
 * One-time migration: deduplicate MonitorGroups by (organizationId,
 * pipelineStackId, anchorFqn).
 *
 * Background: prior to commit XXX, creating monitors for an asset that
 * already had a MonitorGroup produced a *new* MonitorGroup (the dedup
 * query was scoped by monitoringPlanId, which is always fresh on plan
 * creation). The existing P2002 handler then moved the monitors from
 * the old group into the new one, leaving the old group empty.
 *
 * This script:
 *   1. Finds (orgId, stackId, anchorFqn) triples with multiple groups.
 *   2. For each set, picks the OLDEST group as the winner.
 *   3. Reassigns any monitors still attached to losers → winner.
 *   4. Deletes the now-empty losers.
 *
 * Run dry-run first (default — no writes):
 *   npx tsx scripts/dedupe-monitor-groups.ts
 *
 * To actually mutate:
 *   npx tsx scripts/dedupe-monitor-groups.ts --apply
 *
 * Safe to run multiple times.
 */

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

interface DupeSet {
  organizationId: string;
  pipelineStackId: string;
  anchorFqn: string;
  groupIds: string[]; // ordered: [winner, ...losers]
}

async function findDuplicateSets(): Promise<DupeSet[]> {
  // Fetch every group with a non-null anchorFqn. Group in JS so we can
  // honor created-at ordering deterministically.
  const groups = await prisma.monitorGroup.findMany({
    where: { anchorFqn: { not: null } },
    orderBy: { createdAt: 'asc' },
    select: {
      id: true,
      organizationId: true,
      pipelineStackId: true,
      anchorFqn: true,
    },
  });

  const buckets = new Map<string, DupeSet>();
  for (const g of groups) {
    const key = `${g.organizationId}::${g.pipelineStackId}::${g.anchorFqn}`;
    const existing = buckets.get(key);
    if (existing) {
      existing.groupIds.push(g.id);
    } else {
      buckets.set(key, {
        organizationId: g.organizationId,
        pipelineStackId: g.pipelineStackId,
        anchorFqn: g.anchorFqn!,
        groupIds: [g.id],
      });
    }
  }

  return Array.from(buckets.values()).filter((s) => s.groupIds.length > 1);
}

async function main() {
  const apply = process.argv.includes('--apply');

  console.log(`Mode: ${apply ? 'APPLY (will mutate)' : 'DRY RUN (no writes)'}`);
  console.log('');

  const dupes = await findDuplicateSets();
  if (dupes.length === 0) {
    console.log('No duplicate MonitorGroups found. Nothing to do.');
    return;
  }

  console.log(`Found ${dupes.length} (org, stack, anchorFqn) triples with duplicates.`);
  console.log('');

  let totalMonitorsReassigned = 0;
  let totalGroupsDeleted = 0;

  for (const dupe of dupes) {
    const [winnerId, ...loserIds] = dupe.groupIds;
    console.log(`anchor=${dupe.anchorFqn}`);
    console.log(`  winner: ${winnerId}`);
    console.log(`  losers: ${loserIds.join(', ')}`);

    // Count and (optionally) reassign monitors still on the losers.
    const orphanMonitors = await prisma.monitor.count({
      where: { monitorGroupId: { in: loserIds } },
    });
    console.log(`  monitors still on losers: ${orphanMonitors}`);

    if (orphanMonitors > 0) {
      if (apply) {
        const moved = await prisma.monitor.updateMany({
          where: { monitorGroupId: { in: loserIds } },
          data: { monitorGroupId: winnerId },
        });
        console.log(`  → reassigned ${moved.count} monitors to winner`);
      } else {
        console.log(`  → would reassign ${orphanMonitors} monitors to winner`);
      }
      totalMonitorsReassigned += orphanMonitors;
    }

    // Delete losers (they're empty now, or we just emptied them).
    if (apply) {
      const deleted = await prisma.monitorGroup.deleteMany({
        where: { id: { in: loserIds } },
      });
      console.log(`  → deleted ${deleted.count} empty groups`);
      totalGroupsDeleted += deleted.count;
    } else {
      console.log(`  → would delete ${loserIds.length} empty groups`);
      totalGroupsDeleted += loserIds.length;
    }
    console.log('');
  }

  console.log('Summary:');
  console.log(`  duplicate triples: ${dupes.length}`);
  console.log(`  monitors ${apply ? 'reassigned' : 'to reassign'}: ${totalMonitorsReassigned}`);
  console.log(`  groups ${apply ? 'deleted' : 'to delete'}: ${totalGroupsDeleted}`);
  if (!apply) {
    console.log('');
    console.log('Re-run with --apply to perform the cleanup.');
  }
}

main()
  .catch((e) => {
    console.error('Cleanup failed:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
