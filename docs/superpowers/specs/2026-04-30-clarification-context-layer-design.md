# Clarification & Business-Context Layer — Design Spec

**Date**: 2026-04-30
**Status**: Design approved, awaiting implementation plan
**Branch**: to be created at implementation handoff (separate branch)

---

## 1. Problem

Pallisade's SLA discovery and monitor auto-discovery silently guess when input is ambiguous: which timestamp column to use for volume, which column is the primary key for uniqueness, which `volume_mode` fits an append-only vs. upsert table. When a guess is wrong, downstream monitors are wrong, and the user has no easy way to teach the platform the correct answer once.

Borderline monitor failures (small-margin breaches just inside the alert threshold) likewise lack a "is this real or noise?" loop — the platform either alerts or stays silent, with no path to capture the user's interpretation as durable context.

We need a layer that (a) detects when the platform is making a low-confidence guess, (b) asks the user a focused question through the existing copilot, (c) parses the answer, and (d) persists it as either a per-node override or a generalized convention so future runs use it automatically.

## 2. Goals

- Capture business context that the platform cannot derive from the warehouse alone.
- Reduce false-positive monitors by learning expected dips, baselines, and dampening rules.
- Reuse the existing copilot LLM, notification rail, and per-pipeline context store — no parallel chat, no parallel storage.
- Generalize answers via conventions so onboarding 50 tables ≠ 50 prompts.
- Keep all guesses auditable: every uncertain decision the platform makes is a row that can be inspected and revised.

## 3. Non-goals (V1)

- No autonomous answering by the LLM without user input. Every clarification waits for a human reply.
- No retroactive re-run of historical monitor evaluations after a new convention is written. New context affects future runs only.
- No cross-pipeline conventions. All learning is scoped to one `pipelineStack`. Cross-pipeline sharing is a later concern.
- No mobile / push notifications. Reuse the in-app notification rail.

## 4. Architecture

### 4.1 Diagram

```
┌─────────────────────────────────────────────────────────┐
│ Frontend (Next.js)                                      │
│ ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐ │
│ │ Bell (alerts)│  │ LLM-bell ★  │  │ Copilot popup ★  │ │
│ └──────────────┘  └─────────────┘  └──────────────────┘ │
│                          │                │              │
└──────────────────────────┼────────────────┼──────────────┘
                           │                │
                  ┌────────▼────────┐  ┌────▼────────────┐
                  │ /api/context-   │  │ /api/copilot/   │
                  │   requests      │  │   chat          │
                  └────────┬────────┘  └────┬────────────┘
                           │                │
┌──────────────────────────▼────────────────▼──────────────┐
│ FastAPI                                                   │
│ ┌──────────────────────┐  ┌──────────────────────────┐    │
│ │ ContextRequestRouter │  │ CopilotLLM (existing)    │    │
│ │  - list / answer     │  │  + mode="clarify" ★      │    │
│ │  - dismiss           │  │  + mode="sweep" ★        │    │
│ └──────────┬───────────┘  └──────────────────────────┘    │
│            │                                               │
│ ┌──────────▼───────────────────────────────────────────┐  │
│ │ ClarificationEngine ★                                 │  │
│ │  - emit(kind, candidates, evidence, scope)            │  │
│ │  - lookup(kind, scope) → existing answer or null      │  │
│ │  - resolve(request_id, answer) → write to stores      │  │
│ │  - sweep(integration_id) → batched onboarding         │  │
│ │  - completeness(scope) → tier fill rate               │  │
│ └──────────┬─────────────────────────────────────┬─────┘  │
│            │                                     │        │
│ ┌──────────▼──────────┐  ┌──────────────────────▼──────┐  │
│ │ sla_discovery (M)   │  │ monitor evaluation (M)      │  │
│ │  - emit on guess    │  │  - emit on borderline fail  │  │
│ │  - re-run on answer │  │  - z-score band check       │  │
│ └─────────────────────┘  └─────────────────────────────┘  │
└────────────────────┬───────────────────────────────────────┘
                     │
            ┌────────▼─────────────────────────┐
            │ Postgres                         │
            │  ContextRequest ★ (new)          │
            │  ContextResolution ★ (new)       │
            │  PipelineContext.conventions     │
            │   Context (extended)             │
            │  PolicyAssignment.overrides      │
            │   (extended)                     │
            └──────────────────────────────────┘
```

