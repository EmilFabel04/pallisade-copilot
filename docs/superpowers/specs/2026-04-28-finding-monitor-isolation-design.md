# Finding + Monitor Per-Pipeline-Profile Isolation

**Date:** 2026-04-28
**Status:** Draft (pending user approval)
**Related:** Sibling to PR `feat/lineage-tenant-isolation` which scoped `LineageNode/Edge/Snapshot` and `CopilotSession` per stack. This spec applies the same isolation to monitors and findings.

## Problem

The user-reported symptom: switching to a freshly-created pipeline profile **P2** still shows red status dots on the lineage graph for assets that have monitors configured on **P1**. The lineage data itself is now correctly isolated (per the previous PR), but the per-node monitor status overlay is org-wide.

Trace of the leak:

`app/api/pipeline/[stackId]/lineage/unified/route.ts:425`:

```typescript
const monitors = await prisma.monitor.findMany({
  where: { organizationId, enabled: true },
  // no pipelineStackId — every monitor in the org is fetched
});
```

The route then indexes monitors by `targetFqn` (lines 444-462) and overlays each lineage node with its matched monitor's `lastStatus`. Because the matcher works on FQN only, any monitor whose `targetFqn` matches a node in the current profile's lineage gets pinned to that node — even if the monitor was configured for a different profile. The red dot follows.

The `Finding` table has the same shape — `where: { organizationId, table: { in: allFqns } }` at line 402. Currently no active TS or Python code writes to `Finding` (the scan flow at `app/api/pipeline/scan/route.ts` writes `PipelineNodeFinding`, a different table). But the schema's lack of `pipelineStackId` means any future writer would inherit the same leak. We close that hole proactively rather than leaving a known-bad pattern.

The same isolation gap also applies to:

- **`MonitorGroup`** — owns multiple `Monitor` rows; a group spanning two profiles is incoherent under per-profile isolation.
- **`MonitorRun`**, **`MonitorBaseline`**, **`DriftRecommendation`** — children of `Monitor`; isolated naturally via FK cascade once `Monitor` is per-profile, but should be reachable from a stack delete.
- **`MonitoringPlan`** — owns `MonitorGroup` rows (per `MonitorGroup.monitoringPlanId`); same logic.

## Goals

