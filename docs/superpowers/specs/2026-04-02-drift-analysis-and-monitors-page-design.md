# Drift Analysis Engine & Monitors Page Redesign

**Date:** 2026-04-02 (updated 2026-04-03)
**Status:** Approved

## Overview

A weekly scheduled LLM-powered drift analysis system that reviews all monitor run history, detects sustained trends across 6 drift categories (freshness, volume, quality, schema, anomaly, uniqueness), and produces actionable SLA adjustment recommendations. Paired with a page restructure that renames the Tasks page to Monitors, moves it to `/dashboard/monitors`, and splits content into three tabs: Summary (drift recommendations), Data Monitors, and Pipeline Monitors.

## Goals

1. Surface data quality drift that humans would miss by reviewing individual runs
2. Recommend concrete SLA changes backed by statistical evidence and LLM reasoning
3. Give users accept/edit/dismiss workflow so recommendations don't auto-apply
4. Reorganize the monitors page for clarity — separate data monitors from pipeline tool monitors

## Non-Goals

- Real-time drift detection (batch weekly only)
- Auto-applying recommendations without user action
- Changes to existing per-run LLM validation in the task executor

## Dependencies

- **SLA Auto-Discovery system** — assignment type `auto_discovered` in the policy resolution chain. Discovery runs via `scanner/lineage/sla_discovery.py` and covers 5 dimensions: freshness, volume, quality, schema, and uniqueness. Bulk discovery is supported via `discover_sla_profiles_bulk()` with adapter connection pooling. Discovery uses instant zero-cost system views (`__TABLES__`, `INFORMATION_SCHEMA.TABLES`, `pg_stat_user_tables`) rather than historical queries.
- **Discovery API** — `scanner/api/routers/discovery.py` exposes `POST /api/v1/discovery/node` (single) and `POST /api/v1/discovery/bulk` (batch). Persistence via `POST /api/lineage/discovery` creates `PolicyProfile` ("Discovered SLA — {table}") and `PolicyAssignment` with `assignmentType: 'auto_discovered'`.
- **SLA Editor** — `SLAEditorPanel.tsx` is now profile-free with direct form fields and a "Discover from data" button that pre-fills values. Includes uniqueness section with PK detection results. No tiers or profile selection.
- **Uniqueness detection** — `sla_discovery.py` detects PK columns via heuristic chain (declared PK → id → *_id → common names), computes duplicate rate via approximate distinct counting. Note: uniqueness config is not yet persisted to the database — this needs to be added before drift analysis can track uniqueness drift.

---

## 1. Data Model

### New: `DriftRecommendation`

```prisma
model DriftRecommendation {
  id               String    @id @default(cuid())
  organizationId   String
  monitorId        String
  monitorName      String
  monitorType      String
  targetFqn        String

  // Drift detection
  driftCategory    String    // freshness | volume | quality | schema | anomaly | uniqueness
  severity         String    // low | medium | high

  // Current vs recommended
  currentField     String    // e.g. "freshness.maxHours"
  currentValue     String    // e.g. "6"
  recommendedValue String    // e.g. "2"

  // LLM analysis
  reasoning        String    // LLM explanation of why
  confidence       Float     // 0.0-1.0
  evidence         Json      // statistical summary that backed the recommendation

  // User action
  status           String    @default("pending") // pending | accepted | dismissed
  reviewedAt       DateTime?

  // Batch tracking
  runId            String    // groups recommendations from same analysis run

  createdAt        DateTime  @default(now())

  organization     Organization @relation(fields: [organizationId], references: [id])
  monitor          Monitor      @relation(fields: [monitorId], references: [id], onDelete: Cascade)

  @@index([organizationId, status])
  @@index([monitorId])
  @@index([runId])
}
```

Add `driftRecommendations DriftRecommendation[]` relation to both `Organization` and `Monitor` models.

**Lifecycle:** Each weekly run produces a batch linked by `runId`. New pending recommendations for the same monitor+field supersede (auto-dismiss) previous pending ones from older runs.

---

## 2. Backend — Drift Analyzer Module

### File: `scanner/monitors/drift_analyzer.py`

**Entry point:** `async def run_drift_analysis(org_id: str, db: AsyncSession) -> str`
Returns the `runId` for the batch.

**Flow:**

