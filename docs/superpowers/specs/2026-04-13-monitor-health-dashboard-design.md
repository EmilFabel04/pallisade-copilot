# Monitor Health Dashboard

**Date:** 2026-04-13
**Status:** Approved

## Overview

Replace the empty "Drift Analysis" block on the Monitors Summary tab with an always-visible Monitor Health Dashboard. The dashboard shows live health status derived from monitor run results — no manual "Run Analysis" needed for the core view.

Two sections: **Data Health** (by monitor category) and **Pipeline Health** (by connected tool/platform). Each section has compact status cards that expand into per-monitor sparkline trend charts via an accordion.

The existing LLM-based drift analysis (SLA threshold recommendations) moves to a collapsed section below the dashboard.

---

## Data Health Section

### Category Status Cards

Six cards displayed in a single row, one per monitor category:

| Category | Source Monitor Types |
|----------|---------------------|
| Freshness | FRESHNESS |
| Volume | VOLUME |
| Quality | NULL_CHECK, ACCEPTED_VALUES, DATE_CONSISTENCY |
| Schema | SCHEMA_CHANGE, DATA_TYPE_VALIDATION |
| Anomaly | OUTLIER_DETECTION, ANOMALY, RANGE_VALIDATION |
| Uniqueness | UNIQUENESS_CHECK |

This mapping already exists in `scanner/monitors/drift_analyzer.py` as `MONITOR_TYPE_TO_CATEGORY`.

Each card shows:

- **Category label** (uppercase, small)
- **Pass/Total count** (e.g. "4/4") — derived from the latest run status of each monitor in that category
- **Status badge**:
  - `Stable` (green) — all monitors PASS
  - `Warning` (amber) — at least one WARN, no FAIL
  - `Drifting` (red) — at least one FAIL
  - `Pending` (grey) — monitors exist but no runs yet
- **Border color** matches status (green/amber/red)

Cards are clickable. Clicking a card toggles the sparkline panel below it (accordion — only one category open at a time).

### Sparkline Panel (Accordion)

When a category card is clicked, an expandable panel appears directly below the status row. Only one panel is open at a time — clicking a different card collapses the current panel and opens the new one.

The panel contains:

- **Header**: Category name, count of failing monitors, "Last 30 runs" label, "Run Analysis" button (triggers LLM drift analysis scoped to this category)
- **Grid of sparkline cards** (2 columns): One card per monitor in the category

Each sparkline card shows:

- **Monitor target name** (e.g. table name like "customers")
- **Status badge**: PASS / WARN / FAIL / ERROR from latest run
- **SVG sparkline**: Last 30 run values plotted as a polyline. The line color matches the latest status (green for PASS, amber for WARN, red for FAIL). A dot marks the latest value. For monitors with thresholds, a dashed line shows the threshold level.
- **Summary line**: Current value with unit, baseline average in parentheses, and % change from baseline

Sparklines are rendered as inline SVG — no charting library needed. The data is an array of `{ value, status }` objects from the API.

---

## Pipeline Health Section

### Tool Status Cards

One card per connected tool/platform that has pipeline monitors. Cards are derived by grouping pipeline monitors by their `anchorPlatform` field (from the monitor group) or by the monitor's associated integration tool type.

Each card shows the same layout as data health cards:

- **Tool name** (e.g. BigQuery, dbt, Airflow, GitHub)
- **Pass/Total count**
- **Status badge**:
  - `Healthy` (green) — all monitors PASS
  - `Degraded` (amber) — at least one WARN or FAIL
  - `Down` (red) — all monitors FAIL

Cards are clickable with the same accordion behavior — expands to show per-monitor sparklines for that tool.

---

## SLA Recommendations Section

The existing LLM drift analysis moves below the dashboard as a collapsed section:

- **Header**: "SLA Recommendations" label, pending count badge, "Run Analysis" button
- **Subtitle**: "AI-powered threshold tuning based on historical trends"
- **Expandable**: Clicking opens the existing filter tabs + recommendation cards grid (current `DriftSummaryTab` content)

This section is visually subordinate — smaller text, muted colors, separated by a border. It's supplementary to the live health view.

---

## API Endpoint

### `GET /api/schedule/monitor-trends`

**Query params:**
- `stackId` (required) — Pipeline stack ID

**Response:**

