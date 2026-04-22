# Per-Asset Health Dashboard & SLA Writeback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Data Health section to show per-asset rows (with category filter pills) and make drift recommendation acceptance write to both monitor config and SLA PolicyAssignment overrides.

**Architecture:** Extend the monitor-trends API to include an `assets` grouping keyed by targetFqn. Refactor DriftSummaryTab to render category filter pills + asset rows with accordion sparklines. Add PolicyAssignment writeback to the drift accept endpoint.

**Tech Stack:** Next.js API routes (Prisma), React components, TypeScript

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/api/schedule/monitor-trends/route.ts` | Modify | Add `assets` grouping to response, add `category` to MonitorTrend |
| `components/monitors/AssetHealthRow.tsx` | Create | Compact asset row with category badges, progress bar, expandable sparklines |
| `components/monitors/DriftSummaryTab.tsx` | Modify | Replace category card grid with filter pills + asset rows |
| `app/api/drift/[id]/route.ts` | Modify | Add PolicyAssignment writeback on accept |

---

### Task 1: Add `assets` Grouping to Monitor Trends API

**Files:**
- Modify: `app/api/schedule/monitor-trends/route.ts`

- [ ] **Step 1: Add `category` field to MonitorTrend interface**

In `app/api/schedule/monitor-trends/route.ts`, find the `MonitorTrend` interface (around line 32) and add a `category` field:

```typescript
interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  category: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}
```

- [ ] **Step 2: Update `buildTrend` to accept and include category**

Find the `buildTrend` function (around line 123). Change its signature and return to include `category`:

```typescript
    function buildTrend(m: typeof allMonitors[0], category: string): MonitorTrend {
      const runs = m.runs.map((r) => ({
        value: r.value,
        status: r.status,
        at: r.startedAt.toISOString(),
      })).reverse();

      const values = runs.map((r) => r.value).filter((v): v is number => v !== null);
      const latestValue = values.length > 0 ? values[values.length - 1] : null;
      const baselineMean = values.length > 1
        ? values.slice(0, -1).reduce((a, b) => a + b, 0) / (values.length - 1)
        : null;
      const pctChange = latestValue !== null && baselineMean !== null && baselineMean !== 0
        ? ((latestValue - baselineMean) / baselineMean) * 100
        : null;

      return {
        id: m.id,
        name: m.name,
        targetFqn: m.targetFqn || '',
        category,
        latestStatus: m.lastStatus,
        latestValue,
        baselineMean: baselineMean !== null ? Math.round(baselineMean * 100) / 100 : null,
        pctChange: pctChange !== null ? Math.round(pctChange * 10) / 10 : null,
        runs,
      };
    }
```

- [ ] **Step 3: Update all `buildTrend` call sites to pass category**

In the data health loop (around line 169), change:
```typescript
      cat.monitors.push(buildTrend(m, category));
```

In the pipeline health loop (around line 194), change:
```typescript
      ph.monitors.push(buildTrend(m, 'pipeline'));
```

- [ ] **Step 4: Add assets grouping after data health loop**

After the "Derive status for each category" block (after line 175) and before the pipeline health section, add:

```typescript
    // Build per-asset grouping (data monitors only)
    interface AssetHealth {
      name: string;
      fqn: string;
      total: number;
      passing: number;
      warning: number;
      failing: number;
      status: 'stable' | 'warning' | 'drifting' | 'pending';
      monitors: MonitorTrend[];
    }

    const assets: Record<string, AssetHealth> = {};
    for (const m of dataMonitors) {
      const fqn = m.targetFqn || '';
      if (!fqn) continue;
      const category = MONITOR_TYPE_TO_CATEGORY[(m.monitorType || '').toUpperCase()];
      if (!category) continue;

      if (!assets[fqn]) {
        const parts = fqn.split('.');
        assets[fqn] = {
          name: parts[parts.length - 1] || fqn,
          fqn,
          total: 0,
          passing: 0,
          warning: 0,
          failing: 0,
          status: 'pending',
          monitors: [],
        };
      }

      const asset = assets[fqn];
      asset.total++;
      const ls = (m.lastStatus || '').toUpperCase();
      if (ls === 'PASS') asset.passing++;
      else if (ls === 'WARN') asset.warning++;
      else if (ls === 'FAIL' || ls === 'ERROR') asset.failing++;

      asset.monitors.push(buildTrend(m, category));
    }

    for (const asset of Object.values(assets)) {
      asset.status = deriveDataStatus(asset.passing, asset.warning, asset.failing, asset.total);
    }