1. Fetch all enabled monitors for the organization
2. For each monitor, query all `MonitorRun` results and `MonitorBaseline` entries
3. Resolve the effective SLA policy for each monitor's `targetFqn` — this includes policies from all sources in the resolution chain: `direct_profile`, `direct_override`, `imported_dbt`, `auto_discovered`, `branch`, `criticality_default`, `domain_default`. The `auto_discovered` source is particularly relevant as it provides SLA baselines derived from actual warehouse system views via `sla_discovery.py`, covering freshness, volume, quality, schema, and uniqueness dimensions.
4. Skip monitors with fewer than 5 runs (insufficient data). For monitors with sparse run history but an `auto_discovered` SLA, the discovery baselines themselves serve as the historical reference — the drift analyzer compares current monitor results against the discovered thresholds.
5. Compute statistical summaries per drift category:

| Category | What It Analyzes | Key Stats |
|----------|-----------------|-----------|
| **Freshness** | hours-since-update values vs SLA `maxHours` | mean, p95, trend slope, consistency ratio |
| **Volume** | row counts over time | linear regression slope, variance coefficient, growth rate vs threshold |
| **Quality** | null rates vs SLA `maxNullRate` | trend direction, sudden shift detection (>2 stddev), mean vs threshold |
| **Schema** | schema changes vs discovered column baseline | events per period, additions vs removals, diff against discovery snapshot |
| **Anomaly** | false positive rate from LLM validation history | `raw_status` vs `adjusted_status` ratio, sensitivity fit score |
| **Uniqueness** | duplicate rates on detected PK columns vs `maxDuplicateRate` | trend direction, rate vs threshold, PK column stability |

6. Bundle monitors with significant drift into LLM prompt, batched by category (keeps context focused, avoids token bloat). Include the SLA source in context so the LLM knows whether the current threshold came from manual config, auto-discovery, or dbt import — this affects recommendation confidence.
7. LLM returns structured JSON array of recommendations
8. Auto-dismiss previous pending recommendations for the same monitor+field
9. Store new `DriftRecommendation` records

### LLM Prompt Structure

```
You are a data quality analyst reviewing monitor performance trends.

For each monitor below, I've provided:
- Current SLA/config values and their source (direct_profile, auto_discovered, imported_dbt, etc.)
- Statistical summary of all historical results
- Trend direction and significance

Recommend SLA adjustments where the data shows consistent drift.

Rules:
- Only recommend changes where confidence > 0.7 and the trend is sustained
- Do NOT recommend changes for monitors with insufficient history
- For tightening recommendations, ensure the new threshold still has buffer above actual performance
- For loosening recommendations, explain why the current threshold causes false alerts
- For auto_discovered SLAs, weight recommendations higher — these were derived from historical data and the drift analyzer has newer data to refine them
- For imported_dbt SLAs, note in reasoning that the threshold originated from dbt config

Return a JSON array where each element has:
{
  "monitorId": "...",
  "driftCategory": "freshness|volume|quality|schema|anomaly|uniqueness",
  "currentField": "section.field",
  "currentValue": "...",
  "recommendedValue": "...",
  "reasoning": "1-2 sentence explanation",
  "confidence": 0.0-1.0,
  "severity": "low|medium|high"
}
```

### Statistical Helpers

Add to `drift_analyzer.py`:

- `compute_freshness_stats(runs)` — mean, p95, trend slope of hours-since-update
- `compute_volume_stats(baselines)` — linear regression, variance shift detection
- `compute_quality_stats(runs)` — null rate trends, sudden shift detection
- `compute_schema_stats(runs, discovery_snapshot)` — schema change frequency, diff against discovered column baseline (name, type, nullable, ordinal)
- `compute_anomaly_stats(runs)` — false positive rate from validation history
- `compute_uniqueness_stats(runs)` — duplicate rate trends on detected PK columns, threshold fit

These feed pre-digested numbers to the LLM so it reasons over stats rather than raw data points (token-efficient).

### Scheduler Integration

Register in `scanner/scheduler/service.py` as a weekly cron job:
- Default schedule: Sunday 00:00 UTC (configurable per org)
- Uses existing scheduler infrastructure — no new scheduling system needed
- Job calls `POST /api/v1/monitors/drift/analyze` internally

---

## 3. API Routes

### Next.js Routes

**`GET /api/monitors/drift`**
- Query params: `status` (pending|accepted|dismissed), `category`, `runId`
- Returns recommendations grouped by `runId` with monitor metadata
- Scoped to current user's organization

