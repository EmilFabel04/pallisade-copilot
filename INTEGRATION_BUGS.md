# Integration & Credentials Bug Fix Instructions

> **Purpose**: This document gives a fresh Claude Code session 100% context to fix three interconnected bugs in the Pallisade Copilot integration/credentials system. Read fully before coding.

---

## Architecture Overview

**Stack**: Next.js 15 frontend → FastAPI backend (`scanner/`) → LLM (Claude/GPT) with tool calling

**Integration storage is dual-layered**:
1. **`Integration` table** (modern, org-scoped): `prisma/schema.prisma` lines 1788-1846
   - `credentials Json?` — encrypted warehouse creds (BigQuery, Snowflake, etc.)
   - `accessToken String?` — encrypted OAuth tokens (GitHub, Slack, Jira)
   - `metadata Json?` — discovered data (repo lists, table inventories)
   - Unique constraint: `@@unique([organizationId, type, name])`

2. **`PipelineNode` table** (legacy, pipeline-scoped): `prisma/schema.prisma` lines 380-434
   - `config Json?` — was the original credential store, now holds only `{ _cached }` metadata
   - `integrationId String?` — FK to Integration table (modern approach)

**Two credential entry points**:
- **Pipeline page** (`/dashboard/pipeline`): User adds warehouse/tool nodes → `POST /api/pipeline` → `upsertNodeIntegration()` encrypts creds into `Integration.credentials`
- **Settings page** (`/dashboard/settings`): User connects OAuth apps → OAuth callback encrypts token into `Integration.accessToken`

**Credential resolution for copilot**: `lib/integration-credentials.ts` → `resolveStackIntegrations()` reads from both Integration.credentials (pipeline) and Integration.accessToken (OAuth), merges them, passes to FastAPI.

---

## Bug 1: BigQuery "no configuration"

### Symptom
```
[NODE DATA] Node cmmd8ofd8000gqqg6oma6hxap (bigquery) has no configuration
```
Node has valid credentials in the Integration table but the tables endpoint says "no configuration".

### Root Cause
**File**: `app/api/pipeline/[stackId]/nodes/[nodeId]/tables/route.ts`, **line 83**

```typescript
if (!node.config || Object.keys(credentials).length === 0) {
```

When credentials are saved via the modern pipeline flow:
1. `upsertNodeIntegration()` stores creds in `Integration.credentials` (encrypted)
2. `PipelineNode.config` is set to `Prisma.JsonNull` or `{ _cached: ... }` (creds are CLEARED from node)
3. `PipelineNode.integrationId` is set to the Integration record ID

The tables endpoint correctly loads credentials from `Integration.credentials` (lines 57-67). BUT the check on line 83 tests `!node.config` FIRST, which is truthy (null/empty) for ALL modern nodes. This short-circuits before evaluating whether credentials were actually loaded.

### Fix
**File**: `app/api/pipeline/[stackId]/nodes/[nodeId]/tables/route.ts`, **line 83**

Change:
```typescript
if (!node.config || Object.keys(credentials).length === 0) {
```
To:
```typescript
if (Object.keys(credentials).length === 0) {
```

That's it. The `credentials` variable already captures whether any credentials were successfully decrypted from either source (Integration table or legacy node.config). The `!node.config` check is a legacy artifact.

### Verification
After the fix, hitting `GET /api/pipeline/{stackId}/nodes/{nodeId}/tables` for a BigQuery node that has `integrationId` set (but `config` is null) should return tables instead of the "no configuration" message.

---

## Bug 2: GitHub Token "Invalid or Expired" (freshly regenerated)

### Symptom
```
Failed to create PR: GitHub token is invalid or expired. Please reconnect GitHub in Settings > Integrations.
```
Happens even after user freshly re-authenticates GitHub OAuth.

### Root Cause
The `apply-plan/route.ts` has its **own independent token lookup** that doesn't use `resolveStackIntegrations()`. It checks TWO places in sequence:

**File**: `app/api/copilot/apply-plan/route.ts`

1. **Lines 38-53**: Checks `Integration.accessToken` (the OAuth field)
2. **Lines 56-75**: Falls back to `PipelineNode.config` (the legacy field)