1. **Per-profile monitors:** A monitor configured on P1 only appears in P1's lineage, schedule page, drift page, and copilot context. Switching to P2 hides it.
2. **Per-profile findings:** Same behavior for `Finding` rows. Defensive — no current writer, but the schema and read paths are wired correctly so the next writer can't accidentally leak.
3. **Cascading delete:** Deleting a `PipelineStack` removes all its monitors, monitor groups, monitor runs, baselines, drift recommendations, monitoring plans, and findings (matching the user's "ZERO data persistence on profile switch" model).
4. **Every TS read of `Monitor`, `MonitorGroup`, `Finding`** is scoped by `(organizationId, pipelineStackId)`. There is no read path that returns rows from another profile.
5. **Every TS write of `Monitor`, `MonitorGroup`, `Finding`** stamps `pipelineStackId` from the active context. Writes that don't have a stack context fail explicitly (400/precondition error) rather than silently writing org-wide.

## Non-goals

- **Sharing monitors across profiles** ("integration-wide" or "org-wide" monitors). The user explicitly chose strict per-profile isolation; sharing can be added later as an opt-in `scope` column on `Monitor` if real users ask for it.
- **Backfilling existing monitors and findings.** All existing rows are dropped during the migration. The user has confirmed they will re-create monitors as needed (dev/demo data only at this stage). The migration will not attempt to assign existing monitors to a "primary" profile.
- **Modifying `PipelineNodeFinding`** — that's a different table, scoped via `PipelineNode.stackId` (already per-stack), no change needed.
- **Modifying scanner Python code that writes monitor runs.** The Python flow only writes `MonitorRun`, which inherits `pipelineStackId` via the FK to `Monitor` (so no schema change is required there). If a Python flow ever writes `Monitor` directly, that's caught at the DB level by NOT NULL — it will fail at write time and be obvious.
- **Per-stack `Integration`.** Integrations remain org-shared (same as the lineage spec). When the same integration is attached to two profiles, each profile owns its own monitor/finding rows for that integration's assets.
- **Refactoring the schedule UI's data model.** This PR scopes the existing reads/writes; UI improvements are separate.

## Approach

### Schema changes

Add `pipelineStackId String` (NOT NULL) and a cascade FK to `PipelineStack` on three top-level models. The four child models (`MonitorRun`, `MonitorBaseline`, `DriftRecommendation`, `MonitoringPlan`) inherit isolation through their parent FKs and don't need their own `pipelineStackId` column — but `DriftRecommendation` is independently queryable by `organizationId` (it has its own `organizationId` field, line 1764) so it gets a `pipelineStackId` for query simplicity and cascade reach.

```prisma
model Monitor {
  ...existing fields...
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String

  @@unique([organizationId, pipelineStackId, targetFqn, monitorType])  // was: @@unique([organizationId, targetFqn, monitorType])
  @@index([organizationId, pipelineStackId])
  @@index([pipelineStackId])
}

model MonitorGroup {
  ...existing fields...
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
  @@index([pipelineStackId])
}

model Finding {
  ...existing fields...
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
  @@unique([organizationId, pipelineStackId, fingerprint])  // was: @@unique([organizationId, fingerprint])
  @@index([pipelineStackId])
}

model DriftRecommendation {
  ...existing fields...
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
  @@index([pipelineStackId])
}

model PipelineStack {
  ...existing fields...
  monitors             Monitor[]
  monitorGroups        MonitorGroup[]
  findings             Finding[]
  driftRecommendations DriftRecommendation[]
}
```

Rationale for `String` (NOT NULL) rather than `String?`:
- The same code-review finding from the lineage migration applies here — Postgres treats NULL as distinct in UNIQUE indexes. A nullable `pipelineStackId` would let two NULL-stack rows with the same `(organizationId, targetFqn, monitorType)` silently pass the unique constraint, recreating exactly the bug we're fixing.
- The migration handles this in the same shape as the lineage migration: `ADD COLUMN` nullable → `DELETE FROM` → `SET NOT NULL` → add unique/FK/indexes.

### Migration

Single Prisma schema-and-migration commit (project uses `prisma db push` workflow; see lineage migration handling in the previous PR for the exact pattern). The destructive purge is intentional and user-confirmed:

```sql
-- Add nullable
ALTER TABLE "Monitor"             ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "MonitorGroup"        ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "Finding"             ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "DriftRecommendation" ADD COLUMN "pipelineStackId" TEXT;

-- Purge: dev/demo data only. Children cascade-delete via existing FKs.
DELETE FROM "DriftRecommendation";
DELETE FROM "MonitorBaseline";
DELETE FROM "MonitorRun";
DELETE FROM "Monitor";
DELETE FROM "MonitorGroup";
DELETE FROM "Finding";
-- (MonitoringPlan rows stay; they're org-scoped configuration that can survive)

-- Set NOT NULL
ALTER TABLE "Monitor"             ALTER COLUMN "pipelineStackId" SET NOT NULL;
ALTER TABLE "MonitorGroup"        ALTER COLUMN "pipelineStackId" SET NOT NULL;
ALTER TABLE "Finding"             ALTER COLUMN "pipelineStackId" SET NOT NULL;
ALTER TABLE "DriftRecommendation" ALTER COLUMN "pipelineStackId" SET NOT NULL;

-- Replace unique constraints
DROP INDEX "Monitor_organizationId_targetFqn_monitorType_key";
CREATE UNIQUE INDEX "Monitor_organizationId_pipelineStackId_targetFqn_monitorType_key"
  ON "Monitor"("organizationId", "pipelineStackId", "targetFqn", "monitorType");

DROP INDEX "Finding_organizationId_fingerprint_key";
CREATE UNIQUE INDEX "Finding_organizationId_pipelineStackId_fingerprint_key"
  ON "Finding"("organizationId", "pipelineStackId", "fingerprint");

-- FKs and indexes
ALTER TABLE "Monitor"             ADD CONSTRAINT "Monitor_pipelineStackId_fkey"             FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;
ALTER TABLE "MonitorGroup"        ADD CONSTRAINT "MonitorGroup_pipelineStackId_fkey"        FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;
ALTER TABLE "Finding"             ADD CONSTRAINT "Finding_pipelineStackId_fkey"             FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;
ALTER TABLE "DriftRecommendation" ADD CONSTRAINT "DriftRecommendation_pipelineStackId_fkey" FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;

CREATE INDEX "Monitor_organizationId_pipelineStackId_idx" ON "Monitor"("organizationId", "pipelineStackId");
CREATE INDEX "Monitor_pipelineStackId_idx"                ON "Monitor"("pipelineStackId");
CREATE INDEX "MonitorGroup_pipelineStackId_idx"           ON "MonitorGroup"("pipelineStackId");
CREATE INDEX "Finding_pipelineStackId_idx"                ON "Finding"("pipelineStackId");
CREATE INDEX "DriftRecommendation_pipelineStackId_idx"    ON "DriftRecommendation"("pipelineStackId");
```

### Read paths to update

The implementation plan will enumerate every `prisma.monitor.*`, `prisma.monitorGroup.*`, `prisma.finding.*`, `prisma.driftRecommendation.*` call site. Provisional list (from grep):

| File | Reads | Required change |
|---|---|---|
| `app/api/pipeline/[stackId]/lineage/unified/route.ts:402` | `finding.findMany` | add `pipelineStackId: stackId` |
| `app/api/pipeline/[stackId]/lineage/unified/route.ts:425` | `monitor.findMany` | add `pipelineStackId: stackId`, drop org-wide overlay |
| `app/api/schedule/tasks/route.ts:43` | `monitor.findMany` | accept `stackId` query param, scope filter |
| `app/api/schedule/tasks/[taskId]/route.ts:20,60,116` | `monitor.findFirst` | scope by stackId (read from query / body) |
| `app/api/schedule/tasks/[taskId]/run/route.ts:104` | `monitor.findFirst` | scope by stackId |
| `app/api/schedule/tasks/[taskId]/runs/route.ts:20` | `monitor.findFirst` | scope by stackId |
| `app/api/schedule/watches/route.ts` | `monitorGroup.*` | scope by stackId |
| `app/api/schedule/watches/[watchId]/route.ts` | `monitorGroup.findFirst`, `monitor.findMany`, `monitor.create` | scope by stackId on read; stamp on create |
| `app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts:20,61` | `monitor.findFirst`, `monitor.update` | scope by stackId |
| `app/api/schedule/watches/[watchId]/run/route.ts` | `monitor.findMany` | scope by stackId |
| `app/api/schedule/watches/by-anchor/route.ts` | `monitorGroup.findMany` | scope by stackId |
| `app/api/schedule/plans/route.ts` | `monitor.*` | scope by stackId |
| `app/api/schedule/plans/[planId]/route.ts` | `monitor.*` | scope by stackId |
| `app/api/schedule/plans/[planId]/run/route.ts` | `monitor.findMany` | scope by stackId |
| `app/api/schedule/monitor-trends/route.ts:78` | `monitorGroup.findMany` | scope by stackId |
| `app/api/schedule/alert/route.ts` | `monitor.*` | scope by stackId (alert routing should respect profile) |
| `app/api/copilot/internal/get-monitor-run-history/route.ts:34` | `monitor.findFirst` | scope by stackId from caller context |
| `app/api/copilot/internal/list-configured-monitors/route.ts:64` | `monitor.findMany` | scope by stackId from caller context |
| `app/api/drift/run/route.ts:19` | `monitor.findMany` | scope by stackId |
| `app/api/drift/[id]/route.ts` | `driftRecommendation.findFirst` | scope by stackId |
| `app/api/integrations/route.ts:129` | `monitor.findMany` | scope by stackId — the integration list shows monitor counts; those counts should be per the active profile |

The schedule routes are the largest cluster. Each `[taskId]` and `[watchId]` parameter route references one Monitor or MonitorGroup row by id. For these, the existing `findFirst({ where: { id, organizationId } })` ownership pattern is **insufficient** under per-profile isolation: a user viewing P1 could otherwise read or mutate a P2-owned monitor that happens to be in the same org. The fix is to also include `pipelineStackId: stackId` in the `findFirst` (with `stackId` from the active profile context — passed in the query string for GETs and in the body for POST/PATCH/DELETE). On a mismatch, return 404.

This makes find-by-id reads/mutations a stronger ownership check than the current org-only scope: the row must belong to both the caller's org *and* the caller's currently-active profile to be touched. List queries (`findMany`) must scope by stackId to prevent cross-profile listing, as called out in the table above.

### Write paths to update

`Monitor` is created in:

- `app/api/schedule/watches/[watchId]/route.ts:256` (`monitor.create` inside a `watchId` context — derive stackId from the `MonitorGroup` parent).
- `app/api/schedule/tasks/route.ts` (POST creates a Monitor — needs stackId from request body or query).
- `app/api/schedule/plans/[planId]/run/route.ts` (creates monitors per a monitoring plan — derive stackId from the plan).
- Anywhere else the implementation plan turns up.

Every create site must set `pipelineStackId`. The compile-time NOT NULL guarantee will surface any missed site.

`MonitorGroup` is created in:

- `app/api/schedule/watches/route.ts` POST (the user-facing "create a Watch" flow). The frontend calls this with the active stack — the route must accept `stackId` (in body or as a query param) and stamp it on the create.

`Finding` is **not currently written** by any TS or Python code path I found. The migration sets up the schema correctly; if a future writer is added (e.g., a scheduled scan that produces user-visible findings), it will be required by NOT NULL to set `pipelineStackId`.

`DriftRecommendation` is created via `app/api/drift/run/route.ts` (the drift run flow). It must derive `pipelineStackId` from the active stack (passed in the request body or inferred from the monitor it relates to — the latter is cleaner since the monitor already carries it).

### Frontend client changes

The schedule page, drift page, integrations page, and copilot UI all call these routes. Each fetch site needs to include `pipelineStackId=${selectedPipelineId}` (from `usePipeline()` context) in the query string, and re-fetch on profile switch. The implementation plan will enumerate each fetch site and the page-level effect deps that need to include `selectedPipelineId`.

This is structurally the same fix we just shipped for the assistant page (`app/(dashboard)/dashboard/assistant/page.tsx`) — read the active profile from context, pass it on every fetch, re-fetch when it changes.

## Migration order with respect to the lineage PR

This work depends on `feat/lineage-tenant-isolation` being merged (it adds the `PipelineStack` inverse relations that this spec extends, and it ships the `db push` workflow). Branch this PR off `main` after the lineage PR lands.

## Testing

1. **Schema-level test** (`prisma/__tests__/monitor_finding_isolation.test.ts`):
   - Two profiles in the same org can each hold a Monitor with the same `(targetFqn, monitorType)` without violating the unique constraint.
   - `prisma.monitor.findMany({ where: { organizationId, pipelineStackId } })` returns only that profile's monitors.
   - Deleting a `PipelineStack` cascades to its monitors, monitor groups, findings, and drift recommendations (and through them to monitor runs and baselines).

2. **Route-level test for `/api/pipeline/[stackId]/lineage/unified`**:
   - Seed monitor with `lastStatus = 'FAIL'` on stack P1, FQN `db.schema.users`.
   - GET `/api/pipeline/p2/lineage/unified` → the `db.schema.users` node (if present in P2) has no `monitorStatus` overlay (or a passing one if P2 has its own monitor).

3. **Route-level test for `/api/schedule/tasks?stackId=p1`**:
   - Seed monitors on both P1 and P2 with the same target.
   - GET with `stackId=p1` returns only P1's monitor.

4. **End-to-end smoke**:
   - On P1, configure a monitor on `analytics.users`; trigger it to fail.
   - Switch to P2. The lineage page's `analytics.users` node has no red dot.
   - Configure a different monitor on P2 for the same FQN; trigger it. P2's node now shows P2's status, P1's node still shows P1's status.
   - Schedule page on P2 shows P2's monitor only.
   - Copilot on P2 reports only P2's monitors when asked "what monitors are configured?"

## Rollout

- Single migration, applied via `prisma db push` per project convention.
- All existing monitors and findings are dropped. Users (currently only this developer) re-create monitors per profile after deploy.
- No feature flag.

## Out of scope (acknowledged)

- Sharing monitors across profiles (later opt-in feature).
- Backfilling existing monitor configurations.
- Refactoring the Schedule page's data model.
- Modifying `PipelineNodeFinding` (already per-stack via PipelineNode).
- Scanner Python writes (only writes children of Monitor, inherits isolation).

## Open questions

None. The strict per-profile model is confirmed; the destructive migration is confirmed.
