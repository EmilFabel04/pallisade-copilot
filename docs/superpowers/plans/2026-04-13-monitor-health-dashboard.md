# Monitor Health Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the empty Drift Analysis block on the Monitors Summary tab with an always-visible health dashboard showing Data Health (by category) and Pipeline Health (by tool) with accordion sparkline trend charts.

**Architecture:** New API endpoint queries MonitorRun history grouped by category/platform. `DriftSummaryTab` is refactored to render category status cards + tool status cards with accordion sparkline panels. Existing LLM drift analysis moves to a collapsed section below. Two new components: `CategorySparklinePanel` (accordion content) and `SparklineChart` (pure SVG).

**Tech Stack:** Next.js API route (Prisma), React components (inline SVG sparklines), TypeScript

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/api/schedule/monitor-trends/route.ts` | Create | API endpoint: query last 30 runs per monitor, group by category/platform |
| `components/monitors/SparklineChart.tsx` | Create | Pure SVG sparkline from array of values |
| `components/monitors/CategorySparklinePanel.tsx` | Create | Accordion panel: header + 2-col grid of sparkline cards |
| `components/monitors/DriftSummaryTab.tsx` | Modify | Replace with Data Health + Pipeline Health + SLA Recommendations |

---

### Task 1: API Endpoint — Monitor Trends

**Files:**
- Create: `app/api/schedule/monitor-trends/route.ts`

- [ ] **Step 1: Create the endpoint file with the category mapping and types**

Create `app/api/schedule/monitor-trends/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const MONITOR_TYPE_TO_CATEGORY: Record<string, string> = {
  FRESHNESS: 'freshness',
  VOLUME: 'volume',
  NULL_CHECK: 'quality',
  SCHEMA_CHANGE: 'schema',
  OUTLIER_DETECTION: 'anomaly',
  ANOMALY: 'anomaly',
  UNIQUENESS_CHECK: 'uniqueness',
  RANGE_VALIDATION: 'anomaly',
  ACCEPTED_VALUES: 'quality',
  DATE_CONSISTENCY: 'quality',
  DATA_TYPE_VALIDATION: 'schema',
};

const PIPELINE_MONITOR_TYPES = new Set([
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE', 'BI_CONTENT_HEALTH',
  'SERVER_HEALTH', 'CERTIFICATE', 'LOG_ANALYSIS',
]);

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface CategoryHealth {
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: 'stable' | 'warning' | 'drifting' | 'pending';
  monitors: MonitorTrend[];
}

function deriveDataStatus(passing: number, warning: number, failing: number, total: number): CategoryHealth['status'] {
  if (total === 0) return 'pending';
  if (passing + warning + failing === 0) return 'pending';
  if (failing > 0) return 'drifting';
  if (warning > 0) return 'warning';
  return 'stable';
}

function derivePipelineStatus(passing: number, warning: number, failing: number, total: number): 'healthy' | 'degraded' | 'down' | 'pending' {
  if (total === 0) return 'pending';
  if (passing + warning + failing === 0) return 'pending';
  if (failing === total) return 'down';
  if (failing > 0 || warning > 0) return 'degraded';
  return 'healthy';
}