```

- [ ] **Step 5: Add `assets` to the JSON response**

Change the return statement (around line 201) to include `assets`:

```typescript
    return NextResponse.json({
      dataHealth,
      assets,
      pipelineHealth,
      updatedAt: new Date().toISOString(),
    });
```

- [ ] **Step 6: Verify it compiles and commit**

```bash
npx tsc --noEmit 2>&1 | grep "monitor-trends" | head -5
git add app/api/schedule/monitor-trends/route.ts
git commit -m "feat: add per-asset grouping to monitor-trends API"
```

---

### Task 2: Create AssetHealthRow Component

**Files:**
- Create: `components/monitors/AssetHealthRow.tsx`

- [ ] **Step 1: Create the component**

Create `components/monitors/AssetHealthRow.tsx`:

```tsx
'use client';

import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SparklineChart } from './SparklineChart';

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  category: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface AssetHealth {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}

interface AssetHealthRowProps {
  asset: AssetHealth;
  expanded: boolean;
  onToggle: () => void;
  activeCategories: Set<string>;
  onRunAnalysis?: () => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  freshness: 'Fresh',
  volume: 'Vol',
  quality: 'Qual',
  schema: 'Schema',
  anomaly: 'Anom',
  uniqueness: 'Uniq',
};

const STATUS_DOT: Record<string, string> = {
  PASS: 'bg-emerald-500',
  WARN: 'bg-amber-500',
  FAIL: 'bg-red-500',
  ERROR: 'bg-red-500',
};

const SPARKLINE_COLORS: Record<string, string> = {
  PASS: '#34d399',
  WARN: '#fbbf24',
  FAIL: '#f87171',
  ERROR: '#f87171',
};

function formatValue(val: number | null): string {
  if (val === null) return '—';
  if (Math.abs(val) >= 1000) return `${(val / 1000).toFixed(1)}k`;
  if (Number.isInteger(val)) return val.toString();
  return val.toFixed(1);
}

