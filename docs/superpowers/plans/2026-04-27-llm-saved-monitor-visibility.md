# LLM Saved-Monitor Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the LLM-backed copilot two new tools (`list_configured_monitors`, `get_monitor_run_history`) so it can answer questions about *the user's saved monitors* (e.g. "why are my dbt core monitors failing?") by reading from the `Monitor` / `MonitorRun` Prisma tables instead of guessing or wandering off into ad-hoc `run_coverage_monitor` calls.

**Architecture:** Two POST endpoints on the Next.js side that query Prisma (`Monitor`, `MonitorRun`) with internal-secret + org-id auth — same pattern already used by `app/api/schedule/plans/route.ts` for copilot callbacks. Two new tool definitions registered in the FastAPI scanner (`scanner/copilot/tools/observability.py`). Two new `_execute_*` methods on `ToolExecutor` that POST to the Next.js endpoints via the existing `_call_nextjs(path, body)` helper. System-prompt addition that forces the LLM to call `list_configured_monitors` *before* any ad-hoc `run_coverage_monitor` call when the user is asking about their monitors.

**Tech Stack:** Next.js (Prisma), FastAPI (Python), pytest, jest.

---

## Background — read this before starting

This plan exists because the copilot was hallucinating "monitor failures" that didn't correspond to anything saved in the user's account. Verified root cause:

- The user's saved monitors live in Postgres via Prisma (`Monitor`, `MonitorRun`). See `prisma/schema.prisma` — search for `^model Monitor`, `^model MonitorRun`, `^enum MonitorKind`, `^enum MonitorRunStatus`.
- The FastAPI scanner has **no tool** that returns saved-monitor state. It has `get_coverage_report`, `get_coverage_gaps`, `get_node_coverage`, `get_monitor_recommendations` (all derived from the lineage graph — synthetic, not saved state) and `run_coverage_monitor` (an *ad-hoc* one-off check, not a saved-monitor query).
- When asked "why are my dbt core monitors failing?" the LLM grabbed `run_coverage_monitor` (closest tool name to "monitor"), ran an unrelated freshness check, and reported the failure of its own ad-hoc call as if it were a configured monitor.

The earlier session added two preventative fixes that are already merged on this branch — DO NOT redo:

1. `scanner/monitors/freshness.py` — `FreshnessMonitor.build_query` now raises `ValueError` with a clear message when `timestamp_column` is unconfigured (instead of silently using `"updated_at"`).
2. `scanner/copilot/llm.py` — the system prompt explicitly tells the LLM that `_fivetran_synced` is per-row (not per-run), and that `run_coverage_monitor` errors are about its tool call, not about saved monitors.

These help, but the LLM still can't see *what monitors actually exist*. This plan closes that gap.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/api/copilot/internal/list-configured-monitors/route.ts` | Create | Internal-secret-auth POST: query `Monitor` (with `lastStatus`) by org/filters; return list. |
| `app/api/copilot/internal/get-monitor-run-history/route.ts` | Create | Internal-secret-auth POST: query `MonitorRun` for a given monitor id (org-scoped); return last N runs. |
| `lib/__tests__/copilot-internal-monitors.test.ts` | Create | Jest tests for the two endpoints — auth, scoping, filters, ordering. |
| `scanner/copilot/tools/observability.py` | Modify | Add two `register_tool(...)` declarations. |
| `scanner/copilot/tool_executor.py` | Modify | Add `_execute_list_configured_monitors` and `_execute_get_monitor_run_history` (call Next.js via existing `_call_nextjs`). |
| `scanner/copilot/context_builder.py` | Modify | Whitelist the two new tool names in `_get_available_tools` so the LLM is offered them. |
| `scanner/copilot/llm.py` | Modify | Add a "Investigating Saved Monitors" block to the system prompt forbidding ad-hoc `run_coverage_monitor` use before `list_configured_monitors`. |
| `scanner/copilot/tests/test_saved_monitor_tools.py` | Create | Pytest tests for both `_execute_*` methods using a mocked `_call_nextjs`. |
| `scanner/copilot/tests/test_llm_prompt_saved_monitors.py` | Create | Pytest test that the new system-prompt block is present. |

---

## Reference: existing patterns to mirror

Before writing any code, open these files and read them — they show the exact patterns this plan reuses:

- **Internal-secret auth on Next.js routes**: `app/api/schedule/plans/route.ts` lines 145-175 — accepts `X-Internal-Secret` (matching `process.env.INTERNAL_API_SECRET || 'pallisade-internal'`) plus `X-Organization-Id`, falls back to session auth. Copy this block.
- **FastAPI → Next.js call**: `scanner/copilot/tool_executor.py` lines 862-877 — `_call_nextjs(path, body)`. Already uses the right headers; just call it.
- **Tool registration**: `scanner/copilot/tools/coverage.py` lines 7-28 — `@register_tool(name=..., description=..., category=ToolCategory.COVERAGE, parameters=[ToolParameter(...)])` followed by a `def _meta_<name>():` stub.
- **Tool dispatch**: `scanner/copilot/tool_executor.py` line 1033 — `getattr(self, f"_execute_{tool.name}", None)`. The tool name maps directly to the method name; no separate dispatch table.
- **Tool availability gating**: `scanner/copilot/context_builder.py` lines 1265-1383 (`_get_available_tools`). Coverage tools are in the always-available block at lines 1356-1363; the new tools belong there too.