★ = new. (M) = modified existing module.

### 4.2 Load-bearing idea

The `ClarificationEngine` is the **only** module that touches the new tables. Every guesser in the codebase calls `engine.emit(...)`; every consumer calls `engine.lookup(...)`. The popup chat is a thin shell over the engine. This keeps clarification logic out of `sla_discovery.py`, `policy_resolver.py`, and the copilot — they only know about the engine's interface.

## 5. Data model

### 5.1 New tables (Prisma)

```prisma
model ContextRequest {
  id              String   @id @default(cuid())
  pipelineStackId String
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id])

  // What kind of clarification.
  // V1 kinds: timestamp_choice, pk_choice, volume_mode_choice, table_role,
  // update_pattern, calendar, null_baseline, naming_convention, domain_owner,
  // glossary_term, lineage_hint, failure_review, freeform_note.
  kind            String

  // Where the question applies. Exactly one combo is set.
  scopeType       String   // 'node' | 'dataset' | 'integration' | 'pipeline'
  scopeRef        String   // FQN, dataset name, integration id, or pipeline id

  // Everything the LLM needs to phrase the question + parse the reply.
  // Shape varies by kind; validated by the per-kind schema in code.
  payload         Json

  status          String   // 'open' | 'answered' | 'dismissed' | 'superseded' | 'expired'
  priority        String   // 'critical' | 'high' | 'normal' | 'low'

  createdAt       DateTime @default(now())
  resolvedAt      DateTime?
  dismissedUntil  DateTime?  // for re-emit suppression after dismiss
  resolutionId    String?    @unique
  resolution      ContextResolution?

  @@index([pipelineStackId, status])
  @@index([scopeType, scopeRef])
  @@index([pipelineStackId, kind, status])
}

model ContextResolution {
  id              String   @id @default(cuid())
  requestId       String   @unique
  request         ContextRequest @relation(fields: [requestId], references: [id])

  // Structured choice the LLM parsed out of the user's free-text answer.
  // e.g., { "column": "loaded_at" } or { "mode": "period", "period": "1d" }
  // Validated against the per-kind answer schema before insert.
  answer          Json

  // Raw chat transcript — enables re-parsing if our schemas evolve.
  transcript      Json

  // Convention propagation: did this answer also write a convention?
  // { key, scope, oldValue, newValue }
  conventionUpdate Json?

  answeredBy      String   // userId
  answeredAt      DateTime @default(now())
}
```

### 5.2 Extensions to existing tables

`PipelineContext.conventionsContext` (`Json`, already present) gains structured shape:

```json
{
  "volume_timestamp_preference": {
    "ordered": ["loaded_at", "ingested_at", "updated_at"],
    "scope": "raw.*"
  },
  "pk_preference": { "ordered": ["id", "uuid"], "scope": "*" },
  "naming": {
    "raw_prefix": "raw_",
    "staging_prefix": "stg_",
    "fact_prefix": "fct_"
  },
  "calendar": {
    "business_days": ["mon", "tue", "wed", "thu", "fri"],
    "timezone": "UTC",
    "holidays_calendar": "US"
  },
  "glossary": {
    "active_user": "logged in within 30d",
    "revenue_unit": "cents"
  }
}
```

`PolicyAssignment.overrides` (`Json`, already present) gains a `clarifications` sub-object for per-node answers that don't generalize. Both fields are already sparse `Json`, so no migration risk for existing rows.

### 5.3 Per-kind payload + answer schemas

Every `kind` ships with three schemas defined in `scanner/copilot/clarifications/kinds/`:

- `payload_schema` — what `emit()` must provide (candidates, evidence, source heuristic, confidence)
- `answer_schema` — what the LLM must produce after parsing the user's reply
- `convention_rules` — whether (and how) the answer can update `conventionsContext`

The engine validates against these schemas at every boundary. Unknown `kind` is a 400.

## 6. Trigger flows

### 6.1 Flow A — Pre-discovery / pre-monitor (non-blocking)

1. User clicks "Discover from data" on `raw.orders`.
2. `sla_discovery` runs, calls `ClarificationEngine.lookup(kind="timestamp_choice", scope=node)`.
   - Convention covers it (`raw.*` → `loaded_at`)? Use it. No popup.
   - No convention? Run heuristic, get tentative answer + confidence.