```json
{
  "dataHealth": {
    "freshness": {
      "total": 4,
      "passing": 4,
      "warning": 0,
      "failing": 0,
      "status": "stable",
      "monitors": [
        {
          "id": "mon_123",
          "name": "customers",
          "targetFqn": "bigquery.dataset.customers",
          "latestStatus": "PASS",
          "latestValue": 2.5,
          "baselineMean": 3.1,
          "pctChange": -19.4,
          "runs": [
            { "value": 3.2, "status": "PASS", "at": "2026-04-12T08:00:00Z" },
            { "value": 2.8, "status": "PASS", "at": "2026-04-11T08:00:00Z" }
          ]
        }
      ]
    },
    "volume": { ... },
    "quality": { ... },
    "schema": { ... },
    "anomaly": { ... },
    "uniqueness": { ... }
  },
  "pipelineHealth": {
    "bigquery": {
      "total": 2,
      "passing": 2,
      "warning": 0,
      "failing": 0,
      "status": "healthy",
      "monitors": [ ... ]
    },
    "airflow": { ... }
  },
  "updatedAt": "2026-04-13T10:00:00Z"
}
```

**Implementation:**

The endpoint queries all monitors for the given stack (via monitor groups), joins with the last 30 MonitorRun records per monitor, and groups them by category (data monitors) or platform (pipeline monitors).

The category mapping uses the same `MONITOR_TYPE_TO_CATEGORY` mapping from `drift_analyzer.py`, duplicated as a TypeScript constant in the frontend.

For pipeline monitors, grouping is by the monitor group's `anchorPlatform` field. If `anchorPlatform` is null, fall back to the monitor group's `watchType` or the group name.

Status derivation:
- Data health: `stable` (all PASS), `warning` (any WARN, no FAIL), `drifting` (any FAIL), `pending` (no runs)
- Pipeline health: `healthy` (all PASS), `degraded` (any non-PASS), `down` (all FAIL), `pending` (no runs)

---

## Component Changes

### `DriftSummaryTab.tsx` — Major Refactor

Currently this component renders:
1. Data Monitors / Pipeline Monitors summary cards
2. Drift Analysis section (filter tabs + recommendation cards)

After refactor:
1. **Data Health section** — category status cards + accordion sparkline panels
2. **Pipeline Health section** — tool status cards + accordion sparkline panels  
3. **SLA Recommendations section** — collapsed, contains existing drift analysis UI

The existing summary cards ("Data Monitors: 26 passing / 0 failing" and "Pipeline Monitors") are replaced by the category/tool status rows which provide more granular information.

### New: `CategorySparklinePanel.tsx`

Renders the accordion content for a single category:
- Header with category name, failing count, "Run Analysis" button
- 2-column grid of sparkline cards
- Each sparkline card: monitor name, status badge, inline SVG sparkline, summary stats

### New: `SparklineChart.tsx`

Small component that renders a single SVG sparkline from an array of values:
- Accepts: `values: number[]`, `color: string`, `threshold?: number`, `width/height`
- Renders: polyline, optional threshold dashed line, endpoint dot
- No external dependencies — pure SVG

---

## State Management

The `DriftSummaryTab` component manages:

- `trendData` — response from `/api/schedule/monitor-trends`, fetched on mount and refreshed by the existing 30s poll interval
- `expandedCategory` — which category/tool is currently expanded (`null` for collapsed). Only one at a time.

The existing drift recommendations state (`recommendations`, `lastAnalyzedAt`, etc.) remains unchanged and powers the SLA Recommendations section.

---

## Edge Cases

- **No monitors at all**: Show the existing "Create Monitor" empty state. The health dashboard doesn't render.
- **Monitors exist but never run**: Cards show "0/N" with `Pending` badge in grey. Sparklines show "No run data yet" placeholder.
- **Category has no monitors**: That category card is hidden entirely (e.g. if user has no Uniqueness monitors, only 5 cards show).
- **Pipeline has no monitors**: Pipeline Health section is hidden entirely.
- **Only one category exists**: Status row renders a single card, still clickable for sparklines.

---

## Files to Modify

| File | Change |
|------|--------|
| `app/api/schedule/monitor-trends/route.ts` | New endpoint — queries monitors + runs, groups by category/platform |
| `components/monitors/DriftSummaryTab.tsx` | Major refactor — replace with Data Health + Pipeline Health + SLA Recommendations |
| `components/monitors/CategorySparklinePanel.tsx` | New — accordion content with sparkline grid |
| `components/monitors/SparklineChart.tsx` | New — pure SVG sparkline component |
| `components/monitors/DriftRecommendationCard.tsx` | No change — reused in SLA Recommendations section |

---

## Testing

- Verify category cards show correct pass/total counts from latest monitor run statuses
- Verify clicking a category card expands sparkline panel and collapses any other open panel
- Verify sparkline charts render correctly with 1, 2, 10, 30 data points
- Verify pipeline health cards group correctly by `anchorPlatform`
- Verify "Run Analysis" button in sparkline panel triggers LLM drift analysis
- Verify the dashboard updates on the 30s poll interval
- Verify empty states: no monitors, no runs, single category
- Verify SLA Recommendations section shows existing drift recommendation cards