---

## Conventions

- All commits in this plan should be small (one task = one commit). Use Conventional Commit prefixes: `feat:`, `test:`, `fix:`, `chore:`.
- After each task: run that task's tests AND a fast smoke run of the broader suite (`pytest scanner/copilot/tests/test_saved_monitor_tools.py` for Python, `npx jest lib/__tests__/copilot-internal-monitors.test.ts` for TS).
- Pre-existing test failures on this branch (do not try to fix them in this plan): `scanner/tests/copilot/test_golden_conversations.py::TestDebugConversation::test_tool_policy`, `scanner/copilot/tests/test_write_tools.py::test_execute_create_watch*`, `scanner/tests/copilot/maas/test_fallback.py::TestMAASConfig::test_from_env_defaults`, and `scanner/tests/lineage/test_airflow_adapter.py::TestDiscoverAssets::test_empty_dag_files_returns_empty`. Confirm these still fail in the same way after your changes — don't touch them.

---

### Task 1: Next.js endpoint — `list-configured-monitors`

**Files:**
- Create: `app/api/copilot/internal/list-configured-monitors/route.ts`

- [ ] **Step 1: Write the failing test**

Create `lib/__tests__/copilot-internal-monitors.test.ts` (this same file is reused in Task 3 for the second endpoint — leave it for now, just add the suites you need now):

```typescript
import { POST } from '@/app/api/copilot/internal/list-configured-monitors/route';
import { NextRequest } from 'next/server';

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    monitor: { findMany: jest.fn() },
  },
}));

import prisma from '@/lib/db';
const mockedPrisma = prisma as unknown as { monitor: { findMany: jest.Mock } };

const SECRET = 'pallisade-internal';

function makeRequest(body: any, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest('http://localhost/api/copilot/internal/list-configured-monitors', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Secret': headers['X-Internal-Secret'] ?? SECRET,
      'X-Organization-Id': headers['X-Organization-Id'] ?? 'org_1',
    },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  process.env.INTERNAL_API_SECRET = SECRET;
  mockedPrisma.monitor.findMany.mockReset();
});

describe('list-configured-monitors POST', () => {
  test('rejects missing internal secret', async () => {
    const req = makeRequest({}, { 'X-Internal-Secret': '' });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  test('rejects mismatched internal secret', async () => {
    const req = makeRequest({}, { 'X-Internal-Secret': 'wrong' });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  test('rejects missing X-Organization-Id', async () => {
    const req = makeRequest({}, { 'X-Organization-Id': '' });
    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  test('returns monitors scoped to org with default filters', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([
      {
        id: 'mon_1',
        name: 'orders source validation',
        monitorType: 'DBT_CORE_SOURCE_VALIDATION',
        targetFqn: 'analytics.orders',
        enabled: true,
        schedule: '0 6 * * *',
        lastRunAt: new Date('2026-04-27T06:00:00Z'),
        lastStatus: 'FAIL',
      },
    ]);

    const req = makeRequest({});
    const res = await POST(req);
    const data = await res.json();

    expect(res.status).toBe(200);
    expect(mockedPrisma.monitor.findMany).toHaveBeenCalledWith(
      expect.objectContaining({
        where: expect.objectContaining({ organizationId: 'org_1' }),
      }),
    );
    expect(data.monitors).toHaveLength(1);
    expect(data.monitors[0]).toMatchObject({
      id: 'mon_1',
      name: 'orders source validation',
      monitorType: 'DBT_CORE_SOURCE_VALIDATION',
      targetFqn: 'analytics.orders',
      lastStatus: 'FAIL',
    });
  });

  test('applies monitor_type filter (case-insensitive, accepts list)', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({
      monitor_type: ['dbt_core_source_validation', 'DBT_CORE_REF_INTEGRITY'],
    });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.monitorType).toEqual({
      in: ['DBT_CORE_SOURCE_VALIDATION', 'DBT_CORE_REF_INTEGRITY'],
    });
  });

  test('applies status filter and target_fqn filter', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);
    const req = makeRequest({
      status: ['FAIL', 'ERROR'],
      target_fqn: 'analytics.orders',
    });
    await POST(req);

    const where = (mockedPrisma.monitor.findMany.mock.calls[0][0] as any).where;
    expect(where.lastStatus).toEqual({ in: ['FAIL', 'ERROR'] });
    expect(where.targetFqn).toBe('analytics.orders');
  });

  test('respects limit parameter (default 50, max 200)', async () => {
    mockedPrisma.monitor.findMany.mockResolvedValue([]);

    await POST(makeRequest({}));
    expect((mockedPrisma.monitor.findMany.mock.calls[0][0] as any).take).toBe(50);

    await POST(makeRequest({ limit: 10 }));
    expect((mockedPrisma.monitor.findMany.mock.calls[1][0] as any).take).toBe(10);

    await POST(makeRequest({ limit: 999 }));
    expect((mockedPrisma.monitor.findMany.mock.calls[2][0] as any).take).toBe(200);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx jest lib/__tests__/copilot-internal-monitors.test.ts
```