export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    const stackId = request.nextUrl.searchParams.get('stackId');

    // Fetch all monitor groups for this org (optionally filtered by stack via monitors)
    const groups = await prisma.monitorGroup.findMany({
      where: {
        organizationId,
        watchType: { not: null },
      },
      include: {
        monitors: {
          select: {
            id: true,
            name: true,
            monitorType: true,
            targetFqn: true,
            lastStatus: true,
            enabled: true,
            runs: {
              orderBy: { startedAt: 'desc' },
              take: 30,
              select: {
                value: true,
                status: true,
                startedAt: true,
              },
            },
          },
        },
      },
    });

    // Build monitor trends
    const allMonitors = groups.flatMap((g) =>
      g.monitors.map((m) => ({
        ...m,
        anchorPlatform: g.anchorPlatform,
        watchType: g.watchType,
        groupName: g.name,
      }))
    );

    // Separate data vs pipeline monitors
    const dataMonitors = allMonitors.filter(
      (m) => MONITOR_TYPE_TO_CATEGORY[(m.monitorType || '').toUpperCase()] !== undefined
    );
    const pipelineMonitors = allMonitors.filter(
      (m) => PIPELINE_MONITOR_TYPES.has((m.monitorType || '').toUpperCase())
    );

    // Build data health by category
    const dataHealth: Record<string, CategoryHealth> = {};
    for (const m of dataMonitors) {
      const category = MONITOR_TYPE_TO_CATEGORY[(m.monitorType || '').toUpperCase()];
      if (!category) continue;

      if (!dataHealth[category]) {
        dataHealth[category] = { total: 0, passing: 0, warning: 0, failing: 0, status: 'pending', monitors: [] };
      }

      const cat = dataHealth[category];
      cat.total++;

      const ls = (m.lastStatus || '').toUpperCase();
      if (ls === 'PASS') cat.passing++;
      else if (ls === 'WARN') cat.warning++;
      else if (ls === 'FAIL' || ls === 'ERROR') cat.failing++;

      const runs = m.runs.map((r) => ({
        value: r.value,
        status: r.status,
        at: r.startedAt.toISOString(),
      })).reverse(); // oldest first for sparkline

      const values = runs.map((r) => r.value).filter((v): v is number => v !== null);
      const latestValue = values.length > 0 ? values[values.length - 1] : null;
      const baselineMean = values.length > 1
        ? values.slice(0, -1).reduce((a, b) => a + b, 0) / (values.length - 1)
        : null;
      const pctChange = latestValue !== null && baselineMean !== null && baselineMean !== 0
        ? ((latestValue - baselineMean) / baselineMean) * 100
        : null;

      cat.monitors.push({
        id: m.id,
        name: m.name,
        targetFqn: m.targetFqn || '',
        latestStatus: m.lastStatus,
        latestValue,
        baselineMean: baselineMean !== null ? Math.round(baselineMean * 100) / 100 : null,
        pctChange: pctChange !== null ? Math.round(pctChange * 10) / 10 : null,
        runs,
      });
    }

    // Derive status for each category
    for (const cat of Object.values(dataHealth)) {
      cat.status = deriveDataStatus(cat.passing, cat.warning, cat.failing, cat.total);
    }

    // Build pipeline health by platform
    const pipelineHealth: Record<string, { total: number; passing: number; warning: number; failing: number; status: string; monitors: MonitorTrend[] }> = {};
    for (const m of pipelineMonitors) {
      const platform = (m.anchorPlatform || m.watchType || 'other').toLowerCase();

      if (!pipelineHealth[platform]) {
        pipelineHealth[platform] = { total: 0, passing: 0, warning: 0, failing: 0, status: 'pending', monitors: [] };
      }

      const ph = pipelineHealth[platform];
      ph.total++;

      const ls = (m.lastStatus || '').toUpperCase();
      if (ls === 'PASS') ph.passing++;
      else if (ls === 'WARN') ph.warning++;
      else if (ls === 'FAIL' || ls === 'ERROR') ph.failing++;

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

      ph.monitors.push({
        id: m.id,
        name: m.name,
        targetFqn: m.targetFqn || '',
        latestStatus: m.lastStatus,
        latestValue,
        baselineMean: baselineMean !== null ? Math.round(baselineMean * 100) / 100 : null,
        pctChange: pctChange !== null ? Math.round(pctChange * 10) / 10 : null,
        runs,
      });
    }

    for (const ph of Object.values(pipelineHealth)) {
      ph.status = derivePipelineStatus(ph.passing, ph.warning, ph.failing, ph.total);
    }

    return NextResponse.json({
      dataHealth,
      pipelineHealth,
      updatedAt: new Date().toISOString(),
    });
  } catch (error: any) {
    console.error('[MonitorTrends] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
```

- [ ] **Step 2: Verify the endpoint returns data**

Start the dev server, then:

```bash
curl -s http://localhost:3000/api/schedule/monitor-trends | head -100
```

Expected: JSON response with `dataHealth` and `pipelineHealth` objects (may return 401 if not authenticated — that's fine, the shape is correct).

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/monitor-trends/route.ts
git commit -m "feat: add monitor-trends API endpoint for health dashboard"
```

---

### Task 2: SparklineChart Component

**Files:**
- Create: `components/monitors/SparklineChart.tsx`

- [ ] **Step 1: Create the SparklineChart component**

Create `components/monitors/SparklineChart.tsx`:

```tsx
'use client';

interface SparklineChartProps {
  /** Array of values to plot (oldest first) */
  values: (number | null)[];
  /** Line color (CSS color string) */
  color: string;
  /** Optional threshold line value */
  threshold?: number;
  /** SVG width */
  width?: number;
  /** SVG height */
  height?: number;
}

export function SparklineChart({
  values,
  color,
  threshold,
  width = 200,
  height = 40,
}: SparklineChartProps) {
  // Filter out nulls but keep indices for spacing
  const points = values.map((v, i) => ({ x: i, value: v }));
  const validPoints = points.filter((p): p is { x: number; value: number } => p.value !== null);

  if (validPoints.length < 2) {
    return (
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fill="var(--muted)" fontSize={10}>
          Not enough data
        </text>
      </svg>
    );
  }

  const minVal = Math.min(...validPoints.map((p) => p.value));
  const maxVal = Math.max(...validPoints.map((p) => p.value));
  const range = maxVal - minVal || 1;
  const padding = 4;
  const plotHeight = height - padding * 2;
  const plotWidth = width - padding * 2;

  const scaleX = (i: number) => padding + (i / (values.length - 1)) * plotWidth;
  const scaleY = (v: number) => padding + plotHeight - ((v - minVal) / range) * plotHeight;

  const polylinePoints = validPoints
    .map((p) => `${scaleX(p.x)},${scaleY(p.value)}`)
    .join(' ');

  const lastPoint = validPoints[validPoints.length - 1];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }}>
      {/* Threshold line */}
      {threshold !== undefined && threshold >= minVal && threshold <= maxVal && (
        <line
          x1={padding}
          y1={scaleY(threshold)}
          x2={width - padding}
          y2={scaleY(threshold)}
          stroke={color}
          strokeOpacity={0.25}
          strokeWidth={1}
          strokeDasharray="4,3"
        />
      )}
      {/* Sparkline */}
      <polyline
        points={polylinePoints}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Latest value dot */}
      <circle
        cx={scaleX(lastPoint.x)}
        cy={scaleY(lastPoint.value)}
        r={3}
        fill={color}
      />
    </svg>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/monitors/SparklineChart.tsx
git commit -m "feat: add SparklineChart SVG component"
```

---

### Task 3: CategorySparklinePanel Component

**Files:**
- Create: `components/monitors/CategorySparklinePanel.tsx`

- [ ] **Step 1: Create the CategorySparklinePanel component**

Create `components/monitors/CategorySparklinePanel.tsx`:

```tsx
'use client';

import { cn } from '@/lib/utils';
import { SparklineChart } from './SparklineChart';

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface CategorySparklinePanelProps {
  /** Category or tool label */
  label: string;
  /** Number of failing monitors */
  failingCount: number;
  /** Monitors with trend data */
  monitors: MonitorTrend[];
  /** Border color class for the panel */
  borderColor?: string;
  /** Optional: trigger LLM drift analysis for this category */
  onRunAnalysis?: () => void;
}

const STATUS_COLORS: Record<string, { bg: string; text: string; line: string }> = {
  PASS: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', line: '#34d399' },
  WARN: { bg: 'bg-amber-500/10', text: 'text-amber-400', line: '#fbbf24' },
  FAIL: { bg: 'bg-red-500/10', text: 'text-red-400', line: '#f87171' },
  ERROR: { bg: 'bg-red-500/10', text: 'text-red-400', line: '#f87171' },
};

function formatValue(val: number | null): string {
  if (val === null) return '—';
  if (Math.abs(val) >= 1000) return `${(val / 1000).toFixed(1)}k`;
  if (Number.isInteger(val)) return val.toString();
  return val.toFixed(1);
}

export function CategorySparklinePanel({
  label,
  failingCount,
  monitors,
  borderColor = 'border-[var(--subtle-border)]',
  onRunAnalysis,
}: CategorySparklinePanelProps) {
  return (
    <div className={cn('rounded-xl border bg-[var(--surface)] p-4', borderColor)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-[var(--text)]">{label}</span>
          {failingCount > 0 && (
            <span className="text-[10px] text-red-400 font-medium">{failingCount} failing</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-[var(--muted)]">Last 30 runs</span>
          {onRunAnalysis && (
            <button
              onClick={onRunAnalysis}
              className="text-[10px] font-medium text-[var(--accent)] bg-[var(--accent)]/10 px-2 py-0.5 rounded hover:bg-[var(--accent)]/20 transition-colors"
            >
              Run Analysis
            </button>
          )}
        </div>
      </div>

      {/* Sparkline grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {monitors.map((m) => {
          const status = (m.latestStatus || '').toUpperCase();
          const colors = STATUS_COLORS[status] || STATUS_COLORS.PASS;
          const values = m.runs.map((r) => r.value);

          return (
            <div key={m.id} className="bg-[var(--overlay-bg)] rounded-lg p-3">
              {/* Monitor header */}
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-medium text-[var(--text)] truncate">{m.name}</span>
                <span className={cn('text-[9px] font-medium px-1.5 py-0.5 rounded', colors.bg, colors.text)}>
                  {status || 'PENDING'}
                </span>
              </div>

              {/* Sparkline */}
              <SparklineChart values={values} color={colors.line} />

              {/* Summary */}
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

      {monitors.length === 0 && (
        <p className="text-[11px] text-[var(--muted)] text-center py-4">No run data yet</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/monitors/CategorySparklinePanel.tsx
git commit -m "feat: add CategorySparklinePanel accordion component"
```

---

### Task 4: Refactor DriftSummaryTab

**Files:**
- Modify: `components/monitors/DriftSummaryTab.tsx`

This is the main refactor. The component currently renders: (1) Data/Pipeline monitor summary cards, (2) Drift Analysis section. After refactor: (1) Data Health category cards + accordion, (2) Pipeline Health tool cards + accordion, (3) SLA Recommendations (existing drift analysis collapsed).

- [ ] **Step 1: Rewrite DriftSummaryTab.tsx**

Replace the entire contents of `components/monitors/DriftSummaryTab.tsx` with:

```tsx
'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Play, Activity, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';
import { CategorySparklinePanel } from './CategorySparklinePanel';
import type { WatchSummary } from '@/types/health-watch';
import type { ScheduledTask } from '@/types/schedule';

// ── Category / status config ──────────────────────────────────────────────────

const DATA_CATEGORIES = [
  { key: 'freshness', label: 'Freshness' },
  { key: 'volume', label: 'Volume' },
  { key: 'quality', label: 'Quality' },
  { key: 'schema', label: 'Schema' },
  { key: 'anomaly', label: 'Anomaly' },
  { key: 'uniqueness', label: 'Uniqueness' },
] as const;

const STATUS_STYLES: Record<string, { border: string; text: string; badge: string }> = {
  stable:   { border: 'border-emerald-500/30', text: 'text-emerald-400', badge: 'bg-emerald-500/10 text-emerald-400' },
  healthy:  { border: 'border-emerald-500/30', text: 'text-emerald-400', badge: 'bg-emerald-500/10 text-emerald-400' },
  warning:  { border: 'border-amber-500/30',   text: 'text-amber-400',   badge: 'bg-amber-500/10 text-amber-400' },
  degraded: { border: 'border-amber-500/30',   text: 'text-amber-400',   badge: 'bg-amber-500/10 text-amber-400' },
  drifting: { border: 'border-red-500/30',     text: 'text-red-400',     badge: 'bg-red-500/10 text-red-400' },
  down:     { border: 'border-red-500/30',     text: 'text-red-400',     badge: 'bg-red-500/10 text-red-400' },
  pending:  { border: 'border-[var(--subtle-border)]', text: 'text-[var(--muted)]', badge: 'bg-[var(--overlay-medium)] text-[var(--muted)]' },
};

const STATUS_LABELS: Record<string, string> = {
  stable: 'Stable', healthy: 'Healthy', warning: 'Warning',
  degraded: 'Degraded', drifting: 'Drifting', down: 'Down', pending: 'Pending',
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface CategoryHealth {
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}

interface TrendData {
  dataHealth: Record<string, CategoryHealth>;
  pipelineHealth: Record<string, CategoryHealth>;
  updatedAt: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  watches: WatchSummary[];
  tasks: ScheduledTask[];
  loading: boolean;
}

export function DriftSummaryTab({ watches, tasks, loading: monitorsLoading }: Props) {
  // Health dashboard state
  const [trendData, setTrendData] = useState<TrendData | null>(null);
  const [trendLoading, setTrendLoading] = useState(true);
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  // Existing drift analysis state
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [driftLoading, setDriftLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [showDriftSection, setShowDriftSection] = useState(false);

  // ── Fetch trend data ──────────────────────────────────────────────────────

  const fetchTrends = useCallback(async () => {
    try {
      const res = await fetch('/api/schedule/monitor-trends');
      if (res.ok) {
        const data = await res.json();
        setTrendData(data);
      }
    } catch (err) {
      console.error('[HealthDashboard] Fetch error:', err);
    } finally {
      setTrendLoading(false);
    }
  }, []);

  useEffect(() => { fetchTrends(); }, [fetchTrends]);

  // Refresh trends on the same interval as the monitors page poll (30s)
  useEffect(() => {
    const timer = setInterval(fetchTrends, 30000);
    return () => clearInterval(timer);
  }, [fetchTrends]);

  // ── Existing drift analysis handlers ──────────────────────────────────────

  const fetchRecommendations = useCallback(async () => {
    setDriftLoading(true);
    try {
      const res = await fetch('/api/drift?status=pending');
      if (res.ok) {
        const data = await res.json();
        setRecommendations(data.recommendations || []);
        setLastAnalyzedAt(data.lastAnalyzedAt);
        setCounts(data.counts || {});
      }
    } catch (err) {
      console.error('[DriftSummary] Fetch error:', err);
    } finally {
      setDriftLoading(false);
    }
  }, []);

  useEffect(() => { fetchRecommendations(); }, [fetchRecommendations]);

  const handleRunAnalysis = async () => {
    setRunning(true);
    try {
      const res = await fetch('/api/drift/run', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Analysis complete — ${data.recommendationCount} recommendation${data.recommendationCount !== 1 ? 's' : ''}`);
        fetchRecommendations();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Analysis failed');
      }
    } catch {
      toast.error('Failed to run analysis');
    } finally {
      setRunning(false);
    }
  };

  const handleAccept = async (id: string, value?: string) => {
    const action = value ? 'accept_with_value' : 'accept';
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, value }),
    });
    if (res.ok) {
      toast.success('Recommendation applied');
      fetchRecommendations();
    } else {
      toast.error('Failed to apply');
    }
  };

  const handleDismiss = async (id: string) => {
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'dismiss' }),
    });
    if (res.ok) {
      fetchRecommendations();
    } else {
      toast.error('Failed to dismiss');
    }
  };

  // ── Accordion toggle ──────────────────────────────────────────────────────

  const toggleSection = (key: string) => {
    setExpandedSection((prev) => (prev === key ? null : key));
  };

  // ── Derived data ──────────────────────────────────────────────────────────

  const dataCategories = useMemo(() => {
    if (!trendData) return [];
    return DATA_CATEGORIES
      .filter((cat) => trendData.dataHealth[cat.key])
      .map((cat) => ({
        ...cat,
        ...trendData.dataHealth[cat.key],
      }));
  }, [trendData]);

  const pipelineTools = useMemo(() => {
    if (!trendData) return [];
    return Object.entries(trendData.pipelineHealth).map(([key, data]) => ({
      key,
      label: key.charAt(0).toUpperCase() + key.slice(1),
      ...data,
    }));
  }, [trendData]);

  const totalDataMonitors = dataCategories.reduce((s, c) => s + c.total, 0);
  const totalPipelineMonitors = pipelineTools.reduce((s, t) => s + t.total, 0);
  const pending = counts.pending || 0;

  // ── Loading state ─────────────────────────────────────────────────────────

  if (trendLoading && monitorsLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  // No monitors at all
  if (totalDataMonitors === 0 && totalPipelineMonitors === 0 && !trendLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
        <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 w-full">

      {/* ── Data Health ──────────────────────────────────────────── */}
      {totalDataMonitors > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold text-[var(--text)]">Data Health</h2>
              <span className="text-[11px] text-[var(--muted)]">{totalDataMonitors} monitors</span>
            </div>
            {trendData?.updatedAt && (
              <span className="text-[10px] text-[var(--muted)]">
                Updated {new Date(trendData.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>

          {/* Category cards row */}
          <div className={cn('grid gap-2', `grid-cols-${Math.min(dataCategories.length, 6)}`)}>
            {dataCategories.map((cat) => {
              const style = STATUS_STYLES[cat.status] || STATUS_STYLES.pending;
              const isExpanded = expandedSection === `data-${cat.key}`;
              return (
                <button
                  key={cat.key}
                  onClick={() => toggleSection(`data-${cat.key}`)}
                  className={cn(
                    'rounded-lg border p-3 text-center transition-all hover:bg-[var(--hover-bg)]',
                    isExpanded ? `${style.border} bg-[var(--surface)]` : 'border-[var(--subtle-border)] bg-[var(--surface)]',
                    isExpanded && 'ring-1 ring-current/20',
                  )}
                >
                  <div className="text-[9px] text-[var(--muted)] uppercase tracking-wide mb-1">{cat.label}</div>
                  <div className={cn('text-[18px] font-semibold', cat.failing > 0 ? 'text-red-400' : cat.warning > 0 ? 'text-amber-400' : 'text-emerald-400')}>
                    {cat.passing}/{cat.total}
                  </div>
                  <div className={cn('text-[8px] font-medium mt-0.5', style.text)}>
                    {STATUS_LABELS[cat.status] || cat.status}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Accordion sparkline panel */}
          {dataCategories.map((cat) => {
            if (expandedSection !== `data-${cat.key}`) return null;
            const style = STATUS_STYLES[cat.status] || STATUS_STYLES.pending;
            return (
              <div key={cat.key} className="mt-2">
                <CategorySparklinePanel
                  label={cat.label}
                  failingCount={cat.failing}
                  monitors={cat.monitors}
                  borderColor={style.border}
                  onRunAnalysis={handleRunAnalysis}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* ── Pipeline Health ──────────────────────────────────────── */}
      {totalPipelineMonitors > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold text-[var(--text)]">Pipeline Health</h2>
              <span className="text-[11px] text-[var(--muted)]">{totalPipelineMonitors} monitors</span>
            </div>
          </div>

          {/* Tool cards row */}
          <div className={cn('grid gap-2', `grid-cols-${Math.min(pipelineTools.length, 6)}`)}>
            {pipelineTools.map((tool) => {
              const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
              const isExpanded = expandedSection === `pipeline-${tool.key}`;
              return (
                <button
                  key={tool.key}
                  onClick={() => toggleSection(`pipeline-${tool.key}`)}
                  className={cn(
                    'rounded-lg border p-3 text-center transition-all hover:bg-[var(--hover-bg)]',
                    isExpanded ? `${style.border} bg-[var(--surface)]` : 'border-[var(--subtle-border)] bg-[var(--surface)]',
                    isExpanded && 'ring-1 ring-current/20',
                  )}
                >
                  <div className="text-[9px] text-[var(--muted)] uppercase tracking-wide mb-1">{tool.label}</div>
                  <div className={cn('text-[18px] font-semibold', tool.failing > 0 ? 'text-red-400' : tool.warning > 0 ? 'text-amber-400' : 'text-emerald-400')}>
                    {tool.passing}/{tool.total}
                  </div>
                  <div className={cn('text-[8px] font-medium mt-0.5', style.text)}>
                    {STATUS_LABELS[tool.status] || tool.status}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Accordion sparkline panel */}
          {pipelineTools.map((tool) => {
            if (expandedSection !== `pipeline-${tool.key}`) return null;
            const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
            return (
              <div key={tool.key} className="mt-2">
                <CategorySparklinePanel
                  label={tool.label}
                  failingCount={tool.failing}
                  monitors={tool.monitors}
                  borderColor={style.border}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* ── SLA Recommendations (existing drift analysis) ────────── */}
      <div className="rounded-xl border border-[var(--subtle-border)] bg-[var(--surface)] overflow-hidden">
        <button
          onClick={() => setShowDriftSection(!showDriftSection)}
          className="w-full px-5 py-3 flex items-center justify-between hover:bg-[var(--hover-bg)] transition-colors"
        >
          <div className="flex items-center gap-3">
            <span className="text-[13px] font-medium text-[var(--muted)]">SLA Recommendations</span>
            {pending > 0 && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[var(--accent)]/10 text-[var(--accent)]">
                {pending} pending
              </span>
            )}
            {lastAnalyzedAt && (
              <span className="text-[10px] text-[var(--text-faint)]">
                Last run: {new Date(lastAnalyzedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[var(--text-faint)]">AI-powered threshold tuning</span>
            <ChevronDown className={cn('w-4 h-4 text-[var(--muted)] transition-transform', showDriftSection && 'rotate-180')} />
          </div>
        </button>

        {showDriftSection && (
          <div className="px-5 pb-5 border-t border-[var(--subtle-border)]">
            <div className="flex items-center justify-between pt-3 mb-4">
              <div className="flex items-center gap-2 text-[11px]">
                {(counts.accepted || 0) > 0 && <span className="text-emerald-400">{counts.accepted} applied</span>}
                {(counts.dismissed || 0) > 0 && <span className="text-zinc-400">{counts.dismissed} dismissed</span>}
              </div>
              <button
                onClick={handleRunAnalysis}
                disabled={running}
                className="flex items-center gap-1.5 px-4 py-1.5 text-[11px] font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                {running ? 'Analyzing...' : 'Run Analysis'}
              </button>
            </div>

            {driftLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
              </div>
            ) : recommendations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8">
                <Activity className="w-6 h-6 text-[var(--text-faint)] mb-2" />
                <p className="text-[12px] text-[var(--muted)]">No pending recommendations. Run an analysis to check for SLA drift.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {recommendations.map((rec) => (
                  <DriftRecommendationCard
                    key={rec.id}
                    rec={rec}
                    onAccept={handleAccept}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the build passes**

```bash
npx tsc --noEmit 2>&1 | grep -i "DriftSummaryTab\|SparklineChart\|CategorySparkline" | head -10
```

Expected: No errors related to the new/modified files.

- [ ] **Step 3: Verify in the browser**

Start the dev server, navigate to the Monitors page → Summary tab. Verify:
1. Data Health section appears with category cards showing pass/total counts
2. Clicking a category card expands the sparkline panel below
3. Clicking another category collapses the first and expands the new one
4. Pipeline Health section appears if pipeline monitors exist
5. SLA Recommendations section appears collapsed at the bottom
6. No more empty "No drift analysis results yet" block

- [ ] **Step 4: Commit**

```bash
git add components/monitors/DriftSummaryTab.tsx
git commit -m "feat: refactor DriftSummaryTab into monitor health dashboard

Replace summary cards + empty drift analysis block with:
- Data Health: category status cards with accordion sparklines
- Pipeline Health: tool status cards with accordion sparklines  
- SLA Recommendations: existing drift analysis, collapsed by default"
```

---

### Task 5: Fix Dynamic Grid Columns

**Files:**
- Modify: `components/monitors/DriftSummaryTab.tsx`

Tailwind CSS doesn't support dynamic class names like `` grid-cols-${n} ``. These need to be mapped to complete class strings.

- [ ] **Step 1: Replace dynamic grid classes**

In `DriftSummaryTab.tsx`, find both instances of:

```tsx
<div className={cn('grid gap-2', `grid-cols-${Math.min(dataCategories.length, 6)}`)}>
```

and

```tsx
<div className={cn('grid gap-2', `grid-cols-${Math.min(pipelineTools.length, 6)}`)}>
```

Replace each with a helper that uses complete class names. Add this function near the top of the file (after the imports):

```tsx
function gridColsClass(count: number): string {
  const map: Record<number, string> = {
    1: 'grid-cols-1',
    2: 'grid-cols-2',
    3: 'grid-cols-3',
    4: 'grid-cols-4',
    5: 'grid-cols-5',
    6: 'grid-cols-6',
  };
  return map[Math.min(count, 6)] || 'grid-cols-6';
}
```

Then replace the two grid divs:

```tsx
<div className={cn('grid gap-2', gridColsClass(dataCategories.length))}>
```

```tsx
<div className={cn('grid gap-2', gridColsClass(pipelineTools.length))}>
```

- [ ] **Step 2: Verify grid renders correctly**

Check in the browser that the category cards fill the available width correctly (6 cards in a row for data health).

- [ ] **Step 3: Commit**

```bash
git add components/monitors/DriftSummaryTab.tsx
git commit -m "fix: use static Tailwind grid column classes instead of dynamic interpolation"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] Data Health section shows category cards (Freshness, Volume, Quality, Schema, Anomaly, Uniqueness) with correct pass/total from latest runs
- [ ] Clicking a category card expands sparkline panel; clicking another collapses the first (accordion)
- [ ] Sparklines render with correct colors (green=PASS, amber=WARN, red=FAIL)
- [ ] Pipeline Health section groups monitors by tool/platform
- [ ] SLA Recommendations section is collapsed by default, expandable
- [ ] "Run Analysis" button in sparkline panel triggers LLM drift analysis
- [ ] Dashboard updates on 30s poll interval
- [ ] Categories with no monitors are hidden
- [ ] First-time users with no monitors see empty state message
- [ ] Works in both light and dark mode
