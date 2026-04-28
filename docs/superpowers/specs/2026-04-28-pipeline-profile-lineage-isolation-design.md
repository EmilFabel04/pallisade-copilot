# Pipeline Profile Lineage Isolation

**Date:** 2026-04-28
**Status:** Draft (pending user approval)
**Related:** PR #39 (FastAPI in-memory cache isolation, merged separately). This spec closes the same isolation gap at the Next.js / Prisma layer for lineage.

## Problem

PR #39 isolated the FastAPI in-memory lineage caches per `(org_id, stack_id)`, which was correct, but it did not fix the user-visible symptom: when a user creates a new pipeline profile, the new profile shows the previous profile's lineage.

The root cause is in the Prisma layer:

`prisma/schema.prisma:848-919` defines `LineageNode`, `LineageEdge`, and `LineageSnapshot` (line 921+) keyed only on `organizationId`:

```prisma
model LineageNode {
  organization   Organization @relation(fields: [organizationId], references: [id], ...)
  organizationId String
  integration    Integration? @relation(fields: [integrationId], references: [id])
  integrationId  String?
  // NO pipelineStackId
  @@unique([organizationId, name])
}
```

Every pipeline profile in the same org shares the same row set. The user-visible leak surfaces in `app/api/pipeline/[stackId]/lineage/route.ts:74-83`:

```typescript
const allNodes = await prisma.lineageNode.findMany({
  where: {
    organizationId,
    ...(integrationIds.length > 0
      ? { integrationId: { in: integrationIds } }
      : {}        // ← new pipeline → no integrations bound → org-wide leak
    ),
  },
})
```

The route attempts to filter by integrations attached to the stack, but a freshly-created pipeline profile with no integrations bound yet falls into the `{}` branch and the query returns every row in the org.

The DELETE handler at line 173–186 of the same file is symmetrically broken: `prisma.lineageNode.deleteMany({ where: { organizationId } })` wipes ALL profiles' rows.

`Integration` rows are inherently org-level (`prisma/schema.prisma:1567-1568`); a single integration can be referenced by multiple `PipelineStack` rows via `PipelineNode`. That means filtering on `integrationId` is not a substitute for filtering on `pipelineStackId` — the only correct scope is the stack itself.

## Goals

1. New pipeline profiles render an empty lineage graph until the user runs an extraction on that specific profile.
2. The "clear lineage" action on a profile only clears that profile's data.
3. Every read path that surfaces lineage to the user is scoped to the current stack:
   - `GET /api/pipeline/[stackId]/lineage` (the lineage page primary fetch).
   - `GET /api/pipeline/[stackId]/lineage/unified` at `app/api/pipeline/[stackId]/lineage/unified/route.ts:397-404` (uses the same broken `integrationIds` filter as the primary route).
   - `app/api/copilot/chat/route.ts` lines 119 and 502 (two org-wide `lineageNode.findMany` calls that pass lineage to the assistant — must be scoped to `effectivePipelineStackId` so the assistant doesn't see other profiles' nodes).
4. The DELETE path `DELETE /api/pipeline/[stackId]/lineage` only deletes that stack's rows.

## Non-goals

- **Notifications isolation.** The notifications page, header bell badge, and `/api/notifications*` routes also leak across profiles, but that is a separate effort and not in scope here. Tracked separately so this PR stays a focused lineage migration.
- **The un-namespaced `/api/lineage/*` routes** (`/api/lineage`, `/api/lineage/search`, `/api/lineage/upstream`, `/api/lineage/nodes/[nodeId]`). They filter only by `organizationId`, but the lineage page does not call them today (it uses `/api/pipeline/[stackId]/lineage/...`). They are dormant leak paths — fixing them is a separate hardening PR. This PR's migration leaves them functionally unchanged: their queries continue to return rows scoped only by `organizationId` even though the underlying rows are now per-stack. That is acceptable because nothing reads from them in the current UI.
- Re-design of the FastAPI auth or caching architecture — PR #39 already shipped that.
- Moving `Integration` to be per-pipeline-stack. Integrations stay org-level and shared. Per-pipeline scoping is achieved by `pipelineStackId` on the lineage tables.
- Backfilling existing rows. Existing `LineageNode` / `LineageEdge` / `LineageSnapshot` rows are dropped during the migration; the user re-runs extraction on each profile they care about.
- The `LineageNode.upstreamCount` / `downstreamCount` denormalized counts. They keep their current per-row meaning and are recomputed by extraction.

## Approach

### Schema migration

**Add `pipelineStackId` to three Prisma models.**