Expected: FAIL with `Cannot find module '@/app/api/copilot/internal/list-configured-monitors/route'`.

- [ ] **Step 3: Create the endpoint**

Create `app/api/copilot/internal/list-configured-monitors/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

const VALID_STATUSES = new Set(['PASS', 'WARN', 'FAIL', 'ERROR', 'SKIPPED', 'RUNNING']);

function authorize(request: NextRequest): { ok: true; orgId: string } | { ok: false; status: number; error: string } {
  const secret = request.headers.get('X-Internal-Secret');
  const expected = process.env.INTERNAL_API_SECRET || 'pallisade-internal';
  if (!secret || secret !== expected) {
    return { ok: false, status: 401, error: 'invalid internal secret' };
  }
  const orgId = request.headers.get('X-Organization-Id');
  if (!orgId) {
    return { ok: false, status: 400, error: 'missing X-Organization-Id' };
  }
  return { ok: true, orgId };
}

function normalizeList(value: unknown): string[] | undefined {
  if (value == null) return undefined;
  const arr = Array.isArray(value) ? value : [value];
  return arr.filter((v): v is string => typeof v === 'string' && v.length > 0)
            .map((v) => v.toUpperCase());
}

export async function POST(request: NextRequest) {
  const auth = authorize(request);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    /* empty body is fine */
  }

  const monitorTypes = normalizeList(body?.monitor_type);
  const statuses = normalizeList(body?.status)?.filter((s) => VALID_STATUSES.has(s));
  const targetFqn: string | undefined = typeof body?.target_fqn === 'string' ? body.target_fqn : undefined;
  const enabled: boolean | undefined = typeof body?.enabled === 'boolean' ? body.enabled : undefined;

  const limitRaw = Number.isFinite(body?.limit) ? Number(body.limit) : 50;
  const limit = Math.max(1, Math.min(200, Math.trunc(limitRaw)));

  const where: Record<string, any> = { organizationId: auth.orgId };
  if (monitorTypes && monitorTypes.length > 0) where.monitorType = { in: monitorTypes };
  if (statuses && statuses.length > 0) where.lastStatus = { in: statuses };
  if (targetFqn) where.targetFqn = targetFqn;
  if (typeof enabled === 'boolean') where.enabled = enabled;

  const monitors = await prisma.monitor.findMany({
    where,
    select: {
      id: true,
      name: true,
      monitorType: true,
      targetFqn: true,
      targetDatabase: true,
      targetSchema: true,
      targetTable: true,
      enabled: true,
      schedule: true,
      lastRunAt: true,
      lastStatus: true,
      nextRunAt: true,
      description: true,
    },
    orderBy: [
      // Failures first (FAIL/ERROR) so the LLM sees actionable items at the top.
      { lastStatus: 'desc' },
      { lastRunAt: 'desc' },
    ],
    take: limit,
  });

  return NextResponse.json({
    monitors: monitors.map((m) => ({
      ...m,
      lastRunAt: m.lastRunAt ? m.lastRunAt.toISOString() : null,
      nextRunAt: m.nextRunAt ? m.nextRunAt.toISOString() : null,
    })),
    total: monitors.length,
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx jest lib/__tests__/copilot-internal-monitors.test.ts -t 'list-configured-monitors'
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/copilot/internal/list-configured-monitors/route.ts lib/__tests__/copilot-internal-monitors.test.ts
git commit -m "feat(copilot): add internal endpoint to list configured monitors"
```

---

### Task 2: Next.js endpoint — `get-monitor-run-history`

**Files:**
- Create: `app/api/copilot/internal/get-monitor-run-history/route.ts`
- Modify: `lib/__tests__/copilot-internal-monitors.test.ts` (add second describe block)

- [ ] **Step 1: Write the failing test**

Append to `lib/__tests__/copilot-internal-monitors.test.ts`:

