# Agentic Artefacts — Design

**Date:** 2026-05-13
**Status:** Draft, pending implementation plan
**Scope:** Replace the current chat-snippet `Artifact` model with a typed, polymorphic artefact system that represents every concrete thing the agent can produce or modify across Pallisade's integration surfaces. Ship Group A (PR-flow-backed kinds) and a Group B Monitor write slice in v1.

---

## 1. Summary

Today, `/dashboard/artifacts` is a library of saved AI chat-message text. The `Artifact` model stores `title + content + flat type (QUERY/FIX/INSIGHT/CODE/PLAN)`. Nothing the agent *actually does* — open a PR, run a query, create a monitor — lands on this page. The only end-to-end write path the agent has today is `create_change_plan` → GitHub PR; that capability does not flow into the artefacts page.

This design replaces that with a **typed artefact model** where every artefact represents a real deliverable (PR, monitor, schema change, DAG, connector, ticket, document, etc.), is produced by an agent tool call, and is the durable, resumable record of that work. Each artefact carries its own agent session so the user can pause mid-creation and resume later from `/dashboard/artifacts/[id]`.

The v1 cut delivers the data model + UX shell + Group A (PR-flow-backed kinds) + a Group B write slice on internal Monitors. All other kinds have their schema and payload contracts defined but no write tool yet — they are unlocked in subsequent specs without further model changes.

## 2. Goals

- Make the `/artifacts` page the durable home for **everything the agent has built or proposed**, not just text bookmarks.
- Establish one **polymorphic artefact model** that scales to every Pallisade integration surface without table-per-kind sprawl.
- Make every agent write tool emit an artefact automatically via a single executor helper — no per-tool wiring of persistence.
- Make artefacts **resumable**: every artefact owns an agent session, so the user can pause at any step and pick up later.
- Ship a real Group B write slice (Monitors) end-to-end to validate the pattern before fanning out.

## 3. Non-goals

- New page/route structure beyond `/dashboard/artifacts/[id]` (no Workshop page).
- MCP host capability (deferred to a separate spec).
- Write tools for any Group B kind other than Monitor in v1 (other kinds get schema only).
- Migration of existing artefact rows (nuke approved — see §10).
- Scout → Agent rename (separate spec).
- Changes to `ChangePlan`, `apply_change_plan`, or `ToolConfirmation` mechanics — these are reused as-is.

## 4. Background

### 4.1 Current state — what exists

**Backend (`scanner/copilot/`):**

- ~80 registered tools across `dbt`, `warehouse`, `ingestion`, `orchestration`, `infrastructure`, `storage`, `lineage`, `observability`, `github`, `reporting`, `coverage`, `knowledge`, `clarifications`, `onboarding`, `actions`. Almost all are read-only.
- Write tools that exist: `create_change_plan`, `validate_change_plan`, `apply_change_plan`, `create_watch`, `run_watch`, `complete_onboarding`, `save_onboarding_context`, `record_clarification_answer`, `annotate_integration_health`.
- ChangePlan system (`scanner/copilot/change_plan/`) handles file-patch-based changes end-to-end: validates statically/in CI/in sandbox, creates a branch, opens a real PR, returns `pr_url`/`pr_number`. Status lifecycle: `draft → validating → validated → applying → applied | failed | rejected`.
- Drivers exist for ~40 external systems (`scanner/drivers/`) across warehouse, transformation, ingestion, storage, VCS, reporting/BI, ticketing, notifications, infrastructure. Most are read-only at the tool layer even though the underlying drivers can write.

**Frontend (`components/copilot/change-plan/`):**

- `ChangePlanCard`, `ChangePlanToolResult`, `PRCard`, `SharePlanModal`, `ToolConfirmation` are all built and rendered inline in the assistant chat.

**Data model (`prisma/schema.prisma:1972`):**

```prisma
model Artifact {
  id              String          @id @default(cuid())
  title           String
  content         String          @db.Text
  type            ArtifactType    // QUERY/FIX/INSIGHT/CODE/PLAN
  tags            String[]
  sourceSessionId String?
  sourceMessageId String?
  metadata        Json?
  isPinned        Boolean         @default(false)
  ...
}
```

Created via `app/api/artifacts/route.ts` (POST), triggered by `SaveArtifactModal` in the assistant page when the user clicks "Save to artefacts" on a chat message. The content is the raw markdown of that message.

