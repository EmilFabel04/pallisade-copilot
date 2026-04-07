# Tool Health Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add single-monitor-per-tool health monitoring with pre-selected checks, configurable thresholds, drill-in breakdown, and summary alerts — while removing the Quick Setup presets from the monitor creation flow.

**Architecture:** Hybrid composite approach — the UI presents one "Tool Health" monitor per tool, but under the hood individual monitors are created per check category. The existing `MonitorGroup` aggregation + `WatchDetailPanel` drill-in handles the composite view. No new execution engine needed.

**Tech Stack:** Next.js (React), TypeScript, Tailwind CSS, existing monitor catalog + health-watch types.

**Spec:** `docs/superpowers/specs/2026-04-07-tool-health-monitoring-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `types/health-watch.ts` | Add `tool_health` watch type |
| Modify | `types/monitor-catalog.ts` | Add default threshold constants per domain |
| Modify | `components/schedule/MultiMonitorModal.tsx` | Remove presets, add tool health creation flow, remove name field |
| Modify | `components/schedule/WatchCard.tsx` | Tool health badge/domain label |
| Modify | `components/schedule/WatchDetailPanel.tsx` | Tool health category breakdown styling |

---

### Task 1: Add `tool_health` Watch Type

**Files:**
- Modify: `types/health-watch.ts:12-29` (WatchType union + labels)
- Modify: `types/health-watch.ts:31-39` (descriptions)
- Modify: `types/health-watch.ts:54-97` (default scope configs)

- [ ] **Step 1: Add `tool_health` to the WatchType union**

In `types/health-watch.ts`, add `'tool_health'` to the `WatchType` union:

```typescript
export type WatchType =
  | 'pipeline_health'
  | 'dashboard_shield'
  | 'source_guard'
  | 'model_quality'
  | 'data_drift'
  | 'full_pipeline'
  | 'tool_health'       // <-- add
  | 'custom_watch';
```

- [ ] **Step 2: Add label and description**

Add to `WATCH_TYPE_LABELS`:
```typescript
tool_health: 'Tool Health',
```

Add to `WATCH_TYPE_DESCRIPTIONS`:
```typescript
tool_health: 'Holistic health monitoring for a pipeline tool — checks all relevant categories with configurable thresholds.',
```

- [ ] **Step 3: Add default scope config**

Add to `DEFAULT_SCOPE_CONFIGS`:
```typescript
tool_health: {
  maxDepth: 0,
  maxNodes: 1,
  maxMonitors: 12,
  domainFilters: [],
},
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to `tool_health`.

- [ ] **Step 5: Commit**

```bash
git add types/health-watch.ts
git commit -m "feat: add tool_health watch type to health-watch types"
```

---

### Task 2: Add Default Threshold Constants

**Files:**
- Modify: `types/monitor-catalog.ts:767` (after `DOMAIN_MONITOR_MAP`)

- [ ] **Step 1: Add TOOL_HEALTH_DEFAULTS constant**

Add after the `DOMAIN_MONITOR_MAP` export (line ~767) in `types/monitor-catalog.ts`:

```typescript
/**
 * Default thresholds for tool health monitors per domain.
 * Used to pre-populate config when creating tool_health watches.
 * Keys match monitor definition config_schema field keys.
 */
export const TOOL_HEALTH_DEFAULTS: Record<string, Record<string, Record<string, any>>> = {
  ingestion: {
    SYNC_LAG: { max_lag_minutes: 120 },
    FAILED_SYNCS: { lookback_hours: 24 },
    CONNECTOR_SCHEMA_DRIFT: {},
  },
  orchestration: {
    DAG_LAST_RUN: { max_stale_hours: 48 },
    DAG_SCHEDULE_LAG: { max_lag_minutes: 30 },
    TASK_FAILURE_RATE: { max_failure_pct: 10, lookback_hours: 24 },
  },
  transform: {
    DBT_TEST_FAILURES: { include_warnings: false },
    DBT_MODEL_FRESHNESS: { max_hours: 24 },
    DBT_SOURCE_FRESHNESS: {},
  },
  warehouse: {
    QUERY_PERFORMANCE: { query_time_threshold_seconds: 300, lookback_hours: 24 },
    COST_ANOMALY: { cost_spike_multiplier: 1.5, lookback_days: 7 },
    STORAGE_GROWTH: { growth_rate_multiplier: 2.0, lookback_days: 30 },
  },
  bi: {
    BI_FRESHNESS_PROXY: { max_stale_hours: 24, check_upstream: true },
    BI_UPSTREAM_BREAK_RISK: { lookback_hours: 24 },
    BI_CONTENT_HEALTH: { check_deliveries: true },
    BI_REFRESH_FAILURE: { lookback_hours: 24 },
  },
  infrastructure: {
    CERTIFICATE: { warn_days: 30, fail_days: 7 },
    SERVER_HEALTH: {},
    LOG_ANALYSIS: {},
  },
};
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add types/monitor-catalog.ts
git commit -m "feat: add TOOL_HEALTH_DEFAULTS threshold constants per domain"
```

---

### Task 3: Remove Quick Setup Presets from MultiMonitorModal

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx`

This task removes all preset-related code and UI from the modal. The "Monitors" tab becomes just the per-node monitor toggle grid.

- [ ] **Step 1: Remove the `Preset` interface and `PRESETS` array**

Delete lines 95-188 (the `Preset` interface and entire `PRESETS` constant array).

- [ ] **Step 2: Remove `activePreset` state**

In the component state section (~line 492), remove:
```typescript
const [activePreset, setActivePreset] = useState<string | null>(null);
```

- [ ] **Step 3: Remove preset-related reset in useEffect**

In the `useEffect` that resets state when modal opens (~line 541), remove:
```typescript
setActivePreset(null);
```

- [ ] **Step 4: Remove `applyPreset` callback**

Delete the entire `applyPreset` callback (lines ~791-830).

- [ ] **Step 5: Remove `presetMonitorCounts` memo**

Delete the entire `presetMonitorCounts` useMemo (lines ~833-849).

- [ ] **Step 6: Remove `activePreset` from `applyPreset` call in toggleMonitor and toggleAllForNode**

In `toggleMonitor` callback (~line 879), remove:
```typescript
setActivePreset(null);
```

In `toggleAllForNode` callback (~line 893), remove:
```typescript
setActivePreset(null);
```

- [ ] **Step 7: Remove `activePreset` from handleCreate dependency**

In `handleCreate` (~line 1135), change `mode: activePreset || 'manual'` to `mode: 'manual'`.

Remove `activePreset` from the dependency array of `handleCreate`.

- [ ] **Step 8: Remove the Quick Setup UI section**

Delete the entire "Quick Setup" section from Step 2's presets tab. This is the block from line ~1330 (`<div className="shrink-0 px-6 py-4 border-b border-[var(--border)]">`) through the closing `</div>` of the presets grid (~line 1372). This includes:
- The "Quick Setup" heading
- The "— choose a preset or toggle monitors manually below" text
- The entire preset button grid

- [ ] **Step 9: Remove activePreset badge from Step 2 header stats**

In the header stats area (~line 1407-1416), remove the `activePreset` badge:
```typescript
{activePreset && (
  <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--accent)]/15 text-[var(--accent)]">
    {PRESETS.find((p) => p.key === activePreset)?.label}
  </span>
)}
{!activePreset && checkedCount > 0 && (
  <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-white/10 text-[var(--muted)]">
    Custom
  </span>
)}
```

Replace with just a static label when monitors are selected:
```typescript
{checkedCount > 0 && (
  <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-white/10 text-[var(--muted)]">
    Custom
  </span>
)}
```

- [ ] **Step 10: Remove activePreset badge from Step 3**

In Step 3 (~line 1679-1685), remove the entire `activePreset` badge block:
```typescript
{activePreset && configTab === 'presets' && (
  <div className="text-center">
    <span className="px-3 py-1 rounded-full text-[11px] font-medium bg-[var(--accent)]/10 text-[var(--accent)]">
      {PRESETS.find((p) => p.key === activePreset)?.label}
    </span>
  </div>
)}
```

- [ ] **Step 11: Verify TypeScript compiles and no remaining references**

Run: `npx tsc --noEmit --pretty 2>&1 | head -30`
Run: `grep -n 'activePreset\|PRESETS\|applyPreset\|presetMonitorCounts\|Preset' components/schedule/MultiMonitorModal.tsx`
Expected: No matches (other than possibly `ConfigTab` which uses `'presets'` as tab key — that's fine, it's the tab identifier not the quick-setup feature).

- [ ] **Step 12: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: remove Quick Setup presets from monitor creation flow"
```