```typescript
import { POST as runHistoryPOST } from '@/app/api/copilot/internal/get-monitor-run-history/route';

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    monitor: { findMany: jest.fn(), findFirst: jest.fn() },
    monitorRun: { findMany: jest.fn() },
  },
}));

const mockedPrisma2 = prisma as unknown as {
  monitor: { findMany: jest.Mock; findFirst: jest.Mock };
  monitorRun: { findMany: jest.Mock };
};

function makeRunHistoryRequest(body: any, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest('http://localhost/api/copilot/internal/get-monitor-run-history', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Secret': headers['X-Internal-Secret'] ?? SECRET,
      'X-Organization-Id': headers['X-Organization-Id'] ?? 'org_1',
    },
    body: JSON.stringify(body),
  });
}

describe('get-monitor-run-history POST', () => {
  beforeEach(() => {
    mockedPrisma2.monitor.findFirst.mockReset();
    mockedPrisma2.monitorRun.findMany.mockReset();
  });

  test('rejects when monitor_id missing', async () => {
    const res = await runHistoryPOST(makeRunHistoryRequest({}));
    expect(res.status).toBe(400);
  });

  test('returns 404 when monitor does not belong to org', async () => {
    mockedPrisma2.monitor.findFirst.mockResolvedValue(null);
    const res = await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_other' }));
    expect(res.status).toBe(404);
    expect(mockedPrisma2.monitor.findFirst).toHaveBeenCalledWith({
      where: { id: 'mon_other', organizationId: 'org_1' },
      select: { id: true, name: true, monitorType: true, targetFqn: true },
    });
  });

  test('returns recent runs ordered newest first', async () => {
    mockedPrisma2.monitor.findFirst.mockResolvedValue({
      id: 'mon_1',
      name: 'orders source validation',
      monitorType: 'DBT_CORE_SOURCE_VALIDATION',
      targetFqn: 'analytics.orders',
    });
    mockedPrisma2.monitorRun.findMany.mockResolvedValue([
      {
        id: 'run_2',
        status: 'FAIL',
        message: 'source freshness exceeded threshold',
        details: null,
        sqlExecuted: 'SELECT MAX(_loaded_at) ...',
        startedAt: new Date('2026-04-27T06:00:00Z'),
        completedAt: new Date('2026-04-27T06:00:02Z'),
        durationMs: 2000,
      },
      {
        id: 'run_1',
        status: 'PASS',
        message: null,
        details: null,
        sqlExecuted: 'SELECT MAX(_loaded_at) ...',
        startedAt: new Date('2026-04-26T06:00:00Z'),
        completedAt: new Date('2026-04-26T06:00:01Z'),
        durationMs: 1000,
      },
    ]);

    const res = await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1', limit: 5 }));
    const data = await res.json();

    expect(res.status).toBe(200);
    expect(data.monitor.id).toBe('mon_1');
    expect(data.runs).toHaveLength(2);
    expect(data.runs[0].id).toBe('run_2');
    expect(mockedPrisma2.monitorRun.findMany).toHaveBeenCalledWith({
      where: { monitorId: 'mon_1' },
      select: expect.any(Object),
      orderBy: { startedAt: 'desc' },
      take: 5,
    });
  });

  test('clamps limit to [1, 50]', async () => {
    mockedPrisma2.monitor.findFirst.mockResolvedValue({ id: 'mon_1', name: 'x', monitorType: 'FRESHNESS', targetFqn: 't' });
    mockedPrisma2.monitorRun.findMany.mockResolvedValue([]);

    await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1' }));
    expect((mockedPrisma2.monitorRun.findMany.mock.calls[0][0] as any).take).toBe(10);

    await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1', limit: 100 }));
    expect((mockedPrisma2.monitorRun.findMany.mock.calls[1][0] as any).take).toBe(50);

    await runHistoryPOST(makeRunHistoryRequest({ monitor_id: 'mon_1', limit: 0 }));
    expect((mockedPrisma2.monitorRun.findMany.mock.calls[2][0] as any).take).toBe(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx jest lib/__tests__/copilot-internal-monitors.test.ts -t 'get-monitor-run-history'
```

Expected: FAIL with `Cannot find module '@/app/api/copilot/internal/get-monitor-run-history/route'`.

- [ ] **Step 3: Create the endpoint**

Create `app/api/copilot/internal/get-monitor-run-history/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

function authorize(request: NextRequest): { ok: true; orgId: string } | { ok: false; status: number; error: string } {
  const secret = request.headers.get('X-Internal-Secret');
  const expected = process.env.INTERNAL_API_SECRET || 'pallisade-internal';
  if (!secret || secret !== expected) {
    return { ok: false, status: 401, error: 'invalid internal secret' };
  }
  const orgId = request.headers.get('X-Organization-Id');
  if (!orgId) {
    return { ok: false, status: 400, error: 'missing X-Organization-Id' };
  }
  return { ok: true, orgId };
}

export async function POST(request: NextRequest) {
  const auth = authorize(request);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    /* empty body */
  }

  const monitorId: string | undefined = typeof body?.monitor_id === 'string' ? body.monitor_id : undefined;
  if (!monitorId) {
    return NextResponse.json({ error: 'monitor_id is required' }, { status: 400 });
  }

  // Org-scope the lookup so a leaked id from another org returns 404, not data.
  const monitor = await prisma.monitor.findFirst({
    where: { id: monitorId, organizationId: auth.orgId },
    select: { id: true, name: true, monitorType: true, targetFqn: true },
  });
  if (!monitor) {
    return NextResponse.json({ error: 'monitor not found' }, { status: 404 });
  }

  const limitRaw = Number.isFinite(body?.limit) ? Number(body.limit) : 10;
  const limit = Math.max(1, Math.min(50, Math.trunc(limitRaw)));

  const runs = await prisma.monitorRun.findMany({
    where: { monitorId: monitor.id },
    select: {
      id: true,
      status: true,
      value: true,
      threshold: true,
      message: true,
      details: true,
      sqlExecuted: true,
      startedAt: true,
      completedAt: true,
      durationMs: true,
    },
    orderBy: { startedAt: 'desc' },
    take: limit,
  });

  return NextResponse.json({
    monitor,
    runs: runs.map((r) => ({
      ...r,
      startedAt: r.startedAt.toISOString(),
      completedAt: r.completedAt ? r.completedAt.toISOString() : null,
    })),
    total: runs.length,
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx jest lib/__tests__/copilot-internal-monitors.test.ts
```

