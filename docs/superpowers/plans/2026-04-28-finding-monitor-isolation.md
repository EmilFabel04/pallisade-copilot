# Finding + Monitor Per-Pipeline-Profile Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope `Monitor`, `MonitorGroup`, `MonitoringPlan`, `Finding`, and `DriftRecommendation` per-pipeline-profile (not just per-org), so a monitor configured on profile P1 never appears in profile P2's lineage overlay, schedule page, drift page, or copilot context.

**Architecture:** Add `pipelineStackId String` (NOT NULL, cascade FK to `PipelineStack`) to all five top-level models. Tighten unique constraints to include `pipelineStackId`. Update every read to filter by `(organizationId, pipelineStackId)` and every write to stamp `pipelineStackId` from the active context. Frontend reads `selectedPipelineId` from `usePipeline()` and passes it on every fetch. Existing rows are dropped during the migration (per user direction).

**Tech Stack:** Next.js 15 (TypeScript) routes, Prisma 5, Postgres, Jest for schema + route tests, `prisma db push` workflow (no migration files).

**Spec:** `docs/superpowers/specs/2026-04-28-finding-monitor-isolation-design.md`

**Decisions baked into this plan (from spec self-review):**
- `MonitoringPlan` also gets `pipelineStackId` (consistency with the "ZERO data persistence on profile switch" rule). The spec left this implicit; this plan makes it explicit.
- `MonitorRun` and `MonitorBaseline` keep no own column; isolation inherits via the `Monitor` FK. Task 13 audits any direct reads to make sure none leak.
- No helper function — every call site sets `pipelineStackId` explicitly, so it's grep-able and a missed site is visible in code review.
- Branches off `main` (assumes `feat/lineage-tenant-isolation` has merged; Task 0 verifies this).

---

## File Structure

**Schema (1 file):**
- Modify: `prisma/schema.prisma` — add column + relation to 5 models, add inverse arrays to `PipelineStack`, tighten 2 unique constraints, add 5 indexes.

**Tests (2 files):**
- Create: `prisma/__tests__/monitor_finding_isolation.test.ts` — schema-level cascade + uniqueness + filter test (mirrors `prisma/__tests__/lineage_isolation.test.ts`).
- Create: `app/api/pipeline/[stackId]/lineage/__tests__/unified_isolation.test.ts` — route-level test verifying the original bug (red-dot leak) is closed.
- Create: `app/api/schedule/tasks/__tests__/route.test.ts` — route-level test that `/api/schedule/tasks?stackId=p1` returns only P1 monitors.

**Backend routes (~22 files):**
- Modify: `app/api/pipeline/[stackId]/lineage/unified/route.ts` (THE BUG — line 410, 433).
- Modify: schedule cluster — `app/api/schedule/tasks/route.ts`, `app/api/schedule/tasks/[taskId]/route.ts`, `app/api/schedule/tasks/[taskId]/run/route.ts`, `app/api/schedule/tasks/[taskId]/runs/route.ts`, `app/api/schedule/watches/route.ts`, `app/api/schedule/watches/[watchId]/route.ts`, `app/api/schedule/watches/[watchId]/run/route.ts`, `app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts`, `app/api/schedule/watches/by-anchor/route.ts`, `app/api/schedule/monitor-trends/route.ts`, `app/api/schedule/plans/route.ts`, `app/api/schedule/plans/[planId]/route.ts`, `app/api/schedule/plans/[planId]/run/route.ts`, `app/api/schedule/alert/route.ts`.
- Modify: drift cluster — `app/api/drift/route.ts`, `app/api/drift/run/route.ts`, `app/api/drift/[id]/route.ts`.
- Modify: copilot internal — `app/api/copilot/internal/list-configured-monitors/route.ts`, `app/api/copilot/internal/get-monitor-run-history/route.ts`.
- Modify: `app/api/integrations/route.ts` (monitor-count overlay must be per-profile).

**Frontend (3 files):**
- Modify: `app/(dashboard)/dashboard/monitors/page.tsx` — already passes `stackId` to plans + watches; add it to `tasks` fetch and ensure deps include `selectedPipelineId`.
- Modify: `app/(dashboard)/dashboard/pipeline/page.tsx` — pass `stackId` to integrations fetch.
- Verify: `app/(dashboard)/dashboard/lineage/page.tsx` re-fetches on profile switch (likely already does via `[stackId]` URL).

---

## Task 0: Pre-flight verification

**Files:** None modified.

- [ ] **Step 1: Verify lineage isolation has merged on `main`**

```bash
git checkout main && git pull --ff-only
grep -n "pipelineStackId" prisma/schema.prisma | grep -i "lineageNode\|lineageEdge\|lineageSnapshot" || true
grep -nE "model (LineageNode|LineageEdge|LineageSnapshot)" prisma/schema.prisma
# Expected: each lineage model includes "pipelineStackId String" (NOT NULL) and a cascade FK
```

If the schema still has `LineageNode` without `pipelineStackId`, **STOP**. The lineage isolation PR has not merged yet; this work depends on it. Report back to the user before proceeding.

- [ ] **Step 2: Stash any local uncommitted changes (do not discard)**

```bash
git status --short
git stash push -u -m "wip-before-monitor-isolation" || true
```

- [ ] **Step 3: Create the feature branch**

```bash
git checkout -b feat/finding-monitor-isolation main
```

- [ ] **Step 4: Confirm test DB is reachable**

```bash
echo "$DATABASE_URL" | grep -q test && echo "TEST DB OK" || echo "WARN: DATABASE_URL is not pointed at a test DB; schema test will skip"
```

If `DATABASE_URL` is not the test DB, set it before running schema tests later. The Jest test self-skips if not on a test DB (mirroring the lineage isolation test).

- [ ] **Step 5: Smoke-run existing test suite to baseline green**

```bash
npx jest prisma/__tests__/ --runInBand
```

Expected: PASS (or skip on schema tests if no test DB).

---

## Task 1: Schema additions — nullable column + relations on 5 models

**Files:**
- Modify: `prisma/schema.prisma` — `Monitor` (line 1932), `MonitorGroup` (line 2109), `MonitoringPlan` (line 2165), `Finding` (line 1816), `DriftRecommendation` (line 2219), `PipelineStack` (line 303).

Strategy: introduce `pipelineStackId` as **nullable** first, plus the FK relation and `PipelineStack` inverse arrays. We can't push NOT NULL onto a non-empty table; nullable now → purge in Task 2 → flip to NOT NULL in Task 3.

- [ ] **Step 1: Add `pipelineStackId String?` + relation + index to `Monitor`**

