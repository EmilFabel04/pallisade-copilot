# Scheduled Lineage Extraction & Layout Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-extract lineage every 6 hours per pipeline stack (after first manual build) and eliminate layout jitter on tab/visibility/pipeline switches.

**Architecture:** Two independent changes. (1) Add `lastLineageExtractedAt`/`lineageExtractionEnabled` to PipelineStack, create an internal-only extraction endpoint authenticated by `INTERNAL_API_KEY`, and add a lineage check to the Python scheduler loop. (2) Remove premature `setRenderedView(null)` calls from the lineage page so the previous layout stays visible until fresh data atomically replaces it.

**Tech Stack:** Next.js 15 (App Router), Prisma ORM, Python FastAPI scheduler (asyncio + psycopg2), React (ReactFlow)

---

## File Structure

### Part 1: Scheduled Extraction

| File | Action | Responsibility |
|------|--------|----------------|
| `prisma/schema.prisma` | Modify | Add two fields to `PipelineStack` model |
| `app/api/pipeline/[stackId]/lineage/scheduled/route.ts` | Create | Internal-only extraction endpoint (same logic as manual, auth via header) |
| `app/api/pipeline/[stackId]/lineage/route.ts` | Modify | Set `lastLineageExtractedAt` + `lineageExtractionEnabled` after manual build |
| `scanner/scheduler/service.py` | Modify | Add `_check_lineage_extraction()` to the loop |

### Part 2: Layout Stability

| File | Action | Responsibility |
|------|--------|----------------|
| `app/(dashboard)/dashboard/lineage/page.tsx` | Modify | Remove `setRenderedView(null)` from visibility/tab handlers; add loading guard to useMemo |

---

## Part 1: Scheduled Extraction

### Task 1: Prisma Schema — Add Scheduling Fields to PipelineStack

**Files:**
- Modify: `prisma/schema.prisma:297-351` (PipelineStack model)

- [ ] **Step 1: Add the two new fields to PipelineStack**

In `prisma/schema.prisma`, inside the `PipelineStack` model, add these two fields after the `lastScanAt` line (after line ~308):

```prisma
  // Scheduled lineage extraction
  lastLineageExtractedAt   DateTime?
  lineageExtractionEnabled Boolean   @default(false)
```

- [ ] **Step 2: Generate the Prisma migration**

Run:
```bash
npx prisma migrate dev --name add-lineage-scheduling-fields
```

Expected: Migration created successfully, no errors.

- [ ] **Step 3: Verify the migration SQL**

Run:
```bash
cat prisma/migrations/*add-lineage-scheduling-fields*/migration.sql
```

Expected: SQL containing `ALTER TABLE "PipelineStack" ADD COLUMN "lastLineageExtractedAt" TIMESTAMP(3)` and `ADD COLUMN "lineageExtractionEnabled" BOOLEAN NOT NULL DEFAULT false`.

- [ ] **Step 4: Generate Prisma client**

Run:
```bash
npx prisma generate
```

Expected: `✔ Generated Prisma Client`

- [ ] **Step 5: Commit**

```bash
git add prisma/schema.prisma prisma/migrations/
git commit -m "feat: add lineage scheduling fields to PipelineStack"
```

---

### Task 2: Update Manual Build to Set Scheduling Fields

**Files:**
- Modify: `app/api/pipeline/[stackId]/lineage/route.ts:447-458` (after snapshot creation)

- [ ] **Step 1: Add the scheduling field update after snapshot persistence**

In `app/api/pipeline/[stackId]/lineage/route.ts`, find the snapshot creation block (around line 447-458). After the `prisma.lineageSnapshot.create(...)` call and before the "Build results summary" section (line ~485), add:

```typescript
    // Mark stack as extraction-enabled and record timestamp (resets 6h auto-timer)
    await prisma.pipelineStack.update({
      where: { id: stackId },
      data: {
        lineageExtractionEnabled: true,
        lastLineageExtractedAt: new Date(),
      },
    });
```

- [ ] **Step 2: Verify the manual build endpoint still works**

Start the dev server and trigger a "Build Lineage" from the UI on any pipeline stack. Check the browser network tab for a 200 response from `POST /api/pipeline/[stackId]/lineage`.

