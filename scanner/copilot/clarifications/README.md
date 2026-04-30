# Clarification layer — smoke test (V1.0, Plan 1)

## Prerequisites

1. Apply the Prisma migration:
   ```bash
   npx prisma migrate dev --name add_clarification_models
   ```
2. Restart FastAPI and Next.js dev servers.

## Manual flow

1. Open the dashboard.
2. Pick a node whose timestamp columns are ambiguous (or seed one in the dev DB).
3. Click **Discover from data**.
4. Observe the volume section showing a `awaiting clarification` tag and a dotted-underlined value; the LLM-bell shows a `1` badge.
5. Click the LLM-bell. Popup opens with the LLM's question loaded.
6. Type a column name (e.g., `loaded_at`). LLM confirms and calls `record_clarification_answer`.
7. Tag clears; bell badge drops to 0.
8. Click "Discover from data" again — runs without popup (convention applied).

## Backend-only verification (no UI)

1. POST to `/api/context-requests/create` with a synthetic payload to verify dedupe + dismiss-suppression.
2. POST to `/api/clarifications/resolve` to verify the write path persists conventions + overrides.

## Known limitations

- Re-run after resolve is currently a no-op stub; the user re-clicks "Discover" to see the updated result.
- Sweep / borderline failures / completeness UI are deferred to Plans 2-3.

## Plan 2 (V1.1) — Borderline failures

### Manual flow

1. Trigger a volume monitor with crafted history producing a z-score in the borderline band (default: 1.5σ ≤ |z| < threshold). Easiest: edit a test fixture or seed the dev DB with rows that produce a small dip.
2. Run the monitor. The LLM-bell badge increments.
3. Open the popup. The `BorderlineFailureCard` renders at the top with two chips.
4. Click "Expected — dampen". Toast confirms; bell badge decrements.
5. Re-run with the same data → classified as `clear` because the dampening rule bumped the threshold.

### Investigate path

1. Trigger another borderline.
2. Click "Investigate". Browser routes to `/dashboard/copilot?mode=debug&node=...&metric=...`. Debug-mode chat opens with the failure context.

### Known limitations (V1.1)

- Borderline detection wired to volume monitor only in V1.1; freshness/quality monitors will be wired incrementally as they're confirmed to use z-scores.
- Dampening rules are stored in `PipelineContext.conventionsContext.dampening.rules` but are not yet read by the monitor evaluation path. V1.2 will close this loop (read on next eval).