Locate the `Monitor` model (line 1932). Insert after `monitorGroupId  String?` (line 1987) and before `runs MonitorRun[]`:

```prisma
  pipelineStack        PipelineStack?        @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId      String?
```

(Both the column and the relation are optional in this nullable phase — Prisma requires they match. Task 3 flips both to non-optional after the data purge.)

Add to the indexes block at the bottom of the model:

```prisma
  @@index([pipelineStackId])
  @@index([organizationId, pipelineStackId])
```

(Do **not** modify the existing `@@unique([organizationId, targetFqn, monitorType])` yet — that happens in Task 3 after data is purged. The current unique would otherwise still trip on duplicate FQNs across stacks.)

- [ ] **Step 2: Add `pipelineStackId String?` + relation + index to `MonitorGroup`**

In the `MonitorGroup` model (line 2109), insert before `monitors  Monitor[]`:

```prisma
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
```

Add to the indexes block:

```prisma
  @@index([pipelineStackId])
```

- [ ] **Step 3: Add `pipelineStackId String?` + relation + index to `MonitoringPlan`**

In the `MonitoringPlan` model (line 2165), insert before `monitorGroups  MonitorGroup[]`:

```prisma
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
```

Add to the indexes block:

```prisma
  @@index([pipelineStackId])
```

- [ ] **Step 4: Add `pipelineStackId String?` + relation + index to `Finding`**

In the `Finding` model (line 1816), insert before `report  Report?`:

```prisma
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
```

Add to the indexes block:

```prisma
  @@index([pipelineStackId])
```

- [ ] **Step 5: Add `pipelineStackId String?` + relation + index to `DriftRecommendation`**

In the `DriftRecommendation` model (line 2219), insert after the `monitor` relation (line 2246):

```prisma
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
```

Add to the indexes block:

```prisma
  @@index([pipelineStackId])
```

- [ ] **Step 6: Add inverse relations to `PipelineStack`**

In the `PipelineStack` model (line 303), inside the relations section (currently around line 337-357), add:

```prisma
  // Monitors + findings (per-profile isolation)
  monitors             Monitor[]
  monitorGroups        MonitorGroup[]
  monitoringPlans      MonitoringPlan[]
  findings             Finding[]
  driftRecommendations DriftRecommendation[]
```

- [ ] **Step 7: Validate schema compiles**

```bash
npx prisma format
npx prisma validate
```

Expected: Both succeed without errors.

- [ ] **Step 8: Push the schema (nullable column applied to DB)**

```bash
npx prisma db push --skip-generate
```

Expected: "The database is now in sync with the Prisma schema." Five new columns added; FKs added; new indexes created.

- [ ] **Step 9: Regenerate the client**

```bash
npx prisma generate
```

- [ ] **Step 10: Commit**

```bash
git add prisma/schema.prisma
git commit -m "feat(monitors): add nullable pipelineStackId to Monitor/Group/Plan/Finding/DriftRec"
```

---

## Task 2: Purge existing monitor + finding data

**Files:** None modified (operational step).

The user has confirmed all existing rows are disposable. We purge before flipping `pipelineStackId` to NOT NULL.

- [ ] **Step 1: Run the purge**

```bash
npx prisma db execute --stdin <<'SQL'
DELETE FROM "DriftRecommendation";
DELETE FROM "MonitorBaseline";
DELETE FROM "MonitorRun";
DELETE FROM "Monitor";
DELETE FROM "MonitorGroup";
DELETE FROM "MonitoringPlan";
DELETE FROM "Finding";
SQL
```

Order matters: `DriftRecommendation`, `MonitorBaseline`, and `MonitorRun` are children of `Monitor` (cascade in schema, but explicit ordering avoids any ambiguity). `MonitoringPlan` is purged because `MonitorGroup.monitoringPlanId` was `SetNull` on parent delete — keeping plans that no longer have groups is also acceptable, but purging keeps things clean.

- [ ] **Step 2: Verify counts are zero**

```bash
npx prisma db execute --stdin <<'SQL'
SELECT 'Monitor' AS t, COUNT(*) FROM "Monitor"
UNION ALL SELECT 'MonitorRun', COUNT(*) FROM "MonitorRun"
UNION ALL SELECT 'MonitorBaseline', COUNT(*) FROM "MonitorBaseline"
UNION ALL SELECT 'MonitorGroup', COUNT(*) FROM "MonitorGroup"
UNION ALL SELECT 'MonitoringPlan', COUNT(*) FROM "MonitoringPlan"
UNION ALL SELECT 'Finding', COUNT(*) FROM "Finding"
UNION ALL SELECT 'DriftRecommendation', COUNT(*) FROM "DriftRecommendation";
SQL
```

Expected: All counts = 0.

(No commit — operational step. Move on to Task 3.)

---

## Task 3: Make `pipelineStackId` NOT NULL + tighten unique constraints

**Files:**
- Modify: `prisma/schema.prisma` — change `String?` → `String` on five models, swap two `@@unique` constraints, drop the now-redundant `@@index([organizationId])` where the compound covers it (Monitor only).

- [ ] **Step 1: Flip `pipelineStackId` to NOT NULL on all five models**

For `Monitor`:

```prisma
  pipelineStack        PipelineStack         @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId      String
```

For `MonitorGroup`:

```prisma
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
```

For `MonitoringPlan`:

```prisma
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
```

For `Finding`:

```prisma
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
```

For `DriftRecommendation`:

```prisma
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String
```

(All five lose the `?` and the relation field loses `?` to match.)

- [ ] **Step 2: Replace `Monitor` unique constraint to include `pipelineStackId`**

In `Monitor`, change:

```prisma
  @@unique([organizationId, targetFqn, monitorType])
```

to:

```prisma
  @@unique([organizationId, pipelineStackId, targetFqn, monitorType])
```

- [ ] **Step 3: Replace `Finding` unique constraint to include `pipelineStackId`**

In `Finding`, change:

```prisma
  @@unique([organizationId, fingerprint])
```

to:

```prisma
  @@unique([organizationId, pipelineStackId, fingerprint])
```

- [ ] **Step 4: Validate + push**

```bash
npx prisma format && npx prisma validate && npx prisma db push --skip-generate
```

Expected: succeeds (tables are empty so NOT NULL is fine; unique constraint swap is fine on empty tables).

- [ ] **Step 5: Regenerate client**

```bash
npx prisma generate
```

- [ ] **Step 6: Commit**

```bash
git add prisma/schema.prisma
git commit -m "feat(monitors): make pipelineStackId NOT NULL and tighten unique constraints"
```

---

## Task 4: Schema-level isolation test

**Files:**
- Create: `prisma/__tests__/monitor_finding_isolation.test.ts`

