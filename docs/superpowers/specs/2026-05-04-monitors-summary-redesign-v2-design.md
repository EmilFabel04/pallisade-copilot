# Monitors Summary Redesign v2 — Unified Overview

**Date:** 2026-05-04
**Status:** Draft
**Supersedes:** `2026-05-04-monitors-summary-redesign-design.md` (the v1 page-structure section). The incidents data model, lifecycle, LLM diagnosis, and mute/suppression sections from v1 stand unchanged — this v2 only redesigns the Summary tab itself.

## Why this exists

The v1 redesign framed Summary as a triage page ("Should I be worried right now?") and moved the pipeline tool tiles off to the Pipeline Monitors tab. Once v1 was wired up, real-world use surfaced four problems:

1. The Hero said *"All systems healthy. 0 assets monitored."* even on profiles with active monitors, because `monitoredAssetCount` was derived from a payload (`monitor-trends.assets`) that hadn't loaded yet — and even when it did load, that payload only counted data-tier assets, not pipeline tooling.
2. There was no way to **run** drift discovery from the page. SLA recommendations only showed up if a back-end job had already produced them, and the user couldn't trigger that job.
3. Sections painted at staggered times (independent fetches, no shared skeleton), so the page felt busy and inconsistent on first load.
4. Pipeline monitors were entirely invisible on Summary — users with Fivetran/Airflow/dbt couldn't see their pipeline health without switching tabs.

The user picked the unified-overview framing: **Summary is the page you keep open**. It surfaces the full health picture across both data and pipeline tiers, plus the actionable shortcuts (run drift discovery, add monitor for critical asset). The other tabs (Data Monitors, Pipeline Monitors) become deep-dive lists, not where the headline information lives.

## Page structure (top to bottom)

```
┌─────────────────────────────────────────────────────────────────┐
│ HERO — monitor-health pill + incident headline                  │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ ACTIVE INCIDENTS                                                │
└─────────────────────────────────────────────────────────────────┘
┌─────────┬─────────┬─────────┬─────────┐
│Pass rate│  MTTR   │ Opened  │Recovered│  TREND STRIP
└─────────┴─────────┴─────────┴─────────┘
┌─────────────────────────────────────────────────────────────────┐
│ PIPELINE TIER                                                   │
│  Fivetran   Airflow   dbt cloud   BigQuery   Looker   linux     │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ DATA TIER                                                       │
│  ● analytics.fct_orders                                         │
│  ● staging.stg_users                                            │
│  ◐ marts.dim_customers                                          │
│  + 35 healthy assets                                            │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────┬───────────────────────────────────────┐
│ Critical assets         │ SLA recommendations                   │
│ unmonitored             │  [Run drift discovery]                │
└─────────────────────────┴───────────────────────────────────────┘
```

### 1. Hero

Single colored band, top of page. Tone driven by **monitor health, not just incidents** — this is the fix for the "0 assets monitored" bug.

**Tone selection** (first match wins):
- Red — any monitor has `lastStatus = FAIL` or `ERROR`, **or** any open non-muted incident has `severity = FAIL`.
- Amber — any monitor has `lastStatus = WARN`, **or** any open non-muted incident has `severity = WARN`. (No FAIL signals present.)
- Green — all monitors are PASS / SKIPPED, and no open non-muted incidents exist.
- Grey ("Setting up") — zero monitors enabled in the profile. This is the empty-state pill, not a failure state.

**Headline format:**
- Green: `All systems healthy.`
- Amber: `N warning${s}.`  + blast radius if available.
- Red: `N critical incident${s}` + (` · M warning` if any) + `.` + blast radius + ` Oldest <Xh Ym>.` if any open incidents.
- Grey: `Setting up. No monitors yet.`

**Sub-line (always visible, not just on green):**
`<total> monitors · <healthy> healthy · <warning> warning · <failing> failing — <data> data assets, <pipeline> pipeline tools`