Expected: 10 PASS (6 from Task 1 + 4 from Task 2).

- [ ] **Step 5: Commit**

```bash
git add app/api/copilot/internal/get-monitor-run-history/route.ts lib/__tests__/copilot-internal-monitors.test.ts
git commit -m "feat(copilot): add internal endpoint for monitor run history"
```

---

### Task 3: Register `list_configured_monitors` and `get_monitor_run_history` tools

**Files:**
- Modify: `scanner/copilot/tools/observability.py` (append at end of file)

- [ ] **Step 1: Read the existing file**

Open `scanner/copilot/tools/observability.py` to confirm the existing imports and pattern. The file already imports:

```python
from .registry import register_tool
from .base import ToolCategory, ToolParameter
```

- [ ] **Step 2: Append two new tool registrations**

Append at the end of `scanner/copilot/tools/observability.py`:

```python
@register_tool(
    name="list_configured_monitors",
    description=(
        "List the user's saved monitors with their current state. "
        "Use this whenever the user asks about THEIR monitors (e.g. 'why are "
        "my dbt monitors failing', 'show me failing monitors', 'what monitors "
        "are on the orders table'). This returns saved configuration — NOT "
        "ad-hoc results. Always call this BEFORE attempting run_coverage_monitor "
        "when the question is about saved monitors."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter(
            "monitor_type", "string",
            "Filter by monitor type. Pass a single value or comma-separated list. "
            "Examples: 'FRESHNESS', 'DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY'. "
            "Case-insensitive. Common values: FRESHNESS, VOLUME, NULL_CHECK, "
            "SCHEMA_CHANGE, ANOMALY, UNIQUENESS_CHECK, DBT_TEST_FAILURES, "
            "DBT_CORE_SOURCE_VALIDATION, DBT_CORE_REF_INTEGRITY, DAG_LAST_RUN, "
            "TASK_FAILURE_RATE, SYNC_LAG, FAILED_SYNCS.",
            required=False,
        ),
        ToolParameter(
            "status", "string",
            "Filter by last-run status. Pass a single value or comma-separated list. "
            "Values: PASS, WARN, FAIL, ERROR, SKIPPED, RUNNING.",
            required=False,
        ),
        ToolParameter(
            "target_fqn", "string",
            "Restrict to monitors whose target is exactly this FQN (e.g. 'analytics.orders').",
            required=False,
        ),
        ToolParameter(
            "enabled", "boolean",
            "Restrict to enabled (true) or disabled (false) monitors. Omit to include both.",
            required=False,
        ),
        ToolParameter(
            "limit", "integer",
            "Maximum number of monitors to return (default 50, max 200).",
            required=False,
            default=50,
        ),
    ],
)
def _meta_list_configured_monitors():
    pass


@register_tool(
    name="get_monitor_run_history",
    description=(
        "Get recent run history for a specific saved monitor — including the "
        "actual error message, SQL executed, and timing for each run. "
        "Use this AFTER list_configured_monitors when you've identified a "
        "specific failing monitor and want to see why it failed."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter(
            "monitor_id", "string",
            "The saved monitor's id (from list_configured_monitors).",
        ),
        ToolParameter(
            "limit", "integer",
            "Number of recent runs to return (default 10, max 50).",
            required=False,
            default=10,
        ),
    ],
)
def _meta_get_monitor_run_history():
    pass
```

- [ ] **Step 3: Verify the registry sees the new tools**

```bash
cd scanner && PYTHONPATH=. ./venv/bin/python -c "
from copilot.tools.registry import get_tool_registry
import copilot.tools  # force registration
reg = get_tool_registry()
print(sorted(t.name for t in reg.values() if t.name in ('list_configured_monitors', 'get_monitor_run_history')))
"
```

Expected output: `['get_monitor_run_history', 'list_configured_monitors']`.

- [ ] **Step 4: Commit**