export function AssetHealthRow({ asset, expanded, onToggle, activeCategories, onRunAnalysis }: AssetHealthRowProps) {
  // Group monitors by category for badge display
  const byCategory = new Map<string, { status: string; count: number }>();
  for (const m of asset.monitors) {
    if (activeCategories.size > 0 && !activeCategories.has(m.category)) continue;
    const existing = byCategory.get(m.category);
    const s = (m.latestStatus || '').toUpperCase();
    if (!existing) {
      byCategory.set(m.category, { status: s || 'PENDING', count: 1 });
    } else {
      existing.count++;
      // Worst status wins
      if (s === 'FAIL' || s === 'ERROR') existing.status = 'FAIL';
      else if (s === 'WARN' && existing.status === 'PASS') existing.status = 'WARN';
    }
  }

  const filteredMonitors = activeCategories.size > 0
    ? asset.monitors.filter((m) => activeCategories.has(m.category))
    : asset.monitors;

  const passPct = asset.total > 0 ? (asset.passing / asset.total) * 100 : 0;

  return (
    <div className="rounded-xl border border-[var(--subtle-border)] bg-[var(--surface)] overflow-hidden transition-all">
      {/* Row header */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-[var(--hover-bg)] transition-colors"
      >
        <ChevronRight className={cn(
          'w-4 h-4 text-[var(--muted)] transition-transform shrink-0',
          expanded && 'rotate-90',
        )} />

        {/* Asset name */}
        <div className="flex-1 min-w-0 text-left">
          <div className="text-[13px] font-medium text-[var(--text)] truncate">{asset.name}</div>
          <div className="text-[10px] text-[var(--text-faint)] font-mono truncate">{asset.fqn}</div>
        </div>

        {/* Category badges */}
        <div className="flex items-center gap-1.5 shrink-0">
          {Array.from(byCategory.entries()).map(([cat, info]) => (
            <div key={cat} className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[var(--overlay-bg)]">
              <div className={cn('w-1.5 h-1.5 rounded-full', STATUS_DOT[info.status] || 'bg-zinc-400')} />
              <span className="text-[9px] text-[var(--muted)] font-medium">{CATEGORY_LABELS[cat] || cat}</span>
            </div>
          ))}
        </div>

        {/* Pass count + progress */}
        <div className="flex items-center gap-2 shrink-0 w-24">
          <div className="flex-1">
            <div className="h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  asset.failing > 0 ? 'bg-red-500' : asset.warning > 0 ? 'bg-amber-500' : 'bg-emerald-500',
                )}
                style={{ width: `${passPct}%` }}
              />
            </div>
          </div>
          <span className={cn(
            'text-[12px] font-semibold tabular-nums',
            asset.failing > 0 ? 'text-red-500' : asset.warning > 0 ? 'text-amber-500' : 'text-emerald-500',
          )}>
            {asset.passing}/{asset.total}
          </span>
        </div>
      </button>

      {/* Expanded sparklines */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-[var(--subtle-border)]">
          <div className="flex items-center justify-between pt-3 mb-3">
            <span className="text-[11px] text-[var(--muted)]">Last 30 runs</span>
            {onRunAnalysis && (
              <button
                onClick={(e) => { e.stopPropagation(); onRunAnalysis(); }}
                className="text-[10px] font-medium text-[var(--accent)] bg-[var(--accent)]/10 px-2 py-0.5 rounded hover:bg-[var(--accent)]/20 transition-colors"
              >
                Run Analysis
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredMonitors.map((m) => {
              const status = (m.latestStatus || '').toUpperCase();
              const lineColor = SPARKLINE_COLORS[status] || '#34d399';
              const values = m.runs.map((r) => r.value);
              const catLabel = CATEGORY_LABELS[m.category] || m.category;

              return (
                <div key={m.id} className="bg-[var(--overlay-bg)] rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[9px] text-[var(--muted)] font-medium uppercase">{catLabel}</span>
                      <span className="text-[11px] font-medium text-[var(--text)] truncate">{m.name.split('—').pop()?.trim() || m.name}</span>
                    </div>
                    <span className={cn(
                      'text-[9px] font-medium px-1.5 py-0.5 rounded shrink-0',
                      status === 'PASS' ? 'bg-emerald-500/10 text-emerald-400' :
                      status === 'WARN' ? 'bg-amber-500/10 text-amber-400' :
                      status === 'FAIL' || status === 'ERROR' ? 'bg-red-500/10 text-red-400' :
                      'bg-zinc-500/10 text-[var(--muted)]',
                    )}>
                      {status || 'PENDING'}
                    </span>
                  </div>
                  <SparklineChart values={values} color={lineColor} />
                  <div className="flex items-center justify-between mt-1 text-[9px] text-[var(--muted)]">
                    <span>
                      {formatValue(m.latestValue)}
                      {m.baselineMean !== null && (
                        <span className="text-[var(--text-faint)]"> (avg {formatValue(m.baselineMean)})</span>
                      )}
                    </span>
                    {m.pctChange !== null && (
                      <span className={m.pctChange >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {m.pctChange >= 0 ? '+' : ''}{m.pctChange}%
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {filteredMonitors.length === 0 && (
            <p className="text-[11px] text-[var(--muted)] text-center py-4">No monitors match the selected filters</p>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/monitors/AssetHealthRow.tsx
git commit -m "feat: add AssetHealthRow component with category badges and sparklines"
```

---

### Task 3: Refactor DriftSummaryTab — Per-Asset Data Health

**Files:**
- Modify: `components/monitors/DriftSummaryTab.tsx`

This task replaces the category card grid with category filter pills and asset rows. Pipeline Health and SLA Recommendations sections stay as-is.

- [ ] **Step 1: Add imports and new types**

At the top of `components/monitors/DriftSummaryTab.tsx`, add the `AssetHealthRow` import alongside the existing `CategorySparklinePanel` import:

```typescript
import { AssetHealthRow } from './AssetHealthRow';
```

Add the `AssetHealth` interface alongside the existing `CategoryHealth`:

```typescript
interface AssetHealth {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}
```

Add `category: string;` to the existing `MonitorTrend` interface.

Update the `TrendData` interface to include `assets`:

```typescript
interface TrendData {
  dataHealth: Record<string, CategoryHealth>;
  assets: Record<string, AssetHealth>;
  pipelineHealth: Record<string, CategoryHealth>;
  updatedAt: string;
}
```

- [ ] **Step 2: Add category filter state and asset data derivation**

After the existing `const [showDriftSection, setShowDriftSection] = useState(false);` line, add:

```typescript
  const [activeCategories, setActiveCategories] = useState<Set<string>>(new Set());
```

Add a `toggleCategoryFilter` function after `toggleSection`:

```typescript
  const toggleCategoryFilter = (key: string) => {
    setActiveCategories((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };
```

Add an `assetList` derived from trendData after the existing `pipelineTools` memo:

```typescript
  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    let list = Object.values(trendData.assets);
    // Filter by active categories if any selected
    if (activeCategories.size > 0) {
      list = list.filter((a) => a.monitors.some((m) => activeCategories.has(m.category)));
    }
    // Sort: failing first, then warning, then stable
    list.sort((a, b) => {
      if (a.failing !== b.failing) return b.failing - a.failing;
      if (a.warning !== b.warning) return b.warning - a.warning;
      return a.name.localeCompare(b.name);
    });
    return list;
  }, [trendData, activeCategories]);
```

- [ ] **Step 3: Update auto-expand to use asset FQN**

Replace the existing auto-expand useEffect:

```typescript
  // Auto-expand the first asset with issues
  useEffect(() => {
    if (expandedSection !== null || !trendData?.assets) return;
    const failing = assetList.find((a) => a.status === 'drifting');
    const warning = assetList.find((a) => a.status === 'warning');
    const first = failing || warning || assetList[0];
    if (first) setExpandedSection(`asset-${first.fqn}`);
  }, [trendData]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 4: Replace the Data Health category card grid with filter pills + asset rows**

Replace the entire `{/* Data Health */}` section (from `{totalDataMonitors > 0 && (` to its closing `)}`) with:

```tsx
      {/* Data Health */}
      {totalDataMonitors > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold text-[var(--text)]">Data Health</h2>
              <span className="text-[11px] text-[var(--muted)]">{assetList.length} assets · {totalDataMonitors} monitors</span>
            </div>
            {trendData?.updatedAt && (
              <span className="text-[10px] text-[var(--muted)]">
                Updated {new Date(trendData.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>

          {/* Category filter pills */}
          <div className="flex items-center gap-1.5 mb-3">
            {dataCategories.map((cat) => {
              const isActive = activeCategories.has(cat.key);
              const style = STATUS_STYLES[cat.status] || STATUS_STYLES.pending;
              return (
                <button
                  key={cat.key}
                  onClick={() => toggleCategoryFilter(cat.key)}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-all border',
                    isActive
                      ? `${style.border} ${style.badgeBg} ${style.text}`
                      : 'border-transparent bg-[var(--overlay-bg)] text-[var(--muted)] hover:text-[var(--text)]',
                  )}
                >
                  <div className={cn('w-1.5 h-1.5 rounded-full', style.accent)} />
                  {cat.label}
                  <span className="opacity-60">{cat.passing}/{cat.total}</span>
                </button>
              );
            })}
          </div>

          {/* Asset rows */}
          <div className="space-y-2">
            {assetList.map((asset) => (
              <AssetHealthRow
                key={asset.fqn}
                asset={asset}
                expanded={expandedSection === `asset-${asset.fqn}`}
                onToggle={() => toggleSection(`asset-${asset.fqn}`)}
                activeCategories={activeCategories}
                onRunAnalysis={handleRunAnalysis}
              />
            ))}
          </div>

          {assetList.length === 0 && activeCategories.size > 0 && (
            <p className="text-[12px] text-[var(--muted)] text-center py-6">No assets have monitors in the selected categories</p>
          )}
        </div>
      )}
```

- [ ] **Step 5: Verify it compiles and renders**

```bash
npx tsc --noEmit 2>&1 | grep -i "DriftSummaryTab\|AssetHealthRow" | head -5
```

Start dev server, navigate to Monitors → Summary. Verify:
1. Category filter pills appear in a horizontal row
2. Asset rows show below with names, category badges, progress bars
3. Clicking a pill filters visible assets
4. Clicking an asset row expands sparklines
5. Pipeline Health and SLA Recommendations sections still work

- [ ] **Step 6: Commit**

```bash
git add components/monitors/DriftSummaryTab.tsx
git commit -m "feat: restructure Data Health to show per-asset rows with category filter pills"
```

---

### Task 4: SLA Recommendation Writeback

**Files:**
- Modify: `app/api/drift/[id]/route.ts`

- [ ] **Step 1: Add PolicyAssignment writeback after monitor config update**

In `app/api/drift/[id]/route.ts`, find the accept block (line 37-51). After the `prisma.monitor.update()` call (line 47-50) and before the `prisma.driftRecommendation.update()` call (line 53), add the SLA writeback:

```typescript
        // Write to SLA PolicyAssignment overrides
        try {
          const targetFqn = rec.targetFqn;
          if (targetFqn && section) {
            const parsedValue = isNaN(Number(applyValue)) ? applyValue : Number(applyValue);

            // Find existing direct assignment for this asset
            const existingAssignment = await prisma.policyAssignment.findFirst({
              where: {
                nodeFqn: targetFqn,
                assignmentType: 'direct',
                status: 'active',
                organization: { id: organizationId },
              },
            });

            if (existingAssignment) {
              // Update overrides on existing assignment
              const overrides = (existingAssignment.overrides as Record<string, any>) || {};
              if (!overrides[section]) overrides[section] = {};
              overrides[section][field] = parsedValue;
              await prisma.policyAssignment.update({
                where: { id: existingAssignment.id },
                data: { overrides },
              });
            } else {
              // Create new direct assignment with a default profile
              const defaultProfile = await prisma.policyProfile.findFirst({
                where: { organizationId, isBuiltIn: true },
              }) || await prisma.policyProfile.findFirst({
                where: { organizationId },
                orderBy: { createdAt: 'asc' },
              });

              if (defaultProfile) {
                await prisma.policyAssignment.create({
                  data: {
                    profileId: defaultProfile.id,
                    nodeFqn: targetFqn,
                    assignmentType: 'direct',
                    organizationId,
                    overrides: { [section]: { [field]: parsedValue } },
                  },
                });
              }
            }
          }
        } catch (slaErr) {
          // Non-fatal — monitor config was already updated
          console.warn('[Drift] SLA writeback failed (non-fatal):', slaErr);
        }
```

- [ ] **Step 2: Verify the full accept flow**

The complete accept block should now be:

```typescript
    if (action === 'accept' || action === 'accept_with_value') {
      const applyValue = action === 'accept_with_value' && value ? value : rec.recommendedValue;

      const [section, field] = rec.currentField.split('.');
      if (section && field && rec.monitor) {
        // 1. Write to monitor config (existing)
        const config = (rec.monitor.config as Record<string, any>) || {};
        config[rec.currentField.replace('.', '_')] = isNaN(Number(applyValue))
          ? applyValue
          : Number(applyValue);
        await prisma.monitor.update({
          where: { id: rec.monitorId },
          data: { config },
        });

        // 2. Write to SLA PolicyAssignment overrides (new)
        // ... (code from step 1)
      }

      await prisma.driftRecommendation.update({
        where: { id },
        data: { status: 'accepted', reviewedAt: new Date() },
      });

      return NextResponse.json({ ok: true, applied: applyValue });
    }
```

- [ ] **Step 3: Verify it compiles and commit**

```bash
npx tsc --noEmit 2>&1 | grep "drift" | head -5
git add "app/api/drift/[id]/route.ts"
git commit -m "feat: write drift recommendations to SLA PolicyAssignment overrides on accept"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] Data Health section shows per-asset rows sorted by health (failing first)
- [ ] Category filter pills show pass/total per category with colored dots
- [ ] Clicking a filter pill shows only assets with monitors of that type
- [ ] Multiple filter pills can be active simultaneously
- [ ] Clicking an asset row expands sparklines for all its monitors
- [ ] Auto-expands first failing asset on load
- [ ] Pipeline Health section still works with tool cards + accordion
- [ ] SLA Recommendations section still works (collapsed by default)
- [ ] Accepting a drift recommendation writes to both monitor.config AND PolicyAssignment.overrides
- [ ] If no direct PolicyAssignment exists, one is created with the default profile
- [ ] The SLA panel on the lineage page shows the updated value after accepting
