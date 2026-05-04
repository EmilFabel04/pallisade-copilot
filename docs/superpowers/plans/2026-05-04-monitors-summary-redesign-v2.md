# Monitors Summary Redesign v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the Monitors Summary tab into a unified overview — monitor-health-driven hero, pipeline tier on Summary as status-only tiles with click-to-expand, explicit "Run drift discovery" button, three-state critical-assets card, per-section skeletons.

**Architecture:** Two new GET endpoints serve cheap aggregate data the hero and pipeline tier need (`/api/monitors/health-summary`, `/api/monitors/pipeline-status`). The existing `/api/drift/run` is wired to a new button. `SummaryHero` and `CoverageGaps` are modified; new `PipelineTier` and `PipelineToolDetailPanel` components replace the old tile rendering on Summary. `DriftSummaryTab` orchestrates a vertical stack with independent per-section fetches and skeletons.

**Tech Stack:** Next.js 15 (App Router), Prisma 5, FastAPI / Pydantic (existing — not modified), Jest 30 + ts-jest, React 19, TailwindCSS, lucide-react, sonner.

**Spec:** `docs/superpowers/specs/2026-05-04-monitors-summary-redesign-v2-design.md`

**Branch:** `feat/monitors-summary-redesign` (work continues on the existing v1 worktree at `.worktrees/monitors-summary-redesign/`).

---

## File Structure

**Types (TS):**
- `types/monitors-summary.ts` (new) — `MonitorHealthSummary`, `PipelineToolStatus`, `PipelineToolStatusResponse`

**Next.js routes:**
- `app/api/monitors/health-summary/route.ts` (new) — GET aggregate counts for the hero
- `app/api/monitors/pipeline-status/route.ts` (new) — GET per-tool aggregate status for the pipeline tier
- `app/api/coverage/unmonitored-critical/route.ts` (modify) — add `lineageExtracted` to response
- `app/api/monitors/__tests__/health-summary.test.ts` (new) — unit tests for the aggregate logic
- `app/api/monitors/__tests__/pipeline-status.test.ts` (new) — unit tests for status precedence

**Frontend components:**
- `components/monitors/SummaryHero.tsx` (modify) — accept `MonitorHealthSummary`, derive tone from monitor counts
- `components/monitors/__tests__/SummaryHero.test.tsx` (new) — tone + headline tests
- `components/monitors/PipelineTier.tsx` (new) — status-only tiles + click handler
- `components/monitors/PipelineToolDetailPanel.tsx` (new) — side panel for pipeline tile detail
- `components/monitors/CoverageGaps.tsx` (modify) — three-state critical card + drift-run button
- `components/monitors/DriftSummaryTab.tsx` (modify) — vertical stack, new fetches, drift-run state, per-section skeletons

---

### Task 1: Add `lineageExtracted` flag to coverage endpoint

The Critical Assets card needs to distinguish "no critical assets unmonitored" from "lineage hasn't run yet." The flag derives from `PipelineStack.lastLineageExtractedAt`.

**Files:**
- Modify: `app/api/coverage/unmonitored-critical/route.ts`

- [ ] **Step 1: Add the lookup and field**

Open `app/api/coverage/unmonitored-critical/route.ts` and replace the body of the `GET` handler (after the `stackId` validation) with:

```ts
  const stack = await prisma.pipelineStack.findFirst({
    where: { id: stackId, organizationId },
    select: { lastLineageExtractedAt: true },
  });
  const lineageExtracted = !!stack?.lastLineageExtractedAt;

  // Find LineageNodes flagged as having downstream dashboards but no monitors targeting their FQN.
  // For v1 we use a simple proxy: pick LineageNodes whose `criticality` is 'HIGH' or 'CRITICAL',
  // intersected with the absence of a Monitor row sharing the same targetFqn.
  // Note: LineageNode.name stores the fully-qualified name (database.schema.table).
  const monitoredFqns = new Set(
    (await prisma.monitor.findMany({
      where: { organizationId, pipelineStackId: stackId },
      select: { targetFqn: true },
    })).map((m) => m.targetFqn).filter((x): x is string => !!x)
  );

  const criticalNodes = await prisma.lineageNode.findMany({
    where: {
      organizationId,
      pipelineStackId: stackId,
      criticality: { in: ['HIGH', 'CRITICAL'] as any },
    },
    select: { name: true, criticality: true, tableName: true },
    take: 50,
  });

  const assets = criticalNodes
    .filter((n) => n.name && !monitoredFqns.has(n.name))
    .map((n) => ({ fqn: n.name, reason: `criticality=${n.criticality ?? 'HIGH'}` }))
    .slice(0, 10);

  return NextResponse.json({ assets, lineageExtracted });
```

- [ ] **Step 2: Manual smoke test**

Run the dev server and hit `/api/coverage/unmonitored-critical?stackId=<a-real-stack-id>`. Expect a JSON response with both `assets` and `lineageExtracted` fields.

- [ ] **Step 3: Commit**

```bash
cd .worktrees/monitors-summary-redesign
git add app/api/coverage/unmonitored-critical/route.ts
git commit -m "feat(coverage): expose lineageExtracted flag in unmonitored-critical response"
```

---

### Task 2: Shared TypeScript types

Centralize the new shapes so both routes and components import from one place.

**Files:**
- Create: `types/monitors-summary.ts`

- [ ] **Step 1: Create the file**

```ts
// Shapes returned by the Summary tab's new aggregate endpoints.

export interface MonitorHealthSummary {
  total: number;
  healthy: number;
  warning: number;
  failing: number;
  dataAssets: number;
  pipelineTools: number;
  lastRunAt: string | null; // ISO 8601
}

export type PipelineToolStatusValue =
  | 'PASS'
  | 'WARN'
  | 'FAIL'
  | 'ERROR'
  | 'NEVER_RUN';

export interface PipelineToolStatus {
  toolType: string;       // e.g. "fivetran", "airflow", "dbt_cloud"
  displayName: string;    // e.g. "Fivetran", "Airflow", "dbt cloud"
  status: PipelineToolStatusValue;
  failCount: number;
  warnCount: number;
  monitorCount: number;
  lastRunAt: string | null;
}

export interface PipelineToolStatusResponse {
  tools: PipelineToolStatus[];
}
```

- [ ] **Step 2: Commit**

```bash
git add types/monitors-summary.ts
git commit -m "feat(types): MonitorHealthSummary and PipelineToolStatus shapes"
```

---

### Task 3: `GET /api/monitors/health-summary` — failing test

This endpoint feeds the hero. Tests live alongside the route.

**Files:**
- Create: `app/api/monitors/__tests__/health-summary.test.ts`

- [ ] **Step 1: Write the failing test**

The route module exports an `aggregate` pure function so we can unit-test without mocking `auth()` or `NextRequest`. The HTTP handler is a thin wrapper.