**The problem**: If the user configured GitHub through the **pipeline page** (not OAuth), the token is stored in `Integration.credentials` (encrypted JSON), NOT in `Integration.accessToken`. The apply-plan route never checks `Integration.credentials` for GitHub tokens.

Additionally, when a user re-authenticates via OAuth:
- New token goes to `Integration.accessToken` on the Integration record with `type: 'GITHUB', name: 'GitHub'`
- BUT if there's a separate PipelineNode-linked Integration record for GitHub (with a different name), the OAuth callback updates the FIRST one found (line 107-112 of `callback/route.ts` uses `findFirst` by type only)
- The apply-plan route's `findFirst` also just matches `type: 'GITHUB'` — it might find the wrong record

There's also a merge issue in `resolveStackIntegrations()` (line 331-346 of `lib/integration-credentials.ts`): if a pipeline node already has a GITHUB type integration, the OAuth `accessToken` gets merged into its config. But apply-plan doesn't use this merged result.

### Fix
**File**: `app/api/copilot/apply-plan/route.ts`

Replace the current two-step token lookup (lines 34-82) with a call to `resolveStackIntegrations()` which already handles all merging correctly. Extract the GitHub token from the resolved integrations list.

```typescript
// ── 1. Find the GitHub token ──────────────────────────────────
import { resolveStackIntegrations } from '@/lib/integration-credentials';

// Find the user's pipeline stack for resolving integrations
const pipelineStack = await prisma.pipelineStack.findFirst({
  where: { organizationId: user.organizationId },
  select: { id: true },
});

const integrations = await resolveStackIntegrations(
  pipelineStack?.id || null,
  user.organizationId,
);

let accessToken = '';
const githubIntegration = integrations.find(i => i.type === 'GITHUB');
if (githubIntegration?.config) {
  accessToken = githubIntegration.config.access_token
    || githubIntegration.config.token
    || '';
}

if (!accessToken) {
  return NextResponse.json(
    { error: 'GitHub is not connected. Please connect GitHub in Settings > Integrations.' },
    { status: 400 },
  );
}
```

Also update the repo resolution to use the same integration's metadata instead of doing a separate lookup.

Keep the token validation block (lines 85-110) as-is — it's a good pre-check.

### Additional Fix: OAuth Callback Dedup
**File**: `app/api/integrations/oauth/github/callback/route.ts`, **lines 107-112**

The `findFirst` lookup should also match by name to avoid updating the wrong record:
```typescript
const existingIntegration = await prisma.integration.findFirst({
  where: {
    organizationId,
    type: 'GITHUB',
    name: 'GitHub',  // Add name filter to match the record we're creating
  },
});
```

### Verification
1. Connect GitHub via OAuth in Settings
2. Go to copilot, create a change plan, apply it
3. Should use the fresh OAuth token, not a stale pipeline token
4. Also test: connect GitHub via pipeline config → apply plan should still work

---

## Bug 3: Integration Save Failures & Pipeline-Settings Conflicts

### Symptom
- "Failed to save integration" toast in the pipeline editor
- Can't change GitHub integration in Settings because it's configured in Pipeline
- Credentials from one pipeline overwriting another's

### Root Causes (multiple)

#### 3a. Silent P2002 errors in pipeline save
**File**: `app/api/pipeline/route.ts`, **lines 96-99**

```typescript
} catch (e) {
  console.error(`[PIPELINE] Failed to upsert Integration for ${integrationType}:`, e);
  return null;  // Silent failure!
}
```

`upsertNodeIntegration()` returns `null` on any error (including Prisma unique constraint violations P2002). The pipeline save continues, but the node has no `integrationId` → credentials lost. The outer catch (lines 492-495) returns a generic "Failed to save pipeline" with no detail.

**Fix**: Propagate meaningful errors from `upsertNodeIntegration()` and handle P2002 specifically:

```typescript
} catch (e: any) {
  if (e.code === 'P2002') {
    console.error(`[PIPELINE] Integration name conflict for ${integrationType}: ${node.name}`);
    throw new Error(`An integration named "${node.name}" (${integrationType}) already exists. Please use a different name.`);
  }
  console.error(`[PIPELINE] Failed to upsert Integration for ${integrationType}:`, e);
  throw e;  // Don't swallow the error
}
```