```prisma
model LineageNode {
  ...existing fields...
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
  ...
  @@unique([organizationId, pipelineStackId, name])  // was: @@unique([organizationId, name])
  @@index([organizationId, pipelineStackId])
  @@index([pipelineStackId])
}

model LineageEdge {
  ...existing fields...
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
  ...
  @@index([pipelineStackId])
}

model LineageSnapshot {
  ...existing fields...
  pipelineStack   PipelineStack? @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String?
  ...
  @@index([pipelineStackId])
}
```

`pipelineStackId` is `String?` (nullable) so the migration applies cleanly to existing rows. The migration immediately follows the schema change with `DELETE FROM "LineageNode"; DELETE FROM "LineageEdge"; DELETE FROM "LineageSnapshot"` to clear all existing rows — confirmed acceptable by the user (demo / dev data only).

The `@@unique([organizationId, name])` constraint is replaced by `@@unique([organizationId, pipelineStackId, name])` so two profiles can hold a node with the same FQN without collision. `LineageEdge`'s existing `@@unique([sourceId, targetId])` is unchanged: it remains correct because `sourceId`/`targetId` reference per-stack node rows after the migration.

**`LineageEdge.pipelineStackId` is denormalization, not isolation.** Edges are already scoped to a stack via their source/target node FKs. The `pipelineStackId` on the edge is for query speed (filter edges directly without joining nodes) and for the `onDelete: Cascade` from `PipelineStack`. The write path must set `edge.pipelineStackId = source.pipelineStackId` (= `target.pipelineStackId`) at write time; an inconsistency would be a bug.

**Cascading delete.** `onDelete: Cascade` on the new relation means deleting a `PipelineStack` cascades to its lineage rows. This matches the user's mental model: "Pipeline profiles are fully isolated workspaces ... Switching profiles means ZERO data persistence from the previous one."

**`integrationId` semantics post-migration.** `LineageNode.integrationId` stays as informational metadata (which integration extraction populated this row), but it carries no isolation responsibility — `pipelineStackId` does. Reads filter by `pipelineStackId`; `integrationId` is no longer used in the GET filter. If two integrations in the same stack expose the same FQN, the upsert key `(organizationId, pipelineStackId, name)` collapses them to one row whose `integrationId` reflects the most recent writer. This matches today's de-facto dedup behavior at `route.ts:86-94` and is the intended semantics.

### Write paths

The single write site for lineage data is `app/api/pipeline/[stackId]/lineage/extract-lineage.ts`. After the FastAPI extraction returns nodes/edges, the FE upserts them into Prisma. Every write must now set `pipelineStackId = stackId` on nodes, edges, and snapshots. The unique-key `@@unique([organizationId, pipelineStackId, name])` makes the upsert key compound; existing upsert calls keyed on `(organizationId, name)` are updated to include `pipelineStackId`.

### Read paths

| File | Current filter | New filter |
|---|---|---|
| `app/api/pipeline/[stackId]/lineage/route.ts:74-83` (GET nodes) | `{ organizationId, integrationId? in [...] }` | `{ organizationId, pipelineStackId: stackId }` (drop the integrationId branch entirely) |
| same file, line 98-104 (edges) | `{ organizationId, sourceId in nodeIds, targetId in nodeIds }` | add `pipelineStackId: stackId` |
| same file, line 107-116 (snapshot) | `{ organizationId, integrationId? in [...] }` | `{ organizationId, pipelineStackId: stackId }` |
| same file, line 173-186 (DELETE) | `{ organizationId }` | `{ organizationId, pipelineStackId: stackId }` |
| `app/api/pipeline/[stackId]/lineage/unified/route.ts:397-404` (GET nodes for unified view) | `{ organizationId, integrationId? in [...] }` | `{ organizationId, pipelineStackId: stackId }` |
| `app/api/copilot/chat/route.ts:119-132` (lineage nodes for assistant context) | `{ organizationId }` | `{ organizationId, pipelineStackId: effectivePipelineStackId }` |
| `app/api/copilot/chat/route.ts:133-141` (lineage edges for assistant context) | `{ organizationId }` | `{ organizationId, pipelineStackId: effectivePipelineStackId }` |
| `app/api/copilot/chat/route.ts:502-509` (streaming variant — same pattern) | `{ organizationId }` | `{ organizationId, pipelineStackId: effectivePipelineStackId }` |
| `app/api/copilot/chat/route.ts:510-513` (streaming edges) | `{ organizationId }` | `{ organizationId, pipelineStackId: effectivePipelineStackId }` |

The DELETE handler also gains the same ownership check the GET already does (lines 49-66): `findFirst` the stack by `(id, organizationId)` first; if absent, return 404 instead of silently "succeeding" with 0 deletes. This makes "wrong stackId" produce a useful error.

The copilot routes already resolve `effectivePipelineStackId` from the request body before the lineage fetch (lines 100-110, 480-495). Both copilot variants — sync at line 119 and streaming at line 502 — already have the value in scope; only the `where` clause changes.