Mirrors the structure of `prisma/__tests__/lineage_isolation.test.ts`. Self-skips if `DATABASE_URL` doesn't include `test`.

- [ ] **Step 1: Create the test file**

```typescript
/**
 * Schema-level isolation test for the Monitor + Finding migration.
 *
 * Runs against a live Prisma test DB. To execute locally:
 *   DATABASE_URL=<test-db-url> npx jest prisma/__tests__/monitor_finding_isolation.test.ts
 *
 * If DATABASE_URL is not pointed at a test DB, the test skips itself.
 */
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

describeIfTestDb('Monitor + Finding isolation (schema-level)', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `mon-iso-test-${Date.now()}` },
    });
    orgId = org.id;
    const stackA = await prisma.pipelineStack.create({
      data: { name: 'Stack A', organizationId: orgId },
    });
    const stackB = await prisma.pipelineStack.create({
      data: { name: 'Stack B', organizationId: orgId },
    });
    stackAId = stackA.id;
    stackBId = stackB.id;
  });

  afterAll(async () => {
    await prisma.pipelineStack.deleteMany({ where: { organizationId: orgId } });
    await prisma.organization.delete({ where: { id: orgId } });
    await prisma.$disconnect();
  });

  it('allows two profiles in the same org to hold a Monitor with the same (targetFqn, monitorType)', async () => {
    const a = await prisma.monitor.create({
      data: {
        name: 'm-a', monitorType: 'FRESHNESS', targetFqn: 'db.schema.users',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    const b = await prisma.monitor.create({
      data: {
        name: 'm-b', monitorType: 'FRESHNESS', targetFqn: 'db.schema.users',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
    expect(a.id).not.toBe(b.id);
  });

  it('Monitor.findMany filtered by pipelineStackId returns only that profile', async () => {
    const aRows = await prisma.monitor.findMany({
      where: { organizationId: orgId, pipelineStackId: stackAId },
    });
    const bRows = await prisma.monitor.findMany({
      where: { organizationId: orgId, pipelineStackId: stackBId },
    });
    expect(aRows.every((r) => r.pipelineStackId === stackAId)).toBe(true);
    expect(bRows.every((r) => r.pipelineStackId === stackBId)).toBe(true);
    expect(aRows.length).toBeGreaterThan(0);
    expect(bRows.length).toBeGreaterThan(0);
  });

  it('Finding unique constraint includes pipelineStackId', async () => {
    const fp = `fp-${Date.now()}`;
    await prisma.finding.create({
      data: {
        fingerprint: fp, table: 'db.schema.users', scanType: 'quality',
        findingType: 'null_rate', severity: 'LOW', title: 't', description: 'd',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    // Same fingerprint in stack B should NOT collide
    const b = await prisma.finding.create({
      data: {
        fingerprint: fp, table: 'db.schema.users', scanType: 'quality',
        findingType: 'null_rate', severity: 'LOW', title: 't', description: 'd',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
    expect(b.pipelineStackId).toBe(stackBId);
  });

  it('cascades delete from PipelineStack to Monitor + children', async () => {
    const tempStack = await prisma.pipelineStack.create({
      data: { name: 'Temp', organizationId: orgId },
    });
    const monitor = await prisma.monitor.create({
      data: {
        name: 'cascade-check', monitorType: 'FRESHNESS', targetFqn: 'cascade.users',
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    await prisma.monitorRun.create({
      data: { status: 'PASS', monitorId: monitor.id },
    });
    await prisma.pipelineStack.delete({ where: { id: tempStack.id } });
    const orphanMonitors = await prisma.monitor.findMany({
      where: { pipelineStackId: tempStack.id },
    });
    const orphanRuns = await prisma.monitorRun.findMany({
      where: { monitorId: monitor.id },
    });
    expect(orphanMonitors).toHaveLength(0);
    expect(orphanRuns).toHaveLength(0);
  });

  it('cascades delete from PipelineStack to MonitorGroup, MonitoringPlan, Finding, DriftRecommendation', async () => {
    const tempStack = await prisma.pipelineStack.create({
      data: { name: 'Temp2', organizationId: orgId },
    });
    const plan = await prisma.monitoringPlan.create({
      data: {
        name: 'p', scopeType: 'pipeline', mode: 'manual', families: [],
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    const group = await prisma.monitorGroup.create({
      data: {
        name: 'g', groupType: 'custom',
        organizationId: orgId, pipelineStackId: tempStack.id, monitoringPlanId: plan.id,
      },
    });
    const monitor = await prisma.monitor.create({
      data: {
        name: 'm', monitorType: 'FRESHNESS', targetFqn: 'cascade2.users',
        organizationId: orgId, pipelineStackId: tempStack.id, monitorGroupId: group.id,
      },
    });
    await prisma.finding.create({
      data: {
        fingerprint: `cascade-fp-${Date.now()}`, table: 'cascade2.users', scanType: 'quality',
        findingType: 'null_rate', severity: 'LOW', title: 't', description: 'd',
        organizationId: orgId, pipelineStackId: tempStack.id,
      },
    });
    await prisma.driftRecommendation.create({
      data: {
        organizationId: orgId, pipelineStackId: tempStack.id,
        monitorId: monitor.id, monitorName: 'm', monitorType: 'FRESHNESS',
        targetFqn: 'cascade2.users', driftCategory: 'threshold', severity: 'low',
        currentField: 'x', currentValue: '1', recommendedValue: '2',
        reasoning: 'r', confidence: 0.9, evidence: {}, runId: 'run-x',
      },
    });
    await prisma.pipelineStack.delete({ where: { id: tempStack.id } });
    expect(await prisma.monitor.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.monitorGroup.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.monitoringPlan.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.finding.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
    expect(await prisma.driftRecommendation.count({ where: { pipelineStackId: tempStack.id } })).toBe(0);
  });
});
```

- [ ] **Step 2: Run the test, verify it passes**

```bash
DATABASE_URL=<test-db-url> npx jest prisma/__tests__/monitor_finding_isolation.test.ts --runInBand
```

Expected: all 5 `it()` blocks PASS.

- [ ] **Step 3: Commit**

```bash
git add prisma/__tests__/monitor_finding_isolation.test.ts
git commit -m "test(monitors): schema-level isolation tests"
```

---

## Task 5: Fix the lineage/unified bug (THE actual user-reported red-dot leak)

**Files:**
- Modify: `app/api/pipeline/[stackId]/lineage/unified/route.ts` (lines 410, 433).
- Create: `app/api/pipeline/[stackId]/lineage/__tests__/unified_isolation.test.ts`.

The route already has `stackId` from `params`. Just plumb it into the two leaky `findMany` calls.