Then verify the database was updated:

```bash
npx prisma studio
```

Open the `PipelineStack` table and confirm the stack you triggered now has `lineageExtractionEnabled = true` and `lastLineageExtractedAt` set to the current time.

- [ ] **Step 3: Commit**

```bash
git add app/api/pipeline/[stackId]/lineage/route.ts
git commit -m "feat: set lineage scheduling fields on manual build"
```

---

### Task 3: Create Internal Scheduled Extraction Endpoint

**Files:**
- Create: `app/api/pipeline/[stackId]/lineage/scheduled/route.ts`
- Modify: `app/api/pipeline/[stackId]/lineage/route.ts` (extract shared logic)

The internal endpoint reuses the entire extraction flow from the manual endpoint but authenticates via `INTERNAL_API_KEY` header instead of user session. Since the manual handler is ~450 lines, the cleanest approach is to extract the core logic into a shared function and call it from both routes.

- [ ] **Step 1: Extract shared extraction function from the manual route**

In `app/api/pipeline/[stackId]/lineage/route.ts`, extract the core logic (lines ~85–510) into a standalone async function. Add this function above the `POST` export:

```typescript
/**
 * Core lineage extraction logic shared between manual and scheduled routes.
 * Resolves nodes, decrypts creds, calls the Python investigator, persists results.
 */
export async function extractLineageForStack(
  stackId: string,
  organizationId: string,
  body: { nodeId?: string; options?: any }
): Promise<NextResponse> {
  const { nodeId, options } = body;

  // Fetch pipeline stack
  const stack = await prisma.pipelineStack.findFirst({
    where: { id: stackId, organizationId },
    include: { nodes: { include: { integration: true } } },
  });

  if (!stack) {
    return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
  }

  // --- paste the rest of the existing POST handler body here, starting from
  //     "Filter connected nodes" (line ~105) through the return statement (line ~510) ---
  //     Replace every reference to `stackId` and `organizationId` (they're already in scope
  //     as function params).
  //     At the end, after the snapshot creation block, add the scheduling field update
  //     (same code from Task 2) so both manual and scheduled paths set the timestamp.
```

Then simplify the `POST` export to:

```typescript
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  const { stackId } = await params;
  const body = await request.json().catch(() => ({}));

  return extractLineageForStack(stackId, organizationId, body);
}
```

- [ ] **Step 2: Verify the manual endpoint still works after refactor**

Run:
```bash
npm run build
```

Expected: Build succeeds with no type errors.

Start the dev server and trigger "Build Lineage" from the UI to confirm the manual flow is intact.

- [ ] **Step 3: Create the scheduled endpoint**

Create `app/api/pipeline/[stackId]/lineage/scheduled/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';
import { extractLineageForStack } from '../route';

const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY || 'dev-internal-key-not-for-production';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  // Authenticate via internal API key
  const apiKey = request.headers.get('x-internal-api-key');
  if (apiKey !== INTERNAL_API_KEY) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { stackId } = await params;

  // Look up the stack to get its organizationId
  const stack = await prisma.pipelineStack.findUnique({
    where: { id: stackId },
    select: { organizationId: true },
  });

  if (!stack) {
    return NextResponse.json({ error: 'Stack not found' }, { status: 404 });
  }

  console.log(`[LINEAGE-SCHEDULED] Starting auto-extraction for stack ${stackId}`);
  const start = Date.now();

  const result = await extractLineageForStack(stackId, stack.organizationId, {});

  const duration = Date.now() - start;
  const status = result.status;

  if (status === 200) {
    const data = await result.json();
    console.log(
      `[LINEAGE-SCHEDULED] Completed for stack ${stackId}: ` +
      `${data.stats?.totalNodes || 0} nodes, ${data.stats?.totalEdges || 0} edges, ${duration}ms`
    );
    return NextResponse.json({
      success: true,
      nodes: data.stats?.totalNodes || 0,
      edges: data.stats?.totalEdges || 0,
      durationMs: duration,
    });
  } else {
    console.warn(`[LINEAGE-SCHEDULED] Failed for stack ${stackId}: HTTP ${status}, ${duration}ms`);
    return NextResponse.json(
      { error: `Extraction failed with status ${status}` },
      { status: 500 }
    );
  }
}
```