---

### Task 4: Auto-Enable Tool Monitors with Default Thresholds

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx`

When a tool node is selected and the user moves to Step 2, all domain-specific monitors should be pre-checked with default threshold configs populated.

- [ ] **Step 1: Import TOOL_HEALTH_DEFAULTS**

At the top of `MultiMonitorModal.tsx`, add `TOOL_HEALTH_DEFAULTS` to the import from `@/types/monitor-catalog`:

```typescript
import { getMonitorDefinition, DOMAIN_MONITOR_MAP, TOOL_HEALTH_DEFAULTS } from '@/types/monitor-catalog';
```

- [ ] **Step 2: Auto-check tool monitors when preview loads**

Add a `useEffect` after the `preview` memo (~line 691) that auto-checks all tool monitors and seeds their configs when preview first loads:

```typescript
// Auto-check all tool monitors with default thresholds when preview loads
useEffect(() => {
  if (!preview || previewLoading) return;

  const metaById = new Map(allNodeMeta.map((m) => [m.id, m]));
  const autoChecks: Record<string, boolean> = {};
  const autoConfigs: Record<string, Record<string, any>> = {};

  for (const nid of selectedNodeIds) {
    const meta = metaById.get(nid);
    if (!meta?.subNodeIds?.length) continue;
    const domain = meta.domain || '';
    const domainDefaults = TOOL_HEALTH_DEFAULTS[domain];
    if (!domainDefaults) continue;

    for (const group of preview.groups) {
      if (group.anchor_id !== meta.id) continue;
      for (const rec of group.recommendations) {
        const checkKey = `${rec.target_node_id}::${rec.monitor_key}`;
        autoChecks[checkKey] = true;
        const defaults = domainDefaults[rec.monitor_key];
        if (defaults && Object.keys(defaults).length > 0) {
          autoConfigs[checkKey] = { ...defaults };
        }
      }
    }
  }

  if (Object.keys(autoChecks).length > 0) {
    setMonitorChecks((prev) => ({ ...prev, ...autoChecks }));
    setMonitorConfigs((prev) => {
      const merged = { ...prev };
      for (const [k, v] of Object.entries(autoConfigs)) {
        merged[k] = { ...(prev[k] || {}), ...v };
      }
      return merged;
    });
  }
}, [preview, previewLoading]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: auto-enable tool monitors with default thresholds on selection"
```

---

### Task 5: Set watch_type to `tool_health` for Tool Groups

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx`

- [ ] **Step 1: Change synthetic tool group watch_type**

In the `preview` useMemo that injects synthetic tool monitor groups (~line 671), change:

```typescript
watch_type: 'tool_monitor',
```

to:

```typescript
watch_type: 'tool_health',
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: use tool_health watch type for synthetic tool monitor groups"
```

---

### Task 6: Remove Name Field & Auto-Generate Name

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx`

- [ ] **Step 1: Replace planName state with auto-generated name**

Replace the `planName` state declaration (~line 506):

```typescript
const [planName, setPlanName] = useState('');
```

with a computed name:

```typescript
const [planNameOverride, setPlanNameOverride] = useState('');
```

Then add an auto-generated name memo after the `selectedNodesWithMonitors` memo:

```typescript
const autoGeneratedName = useMemo(() => {
  if (configTab === 'ai-prompt') return 'AI Monitor';
  const names: string[] = [];
  for (const { meta } of selectedNodesWithMonitors) {
    if (meta.subNodeIds?.length) {
      names.push(`${meta.name} Health`);
    } else {
      names.push(`${meta.name} Monitor`);
    }
  }
  if (names.length === 0) return 'Monitor';
  if (names.length === 1) return names[0];
  return `${names[0]} +${names.length - 1} more`;
}, [selectedNodesWithMonitors, configTab]);

const planName = autoGeneratedName;
```

- [ ] **Step 2: Remove the name input from Step 3 UI**

In Step 3 (~lines 1648-1658), remove the entire "Name" section:

```typescript
{/* Name */}
<div>
  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Name</label>
  <input
    value={planName}
    onChange={(e) => setPlanName(e.target.value)}
    placeholder="e.g. Production Pipeline Health"
    className="w-full px-4 py-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[14px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)] text-center"
    autoFocus
  />
</div>
```

Replace with a display of the auto-generated name:

```typescript
{/* Auto-generated name */}
<div className="text-center">
  <span className="text-[14px] font-medium text-[var(--text)]">{planName}</span>
</div>
```

- [ ] **Step 3: Update canGoNext — remove planName validation**

In `canGoNext` (~line 992), change the Step 3 case:

```typescript
case 3:
  return planName.trim().length > 0;
```

to:

```typescript
case 3:
  return true;
```

- [ ] **Step 4: Update the Step 3 title for AI prompt tab**

Change the AI prompt title from "Name Your AI Monitor" to "Finalize Your AI Monitor" (~line 1632):

```typescript
{configTab === 'ai-prompt' ? 'Finalize Your AI Monitor' : 'Finalize Your Monitor'}
```

- [ ] **Step 5: Clean up unused references**

Remove `setPlanName` from the reset `useEffect`:
```typescript
setPlanName('');
```

Remove `planName` from `handleCreate` dependency array if it's listed there (it shouldn't cause issues as a memo, but clean up).

- [ ] **Step 6: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: auto-generate monitor name, remove manual name input"
```

---

### Task 7: Tool Health Badge on WatchCard

**Files:**
- Modify: `components/schedule/WatchCard.tsx`

- [ ] **Step 1: Read WatchCard.tsx**

Read the full file to understand its current structure.

- [ ] **Step 2: Add domain badge for tool_health watch type**

The `WatchCard` already shows `watchType` labels. Add special handling for `tool_health` watches to show the tool's domain as a colored badge. Find where the watch type label is rendered and add a condition:

If `watch.watchType === 'tool_health'`, render the `anchorPlatform` as a domain-colored badge next to the title using the `DOMAIN_COLORS` mapping (import from `MultiMonitorModal.tsx` or define locally if not already available).

The exact code depends on the current WatchCard structure — read the file first and add the badge next to the existing watch type label, using this pattern:

```typescript
{watch.watchType === 'tool_health' && watch.anchorPlatform && (
  <span className={cn(
    'px-1.5 py-0.5 rounded text-[10px] font-medium',
    DOMAIN_COLORS[watch.anchorPlatform?.toLowerCase()] || 'bg-white/10 text-white/50',
  )}>
    {watch.anchorPlatform}
  </span>
)}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/schedule/WatchCard.tsx
git commit -m "feat: add domain badge to WatchCard for tool_health watches"
```

---

### Task 8: Tool Health Category Breakdown in WatchDetailPanel

**Files:**
- Modify: `components/schedule/WatchDetailPanel.tsx`

- [ ] **Step 1: Read WatchDetailPanel.tsx**

Read the full file to understand the current detail view structure — especially how monitors are listed and how failure groups are displayed.

- [ ] **Step 2: Add tool health category grouping**

For `tool_health` watches, group the monitors list by their monitor type category (ingestion, orchestration, etc.) and show each category as a collapsible section with:
- Status icon (worst status among monitors in that category)
- Category label
- Monitor count (pass/fail)

Find the section that renders the individual monitor list and wrap it with a conditional:

```typescript
{watch.watchType === 'tool_health' ? (
  // Group monitors by category for tool health
  <div className="space-y-2">
    {Object.entries(
      watch.monitors.reduce<Record<string, typeof watch.monitors>>((acc, mon) => {
        const def = getMonitorDefinition(mon.monitorType || '');
        const cat = def?.category || 'other';
        if (!acc[cat]) acc[cat] = [];
        acc[cat].push(mon);
        return acc;
      }, {})
    ).map(([category, monitors]) => {
      const worstStatus = monitors.some((m) => m.lastStatus === 'FAIL') ? 'FAIL'
        : monitors.some((m) => m.lastStatus === 'WARN') ? 'WARN'
        : monitors.some((m) => m.lastStatus === 'PASS') ? 'PASS'
        : 'PENDING';
      const catLabel = MONITOR_CATEGORY_LABELS[category as MonitorCategory] || category;
      return (
        <div key={category} className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-center gap-2 px-3 py-2">
            {/* Status dot */}
            <span className={cn('w-2 h-2 rounded-full', {
              'bg-emerald-400': worstStatus === 'PASS',
              'bg-amber-400': worstStatus === 'WARN',
              'bg-red-400': worstStatus === 'FAIL',
              'bg-[var(--muted)]/40': worstStatus === 'PENDING',
            })} />
            <span className="text-[12px] font-medium text-[var(--text)]">{catLabel}</span>
            <span className="text-[10px] text-[var(--muted)] ml-auto">
              {monitors.filter((m) => m.lastStatus === 'PASS').length}/{monitors.length} passing
            </span>
          </div>
          {/* Individual monitors in category */}
          <div className="px-3 pb-2 space-y-1">
            {monitors.map((mon) => (
              /* render each monitor row — reuse existing monitor row rendering */
            ))}
          </div>
        </div>
      );
    })}
  </div>
) : (
  // Existing flat monitor list for non-tool watches
  /* existing code */
)}
```

The exact implementation depends on the current WatchDetailPanel structure — read the file first and adapt this pattern to fit the existing rendering. Import `getMonitorDefinition` and `MONITOR_CATEGORY_LABELS` from `@/types/monitor-catalog`.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/schedule/WatchDetailPanel.tsx
git commit -m "feat: add category-grouped monitor breakdown for tool_health watches"
```

---

### Task 9: Verify End-to-End Flow

**Files:** None (testing only)

- [ ] **Step 1: Verify TypeScript compilation**

Run: `npx tsc --noEmit --pretty 2>&1 | tail -5`
Expected: No errors.

- [ ] **Step 2: Verify no broken imports**

Run: `grep -rn "PRESETS\|applyPreset\|presetMonitorCounts\|activePreset" components/schedule/MultiMonitorModal.tsx`
Expected: No matches.

- [ ] **Step 3: Verify tool_health type is used consistently**

Run: `grep -rn "tool_health" types/ components/`
Expected: References in `health-watch.ts`, `MultiMonitorModal.tsx`, `WatchCard.tsx`, `WatchDetailPanel.tsx`.

- [ ] **Step 4: Verify TOOL_HEALTH_DEFAULTS is imported and used**

Run: `grep -rn "TOOL_HEALTH_DEFAULTS" types/ components/`
Expected: Defined in `monitor-catalog.ts`, imported in `MultiMonitorModal.tsx`.

- [ ] **Step 5: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: address verification issues in tool health monitoring"
```