- [ ] **Step 1: Write the failing route-level test first**

Create `app/api/pipeline/[stackId]/lineage/__tests__/unified_isolation.test.ts`:

```typescript
/**
 * Route-level test for /api/pipeline/[stackId]/lineage/unified.
 *
 * Verifies that monitor.lastStatus and findings overlays are scoped
 * by pipelineStackId, not just by organizationId. Closes the original
 * red-dot-on-wrong-profile bug.
 */
import { PrismaClient } from '@prisma/client';
import { GET } from '../unified/route';
import { NextRequest } from 'next/server';

const prisma = new PrismaClient();
const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

// Stub the auth() module so the route sees a session.
jest.mock('@/auth', () => ({
  auth: jest.fn().mockResolvedValue({
    user: { id: 'test-user', organizationId: '__SET_AT_RUNTIME__' },
  }),
}));

describeIfTestDb('GET /api/pipeline/[stackId]/lineage/unified — monitor isolation', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `route-iso-test-${Date.now()}` },
    });
    orgId = org.id;
    // Patch the auth mock with the runtime org id
    const { auth } = require('@/auth');
    (auth as jest.Mock).mockResolvedValue({
      user: { id: 'test-user', organizationId: orgId },
    });

    const stackA = await prisma.pipelineStack.create({
      data: { name: 'A', organizationId: orgId },
    });
    const stackB = await prisma.pipelineStack.create({
      data: { name: 'B', organizationId: orgId },
    });
    stackAId = stackA.id;
    stackBId = stackB.id;

    // Failing monitor in stack A on db.schema.users
    await prisma.monitor.create({
      data: {
        name: 'm-a', monitorType: 'FRESHNESS', targetFqn: 'db.schema.users',
        enabled: true, lastStatus: 'FAIL',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    // No monitor in stack B
  });

  afterAll(async () => {
    await prisma.pipelineStack.deleteMany({ where: { organizationId: orgId } });
    await prisma.organization.delete({ where: { id: orgId } });
    await prisma.$disconnect();
  });

  it('does not bleed P1 monitor status onto P2 lineage', async () => {
    const req = new NextRequest('http://localhost/api/pipeline/' + stackBId + '/lineage/unified');
    const res = await GET(req, { params: Promise.resolve({ stackId: stackBId }) });
    const body = await res.json();
    // None of the returned nodes for stack B should carry the failing monitor from stack A.
    const allMonitorIds = (body.nodes || []).flatMap((n: any) => (n.monitors || []).map((m: any) => m.id));
    const monitorRows = await prisma.monitor.findMany({
      where: { id: { in: allMonitorIds } },
      select: { id: true, pipelineStackId: true },
    });
    expect(monitorRows.every((m) => m.pipelineStackId === stackBId)).toBe(true);
  });
});
```

- [ ] **Step 2: Run the test — should fail because route doesn't yet filter**

```bash
DATABASE_URL=<test-db-url> npx jest app/api/pipeline/\[stackId\]/lineage/__tests__/unified_isolation.test.ts --runInBand
```

Expected: FAIL — assertion fires because the route returns the stack-A monitor on a stack-B request.

- [ ] **Step 3: Fix `finding.findMany` (line 410)**

In `app/api/pipeline/[stackId]/lineage/unified/route.ts`, change:

```typescript
const findings = await prisma.finding.findMany({
  where: {
    organizationId,
    table: { in: allFqns },
    status: { in: ['OPEN', 'IN_PROGRESS'] },
  },
  ...
```

to:

```typescript
const findings = await prisma.finding.findMany({
  where: {
    organizationId,
    pipelineStackId: stackId,
    table: { in: allFqns },
    status: { in: ['OPEN', 'IN_PROGRESS'] },
  },
  ...
```

- [ ] **Step 4: Fix `monitor.findMany` (line 433)**

Change:

```typescript
const monitors = await prisma.monitor.findMany({
  where: { organizationId, enabled: true },
  ...
```

to:

```typescript
const monitors = await prisma.monitor.findMany({
  where: { organizationId, pipelineStackId: stackId, enabled: true },
  ...
```

- [ ] **Step 5: Re-run the test — should pass**

```bash
DATABASE_URL=<test-db-url> npx jest app/api/pipeline/\[stackId\]/lineage/__tests__/unified_isolation.test.ts --runInBand
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/pipeline/\[stackId\]/lineage/unified/route.ts app/api/pipeline/\[stackId\]/lineage/__tests__/unified_isolation.test.ts
git commit -m "fix(lineage): scope finding+monitor overlays by pipelineStackId on unified view

Closes the user-reported red-dot leak: monitors configured on profile P1
were showing as failing on profile P2's lineage view because the unified
view was filtering monitor and finding overlays by organizationId only."
```

---

## Task 6: Schedule — `tasks` route + sub-routes

**Files:**
- Modify: `app/api/schedule/tasks/route.ts` (line 43).
- Modify: `app/api/schedule/tasks/[taskId]/route.ts` (lines 20, 60, 90, 116, 124).
- Modify: `app/api/schedule/tasks/[taskId]/run/route.ts` (lines 41, 104, 459, 493, 505, 520).
- Modify: `app/api/schedule/tasks/[taskId]/runs/route.ts` (line 20).
- Create: `app/api/schedule/tasks/__tests__/route.test.ts` (route-level isolation sample test).

Pattern: each route accepts `stackId` via query (GET) or body (POST/PATCH/DELETE), validates it's present, and adds `pipelineStackId: stackId` to every `where` and `data` object. On id-based reads, the `findFirst` includes `pipelineStackId` so a P1 user can't reach a P2 monitor by id.

- [ ] **Step 1: Update `tasks/route.ts` GET (list) — accept and apply `stackId`**

In `app/api/schedule/tasks/route.ts`, after the `organizationId` extraction (line 14), insert:

```typescript
const stackId = searchParams.get('stackId');
if (!stackId) {
  return NextResponse.json(
    { error: 'stackId query parameter is required' },
    { status: 400 }
  );
}
```

(Note: `searchParams` is currently extracted on line 17 — move that line before the `stackId` check, or inline the `new URL(...)` call.)

Then change line 21:

```typescript
const where: any = { organizationId };
```

to:

```typescript
const where: any = { organizationId, pipelineStackId: stackId };
```

- [ ] **Step 2: Update `tasks/route.ts` POST (create) — stamp `pipelineStackId`**

If `tasks/route.ts` has a POST handler that creates a `Monitor`, find the `prisma.monitor.create` call. Read `stackId` from the JSON body:

```typescript
const body = await request.json();
const { stackId, ...rest } = body;
if (!stackId) {
  return NextResponse.json({ error: 'stackId is required' }, { status: 400 });
}
```