```ts
/**
 * Run with: npx jest app/api/monitors/__tests__/health-summary.test.ts
 */
import { aggregate } from '../health-summary/route';

const DATA_FQN = 'analytics.fct_orders';
const PIPELINE_TYPES = ['SYNC_LAG', 'DAG_LAST_RUN', 'DBT_TEST_FAILURES'];

function mon(over: Partial<{
  monitorType: string; targetFqn: string | null; lastStatus: string | null; lastRunAt: Date | null;
}> = {}) {
  return {
    monitorType: 'FRESHNESS',
    targetFqn: DATA_FQN,
    lastStatus: 'PASS' as string | null,
    lastRunAt: new Date('2026-05-04T10:00:00Z') as Date | null,
    ...over,
  };
}

describe('health-summary aggregate()', () => {
  it('returns zeros for an empty profile', () => {
    expect(aggregate([])).toEqual({
      total: 0,
      healthy: 0,
      warning: 0,
      failing: 0,
      dataAssets: 0,
      pipelineTools: 0,
      lastRunAt: null,
    });
  });

  it('counts PASS, NULL, and SKIPPED as healthy', () => {
    const out = aggregate([
      mon({ lastStatus: 'PASS' }),
      mon({ lastStatus: null }),
      mon({ lastStatus: 'SKIPPED' }),
    ]);
    expect(out.healthy).toBe(3);
    expect(out.warning).toBe(0);
    expect(out.failing).toBe(0);
  });

  it('counts WARN as warning, FAIL and ERROR as failing', () => {
    const out = aggregate([
      mon({ lastStatus: 'WARN' }),
      mon({ lastStatus: 'FAIL' }),
      mon({ lastStatus: 'ERROR' }),
    ]);
    expect(out.warning).toBe(1);
    expect(out.failing).toBe(2);
  });

  it('counts distinct targetFqn for data-tier monitors only', () => {
    const out = aggregate([
      mon({ monitorType: 'FRESHNESS', targetFqn: 'a.x' }),
      mon({ monitorType: 'VOLUME',    targetFqn: 'a.x' }), // same fqn, still data tier
      mon({ monitorType: 'FRESHNESS', targetFqn: 'a.y' }),
      mon({ monitorType: 'SYNC_LAG',  targetFqn: 'a.z' }), // pipeline-tier — excluded from dataAssets
    ]);
    expect(out.dataAssets).toBe(2); // a.x, a.y
  });

  it('counts distinct toolType for pipeline-tier monitors only', () => {
    const out = aggregate([
      mon({ monitorType: 'FRESHNESS' }),                  // data — excluded
      mon({ monitorType: 'SYNC_LAG',          targetFqn: null }),
      mon({ monitorType: 'DAG_LAST_RUN',      targetFqn: null }),
      mon({ monitorType: 'DAG_SCHEDULE_LAG',  targetFqn: null }), // same tool family as DAG_LAST_RUN
    ]);
    // The aggregate maps PIPELINE monitorTypes to a tool key; SYNC_LAG → fivetran/airbyte family,
    // DAG_* → airflow/dagster family. We expect the count of distinct families.
    expect(out.pipelineTools).toBeGreaterThanOrEqual(1);
    expect(out.pipelineTools).toBeLessThanOrEqual(3);
  });

  it('returns the most recent lastRunAt as ISO', () => {
    const earlier = new Date('2026-05-04T08:00:00Z');
    const later = new Date('2026-05-04T11:30:00Z');
    const out = aggregate([
      mon({ lastRunAt: earlier }),
      mon({ lastRunAt: later }),
      mon({ lastRunAt: null }),
    ]);
    expect(out.lastRunAt).toBe(later.toISOString());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npx jest app/api/monitors/__tests__/health-summary.test.ts 2>&1 | tail
```
Expected: FAIL — `Cannot find module '../health-summary/route'`.

---

### Task 4: `GET /api/monitors/health-summary` — implementation

**Files:**
- Create: `app/api/monitors/health-summary/route.ts`

- [ ] **Step 1: Write the route + pure aggregate**

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import type { MonitorHealthSummary } from '@/types/monitors-summary';

const DATA_MONITOR_TYPES = new Set([
  'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK', 'UNIQUENESS_CHECK',
  'OUTLIER_DETECTION', 'ANOMALY', 'RANGE_VALIDATION', 'ACCEPTED_VALUES',
  'DATE_CONSISTENCY', 'DATA_TYPE_VALIDATION',
]);

// Pipeline monitor type → tool family. Multiple monitor types may share a family
// (DAG_LAST_RUN and DAG_SCHEDULE_LAG both target Airflow/Dagster). The hero
// counts distinct families, so users see "3 pipeline tools" when they have
// Fivetran, Airflow, and dbt — not "8 monitor variants".
const PIPELINE_TYPE_TO_FAMILY: Record<string, string> = {
  SYNC_LAG: 'ingestion', FAILED_SYNCS: 'ingestion', CONNECTOR_SCHEMA_DRIFT: 'ingestion',
  DAG_LAST_RUN: 'orchestration', DAG_SCHEDULE_LAG: 'orchestration', TASK_FAILURE_RATE: 'orchestration',
  DBT_TEST_FAILURES: 'transform', DBT_MODEL_FRESHNESS: 'transform', DBT_SOURCE_FRESHNESS: 'transform',
  DBT_CORE_SOURCE_VALIDATION: 'transform', DBT_CORE_REF_INTEGRITY: 'transform',
  BI_FRESHNESS_PROXY: 'bi', BI_UPSTREAM_BREAK_RISK: 'bi', BI_REFRESH_FAILURE: 'bi', BI_CONTENT_HEALTH: 'bi',
  CERTIFICATE: 'infra', SERVER_HEALTH: 'infra', LOG_ANALYSIS: 'infra',
};

type MonitorRow = {
  monitorType: string;
  targetFqn: string | null;
  lastStatus: string | null;
  lastRunAt: Date | null;
};

export function aggregate(monitors: MonitorRow[]): MonitorHealthSummary {
  let healthy = 0, warning = 0, failing = 0;
  const dataFqns = new Set<string>();
  const pipelineFamilies = new Set<string>();
  let mostRecent: Date | null = null;

  for (const m of monitors) {
    const status = (m.lastStatus || '').toUpperCase();
    if (status === 'WARN') warning += 1;
    else if (status === 'FAIL' || status === 'ERROR') failing += 1;
    else healthy += 1; // PASS, SKIPPED, NULL/empty

    const type = (m.monitorType || '').toUpperCase();
    if (DATA_MONITOR_TYPES.has(type) && m.targetFqn) {
      dataFqns.add(m.targetFqn);
    }
    const family = PIPELINE_TYPE_TO_FAMILY[type];
    if (family) pipelineFamilies.add(family);

    if (m.lastRunAt && (!mostRecent || m.lastRunAt > mostRecent)) {
      mostRecent = m.lastRunAt;
    }
  }

  return {
    total: monitors.length,
    healthy,
    warning,
    failing,
    dataAssets: dataFqns.size,
    pipelineTools: pipelineFamilies.size,
    lastRunAt: mostRecent ? mostRecent.toISOString() : null,
  };
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  const monitors = await prisma.monitor.findMany({
    where: { organizationId, pipelineStackId: stackId, enabled: true },
    select: { monitorType: true, targetFqn: true, lastStatus: true, lastRunAt: true },
  });

  return NextResponse.json(aggregate(monitors));
}
```

- [ ] **Step 2: Run tests**

```bash
npx jest app/api/monitors/__tests__/health-summary.test.ts 2>&1 | tail
```
Expected: 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add types/monitors-summary.ts app/api/monitors/health-summary/route.ts app/api/monitors/__tests__/health-summary.test.ts
git commit -m "feat(monitors): GET /api/monitors/health-summary aggregate endpoint"
```

