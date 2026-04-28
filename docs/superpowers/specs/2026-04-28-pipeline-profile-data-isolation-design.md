# Pipeline Profile Data Isolation (DB Layer + Notifications)

**Date:** 2026-04-28
**Status:** Draft (pending user approval)
**Related:** PR #39 (FastAPI in-memory cache isolation, merged separately). This spec is the follow-up that closes the same isolation gap at the Next.js / Prisma layer.

## Problem

PR #39 isolated the FastAPI in-memory lineage caches per `(org_id, stack_id)`, which was correct, but it did not fix the user-visible symptom: when a user creates a new pipeline profile, the new profile shows the previous profile's lineage and the previous profile's notifications.

Investigation of the actual data flow revealed three independent isolation gaps **at the Next.js / Prisma layer**, all of which pre-date PR #39:

### Gap 1 — Lineage DB schema has no `pipelineStackId`

`prisma/schema.prisma` lines 848–919 define `LineageNode`, `LineageEdge`, and `LineageSnapshot` (lines 921+) keyed only on `organizationId`:

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

### Gap 2 — Notifications client never sends `pipelineStackId`

`NotificationEvent` already has the column (`prisma/schema.prisma:1189`: `pipelineStackId String?`). The backend route at `app/api/notifications/route.ts:45-56` accepts and applies a `pipelineStackId` query parameter. The leak is purely client-side:

- `app/(dashboard)/dashboard/notifications/page.tsx:33-41` builds the URL without including `pipelineStackId`, so the API returns org-wide notifications.
- The page does not subscribe to `usePipeline()`. The `useEffect` (lines 61-63) depends on `[fetchNotifications]`; that callback's deps are `[severity, category, readFilter]` (line 58); none of them change when `selectedPipelineId` changes, so the page never re-fetches on profile switch.
- `cachedFetch` keys on the URL string. Because the URL never contains `pipelineStackId`, the in-memory cache (`lib/fetch-cache.ts`) serves the same payload across profile switches for up to 2 minutes.
- `components/dashboard/Header.tsx:124-174` polls `/api/notifications/unread-count` and `/api/notifications?...&unreadOnly=true` with the same omission and the same lifecycle (mount-only deps, never re-runs on profile switch). The unread-count badge is permanently org-wide.

### Gap 3 — Un-namespaced `/api/lineage/*` routes filter only by `organizationId`

These four FE routes proxy to either Prisma directly or the FastAPI scanner without forwarding a `pipelineStackId` filter:

- `app/api/lineage/route.ts:26` — `GET /api/lineage` returns `prisma.lineageNode.findMany({ where: { organizationId } })`.
- `app/api/lineage/search/route.ts:22` — accepts `stackId` in its docstring (line 5) but never reads `searchParams.get('stackId')`. Prisma query is `{ where: { organizationId, OR: [...] } }`.
- `app/api/lineage/upstream/route.ts:24` — anchor lookup is `{ where: { organizationId, name: fqn } }`. No `stackId` read.
- `app/api/lineage/nodes/[nodeId]/route.ts:26,47,94,110` — every Prisma call is `{ where: { id: nodeId, organizationId } }` or `{ where: { organizationId } }` for upstream / downstream traversal.

These routes are not currently called by the lineage page (which uses `/api/pipeline/[stackId]/lineage/...`), so they don't surface the user's symptom today. They are dormant leak paths: any future component or any other UI surface that reads them gets cross-pipeline data without warning.

## Goals

1. New pipeline profiles render an empty lineage graph until the user runs an extraction on that specific profile.
2. New pipeline profiles see no notifications until events occur on that specific profile.
3. The "clear lineage" action on a profile only clears that profile's data.
4. The unread-count badge in the Header reflects the currently-selected profile only.
5. Every `/api/lineage/*` and `/api/notifications` query that returns rows is scoped by `(organizationId, pipelineStackId)`. There is no read path that returns org-wide rows.

## Non-goals

- Re-design of the FastAPI auth or caching architecture — PR #39 already shipped that piece.
- Moving `Integration` to be per-pipeline-stack. Integrations stay org-level and shared. Per-pipeline scoping is achieved by `pipelineStackId` on the lineage tables, not by reshaping integrations.
- Backfilling existing rows. Existing `LineageNode` / `LineageEdge` / `LineageSnapshot` rows are dropped during the migration; the user re-runs extraction on each profile they care about.
- The `LineageNode.upstreamCount` / `downstreamCount` denormalized counts. They keep their current meaning (per-row) and are recomputed by extraction.
- The four `HIGH`-severity auth-audit findings in `drift.py`, `schedule.py`, `policies.py`, `copilot.py` — separate PR.
- The OpenLineage push endpoints — separate PR.