And in the outer handler (lines 492-495), return the error message to the frontend:
```typescript
} catch (error: any) {
  console.error('Failed to save pipeline:', error);
  return NextResponse.json(
    { error: error.message || 'Failed to save pipeline' },
    { status: 500 },
  );
}
```

#### 3b. Cross-pipeline credential overwriting
**Problem**: Integration records are unique by `(organizationId, type, name)`. If Pipeline A and Pipeline B both have a node named "BigQuery" of type BIGQUERY, they share the SAME Integration record. Saving Pipeline B overwrites Pipeline A's credentials.

**Fix (two options)**:
- **Option A (simple)**: Include `stackId` in the upsert name to disambiguate: `name: "${node.name} (${stackName})"`. This is a quick fix but changes display names.
- **Option B (proper)**: Add a `pipelineStackId` column to the Integration unique constraint so each pipeline gets its own copy. This requires a schema migration.

Recommended: **Option A** for now, with a follow-up task for Option B.

#### 3c. Settings page can't edit pipeline-owned integrations
**Problem**: The Settings page shows GitHub (from OAuth) and the Pipeline page shows GitHub (from pipeline config). They may be the same Integration record or different ones. If the user tries to edit in Settings but the Integration is "owned" by a pipeline, there's no clear error.

**Fix**: In the Settings page integration list, if an integration has `pipelineNodes` relations, show a badge saying "Managed by Pipeline" and disable the edit/disconnect buttons with a tooltip: "This integration is managed by your pipeline. Edit it there."

**File**: `app/(dashboard)/dashboard/settings/page.tsx` — add check in the integrations tab (around line 273-384).

**File**: `app/api/integrations/route.ts` — include `pipelineNodes: { select: { id: true } }` in the GET query to expose whether it's pipeline-managed.

---

## File Reference

| File | What to change |
|------|---------------|
| `app/api/pipeline/[stackId]/nodes/[nodeId]/tables/route.ts:83` | Remove `!node.config \|\|` from config check |
| `app/api/copilot/apply-plan/route.ts:34-82` | Replace dual lookup with `resolveStackIntegrations()` |
| `app/api/integrations/oauth/github/callback/route.ts:107-112` | Add `name: 'GitHub'` to findFirst |
| `app/api/pipeline/route.ts:96-99` | Propagate errors from upsertNodeIntegration |
| `app/api/pipeline/route.ts:492-495` | Return error.message instead of generic string |
| `lib/integration-credentials.ts:303-364` | No changes needed — already correct |
| `app/(dashboard)/dashboard/settings/page.tsx:273-384` | Show "Managed by Pipeline" badge |
| `app/api/integrations/route.ts` | Include pipelineNodes in GET response |

## Testing Checklist

1. **BigQuery config**: Save BigQuery in pipeline → GET tables endpoint → should return tables (not "no configuration")
2. **GitHub token (OAuth)**: Connect GitHub in Settings → create change plan in copilot → apply → PR should be created
3. **GitHub token (Pipeline)**: Configure GitHub in pipeline config → apply change plan → should work
4. **Token refresh**: Re-authenticate GitHub OAuth → apply plan → should use new token
5. **Pipeline save errors**: Try saving with a duplicate integration name → should show specific error, not generic "Failed to save"
6. **Cross-pipeline isolation**: Two pipelines with same-type nodes → credentials should not overwrite each other
7. **Settings vs Pipeline**: Integration shown in Settings should indicate if pipeline-managed

## Key Crypto Detail

Encryption: AES-256-GCM in `lib/crypto.ts`. Uses `ENCRYPTION_KEY` env var (or dev fallback). The warning `"Using development encryption key"` in logs means production key is not set — this is fine for local dev but critical for production.

Two encryption patterns in the codebase:
- `Integration.accessToken` = `encrypt(rawToken)` (simple string encryption)
- `Integration.credentials` = `{ encrypted: encrypt(JSON.stringify(credsObject)) }` (JSON-wrapped)

Both use the same `encrypt()`/`decrypt()` from `lib/crypto.ts`. The pattern difference is important when reading credentials.