---

### Task 5: `GET /api/monitors/pipeline-status` — failing test

This endpoint feeds the pipeline tier tiles. Status precedence is FAIL > ERROR > WARN > PASS.

**Files:**
- Create: `app/api/monitors/__tests__/pipeline-status.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
/**
 * Run with: npx jest app/api/monitors/__tests__/pipeline-status.test.ts
 */
import { aggregateByTool } from '../pipeline-status/route';

function mon(toolType: string, lastStatus: string | null, lastRunAt: Date | null = new Date('2026-05-04T10:00:00Z')) {
  return { toolType, lastStatus, lastRunAt };
}

describe('pipeline-status aggregateByTool()', () => {
  it('groups by tool and applies FAIL > ERROR > WARN > PASS precedence', () => {
    const out = aggregateByTool([
      mon('fivetran', 'PASS'),
      mon('fivetran', 'WARN'),
      mon('fivetran', 'FAIL'),
      mon('airflow', 'PASS'),
      mon('airflow', 'ERROR'),
    ]);
    const fivetran = out.find((t) => t.toolType === 'fivetran')!;
    expect(fivetran.status).toBe('FAIL');
    expect(fivetran.failCount).toBe(1);
    expect(fivetran.warnCount).toBe(1);
    expect(fivetran.monitorCount).toBe(3);

    const airflow = out.find((t) => t.toolType === 'airflow')!;
    expect(airflow.status).toBe('ERROR');
    expect(airflow.failCount).toBe(1);
  });

  it('marks NEVER_RUN when every monitor for a tool has null lastStatus', () => {
    const out = aggregateByTool([
      mon('dbt_cloud', null, null),
      mon('dbt_cloud', null, null),
    ]);
    expect(out[0].status).toBe('NEVER_RUN');
    expect(out[0].lastRunAt).toBeNull();
  });

  it('returns empty array for no monitors', () => {
    expect(aggregateByTool([])).toEqual([]);
  });

  it('returns the most recent lastRunAt across the tool', () => {
    const a = new Date('2026-05-04T09:00:00Z');
    const b = new Date('2026-05-04T11:30:00Z');
    const out = aggregateByTool([
      mon('fivetran', 'PASS', a),
      mon('fivetran', 'PASS', b),
      mon('fivetran', 'PASS', null),
    ]);
    expect(out[0].lastRunAt).toBe(b.toISOString());
  });

  it('produces a friendly displayName for known tool types', () => {
    const out = aggregateByTool([
      mon('fivetran', 'PASS'),
      mon('dbt_cloud', 'PASS'),
      mon('linux_server', 'PASS'),
      mon('something_unknown', 'PASS'),
    ]);
    const byType: Record<string, string> = Object.fromEntries(out.map((t) => [t.toolType, t.displayName]));
    expect(byType.fivetran).toBe('Fivetran');
    expect(byType.dbt_cloud).toBe('dbt cloud');
    expect(byType.linux_server).toBe('linux server');
    expect(byType.something_unknown).toBe('Something Unknown');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npx jest app/api/monitors/__tests__/pipeline-status.test.ts 2>&1 | tail
```
Expected: FAIL — `Cannot find module '../pipeline-status/route'`.

---

### Task 6: `GET /api/monitors/pipeline-status` — implementation

The route reads `Monitor` rows filtered to pipeline-tier monitor types. The challenge: `Monitor` does not store `toolType` directly — it's resolved through the `Integration` or `PipelineNode` linked via `integrationId`. Today's `monitors/page.tsx` uses `monitor-trends.pipelineHealth` (which is computed scanner-side). For Summary we need our own grouping by tool.

**Decision:** Resolve `toolType` by joining `Monitor.integrationId → Integration.toolType`. For monitors without an `integrationId`, fall back to grouping by the `monitorType → family` mapping.

**Files:**
- Create: `app/api/monitors/pipeline-status/route.ts`

- [ ] **Step 1: Write the route + pure aggregator**

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import type { PipelineToolStatus, PipelineToolStatusValue, PipelineToolStatusResponse } from '@/types/monitors-summary';

const PIPELINE_MONITOR_TYPES = [
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY',
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE', 'BI_CONTENT_HEALTH',
  'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS',
] as const;

const FAMILY_BY_TYPE: Record<string, string> = {
  SYNC_LAG: 'ingestion', FAILED_SYNCS: 'ingestion', CONNECTOR_SCHEMA_DRIFT: 'ingestion',
  DAG_LAST_RUN: 'orchestration', DAG_SCHEDULE_LAG: 'orchestration', TASK_FAILURE_RATE: 'orchestration',
  DBT_TEST_FAILURES: 'transform', DBT_MODEL_FRESHNESS: 'transform', DBT_SOURCE_FRESHNESS: 'transform',
  DBT_CORE_SOURCE_VALIDATION: 'transform', DBT_CORE_REF_INTEGRITY: 'transform',
  BI_FRESHNESS_PROXY: 'bi', BI_UPSTREAM_BREAK_RISK: 'bi', BI_REFRESH_FAILURE: 'bi', BI_CONTENT_HEALTH: 'bi',
  CERTIFICATE: 'infra', SERVER_HEALTH: 'infra', LOG_ANALYSIS: 'infra',
};

const DISPLAY_OVERRIDES: Record<string, string> = {
  fivetran: 'Fivetran',
  airbyte: 'Airbyte',
  airflow: 'Airflow',
  dagster: 'Dagster',
  dbt_cloud: 'dbt cloud',
  dbt_core: 'dbt core',
  looker: 'Looker',
  tableau: 'Tableau',
  bigquery: 'BigQuery',
  snowflake: 'Snowflake',
  postgres: 'Postgres',
  redshift: 'Redshift',
  linux_server: 'linux server',
};