```bash
git add scanner/copilot/tools/observability.py
git commit -m "feat(copilot): register list_configured_monitors and get_monitor_run_history tools"
```

---

### Task 4: Implement `_execute_list_configured_monitors`

**Files:**
- Modify: `scanner/copilot/tool_executor.py` (add new method)
- Create: `scanner/copilot/tests/test_saved_monitor_tools.py`

- [ ] **Step 1: Write the failing test**

Create `scanner/copilot/tests/test_saved_monitor_tools.py`:

```python
"""Tests for the saved-monitor visibility tools (list_configured_monitors,
get_monitor_run_history) — both POST to Next.js via _call_nextjs."""
import pytest
from unittest.mock import AsyncMock

from copilot.context_builder import CopilotContext
from copilot.tool_executor import ToolExecutor


def _ctx() -> CopilotContext:
    return CopilotContext(
        org_id="org_1",
        base_url="http://localhost:3000",
        auth_token="copilot-token",
    )


@pytest.mark.asyncio
async def test_list_configured_monitors_posts_filters_to_nextjs():
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock(return_value={
        "monitors": [
            {
                "id": "mon_1",
                "name": "orders source validation",
                "monitorType": "DBT_CORE_SOURCE_VALIDATION",
                "targetFqn": "analytics.orders",
                "enabled": True,
                "lastStatus": "FAIL",
                "lastRunAt": "2026-04-27T06:00:00Z",
            }
        ],
        "total": 1,
    })

    result = await executor.execute("list_configured_monitors", {
        "monitor_type": "DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY",
        "status": "FAIL,ERROR",
        "limit": 25,
    })

    assert result.success is True
    assert len(result.data["monitors"]) == 1
    assert result.data["monitors"][0]["id"] == "mon_1"

    executor._call_nextjs.assert_awaited_once()
    path, body = executor._call_nextjs.await_args.args
    assert path == "/api/copilot/internal/list-configured-monitors"
    assert body == {
        "monitor_type": "DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY",
        "status": "FAIL,ERROR",
        "limit": 25,
    }


@pytest.mark.asyncio
async def test_list_configured_monitors_surfaces_endpoint_errors():
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock(side_effect=Exception("Next.js /... failed (500): db down"))

    result = await executor.execute("list_configured_monitors", {})

    assert result.success is False
    assert "db down" in (result.error or "")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd scanner && PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_saved_monitor_tools.py -v
```

Expected: FAIL — likely `ToolResult(success=False, error='Unknown tool: list_configured_monitors')` because dispatch can't find the method yet.

- [ ] **Step 3: Add the executor method**

In `scanner/copilot/tool_executor.py`, add this method near the other observability/coverage methods (just after `_execute_get_monitor_recommendations` is a fine spot):

```python
    async def _execute_list_configured_monitors(self, args: Dict[str, Any]) -> ToolResult:
        """List the user's saved monitors via the Next.js Prisma-backed endpoint."""
        body = {
            k: v for k, v in {
                "monitor_type": args.get("monitor_type"),
                "status": args.get("status"),
                "target_fqn": args.get("target_fqn"),
                "enabled": args.get("enabled"),
                "limit": args.get("limit"),
            }.items()
            if v is not None
        }
        try:
            data = await self._call_nextjs(
                "/api/copilot/internal/list-configured-monitors",
                body,
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, data=data)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_saved_monitor_tools.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tool_executor.py scanner/copilot/tests/test_saved_monitor_tools.py
git commit -m "feat(copilot): wire list_configured_monitors executor"
```

---

### Task 5: Implement `_execute_get_monitor_run_history`

**Files:**
- Modify: `scanner/copilot/tool_executor.py`
- Modify: `scanner/copilot/tests/test_saved_monitor_tools.py`

- [ ] **Step 1: Append failing tests**

Append to `scanner/copilot/tests/test_saved_monitor_tools.py`:

```python
@pytest.mark.asyncio
async def test_get_monitor_run_history_posts_to_nextjs():
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock(return_value={
        "monitor": {
            "id": "mon_1",
            "name": "orders source validation",
            "monitorType": "DBT_CORE_SOURCE_VALIDATION",
            "targetFqn": "analytics.orders",
        },
        "runs": [
            {
                "id": "run_2",
                "status": "FAIL",
                "message": "source freshness exceeded threshold",
                "startedAt": "2026-04-27T06:00:00Z",
                "completedAt": "2026-04-27T06:00:02Z",
                "durationMs": 2000,
            }
        ],
        "total": 1,
    })

    result = await executor.execute("get_monitor_run_history", {
        "monitor_id": "mon_1",
        "limit": 5,
    })

    assert result.success is True
    assert result.data["runs"][0]["status"] == "FAIL"

    path, body = executor._call_nextjs.await_args.args
    assert path == "/api/copilot/internal/get-monitor-run-history"
    assert body == {"monitor_id": "mon_1", "limit": 5}


@pytest.mark.asyncio
async def test_get_monitor_run_history_requires_monitor_id():
    """The tool itself should reject a call without monitor_id rather than
    making a doomed network call."""
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock()

    result = await executor.execute("get_monitor_run_history", {})

    assert result.success is False
    assert "monitor_id" in (result.error or "").lower()
    executor._call_nextjs.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_saved_monitor_tools.py -v
```

