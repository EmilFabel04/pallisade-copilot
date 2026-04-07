# Tool Health Monitoring Design

## Problem

Pipeline tools (Fivetran, Airflow, dbt, BigQuery, Tableau, etc.) don't have SLAs like data assets. Users need a way to monitor tool health holistically — one monitor per tool that checks everything relevant, with drill-in to see what's wrong.

## Approach: Hybrid Composite (Approach C)

Clean single-monitor UX backed by individual monitors under the hood. The existing `MonitorGroup` aggregation and `WatchDetailPanel` drill-in handle the composite view. No new execution engine needed.

---

## Monitor Creation Flow

### Current (3 steps)
1. Select assets from lineage
2. Configure monitors (presets/quick setup + manual toggles)
3. Name, schedule, alerts

### New (3 steps)
1. Select assets from lineage (unchanged)
2. Configure monitors — **context-sensitive based on selection**:
   - **Tool node**: Single "Tool Health" card with domain-specific checks pre-enabled as a categorized checklist. User can toggle categories and adjust thresholds. AI Prompt tab available.
   - **Data asset**: Manual monitor toggle grid (FRESHNESS, VOLUME, etc.) — no presets. AI Prompt tab available.
   - **Mix of both**: Tool monitors grouped under their tool, data monitors grouped under their asset.
3. Schedule + alert channels. **Name field removed** — auto-generated as `"{ToolName} Health"`.

### Removed
- Entire "Quick Setup" presets section (11 preset buttons, `PRESETS` array, `applyPreset()`, `presetMonitorCounts`, `activePreset` state).

---

## Per-Tool Check Categories

Checks determined by `DOMAIN_MONITOR_MAP`. All pre-enabled with sensible defaults.

| Tool Domain | Checks | Default Thresholds |
|---|---|---|
| **Ingestion** (Fivetran, Airbyte, Stitch) | Sync Status, Failed Syncs, Schema Drift | Sync lag > 2x schedule = warn; any failure = fail; any drift = warn |
| **Orchestration** (Airflow, Prefect, Dagster, n8n) | Last Run, Schedule Lag, Task Failure Rate | No run in 2x schedule = warn; lag > 30min = warn; failure rate > 10% = fail |
| **Transform** (dbt) | Test Failures, Model Freshness, Source Freshness | Any test failure = fail; model stale > 24h = warn; source stale > 12h = warn |
| **Warehouse** (BigQuery, Snowflake, etc.) | Query Performance, Cost Anomaly, Storage Growth | Latency > 2x baseline = warn; cost > 3x avg = fail; storage spike > 50% = warn |
| **BI** (Tableau, Looker, Power BI, Metabase) | Freshness Proxy, Upstream Break Risk, Content Health, Refresh Failure | Stale > 24h = warn; broken upstream = fail; any refresh failure = fail |
| **Infrastructure** | Certificate Expiry, Server Health, Log Analysis | Cert < 30d = warn, < 7d = fail; CPU/mem > 90% = fail; error rate spike = warn |

### UI for check categories (Step 2, tool node selected)
Each check shows as a row:
- Toggle (on/off, all on by default)
- Category name + short description
- Threshold inputs (collapsed by default, expand on click)
- "Reset to default" per category

---

## Backend

### Creation
- One `MonitorGroup` with `watchType: 'tool_health'`, `anchorFqn` = tool FQN
- Individual `Monitor` records per enabled check category, linked to group
- `scopeConfig` stores tool domain, enabled categories, threshold overrides
- Name auto-generated: `"{ToolName} Health"`

### Execution
- Group's monitors run individually via existing monitor execution engine
- Each produces a `MonitorResult` with status, value, threshold, message

### Aggregation
- Existing `MonitorGroup` health calculation: pass=1.0, warn=0.5, fail=0.0
- Failure categories via existing `MONITOR_TYPE_TO_FAILURE_CATEGORY` mapping
- `WatchCard` displays aggregate; `WatchDetailPanel` shows per-category breakdown

### Alerting
- One consolidated summary alert per group run
- Format: `"Fivetran Health: 3 issues — 2 sync failures (connectors X, Y), 1 schema drift (connector Z)"`
- Fires on worst individual status

---

## UI

### WatchCard (Pipeline Monitors tab)
- Tool icon + auto-generated name
- Status bar: pass/warn/fail distribution across categories
- Stats: total checks, passing, warnings, failures
- Domain badge (e.g., "INGESTION")
- Last run + schedule

### WatchDetailPanel (drill-in)
- Health score (0-100) with status badge
- Category breakdown: collapsible rows per check category showing:
  - Status icon (pass/warn/fail)
  - Category name
  - Measured value vs threshold
  - Affected targets (e.g., specific connectors)
- Inline threshold editing with "Reset to default"
- Run history timeline
- Alert config

### Tool detail page (lineage node click)
- Same WatchDetailPanel rendered on the tool's page
- Shows linked tool health monitor if exists
- "Create Monitor" button if none exists

---

## Files to Change

### Remove presets
- `components/schedule/MultiMonitorModal.tsx`: Delete `PRESETS`, `Preset`, `applyPreset()`, `presetMonitorCounts`, `activePreset`, "Quick Setup" UI section

### New tool health creation flow
- `components/schedule/MultiMonitorModal.tsx`: New Step 2 branch for tool nodes — category checklist with threshold config, pre-enabled defaults
- `types/monitor-catalog.ts`: Add default threshold definitions per domain/monitor type

### Monitor group changes
- Add `'tool_health'` to `WatchType` union in `types/health-watch.ts`
- `components/schedule/WatchCard.tsx`: Tool health badge/styling
- `components/schedule/WatchDetailPanel.tsx`: Category breakdown view for tool_health groups

### Name removal
- `components/schedule/MultiMonitorModal.tsx`: Remove name input from Step 3. Auto-generate: `"{ToolName} Health"` for tools, `"{AssetName} Monitor"` for data assets.

### Backend
- `scanner/monitors/tools.py`: Default threshold constants per domain
- `app/api/schedule/plans/route.ts`: Handle `tool_health` watch type creation