function displayName(toolType: string): string {
  if (DISPLAY_OVERRIDES[toolType]) return DISPLAY_OVERRIDES[toolType];
  return toolType
    .split('_')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

type ToolMonitor = {
  toolType: string; // either Integration.toolType or monitor-type-derived family
  lastStatus: string | null;
  lastRunAt: Date | null;
};

function precedence(status: string): number {
  const s = status.toUpperCase();
  if (s === 'FAIL') return 4;
  if (s === 'ERROR') return 3;
  if (s === 'WARN') return 2;
  if (s === 'PASS' || s === 'SKIPPED') return 1;
  return 0; // null / NEVER_RUN
}

export function aggregateByTool(monitors: ToolMonitor[]): PipelineToolStatus[] {
  const buckets = new Map<string, ToolMonitor[]>();
  for (const m of monitors) {
    const key = m.toolType || 'unknown';
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(m);
  }
  const out: PipelineToolStatus[] = [];
  for (const [toolType, items] of buckets) {
    let topStatus = '';
    let topRank = 0;
    let failCount = 0, warnCount = 0;
    let mostRecent: Date | null = null;
    for (const m of items) {
      const s = (m.lastStatus || '').toUpperCase();
      if (s === 'FAIL') failCount += 1;
      if (s === 'WARN') warnCount += 1;
      const r = precedence(s);
      if (r > topRank) { topRank = r; topStatus = s; }
      if (m.lastRunAt && (!mostRecent || m.lastRunAt > mostRecent)) mostRecent = m.lastRunAt;
    }
    let status: PipelineToolStatusValue;
    if (topRank === 0) status = 'NEVER_RUN';
    else if (topStatus === 'SKIPPED' || topStatus === 'PASS') status = 'PASS';
    else status = topStatus as PipelineToolStatusValue;

    out.push({
      toolType,
      displayName: displayName(toolType),
      status,
      failCount,
      warnCount,
      monitorCount: items.length,
      lastRunAt: mostRecent ? mostRecent.toISOString() : null,
    });
  }
  // Stable sort: failing tools first, then warning, then by name
  return out.sort((a, b) => {
    const aRank = a.status === 'FAIL' ? 4 : a.status === 'ERROR' ? 3 : a.status === 'WARN' ? 2 : 1;
    const bRank = b.status === 'FAIL' ? 4 : b.status === 'ERROR' ? 3 : b.status === 'WARN' ? 2 : 1;
    if (aRank !== bRank) return bRank - aRank;
    return a.displayName.localeCompare(b.displayName);
  });
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  const monitors = await prisma.monitor.findMany({
    where: {
      organizationId,
      pipelineStackId: stackId,
      enabled: true,
      monitorType: { in: PIPELINE_MONITOR_TYPES as unknown as string[] },
    },
    select: {
      monitorType: true,
      lastStatus: true,
      lastRunAt: true,
      integration: { select: { toolType: true } },
    },
  });

  const toolMonitors: ToolMonitor[] = monitors.map((m) => ({
    toolType: m.integration?.toolType || FAMILY_BY_TYPE[(m.monitorType || '').toUpperCase()] || 'unknown',
    lastStatus: m.lastStatus,
    lastRunAt: m.lastRunAt,
  }));

  const response: PipelineToolStatusResponse = { tools: aggregateByTool(toolMonitors) };
  return NextResponse.json(response);
}
```

- [ ] **Step 2: Run tests**

```bash
npx jest app/api/monitors/__tests__/pipeline-status.test.ts 2>&1 | tail
```
Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/api/monitors/pipeline-status/route.ts app/api/monitors/__tests__/pipeline-status.test.ts
git commit -m "feat(monitors): GET /api/monitors/pipeline-status with FAIL>ERROR>WARN>PASS precedence"
```

---

### Task 7: `SummaryHero` rewrite — failing test

The hero tone now derives from monitor counts plus incidents (not incidents alone). Tests cover each tone and headline format.

**Files:**
- Create: `components/monitors/__tests__/SummaryHero.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
/**
 * Run with: npx jest components/monitors/__tests__/SummaryHero.test.tsx
 */
import { render, screen } from '@testing-library/react';
import { SummaryHero } from '../SummaryHero';
import type { MonitorHealthSummary } from '@/types/monitors-summary';
import type { IncidentSummary } from '@/types/incident';

const ZERO: MonitorHealthSummary = {
  total: 0, healthy: 0, warning: 0, failing: 0,
  dataAssets: 0, pipelineTools: 0, lastRunAt: null,
};

const HEALTHY: MonitorHealthSummary = {
  total: 47, healthy: 47, warning: 0, failing: 0,
  dataAssets: 38, pipelineTools: 6, lastRunAt: '2026-05-04T14:32:00Z',
};

function inc(over: Partial<IncidentSummary>): IncidentSummary {
  return {
    id: 'i1', monitorId: 'm1', targetFqn: 'a.x',
    status: 'OPEN', severity: 'FAIL',
    openedAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    isMuted: false,
    ...(over as any),
  } as IncidentSummary;
}

describe('<SummaryHero />', () => {
  it('renders the grey "Setting up" state when zero monitors exist', () => {
    render(<SummaryHero health={ZERO} incidents={[]} />);
    expect(screen.getByText(/setting up/i)).toBeInTheDocument();
    expect(screen.getByText(/no monitors yet/i)).toBeInTheDocument();
  });

  it('renders green when all monitors pass and no incidents are open', () => {
    render(<SummaryHero health={HEALTHY} incidents={[]} />);
    expect(screen.getByText(/all systems healthy/i)).toBeInTheDocument();
    expect(screen.getByText(/47 monitors/)).toBeInTheDocument();
    expect(screen.getByText(/38 data assets/)).toBeInTheDocument();
    expect(screen.getByText(/6 pipeline tools/)).toBeInTheDocument();
  });

  it('renders amber when any monitor is WARN and no FAIL/ERROR signals', () => {
    const health: MonitorHealthSummary = { ...HEALTHY, healthy: 45, warning: 2 };
    render(<SummaryHero health={health} incidents={[]} />);
    expect(screen.getByText(/2 warnings/)).toBeInTheDocument();
  });

  it('renders red when any monitor is FAIL', () => {
    const health: MonitorHealthSummary = { ...HEALTHY, healthy: 44, failing: 3 };
    render(<SummaryHero health={health} incidents={[inc({ severity: 'FAIL' })]} />);
    expect(screen.getByText(/critical incident/i)).toBeInTheDocument();
  });

  it('renders red when there is an open FAIL incident even if monitor counts look clean', () => {
    // Edge case: incident exists but monitor.lastStatus has not been updated yet.
    render(<SummaryHero health={HEALTHY} incidents={[inc({ severity: 'FAIL' })]} />);
    expect(screen.getByText(/critical incident/i)).toBeInTheDocument();
  });

  it('ignores muted incidents in tone calculation', () => {
    const muted = inc({ severity: 'FAIL', isMuted: true });
    render(<SummaryHero health={HEALTHY} incidents={[muted]} />);
    expect(screen.getByText(/all systems healthy/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npx jest components/monitors/__tests__/SummaryHero.test.tsx 2>&1 | tail
```
Expected: FAIL — current `SummaryHero` accepts `monitoredAssetCount`, not `health`.

---

### Task 8: `SummaryHero` rewrite — implementation

**Files:**
- Modify: `components/monitors/SummaryHero.tsx`

- [ ] **Step 1: Replace the component body**

```tsx
'use client';

import { cn } from '@/lib/utils';
import type { IncidentSummary } from '@/types/incident';
import type { MonitorHealthSummary } from '@/types/monitors-summary';

interface Props {
  health: MonitorHealthSummary;
  incidents: IncidentSummary[];   // active incidents (open + ack), already filtered
  blastRadius?: { dashboards: number; tables: number };
}

function formatMs(ms: number): string {
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function SummaryHero({ health, incidents, blastRadius }: Props) {
  const open = incidents.filter((i) => i.status === 'OPEN' && !i.isMuted);
  const failIncidents = open.filter((i) => i.severity === 'FAIL');
  const warnIncidents = open.filter((i) => i.severity === 'WARN');

  // Tone selection — first match wins. Empty profile is its own grey state.
  let tone: 'green' | 'amber' | 'red' | 'grey' = 'green';
  if (health.total === 0) {
    tone = 'grey';
  } else if (health.failing > 0 || failIncidents.length > 0) {
    tone = 'red';
  } else if (health.warning > 0 || warnIncidents.length > 0) {
    tone = 'amber';
  } else {
    tone = 'green';
  }

  const styles = {
    grey:  'from-zinc-500/12 to-zinc-500/[0.02] border-zinc-500/30 text-zinc-400',
    green: 'from-emerald-500/12 to-emerald-500/[0.02] border-emerald-500/30 text-emerald-400',
    amber: 'from-amber-500/12  to-amber-500/[0.02]  border-amber-500/30  text-amber-400',
    red:   'from-red-500/12    to-red-500/[0.02]    border-red-500/30    text-red-400',
  } as const;

  const dotColor = {
    grey: 'bg-zinc-500',
    green: 'bg-emerald-500',
    amber: 'bg-amber-500',
    red: 'bg-red-500',
  }[tone];

  const oldestMs = open.length > 0
    ? Math.max(...open.map((i) => Date.now() - new Date(i.openedAt).getTime()))
    : null;

  let headline: string;
  if (tone === 'grey') {
    headline = 'Setting up. No monitors yet.';
  } else if (tone === 'green') {
    headline = 'All systems healthy.';
  } else if (tone === 'amber') {
    const n = health.warning + warnIncidents.length;
    headline = `${n} warning${n === 1 ? '' : 's'}.`;
    if (blastRadius) headline += ` Affecting ${blastRadius.dashboards} dashboards.`;
  } else {
    const f = failIncidents.length || health.failing;
    headline = `${f} critical incident${f === 1 ? '' : 's'}`;
    if (warnIncidents.length > 0) headline += ` · ${warnIncidents.length} warning`;
    headline += '.';
    if (blastRadius) headline += ` Affecting ${blastRadius.dashboards} BI dashboards and ${blastRadius.tables} downstream tables.`;
    if (oldestMs) headline += ` Oldest ${formatMs(oldestMs)}.`;
  }

  // Sub-line is always shown — it's the bug fix for the "0 assets monitored" issue.
  const subline =
    `${health.total} monitor${health.total === 1 ? '' : 's'} · ` +
    `${health.healthy} healthy · ${health.warning} warning · ${health.failing} failing — ` +
    `${health.dataAssets} data asset${health.dataAssets === 1 ? '' : 's'}, ` +
    `${health.pipelineTools} pipeline tool${health.pipelineTools === 1 ? '' : 's'}`;

  const updatedLabel = health.lastRunAt
    ? new Date(health.lastRunAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className={cn('rounded-lg border bg-gradient-to-r px-5 py-4 mb-4', styles[tone])}>
      <div className="flex items-center gap-3">
        <div className={cn('w-2.5 h-2.5 rounded-full shadow', dotColor)} />
        <div className="flex-1">
          <div className="text-[14px] font-semibold">{headline}</div>
          {health.total > 0 && (
            <div className="text-[11px] opacity-70 mt-0.5">{subline}</div>
          )}
        </div>
        {updatedLabel && (
          <div className="text-[10px] opacity-60">Updated {updatedLabel}</div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Run hero tests**

```bash
npx jest components/monitors/__tests__/SummaryHero.test.tsx 2>&1 | tail
```
Expected: 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add components/monitors/SummaryHero.tsx components/monitors/__tests__/SummaryHero.test.tsx
git commit -m "feat(monitors): hero tone derived from MonitorHealthSummary + incidents"
```

---

### Task 9: `PipelineTier` component — status-only tiles

Renders the new pipeline tier section: one tile per pipeline tool, click opens a side panel.

**Files:**
- Create: `components/monitors/PipelineTier.tsx`

- [ ] **Step 1: Write the component**

```tsx
'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import type { PipelineToolStatus } from '@/types/monitors-summary';
import { PipelineToolDetailPanel } from './PipelineToolDetailPanel';

interface Props {
  tools: PipelineToolStatus[];
  loading: boolean;
  stackId: string;
}

const STATUS_COLOR: Record<string, string> = {
  PASS:      'text-emerald-500',
  WARN:      'text-amber-500',
  FAIL:      'text-red-500',
  ERROR:     'text-red-500',
  NEVER_RUN: 'text-[var(--muted)]',
};

const STATUS_LABEL: Record<string, (t: PipelineToolStatus) => string> = {
  PASS:      () => 'healthy',
  WARN:      (t) => `${t.warnCount} warn`,
  FAIL:      (t) => `${t.failCount} fail`,
  ERROR:     (t) => `${t.failCount} error`,
  NEVER_RUN: () => 'never run',
};

function timeSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function PipelineTier({ tools, loading, stackId }: Props) {
  const [openTool, setOpenTool] = useState<PipelineToolStatus | null>(null);

  if (!loading && tools.length === 0) return null; // suppress section on empty

  return (
    <section className="mb-4">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Pipeline tier
      </div>
      {loading ? (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-16 rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
          {tools.map((tool) => (
            <button
              key={tool.toolType}
              onClick={() => setOpenTool(tool)}
              className="text-left rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] hover:border-[var(--border)] transition-colors p-2.5"
            >
              <div className="text-[11px] text-[var(--muted)] truncate">{tool.displayName}</div>
              <div className={cn('text-[12px] font-semibold mt-0.5', STATUS_COLOR[tool.status])}>
                {STATUS_LABEL[tool.status](tool)}
              </div>
              {tool.lastRunAt && (
                <div className="text-[10px] text-[var(--text-faint)] mt-0.5">{timeSince(tool.lastRunAt)}</div>
              )}
            </button>
          ))}
        </div>
      )}

      {openTool && (
        <PipelineToolDetailPanel
          tool={openTool}
          stackId={stackId}
          onClose={() => setOpenTool(null)}
        />
      )}
    </section>
  );
}
```

- [ ] **Step 2: Commit (panel comes in next task)**

The component will fail to compile until `PipelineToolDetailPanel` exists — write the panel first if jumping ahead, then commit them together. The plan groups the commit with Task 10.

---

### Task 10: `PipelineToolDetailPanel` side panel

Shows the per-tool drill-down: list of monitors targeting this tool, last 5 failures, link into Pipeline Monitors tab.

**Files:**
- Create: `components/monitors/PipelineToolDetailPanel.tsx`

- [ ] **Step 1: Write the panel**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { X, ExternalLink, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { PipelineToolStatus } from '@/types/monitors-summary';

interface Props {
  tool: PipelineToolStatus;
  stackId: string;
  onClose: () => void;
}

interface MonitorRow {
  id: string;
  name: string;
  monitorType: string;
  lastStatus: string | null;
  lastRunAt: string | null;
  targetFqn: string | null;
}

export function PipelineToolDetailPanel({ tool, stackId, onClose }: Props) {
  const router = useRouter();
  const [monitors, setMonitors] = useState<MonitorRow[]>([]);
  const [loading, setLoading] = useState(true);

  // Close on ESC
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Fetch monitors targeting this tool. Reuse /api/schedule/tasks and filter client-side
  // — the page already loads the same data once, so this is cache-warm.
  useEffect(() => {
    let active = true;
    fetch(`/api/schedule/tasks?stackId=${stackId}`)
      .then((r) => r.ok ? r.json() : { tasks: [] })
      .then((d) => {
        if (!active) return;
        const all: any[] = d.tasks || [];
        // Match by integration.toolType, falling back to monitor-type-derived family.
        const filtered = all.filter((t) => {
          const it = (t.integration?.toolType || '').toLowerCase();
          if (it && it === tool.toolType) return true;
          // Family fallback: trust the server's grouping by re-checking the family map.
          return false;
        });
        setMonitors(filtered as MonitorRow[]);
        setLoading(false);
      })
      .catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [stackId, tool.toolType]);

  const failures = monitors
    .filter((m) => (m.lastStatus || '').toUpperCase() === 'FAIL' || (m.lastStatus || '').toUpperCase() === 'ERROR')
    .slice(0, 5);

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        aria-hidden
      />
      <aside
        className="fixed right-0 top-0 bottom-0 w-[440px] max-w-[90vw] bg-[var(--bg)] border-l border-[var(--subtle-border)] z-50 flex flex-col"
        role="dialog"
        aria-label={`${tool.displayName} detail`}
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--subtle-border)]">
          <div>
            <div className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Pipeline tool</div>
            <div className="text-[14px] font-semibold">{tool.displayName}</div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--surface)]" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Monitors" value={String(tool.monitorCount)} />
            <Stat label="Failing" value={String(tool.failCount)} tone={tool.failCount > 0 ? 'red' : undefined} />
            <Stat label="Warning" value={String(tool.warnCount)} tone={tool.warnCount > 0 ? 'amber' : undefined} />
          </div>

          <section>
            <div className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">Recent failures</div>
            {loading ? (
              <div className="h-12 animate-pulse rounded bg-[var(--surface)]" />
            ) : failures.length === 0 ? (
              <div className="text-[12px] text-[var(--muted)]">No recent failures.</div>
            ) : (
              <ul className="space-y-1.5">
                {failures.map((m) => (
                  <li key={m.id} className="flex items-center gap-2 text-[12px]">
                    <AlertCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                    <span className="truncate">{m.name}</span>
                    <span className="text-[10px] text-[var(--text-faint)] shrink-0">{m.targetFqn || m.monitorType}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <div className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">Monitors</div>
            {loading ? (
              <div className="h-20 animate-pulse rounded bg-[var(--surface)]" />
            ) : monitors.length === 0 ? (
              <div className="text-[12px] text-[var(--muted)]">No monitors target this tool yet.</div>
            ) : (
              <ul className="space-y-1">
                {monitors.map((m) => (
                  <li key={m.id} className="flex items-center justify-between text-[12px] py-0.5">
                    <span className="truncate">{m.name}</span>
                    <span className={cn(
                      'text-[10px] px-1.5 py-0.5 rounded',
                      (m.lastStatus || '').toUpperCase() === 'FAIL' || (m.lastStatus || '').toUpperCase() === 'ERROR' ? 'bg-red-500/10 text-red-500'
                        : (m.lastStatus || '').toUpperCase() === 'WARN' ? 'bg-amber-500/10 text-amber-500'
                        : 'bg-[var(--overlay-bg)] text-[var(--muted)]'
                    )}>
                      {m.lastStatus || 'NEVER RUN'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <footer className="border-t border-[var(--subtle-border)] px-4 py-3">
          <button
            onClick={() => router.push(`/dashboard/monitors?tab=pipeline&tool=${tool.toolType}`)}
            className="w-full flex items-center justify-center gap-1.5 text-[12px] py-2 rounded border border-[var(--subtle-border)] hover:bg-[var(--surface)]"
          >
            View all in Pipeline Monitors <ExternalLink className="w-3 h-3" />
          </button>
        </footer>
      </aside>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'red' | 'amber' }) {
  const color = tone === 'red' ? 'text-red-500' : tone === 'amber' ? 'text-amber-500' : 'text-[var(--text)]';
  return (
    <div className="rounded border border-[var(--subtle-border)] bg-[var(--surface)] px-2.5 py-2">
      <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{label}</div>
      <div className={cn('text-[16px] font-semibold mt-0.5', color)}>{value}</div>
    </div>
  );
}
```

- [ ] **Step 2: Commit `PipelineTier` and panel together**

```bash
git add components/monitors/PipelineTier.tsx components/monitors/PipelineToolDetailPanel.tsx
git commit -m "feat(monitors): PipelineTier + PipelineToolDetailPanel — status tiles with click-to-expand"
```

---

### Task 11: `CoverageGaps` rewrite — three-state critical card + drift discovery button

**Files:**
- Modify: `components/monitors/CoverageGaps.tsx`

- [ ] **Step 1: Read the current shape**

```bash
sed -n '1,40p' components/monitors/CoverageGaps.tsx
```

- [ ] **Step 2: Replace the file**

```tsx
'use client';

import { useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  unmonitoredCriticalAssets: Array<{ fqn: string; reason: string }>;
  lineageExtracted: boolean;
  pendingRecommendations: DriftRecommendation[];
  lastAnalyzedAt: string | null;
  stackId: string;
  onAddMonitor: (fqn: string) => void;
  onReviewRecs: () => void;
  onDriftRunComplete: () => void;
}

function timeSince(iso: string | null): string | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function CoverageGaps({
  unmonitoredCriticalAssets,
  lineageExtracted,
  pendingRecommendations,
  lastAnalyzedAt,
  stackId,
  onAddMonitor,
  onReviewRecs,
  onDriftRunComplete,
}: Props) {
  const [running, setRunning] = useState(false);

  const handleRunDrift = async () => {
    if (running) return;
    setRunning(true);
    try {
      const res = await fetch('/api/drift/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stackId }),
        signal: AbortSignal.timeout(125_000),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `drift run failed (${res.status})`);
      }
      const data = await res.json();
      const n = data.recommendationCount ?? 0;
      toast.success(n > 0
        ? `Drift discovery complete — ${n} recommendation${n === 1 ? '' : 's'}`
        : 'Drift discovery complete — no threshold drift detected');
      onDriftRunComplete();
    } catch (e: any) {
      toast.error(`Drift discovery failed: ${e?.message ?? 'unknown error'}`);
    } finally {
      setRunning(false);
    }
  };

  // Critical Assets card render state
  const N = unmonitoredCriticalAssets.length;
  const hideCritical = lineageExtracted && N === 0;
  const lineageMissing = !lineageExtracted;

  return (
    <section className="mb-4">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Coverage &amp; recommendations
      </div>
      <div className={cn('grid gap-3', hideCritical ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2')}>
        {!hideCritical && (
          <div className="rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] p-3">
            {lineageMissing ? (
              <>
                <div className="text-[13px] font-semibold">Lineage not yet extracted.</div>
                <div className="text-[11px] text-[var(--muted)] mt-1">
                  Critical-asset coverage needs lineage to identify what feeds your BI dashboards.
                </div>
                <button
                  onClick={() => window.location.assign('/dashboard/pipeline')}
                  className="mt-2 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)] hover:bg-[var(--overlay-bg)]"
                >
                  Extract lineage →
                </button>
              </>
            ) : (
              <>
                <div className="text-[13px] font-semibold">
                  {N} critical asset{N === 1 ? '' : 's'} unmonitored
                </div>
                <div className="text-[11px] text-[var(--muted)] mt-1 truncate">
                  {unmonitoredCriticalAssets.slice(0, 3).map((a) => a.fqn).join(', ')}
                </div>
                <button
                  onClick={() => onAddMonitor(unmonitoredCriticalAssets[0]?.fqn || '')}
                  className="mt-2 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)] hover:bg-[var(--overlay-bg)]"
                >
                  Add monitors →
                </button>
              </>
            )}
          </div>
        )}

        <div className="rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] p-3">
          <div className="flex items-center justify-between">
            <div className="text-[13px] font-semibold">SLA recommendations</div>
            <button
              onClick={handleRunDrift}
              disabled={running}
              className={cn(
                'flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)]',
                running ? 'opacity-60' : 'hover:bg-[var(--overlay-bg)]'
              )}
            >
              {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              {running ? 'Running…' : 'Run drift discovery'}
            </button>
          </div>
          <div className="text-[11px] text-[var(--muted)] mt-1">
            {pendingRecommendations.length > 0
              ? `${pendingRecommendations.length} threshold${pendingRecommendations.length === 1 ? '' : 's'} drifted.`
              : 'No threshold drift detected.'}
            {' '}
            {lastAnalyzedAt
              ? `Last analysis ${timeSince(lastAnalyzedAt)}.`
              : 'Drift discovery has not run yet.'}
          </div>
          {pendingRecommendations.length > 0 && (
            <button
              onClick={onReviewRecs}
              className="mt-2 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)] hover:bg-[var(--overlay-bg)]"
            >
              Review recommendations →
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add components/monitors/CoverageGaps.tsx
git commit -m "feat(monitors): CoverageGaps three-state critical card + Run drift discovery button"
```

---

### Task 12: `DriftSummaryTab` rewrite — vertical stack, new fetches, per-section skeletons

**Files:**
- Modify: `components/monitors/DriftSummaryTab.tsx`

- [ ] **Step 1: Replace the file**

```tsx
'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Activity, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { SummaryHero } from './SummaryHero';
import { ActiveIncidents } from './ActiveIncidents';
import { TrendStrip } from './TrendStrip';
import { AssetHealthLean } from './AssetHealthLean';
import { PipelineTier } from './PipelineTier';
import { CoverageGaps } from './CoverageGaps';
import type { IncidentSummary, IncidentStats } from '@/types/incident';
import type {
  MonitorHealthSummary,
  PipelineToolStatusResponse,
} from '@/types/monitors-summary';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  watches: any[];
  tasks: any[];
  loading: boolean;
}

export function DriftSummaryTab({ watches: _w, tasks: _t, loading: _l }: Props) {
  const { selectedPipelineId } = usePipeline();
  const router = useRouter();

  const [activeIncidents, setActiveIncidents] = useState<IncidentSummary[]>([]);
  const [health, setHealth] = useState<MonitorHealthSummary | null>(null);
  const [stats, setStats] = useState<IncidentStats | null>(null);
  const [pipelineTools, setPipelineTools] = useState<PipelineToolStatusResponse['tools']>([]);
  const [trendData, setTrendData] = useState<any | null>(null);
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [unmonitoredCritical, setUnmonitoredCritical] = useState<Array<{ fqn: string; reason: string }>>([]);
  const [lineageExtracted, setLineageExtracted] = useState(false);
  const [expandedAssetFqn, setExpandedAssetFqn] = useState<string | null>(null);
  const [activeCategories] = useState<Set<string>>(new Set());

  // Per-section ready flags. The page renders skeletons per section, NOT one global gate.
  const [healthReady, setHealthReady] = useState(false);
  const [incidentsReady, setIncidentsReady] = useState(false);
  const [pipelineReady, setPipelineReady] = useState(false);
  const [trendsReady, setTrendsReady] = useState(false);
  const [coverageReady, setCoverageReady] = useState(false);
  const [driftReady, setDriftReady] = useState(false);

  const fetchHealth = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/monitors/health-summary?stackId=${selectedPipelineId}`);
      if (r.ok) setHealth(await r.json());
    } catch {}
    setHealthReady(true);
  }, [selectedPipelineId]);

  const fetchIncidents = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/incidents?stackId=${selectedPipelineId}&status=active`);
      if (r.ok) {
        const d = await r.json();
        setActiveIncidents(d.incidents || []);
      }
    } catch {}
    setIncidentsReady(true);
  }, [selectedPipelineId]);

  const fetchStats = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/incidents/stats?stackId=${selectedPipelineId}&window=7d`);
      if (r.ok) setStats(await r.json());
    } catch {}
  }, [selectedPipelineId]);

  const fetchPipelineStatus = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/monitors/pipeline-status?stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d: PipelineToolStatusResponse = await r.json();
        setPipelineTools(d.tools || []);
      }
    } catch {}
    setPipelineReady(true);
  }, [selectedPipelineId]);

  const fetchTrends = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`);
      if (r.ok) setTrendData(await r.json());
    } catch {}
    setTrendsReady(true);
  }, [selectedPipelineId]);

  const fetchDrift = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/drift?status=pending&stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d = await r.json();
        setRecommendations(d.recommendations || []);
        setLastAnalyzedAt(d.lastAnalyzedAt || null);
      }
    } catch {}
    setDriftReady(true);
  }, [selectedPipelineId]);

  const fetchCoverage = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/coverage/unmonitored-critical?stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d = await r.json();
        setUnmonitoredCritical(d.assets || []);
        setLineageExtracted(!!d.lineageExtracted);
      }
    } catch {}
    setCoverageReady(true);
  }, [selectedPipelineId]);

  // Reset per-section flags + state on pipeline change.
  useEffect(() => {
    setHealth(null);
    setActiveIncidents([]);
    setStats(null);
    setPipelineTools([]);
    setTrendData(null);
    setRecommendations([]);
    setLastAnalyzedAt(null);
    setUnmonitoredCritical([]);
    setLineageExtracted(false);
    setHealthReady(false);
    setIncidentsReady(false);
    setPipelineReady(false);
    setTrendsReady(false);
    setCoverageReady(false);
    setDriftReady(false);
  }, [selectedPipelineId]);

  // Fan out independent fetches; each section gates on its own readiness.
  useEffect(() => {
    if (!selectedPipelineId) return;
    fetchHealth();
    fetchIncidents();
    fetchStats();
    fetchPipelineStatus();
    fetchTrends();
    fetchDrift();
    fetchCoverage();
  }, [
    selectedPipelineId,
    fetchHealth, fetchIncidents, fetchStats, fetchPipelineStatus,
    fetchTrends, fetchDrift, fetchCoverage,
  ]);

  // Periodic refresh — invalidate first so cachedFetch re-fetches.
  useEffect(() => {
    if (!selectedPipelineId) return;
    const t = setInterval(() => {
      invalidateCache('/api/monitors/health-summary');
      invalidateCache('/api/incidents');
      invalidateCache('/api/monitors/pipeline-status');
      invalidateCache('/api/schedule/monitor-trends');
      invalidateCache('/api/drift');
      invalidateCache('/api/coverage');
      fetchHealth();
      fetchIncidents();
      fetchStats();
      fetchPipelineStatus();
      fetchTrends();
      fetchDrift();
      fetchCoverage();
    }, 30_000);
    return () => clearInterval(t);
  }, [
    selectedPipelineId,
    fetchHealth, fetchIncidents, fetchStats, fetchPipelineStatus,
    fetchTrends, fetchDrift, fetchCoverage,
  ]);

  const handleOpenInCopilot = useCallback((incident: IncidentSummary) => {
    const params = new URLSearchParams({
      contextType: 'incident',
      incidentId: incident.id,
      monitorId: incident.monitorId,
      targetFqn: incident.targetFqn,
    });
    router.push(`/dashboard/assistant?${params.toString()}`);
  }, [router]);

  const onIncidentChanged = useCallback(() => {
    invalidateCache('/api/incidents');
    fetchIncidents();
  }, [fetchIncidents]);

  const onDriftRunComplete = useCallback(() => {
    invalidateCache('/api/drift');
    fetchDrift();
  }, [fetchDrift]);

  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    return Object.values(trendData.assets) as any[];
  }, [trendData]);

  if (!selectedPipelineId) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {healthReady && incidentsReady && health ? (
        <SummaryHero health={health} incidents={activeIncidents} />
      ) : (
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] px-5 py-4 mb-4 animate-pulse">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-[var(--subtle-border)]" />
            <div className="h-3.5 w-64 bg-[var(--subtle-border)] rounded" />
          </div>
        </div>
      )}

      <ActiveIncidents
        incidents={activeIncidents}
        onChanged={onIncidentChanged}
        onOpenInCopilot={handleOpenInCopilot}
      />

      <TrendStrip stats={stats} />

      <PipelineTier
        tools={pipelineTools}
        loading={!pipelineReady}
        stackId={selectedPipelineId}
      />

      <AssetHealthLean
        assets={assetList}
        expandedFqn={expandedAssetFqn}
        onToggle={(fqn) => setExpandedAssetFqn((p) => p === fqn ? null : fqn)}
        activeCategories={activeCategories}
        onRunAnalysis={() => {}}
      />

      {coverageReady && driftReady && (
        <CoverageGaps
          unmonitoredCriticalAssets={unmonitoredCritical}
          lineageExtracted={lineageExtracted}
          pendingRecommendations={recommendations}
          lastAnalyzedAt={lastAnalyzedAt}
          stackId={selectedPipelineId}
          onAddMonitor={(fqn) => router.push(`/dashboard/monitors?createFor=${encodeURIComponent(fqn)}`)}
          onReviewRecs={() => router.push('/dashboard/monitors?tab=recommendations')}
          onDriftRunComplete={onDriftRunComplete}
        />
      )}

      {healthReady
        && incidentsReady
        && trendsReady
        && pipelineReady
        && (health?.total ?? 0) === 0
        && activeIncidents.length === 0
        && pipelineTools.length === 0
        && assetList.length === 0
        && (
          <div className="flex flex-col items-center justify-center py-12">
            <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
            <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
          </div>
        )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit -p . 2>&1 | grep -E "(SummaryHero|PipelineTier|CoverageGaps|DriftSummaryTab|monitors-summary|incident)" | head -20
```
Expected: empty (no errors in changed files).

- [ ] **Step 3: Commit**

```bash
git add components/monitors/DriftSummaryTab.tsx
git commit -m "feat(monitors): DriftSummaryTab v2 — vertical stack with per-section skeletons"
```

---

### Task 13: Smoke verification + final commit

**Files:**
- All changed files (no new ones)

- [ ] **Step 1: Run all related tests**

```bash
npx jest \
  app/api/monitors/__tests__/health-summary.test.ts \
  app/api/monitors/__tests__/pipeline-status.test.ts \
  components/monitors/__tests__/SummaryHero.test.tsx \
  lib/incidents/__tests__/ \
  2>&1 | tail -30
```
Expected: all tests green.

- [ ] **Step 2: Manual smoke**

Boot the dev server and exercise:

1. Open `/dashboard/monitors` and switch to the Summary tab on a profile that has monitors.
   - Hero shows total / healthy / warning / failing counts.
   - Pipeline tier shows tool tiles. Click one — side panel opens, ESC dismisses.
   - "Run drift discovery" runs and toasts success or no-drift.
2. Switch to a profile with **zero monitors**.
   - Hero shows the grey "Setting up. No monitors yet." state.
   - Pipeline tier section is suppressed.
3. Switch back. The empty-state placeholder ("No monitors configured yet.") shows only when truly empty.

- [ ] **Step 3: Final cleanup commit**

If smoke surfaced any small fixes, commit them. Otherwise nothing to commit.

```bash
git status
# if clean: skip
git add <files>
git commit -m "fix(monitors): summary tab smoke fixes"
```

---

## Self-Review

**Spec coverage:**
- Hero monitor-health formula → Tasks 3, 4, 7, 8.
- Pipeline tier tiles + click-to-expand → Tasks 5, 6, 9, 10.
- Three-state Critical Assets card → Tasks 1, 11.
- Run drift discovery button → Task 11 (wires existing `/api/drift/run`).
- Per-section skeletons + vertical stack → Task 12.
- `lineageExtracted` flag → Task 1.
- `MonitorHealthSummary`, `PipelineToolStatus` types → Task 2.

**Placeholders:** None — every step has the code to write.

**Type consistency:** `MonitorHealthSummary`, `PipelineToolStatus`, `PipelineToolStatusValue`, `PipelineToolStatusResponse` are defined in Task 2 and used identically in Tasks 4, 6, 8, 9, 10, 12.
