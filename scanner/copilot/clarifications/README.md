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