3. If `confidence < threshold` OR 0 candidates OR multiple equally-strong candidates → `engine.emit(...)` creates a `ContextRequest`. Discovery returns its tentative result tagged `{"tentative": true, "context_request_id": "..."}`.
4. Frontend renders the discovery result with a "Pending clarification" badge; LLM-bell badge increments.
5. User opens popup, LLM phrases the question, user answers, parser writes `ContextResolution` and (if applicable) updates `conventionsContext`.
6. Engine fires a `context_resolved` event → discovery re-runs in the background → tentative tag drops, result updates in place.

### 6.2 Flow B — Onboarding sweep

1. User adds an integration / connects a new pipeline.
2. `ClarificationEngine.sweep(integration_id)` groups discoverable tables by detected pattern (schema prefix, dbt project layer, name regex).
3. For each pattern group, it asks **one** question (not per-table). e.g.: "I see 23 `raw.*` tables, all append-only with a `loaded_at` column. Treat that as the volume time column for the whole `raw` schema?"
4. User answers in popup. Engine writes a convention scoped to `raw.*`.
5. Future per-node discoveries hit the convention; no popup.
6. Per-table override is still possible via Flow A.

Sweep target: ≤ 5 questions per integration with ≤ 50 tables in V1.

### 6.3 Flow C — Borderline monitor failure

1. Monitor evaluation computes z-score against historical baseline (existing `sensitivity_to_zscore` machinery).
2. `|z| > sensitivity_threshold` (e.g., 3σ) → normal alert. Done.
3. `1.5σ ≤ |z| < threshold` → `engine.emit(kind="failure_review", priority="high")` with payload `{metric, observed, expected_range, z, sample_window}`.
4. LLM-bell badge appears: "raw.orders volume dipped 18% — within normal noise but close to the line. Investigate or mark expected?"
5. User answers:
   - "expected" → engine writes a `null_baseline` / `expected_dip` convention, dampens future alerts on this node.
   - "investigate" → routes to existing copilot debug flow with the failure context loaded.
6. Drastic failures (`>3σ`) bypass this entirely; they alert as today.

The borderline band lower bound (1.5σ default) is a config value in `scanner/copilot/clarifications/config.py`.

### 6.4 Flow D — Ad-hoc context volunteering

User opens popup from any page and types: "fyi we treat Mondays as low-volume, that's expected." LLM detects this is convention-worthy, writes it, confirms back. Engine creates a synthetic `ContextRequest` (status `answered`) so the audit trail stays uniform.

### 6.5 Completeness badge

Each node, dataset, and pipeline has a Tier-1/2/3 fill score computed by `ClarificationEngine.completeness(scope)`. Surfaced as a chip on the lineage hover-card and in the SLA editor panel. Click → opens popup; LLM offers to ask the gap questions in batch.

## 7. UI

### 7.1 Notification rail

```
[ 🔔 alerts ]  [ 💡 LLM ★ ]
```

LLM-bell badge = count of `status='open'` `ContextRequest`s for the current pipeline.

### 7.2 Popup chat

- Right-anchored side panel, 420px wide, persistent across pages.
- Same chat UI as existing copilot.
- Header shows the focused `ContextRequest` (kind, scope, priority); user can cycle through pending ones with arrows.
- Free-text input is the default answer surface; the LLM owns phrasing and parsing. Quick-reply chips are only used for the borderline-failure card (Section 7.5), which has exactly two structured answers; for every other `kind` the popup is text-only in V1.
- New copilot mode `clarify` is selected automatically when a `ContextRequest` is in focus; otherwise mode follows the existing routing.

### 7.3 Visual states

- LLM-bell empty → grey, no badge.
- LLM-bell with open requests → coloured + count badge.
- `priority='critical'` emit → red dot pulse for 5s. Used sparingly: borderline failure on a high-criticality node; missing PK on a production-tier table.

### 7.4 Tentative results

In the SLA editor and discovery result UI, fields backed by a tentative guess render with a dotted underline + "🔍 awaiting clarification" tag. Hover shows the question summary and a "Open in popup" button.

### 7.5 Borderline failure card

Renders inside the popup with the question pre-loaded, two quick-reply chips ("Expected — dampen future alerts" / "Investigate"), and the free-text input for nuance. The chips are convenience shortcuts that submit pre-filled text to the same parser.

## 8. LLM integration