## Approach

### Cluster 1 — Lineage DB schema migration

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

The column is `String?` (nullable) so the migration applies cleanly to existing rows. The migration immediately follows the schema change with a `DELETE FROM "LineageNode"; DELETE FROM "LineageEdge"; DELETE FROM "LineageSnapshot"` to clear all existing rows — confirmed acceptable by the user (demo / dev data only).

The `@@unique([organizationId, name])` constraint is replaced by `@@unique([organizationId, pipelineStackId, name])` so two profiles can hold a node with the same FQN without collision.

**Cascading delete.** `onDelete: Cascade` on the new relation means deleting a `PipelineStack` cascades to its lineage rows. This matches the user's mental model from the project memory ("Pipeline profiles are fully isolated workspaces ... Switching profiles means ZERO data persistence from the previous one").

### Cluster 1 — Lineage write paths

The single write site for lineage data is `app/api/pipeline/[stackId]/lineage/extract-lineage.ts`. After the FastAPI extraction returns nodes/edges, the FE upserts them into Prisma. Every write must now set `pipelineStackId = stackId`. The unique-key `@@unique([organizationId, pipelineStackId, name])` makes the upsert key compound; existing upsert calls keyed on `(organizationId, name)` are updated to include `pipelineStackId`.

### Cluster 1 — Lineage read paths

| File | Current filter | New filter |
|---|---|---|
| `app/api/pipeline/[stackId]/lineage/route.ts:74-83` (GET) | `{ organizationId, integrationId? in [...] }` | `{ organizationId, pipelineStackId: stackId }` (drop the integrationId branch entirely) |
| same file, line 98-104 (edges) | `{ organizationId, sourceId in nodeIds, targetId in nodeIds }` | add `pipelineStackId: stackId` |
| same file, line 107-116 (snapshot) | `{ organizationId, integrationId? in [...] }` | `{ organizationId, pipelineStackId: stackId }` |
| same file, line 173-186 (DELETE) | `{ organizationId }` | `{ organizationId, pipelineStackId: stackId }` |

### Cluster 1 — Un-namespaced `/api/lineage/*` route fixes

For each of the four routes, accept `stackId` (or `pipelineStackId`) as a query parameter, derive the user's `organizationId` from session as today, and add the filter to every Prisma query:

| File | Change |
|---|---|
| `app/api/lineage/route.ts:26` (GET) | Read `stackId` from query; require it (400 if missing); add to `where` clause |
| `app/api/lineage/route.ts` (POST) | Read `stackId` from body; require it; set on every created node/edge |
| `app/api/lineage/search/route.ts:22` | Read `stackId` (already documented in the comment); require it; add to `where` |
| `app/api/lineage/upstream/route.ts:24` | Read `stackId` from query; require it; add to anchor lookup and traversal queries |
| `app/api/lineage/nodes/[nodeId]/route.ts:26,47,94,110` | Read `stackId` from query; require it; add to every query |

"Require it" is concrete: if `stackId` is absent or empty, return `400 {"error": "missing_pipeline_stack_id"}`. This makes the contract explicit — there is no fallback to org-wide queries from these routes after the change.

Callers of these routes that don't currently pass a `stackId` (e.g. `app/lineage/route.ts`'s GET callers, if any) must be updated to pass the active `selectedPipelineId` from `usePipeline()`. The implementation plan will enumerate every call site.

### Cluster 2 — Notifications client wiring

**Page-level fix** (`app/(dashboard)/dashboard/notifications/page.tsx`):

1. Add `import { usePipeline } from '@/contexts/PipelineContext'` and read `selectedPipelineId` at the top of the component.
2. Append `pipelineStackId=${selectedPipelineId}` to the `URLSearchParams` in the `fetchNotifications` callback (lines 33-39). If `selectedPipelineId` is null/empty, the page renders an empty state ("Select a pipeline profile to view notifications") instead of fetching org-wide.
3. Add `selectedPipelineId` to the `useCallback` deps for `fetchNotifications` (currently `[severity, category, readFilter]`, line 58) so the callback identity changes on profile switch and triggers the existing `useEffect`.
4. Invalidate the `cachedFetch` cache for the notifications URL prefix on profile switch so a stale entry from the previous profile cannot be served. Use `invalidateCache('/api/notifications')` (already supported by `lib/fetch-cache.ts`).

**Header poller fix** (`components/dashboard/Header.tsx:124-174`):