- [ ] **Step 4: Verify the scheduled endpoint rejects bad auth**

```bash
curl -X POST http://localhost:3000/api/pipeline/fake-id/lineage/scheduled \
  -H "Content-Type: application/json"
```

Expected: `401 Unauthorized` (no API key header).

```bash
curl -X POST http://localhost:3000/api/pipeline/fake-id/lineage/scheduled \
  -H "Content-Type: application/json" \
  -H "x-internal-api-key: wrong-key"
```

Expected: `401 Unauthorized` (wrong key).

```bash
curl -X POST http://localhost:3000/api/pipeline/fake-id/lineage/scheduled \
  -H "Content-Type: application/json" \
  -H "x-internal-api-key: dev-internal-key-not-for-production"
```

Expected: `404 Stack not found` (correct auth, stack doesn't exist).

- [ ] **Step 5: Commit**

```bash
git add app/api/pipeline/[stackId]/lineage/route.ts app/api/pipeline/[stackId]/lineage/scheduled/route.ts
git commit -m "feat: add internal scheduled lineage extraction endpoint"
```

---

### Task 4: Add Lineage Extraction Check to Python Scheduler

**Files:**
- Modify: `scanner/scheduler/service.py:98-108` (add to loop), plus new method

- [ ] **Step 1: Add the lineage check call to the loop**

In `scanner/scheduler/service.py`, modify the `_loop` method (line 98) to include the new check:

```python
    async def _loop(self):
        # Small initial delay to let the app fully boot
        await asyncio.sleep(5)

        while self._running:
            try:
                await self._check_due_tasks()
                await self._check_drift_analysis()
                await self._check_lineage_extraction()
            except Exception as e:
                logger.error(f"[Scheduler] Error in loop: {e}")
            await asyncio.sleep(self._interval)
```

- [ ] **Step 2: Add the `_check_lineage_extraction` method**

Add this method to the `SchedulerService` class, after the `_check_drift_analysis` method:

```python
    async def _check_lineage_extraction(self):
        """Check for pipeline stacks due for automatic lineage re-extraction."""
        import httpx
        from datetime import timedelta

        conn = self._get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            six_hours_ago = datetime.now(timezone.utc) - timedelta(hours=6)

            # Find stacks where auto-extraction is enabled and last extraction was >6h ago
            cursor.execute(
                """
                SELECT id, "lastLineageExtractedAt"
                FROM "PipelineStack"
                WHERE "lineageExtractionEnabled" = true
                  AND (
                    "lastLineageExtractedAt" IS NULL
                    OR "lastLineageExtractedAt" <= %s
                  )
                """,
                (six_hours_ago,),
            )
            due_stacks = cursor.fetchall()
            cursor.close()

            if not due_stacks:
                return

            logger.info(
                "[Scheduler] Lineage extraction due",
                count=len(due_stacks),
            )

            nextauth_url = os.environ.get("NEXTAUTH_URL", "http://localhost:3000")
            internal_key = os.environ.get("INTERNAL_API_KEY", "dev-internal-key-not-for-production")

            async with httpx.AsyncClient(timeout=httpx.Timeout(620.0)) as client:
                for stack_id, last_extracted in due_stacks:
                    try:
                        logger.info(
                            "[Scheduler] Starting lineage extraction",
                            stack_id=stack_id,
                            last_extracted=str(last_extracted),
                        )
                        resp = await client.post(
                            f"{nextauth_url}/api/pipeline/{stack_id}/lineage/scheduled",
                            headers={"x-internal-api-key": internal_key},
                            json={},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            logger.info(
                                "[Scheduler] Lineage extraction complete",
                                stack_id=stack_id,
                                nodes=data.get("nodes", 0),
                                edges=data.get("edges", 0),
                                duration_ms=data.get("durationMs", 0),
                            )
                        else:
                            logger.warning(
                                "[Scheduler] Lineage extraction failed",
                                stack_id=stack_id,
                                status=resp.status_code,
                                body=resp.text[:200],
                            )
                    except Exception as e:
                        logger.warning(
                            "[Scheduler] Lineage extraction error",
                            stack_id=stack_id,
                            error=str(e),
                        )
        except Exception as e:
            logger.error(f"[Scheduler] Error checking lineage extraction: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
```

- [ ] **Step 3: Add httpx to scanner dependencies (if not already present)**

Check if httpx is already available:
```bash
cd scanner && pip show httpx
```

If not installed:
```bash
pip install httpx
```

And add `httpx` to `scanner/requirements.txt` (or `pyproject.toml`).

- [ ] **Step 4: Verify the scheduler starts without errors**

```bash
cd scanner && python -m uvicorn main:app --reload
```

Check logs for `[Scheduler] Started` — no import errors or exceptions.

- [ ] **Step 5: Commit**

```bash
git add scanner/scheduler/service.py
git commit -m "feat: add scheduled lineage extraction to scheduler loop"
```

---

### Task 5: Add INTERNAL_API_KEY to Environment

**Files:**
- Modify: `.env` (local dev)

- [ ] **Step 1: Generate and add the key**

```bash
echo "INTERNAL_API_KEY=$(openssl rand -hex 32)" >> .env
```

- [ ] **Step 2: Verify both services can read it**

Restart the Next.js dev server and the Python scanner. Confirm no errors related to the new environment variable.

- [ ] **Step 3: Commit (do NOT commit .env — just document)**

Do NOT commit `.env`. If there is a `.env.example`, add:

```
INTERNAL_API_KEY=          # Shared secret between Next.js and Python scheduler for internal API calls
```

```bash
git add .env.example  # only if it exists
git commit -m "docs: document INTERNAL_API_KEY env var"
```

---

## Part 2: Layout Stability

### Task 6: Remove Premature renderedView Clears from Visibility and Tab Handlers

**Files:**
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx:655-690`

- [ ] **Step 1: Fix the visibility handler (lines 655-679)**

Replace the `handleVisibility` else-if block so it no longer clears renderedView/renderedOverview/laneOverview. Change from:

```typescript
      } else if (hiddenAt && Date.now() - hiddenAt > IDLE_THRESHOLD_MS) {
        hiddenAt = null;
        invalidateCache('/api/pipeline/');
        setRenderedView(null);
        setRenderedOverview(null);
        setLaneOverview(null);
        if (stackId) {
          fetchLineage();
          if (activeTab === 'control-plane') fetchControlPlane();
        }
```

To:

```typescript
      } else if (hiddenAt && Date.now() - hiddenAt > IDLE_THRESHOLD_MS) {
        hiddenAt = null;
        invalidateCache('/api/pipeline/');
        // Don't clear renderedView — keep previous layout visible until fresh data arrives
        if (stackId) {
          fetchLineage();
          if (activeTab === 'control-plane') fetchControlPlane();
        }
```

- [ ] **Step 2: Fix the tab change handler (lines 682-690)**

Replace `handleTabChange` so it no longer clears renderedView and lineageData. Change from:

```typescript
  const handleTabChange = useCallback((tab: 'data' | 'control-plane') => {
    setActiveTab(tab);
    setSelectedNode(null);
    setSelectedEdge(null);
    setLineageData(null); // Clear stale data to prevent wrong-layout flash
    setRenderedView(null);
    setRenderedOverview(null);
    setLaneOverview(null);
  }, []);
```

To:

```typescript
  const handleTabChange = useCallback((tab: 'data' | 'control-plane') => {
    setActiveTab(tab);
    setSelectedNode(null);
    setSelectedEdge(null);
    // Don't clear renderedView/lineageData — activeTab controls which nodes render,
    // and fetchLineage triggered by the stackId/activeTab effect atomically replaces data
  }, []);
```

- [ ] **Step 3: Verify tab switch and visibility don't cause jitter**

Start the dev server. Navigate to the lineage page.
1. Switch between "Data Lineage" and "Pipeline Overview" tabs — the graph should NOT flash/jitter to scattered positions.
2. Switch to another browser tab, wait >2 minutes, switch back — the graph should hold its previous positions until fresh data loads.

- [ ] **Step 4: Commit**

```bash
git add "app/(dashboard)/dashboard/lineage/page.tsx"
git commit -m "fix: remove premature renderedView clears from visibility and tab handlers"
```

---

### Task 7: Add Loading Guard to useMemo for Pipeline Switch

**Files:**
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx:626-642, 1011-1211`

- [ ] **Step 1: Batch the clear + loading state in the stackId change effect**

The existing `useEffect` at line 626 already clears `renderedView(null)` on stack change (correct — different stack = different graph). Ensure `setLoading(true)` is called in the same synchronous batch. The current code calls `fetchLineage()` which sets `setLoading(true)` internally (line 372), but there's a gap between the `setRenderedView(null)` and the `fetchLineage()` call where React could render. Fix this by adding an explicit `setLoading(true)` right after the clears:

Change lines 626-642 from:

```typescript
  useEffect(() => {
    if (stackId !== prevStackIdRef.current) {
      prevStackIdRef.current = stackId;
      // Reset all state so previous pipeline's data doesn't persist
      setLineageData(null);
      setRenderedView(null);
      setRenderedOverview(null);
      setLaneOverview(null);
      setControlPlaneData(null);
      setSelectedNode(null);
      setSelectedEdge(null);
      setError(null);
      setActiveRunId(null);
      setLlmProgress([]);
      setLlmNodeCount(0);
      setLlmEdgeCount(0);
    }
```

To:

```typescript
  useEffect(() => {
    if (stackId !== prevStackIdRef.current) {
      prevStackIdRef.current = stackId;
      // Reset all state so previous pipeline's data doesn't persist
      setLineageData(null);
      setRenderedView(null);
      setRenderedOverview(null);
      setLaneOverview(null);
      setControlPlaneData(null);
      setSelectedNode(null);
      setSelectedEdge(null);
      setError(null);
      setActiveRunId(null);
      setLlmProgress([]);
      setLlmNodeCount(0);
      setLlmEdgeCount(0);
      // Set loading in same batch so React shows spinner, not dagre flash
      setLoading(true);
    }
```

- [ ] **Step 2: Add loading guard to the useMemo**

At the very top of the useMemo (line 1011), add an early return when loading is true and there's no renderedView. This prevents dagre from running on stale data during pipeline switch transitions:

Change lines 1011-1013 from:

```typescript
  const { flowNodes, flowEdges } = useMemo(() => {
    // Rendered view path: use backend-computed positions
    if (renderedView && renderedView.nodes.length > 0) {
```

To:

```typescript
  const { flowNodes, flowEdges } = useMemo(() => {
    // During pipeline switch: renderedView is null + loading is true → show spinner, not dagre
    if (loading && !renderedView && !lineageData) {
      return { flowNodes: [], flowEdges: [] };
    }

    // Rendered view path: use backend-computed positions
    if (renderedView && renderedView.nodes.length > 0) {
```

Add `loading` to the dependency array at line 1211:

```typescript
  }, [filteredNodes, lineageData?.edges, lineageData?.nodes, filters, renderedView, slaMode, slaSelectedNodeIds, nodeSLAs, loading]);
```

- [ ] **Step 3: Verify pipeline switch shows loading spinner instead of dagre flash**

Start the dev server. Navigate to the lineage page. Switch to a different pipeline profile using the pipeline selector dropdown. Expected: a loading spinner appears — NOT a flash of scattered dagre nodes before the correct layout loads.

Also verify: first-time users (no rendered view yet, no lineage data) still get a dagre layout after data loads, not a permanent empty screen.

- [ ] **Step 4: Commit**

```bash
git add "app/(dashboard)/dashboard/lineage/page.tsx"
git commit -m "fix: show loading spinner on pipeline switch instead of dagre layout flash"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] Manual "Build Lineage" sets `lineageExtractionEnabled = true` and `lastLineageExtractedAt` on the PipelineStack
- [ ] The internal endpoint at `/api/pipeline/[stackId]/lineage/scheduled` rejects requests without valid `INTERNAL_API_KEY`
- [ ] The Python scheduler logs `[Scheduler] Lineage extraction due` for stacks with `lastLineageExtractedAt` > 6h ago
- [ ] Tab switch (Data Lineage ↔ Pipeline Overview) doesn't cause layout jitter
- [ ] Pipeline profile switch shows loading spinner, not scattered dagre layout
- [ ] Returning from background (>2min idle) keeps previous layout until fresh data loads
- [ ] First-time users (no rendered view) still get a dagre layout without errors