## Data flow after the change

```
User creates new pipeline profile P2 (in same org X as P1)
  → PipelineContext.selectPipeline("p2-id")
  → selectedPipelineId = "p2-id" in context + localStorage

Lineage page mounts on P2
  → fetchLineage uses URL /api/pipeline/p2-id/lineage/...
  → route reads from Prisma WHERE organizationId='X' AND pipelineStackId='p2-id'
  → returns 0 nodes / 0 edges (P2 has no extraction yet)
  → page renders empty graph

User runs extraction on P2
  → extract-lineage.ts upserts with pipelineStackId='p2-id'
  → P2's rows live alongside P1's rows; neither is visible to the other.

User clicks "clear lineage" on P2
  → DELETE /api/pipeline/p2-id/lineage
  → route deletes WHERE organizationId='X' AND pipelineStackId='p2-id'
  → P1's rows untouched.
```

## Migration

Single migration file `prisma/migrations/<timestamp>_add_pipeline_stack_id_to_lineage/migration.sql`:

```sql
-- Add nullable column
ALTER TABLE "LineageNode"     ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "LineageEdge"     ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "LineageSnapshot" ADD COLUMN "pipelineStackId" TEXT;

-- Drop existing rows (user accepted: demo / dev data only).
-- This is the destructive step; users re-run extraction post-deploy.
DELETE FROM "LineageEdge";
DELETE FROM "LineageNode";
DELETE FROM "LineageSnapshot";

-- Replace the unique constraint to include the new column
ALTER TABLE "LineageNode" DROP CONSTRAINT "LineageNode_organizationId_name_key";
ALTER TABLE "LineageNode"
  ADD CONSTRAINT "LineageNode_organizationId_pipelineStackId_name_key"
  UNIQUE ("organizationId", "pipelineStackId", "name");

-- Foreign keys with cascade delete (matches the @relation onDelete: Cascade)
ALTER TABLE "LineageNode"
  ADD CONSTRAINT "LineageNode_pipelineStackId_fkey"
  FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;
ALTER TABLE "LineageEdge"
  ADD CONSTRAINT "LineageEdge_pipelineStackId_fkey"
  FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;
ALTER TABLE "LineageSnapshot"
  ADD CONSTRAINT "LineageSnapshot_pipelineStackId_fkey"
  FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE;

-- Indexes
CREATE INDEX "LineageNode_organizationId_pipelineStackId_idx" ON "LineageNode" ("organizationId", "pipelineStackId");
CREATE INDEX "LineageNode_pipelineStackId_idx"               ON "LineageNode" ("pipelineStackId");
CREATE INDEX "LineageEdge_pipelineStackId_idx"               ON "LineageEdge" ("pipelineStackId");
CREATE INDEX "LineageSnapshot_pipelineStackId_idx"           ON "LineageSnapshot" ("pipelineStackId");
```

The migration runs as part of normal `prisma migrate deploy`. After deploy, the user re-runs extraction on each profile they care about.

## Testing

1. **Schema-level test.** A Vitest / Jest test against a Prisma test database asserts:
   - Two profiles in the same org with the same node FQN can both create their own `LineageNode` rows without violating the unique constraint.
   - `prisma.lineageNode.findMany({ where: { organizationId, pipelineStackId } })` returns only that profile's rows.
   - Deleting a `PipelineStack` cascades to its lineage rows (nodes, edges, snapshots).
   - Concurrent extractions on two stacks with overlapping FQNs do not collide.
2. **Route-level test for `/api/pipeline/[stackId]/lineage`.** Stub `auth()` for one session in org X with two profiles P1 and P2. Seed lineage for P1 only. Assert:
   - `GET /api/pipeline/p2/lineage` returns 0 nodes.
   - `GET /api/pipeline/p1/lineage` returns the seeded rows.
   - `DELETE /api/pipeline/p1/lineage` after also seeding P2 leaves P2's rows intact.
   - `DELETE /api/pipeline/<unknown-stack>/lineage` returns 404.
3. **End-to-end smoke (manual).**
   - Run extraction on profile P1 (graph populates).
   - Switch to a freshly-created profile P2: graph is empty.
   - Run extraction on P2: P2's graph populates; P1's is unaffected.
   - Switch back to P1: P1's graph is exactly as it was.

## Rollout

- Single migration, applied via `prisma migrate deploy` on next deploy.
- The migration drops existing `LineageNode` / `LineageEdge` / `LineageSnapshot` rows. Users (currently only this developer's demo data) re-run extraction on each profile.
- No feature flag.

## PR strategy

This work is a separate PR (call it #40). PR #39 stands on its own. #40 sequences after #39 (no rebase required since they touch different layers).

## Open questions

None.