Then in the `data` object passed to `prisma.monitor.create`, add `pipelineStackId: stackId`.

(If POST is not in this file, skip — Task 7's watch-create handles the create flow.)

- [ ] **Step 3: Update `tasks/[taskId]/route.ts` — scope all 5 monitor calls**

For each of `findFirst` (lines 20, 60, 116), `update` (line 90), and `delete` (line 124), the existing `where: { id: taskId, organizationId }` becomes `where: { id: taskId, organizationId, pipelineStackId: stackId }`.

`stackId` is read from the query string for GET and from the body for PATCH/DELETE:

For GET:
```typescript
const stackId = new URL(request.url).searchParams.get('stackId');
if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });
```

For PATCH/DELETE:
```typescript
const body = await request.json().catch(() => ({}));
const stackId = body.stackId || new URL(request.url).searchParams.get('stackId');
if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });
```

(Body-or-query for PATCH/DELETE because some clients send via query string for clarity.)

A failed `findFirst` (returns `null`) should already be handled with a 404 by the existing code; the new stack mismatch produces the same 404 — that's correct behavior (a P1 user trying to reach a P2 monitor should not be told it exists).

- [ ] **Step 4: Update `tasks/[taskId]/run/route.ts` — scope monitor + monitorGroup**

Same pattern: read `stackId` from body, apply to:
- Line 41 (`monitor.update`)
- Line 104 (`monitor.findFirst`)
- Line 493 (`monitor.update`)

For `monitorGroup` calls on lines 505 + 520 — these currently have NO `organizationId` filter (`findUnique` by id alone — see explore output). Change `findUnique` → `findFirst` and scope by `(organizationId, pipelineStackId)`:

```typescript
// Was:
const group = await prisma.monitorGroup.findUnique({ where: { id: ... } });
// Becomes:
const group = await prisma.monitorGroup.findFirst({
  where: { id: groupId, organizationId, pipelineStackId: stackId },
});
```

For the `monitorRun.create` calls on lines 29 and 459 — `MonitorRun` has no `pipelineStackId` of its own; isolation is via the `Monitor` FK. No code change needed there beyond ensuring the parent monitor was loaded with proper scoping (which Step 4's `findFirst` updates handle).

- [ ] **Step 5: Update `tasks/[taskId]/runs/route.ts` — line 20**

Same pattern on `monitor.findFirst` (line 20). The `monitorRun.findMany` and `count` calls below (lines 34, 40) inherit isolation through the parent `monitorId` filter — no change needed.

- [ ] **Step 6: Write a route-level test for `/api/schedule/tasks?stackId=...`**

Create `app/api/schedule/tasks/__tests__/route.test.ts`:

```typescript
import { PrismaClient } from '@prisma/client';
import { GET } from '../route';
import { NextRequest } from 'next/server';

const prisma = new PrismaClient();
const isTestDb = !!process.env.DATABASE_URL?.includes('test');
const describeIfTestDb = isTestDb ? describe : describe.skip;

jest.mock('@/auth', () => ({
  auth: jest.fn(),
}));

describeIfTestDb('GET /api/schedule/tasks — stack isolation', () => {
  let orgId: string;
  let stackAId: string;
  let stackBId: string;

  beforeAll(async () => {
    const org = await prisma.organization.create({
      data: { name: `tasks-iso-${Date.now()}` },
    });
    orgId = org.id;
    const { auth } = require('@/auth');
    (auth as jest.Mock).mockResolvedValue({
      user: { id: 'u', organizationId: orgId },
    });
    const a = await prisma.pipelineStack.create({
      data: { name: 'A', organizationId: orgId },
    });
    const b = await prisma.pipelineStack.create({
      data: { name: 'B', organizationId: orgId },
    });
    stackAId = a.id;
    stackBId = b.id;
    await prisma.monitor.create({
      data: {
        name: 'in-a', monitorType: 'FRESHNESS', targetFqn: 'db.s.t1',
        organizationId: orgId, pipelineStackId: stackAId,
      },
    });
    await prisma.monitor.create({
      data: {
        name: 'in-b', monitorType: 'FRESHNESS', targetFqn: 'db.s.t2',
        organizationId: orgId, pipelineStackId: stackBId,
      },
    });
  });

  afterAll(async () => {
    await prisma.pipelineStack.deleteMany({ where: { organizationId: orgId } });
    await prisma.organization.delete({ where: { id: orgId } });
    await prisma.$disconnect();
  });

  it('returns only the requested stack monitors', async () => {
    const req = new NextRequest(`http://localhost/api/schedule/tasks?stackId=${stackAId}`);
    const res = await GET(req);
    const body = await res.json();
    expect(body.tasks).toHaveLength(1);
    expect(body.tasks[0].name).toBe('in-a');
  });

  it('400s when stackId is missing', async () => {
    const req = new NextRequest('http://localhost/api/schedule/tasks');
    const res = await GET(req);
    expect(res.status).toBe(400);
  });
});
```

- [ ] **Step 7: Run the route test**

```bash
DATABASE_URL=<test-db-url> npx jest app/api/schedule/tasks/__tests__/route.test.ts --runInBand
```

Expected: PASS (2 cases).

- [ ] **Step 8: Commit**

```bash
git add app/api/schedule/tasks/
git commit -m "feat(schedule): scope tasks routes by pipelineStackId"
```

---

## Task 7: Schedule — `watches` routes (groups + member monitors)

**Files:**
- Modify: `app/api/schedule/watches/route.ts` (line 18).
- Modify: `app/api/schedule/watches/[watchId]/route.ts` (lines 21, 158, 311) — also handles `monitor.create` in the watch flow.
- Modify: `app/api/schedule/watches/[watchId]/run/route.ts` (lines 159, 257).
- Modify: `app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts` (lines 20, 61, 68).
- Modify: `app/api/schedule/watches/by-anchor/route.ts` (line 25).

- [ ] **Step 1: `watches/route.ts` GET (list)**

In the existing where clause on line 18:

```typescript
where: { organizationId, watchType: { not: null }, monitoringPlanId: null }
```

becomes (after parsing `stackId` from `searchParams`):

```typescript
const stackId = new URL(request.url).searchParams.get('stackId');
if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });
// ...
where: { organizationId, pipelineStackId: stackId, watchType: { not: null }, monitoringPlanId: null }
```

- [ ] **Step 2: `watches/route.ts` POST (create) — stamp `pipelineStackId` on `MonitorGroup.create`**

Read `stackId` from JSON body. In the `prisma.monitorGroup.create` call's `data`, add `pipelineStackId: stackId`.

If the POST handler also creates child `Monitor` rows (typical for the "create a Watch" flow), each one must also include `pipelineStackId: stackId` in its `data`.

- [ ] **Step 3: `watches/[watchId]/route.ts` — scope all calls**

For each `monitorGroup.findFirst` on lines 21, 158, 311: add `pipelineStackId: stackId` (read `stackId` from body for PATCH/DELETE, query for GET).

If the route creates child monitors (e.g., adding a member to a watch), stamp `pipelineStackId` on each `monitor.create`.

- [ ] **Step 4: `watches/[watchId]/run/route.ts` — scope group calls**

Lines 159 (`findFirst`) + 257 (`update`): apply same scoping.

- [ ] **Step 5: `watches/[watchId]/monitors/[monitorId]/route.ts` — scope monitor calls**

Lines 20 (`findFirst`), 61 (`update`), 68 (`update`): apply scoping.

- [ ] **Step 6: `watches/by-anchor/route.ts` — scope group findMany**

Line 25: add `pipelineStackId: stackId`.

- [ ] **Step 7: Verify all schedule/watches tests still pass (if any exist)**

```bash
npx jest app/api/schedule/watches --runInBand
```

Expected: PASS or "no tests found" (acceptable; the schema test in Task 4 + tasks test in Task 6 cover the pattern).

- [ ] **Step 8: Commit**

```bash
git add app/api/schedule/watches/
git commit -m "feat(schedule): scope watches (group + member monitor) routes by pipelineStackId"
```

---

## Task 8: Schedule — `plans` routes

**Files:**
- Modify: `app/api/schedule/plans/route.ts` (line 22).
- Modify: `app/api/schedule/plans/[planId]/route.ts` (lines 19, 109, 200).
- Modify: `app/api/schedule/plans/[planId]/run/route.ts` (line 21).

- [ ] **Step 1: `plans/route.ts` GET — scope `monitoringPlan.findMany`**

Read `stackId` from query, add `pipelineStackId: stackId` to the where clause.

- [ ] **Step 2: `plans/route.ts` POST (create plan) — stamp `pipelineStackId`**

In the `prisma.monitoringPlan.create` `data`, add `pipelineStackId: stackId`.

If the route also creates `MonitorGroup` rows (likely — plans own groups), each `monitorGroup.create` must stamp `pipelineStackId: stackId` too. Same for any `monitor.create`.

- [ ] **Step 3: `plans/[planId]/route.ts` — scope all 3 `findFirst` calls**

Lines 19, 109, 200: add `pipelineStackId: stackId`. Read from body for PATCH/DELETE, query for GET.

- [ ] **Step 4: `plans/[planId]/run/route.ts` — scope `findFirst` + propagate to children**

Line 21: add `pipelineStackId: stackId`. The plan run path may create monitors — verify any `monitor.create` or `monitorGroup.create` in this file stamps `pipelineStackId: stackId`.

- [ ] **Step 5: Commit**

```bash
git add app/api/schedule/plans/
git commit -m "feat(schedule): scope plans routes by pipelineStackId"
```

---

## Task 9: Schedule — `monitor-trends` + `alert`

**Files:**
- Modify: `app/api/schedule/monitor-trends/route.ts` (line 78).
- Modify: `app/api/schedule/alert/route.ts` (lines 59, 74).

- [ ] **Step 1: `monitor-trends/route.ts` — scope `monitorGroup.findMany`**

Read `stackId` from query, add `pipelineStackId: stackId` to where.

- [ ] **Step 2: `alert/route.ts` — convert `findUnique` → scoped `findFirst`**

Alert is called server-internally with an API key, not session — but it still must respect stack ownership. The alert payload should include the monitor's `pipelineStackId` (or fetch it from the loaded monitor and continue).

For `monitor.findUnique` on line 59: switch to `findFirst` only if the caller passes `stackId`; otherwise leave as `findUnique` and ensure `pipelineStackId` is in the `select` so downstream alert routing can use it.

The defensive change: load monitor via `findUnique` as before, but then verify `monitor.pipelineStackId === payload.stackId` if the payload has one. If they mismatch, return 400 (`payload mismatch`).

```typescript
const monitor = await prisma.monitor.findUnique({
  where: { id: payload.monitorId },
  select: { id: true, organizationId: true, pipelineStackId: true, /* ...existing fields... */ },
});
if (payload.stackId && monitor && monitor.pipelineStackId !== payload.stackId) {
  return NextResponse.json({ error: 'monitor stack mismatch' }, { status: 400 });
}
```

Same pattern for `monitorGroup.findUnique` on line 74.

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/monitor-trends/route.ts app/api/schedule/alert/route.ts
git commit -m "feat(schedule): scope monitor-trends + alert routes by pipelineStackId"
```