### 4.2 The gap

Three structural problems:

1. **No typed deliverables.** `Artifact.content` is text. A PR, a monitor, a query result, and a DAG diff cannot share a flat-text model without losing all structure and renderability.
2. **No agent-write tools beyond PR.** The agent has read-everywhere and write-only-to-GitHub-via-ChangePlan. Connector creation, monitor creation, DDL execution, DAG edits, ticket filing, BI refreshes — none exist as agent tools, even where the underlying driver supports them.
3. **No artefact resumability.** Even ChangePlans, the one thing the agent can build, don't persist as artefacts. There is no "I started a monitor proposal yesterday, let me continue."

## 5. Data model

### 5.1 New `Artifact` model

Single polymorphic table. Replace the existing model in `prisma/schema.prisma`:

```prisma
model Artifact {
  id      String @id @default(cuid())

  kind    ArtifactKind
  subtype String?           // e.g. "snowflake", "airflow", "fivetran"; nullable for kinds without a subtype
  status  ArtifactStatus

  // Sessions
  sourceSessionId String?
  sourceMessageId String?
  sourceSession   CopilotSession? @relation("ArtifactSource", fields: [sourceSessionId], references: [id], onDelete: SetNull)
  agentSessionId  String?         @unique
  agentSession    CopilotSession? @relation("ArtifactAgent", fields: [agentSessionId], references: [id], onDelete: SetNull)

  // Tool-call provenance
  toolCallId      String?
  idempotencyKey  String?
  agentRunId      String?

  // Integration binding
  integrationId   String?
  integration     Integration? @relation(fields: [integrationId], references: [id], onDelete: SetNull)

  // External system reference
  externalRef     Json?       // { pr_url, pr_number, branch, monitor_id, dag_id, ticket_url, ... }

  // Typed payload (validated in app layer per kind)
  payload         Json

  // Display
  title           String
  summary         String?
  riskLevel       ArtifactRisk?
  rollbackHint    String?

  tags            String[]
  isPinned        Boolean   @default(false)
  isSaved         Boolean   @default(false)   // true once user clicks "Save to artefacts" or status advances past `draft`
  metadata        Json?

  createdAt       DateTime  @default(now())
  updatedAt       DateTime  @updatedAt
  appliedAt       DateTime?

  user            User         @relation(fields: [userId], references: [id], onDelete: Cascade)
  userId          String
  organization    Organization @relation(fields: [organizationId], references: [id], onDelete: Cascade)
  organizationId  String

  @@index([userId])
  @@index([organizationId])
  @@index([kind])
  @@index([kind, status])
  @@index([organizationId, isSaved, status, createdAt])  // primary /artefacts list query
  @@index([sourceSessionId])
  @@index([agentRunId])
  @@unique([idempotencyKey, organizationId])
}

enum ArtifactKind {
  PR_CHANGE
  WAREHOUSE_QUERY
  SCHEMA_CHANGE
  DBT_CORE_CHANGE
  DBT_CLOUD_CHANGE
  DAG
  INGESTION_CONNECTOR
  MONITOR
  WATCH
  INCIDENT
  TICKET
  NOTIFICATION_RULE
  BI_ASSET
  STORAGE_OBJECT
  SERVER_ACTION
  DOCUMENT
}

enum ArtifactStatus {
  draft
  proposed
  approved
  applied
  rejected
  failed
  archived
  open
  resolved
}

enum ArtifactRisk {
  LOW
  MEDIUM
  HIGH
}
```

Removed from previous schema: `type ArtifactType`, `content String`, and the `ArtifactType` enum itself. All gone — see §10 (nuke migration).

### 5.2 Visibility: `isSaved` reconciles transient chat-cards with the /artefacts page

The artefact row exists in DB the moment `begin_artefact` fires (needed to hold the `agentSessionId` and let the chat card render with a stable id). But not every transient artefact card should clutter `/artefacts` — a user might start configuring a monitor, change their mind, and never apply it.

Rule: an artefact is **visible on /artefacts iff** `isSaved = true` OR `status ∈ {proposed, approved, applied, rejected, failed, open, resolved}`. In other words: rows in `draft` are hidden until the user explicitly clicks "Save to artefacts" (which flips `isSaved`) or the agent advances the status. Once visible, always visible (until archived).

