# Scheduled Lineage Extraction & Layout Stability

**Date:** 2026-04-12
**Status:** Approved

## Overview

Two related improvements to the lineage system:

1. **Scheduled Extraction** — Every pipeline stack automatically re-extracts lineage every 6 hours after the user's first manual "Build Lineage" click. Manual builds reset the timer.
2. **Layout Stability** — Eliminate the visual jitter where the graph bounces between scattered (dagre-computed) and correct (server-positioned) layouts during state transitions.

---

## Part 1: Scheduled Lineage Extraction

### Behavior

- Every `PipelineStack` gets automatic 6-hour extraction cycles.
- The schedule begins when the user first clicks "Build Lineage" manually.
- Every subsequent manual build resets the 6-hour timer from that point.
- No user-facing configuration UI — this is a platform standard, always-on once the first manual build happens.
- If auto-extraction fails, log the error and skip. Next attempt in 6 hours. No retry loop.

### Data Model

Add two fields to `PipelineStack` in `prisma/schema.prisma`:

```prisma
lastLineageExtractedAt   DateTime?
lineageExtractionEnabled Boolean   @default(false)
```

No new tables. The scheduler checks: for each stack where `lineageExtractionEnabled = true` and `now - lastLineageExtractedAt >= 6 hours`, trigger extraction.

### Execution Path

**Internal API endpoint (Next.js):**

New route: `POST /api/pipeline/[stackId]/lineage/scheduled`

This is functionally identical to the existing `POST /api/pipeline/[stackId]/lineage/route.ts` handler (resolves all connected pipeline nodes, decrypts credentials, builds `tool_configs`, calls Python `POST /api/v1/lineage/investigate-llm`, persists results to `LineageNode`/`LineageEdge`/`LineageSnapshot` via Prisma). The only difference:

- Authenticates via `INTERNAL_API_KEY` header (env var) instead of a user session.
- Sets `lastLineageExtractedAt = now` and `lineageExtractionEnabled = true` on the `PipelineStack` after successful extraction.
- Returns a summary (node count, edge count, duration) for logging.

**Manual build wiring:**

The existing "Build Lineage" POST handler (`app/api/pipeline/[stackId]/lineage/route.ts`) also sets `lastLineageExtractedAt = now` and `lineageExtractionEnabled = true` after successful extraction. This ensures manual builds reset the 6-hour timer.

**Python scheduler addition:**

In `scanner/scheduler/service.py`, add a separate periodic check that runs alongside the existing monitor loop. Every 60 seconds (piggybacks on the existing `_loop` tick):

1. Query `PipelineStack` for rows where `lineageExtractionEnabled = true` AND `lastLineageExtractedAt <= now - 6 hours` (or `lastLineageExtractedAt IS NULL` as a safety fallback).
2. For each due stack, call `POST http://localhost:3000/api/pipeline/{stackId}/lineage/scheduled` with the `INTERNAL_API_KEY` header.
3. Log the result (success/failure, node count, duration).
4. On failure: log warning, do not retry. The next cycle (6h later) will try again.

The scheduler does NOT update `lastLineageExtractedAt` — the Next.js endpoint handles that after successful persistence. This prevents marking a stack as extracted when the extraction actually failed.

### Environment Variable

```
INTERNAL_API_KEY=<random-secret>
```

Both the Next.js endpoint (to verify) and the Python scheduler (to send) read this variable. In development, a hardcoded fallback is acceptable.

### Timer Reset Semantics

Both manual and auto extraction set `lastLineageExtractedAt = now` on the `PipelineStack`. Clicking "Build Lineage" at 14:00 means the next auto-extraction fires at 20:00, not the original schedule. The scheduler's interval check (`now - lastLineageExtractedAt >= 6h`) naturally handles this without cron parsing.

---

## Part 2: Layout Stability Fix

### Root Cause

The `useMemo` in `lineage/page.tsx` (line ~982) that computes graph positions has two paths:

- **Path A** (`renderedView` set): Uses pre-positioned server coordinates — correct layout.
- **Path B** (`renderedView` null): Runs dagre from scratch — different, scattered positions.