---

## Task 10: Drift routes

**Files:**
- Modify: `app/api/drift/route.ts` (lines 27, 37, 43).
- Modify: `app/api/drift/run/route.ts` (lines 19, 97, 108).
- Modify: `app/api/drift/[id]/route.ts` (lines 20, 30, 47, 101).

- [ ] **Step 1: `drift/route.ts` — scope all 3 calls**

Read `stackId` from query. For each of `findMany` (line 27), `findFirst` (line 37), `groupBy` (line 43), add `pipelineStackId: stackId` to where.

- [ ] **Step 2: `drift/run/route.ts` — scope monitor query + stamp drift recommendations**

Line 19 (`monitor.findMany`): add `pipelineStackId: stackId`.

Line 97 (`driftRecommendation.updateMany`): add `pipelineStackId: stackId` to the where.

Line 108 (`driftRecommendation.createMany`): for each row in the `data` array, add `pipelineStackId: stackId`. The `stackId` comes from the loaded monitor's `pipelineStackId` (since we now query monitors by `(organizationId, pipelineStackId)` on line 19, all loaded monitors share the same stack — use that single value).

- [ ] **Step 3: `drift/[id]/route.ts` — scope all 4 calls**

Read `stackId` from query (GET) or body (PATCH). Apply to:
- Line 20 (`driftRecommendation.findFirst`)
- Line 30 (`driftRecommendation.update`) — the where on `update` reduces to `id`, but precede with a `findFirst` ownership check (or use `updateMany` with `pipelineStackId` filter and check the `count` result).
- Line 47 (`monitor.update`) — same pattern.
- Line 101 (`driftRecommendation.update`) — same pattern.

Concrete pattern for `update` in this codebase (since `update` requires a unique `where`):

```typescript
const owned = await prisma.driftRecommendation.findFirst({
  where: { id, organizationId, pipelineStackId: stackId },
});
if (!owned) return NextResponse.json({ error: 'not found' }, { status: 404 });
const updated = await prisma.driftRecommendation.update({
  where: { id },
  data: { /* ... */ },
});
```