1. Add `usePipeline()` to read `selectedPipelineId`.
2. Update `fetchUnreadCount` to call `/api/notifications/unread-count?pipelineStackId=${selectedPipelineId}` and add `selectedPipelineId` to its `useCallback` deps.
3. Update `checkNewAlerts` similarly.
4. The interval `useEffect` at line 169 keeps its existing structure; both callbacks now have `selectedPipelineId` in their deps so the interval re-binds to the new profile on switch.
5. The backend `GET /api/notifications/unread-count` route must accept and filter by `pipelineStackId` if it doesn't already — the implementation plan verifies and patches this.

When `selectedPipelineId` is null/empty (e.g. before the user has selected a profile, or while the context is loading), the badge displays no count instead of org-wide.

### Cluster 3 — Backend route filter for `/api/notifications/unread-count`

Verify the backend supports `pipelineStackId` filtering (the implementation plan checks this; if not, it adds the parameter handling using the same pattern as `/api/notifications/route.ts:45-56`).

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

Notifications page mounts on P2 (or user switches while on it)
  → fetchNotifications builds URL with pipelineStackId='p2-id'
  → route reads from Prisma WHERE organizationId='X' AND pipelineStackId='p2-id'
  → returns 0 events
  → page renders "No notifications"

Header bell badge re-fetches unread count for P2
  → /api/notifications/unread-count?pipelineStackId=p2-id
  → returns 0
  → badge hidden
```

## Migration

Single migration file `prisma/migrations/<timestamp>_add_pipeline_stack_id_to_lineage/migration.sql`:

```sql
-- Add nullable column
ALTER TABLE "LineageNode"     ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "LineageEdge"     ADD COLUMN "pipelineStackId" TEXT;
ALTER TABLE "LineageSnapshot" ADD COLUMN "pipelineStackId" TEXT;

-- Drop existing rows (user accepted: demo / dev data only)
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

The migration runs as part of normal `prisma migrate deploy`. No manual data step. After deploy, the user re-runs extraction on each profile they care about.

## Testing

1. **Schema-level test.** A Vitest / Jest test that uses a Prisma test database and asserts:
   - Two profiles in the same org with the same node FQN can both create their own `LineageNode` rows without violating the unique constraint.
   - Querying `prisma.lineageNode.findMany({ where: { organizationId, pipelineStackId } })` returns only that profile's rows.
   - Deleting a `PipelineStack` cascades to its lineage rows.
2. **Route-level test for `/api/pipeline/[stackId]/lineage`.** Stub `auth()` to return two distinct sessions (org X, user A and user B both in org X for two profiles). Seed lineage for profile P1 only. Assert:
   - `GET /api/pipeline/p2/lineage` returns 0 nodes.
   - `DELETE /api/pipeline/p1/lineage` does not affect P2's data (seed P2 first to make this assertable).
3. **Route-level tests for the four un-namespaced `/api/lineage/*` routes.** For each:
   - Without `stackId` → 400.
   - With `stackId=p1` and seeded data for P1 only → returns rows.
   - With `stackId=p2` (no seeded data) → returns no rows even when P1 has data.
4. **Notifications test.**
   - `GET /api/notifications` without `pipelineStackId` returns no rows for any pipeline (or 400; pick one in the implementation plan and stick to it). With `pipelineStackId=p1` returns only P1 events.
   - `GET /api/notifications/unread-count?pipelineStackId=p2` returns 0 when only P1 has events.
5. **End-to-end smoke test (Playwright or manual).**
   - Run extraction on profile P1 (sees graph populated).
   - Switch to a freshly-created profile P2.
   - Lineage page shows empty graph (0 nodes / 0 edges).
   - Notifications page shows empty list.
   - Header bell badge shows no count.
   - Switch back to P1: graph and notifications come back exactly as before.

## Rollout

- Single migration, applied via `prisma migrate deploy` on next deploy.
- The migration drops existing `LineageNode` / `LineageEdge` / `LineageSnapshot` rows. Users (currently only this developer's demo data) re-run extraction on each profile.
- No feature flag.

## PR strategy

This work is a separate PR (call it #40). PR #39 stands on its own — it correctly fixed the in-memory FastAPI cache and remains an independent commit set. #40 is sequenced after #39 (no rebase required since they touch different layers, but #40 may want #39's clean-cache helper if it triggers a re-build during testing).

## Out of scope (acknowledged)

- Backfilling existing lineage data — explicitly dropped per user direction.
- Per-pipeline scoping of `Integration` — integrations stay org-level shared.
- The four `HIGH` severity auth findings (`drift.py`, `schedule.py`, `policies.py`, `copilot.py`).
- OpenLineage push-endpoint auth redesign.
- Other dashboard surfaces that may have similar isolation gaps (the audit covered the lineage page, notifications page, header poller, and the `/api/lineage/*` and `/api/notifications` routes — that is the scope here).

## Open questions

None.