Whenever `setRenderedView(null)` is called (tab switch, visibility wake, pipeline switch), the layout immediately jumps to dagre positions. Then when fresh `renderedView` data arrives moments later, it snaps back. This null→dagre→renderedView cycle is the visible bounce.

### Fix: Atomic Replacement

Keep the previous `renderedView` visible until new data atomically replaces it. No intermediate null state.

**1. Visibility handler (`useEffect` with `visibilitychange`):**

Remove the `setRenderedView(null)`, `setRenderedOverview(null)`, `setLaneOverview(null)` calls. Just invalidate the cache and re-fetch. When fresh data arrives, `setRenderedView(newData)` atomically replaces the old view.

**2. `fetchLineage()` function:**

Do not clear `renderedView` at the start of the fetch. The fetch version guard (`fetchVersionRef`) already prevents stale responses from overwriting newer data. When the new renderedView arrives from the API, it replaces the old one in a single `setRenderedView(viewData)` call.

**3. Tab switch (`handleTabChange`):**

Currently clears `lineageData` and `renderedView` to "prevent wrong-layout flash." Remove these clears. The tab content switches via `activeTab` which changes which flow nodes are rendered (`activeFlowNodes` selects between data-plane and control-plane), so stale data from the previous tab isn't visible during the transition. The re-fetch triggered by the `useEffect` dependency on `activeTab` will atomically replace the data.

**4. Pipeline switch (stack change):**

This IS the one case where clearing is correct — different stack means a completely different graph. But instead of clearing and showing a dagre fallback, keep the loading state handling: if `renderedView` is null AND `loading` is true, the existing loading spinner shows. The fix is to ensure the clear + loading state are set together so the spinner appears instead of a dagre flash.

In the `useEffect` that handles `stackId` changes (line ~626): keep the `setRenderedView(null)` call here (it's correct to clear for a different stack), but ensure `setLoading(true)` is called in the same synchronous batch so React renders the loading spinner, not the dagre fallback. The `useMemo` should also early-return empty arrays when `loading` is true, preventing dagre from running on stale data during the transition.

### Result

- No more scattered→normal bounce during normal use.
- Tab switches keep the previous layout visible until fresh data loads.
- Pipeline switches show a loading spinner instead of a dagre flash.
- Overnight wake keeps the previous layout visible until fresh data replaces it.
- The dagre fallback path still works for stacks that have never had a rendered view (first-time users before any "Build Lineage" click).

---

## Files to Modify

### Scheduled Extraction

| File | Change |
|------|--------|
| `prisma/schema.prisma` | Add `lastLineageExtractedAt` and `lineageExtractionEnabled` to `PipelineStack` |
| `app/api/pipeline/[stackId]/lineage/scheduled/route.ts` | New internal-only extraction endpoint |
| `app/api/pipeline/[stackId]/lineage/route.ts` | Set `lastLineageExtractedAt` and `lineageExtractionEnabled` after manual build |
| `scanner/scheduler/service.py` | Add lineage extraction check to scheduler loop |

### Layout Stability

| File | Change |
|------|--------|
| `app/(dashboard)/dashboard/lineage/page.tsx` | Remove `setRenderedView(null)` from visibility handler and tab switch; add loading guard to useMemo |

---

## Testing

### Scheduled Extraction

- Verify manual "Build Lineage" sets `lastLineageExtractedAt` and `lineageExtractionEnabled = true`.
- Verify the scheduler picks up due stacks and calls the internal endpoint.
- Verify the internal endpoint rejects requests without a valid `INTERNAL_API_KEY`.
- Verify a second manual build resets the timer (next auto-extraction is 6h from the new build, not the old one).
- Verify failed auto-extraction logs a warning and doesn't block the next cycle.

### Layout Stability

- Verify tab switch (Data Lineage ↔ Pipeline Overview) doesn't cause layout jitter.
- Verify pipeline profile switch shows loading spinner, not scattered dagre layout.
- Verify leaving the tab in background for >2 minutes and returning shows the previous layout until fresh data loads.
- Verify first-time users (no rendered view yet) still get a dagre layout without errors.