- [ ] **Step 4: Commit**

```bash
git add app/api/drift/
git commit -m "feat(drift): scope drift routes by pipelineStackId"
```

---

## Task 11: Copilot internal routes

**Files:**
- Modify: `app/api/copilot/internal/list-configured-monitors/route.ts` (line 64).
- Modify: `app/api/copilot/internal/get-monitor-run-history/route.ts` (line 34).

These are server-to-server endpoints called from Python (scanner). The caller already passes `pipelineStackId` in the request body for similar copilot internal routes (see e.g. assistant chat). Pattern: read `pipelineStackId` from JSON body, fail-fast 400 if absent.

- [ ] **Step 1: `list-configured-monitors/route.ts` — scope `monitor.findMany`**

```typescript
const { pipelineStackId, /* other body fields */ } = await request.json();
if (!pipelineStackId) {
  return NextResponse.json({ error: 'pipelineStackId required' }, { status: 400 });
}
// On line 64:
const monitors = await prisma.monitor.findMany({
  where: { organizationId, pipelineStackId, /* existing filters */ },
  ...
});
```

- [ ] **Step 2: `get-monitor-run-history/route.ts` — scope `monitor.findFirst`**

Same pattern on the `findFirst` at line 34: add `pipelineStackId` to the where.

The downstream `monitorRun.findMany` (line 45) inherits via `monitorId` — no change.

- [ ] **Step 3: Update Python callers to pass `pipelineStackId`**

The scanner calls these endpoints from `scanner/copilot/tools/` (likely `tool_executor.py`). Grep:

```bash
grep -rn "list-configured-monitors\|get-monitor-run-history" scanner/ --include="*.py"
```

For each call site, ensure the request body includes `pipelineStackId` from the active copilot session context. (The session already carries `pipelineStackId` after the lineage isolation work; the tool just needs to forward it.)

If the Python call sites don't have access to `pipelineStackId`, trace back to the copilot session context (`scanner/copilot/llm.py` or `context_builder.py`) — `selectedPipelineId` is plumbed through `CopilotContextBuilder`. Use that.

- [ ] **Step 4: Commit**

```bash
git add app/api/copilot/internal/ scanner/copilot/
git commit -m "feat(copilot): scope internal monitor endpoints + tool callers by pipelineStackId"
```

---

## Task 12: Integrations route — per-profile monitor counts

**Files:**
- Modify: `app/api/integrations/route.ts` (around line 129; also check line 41 for any `monitor` query).

The integrations list overlays a monitor count on each integration. Currently org-wide; should be per-profile.

- [ ] **Step 1: Locate the `prisma.monitor.*` calls in `integrations/route.ts`**

```bash
grep -n "prisma\.monitor" app/api/integrations/route.ts
```

For each, add `pipelineStackId: stackId` to the where (reading `stackId` from query, falling back to a 400 if not present — *or*, if the integrations list is meant to be org-wide for a settings page, leave it but stamp `pipelineStackId` on the count subquery only).

Decision: integrations themselves stay org-shared (per spec non-goals). Only the **monitor-count overlay** is per-profile. So the route shape becomes:

```typescript
const integrations = await prisma.integration.findMany({
  where: { organizationId },  // unchanged
});
// Per-profile monitor counts:
const monitorCounts = await prisma.monitor.groupBy({
  by: ['integrationId'],
  where: { organizationId, pipelineStackId: stackId, integrationId: { in: integrations.map(i => i.id) } },
  _count: true,
});
```

If the existing code already structures it this way (count via `_count: { runs: true }` on `findMany` etc.), apply the same `pipelineStackId` filter to whichever query produces the count.

- [ ] **Step 2: Commit**

```bash
git add app/api/integrations/route.ts
git commit -m "feat(integrations): scope monitor-count overlay by pipelineStackId"
```

---

## Task 13: Audit `MonitorRun` + `MonitorBaseline` direct reads

**Files:** Read-only audit; modify any file that has a direct cross-stack read.

`MonitorRun` and `MonitorBaseline` don't carry `pipelineStackId`. Isolation flows through their parent `Monitor`. Most reads filter by `monitorId` (already scoped). But any read that filters by `organizationId` directly without joining through `Monitor` could leak.

- [ ] **Step 1: Grep all direct reads**

```bash
grep -rn "prisma\.monitorRun\|prisma\.monitorBaseline" app/ lib/ --include="*.ts" --include="*.tsx"
```

Known sites (from explore):
- `app/api/schedule/tasks/[taskId]/runs/route.ts:34, 40` — filters by `monitorId`, OK.
- `app/api/schedule/tasks/[taskId]/run/route.ts:29, 459` — `create`, scoped by `monitorId`, OK.
- `app/api/copilot/internal/get-monitor-run-history/route.ts:45` — filters by `monitorId`, OK.
- `app/api/drift/run/route.ts:24` — filters by `monitorId`, OK.
- `lib/high-impact-events.ts:64` — verify the where clause in this file:

- [ ] **Step 2: Inspect `lib/high-impact-events.ts:64`**

```bash
sed -n '50,80p' lib/high-impact-events.ts
```

If it filters via `monitor: { organizationId }`, also add `monitor: { organizationId, pipelineStackId: stackId }`. If `stackId` isn't available in this helper's signature, propagate it as a parameter from callers.

If it ONLY filters by `monitorId` or via a `monitor.organizationId` join with no leaks, mark this task no-op.

- [ ] **Step 3: Apply fix if any leak found, otherwise commit nothing for this task**

If a fix was needed:

```bash
git add <fixed-files>
git commit -m "fix(monitors): scope MonitorRun/MonitorBaseline indirect reads by pipelineStackId"
```

If no fix needed, document the audit conclusion in the next commit message body.

---

## Task 14: Frontend — pass `pipelineStackId` on every fetch

**Files:**
- Modify: `app/(dashboard)/dashboard/monitors/page.tsx` — line 128 `cachedFetch('/api/schedule/tasks')` is missing `stackId`.
- Modify: `app/(dashboard)/dashboard/pipeline/page.tsx` — pass `stackId` to integrations fetch.
- Verify: `app/(dashboard)/dashboard/lineage/page.tsx` re-fetches on profile switch (the URL already includes `[stackId]`, so the page rerenders on switch — confirm).

Pattern (per the `usePipeline()` context): each fetch uses `selectedPipelineId` from the context and includes it in `useEffect` deps so the page re-fetches on switch.

- [ ] **Step 1: Update `monitors/page.tsx` — tasks fetch**

Find the `cachedFetch('/api/schedule/tasks')` call (around line 128). Change to:

```typescript
const res = await cachedFetch(`/api/schedule/tasks?stackId=${selectedPipelineId}`);
```

Also confirm the `useEffect` (or hook) that triggers this fetch has `selectedPipelineId` in its deps. If not, add it.

- [ ] **Step 2: Confirm watches + plans fetches already include `stackId`**

Per the explore output, lines 121, 139, 140 already use `selectedPipeline.id`. Verify they also have `selectedPipelineId` in their effect deps:

```bash
grep -B2 -A4 "selectedPipeline" app/\(dashboard\)/dashboard/monitors/page.tsx | head -40
```

If any effect uses an empty `[]` dep array or a stale `initializedRef.current` one-shot, refactor to depend on `selectedPipelineId`.

- [ ] **Step 3: Update `pipeline/page.tsx` — integrations fetch**

Find `invalidateCache('/api/integrations')` (around line 226) and any preceding `fetch('/api/integrations')`. Change the URL to include `?stackId=${selectedPipelineId}`. Add `selectedPipelineId` to the effect deps.

- [ ] **Step 4: Verify lineage page picks up the fix**

The lineage page calls `/api/pipeline/[stackId]/lineage/unified/route.ts` — `stackId` is already in the URL path, so the route fix in Task 5 is automatic. No frontend change needed beyond confirming the page re-renders on pipeline switch (it should, because the URL changes).

```bash
grep -n "selectedPipeline\|usePipeline" app/\(dashboard\)/dashboard/lineage/page.tsx | head -20
```

If lineage page uses `selectedPipelineId` from `usePipeline()` and the URL is rebuilt from it, no change needed.

- [ ] **Step 5: Manual smoke (cannot be automated; document the run)**

Spin up the dev server:

```bash
npm run dev
```

In the browser:
1. Sign in.
2. Profile P1 (existing or new): on the schedule page, create a monitor on `db.schema.users` and force-fail it (run with broken config).
3. Confirm P1 lineage shows the red dot on `db.schema.users`.
4. Switch to P2 (create a new pipeline profile via the picker).
5. P2 schedule page: list is empty.
6. P2 lineage page: `db.schema.users` (if present in P2's lineage) has NO red dot.
7. Switch back to P1: red dot reappears.
8. Copilot on P2 — ask "what monitors are configured?" → response says none.

Record the outcome.

- [ ] **Step 6: Commit**

```bash
git add app/\(dashboard\)/dashboard/
git commit -m "feat(ui): pass pipelineStackId on every monitor/integration fetch"
```

---

## Task 15: End-to-end verification + finishing touches

**Files:** None (or follow-ups).

- [ ] **Step 1: Full Jest suite**

```bash
DATABASE_URL=<test-db-url> npx jest --runInBand
```

Expected: all tests pass. If any tests in unrelated files broke (e.g., test fixtures that built monitors without `pipelineStackId`), update the fixtures.

- [ ] **Step 2: TypeScript check**

```bash
npx tsc --noEmit
```

Expected: no errors. The Prisma `Monitor.create` signature now requires `pipelineStackId` because it's NOT NULL — any missed call site fails the compile.

- [ ] **Step 3: ESLint**

```bash
npm run lint
```

- [ ] **Step 4: Final code review pass**

Use the `superpowers:requesting-code-review` skill against this branch before opening the PR. Specifically ask the reviewer to verify:
- Every `prisma.monitor.*`, `prisma.monitorGroup.*`, `prisma.monitoringPlan.*`, `prisma.finding.*`, `prisma.driftRecommendation.*` call includes `pipelineStackId` in its `where` (or in `data` for create).
- No remaining `findUnique({ where: { id } })` calls on these models.
- All find-by-id reads (`findFirst({ where: { id, organizationId } })`) include `pipelineStackId`.
- The Python callers of copilot internal endpoints forward `pipelineStackId`.

- [ ] **Step 5: Open the PR**

```bash
git push -u origin feat/finding-monitor-isolation
gh pr create --title "feat: per-pipeline-profile isolation for Monitor + Finding" --body "$(cat <<'EOF'
## Summary
- Adds `pipelineStackId` (NOT NULL, cascade FK) to `Monitor`, `MonitorGroup`, `MonitoringPlan`, `Finding`, and `DriftRecommendation`.
- Tightens unique constraints on `Monitor` and `Finding` to include `pipelineStackId`.
- Updates ~22 backend routes to filter by `(organizationId, pipelineStackId)` on every read and stamp `pipelineStackId` on every write.
- Updates frontend fetches to pass `pipelineStackId` from `usePipeline()`.
- Closes the user-reported bug: profile P1's failing-monitor red dots no longer appear on profile P2's lineage view.

## Migration
All existing monitors, groups, plans, findings, and drift recommendations are dropped (per spec — dev/demo data only). Recreate per profile after deploy.

## Test plan
- [ ] `npx jest prisma/__tests__/monitor_finding_isolation.test.ts` — schema cascade + uniqueness.
- [ ] `npx jest app/api/pipeline/[stackId]/lineage/__tests__/unified_isolation.test.ts` — closes the original bug.
- [ ] `npx jest app/api/schedule/tasks/__tests__/route.test.ts` — sample route-level test.
- [ ] Manual smoke: create a failing monitor on P1, switch to P2, confirm no red dot.

## Spec
`docs/superpowers/specs/2026-04-28-finding-monitor-isolation-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes (post-write)

- **Spec coverage:** Schema (Tasks 1-3), schema test (Task 4), unified-view bug fix + route test (Task 5), all schedule routes (Tasks 6-9), drift (Task 10), copilot internal + Python callers (Task 11), integrations overlay (Task 12), `MonitorRun`/`MonitorBaseline` audit (Task 13), frontend (Task 14), e2e + PR (Task 15). Each spec section maps to at least one task.
- **`MonitoringPlan` decision:** The spec was ambiguous on whether `MonitoringPlan` should also be per-stack (it left the model out of the schema diff but called it out as a non-goal in the migration purge SQL). This plan adds `pipelineStackId` to `MonitoringPlan` for consistency with the "ZERO data persistence on profile switch" rule. If the user disagrees, drop Steps 3 (Task 1) and the corresponding entries in Tasks 3, 4, and 8 — leaving plans org-shared.
- **Route count:** 22 files modified, matching the spec's enumeration.
- **No placeholders:** Every step has explicit code or commands. No "TODO" or "fill in details."
- **Type consistency:** `pipelineStackId` is the field name everywhere (matching the lineage models). Method signatures match Prisma's generated types — `findFirst`, `findMany`, `update`, `create`, `delete`, `groupBy`, `count` are unchanged from current usage.