Where:
- `total = count(Monitor where enabled=true and pipelineStackId=…)`
- `healthy = count(lastStatus IN (PASS, SKIPPED, NULL))` — `NULL` (never-run) renders as healthy in the count, NOT in the headline; if everything is NULL we show the grey "Setting up" state via the tone rule above.
- `warning = count(lastStatus = WARN)`
- `failing = count(lastStatus IN (FAIL, ERROR))`
- `data` = count of distinct `targetFqn` across data-tier monitors (DATA_MONITOR_TYPES — the set already used in `monitors/page.tsx:367`).
- `pipeline` = count of pipeline tools currently connected (one per tool type seen in pipeline-tier monitors, regardless of how many monitors target it).

**Updated-at timestamp** stays in the top-right of the band, sourced from the most recent monitor `lastRunAt` across the profile (so it doesn't depend on the trends payload).

### 2. Active incidents

Unchanged from v1. Open + acknowledged incidents, ranked by status / blast radius / open age. Acknowledged render at reduced opacity. Muted incidents collapse under a "+ N muted" expandable. Each card shows the LLM hypothesis, blast-radius badge, and the action row (Open in Co-pilot, Acknowledge, Resolve, Mute). Renders nothing when the list is empty (the hero already said "all healthy"; the section quietly disappears).

### 3. 7-day trend strip

Unchanged from v1. Four tiles: pass rate, MTTR, opened, recovered. Each shows current value, week-over-week delta, and a 7-point sparkline.

### 4. Pipeline tier

Full-width section. One row of compact tiles, one per pipeline tool present in the profile.

**Layout:** Horizontal grid (`grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))`) so tiles size themselves to the viewport — six tools fit on one row at desktop width, fewer wrap to additional rows on narrow screens. If the profile has zero pipeline tools the section is suppressed entirely (rather than rendering an empty placeholder).

**Tile content (status-only):**
- Tool icon + name (e.g. "Fivetran", "Airflow", "dbt cloud", "BigQuery", "Looker", "linux server")
- Single status line: `healthy`, `N warn`, `N fail`, or `N error` — colored. The line aggregates over **all monitors targeting that tool** in the current profile. Status precedence: FAIL > ERROR > WARN > PASS.
- Last-run timestamp under the status line (e.g. "12m ago"). Sourced from `max(lastRunAt)` across the tool's monitors. Omit when no monitors have ever run.

**Click behavior:** Opens a new `PipelineToolDetailPanel` side panel showing:
- Tool name, status, connection state
- All monitors targeting this tool with their last-run status and sparkline
- Last 5 failures across the tool's monitors (most recent first)
- Link `View all in Pipeline Monitors →` that switches to the Pipeline Monitors tab pre-filtered to this tool.

The side panel is a sibling of the existing copilot/asset detail panels — it dismisses on outside click and ESC.

### 5. Data tier

Full-width section directly under the pipeline tier. `AssetHealthLean` reused as-is from v1. Failing/warning rows visible, healthy collapsed under "+ N healthy assets". Each row has a 30-run sparkline, click expands the existing per-asset detail panel.

**Empty state:** "No data-tier monitors yet. + Add monitor" CTA inline.

### 6. Coverage actions

Two side-by-side cards, full width below the data tier.

#### 6a. Critical assets unmonitored

Same data source as v1 (`/api/coverage/unmonitored-critical`). The endpoint response gains one field: `lineageExtracted: boolean` (true when `PipelineStack.lastLineageExtractedAt` is non-null). The card has three render states:

- **N ≥ 1:** Headline `N critical asset${s} unmonitored`. Sub: "Tables feeding `<top dashboard>` and N other downstream targets." CTA: `Add monitors →` (opens the create-monitor flow with the most-critical asset pre-selected).
- **N = 0 and `lineageExtracted = true`:** Suppressed. Card does not render. (Fixes the "says 0 critical" complaint — when there is genuinely nothing to flag, we don't show a "0" tile that reads as a bug.)
- **`lineageExtracted = false`:** Headline "Lineage not yet extracted." Sub: "Critical-asset coverage needs lineage to identify what feeds your BI dashboards." CTA: `Extract lineage →` (links to the pipeline page lineage panel). This makes the empty state meaningful.

#### 6b. SLA recommendations + drift discovery

Always renders (this is the entry point for proactive analysis, not just a result list).

- Header: `SLA recommendations` (left), `[Run drift discovery]` button (right, primary style).
- Body line: `<N> threshold${s} drifted` if N ≥ 1, else `No threshold drift detected.`
- Sub-line: `Last analysis <relative time>` if a drift run has ever completed for the profile, else `Drift discovery has not run yet.`
- CTA: `Review recommendations →` only when N ≥ 1.

**Drift-discovery button behavior:**

`POST /api/drift/run` already exists — it fans out to the scanner FastAPI drift analyzer (`scanner/api/routers/drift.py` → `scanner/monitors/drift_analyzer.py:run_drift_analysis`) synchronously and persists the resulting `DriftRecommendation` rows. The endpoint can take up to ~2 minutes for large profiles. Flow:

1. User clicks `Run drift discovery`.
2. Frontend POSTs `/api/drift/run` with `{ stackId }` and **awaits** the response (the endpoint is synchronous, AbortSignal.timeout 120s on the FastAPI hop).
3. Button enters running state immediately: spinner + label `Running…`. Disabled until the response lands.
4. On 2xx response, refetch `/api/drift?status=pending&stackId=…` to refresh the recommendation count, show a success toast (`Found N recommendations` / `No threshold drift detected`), return to idle.
5. On non-2xx or AbortError, surface the error message as a `sonner` toast and return to idle.

No new endpoint. The weekly scheduler can also start using this same endpoint internally — but that's out of scope for this plan.

## Data flow

```
Summary tab mounts (selectedPipelineId resolves)
   │
   ▼ seven fetches fire in parallel (independent, no shared gating):
   ├─ /api/incidents?stackId=…&status=active     → ActiveIncidents + Hero (incident count)
   ├─ /api/monitors/health-summary?stackId=…     → Hero (monitor counts) [NEW endpoint]
   ├─ /api/incidents/stats?stackId=…&window=7d   → TrendStrip
   ├─ /api/monitors/pipeline-status?stackId=…    → PipelineTier tiles [NEW endpoint]
   ├─ /api/schedule/monitor-trends?stackId=…     → DataTier (AssetHealthLean)
   ├─ /api/coverage/unmonitored-critical?stackId=…→ Coverage card 6a
   └─ /api/drift?status=pending&stackId=…        → SLA card 6b

Hero paints when health-summary + incidents both arrive (both are cheap)
Each other section paints independently as its data lands.
```

## Architecture

### New endpoints (Next.js)

**`GET /api/monitors/health-summary?stackId=…`**

Returns a single object that the Hero needs:

```ts
{
  total: number;            // count enabled monitors
  healthy: number;          // PASS, SKIPPED, NULL
  warning: number;          // WARN
  failing: number;          // FAIL, ERROR
  dataAssets: number;       // distinct targetFqn across DATA monitors
  pipelineTools: number;    // distinct toolType across PIPELINE monitors
  lastRunAt: string | null; // max lastRunAt across all monitors (ISO)
}
```

A single Prisma `groupBy` on `Monitor` plus two distinct counts. p95 < 200ms expected.

**`GET /api/monitors/pipeline-status?stackId=…`**

Returns one row per pipeline tool present in the profile:

```ts
{
  tools: Array<{
    toolType: string;       // e.g. "fivetran"
    displayName: string;    // e.g. "Fivetran"
    status: 'PASS' | 'WARN' | 'FAIL' | 'ERROR' | 'NEVER_RUN';
    failCount: number;
    warnCount: number;
    monitorCount: number;
    lastRunAt: string | null;
  }>;
}
```

Computed by `groupBy(Monitor, toolType)` filtered to PIPELINE_MONITOR_TYPES, with status precedence FAIL > ERROR > WARN > PASS.

**`POST /api/drift/run` (existing — wire only):** Already implemented at `app/api/drift/run/route.ts`. Synchronous, returns `{ runId, recommendationCount }` after analysis completes. The plan only adds the button that calls it; no endpoint changes needed.

### Frontend components

- **`SummaryHero.tsx`** (modify) — accept the new `MonitorHealthSummary` shape. Compute tone from monitor counts, not just incidents. Sub-line shows `total / healthy / warn / fail` plus tier breakdown.
- **`PipelineTier.tsx`** (new) — replaces today's `PipelineHealthTiles` for use on Summary. Status-only tiles, click opens detail panel. The existing `PipelineHealthTiles` (rich version) stays as-is on the Pipeline Monitors tab.
- **`PipelineToolDetailPanel.tsx`** (new) — side panel shown on tile click. Sibling of existing `DataAssetDetailPanel`.
- **`DriftSummaryTab.tsx`** (modify) — vertical stack (hero → incidents → trends → pipeline tier → data tier → coverage); fan out the new fetches; manage the drift-run polling state.
- **`CoverageGaps.tsx`** (modify) — three-state render for the critical-assets card; `Run drift discovery` button on the SLA card with run/idle state.

### State management

The drift-run state (idle / running / error) lives in `DriftSummaryTab` local state. Since `/api/drift/run` is synchronous and `await`-ed, there is no in-flight job to recover after a remount — if the user navigates away mid-run, the request is abandoned (the FastAPI side still completes and persists recommendations). On remount we just refetch `/api/drift` to show the latest count and `lastAnalyzedAt`.

### Loading consistency

All sections render their own per-section skeleton on first paint. The hero waits on **two cheap fetches** (`health-summary`, `incidents`), not on the heaviest one. AssetHealthLean and PipelineTier render their own skeletons until their respective payloads arrive. The user no longer sees the page expand mid-skeleton because the skeleton heights match the final content.

## Scope and non-goals

**In scope (v2):**
- Vertical-stack layout — hero, incidents, trends, pipeline tier (full width), data tier (full width), coverage actions
- Hero recomputed from `Monitor.lastStatus`, fixing the "0 assets monitored" bug
- Pipeline tier tiles (status-only) on Summary, click opens detail panel
- Run drift discovery as an explicit button + new endpoint
- Three-state Critical Assets card (suppress when N=0 and lineage is extracted)
- Per-section skeletons for first-paint stability
- Reuse v1's incidents data model, lifecycle, LLM diagnosis, and mute logic unchanged

**Out of scope (v2):**
- Re-imagining the Pipeline Monitors and Data Monitors tabs (they remain deep-dive lists)
- Customizing which sections show / order (no user preferences for v2)
- Cross-pipeline summary (Summary stays scoped to the selected pipeline)
- Realtime push (we keep the existing 30s poll for incidents and trends)

## Migration

- The v1 components (`SummaryHero`, `CoverageGaps`, `DriftSummaryTab`) are modified, not replaced. `PipelineHealthTiles` (rich version) stays for the Pipeline Monitors tab; `PipelineTier` is new.
- The two new endpoints (`/api/monitors/health-summary`, `/api/monitors/pipeline-status`) are additive.
- `/api/drift/run` is reused as-is — only the button that calls it is new.
- No schema changes.

## Open questions

None at design close. Confirmed during brainstorming:
- Layout: A1 vertical stack (pipeline tier and data tier each full-width).
- Pipeline tile density: status-only with click-to-expand details.
- Hero is monitor-health-driven, not just incident-driven.
- Drift discovery becomes a first-class manual action.