Expected: 2 PASS (from Task 4) + 2 FAIL.

- [ ] **Step 3: Add the executor method**

Add to `scanner/copilot/tool_executor.py` immediately after `_execute_list_configured_monitors`:

```python
    async def _execute_get_monitor_run_history(self, args: Dict[str, Any]) -> ToolResult:
        """Fetch the recent run history for one saved monitor."""
        monitor_id = args.get("monitor_id")
        if not isinstance(monitor_id, str) or not monitor_id.strip():
            return ToolResult(
                success=False,
                error="monitor_id is required. Call list_configured_monitors first to find the right id.",
            )

        body: Dict[str, Any] = {"monitor_id": monitor_id}
        if "limit" in args and args["limit"] is not None:
            body["limit"] = args["limit"]

        try:
            data = await self._call_nextjs(
                "/api/copilot/internal/get-monitor-run-history",
                body,
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, data=data)
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_saved_monitor_tools.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tool_executor.py scanner/copilot/tests/test_saved_monitor_tools.py
git commit -m "feat(copilot): wire get_monitor_run_history executor"
```

---

### Task 6: Surface the new tools in `_get_available_tools`

**Files:**
- Modify: `scanner/copilot/context_builder.py:1340-1350`

The new tools have no integration prerequisite (they read from Prisma) — they belong in the always-available block alongside the existing coverage tools.

- [ ] **Step 1: Locate the always-available coverage block**

Open `scanner/copilot/context_builder.py` and search for the comment `# Coverage tools (always available`. Currently this block reads:

```python
        # Coverage tools (always available — they use the lineage graph
        # to compute scores/gaps/recommendations, no extra integration needed)
        tools.extend([
            "get_coverage_report",
            "get_coverage_gaps",
            "get_node_coverage",
            "get_monitor_recommendations",
        ])
```

- [ ] **Step 2: Add the two new tool names to that list**

Replace with:

```python
        # Coverage tools (always available — they use the lineage graph
        # to compute scores/gaps/recommendations, no extra integration needed)
        tools.extend([
            "get_coverage_report",
            "get_coverage_gaps",
            "get_node_coverage",
            "get_monitor_recommendations",
            # Saved-monitor visibility — query Prisma via Next.js callback.
            "list_configured_monitors",
            "get_monitor_run_history",
        ])
```

- [ ] **Step 3: Add a tiny test that confirms availability**

Append to `scanner/copilot/tests/test_saved_monitor_tools.py`:

```python
def test_saved_monitor_tools_are_always_available():
    from copilot.context_builder import CopilotContextBuilder

    builder = CopilotContextBuilder.__new__(CopilotContextBuilder)
    # Empty integration set — these tools must still be offered.
    tools = builder._get_available_tools(set())
    assert "list_configured_monitors" in tools
    assert "get_monitor_run_history" in tools
```

- [ ] **Step 4: Run all tests in the file**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_saved_monitor_tools.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/context_builder.py scanner/copilot/tests/test_saved_monitor_tools.py
git commit -m "feat(copilot): expose saved-monitor tools in available_tools"
```

---

### Task 7: System-prompt rule — call list_configured_monitors first

**Files:**
- Modify: `scanner/copilot/llm.py` (add a guidance block in `build_system_prompt`)
- Create: `scanner/copilot/tests/test_llm_prompt_saved_monitors.py`

- [ ] **Step 1: Write the failing test**

Create `scanner/copilot/tests/test_llm_prompt_saved_monitors.py`:

```python
"""The system prompt must instruct the LLM to use list_configured_monitors
when asked about the user's saved monitors, instead of immediately reaching
for run_coverage_monitor."""
from copilot.context_builder import CopilotContext
from copilot.llm import CopilotLLM


def _llm() -> CopilotLLM:
    return CopilotLLM.__new__(CopilotLLM)


def test_prompt_directs_llm_to_list_configured_monitors_first():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="why are my dbt core monitors failing")

    assert "list_configured_monitors" in prompt
    assert "get_monitor_run_history" in prompt
    # Must explicitly forbid the wandering pattern that produced the bug.
    assert "before" in prompt.lower() and "run_coverage_monitor" in prompt


def test_prompt_explains_what_dbt_core_monitors_are():
    ctx = CopilotContext(org_id="org_test")
    prompt = _llm().build_system_prompt(ctx, query="x")
    assert "DBT_CORE_SOURCE_VALIDATION" in prompt
    assert "DBT_CORE_REF_INTEGRITY" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_llm_prompt_saved_monitors.py -v