**`PATCH /api/monitors/drift/[id]`**
- Body: `{ action: "accept" | "accept_with_value" | "dismiss", value?: string }`
- `accept`: updates monitor config or SLA with recommended value, marks as accepted
- `accept_with_value`: same but uses user-provided value instead of recommended
- `dismiss`: marks as dismissed
- Sets `reviewedAt` to now

**`POST /api/monitors/drift/run`**
- Manually triggers drift analysis (proxies to FastAPI)
- Returns the `runId` for polling/fetching results

### FastAPI Route

**`POST /api/v1/monitors/drift/analyze`** in `scanner/api/routers/monitors.py`
- Receives `{ org_id: string }`
- Calls `drift_analyzer.run_drift_analysis()`
- Returns `{ runId, recommendationCount }`

---

## 4. Page Restructure

### URL Change

`/dashboard/schedule` → `/dashboard/monitors`

Move the page directory from `app/(dashboard)/dashboard/schedule/` to `app/(dashboard)/dashboard/monitors/`.

### Sidebar

Rename "Tasks" to "Monitors" in the sidebar navigation component.

### Tab Structure

| Tab | Route | Content |
|-----|-------|---------|
| **Summary** | `/dashboard/monitors` (default) | Drift recommendation cards from latest analysis run |
| **Data Monitors** | `/dashboard/monitors?tab=data` | Monitors with data quality types |
| **Pipeline Monitors** | `/dashboard/monitors?tab=pipeline` | Monitors with pipeline tool types |

### Monitor Type Splitting

**Data Monitors tab** — monitor types:
`FRESHNESS`, `VOLUME`, `SCHEMA_CHANGE`, `NULL_CHECK`, `UNIQUENESS_CHECK`, `OUTLIER_DETECTION`, `ANOMALY`, `RANGE_VALIDATION`, `ACCEPTED_VALUES`, `DATE_CONSISTENCY`, `DATA_TYPE_VALIDATION`

**Pipeline Monitors tab** — monitor types:
`SYNC_LAG`, `FAILED_SYNCS`, `CONNECTOR_SCHEMA_DRIFT`, `DAG_LAST_RUN`, `DAG_SCHEDULE_LAG`, `TASK_FAILURE_RATE`, `DBT_TEST_FAILURES`, `DBT_MODEL_FRESHNESS`, `DBT_SOURCE_FRESHNESS`, `BI_FRESHNESS_PROXY`, `BI_UPSTREAM_BREAK_RISK`, `BI_REFRESH_FAILURE`, `BI_CONTENT_HEALTH`, `SERVER_HEALTH`, `CERTIFICATE`, `LOG_ANALYSIS`

Both tabs reuse the existing `WatchCard`, `MonitoringPlanCard`, and `WatchDetailPanel` components. The existing monitors simply get filtered by type into their respective tabs.

### Scheduled Tasks

Removed from this page entirely. User will delete the existing task-related code.

---

## 5. Summary Tab — Drift Recommendation UI

### Stats Banner

Top of the Summary tab:
- Last analysis date (e.g., "Last analyzed: Mar 30, 2026")
- Pending / Accepted / Dismissed counts
- Total monitors analyzed
- "Run Analysis" button (triggers manual drift analysis)

### Filters

- Category: freshness, volume, quality, schema, anomaly, uniqueness (multi-select pills)
- Severity: low, medium, high
- Status: pending, accepted, dismissed

### Recommendation Card

Each card displays:
- **Header row**: Monitor name, target FQN, drift category badge (color-coded)
  - freshness = blue, volume = purple, quality = amber, schema = orange, anomaly = red, uniqueness = cyan
- **Change row**: Current value → Recommended value with field label (e.g., "Max Freshness: 6h → 2h")
- **Severity indicator**: Dot or badge (low = gray, medium = amber, high = red)
- **Reasoning**: LLM explanation, 1-2 sentences, expandable for full evidence
- **Evidence line**: Compact stat (e.g., "avg 1.2h across 47 runs, p95 1.8h")
- **Action buttons**: Accept (green), Edit (opens inline editor pre-filled with recommended value), Dismiss (gray)

### Accepted/Dismissed States

- Accepted cards get a green checkmark, muted styling, show what was applied
- Dismissed cards get strikethrough styling, can be filtered out
- Both remain visible until the next analysis run supersedes them

---

## 6. Component Structure

### New Components