### 8.1 Modes

`CopilotLLM` gains two new modes alongside existing `ask`/`debug`/`plan`/`create`:

- `clarify` — focused on a single `ContextRequest`. System prompt loads `payload`, available tools restricted to read-only schema/metadata lookups + the new `record_clarification_answer` tool.
- `sweep` — knows it's running an onboarding sweep across pattern groups. Tools include `enumerate_pattern_groups(integration_id)` and `record_clarification_answer`.

### 8.2 Per-kind prompts

Each `kind` has a prompt template in `scanner/copilot/clarifications/kinds/<kind>/prompt.md` defining how to phrase the question and how to parse the reply. Adding a new `kind` is: drop a folder, register schemas, register prompt. No core code changes.

### 8.3 Write-back tool

Single new tool: `record_clarification_answer(request_id, structured_answer, propose_convention?)`. Validated against the kind's `answer_schema` before commit. The only path the LLM can use to write to clarification stores.

### 8.4 Lookup at emit-time

Before emitting, every guesser calls `engine.lookup(kind, scope)` to honour existing conventions and answers. Lookup precedence:

1. Per-node override in `PolicyAssignment.overrides.clarifications`
2. Per-dataset override in `conventionsContext` (scoped match)
3. Pipeline-wide convention in `conventionsContext` (scope `*`)
4. None → emit a new request

## 9. Error handling & edge cases

- **Discovery fails entirely** → no `ContextRequest` emitted; existing error path unchanged.
- **Heuristic returns 0 candidates** → emit with `payload.candidates = []`; LLM asks open-ended.
- **User dismisses** → status `dismissed`, `dismissedUntil = now + 14d`. Engine won't re-emit the same `(kind, scopeType, scopeRef)` until that timestamp passes OR underlying evidence changes (schema diff, sensitivity bump).
- **Schema invalidates an answer** (column removed, table dropped) → engine sets old resolution `superseded` and emits a fresh request.
- **LLM produces unparseable output** → retry once with a stricter parse prompt; if still fails, surface the raw answer as a `freeform_note` request with `needs_human_review=true` rather than discarding.
- **Concurrent edits** (two users answer same request) → first commit wins; second sees a "this was just answered by X" toast and the popup refreshes.
- **Convention conflict** (new answer contradicts existing convention) → LLM must explicitly confirm the override before writing; old convention archived on the new resolution's `conventionUpdate.oldValue`.
- **Pipeline switch mid-conversation** → popup closes the current chat thread, badge re-counts for the newly-selected pipeline. Per existing isolation rules.

## 10. Testing strategy

### 10.1 Unit (`scanner/copilot/clarifications/tests/`)

- `ClarificationEngine.emit / lookup / resolve` — covers convention precedence, dismiss decay, schema invalidation.
- Per-kind parsers — golden-file tests of LLM reply → structured answer for every `kind`.
- Borderline-band z-score classifier.
- Sweep pattern-grouper — input: list of FQNs → output: pattern groups.

### 10.2 Integration

- End-to-end Flow A: emit → user answers → discovery re-runs → tentative tag drops.
- End-to-end Flow C: monitor evaluation in borderline band → request created → answered → convention written → next eval respects dampening.
- Sweep on a fake integration with 30 tables → asserts ≤ 5 questions emitted.

### 10.3 Frontend

- Playwright (or existing harness): popup opens with badge count, cycling through pending, free-text submit, optimistic UI on resolve.

### 10.4 Regression

- Existing `test_sla_discovery.py` must pass unchanged.

## 11. Rollout

- Implementation lives on a separate branch (per user request); merged to `main` after the full set of unit + integration + frontend tests is green.
- Feature surface is additive — disabled paths simply skip emitting and the system behaves as today. No feature flag necessary in V1.
- After ship: monitor the count of open `ContextRequest`s per pipeline as a UX health metric. > 50 open per pipeline = signal that we're over-asking; tune confidence thresholds and sweep grouping.

## 12. Open follow-ups (post-V1, deliberately deferred)

- Cross-pipeline convention sharing (org-level glossary).
- Tier-4 strategic context capture (priorities, compliance/PII tagging, tooling overlap).
- Automatic re-evaluation of historical monitor runs after a new convention writes.
- Push notifications / email for `priority='critical'` requests.
- Multi-language LLM responses (EN-only in V1).