```

Expected: 2 FAIL.

- [ ] **Step 3: Add the guidance block**

Open `scanner/copilot/llm.py` and find the existing block titled `## Distinguishing Ad-Hoc Checks From Configured Monitors` (added earlier on this branch — search for that exact heading). Replace that block with the expanded version below:

```text
## Investigating Saved Monitors (REQUIRED FIRST STEP)

When the user asks about their monitors — "why are my monitors failing", "which monitors are red", "are my dbt core monitors working", anything in that family — you MUST start with `list_configured_monitors` filtered to the relevant monitor type or table. Do NOT reach for `run_coverage_monitor` first; that runs an ad-hoc one-off check and tells you nothing about saved state.

The "dbt core monitors" the user means are `DBT_CORE_SOURCE_VALIDATION` and `DBT_CORE_REF_INTEGRITY` — they validate the parsed dbt manifest's sources and ref integrity. They have nothing to do with freshness. If the user says "my dbt core monitors are failing", call:

```
list_configured_monitors(monitor_type="DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY", status="FAIL,ERROR")
```

Then for each failing monitor returned, call `get_monitor_run_history(monitor_id=<id>, limit=5)` to see the actual error message and SQL executed. Report findings *from those run records* — never from your own ad-hoc tool calls.

## Distinguishing Ad-Hoc Checks From Configured Monitors

When you call `run_coverage_monitor`, you are running a one-off check that you initiated, not querying a saved monitor. If that check errors (missing column config, invalid SQL, etc.) it is a problem with your tool call, not evidence that "a monitor on the user's dashboard is failing." Never report `run_coverage_monitor` errors as "the user's freshness monitor is broken." If you want to report on actual configured monitors, use `list_configured_monitors` and `get_monitor_run_history` — those reflect saved state.
```

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_llm_prompt_saved_monitors.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run the existing prompt tests too — they must still pass**

```bash
PYTHONPATH=. ./venv/bin/pytest copilot/tests/test_llm_prompt_guidance.py copilot/tests/test_llm_prompt_saved_monitors.py -v
```

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/llm.py scanner/copilot/tests/test_llm_prompt_saved_monitors.py
git commit -m "feat(copilot): instruct LLM to use list_configured_monitors before ad-hoc tools"
```

---

### Task 8: Full regression sweep + manual smoke test

- [ ] **Step 1: Run all relevant Python tests**

```bash
cd scanner && PYTHONPATH=. ./venv/bin/pytest \
  copilot/tests/test_saved_monitor_tools.py \
  copilot/tests/test_llm_prompt_saved_monitors.py \
  copilot/tests/test_llm_prompt_guidance.py \
  copilot/tests/test_dbt_manifest_resolution.py \
  copilot/tests/test_dbt_manifest_errors.py \
  copilot/tests/test_context_builder_dbt_visibility.py \
  copilot/tests/test_write_tools.py \
  tests/copilot \
  tests/integrations \
  tests/test_freshness_cadence.py \
  tests/test_freshness_no_column_fail_loud.py
```

Expected: all new tests pass; pre-existing failures listed in **Conventions** above remain (and only those).

- [ ] **Step 2: Run all relevant TS tests**

```bash
cd /Users/emilfabel/pallisade-copilot && \
  npx jest lib/__tests__/copilot-internal-monitors.test.ts \
           lib/__tests__/integration-credentials.test.ts \
           lib/__tests__/crypto.test.ts \
           lib/__tests__/scanner-client.test.ts
```

Expected: all green.

- [ ] **Step 3: Manual smoke test**

Start the Next.js dev server and the FastAPI scanner. In the copilot UI, ask:

> "why are my dbt core monitors failing?"

Watch the FastAPI logs. You should see:

```
[Stream/OpenAI] Executing tool: list_configured_monitors
```

…before any `run_coverage_monitor` call. If `list_configured_monitors` returns an empty list, the LLM should tell the user "I don't see any DBT_CORE_SOURCE_VALIDATION or DBT_CORE_REF_INTEGRITY monitors configured" rather than fabricating findings.

- [ ] **Step 4: Final commit (chore: any cleanup)**

If anything was missed, fix and commit. Otherwise this task has no commit.

---

## Out of scope (do not do in this plan)

- New tool: `list_monitor_groups` / inspecting `MonitorGroup`. Could come later — not needed to fix the immediate hallucination.
- `Monitor` write operations (create/update/disable). The change-plan flow already exists for that.
- Changes to `run_coverage_monitor`. The earlier session already added a fail-loud `ValueError` and the system-prompt now guides the LLM away from misuse. Don't touch.
- Streaming the new tools' results into the system prompt as preloaded context. We want the LLM to *call* the tools so its calls are logged and interpretable.

## Verification of out-of-scope assumption

If during execution you find that the LLM still misbehaves even with these tools available, do NOT add more layers. Stop and consult — the next likely fix is the `_intent` classifier or the mode config (`scanner/copilot/modes.py`), not more prompt rules or more tools.