| Component | Purpose |
|-----------|---------|
| `components/monitors/MonitorsPageTabs.tsx` | Tab bar: Summary, Data Monitors, Pipeline Monitors |
| `components/monitors/DriftSummaryTab.tsx` | Stats banner + filter + recommendation card grid |
| `components/monitors/DriftRecommendationCard.tsx` | Individual recommendation card with actions |
| `components/monitors/DriftStatsBar.tsx` | Banner with counts and "Run Analysis" button |

### Modified Components

| Component | Change |
|-----------|--------|
| `app/(dashboard)/dashboard/monitors/page.tsx` | New page (moved from schedule), tab routing |
| Sidebar nav component | Rename "Tasks" → "Monitors", update href |

### Existing Components Reused

- `WatchCard`, `MonitoringPlanCard`, `WatchDetailPanel` — used in Data/Pipeline tabs
- `GovernanceFilters` — reusable filter pattern for Summary tab

---

## 7. Accept Flow — Applying Recommendations

When user clicks Accept on a recommendation:

1. `PATCH /api/monitors/drift/[id]` with `{ action: "accept" }`
2. Route looks up the recommendation's `currentField` (e.g., `freshness.maxHours`)
3. Determines target based on the monitor's resolved SLA source:
   - `direct_profile` or `direct_override` → update the SLA policy assignment overrides
   - `auto_discovered` → update the auto-discovered policy assignment (effectively promoting the recommendation into the discovered SLA)
   - `imported_dbt` → update the policy assignment overrides (preserves dbt import as base, layers the adjustment on top)
   - `branch` → update the branch assignment overrides
   - No SLA / `domain_default` / `criticality_default` → update the monitor's own `config` field
4. Applies the `recommendedValue` to the correct field
5. Marks recommendation as `accepted`, sets `reviewedAt`

When user clicks Edit:
- Inline editor appears on the card pre-filled with `recommendedValue`
- User adjusts the value
- On save: `PATCH` with `{ action: "accept_with_value", value: "user_value" }`
- Same apply flow but with user's custom value

---

## 8. Error Handling

- **LLM failure during analysis**: Log error, store partial results if any, set run status to `partial`. Don't discard the statistical work.
- **No drift detected**: Store an empty run (runId with zero recommendations). Summary tab shows "No drift detected in latest analysis" message.
- **Accept fails** (e.g., monitor deleted since recommendation): Show error toast, mark recommendation as dismissed with a note.
- **Insufficient data**: Monitors with <5 runs are skipped silently (unless they have an `auto_discovered` SLA, in which case the discovery baselines provide the reference). Summary shows "X monitors skipped (insufficient data)" in the stats bar.

---

## 10. Prerequisites

Before implementing the drift analyzer, the following gaps must be addressed:

1. **Persist uniqueness config** — the discovery API (`/api/lineage/discovery`) does not yet save uniqueness config to the `PolicyProfile`. Add `uniquenessConfig` Json field to the profile upsert so the drift analyzer can compare monitor results against discovered uniqueness baselines.
2. **Schema snapshot storage** — discovery computes full column baselines (name, type, nullable, ordinal) but this needs to be accessible for schema drift comparison. Currently stored in `schemaConfig` on the profile — verify this includes the column list, not just `strictness`/`allowEvolution`.

---

## 9. SLA Source Awareness

The drift analyzer is aware of all SLA policy sources in the resolution chain:

| Source | Drift Analysis Behavior |
|--------|------------------------|
| `direct_profile` | Compare monitor results against manually configured SLA thresholds |
| `direct_override` | Same as direct_profile — user-set overrides on a profile |
| `auto_discovered` | High-confidence recommendations — these SLAs were derived from warehouse system views (freshness, volume, quality, schema, uniqueness) via `sla_discovery.py`. The drift analyzer has newer monitor run data to refine the discovered baselines. Discovery snapshots (especially schema column lists and uniqueness PK columns) serve as the baseline reference for detecting drift. |
| `imported_dbt` | Note dbt origin in reasoning. Recommend adjustments when actual performance consistently differs from dbt-defined expectations. |
| `branch` | Evaluate whether branch-inherited SLA still fits the node's actual behavior |
| `domain_default` / `criticality_default` | Lower priority — these are broad defaults. Recommendations here suggest the node deserves a more specific SLA. |
| No SLA (`none`) | Flag monitors with no SLA that show consistent patterns — recommend creating an SLA based on observed behavior. |