`POST /api/artifacts/[id]/save-snapshot` (§9) is the endpoint that flips `isSaved=true`. Idempotent.

### 5.3 Sessions: two fields with different meaning

- `sourceSessionId`: the **parent chat** the artefact was born inside. Provenance only. Many artefacts can share a `sourceSessionId`.
- `agentSessionId`: the **artefact's own agent session**. One-to-one. This is the session that powers "Continue" on the artefacts page — the agent runtime can be rehydrated from this session's transcript and tool history to keep working on this artefact specifically.

When the agent decides to produce an artefact in the parent chat, the executor creates a child `CopilotSession` for that artefact, seeded with the relevant slice of parent-chat context (the goal, the affected assets, the agent's plan). The artefact card renders in the parent chat, but its state lives in the child session.

### 5.4 Per-kind payload contracts

Mirrored in TS (`types/artifact.ts`, discriminated union) and Pydantic (`scanner/copilot/artifacts/models.py`). Examples for the kinds we touch in v1:

```ts
type ArtifactPayload =
  | { kind: 'PR_CHANGE'; changePlanId: string; filesChanged: number; diffSummary: string;
      validationResults: Record<ValidationLevel, ValidationStatus> }
  | { kind: 'WAREHOUSE_QUERY'; sql: string; rowCount?: number; executionMs?: number;
      resultPreview?: unknown[]; error?: string }
  | { kind: 'SCHEMA_CHANGE'; ddl: string; affectedTables: string[]; reversible: boolean }
  | { kind: 'DBT_CORE_CHANGE'; modelsTouched: string[]; testsAdded: string[]; changePlanId?: string }
  | { kind: 'DBT_CLOUD_CHANGE'; projectId: string; jobId?: string; environmentId?: string;
      operation: 'job_edit'|'env_update'|'deploy'|'run_trigger' }
  | { kind: 'DAG'; dagId: string; operation: 'create'|'edit'|'pause'|'resume'|'trigger'|'clear';
      affectedTasks: string[] }
  | { kind: 'INGESTION_CONNECTOR'; connectorId: string;
      operation: 'create'|'edit'|'pause'|'resume'|'trigger_sync'; configDiff?: Record<string,unknown> }
  | { kind: 'MONITOR'; monitorId: string; monitorKind: MonitorKind; targetFqn?: string;
      configDiff?: Record<string,unknown> }
  | { kind: 'WATCH'; watchId: string; configDiff?: Record<string,unknown> }
  | { kind: 'INCIDENT'; incidentId: string; severity: string; affectedAssets: string[] }
  | { kind: 'TICKET'; ticketKey: string; ticketUrl: string; title: string }
  | { kind: 'NOTIFICATION_RULE'; ruleId: string; channel: string; trigger: string }
  | { kind: 'BI_ASSET'; assetId: string; operation: 'create'|'edit'|'refresh';
      assetType: 'dashboard'|'model'|'dataset' }
  | { kind: 'STORAGE_OBJECT'; bucket: string; key: string; operation: 'write'|'delete'|'copy' }
  | { kind: 'SERVER_ACTION'; serverId: string; action: string; commandPreview?: string }
  | { kind: 'DOCUMENT'; format: 'md'|'html'|'pdf'; body: string };
```

All 16 kinds' payloads are defined in v1, even kinds whose write tools land later, so the schema is stable from the start.

## 6. Lifecycle & state machine

```
            ┌────────┐   user save                  ┌────────────┐
agent ────► │  draft │ ───────────────────────────► │  proposed  │
            └────────┘                              └────────────┘
                                                         │
                                       user approves     │   user rejects
                                          ┌──────────────┴──────────────┐
                                          ▼                             ▼
                                    ┌──────────┐                  ┌──────────┐
                                    │ approved │                  │ rejected │
                                    └──────────┘                  └──────────┘
                                          │
                              apply succeeds / fails
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                        ┌─────────┐             ┌────────┐
                        │ applied │             │ failed │
                        └─────────┘             └────────┘
```

Per-kind variations:

- `INCIDENT` uses `open → resolved → archived` instead of approved/applied.
- `WAREHOUSE_QUERY` goes directly `draft → applied | failed` (a query either ran or didn't).
- `DOCUMENT` uses `draft → applied | archived` (publish = apply).

`archived` is a terminal soft-delete reachable from any state — filtered out of default views.

## 7. Agent flow & tool contracts

### 7.1 `emit_artifact` helper

A single executor helper writes the artefact row on tool success. New module: `scanner/copilot/artifacts/emitter.py`.

```python
def emit_artifact(
    tool_call: ToolCall,
    *,
    kind: ArtifactKind,
    payload: ArtifactPayload,
    status: ArtifactStatus,
    title: str,
    summary: str | None = None,
    subtype: str | None = None,
    integration_id: str | None = None,
    external_ref: dict | None = None,
    risk_level: ArtifactRisk | None = None,
    rollback_hint: str | None = None,
) -> Artifact:
    """Persist or update an artefact for this tool call. Idempotent on (idempotency_key, org_id)."""
```

Idempotency key formula: `f"{tool_call.id}:{kind.value}"` — same tool retry produces the same artefact.

The helper either creates the artefact (first call for that tool) or updates the existing row (status transitions, externalRef fill-in, payload refresh on validate). It does not create a child agent session itself — that happens at agent-run start (§7.3).

### 7.2 Write-tool contract

Every write tool declares (in its `register_tool` decorator) an `ArtifactSpec`:

```python
@register_tool(
    name="create_monitor",
    requires_confirmation=True,
    risk_level=RiskLevel.LOW,
    artifact_spec=ArtifactSpec(
        kind=ArtifactKind.MONITOR,
        status_on_success=ArtifactStatus.applied,
        status_on_propose=ArtifactStatus.proposed,
    ),
)
def create_monitor(...): ...
```

`tool_executor.py` reads the spec after the tool runs and calls `emit_artifact` with the tool's structured return value mapped onto the kind's payload.

### 7.3 Agent session forking

When the agent decides (via planning) to produce a typed artefact, it calls a sentinel tool — `begin_artefact(kind: ArtifactKind, intent: str)` — which:

1. Creates a child `CopilotSession` seeded with parent context (goal, asset context, parent run id).
2. Returns a new `artefact_run_id` the agent uses for all subsequent tool calls in this artefact's flow.
3. Pre-creates the `Artifact` row at `status=draft` so the chat-side card can render immediately and "Save to artefacts" is wired from step one.

Subsequent tool calls in the artefact's flow (e.g. `validate_monitor`, `create_monitor`) update the same artefact via the idempotency key.

When the user (or agent) declares the artefact done — applied or abandoned — the agent stops the turn loop for that session, but the `CopilotSession` row and full transcript persist on the artefact row. Resume is always possible: clicking Continue on `/dashboard/artifacts/[id]` reopens the turn loop against that session.

### 7.4 Group A — PR-flow-backed kinds

`PR_CHANGE`, `DBT_CORE_CHANGE`, `DAG` (repo-managed), `SCHEMA_CHANGE` (repo-managed) all flow through the existing `create_change_plan` → `validate_change_plan` → `apply_change_plan` toolchain. v1 work:

- Add `artifact_spec=ArtifactSpec(kind=ArtifactKind.PR_CHANGE, ...)` to each of those three tools.
- Inside the executor, when a ChangePlan is built, inspect the `patches` to refine the kind: dbt-only patches → `DBT_CORE_CHANGE`; orchestration-only patches → `DAG`; sql_model-only on a non-dbt path → `SCHEMA_CHANGE`; mixed → `PR_CHANGE`.
- `payload.changePlanId` cross-links the artefact to the existing `ChangePlan` row — that table stays the source of truth for the code change.

No changes to `ChangePlan`, `FilePatch`, or `ToolConfirmation`.

### 7.5 Group B — Monitor write slice (v1)

Three new tools:

- `create_monitor(target_fqn, monitor_kind, config)` → `requires_confirmation=true`, `risk=LOW`, `artifact_kind=MONITOR`, `status_on_propose=proposed`, `status_on_success=applied`.
- `update_monitor(monitor_id, config)` → same shape, `risk=LOW`/`MEDIUM` depending on config delta.
- `delete_monitor(monitor_id)` → `risk=MEDIUM`, always confirms.

These wrap the existing internal monitor creation logic (`scanner/monitors/` + the `app/api/monitors` Next routes) — no monitor-runtime work is in scope. Each emits a `MONITOR` artefact with `payload = { monitorId, monitorKind, targetFqn, configDiff }` and `externalRef = { monitor_id }`.

UI side: a `MonitorArtifactCard` component renders the monitor config diff inline in chat and on `/artifacts`. Approve/reject buttons hit the same backend confirmation endpoint that PR-flow uses.

### 7.6 Other Group B kinds (schema-only in v1)

`WAREHOUSE_QUERY`, `SCHEMA_CHANGE` (non-repo), `DBT_CLOUD_CHANGE`, `DAG` (non-repo), `INGESTION_CONNECTOR`, `WATCH`, `INCIDENT`, `TICKET`, `NOTIFICATION_RULE`, `BI_ASSET`, `STORAGE_OBJECT`, `SERVER_ACTION`, `DOCUMENT` all have their `kind`, payload shape, and lifecycle defined in this spec. **No write tools land in v1 for these.** Each gets its own follow-up spec to add tools.

## 8. UI

### 8.1 Chat-side artefact card

When `begin_artefact` fires, the assistant chat renders an `ArtifactCard` inline at the current scroll position. The card:

- Shows kind, status, title, summary.
- Has step-by-step controls (configure → validate → confirm → apply) driven by the agent session's state.
- Has a persistent **"Save to artefacts"** button visible at every step.
- Has approve/reject controls when the artefact is in `proposed`.
- Updates live as the agent progresses (SSE events stream status changes).

The card is a thin shell with a per-kind body component (`PRArtifactBody`, `MonitorArtifactBody`, …). v1 ships bodies for the kinds with write tools (PR_CHANGE family, MONITOR). All other kinds use a generic `GenericArtifactBody` until their feature lands.

The existing `SaveArtifactModal` is rewritten — it no longer prompts for a flat type (Query/Fix/Insight/Code/Plan). For typed artefacts produced by tool calls, "Save to artefacts" is a one-click action that simply persists the current `Artifact` row (which already exists from `begin_artefact`); for free-form messages the user wants to capture, it becomes "Save as Document," producing a `DOCUMENT` artefact with the message text.

### 8.2 `/dashboard/artifacts` page

Same shell as today (header + filter bar + list), polymorphic content:

**Filters:**
- Search (existing)
- Kind multi-select (chips)
- Status filter (default: hide `archived`, `rejected`)
- Subtype/Integration filter (shown contextually when ≥1 subtype present)
- Pinned-only toggle (existing)
- Source filter: All / Agent-produced (has `toolCallId`) / User-saved (no `toolCallId`)

**List item:** single `ArtifactListCard` component that dispatches a per-kind preview component. Preview components are small (~80–150 LOC each). v1 ships PR and Monitor previews; everything else gets a generic title+summary+status preview.

Inline actions on each card:
- View source session →
- Open external link → (when `externalRef` has one)
- Continue → (navigates to `/dashboard/artifacts/[id]`)
- Approve / Reject (when status is `proposed`)
- Pin / Archive / Delete

### 8.3 `/dashboard/artifacts/[id]` — per-artefact view (new route)

Full-page view, three sections stacked:

1. **Artefact header** — title, status, kind+subtype, integration, riskLevel, externalRef links, action buttons (approve/reject/archive).
2. **Artefact body** — the kind-specific renderer (PR diff, Monitor config, DAG diff, etc.).
3. **Agent session** — embedded chat surface scoped to this artefact's `agentSessionId`. Same components as `/dashboard/assistant` (`MessageList`, `MessageInput`, streaming), just bound to the child session. User can keep talking to the agent here; agent has full context of the artefact and can resume from wherever it left off.

This route is the "continue" target. It is also the canonical detail view — clicking any artefact card on `/artifacts` lands here.

### 8.4 `/dashboard/assistant` (existing chat surface)

No structural redesign. Artefact cards render inline as agent tool calls produce them. The existing `ChangePlanCard` / `PRCard` / `ToolConfirmation` keep working. New per-kind cards are added as their write tools land.

## 9. API surface

### Existing routes — kept

- `GET /api/artifacts` — list (extended with `kind`, `status`, `subtype`, `source` filters)
- `GET /api/artifacts/[id]` — get one
- `PATCH /api/artifacts/[id]` — update (existing; supports `isPinned`, gains `status` transitions for approve/reject from /artefacts)
- `DELETE /api/artifacts/[id]` — delete

### New routes

- `POST /api/artifacts/[id]/continue` — rehydrate the artefact's `agentSessionId` and return a session handle the frontend can subscribe to via SSE. Used by `/dashboard/artifacts/[id]`.
- `POST /api/artifacts/[id]/save-snapshot` — explicit "Save to artefacts" trigger; idempotent (no-op if already persisted).

`POST /api/artifacts` (manual create) is removed — artefacts are only created by agent tool calls or by saving a chat message as a `DOCUMENT`. The `DOCUMENT` path goes through `POST /api/artifacts/document` (new, narrowly scoped).

## 10. Migration: nuke

Per user direction (dev data only, no production rows worth preserving):

`scripts/nuke_legacy_artifacts.ts`:

```typescript
import { prisma } from '@/lib/prisma';
async function main() {
  const { count } = await prisma.artifact.deleteMany({});
  console.log(`Deleted ${count} legacy artifacts`);
}
main();
```

Run order:

1. `tsx scripts/nuke_legacy_artifacts.ts`
2. Edit `prisma/schema.prisma` to the new model (§5).
3. `npx prisma db push`
4. `npx prisma generate`

No backfill. No legacy kind. No `content`/`type` columns survive.

This matches Pallisade's Prisma conventions: `db push` only; backfills are tsx under `scripts/`; `prisma/migrations/` is gitignored.

## 11. Implementation slices

All work in this spec ships behind a single feature flag, `ff_artefacts_v2`. The flag stays off until slice #6 lands, then flips on. Each slice below is a separately-mergeable PR:

1. **Schema + types.** Prisma model swap, nuke script, TS discriminated union, Pydantic models. No UI changes; existing /artifacts page renders nothing under the flag (table is empty).
2. **`emit_artifact` + `begin_artefact` + executor wiring.** Plumb the helper, add the sentinel tool, child-session forking. Test with a no-op write tool.
3. **Group A wiring.** Add `artifact_spec` to `create_change_plan` / `validate_change_plan` / `apply_change_plan`. PR_CHANGE artefacts start materializing. Reuse `PRCard`.
4. **`/artifacts` page polymorphism.** New filters, polymorphic list card, PR preview.
5. **`/dashboard/artifacts/[id]` route.** Per-artefact view, Continue flow, embedded scoped chat.
6. **Monitor write slice.** `create_monitor` / `update_monitor` / `delete_monitor` tools, `MonitorArtifactBody`, `MonitorArtifactCard`. Flag flips on after this lands.
7. **`DOCUMENT` save path.** Rewrite `SaveArtifactModal` to save-as-document for free-form text and no-op when the artefact already exists from a tool call.

## 12. Out of scope (named)

- Scout → Agent rename. Tracked in its own spec.
- MCP host capability. Tracked in its own spec.
- Write tools for the other 12 Group B kinds (Warehouse query, schema-direct, dbt-cloud, non-repo DAG, connector, watch, incident, ticket, notification rule, BI asset, storage, server action). Each gets its own follow-up spec.
- Multi-tenant audit log surface for artefacts. The data is captured (toolCallId, userId, agentRunId, appliedAt) but the audit page is later.
- Cost / budget enforcement per artefact. Captured at the agent-run level via existing `scanner/copilot/maas/budgets.py`; no artefact-level accounting in v1.
- Artefact-to-artefact dependency graph (e.g. "this PR depends on that schema change"). Modelable later via `metadata.dependsOn` array.

## 13. Open questions

- **`begin_artefact` tool vs. implicit forking:** §7.3 specs a sentinel tool. Alternative: the executor detects any write tool call and auto-forks. Sentinel is more explicit and easier to test; implicit is less intrusive. Going with sentinel in v1; can revisit.
- **Continue ergonomics:** if the user hits Continue on a long-idle artefact (session compacted), the agent will rehydrate from the compacted transcript. v1 accepts whatever transcript-compaction the existing runtime applies; no special long-idle handling.
- **Multi-user editing of one artefact:** out of scope. Last-writer-wins on status transitions; we'll see if collisions happen in practice before designing a lock.
