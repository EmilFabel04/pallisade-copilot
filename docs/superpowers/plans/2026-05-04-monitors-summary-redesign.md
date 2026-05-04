# Monitors Summary Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the Monitors Summary tab around the question "should I be worried right now?" by introducing an `Incident` lifecycle (open → acknowledged → resolved with a mute flag), an LLM-generated root-cause hypothesis rendered inline on each active incident, and an MTTR/recovered-rate trend strip — replacing the current category pills + asset rows + collapsed SLA recommendations layout.

**Architecture:** The Prisma DB is owned by Next.js. A new `Incident` Prisma model holds one row per fault episode. After every monitor run the existing `app/api/schedule/tasks/[taskId]/run/route.ts` calls `lib/incidents/lifecycle.handleRun(...)` which opens, updates, or auto-resolves an incident. When diagnosis is needed the route fires `diagnoseIncident(...)` (fire-and-forget); that function HTTPs to a new scanner endpoint `POST /api/v1/copilot/incident-diagnose` which wraps the existing copilot LLM tool-calling pipeline and returns `{hypothesis, signature, ownerSystem, ownerConfidence}`. A per-stack semaphore caps LLM concurrency. New REST endpoints (`/api/incidents/*`) expose list, ack, resolve, mute/unmute, reanalyze, and stats. Five new React components (`SummaryHero`, `IncidentCard`, `ActiveIncidents`, `TrendStrip`, `AssetHealthLean`, `CoverageGaps`) compose the redesigned Summary tab; the existing Pipeline Health tiles relocate to the Pipeline Monitors tab.

**Tech Stack:** Next.js 15 (App Router), Prisma 5, FastAPI / Pydantic, Jest 30 + ts-jest (TS tests), pytest (Python tests), React 19, TailwindCSS, lucide-react, sonner.

**Spec:** `docs/superpowers/specs/2026-05-04-monitors-summary-redesign-design.md`

---

## File Structure

**Database:**
- `prisma/schema.prisma` — add `Incident` model + `IncidentStatus`, `IncidentResolutionType` enums

**Next.js (TS):**
- `lib/incidents/lifecycle.ts` (new) — pure function decisions for open / update / auto-resolve based on monitor run
- `lib/incidents/signature.ts` (new) — deterministic fallback signature
- `lib/incidents/diagnose.ts` (new) — scanner HTTP orchestration with per-stack semaphore
- `lib/incidents/__tests__/lifecycle.test.ts` (new)
- `lib/incidents/__tests__/signature.test.ts` (new)
- `lib/incidents/__tests__/diagnose.test.ts` (new)
- `app/api/schedule/tasks/[taskId]/run/route.ts` (modify) — call lifecycle after `monitorRun.create`
- `app/api/incidents/route.ts` (new) — `GET` list
- `app/api/incidents/[id]/acknowledge/route.ts` (new)
- `app/api/incidents/[id]/resolve/route.ts` (new)
- `app/api/incidents/[id]/mute/route.ts` (new)
- `app/api/incidents/[id]/unmute/route.ts` (new)
- `app/api/incidents/[id]/reanalyze/route.ts` (new)
- `app/api/incidents/stats/route.ts` (new) — pass rate, MTTR, opened/recovered counts, sparklines
- `prisma/__tests__/incidents.test.ts` (new) — integration tests against a real Prisma test DB
- `types/incident.ts` (new) — shared frontend types
- `prisma/scripts/backfill-incidents.ts` (new) — one-shot backfill script

**Frontend:**
- `components/monitors/SummaryHero.tsx` (new)
- `components/monitors/IncidentCard.tsx` (new)
- `components/monitors/ActiveIncidents.tsx` (new)
- `components/monitors/TrendStrip.tsx` (new)
- `components/monitors/AssetHealthLean.tsx` (new)
- `components/monitors/CoverageGaps.tsx` (new)
- `components/monitors/PipelineHealthTiles.tsx` (new — extracted from current `DriftSummaryTab`)
- `components/monitors/DriftSummaryTab.tsx` (replace)
- `app/(dashboard)/dashboard/monitors/page.tsx` (modify) — render `PipelineHealthTiles` above the Pipeline Monitors tab list

**Scanner (Python):**
- `scanner/copilot/incident_diagnosis.py` (new)
- `scanner/api/routers/copilot.py` (modify) — add `POST /api/v1/copilot/incident-diagnose`
- `scanner/tests/copilot/test_incident_diagnosis.py` (new)

---

### Task 1: Add `Incident` Prisma model

**Files:**
- Modify: `prisma/schema.prisma`

- [ ] **Step 1: Add the model and enums**

Add to `prisma/schema.prisma` (place after the `MonitorRun` model definition, near line ~430 — find the model and insert after it):

```prisma
enum IncidentStatus {
  OPEN
  ACKNOWLEDGED
  RESOLVED
}

enum IncidentResolutionType {
  AUTO_RECOVERED
  FIXED
  EXPECTED
  FALSE_POSITIVE
  WONT_FIX
}

enum IncidentSeverity {
  FAIL
  WARN
}

model Incident {
  id String @id @default(cuid())

  // Tenancy
  organizationId  String
  pipelineStackId String

  // Source monitor
  monitorId       String
  monitor         Monitor @relation(fields: [monitorId], references: [id], onDelete: Cascade)
  monitorGroupId  String?
  targetFqn       String

  // Lifecycle
  status          IncidentStatus   @default(OPEN)
  severity        IncidentSeverity // FAIL → red hero, WARN → amber hero
  openedAt        DateTime
  openingRunId    String

  // LLM diagnosis (nullable until first analysis completes)
  signature         String?
  consecutiveCount  Int     @default(1)
  llmHypothesis     String?
  llmHypothesisAt   DateTime?
  ownerSystem       String?
  ownerConfidence   Float?

  // Acknowledgement
  acknowledgedAt DateTime?
  acknowledgedBy String?

  // Resolution
  resolvedAt     DateTime?
  resolvedBy     String?  // user id, or 'system' for auto
  resolutionType IncidentResolutionType?
  resolutionNote String?

  // Mute (orthogonal flag)
  mutedUntil  DateTime?
  mutedBy     String?
  mutedReason String?

  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  @@index([organizationId, pipelineStackId, status])
  @@index([monitorId, status])
  @@index([openedAt])
  @@index([resolvedAt])
}
```

- [ ] **Step 2: Add the back-reference on `Monitor`**

Find the `Monitor` model in `prisma/schema.prisma`. Add this line just before the closing `}` of the model:

```prisma
  incidents Incident[]
```

- [ ] **Step 3: Generate the Prisma client and push the schema**

Run:

```bash
npx prisma generate
npx prisma db push
```

Expected: "Your database is now in sync with your Prisma schema." and "✔ Generated Prisma Client".

- [ ] **Step 4: Commit**

```bash
git add prisma/schema.prisma
git commit -m "feat(incidents): add Incident model with lifecycle + mute fields"
```

---

### Task 2: Lifecycle pure function — opening an incident

**Files:**
- Create: `lib/incidents/lifecycle.ts`
- Test: `lib/incidents/__tests__/lifecycle.test.ts`

The lifecycle module owns the decision: given a `MonitorRun` row that just got persisted, what should happen to the `Incident` table? It's split out as a pure function so we can unit-test without spinning up a server.

- [ ] **Step 1: Write the failing test for "FAIL run with no open incident opens a new one"**

Create `lib/incidents/__tests__/lifecycle.test.ts`:

```ts
/**
 * Run with: npx jest lib/incidents/__tests__/lifecycle.test.ts
 */

import { handleRun, LifecycleResult } from '../lifecycle';

// Minimal fakes — we type the prisma client narrowly so the test does not
// require a real DB connection.
type FakeRun = {
  id: string;
  monitorId: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'ERROR' | 'SKIPPED';
  startedAt: Date;
  completedAt: Date | null;
};

type FakeIncident = {
  id: string;
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';
  signature: string | null;
  consecutiveCount: number;
};

function makePrismaMock(opts: {
  monitor: { id: string; organizationId: string; pipelineStackId: string; targetFqn: string; monitorGroupId?: string | null };
  existingIncident?: FakeIncident | null;
}) {
  const incidentCreate = jest.fn(async (args: any) => ({ id: 'inc_new', ...args.data }));
  const incidentUpdate = jest.fn(async (args: any) => ({ ...opts.existingIncident, ...args.data }));
  const incidentFindFirst = jest.fn(async () => opts.existingIncident ?? null);
  const monitorFindUnique = jest.fn(async () => opts.monitor);

  return {
    incident: { create: incidentCreate, update: incidentUpdate, findFirst: incidentFindFirst },
    monitor: { findUnique: monitorFindUnique },
    _spies: { incidentCreate, incidentUpdate, incidentFindFirst },
  } as any;
}

describe('handleRun: opening', () => {
  it('opens a new incident when a FAIL run has no open incident on this monitor', async () => {
    const prisma = makePrismaMock({
      monitor: {
        id: 'mon_1',
        organizationId: 'org_1',
        pipelineStackId: 'stack_1',
        targetFqn: 'raw.orders',
        monitorGroupId: 'grp_1',
      },
      existingIncident: null,
    });

    const run: FakeRun = {
      id: 'run_1',
      monitorId: 'mon_1',
      status: 'FAIL',
      startedAt: new Date('2026-05-04T10:00:00Z'),
      completedAt: new Date('2026-05-04T10:00:05Z'),
    };

    const result: LifecycleResult = await handleRun(run as any, prisma);

    expect(result.action).toBe('opened');
    expect(result.shouldDiagnose).toBe(true);
    expect(prisma._spies.incidentCreate).toHaveBeenCalledTimes(1);
    const call = prisma._spies.incidentCreate.mock.calls[0][0];
    expect(call.data).toMatchObject({
      monitorId: 'mon_1',
      organizationId: 'org_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      status: 'OPEN',
      severity: 'FAIL',
      openingRunId: 'run_1',
      consecutiveCount: 1,
    });
    expect(call.data.openedAt).toEqual(run.startedAt);
  });

  it('opens with severity=WARN when the run is WARN', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: null,
    });
    const run: FakeRun = {
      id: 'run_w',
      monitorId: 'mon_1',
      status: 'WARN',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    await handleRun(run as any, prisma);
    const call = prisma._spies.incidentCreate.mock.calls[0][0];
    expect(call.data.severity).toBe('WARN');
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `npx jest lib/incidents/__tests__/lifecycle.test.ts`
Expected: FAIL — `Cannot find module '../lifecycle'`.

- [ ] **Step 3: Create the minimal lifecycle module**

Create `lib/incidents/lifecycle.ts`:

```ts
import type { PrismaClient, MonitorRun } from '@prisma/client';

export type LifecycleAction = 'opened' | 'updated' | 'noop' | 'auto_resolved';

export interface LifecycleResult {
  action: LifecycleAction;
  shouldDiagnose: boolean;
  incidentId?: string;
}

const FAILING = new Set(['FAIL', 'WARN', 'ERROR']);

export async function handleRun(
  run: MonitorRun,
  prisma: PrismaClient,
): Promise<LifecycleResult> {
  const monitor = await prisma.monitor.findUnique({
    where: { id: run.monitorId },
    select: {
      id: true,
      organizationId: true,
      pipelineStackId: true,
      targetFqn: true,
      monitorGroupId: true,
    },
  });
  if (!monitor || !monitor.organizationId || !monitor.pipelineStackId) {
    return { action: 'noop', shouldDiagnose: false };
  }

  const existing = await prisma.incident.findFirst({
    where: { monitorId: run.monitorId, status: { in: ['OPEN', 'ACKNOWLEDGED'] } },
  });

  if (FAILING.has(run.status)) {
    if (!existing) {
      const severity = run.status === 'WARN' ? 'WARN' : 'FAIL';
      const created = await prisma.incident.create({
        data: {
          organizationId: monitor.organizationId,
          pipelineStackId: monitor.pipelineStackId,
          monitorId: monitor.id,
          monitorGroupId: monitor.monitorGroupId ?? null,
          targetFqn: monitor.targetFqn ?? 'unknown',
          status: 'OPEN',
          severity,
          openedAt: run.startedAt,
          openingRunId: run.id,
          consecutiveCount: 1,
        },
      });
      return { action: 'opened', shouldDiagnose: true, incidentId: created.id };
    }
    // Existing open/ack incident — diagnosis decision made later in diagnose.ts
    return { action: 'updated', shouldDiagnose: existing.consecutiveCount < 3, incidentId: existing.id };
  }

  // PASS / SKIPPED on a target with an open incident → auto-resolve
  if (run.status === 'PASS' && existing) {
    await prisma.incident.update({
      where: { id: existing.id },
      data: {
        status: 'RESOLVED',
        resolvedAt: run.completedAt ?? new Date(),
        resolvedBy: 'system',
        resolutionType: 'AUTO_RECOVERED',
      },
    });
    return { action: 'auto_resolved', shouldDiagnose: false, incidentId: existing.id };
  }

  return { action: 'noop', shouldDiagnose: false };
}
```

- [ ] **Step 4: Run the test, confirm it passes**

Run: `npx jest lib/incidents/__tests__/lifecycle.test.ts`
Expected: PASS, 1 test.

- [ ] **Step 5: Commit**

```bash
git add lib/incidents/lifecycle.ts lib/incidents/__tests__/lifecycle.test.ts
git commit -m "feat(incidents): lifecycle handleRun opens new incident on FAIL"
```

---

### Task 3: Lifecycle — auto-resolve on PASS, increment on existing

**Files:**
- Modify: `lib/incidents/__tests__/lifecycle.test.ts`

- [ ] **Step 1: Add the auto-resolve test**

Append to `lib/incidents/__tests__/lifecycle.test.ts`:

```ts
describe('handleRun: auto-resolve', () => {
  it('marks an open incident RESOLVED when a PASS run lands', async () => {
    const prisma = makePrismaMock({
      monitor: {
        id: 'mon_1',
        organizationId: 'org_1',
        pipelineStackId: 'stack_1',
        targetFqn: 'raw.orders',
      },
      existingIncident: {
        id: 'inc_1',
        status: 'OPEN',
        signature: 'fivetran-source-stalled',
        consecutiveCount: 2,
      },
    });

    const run: FakeRun = {
      id: 'run_2',
      monitorId: 'mon_1',
      status: 'PASS',
      startedAt: new Date('2026-05-04T11:00:00Z'),
      completedAt: new Date('2026-05-04T11:00:05Z'),
    };

    const result = await handleRun(run as any, prisma);

    expect(result.action).toBe('auto_resolved');
    expect(result.shouldDiagnose).toBe(false);
    expect(prisma._spies.incidentUpdate).toHaveBeenCalledTimes(1);
    const call = prisma._spies.incidentUpdate.mock.calls[0][0];
    expect(call.where).toEqual({ id: 'inc_1' });
    expect(call.data).toMatchObject({
      status: 'RESOLVED',
      resolvedBy: 'system',
      resolutionType: 'AUTO_RECOVERED',
    });
    expect(call.data.resolvedAt).toEqual(run.completedAt);
  });

  it('does nothing when a PASS run lands with no open incident', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: null,
    });
    const run: FakeRun = {
      id: 'run_3',
      monitorId: 'mon_1',
      status: 'PASS',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    const result = await handleRun(run as any, prisma);
    expect(result.action).toBe('noop');
    expect(prisma._spies.incidentCreate).not.toHaveBeenCalled();
    expect(prisma._spies.incidentUpdate).not.toHaveBeenCalled();
  });

  it('returns shouldDiagnose=true when a FAIL run hits an existing incident with consecutiveCount < 3', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: { id: 'inc_1', status: 'OPEN', signature: 'fivetran-source-stalled', consecutiveCount: 2 },
    });
    const run: FakeRun = {
      id: 'run_4',
      monitorId: 'mon_1',
      status: 'FAIL',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    const result = await handleRun(run as any, prisma);
    expect(result.action).toBe('updated');
    expect(result.shouldDiagnose).toBe(true);
    expect(result.incidentId).toBe('inc_1');
  });

  it('returns shouldDiagnose=false when a FAIL run hits an existing incident with consecutiveCount >= 3', async () => {
    const prisma = makePrismaMock({
      monitor: { id: 'mon_1', organizationId: 'org_1', pipelineStackId: 'stack_1', targetFqn: 'raw.orders' },
      existingIncident: { id: 'inc_1', status: 'OPEN', signature: 'fivetran-source-stalled', consecutiveCount: 3 },
    });
    const run: FakeRun = {
      id: 'run_5',
      monitorId: 'mon_1',
      status: 'FAIL',
      startedAt: new Date(),
      completedAt: new Date(),
    };
    const result = await handleRun(run as any, prisma);
    expect(result.action).toBe('updated');
    expect(result.shouldDiagnose).toBe(false);
  });
});
```

- [ ] **Step 2: Run the tests**

Run: `npx jest lib/incidents/__tests__/lifecycle.test.ts`
Expected: all 4 tests PASS (the lifecycle code from Task 2 already covers these branches).

- [ ] **Step 3: Commit**

```bash
git add lib/incidents/__tests__/lifecycle.test.ts
git commit -m "test(incidents): cover auto-resolve and consecutive-count branching"
```

---

### Task 4: Fallback signature module

**Files:**
- Create: `lib/incidents/signature.ts`
- Test: `lib/incidents/__tests__/signature.test.ts`

When the LLM call fails, we still want a stable signature so the dedup counter still works.

- [ ] **Step 1: Write the failing test**

Create `lib/incidents/__tests__/signature.test.ts`:

```ts
import { fallbackSignature } from '../signature';

describe('fallbackSignature', () => {
  it('produces the same slug for the same monitor type and breach class', () => {
    const a = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    const b = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    expect(a).toEqual(b);
  });

  it('differs across monitor types', () => {
    const a = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    const b = fallbackSignature({ monitorType: 'VOLUME',    breachClass: 'over-threshold' });
    expect(a).not.toEqual(b);
  });

  it('produces a kebab-case slug shorter than 32 chars', () => {
    const slug = fallbackSignature({ monitorType: 'FRESHNESS', breachClass: 'over-threshold' });
    expect(slug).toMatch(/^[a-z0-9-]+$/);
    expect(slug.length).toBeLessThanOrEqual(32);
  });
});
```

- [ ] **Step 2: Run the test, confirm failure**

Run: `npx jest lib/incidents/__tests__/signature.test.ts`
Expected: FAIL — `Cannot find module '../signature'`.

- [ ] **Step 3: Implement**

Create `lib/incidents/signature.ts`:

```ts
import { createHash } from 'crypto';

export interface SignatureInput {
  monitorType: string;     // e.g. 'FRESHNESS'
  breachClass: string;     // e.g. 'over-threshold' | 'under-threshold' | 'schema-changed' | 'unknown'
}

export function fallbackSignature(input: SignatureInput): string {
  const key = `${input.monitorType.toLowerCase()}|${input.breachClass.toLowerCase()}`;
  const hash = createHash('sha1').update(key).digest('hex').slice(0, 8);
  // Slug: monitorType (lowercase) + 8-char hash, capped at 32 chars
  const prefix = input.monitorType.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 22);
  return `${prefix}-${hash}`;
}
```

- [ ] **Step 4: Run the test, confirm pass**

Run: `npx jest lib/incidents/__tests__/signature.test.ts`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/incidents/signature.ts lib/incidents/__tests__/signature.test.ts
git commit -m "feat(incidents): deterministic fallback signature for LLM-unavailable case"
```

---

### Task 5: Scanner — incident_diagnosis module

**Files:**
- Create: `scanner/copilot/incident_diagnosis.py`
- Test: `scanner/tests/copilot/test_incident_diagnosis.py`

This wraps the existing `scanner/copilot/llm.py` tool-calling pipeline with a scoped prompt that returns JSON.

- [ ] **Step 1: Write the failing test**

Create `scanner/tests/copilot/test_incident_diagnosis.py`:

```python
"""
Run with: pytest scanner/tests/copilot/test_incident_diagnosis.py -v
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from scanner.copilot.incident_diagnosis import diagnose_incident, DiagnosisRequest


def test_diagnose_returns_json_fields_from_llm(monkeypatch):
    fake_llm_response = {
        "content": '{"hypothesis": "Upstream sync stalled at 09:14.", "signature": "fivetran-source-stalled"}',
        "tool_call_evidence": [
            {"tool": "query_warehouse", "input": "...", "output": "..."},
        ],
    }

    with patch("scanner.copilot.incident_diagnosis._call_copilot_llm", return_value=fake_llm_response) as call:
        with patch("scanner.copilot.incident_diagnosis._classify_owner", return_value=("ingestion", 0.85)):
            req = DiagnosisRequest(
                stack_id="stack_1",
                monitor_run_id="run_1",
                target_fqn="raw.orders",
                monitor_type="FRESHNESS",
                run_details={"value": 26.2, "threshold": 24, "message": "stale"},
            )
            result = diagnose_incident(req)

    assert call.called
    assert result.hypothesis.startswith("Upstream sync")
    assert result.signature == "fivetran-source-stalled"
    assert result.owner_system == "ingestion"
    assert result.owner_confidence == 0.85


def test_diagnose_rejects_invalid_json_with_fallback():
    fake_llm_response = {"content": "not json at all", "tool_call_evidence": []}

    with patch("scanner.copilot.incident_diagnosis._call_copilot_llm", return_value=fake_llm_response):
        with patch("scanner.copilot.incident_diagnosis._classify_owner", return_value=("unknown", 0.0)):
            req = DiagnosisRequest(
                stack_id="stack_1",
                monitor_run_id="run_1",
                target_fqn="raw.orders",
                monitor_type="FRESHNESS",
                run_details={},
            )
            result = diagnose_incident(req)

    # Falls back to a deterministic signature based on monitor type
    assert result.signature == "freshness-unknown"
    # Hypothesis is the LLM's raw text since JSON parse failed
    assert "not json" in result.hypothesis or result.hypothesis  # non-empty
```

- [ ] **Step 2: Run the test, confirm failure**

Run: `cd scanner && source venv/bin/activate && pytest tests/copilot/test_incident_diagnosis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.copilot.incident_diagnosis'`.

- [ ] **Step 3: Implement the module**

Create `scanner/copilot/incident_diagnosis.py`:

```python
"""
Incident diagnosis — wraps the copilot LLM tool-calling pipeline with a
scoped prompt that returns JSON {hypothesis, signature}, and runs the
deterministic owner classifier on the gathered evidence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from scanner.copilot.llm import CopilotLLM
from scanner.copilot.context_builder import CopilotContextBuilder
from scanner.copilot.tool_executor import ToolExecutor
from scanner.copilot.root_cause import classify_owner_from_evidence


SYSTEM_PROMPT = """You are diagnosing a single monitor failure for an observability platform.
Use the available tools (warehouse queries, lineage lookups, dbt status, connector status) to
gather just enough evidence to form a hypothesis. Limit yourself to ~6 tool calls.

When you have enough evidence, respond ONLY with a JSON object — no prose around it:
{"hypothesis": "<at most 2 sentences explaining the most likely cause>",
 "signature": "<short kebab-case slug under 32 chars, e.g. fivetran-source-stalled, dbt-test-not-null-failed, schema-added-column>"}
"""


@dataclass
class DiagnosisRequest:
    stack_id: str
    monitor_run_id: str
    target_fqn: str
    monitor_type: str
    run_details: Dict[str, Any]


@dataclass
class DiagnosisResult:
    hypothesis: str
    signature: str
    owner_system: str
    owner_confidence: float


def _fallback_signature(monitor_type: str, breach_class: str) -> str:
    return f"{monitor_type.lower()}-{breach_class.lower()}"[:32]


def _slugify_signature(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:32] or "unknown"


def _call_copilot_llm(messages: list, tools: list, stack_id: str) -> Dict[str, Any]:
    """Thin wrapper around CopilotLLM so the test can patch this single function."""
    llm = CopilotLLM()
    response = llm.chat(messages=messages, tools=tools, stack_id=stack_id, max_tool_calls=6)
    return {
        "content": response.get("content", ""),
        "tool_call_evidence": response.get("tool_call_evidence", []),
    }


def _classify_owner(evidence: list, run_details: Dict[str, Any]):
    decision = classify_owner_from_evidence(evidence=evidence, error_text=str(run_details.get("message", "")))
    return decision.owner_system.value, float(decision.confidence)


def diagnose_incident(req: DiagnosisRequest) -> DiagnosisResult:
    builder = CopilotContextBuilder(stack_id=req.stack_id)
    user_message = (
        f"Monitor `{req.monitor_type}` on `{req.target_fqn}` failed. Run details: "
        f"{json.dumps(req.run_details, default=str)[:1500]}. "
        "Investigate and return the JSON object."
    )
    messages = [{"role": "user", "content": user_message}]
    tools = ToolExecutor(stack_id=req.stack_id).list_tools()

    response = _call_copilot_llm(messages=messages, tools=tools, stack_id=req.stack_id)
    content = response["content"] or ""
    evidence = response["tool_call_evidence"]

    hypothesis: Optional[str] = None
    signature: Optional[str] = None
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else json.loads(content)
        hypothesis = str(parsed.get("hypothesis") or "").strip() or None
        raw_sig = str(parsed.get("signature") or "").strip()
        if raw_sig:
            signature = _slugify_signature(raw_sig)
    except Exception:
        pass

    if not hypothesis:
        hypothesis = content.strip()[:500] or "Unable to generate hypothesis"
    if not signature:
        breach_class = "unknown"
        if "threshold" in req.run_details and "value" in req.run_details:
            try:
                v = float(req.run_details["value"]); t = float(req.run_details["threshold"])
                breach_class = "over-threshold" if v > t else "under-threshold"
            except Exception:
                pass
        signature = _fallback_signature(req.monitor_type, breach_class)

    owner_system, owner_confidence = _classify_owner(evidence, req.run_details)
    return DiagnosisResult(
        hypothesis=hypothesis,
        signature=signature,
        owner_system=owner_system,
        owner_confidence=owner_confidence,
    )
```

- [ ] **Step 4: Run the test, confirm pass**

Run: `cd scanner && source venv/bin/activate && pytest tests/copilot/test_incident_diagnosis.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/incident_diagnosis.py scanner/tests/copilot/test_incident_diagnosis.py
git commit -m "feat(scanner/copilot): incident_diagnosis wraps LLM tool calls with JSON output"
```

---

### Task 6: Scanner endpoint — `POST /api/v1/copilot/incident-diagnose`

**Files:**
- Modify: `scanner/api/routers/copilot.py`
- Test: extend `scanner/tests/copilot/test_incident_diagnosis.py` with a router test

- [ ] **Step 1: Add the router test**

Append to `scanner/tests/copilot/test_incident_diagnosis.py`:

```python
from fastapi.testclient import TestClient
from scanner.api.server import app


def test_router_accepts_diagnose_request():
    client = TestClient(app)
    payload = {
        "stackId": "stack_1",
        "monitorRunId": "run_1",
        "targetFqn": "raw.orders",
        "monitorType": "FRESHNESS",
        "runDetails": {"value": 26, "threshold": 24, "message": "stale"},
    }
    fake_result_dict = {
        "hypothesis": "Upstream sync stalled.",
        "signature": "fivetran-source-stalled",
        "owner_system": "ingestion",
        "owner_confidence": 0.85,
    }

    with patch("scanner.api.routers.copilot.diagnose_incident") as fake:
        from scanner.copilot.incident_diagnosis import DiagnosisResult
        fake.return_value = DiagnosisResult(
            hypothesis=fake_result_dict["hypothesis"],
            signature=fake_result_dict["signature"],
            owner_system=fake_result_dict["owner_system"],
            owner_confidence=fake_result_dict["owner_confidence"],
        )
        res = client.post("/api/v1/copilot/incident-diagnose", json=payload)

    assert res.status_code == 200
    body = res.json()
    assert body["hypothesis"] == "Upstream sync stalled."
    assert body["signature"] == "fivetran-source-stalled"
    assert body["ownerSystem"] == "ingestion"
    assert body["ownerConfidence"] == 0.85
```

- [ ] **Step 2: Run the test, confirm failure**

Run: `cd scanner && source venv/bin/activate && pytest tests/copilot/test_incident_diagnosis.py::test_router_accepts_diagnose_request -v`
Expected: 404 (route not yet defined) — test FAILS.

- [ ] **Step 3: Add the route**

In `scanner/api/routers/copilot.py`, add at the bottom of the file (after the existing routes):

```python
from scanner.copilot.incident_diagnosis import diagnose_incident, DiagnosisRequest, DiagnosisResult
from pydantic import BaseModel


class IncidentDiagnoseRequest(BaseModel):
    stackId: str
    monitorRunId: str
    targetFqn: str
    monitorType: str
    runDetails: Dict[str, Any]


class IncidentDiagnoseResponse(BaseModel):
    hypothesis: str
    signature: str
    ownerSystem: str
    ownerConfidence: float


@router.post("/incident-diagnose", response_model=IncidentDiagnoseResponse)
def post_incident_diagnose(req: IncidentDiagnoseRequest) -> IncidentDiagnoseResponse:
    result: DiagnosisResult = diagnose_incident(DiagnosisRequest(
        stack_id=req.stackId,
        monitor_run_id=req.monitorRunId,
        target_fqn=req.targetFqn,
        monitor_type=req.monitorType,
        run_details=req.runDetails,
    ))
    return IncidentDiagnoseResponse(
        hypothesis=result.hypothesis,
        signature=result.signature,
        ownerSystem=result.owner_system,
        ownerConfidence=result.owner_confidence,
    )
```

If the file doesn't already import `Dict, Any` from typing, add `from typing import Any, Dict` at the top of the imports block.

- [ ] **Step 4: Run the test, confirm pass**

Run: `cd scanner && source venv/bin/activate && pytest tests/copilot/test_incident_diagnosis.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/api/routers/copilot.py scanner/tests/copilot/test_incident_diagnosis.py
git commit -m "feat(scanner/api): POST /api/v1/copilot/incident-diagnose"
```

---

### Task 7: Diagnose orchestration with per-stack semaphore

**Files:**
- Create: `lib/incidents/diagnose.ts`
- Test: `lib/incidents/__tests__/diagnose.test.ts`

- [ ] **Step 1: Write the failing test**

Create `lib/incidents/__tests__/diagnose.test.ts`:

```ts
import { diagnoseIncident, __resetSemaphoresForTest } from '../diagnose';

const fetchMock = jest.fn();
(global as any).fetch = fetchMock;

const incidentMock = { update: jest.fn() };
const prismaMock = {
  incident: {
    findUnique: jest.fn(),
    update: incidentMock.update,
  },
} as any;

beforeEach(() => {
  fetchMock.mockReset();
  incidentMock.update.mockReset();
  prismaMock.incident.findUnique.mockReset();
  __resetSemaphoresForTest();
});

describe('diagnoseIncident', () => {
  it('writes hypothesis/signature/owner back; resets consecutiveCount on signature change', async () => {
    prismaMock.incident.findUnique.mockResolvedValue({
      id: 'inc_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      monitorId: 'mon_1',
      openingRunId: 'run_1',
      signature: 'previous-sig',
      consecutiveCount: 2,
      monitor: { monitorType: 'FRESHNESS' },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        hypothesis: 'Upstream sync stalled.',
        signature: 'fivetran-source-stalled',
        ownerSystem: 'ingestion',
        ownerConfidence: 0.85,
      }),
    });

    await diagnoseIncident('inc_1', prismaMock);

    expect(incidentMock.update).toHaveBeenCalledTimes(1);
    const data = incidentMock.update.mock.calls[0][0].data;
    expect(data.signature).toBe('fivetran-source-stalled');
    expect(data.llmHypothesis).toBe('Upstream sync stalled.');
    expect(data.ownerSystem).toBe('ingestion');
    expect(data.ownerConfidence).toBe(0.85);
    expect(data.consecutiveCount).toBe(1); // signature changed → reset
  });

  it('increments consecutiveCount when signature is unchanged', async () => {
    prismaMock.incident.findUnique.mockResolvedValue({
      id: 'inc_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      monitorId: 'mon_1',
      openingRunId: 'run_1',
      signature: 'fivetran-source-stalled',
      consecutiveCount: 2,
      monitor: { monitorType: 'FRESHNESS' },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        hypothesis: 'Same as before.',
        signature: 'fivetran-source-stalled',
        ownerSystem: 'ingestion',
        ownerConfidence: 0.9,
      }),
    });

    await diagnoseIncident('inc_1', prismaMock);

    const data = incidentMock.update.mock.calls[0][0].data;
    expect(data.consecutiveCount).toBe(3);
  });

  it('falls back to deterministic signature on scanner error', async () => {
    prismaMock.incident.findUnique.mockResolvedValue({
      id: 'inc_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      monitorId: 'mon_1',
      openingRunId: 'run_1',
      signature: null,
      consecutiveCount: 1,
      monitor: { monitorType: 'FRESHNESS' },
    });
    fetchMock.mockRejectedValue(new Error('connection refused'));

    await diagnoseIncident('inc_1', prismaMock);

    const data = incidentMock.update.mock.calls[0][0].data;
    expect(data.signature).toMatch(/^freshness-/);
    expect(data.llmHypothesis).toContain('Unable to generate'); // deterministic fallback string
  });
});
```

- [ ] **Step 2: Run the test, confirm failure**

Run: `npx jest lib/incidents/__tests__/diagnose.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `lib/incidents/diagnose.ts`:

```ts
import type { PrismaClient } from '@prisma/client';
import { fallbackSignature } from './signature';

const SCANNER_URL = process.env.SCANNER_URL ?? 'http://localhost:8000';
const DEFAULT_CONCURRENCY = Number(process.env.INCIDENT_DIAGNOSE_CONCURRENCY ?? 3);

const semaphores = new Map<string, { count: number; queue: Array<() => void> }>();

function acquire(stackId: string): Promise<() => void> {
  let s = semaphores.get(stackId);
  if (!s) {
    s = { count: 0, queue: [] };
    semaphores.set(stackId, s);
  }
  return new Promise((resolve) => {
    const tryAcquire = () => {
      if (s!.count < DEFAULT_CONCURRENCY) {
        s!.count += 1;
        resolve(() => release(stackId));
      } else {
        s!.queue.push(tryAcquire);
      }
    };
    tryAcquire();
  });
}

function release(stackId: string) {
  const s = semaphores.get(stackId);
  if (!s) return;
  s.count -= 1;
  const next = s.queue.shift();
  if (next) next();
}

/** For tests only — reset semaphore state between cases. */
export function __resetSemaphoresForTest() {
  semaphores.clear();
}

export async function diagnoseIncident(incidentId: string, prisma: PrismaClient): Promise<void> {
  const incident = await prisma.incident.findUnique({
    where: { id: incidentId },
    include: { monitor: { select: { monitorType: true } } },
  } as any) as any;
  if (!incident) return;

  const release = await acquire(incident.pipelineStackId);
  try {
    let hypothesis: string;
    let signature: string;
    let ownerSystem = 'unknown';
    let ownerConfidence = 0;

    try {
      const res = await fetch(`${SCANNER_URL}/api/v1/copilot/incident-diagnose`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stackId: incident.pipelineStackId,
          monitorRunId: incident.openingRunId,
          targetFqn: incident.targetFqn,
          monitorType: incident.monitor?.monitorType ?? 'UNKNOWN',
          runDetails: {},
        }),
      });
      if (!res.ok) throw new Error(`scanner returned ${res.status}`);
      const body = await res.json();
      hypothesis = body.hypothesis;
      signature = body.signature;
      ownerSystem = body.ownerSystem;
      ownerConfidence = body.ownerConfidence;
    } catch {
      // Deterministic fallback
      signature = fallbackSignature({
        monitorType: incident.monitor?.monitorType ?? 'UNKNOWN',
        breachClass: 'unknown',
      });
      hypothesis = 'Unable to generate hypothesis — analysis is offline. Click "Open in Co-pilot" to investigate manually.';
    }

    const signatureChanged = incident.signature !== null && incident.signature !== signature;
    const newCount = signatureChanged ? 1 : (incident.consecutiveCount ?? 0) + 1;

    await prisma.incident.update({
      where: { id: incidentId },
      data: {
        signature,
        llmHypothesis: hypothesis,
        llmHypothesisAt: new Date(),
        ownerSystem,
        ownerConfidence,
        consecutiveCount: newCount,
      },
    });
  } finally {
    release();
  }
}
```

- [ ] **Step 4: Run the test, confirm pass**

Run: `npx jest lib/incidents/__tests__/diagnose.test.ts`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/incidents/diagnose.ts lib/incidents/__tests__/diagnose.test.ts
git commit -m "feat(incidents): diagnose.ts orchestrates scanner call with semaphore + signature dedup"
```

---

### Task 8: Wire lifecycle into the run route

**Files:**
- Modify: `app/api/schedule/tasks/[taskId]/run/route.ts`

- [ ] **Step 1: Locate the `monitorRun.create` block**

Open `app/api/schedule/tasks/[taskId]/run/route.ts`. There are two places that create `MonitorRun` rows: one for the success path, one for the error path. Find both (search for `prisma.monitorRun.create`).

- [ ] **Step 2: Add imports at the top of the file**

Add these imports at the top, alongside existing imports:

```ts
import { handleRun } from '@/lib/incidents/lifecycle';
import { diagnoseIncident } from '@/lib/incidents/diagnose';
```

- [ ] **Step 3: After each `monitorRun.create` call, invoke the lifecycle**

Immediately after each `const run = await prisma.monitorRun.create({...})` (or the `await prisma.monitorRun.create({...})` call in the error path), add:

```ts
try {
  const lc = await handleRun(run as any, prisma);
  if (lc.shouldDiagnose && lc.incidentId) {
    // Fire-and-forget — never blocks the run response
    void diagnoseIncident(lc.incidentId, prisma).catch((err) => {
      console.error('[incidents] diagnose failed', err);
    });
  }
} catch (err) {
  console.error('[incidents] lifecycle.handleRun failed', err);
}
```

For the error path (where `run` is created without being assigned to a const), capture it: change `await prisma.monitorRun.create({...})` to `const errRun = await prisma.monitorRun.create({...})`, then call `handleRun(errRun as any, prisma)` the same way.

- [ ] **Step 4: Type-check the file**

Run: `npm run type-check`
Expected: no errors related to `incidents`.

- [ ] **Step 5: Commit**

```bash
git add app/api/schedule/tasks/[taskId]/run/route.ts
git commit -m "feat(incidents): wire lifecycle.handleRun into monitor run pipeline"
```

---

### Task 9: `GET /api/incidents` list endpoint

**Files:**
- Create: `app/api/incidents/route.ts`

- [ ] **Step 1: Implement the route**

Create `app/api/incidents/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const url = new URL(request.url);
  const stackId = url.searchParams.get('stackId');
  const status = url.searchParams.get('status'); // 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'active' (open+ack)
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  const where: any = { organizationId, pipelineStackId: stackId };
  if (status === 'active') where.status = { in: ['OPEN', 'ACKNOWLEDGED'] };
  else if (status) where.status = status;

  const incidents = await prisma.incident.findMany({
    where,
    orderBy: [{ status: 'asc' }, { openedAt: 'desc' }],
    include: {
      monitor: {
        select: { id: true, name: true, monitorType: true, targetFqn: true, lastStatus: true },
      },
    },
  });

  const now = Date.now();
  const result = incidents.map((i) => ({
    id: i.id,
    monitorId: i.monitorId,
    monitorGroupId: i.monitorGroupId,
    monitorType: i.monitor?.monitorType ?? null,
    targetFqn: i.targetFqn,
    status: i.status,
    severity: i.severity,
    openedAt: i.openedAt.toISOString(),
    signature: i.signature,
    consecutiveCount: i.consecutiveCount,
    llmHypothesis: i.llmHypothesis,
    llmHypothesisAt: i.llmHypothesisAt?.toISOString() ?? null,
    ownerSystem: i.ownerSystem,
    ownerConfidence: i.ownerConfidence,
    acknowledgedAt: i.acknowledgedAt?.toISOString() ?? null,
    acknowledgedBy: i.acknowledgedBy,
    resolvedAt: i.resolvedAt?.toISOString() ?? null,
    resolvedBy: i.resolvedBy,
    resolutionType: i.resolutionType,
    resolutionNote: i.resolutionNote,
    mutedUntil: i.mutedUntil?.toISOString() ?? null,
    isMuted: !!(i.mutedUntil && i.mutedUntil.getTime() > now),
    mutedReason: i.mutedReason,
  }));

  return NextResponse.json({ incidents: result });
}
```

- [ ] **Step 2: Smoke test by hand**

Start the dev server (`npm run dev`) and hit `http://localhost:3000/api/incidents?stackId=<your-stack-id>`. Expected: `{"incidents": []}` (no incidents yet) once you have a session cookie. If you get 401, sign in first.

- [ ] **Step 3: Commit**

```bash
git add app/api/incidents/route.ts
git commit -m "feat(incidents): GET /api/incidents list endpoint"
```

---

### Task 10: Action endpoints — acknowledge

**Files:**
- Create: `app/api/incidents/[id]/acknowledge/route.ts`

- [ ] **Step 1: Implement**

Create `app/api/incidents/[id]/acknowledge/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (incident.status !== 'OPEN') return NextResponse.json({ error: 'Only OPEN incidents can be acknowledged' }, { status: 400 });

  const updated = await prisma.incident.update({
    where: { id },
    data: {
      status: 'ACKNOWLEDGED',
      acknowledgedAt: new Date(),
      acknowledgedBy: (session.user as any).id ?? session.user.email,
    },
  });
  return NextResponse.json({ incident: updated });
}
```

- [ ] **Step 2: Type-check**

Run: `npm run type-check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/api/incidents/[id]/acknowledge/route.ts
git commit -m "feat(incidents): POST /api/incidents/[id]/acknowledge"
```

---

### Task 11: Action endpoints — resolve

**Files:**
- Create: `app/api/incidents/[id]/resolve/route.ts`

- [ ] **Step 1: Implement**

Create `app/api/incidents/[id]/resolve/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const VALID = ['FIXED', 'EXPECTED', 'FALSE_POSITIVE', 'WONT_FIX'] as const;

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const { reason, note } = body as { reason?: string; note?: string };

  if (!reason || !VALID.includes(reason as any)) {
    return NextResponse.json({ error: `reason must be one of ${VALID.join(', ')}` }, { status: 400 });
  }

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (incident.status === 'RESOLVED') return NextResponse.json({ incident }, { status: 200 });

  const updated = await prisma.incident.update({
    where: { id },
    data: {
      status: 'RESOLVED',
      resolvedAt: new Date(),
      resolvedBy: (session.user as any).id ?? session.user.email,
      resolutionType: reason as any,
      resolutionNote: note ?? null,
    },
  });
  return NextResponse.json({ incident: updated });
}
```

- [ ] **Step 2: Type-check**

Run: `npm run type-check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/api/incidents/[id]/resolve/route.ts
git commit -m "feat(incidents): POST /api/incidents/[id]/resolve with reason validation"
```

---

### Task 12: Action endpoints — mute / unmute

**Files:**
- Create: `app/api/incidents/[id]/mute/route.ts`
- Create: `app/api/incidents/[id]/unmute/route.ts`

- [ ] **Step 1: Implement mute**

Create `app/api/incidents/[id]/mute/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const { until, reason } = body as { until?: string; reason?: string };

  if (!until) return NextResponse.json({ error: 'until (ISO8601) required' }, { status: 400 });
  const untilDate = new Date(until);
  if (isNaN(untilDate.getTime()) || untilDate.getTime() <= Date.now()) {
    return NextResponse.json({ error: 'until must be a future ISO8601 timestamp' }, { status: 400 });
  }

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (incident.status === 'RESOLVED') return NextResponse.json({ error: 'Cannot mute a resolved incident' }, { status: 400 });

  const updated = await prisma.incident.update({
    where: { id },
    data: {
      mutedUntil: untilDate,
      mutedBy: (session.user as any).id ?? session.user.email,
      mutedReason: reason ?? null,
    },
  });
  return NextResponse.json({ incident: updated });
}
```

- [ ] **Step 2: Implement unmute**

Create `app/api/incidents/[id]/unmute/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const updated = await prisma.incident.update({
    where: { id },
    data: { mutedUntil: null, mutedBy: null, mutedReason: null },
  });
  return NextResponse.json({ incident: updated });
}
```

- [ ] **Step 3: Type-check**

Run: `npm run type-check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add app/api/incidents/[id]/mute/route.ts app/api/incidents/[id]/unmute/route.ts
git commit -m "feat(incidents): POST mute/unmute endpoints"
```

---

### Task 13: Action endpoint — reanalyze

**Files:**
- Create: `app/api/incidents/[id]/reanalyze/route.ts`

- [ ] **Step 1: Implement**

Create `app/api/incidents/[id]/reanalyze/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { diagnoseIncident } from '@/lib/incidents/diagnose';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;

  const incident = await prisma.incident.findUnique({ where: { id } });
  if (!incident) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  await diagnoseIncident(id, prisma);
  const refreshed = await prisma.incident.findUnique({ where: { id } });
  return NextResponse.json({ incident: refreshed });
}
```

- [ ] **Step 2: Type-check**

Run: `npm run type-check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/api/incidents/[id]/reanalyze/route.ts
git commit -m "feat(incidents): POST /api/incidents/[id]/reanalyze"
```

---

### Task 14: `GET /api/incidents/stats` for the trend strip

**Files:**
- Create: `app/api/incidents/stats/route.ts`

- [ ] **Step 1: Implement**

Create `app/api/incidents/stats/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const DAY_MS = 24 * 60 * 60 * 1000;

function dayBuckets(start: Date, end: Date): Date[] {
  const out: Date[] = [];
  const d0 = new Date(start);
  d0.setUTCHours(0, 0, 0, 0);
  while (d0.getTime() <= end.getTime()) {
    out.push(new Date(d0));
    d0.setUTCDate(d0.getUTCDate() + 1);
  }
  return out;
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const url = new URL(request.url);
  const stackId = url.searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });
  const windowDays = Number(url.searchParams.get('window')?.replace('d', '') ?? 7);

  const now = new Date();
  const windowStart = new Date(now.getTime() - windowDays * DAY_MS);
  const priorStart = new Date(windowStart.getTime() - windowDays * DAY_MS);

  // Pass rate uses MonitorRun rows joined to Monitor → MonitorGroup → pipelineStackId
  // For simplicity (and to keep SQL-via-Prisma ergonomic) we fetch monitors first.
  const monitorIds = (await prisma.monitor.findMany({
    where: { organizationId, monitorGroup: { pipelineStackId: stackId } },
    select: { id: true },
  })).map((m) => m.id);

  async function passRate(from: Date, to: Date) {
    if (monitorIds.length === 0) return null;
    const total = await prisma.monitorRun.count({
      where: { monitorId: { in: monitorIds }, startedAt: { gte: from, lt: to } },
    });
    if (total === 0) return null;
    const passing = await prisma.monitorRun.count({
      where: { monitorId: { in: monitorIds }, startedAt: { gte: from, lt: to }, status: 'PASS' },
    });
    return passing / total;
  }

  const [openedNow, openedPrior, resolvedNow, resolvedPrior, currentPass, priorPass] = await Promise.all([
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, openedAt: { gte: windowStart, lt: now } } }),
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, openedAt: { gte: priorStart, lt: windowStart } } }),
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: windowStart, lt: now } } }),
    prisma.incident.count({ where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: priorStart, lt: windowStart } } }),
    passRate(windowStart, now),
    passRate(priorStart, windowStart),
  ]);

  // MTTR: avg(resolvedAt - openedAt) over incidents resolved in window
  const resolvedIncidents = await prisma.incident.findMany({
    where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: windowStart, lt: now } },
    select: { openedAt: true, resolvedAt: true },
  });
  const mttrMs = resolvedIncidents.length === 0
    ? null
    : resolvedIncidents.reduce((s, i) => s + (i.resolvedAt!.getTime() - i.openedAt.getTime()), 0) / resolvedIncidents.length;

  const priorResolved = await prisma.incident.findMany({
    where: { organizationId, pipelineStackId: stackId, resolvedAt: { gte: priorStart, lt: windowStart } },
    select: { openedAt: true, resolvedAt: true },
  });
  const priorMttrMs = priorResolved.length === 0
    ? null
    : priorResolved.reduce((s, i) => s + (i.resolvedAt!.getTime() - i.openedAt.getTime()), 0) / priorResolved.length;

  // Daily sparkline: 1 bucket per day, count of incidents opened
  const buckets = dayBuckets(windowStart, now);
  const opened = await prisma.incident.findMany({
    where: { organizationId, pipelineStackId: stackId, openedAt: { gte: windowStart, lt: now } },
    select: { openedAt: true },
  });
  const openedByDay = buckets.map((day, i) => {
    const next = buckets[i + 1] ?? now;
    return opened.filter((o) => o.openedAt >= day && o.openedAt < next).length;
  });

  return NextResponse.json({
    windowDays,
    passRate: { current: currentPass, prior: priorPass },
    mttrMs:    { current: mttrMs,     prior: priorMttrMs },
    opened:    { current: openedNow,  prior: openedPrior, sparkline: openedByDay },
    recovered: { current: resolvedNow, prior: resolvedPrior, ratio: openedNow === 0 ? null : resolvedNow / openedNow },
  });
}
```

- [ ] **Step 2: Smoke test**

Hit `http://localhost:3000/api/incidents/stats?stackId=<id>` while signed in. Expected: a JSON shape matching the structure above with mostly `null` values until you have data.

- [ ] **Step 3: Commit**

```bash
git add app/api/incidents/stats/route.ts
git commit -m "feat(incidents): GET /api/incidents/stats with pass-rate, MTTR, opened, recovered"
```

---

### Task 15: Frontend types

**Files:**
- Create: `types/incident.ts`

- [ ] **Step 1: Create**

Create `types/incident.ts`:

```ts
export type IncidentStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';
export type IncidentSeverity = 'FAIL' | 'WARN';

export type IncidentResolutionType =
  | 'AUTO_RECOVERED'
  | 'FIXED'
  | 'EXPECTED'
  | 'FALSE_POSITIVE'
  | 'WONT_FIX';

export interface IncidentSummary {
  id: string;
  monitorId: string;
  monitorGroupId: string | null;
  monitorType: string | null;
  targetFqn: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  openedAt: string;
  signature: string | null;
  consecutiveCount: number;
  llmHypothesis: string | null;
  llmHypothesisAt: string | null;
  ownerSystem: string | null;
  ownerConfidence: number | null;
  acknowledgedAt: string | null;
  acknowledgedBy: string | null;
  resolvedAt: string | null;
  resolvedBy: string | null;
  resolutionType: IncidentResolutionType | null;
  resolutionNote: string | null;
  mutedUntil: string | null;
  isMuted: boolean;
  mutedReason: string | null;
}

export interface IncidentStats {
  windowDays: number;
  passRate:  { current: number | null; prior: number | null };
  mttrMs:    { current: number | null; prior: number | null };
  opened:    { current: number; prior: number; sparkline: number[] };
  recovered: { current: number; prior: number; ratio: number | null };
}
```

- [ ] **Step 2: Commit**

```bash
git add types/incident.ts
git commit -m "feat(types): IncidentSummary and IncidentStats"
```

---

### Task 16: `SummaryHero` component

**Files:**
- Create: `components/monitors/SummaryHero.tsx`

- [ ] **Step 1: Implement**

Create `components/monitors/SummaryHero.tsx`:

```tsx
'use client';

import { cn } from '@/lib/utils';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  incidents: IncidentSummary[];   // active incidents (open + ack), already filtered
  monitoredAssetCount: number;
  blastRadius?: { dashboards: number; tables: number };
  updatedAt?: string;
}

function timeSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d`;
}

export function SummaryHero({ incidents, monitoredAssetCount, blastRadius, updatedAt }: Props) {
  // Hero counts use status='OPEN' AND not muted
  const open = incidents.filter((i) => i.status === 'OPEN' && !i.isMuted);
  const fail = open.filter((i) => i.severity === 'FAIL');
  const warn = open.filter((i) => i.severity === 'WARN');

  let tone: 'green' | 'amber' | 'red' = 'green';
  if (open.length === 0) tone = 'green';
  else if (fail.length > 0) tone = 'red';
  else tone = 'amber';

  const oldestMs = open.length > 0
    ? Math.max(...open.map((i) => Date.now() - new Date(i.openedAt).getTime()))
    : null;

  const styles = {
    green: 'from-emerald-500/12 to-emerald-500/[0.02] border-emerald-500/30 text-emerald-400',
    amber: 'from-amber-500/12  to-amber-500/[0.02]  border-amber-500/30  text-amber-400',
    red:   'from-red-500/12    to-red-500/[0.02]    border-red-500/30    text-red-400',
  } as const;

  const dotColor = { green: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-red-500' }[tone];

  const headline =
    tone === 'green'
      ? `All systems healthy. ${monitoredAssetCount} asset${monitoredAssetCount === 1 ? '' : 's'} monitored.`
      : tone === 'amber'
        ? `${warn.length} warning${warn.length === 1 ? '' : 's'}.${blastRadius ? ` Affecting ${blastRadius.dashboards} dashboards.` : ''}`
        : `${fail.length} critical incident${fail.length === 1 ? '' : 's'}${warn.length > 0 ? ` · ${warn.length} warning` : ''}.${blastRadius ? ` Affecting ${blastRadius.dashboards} BI dashboards and ${blastRadius.tables} downstream tables.` : ''}${oldestMs ? ` Oldest ${formatMs(oldestMs)}.` : ''}`;

  return (
    <div className={cn('rounded-lg border bg-gradient-to-r px-5 py-4 mb-4', styles[tone])}>
      <div className="flex items-center gap-3">
        <div className={cn('w-2.5 h-2.5 rounded-full shadow', dotColor)} />
        <div className="flex-1">
          <div className="text-[14px] font-semibold">{headline}</div>
        </div>
        {updatedAt && (
          <div className="text-[10px] opacity-60">Updated {new Date(updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
        )}
      </div>
    </div>
  );
}

function formatMs(ms: number): string {
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
```

- [ ] **Step 2: Visual smoke check**

Run `npm run dev` and hard-refresh `/dashboard/monitors`. The hero won't render yet (`DriftSummaryTab` isn't rebuilt) — verify the file at least type-checks: `npm run type-check`.

- [ ] **Step 3: Commit**

```bash
git add components/monitors/SummaryHero.tsx
git commit -m "feat(monitors): SummaryHero status banner"
```

---

### Task 17: `IncidentCard` component

**Files:**
- Create: `components/monitors/IncidentCard.tsx`

- [ ] **Step 1: Implement**

Create `components/monitors/IncidentCard.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  incident: IncidentSummary;
  onChanged: () => void;        // parent refetches after action
  onOpenInCopilot: (incident: IncidentSummary) => void;
}

const MUTE_PRESETS: Array<{ label: string; ms: number }> = [
  { label: '1h', ms: 60 * 60 * 1000 },
  { label: '4h', ms: 4 * 60 * 60 * 1000 },
  { label: '1d', ms: 24 * 60 * 60 * 1000 },
  { label: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
];

export function IncidentCard({ incident, onChanged, onOpenInCopilot }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showMuteMenu, setShowMuteMenu] = useState(false);

  const tone = incident.status === 'ACKNOWLEDGED'
    ? 'border-zinc-600/40 bg-zinc-500/[0.03] opacity-75'
    : incident.isMuted
      ? 'border-purple-500/30 bg-purple-500/[0.03] opacity-75'
      : 'border-red-400/40 bg-red-400/[0.04]';

  const dot = incident.status === 'ACKNOWLEDGED'
    ? 'bg-zinc-400'
    : incident.isMuted
      ? 'bg-purple-400'
      : 'bg-red-500';

  const since = (() => {
    const ms = Date.now() - new Date(incident.openedAt).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h`;
    return `${Math.floor(h / 24)}d`;
  })();

  async function callAction(path: string, body?: any) {
    setBusy(true);
    try {
      const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Action failed');
      } else {
        onChanged();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn('rounded-xl border px-4 py-3 mb-2', tone)}>
      <div className="flex items-center gap-2.5">
        <span className={cn('w-2 h-2 rounded-full flex-shrink-0', dot)} />
        <span className="font-semibold text-[13px] text-[var(--text)]">{incident.targetFqn}</span>
        <span className="text-[11px] text-[var(--muted)]">{(incident.monitorType ?? 'unknown').toLowerCase()} · {since}</span>
        {incident.isMuted && incident.mutedUntil && (
          <span className="text-[10px] text-purple-300 ml-1">muted until {new Date(incident.mutedUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        )}
      </div>

      <div className="mt-2 text-[12px] leading-snug">
        <div className="text-[9px] uppercase tracking-wider text-[var(--muted)]">Likely cause</div>
        {incident.llmHypothesis ? (
          <div className="text-[var(--text)]/90 mt-0.5">{incident.llmHypothesis}</div>
        ) : (
          <div className="text-[var(--muted)] mt-0.5 flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 animate-spin" /> Analyzing…
          </div>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
        <button
          disabled={busy}
          onClick={() => onOpenInCopilot(incident)}
          className="px-2.5 py-1 text-[11px] font-medium rounded bg-[var(--accent)] text-white hover:opacity-90"
        >
          Open in Co-pilot →
        </button>
        {incident.status === 'OPEN' && (
          <button disabled={busy} onClick={() => callAction(`/api/incidents/${incident.id}/acknowledge`)} className="px-2.5 py-1 text-[11px] rounded border border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]">
            Acknowledge
          </button>
        )}
        {(incident.status === 'OPEN' || incident.status === 'ACKNOWLEDGED') && (
          <ResolveMenu disabled={busy} onPick={(reason) => callAction(`/api/incidents/${incident.id}/resolve`, { reason })} />
        )}
        {incident.isMuted ? (
          <button disabled={busy} onClick={() => callAction(`/api/incidents/${incident.id}/unmute`)} className="px-2.5 py-1 text-[11px] rounded border border-purple-500/40 text-purple-300">
            Unmute
          </button>
        ) : (
          <div className="relative">
            <button disabled={busy} onClick={() => setShowMuteMenu((v) => !v)} className="px-2.5 py-1 text-[11px] rounded border border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]">
              Mute ▾
            </button>
            {showMuteMenu && (
              <div className="absolute z-10 mt-1 bg-[var(--surface)] border border-[var(--subtle-border)] rounded shadow-md p-1 min-w-[100px]">
                {MUTE_PRESETS.map((p) => (
                  <button key={p.label} className="block w-full text-left px-2 py-1 text-[11px] hover:bg-[var(--hover-bg)]"
                    onClick={() => { setShowMuteMenu(false); callAction(`/api/incidents/${incident.id}/mute`, { until: new Date(Date.now() + p.ms).toISOString() }); }}>
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <button onClick={() => setExpanded((v) => !v)} className="ml-auto text-[10px] text-[var(--muted)] flex items-center gap-1">
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          {expanded ? 'Hide' : 'Show'} evidence
        </button>
      </div>

      {expanded && (
        <div className="mt-2 pt-2 border-t border-[var(--subtle-border)] text-[11px] text-[var(--muted)] space-y-1.5">
          <div>Signature: <code>{incident.signature ?? '—'}</code> · count: {incident.consecutiveCount}</div>
          <div>Owner system: {incident.ownerSystem ?? '—'} ({incident.ownerConfidence != null ? `${Math.round(incident.ownerConfidence * 100)}% confidence` : 'n/a'})</div>
          <div>Opened {new Date(incident.openedAt).toLocaleString()}</div>
          <button
            disabled={busy}
            onClick={() => callAction(`/api/incidents/${incident.id}/reanalyze`)}
            className="text-[var(--accent)] hover:underline disabled:opacity-50"
          >
            {busy ? 'Re-analyzing…' : 'Re-analyze'}
          </button>
        </div>
      )}
    </div>
  );
}

function ResolveMenu({ disabled, onPick }: { disabled: boolean; onPick: (reason: string) => void }) {
  const [open, setOpen] = useState(false);
  const reasons = [
    { value: 'FIXED', label: 'Fixed' },
    { value: 'EXPECTED', label: 'Expected' },
    { value: 'FALSE_POSITIVE', label: 'False positive' },
    { value: 'WONT_FIX', label: "Won't fix" },
  ];
  return (
    <div className="relative">
      <button disabled={disabled} onClick={() => setOpen((v) => !v)} className="px-2.5 py-1 text-[11px] rounded border border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]">
        Resolve ▾
      </button>
      {open && (
        <div className="absolute z-10 mt-1 bg-[var(--surface)] border border-[var(--subtle-border)] rounded shadow-md p-1 min-w-[140px]">
          {reasons.map((r) => (
            <button key={r.value} className="block w-full text-left px-2 py-1 text-[11px] hover:bg-[var(--hover-bg)]"
              onClick={() => { setOpen(false); onPick(r.value); }}>
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npm run type-check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/monitors/IncidentCard.tsx
git commit -m "feat(monitors): IncidentCard with collapsible evidence and mute/resolve menus"
```

---

### Task 18: `ActiveIncidents` container — list, sort, polling

**Files:**
- Create: `components/monitors/ActiveIncidents.tsx`

- [ ] **Step 1: Implement**

Create `components/monitors/ActiveIncidents.tsx`:

```tsx
'use client';

import { useEffect, useState, useCallback } from 'react';
import { IncidentCard } from './IncidentCard';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  stackId: string;
  onOpenInCopilot: (i: IncidentSummary) => void;
}

export function ActiveIncidents({ stackId, onOpenInCopilot }: Props) {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [showMuted, setShowMuted] = useState(false);

  const fetchIncidents = useCallback(async () => {
    const res = await fetch(`/api/incidents?stackId=${stackId}&status=active`);
    if (res.ok) {
      const data = await res.json();
      setIncidents(data.incidents || []);
    }
  }, [stackId]);

  useEffect(() => { fetchIncidents(); }, [fetchIncidents]);
  useEffect(() => {
    const t = setInterval(fetchIncidents, 15000);
    return () => clearInterval(t);
  }, [fetchIncidents]);

  // Sort: status (OPEN before ACK), then opened age desc
  const visible = incidents.filter((i) => !i.isMuted);
  const muted = incidents.filter((i) => i.isMuted);

  visible.sort((a, b) => {
    if (a.status !== b.status) return a.status === 'OPEN' ? -1 : 1;
    return new Date(a.openedAt).getTime() - new Date(b.openedAt).getTime();
  });

  if (incidents.length === 0) return null;

  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Active incidents
      </div>
      {visible.map((i) => (
        <IncidentCard key={i.id} incident={i} onChanged={fetchIncidents} onOpenInCopilot={onOpenInCopilot} />
      ))}
      {muted.length > 0 && (
        <div className="mt-2">
          <button onClick={() => setShowMuted((v) => !v)} className="text-[11px] text-[var(--muted)] hover:text-[var(--text)]">
            {showMuted ? '−' : '+'} {muted.length} muted incident{muted.length === 1 ? '' : 's'}
          </button>
          {showMuted && (
            <div className="mt-2">
              {muted.map((i) => (
                <IncidentCard key={i.id} incident={i} onChanged={fetchIncidents} onOpenInCopilot={onOpenInCopilot} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check and commit**

Run: `npm run type-check`
Expected: no errors.

```bash
git add components/monitors/ActiveIncidents.tsx
git commit -m "feat(monitors): ActiveIncidents container with sort and 15s polling"
```

---

### Task 19: `TrendStrip` component

**Files:**
- Create: `components/monitors/TrendStrip.tsx`

- [ ] **Step 1: Implement**

Create `components/monitors/TrendStrip.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import type { IncidentStats } from '@/types/incident';

interface Props { stackId: string; }

function formatMs(ms: number | null): string {
  if (ms == null) return '—';
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function delta(current: number | null, prior: number | null): { sign: '+' | '-' | ''; magnitude: number } {
  if (current == null || prior == null) return { sign: '', magnitude: 0 };
  const d = current - prior;
  return { sign: d > 0 ? '+' : d < 0 ? '-' : '', magnitude: Math.abs(d) };
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length === 0) return null;
  const max = Math.max(...data, 1);
  const points = data.map((v, i) => `${(i / (data.length - 1 || 1)) * 100},${20 - (v / max) * 16}`).join(' ');
  return (
    <svg width="100%" height="20" viewBox="0 0 100 20" className="mt-1">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

export function TrendStrip({ stackId }: Props) {
  const [stats, setStats] = useState<IncidentStats | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`/api/incidents/stats?stackId=${stackId}&window=7d`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (active) setStats(d); })
      .catch(() => {});
    const t = setInterval(() => {
      fetch(`/api/incidents/stats?stackId=${stackId}&window=7d`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (active) setStats(d); })
        .catch(() => {});
    }, 60000);
    return () => { active = false; clearInterval(t); };
  }, [stackId]);

  if (!stats) return null;

  const passDelta = stats.passRate.current != null && stats.passRate.prior != null
    ? (stats.passRate.current - stats.passRate.prior) * 100
    : null;
  const mttrDelta = delta(stats.mttrMs.current, stats.mttrMs.prior);
  const incidentDelta = stats.opened.current - stats.opened.prior;

  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">7-day trend</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Pass rate"
              value={stats.passRate.current != null ? `${(stats.passRate.current * 100).toFixed(1)}%` : '—'}
              delta={passDelta != null ? `${passDelta >= 0 ? '▲' : '▼'} ${Math.abs(passDelta).toFixed(1)}` : ''}
              tone={passDelta == null ? 'neutral' : passDelta >= 0 ? 'good' : 'bad'} />
        <Tile label="MTTR"
              value={formatMs(stats.mttrMs.current)}
              delta={mttrDelta.sign ? `${mttrDelta.sign === '+' ? '▲' : '▼'} ${formatMs(mttrDelta.magnitude)}` : ''}
              tone={mttrDelta.sign === '-' ? 'good' : mttrDelta.sign === '+' ? 'bad' : 'neutral'} />
        <Tile label="Incidents"
              value={String(stats.opened.current)}
              delta={incidentDelta !== 0 ? `${incidentDelta > 0 ? '▲' : '▼'} ${Math.abs(incidentDelta)}` : ''}
              tone={incidentDelta < 0 ? 'good' : incidentDelta > 0 ? 'bad' : 'neutral'}>
          <Sparkline data={stats.opened.sparkline} color="#a1a1aa" />
        </Tile>
        <Tile label="Recovered"
              value={`${stats.recovered.current} / ${stats.opened.current}`}
              delta={stats.recovered.ratio != null ? `${Math.round(stats.recovered.ratio * 100)}%` : ''}
              tone="good" />
      </div>
    </div>
  );
}

function Tile({ label, value, delta, tone, children }: { label: string; value: string; delta: string; tone: 'good' | 'bad' | 'neutral'; children?: React.ReactNode }) {
  const deltaClr = tone === 'good' ? 'text-emerald-400' : tone === 'bad' ? 'text-red-400' : 'text-[var(--muted)]';
  return (
    <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] px-3 py-2.5">
      <div className="text-[9px] uppercase tracking-wider text-[var(--muted)]">{label}</div>
      <div className="text-[18px] font-bold tabular-nums text-[var(--text)] mt-0.5">
        {value}
        {delta && <span className={cn('text-[10px] font-medium ml-1.5', deltaClr)}>{delta}</span>}
      </div>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Type-check and commit**

Run: `npm run type-check`
Expected: no errors.

```bash
git add components/monitors/TrendStrip.tsx
git commit -m "feat(monitors): TrendStrip with pass rate / MTTR / opened / recovered tiles"
```

---

### Task 20: `AssetHealthLean` and `CoverageGaps`

**Files:**
- Create: `components/monitors/AssetHealthLean.tsx`
- Create: `components/monitors/CoverageGaps.tsx`

- [ ] **Step 1: Implement AssetHealthLean**

Create `components/monitors/AssetHealthLean.tsx`. This wraps the existing `AssetHealthRow` component with the lean policy: only show non-healthy by default, collapse healthy under a count.

```tsx
'use client';

import { useState } from 'react';
import { AssetHealthRow } from './AssetHealthRow';

interface AssetTrend {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: any[];
}

interface Props {
  assets: AssetTrend[];
  expandedFqn: string | null;
  onToggle: (fqn: string) => void;
  activeCategories: Set<string>;
  onRunAnalysis: () => void;
}

export function AssetHealthLean({ assets, expandedFqn, onToggle, activeCategories, onRunAnalysis }: Props) {
  const [showHealthy, setShowHealthy] = useState(false);
  const unhealthy = assets.filter((a) => a.status !== 'stable' && a.status !== 'healthy');
  const healthy = assets.filter((a) => a.status === 'stable' || a.status === 'healthy');

  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Asset health <span className="text-[var(--text-faint)] normal-case tracking-normal">· {assets.length} monitored, {healthy.length} healthy</span>
      </div>
      <div className="space-y-2">
        {unhealthy.map((asset) => (
          <AssetHealthRow
            key={asset.fqn}
            asset={asset}
            expanded={expandedFqn === asset.fqn}
            onToggle={() => onToggle(asset.fqn)}
            activeCategories={activeCategories}
            onRunAnalysis={onRunAnalysis}
          />
        ))}
        {healthy.length > 0 && (
          <button
            onClick={() => setShowHealthy((v) => !v)}
            className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] block py-1"
          >
            {showHealthy ? '−' : '+'} {healthy.length} healthy asset{healthy.length === 1 ? '' : 's'}
          </button>
        )}
        {showHealthy && healthy.map((asset) => (
          <AssetHealthRow
            key={asset.fqn}
            asset={asset}
            expanded={expandedFqn === asset.fqn}
            onToggle={() => onToggle(asset.fqn)}
            activeCategories={activeCategories}
            onRunAnalysis={onRunAnalysis}
          />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement CoverageGaps**

Create `components/monitors/CoverageGaps.tsx`:

```tsx
'use client';

import { Button } from '@/components/ui/button';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  unmonitoredCriticalAssets: Array<{ fqn: string; reason: string }>;
  pendingRecommendations: DriftRecommendation[];
  onAddMonitor: (fqn: string) => void;
  onReviewRecs: () => void;
}

export function CoverageGaps({ unmonitoredCriticalAssets, pendingRecommendations, onAddMonitor, onReviewRecs }: Props) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Improve coverage
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] p-4">
          <div className="text-[12px] text-[var(--text)] font-semibold mb-1">
            {unmonitoredCriticalAssets.length} critical asset{unmonitoredCriticalAssets.length === 1 ? '' : 's'} unmonitored
          </div>
          {unmonitoredCriticalAssets.length === 0 ? (
            <p className="text-[11px] text-[var(--muted)] mb-3">All critical assets are monitored.</p>
          ) : (
            <ul className="text-[11px] text-[var(--muted)] mb-3 space-y-1">
              {unmonitoredCriticalAssets.slice(0, 3).map((a) => (
                <li key={a.fqn} className="flex items-center justify-between gap-2">
                  <code className="truncate">{a.fqn}</code>
                  <button onClick={() => onAddMonitor(a.fqn)} className="text-[var(--accent)] hover:underline shrink-0">+ Add</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] p-4">
          <div className="text-[12px] text-[var(--text)] font-semibold mb-1">
            {pendingRecommendations.length} SLA recommendation{pendingRecommendations.length === 1 ? '' : 's'}
          </div>
          <p className="text-[11px] text-[var(--muted)] mb-3">
            {pendingRecommendations.length === 0
              ? 'No drift detected in current baselines.'
              : 'Pallisade detected drift in baselines. Suggested threshold updates pending review.'}
          </p>
          <Button size="sm" variant="outline" onClick={onReviewRecs} disabled={pendingRecommendations.length === 0}>
            Review →
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Type-check and commit**

Run: `npm run type-check`
Expected: no errors.

```bash
git add components/monitors/AssetHealthLean.tsx components/monitors/CoverageGaps.tsx
git commit -m "feat(monitors): AssetHealthLean (collapse healthy) and CoverageGaps cards"
```

---

### Task 21: Replace `DriftSummaryTab`

**Files:**
- Modify: `components/monitors/DriftSummaryTab.tsx`
- Create: `components/monitors/PipelineHealthTiles.tsx`

- [ ] **Step 1: Extract Pipeline Health tiles to their own component**

Create `components/monitors/PipelineHealthTiles.tsx`. Copy the existing `pipelineTools` rendering block from the current `DriftSummaryTab.tsx` (the `grid grid-cols-3 md:grid-cols-6 gap-3` block plus the expanded sparkline panel). Export as `PipelineHealthTiles`.

```tsx
'use client';

import { useEffect, useState, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { CategorySparklinePanel } from './CategorySparklinePanel';
import { usePipeline } from '@/contexts/PipelineContext';

const STATUS_STYLES: Record<string, { border: string; text: string; accent: string; badgeBg: string }> = {
  stable:   { border: 'border-emerald-500/30', text: 'text-emerald-500', accent: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10' },
  healthy:  { border: 'border-emerald-500/30', text: 'text-emerald-500', accent: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10' },
  warning:  { border: 'border-amber-500/30',   text: 'text-amber-500',   accent: 'bg-amber-500',   badgeBg: 'bg-amber-500/10' },
  degraded: { border: 'border-amber-500/30',   text: 'text-amber-500',   accent: 'bg-amber-500',   badgeBg: 'bg-amber-500/10' },
  drifting: { border: 'border-red-500/30',     text: 'text-red-500',     accent: 'bg-red-500',     badgeBg: 'bg-red-500/10' },
  down:     { border: 'border-red-500/30',     text: 'text-red-500',     accent: 'bg-red-500',     badgeBg: 'bg-red-500/10' },
  pending:  { border: 'border-[var(--subtle-border)]', text: 'text-[var(--muted)]', accent: 'bg-zinc-400', badgeBg: 'bg-zinc-500/10' },
};
const STATUS_LABELS: Record<string, string> = { stable: 'Stable', healthy: 'Healthy', warning: 'Warning', degraded: 'Degraded', drifting: 'Drifting', down: 'Down', pending: 'Pending' };

export function PipelineHealthTiles() {
  const { selectedPipelineId } = usePipeline();
  const [trendData, setTrendData] = useState<any | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedPipelineId) return;
    let active = true;
    fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (active) setTrendData(d); })
      .catch(() => {});
    const t = setInterval(() => {
      fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (active) setTrendData(d); })
        .catch(() => {});
    }, 30000);
    return () => { active = false; clearInterval(t); };
  }, [selectedPipelineId]);

  const tools = useMemo(() => {
    if (!trendData?.pipelineHealth) return [];
    return Object.entries(trendData.pipelineHealth).map(([key, data]: any) => ({
      key, label: key.charAt(0).toUpperCase() + key.slice(1), ...data,
    }));
  }, [trendData]);

  if (tools.length === 0) return null;

  return (
    <div className="mb-4">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">Pipeline Health</div>
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {tools.map((tool) => {
          const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
          const isExpanded = expanded === `pipeline-${tool.key}`;
          const passPct = tool.total > 0 ? (tool.passing / tool.total) * 100 : 0;
          return (
            <button key={tool.key} onClick={() => setExpanded(isExpanded ? null : `pipeline-${tool.key}`)}
              className={cn('rounded-xl border overflow-hidden text-left transition-all hover:shadow-md',
                isExpanded ? `${style.border} bg-[var(--surface)] shadow-sm` : 'border-[var(--subtle-border)] bg-[var(--surface)]')}>
              <div className={cn('h-1', style.accent, isExpanded ? 'opacity-100' : 'opacity-40')} />
              <div className="px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wide">{tool.label}</span>
                  <span className={cn('text-[9px] font-medium px-1.5 py-0.5 rounded-full', style.badgeBg, style.text)}>
                    {STATUS_LABELS[tool.status] || tool.status}
                  </span>
                </div>
                <div className={cn('text-[22px] font-bold tabular-nums',
                  tool.failing > 0 ? 'text-red-500' : tool.warning > 0 ? 'text-amber-500' : 'text-emerald-500')}>
                  {tool.passing}<span className="text-[14px] font-normal text-[var(--muted)]">/{tool.total}</span>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--overlay-bg)] mt-2 overflow-hidden">
                  <div className={cn('h-full rounded-full transition-all', style.accent)} style={{ width: `${passPct}%` }} />
                </div>
              </div>
            </button>
          );
        })}
      </div>
      {tools.map((tool) => {
        if (expanded !== `pipeline-${tool.key}`) return null;
        const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
        return (
          <div key={tool.key} className="mt-2">
            <CategorySparklinePanel label={tool.label} failingCount={tool.failing} monitors={tool.monitors} borderColor={style.border} />
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Replace `DriftSummaryTab.tsx`**

Replace the entire contents of `components/monitors/DriftSummaryTab.tsx` with:

```tsx
'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Activity } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';
import { SummaryHero } from './SummaryHero';
import { ActiveIncidents } from './ActiveIncidents';
import { TrendStrip } from './TrendStrip';
import { AssetHealthLean } from './AssetHealthLean';
import { CoverageGaps } from './CoverageGaps';
import type { IncidentSummary } from '@/types/incident';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  watches: any[];
  tasks: any[];
  loading: boolean;
}

export function DriftSummaryTab({ watches, tasks, loading: _loading }: Props) {
  const { selectedPipelineId } = usePipeline();
  const router = useRouter();

  const [activeIncidents, setActiveIncidents] = useState<IncidentSummary[]>([]);
  const [trendData, setTrendData] = useState<any | null>(null);
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [unmonitoredCritical, setUnmonitoredCritical] = useState<Array<{ fqn: string; reason: string }>>([]);
  const [expandedAssetFqn, setExpandedAssetFqn] = useState<string | null>(null);
  const [activeCategories] = useState<Set<string>>(new Set());

  const fetchAll = useCallback(async () => {
    if (!selectedPipelineId) return;
    const [incRes, trRes, drRes, covRes] = await Promise.all([
      fetch(`/api/incidents?stackId=${selectedPipelineId}&status=active`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/drift?status=pending&stackId=${selectedPipelineId}`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/coverage/unmonitored-critical?stackId=${selectedPipelineId}`).then((r) => r.ok ? r.json() : null).catch(() => null),
    ]);
    setActiveIncidents(incRes?.incidents || []);
    setTrendData(trRes);
    setRecommendations(drRes?.recommendations || []);
    setUnmonitoredCritical(covRes?.assets || []);
  }, [selectedPipelineId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    const t = setInterval(fetchAll, 30000);
    return () => clearInterval(t);
  }, [fetchAll]);

  const handleOpenInCopilot = useCallback((incident: IncidentSummary) => {
    const params = new URLSearchParams({
      contextType: 'incident',
      incidentId: incident.id,
      monitorId: incident.monitorId,
      targetFqn: incident.targetFqn,
    });
    router.push(`/dashboard/copilot?${params.toString()}`);
  }, [router]);

  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    return Object.values(trendData.assets) as any[];
  }, [trendData]);

  const monitoredAssetCount = assetList.length;

  if (!selectedPipelineId) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" /></div>;
  }

  return (
    <div className="space-y-2">
      <SummaryHero
        incidents={activeIncidents}
        monitoredAssetCount={monitoredAssetCount}
        updatedAt={trendData?.updatedAt}
      />
      <ActiveIncidents stackId={selectedPipelineId} onOpenInCopilot={handleOpenInCopilot} />
      <TrendStrip stackId={selectedPipelineId} />
      <AssetHealthLean
        assets={assetList}
        expandedFqn={expandedAssetFqn}
        onToggle={(fqn) => setExpandedAssetFqn((p) => p === fqn ? null : fqn)}
        activeCategories={activeCategories}
        onRunAnalysis={() => {}}
      />
      <CoverageGaps
        unmonitoredCriticalAssets={unmonitoredCritical}
        pendingRecommendations={recommendations}
        onAddMonitor={(fqn) => router.push(`/dashboard/monitors?createFor=${encodeURIComponent(fqn)}`)}
        onReviewRecs={() => router.push('/dashboard/monitors?tab=recommendations')}
      />
      {assetList.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12">
          <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
          <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Visual smoke test**

Run `npm run dev` and open `/dashboard/monitors`. The Summary tab should render the hero, then (eventually) any active incidents, then a trend strip, then the asset list, then coverage gaps. With no incidents the hero should be green. Type-check too: `npm run type-check`.

- [ ] **Step 4: Commit**

```bash
git add components/monitors/DriftSummaryTab.tsx components/monitors/PipelineHealthTiles.tsx
git commit -m "feat(monitors): rebuild Summary tab around hero + active incidents + trend strip"
```

---

### Task 22: Coverage endpoint stub for unmonitored critical assets

**Files:**
- Create: `app/api/coverage/unmonitored-critical/route.ts`

The frontend calls `/api/coverage/unmonitored-critical?stackId=...`. Implement a basic endpoint that returns assets with downstream dashboards but no monitors. Reuse the existing engine graph store (this file mirrors the pattern in `app/api/lineage/...`).

- [ ] **Step 1: Implement minimal endpoint**

Create `app/api/coverage/unmonitored-critical/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  // Find LineageNodes flagged as having downstream dashboards but no monitors targeting their FQN.
  // For v1 we use a simple proxy: pick LineageNodes whose `criticality` is 'high' or whose
  // metadata indicates a downstream dashboard, intersected with the absence of a Monitor row
  // sharing the same targetFqn.
  const monitoredFqns = new Set(
    (await prisma.monitor.findMany({
      where: { organizationId, monitorGroup: { pipelineStackId: stackId } },
      select: { targetFqn: true },
    })).map((m) => m.targetFqn).filter((x): x is string => !!x)
  );

  const criticalNodes = await prisma.lineageNode.findMany({
    where: { organizationId, pipelineStackId: stackId, criticality: { in: ['high', 'critical'] } as any },
    select: { fqn: true, criticality: true, name: true },
    take: 50,
  });

  const assets = criticalNodes
    .filter((n) => n.fqn && !monitoredFqns.has(n.fqn))
    .map((n) => ({ fqn: n.fqn!, reason: `criticality=${n.criticality ?? 'high'}` }))
    .slice(0, 10);

  return NextResponse.json({ assets });
}
```

If the `LineageNode` model doesn't have a `criticality` field, replace the `where` clause with `where: { organizationId, pipelineStackId: stackId, type: { in: ['table', 'dataset'] } }` and return the first 10 nodes that have no monitor — the design goal is just to surface a non-empty list so the CoverageGaps card has content. Adjust to whatever criticality signal the codebase actually exposes.

- [ ] **Step 2: Type-check**

Run: `npm run type-check`
Expected: no errors. If `criticality` is not a field on `LineageNode`, simplify per the note above.

- [ ] **Step 3: Commit**

```bash
git add app/api/coverage/unmonitored-critical/route.ts
git commit -m "feat(coverage): GET /api/coverage/unmonitored-critical for CoverageGaps card"
```

---

### Task 23: Move Pipeline Health tiles into the Pipeline Monitors tab

**Files:**
- Modify: `app/(dashboard)/dashboard/monitors/page.tsx`

- [ ] **Step 1: Render `PipelineHealthTiles` above the Pipeline Monitors list**

In `app/(dashboard)/dashboard/monitors/page.tsx`, find the tab content block (around line 540, the section that renders `{activeTab === 'pipeline' && renderMonitorList(pipelineWatches, pipelineTasks)}`).

Replace it with:

```tsx
{activeTab === 'pipeline' && (
  <>
    <PipelineHealthTiles />
    {renderMonitorList(pipelineWatches, pipelineTasks)}
  </>
)}
```

Add the import at the top of the file:

```tsx
import { PipelineHealthTiles } from '@/components/monitors/PipelineHealthTiles';
```

- [ ] **Step 2: Type-check and visually verify**

Run `npm run type-check` then `npm run dev` and click into the **Pipeline Monitors** tab. The six tiles should render at the top of the tab; the Summary tab no longer shows them.

- [ ] **Step 3: Commit**

```bash
git add app/\(dashboard\)/dashboard/monitors/page.tsx
git commit -m "feat(monitors): relocate Pipeline Health tiles to Pipeline Monitors tab"
```

---

### Task 24: Pre-seed the co-pilot panel with the cached hypothesis

**Files:**
- Modify: copilot page (find by grepping for `'incident'` after the previous task lands; the route push uses `?contextType=incident`)

The `IncidentCard`'s `Open in Co-pilot` action sends the user to `/dashboard/copilot?contextType=incident&incidentId=…&monitorId=…&targetFqn=…`. The copilot page needs to consume those query params and pre-seed the chat with the cached hypothesis.

- [ ] **Step 1: Locate the copilot page**

Run: `find app -path '*/copilot/page.tsx' -not -path '*/.worktrees/*'`
Expected: one path printed.

- [ ] **Step 2: Add incident-context handling at the page level**

At the top of the copilot page component, add:

```tsx
import { useSearchParams } from 'next/navigation';
// ...inside component
const searchParams = useSearchParams();
const incidentId = searchParams.get('incidentId');
const incidentTargetFqn = searchParams.get('targetFqn');

useEffect(() => {
  if (!incidentId) return;
  let active = true;
  // Fetch the incident and seed the chat
  fetch(`/api/incidents?stackId=${selectedPipelineId}&status=active`)
    .then((r) => r.ok ? r.json() : null)
    .then((d) => {
      if (!active) return;
      const inc = (d?.incidents || []).find((i: any) => i.id === incidentId);
      if (!inc) return;
      const seed = `[Incident on ${inc.targetFqn}] Hypothesis: ${inc.llmHypothesis ?? '—'}\n\nWhat would you like me to investigate?`;
      // Adapt this call to whatever the existing copilot page uses to programmatically inject a message.
      // Look for an existing helper like `setMessages` or `appendAssistantMessage`.
      seedAssistantMessage(seed);
    });
  return () => { active = false; };
}, [incidentId, selectedPipelineId]);
```

Replace `seedAssistantMessage(seed)` with whatever the existing copilot page uses to insert a pre-canned assistant message. If the copilot page does not currently support pre-seeding, add a `seedAssistant` helper that pushes onto its `messages` state.

- [ ] **Step 3: Manually verify the round trip**

1. Trigger a monitor failure (run a known-failing monitor with "Run Now").
2. Wait until the diagnose call finishes (poll `/api/incidents?stackId=…&status=active` to confirm `llmHypothesis` is populated).
3. Click the Active Incident's `Open in Co-pilot →` button.
4. Confirm the co-pilot opens with the hypothesis as the first assistant message.

- [ ] **Step 4: Commit**

```bash
git add app  # whatever copilot page file changed
git commit -m "feat(copilot): seed chat with incident hypothesis when opened from IncidentCard"
```

---

### Task 25: Backfill script for incidents

**Files:**
- Create: `prisma/scripts/backfill-incidents.ts`

- [ ] **Step 1: Implement**

Create `prisma/scripts/backfill-incidents.ts`:

```ts
/**
 * One-shot backfill: open an Incident for each currently-failing monitor
 * that has no existing Incident. Run once after deploy.
 *
 * Run with: npx tsx prisma/scripts/backfill-incidents.ts
 */
import prisma from '@/lib/db';

async function main() {
  const failing = await prisma.monitor.findMany({
    where: { lastStatus: { in: ['FAIL', 'WARN', 'ERROR'] } },
    include: { monitorGroup: true, runs: { take: 1, orderBy: { startedAt: 'desc' } } },
  });
  let opened = 0;
  for (const m of failing) {
    const existing = await prisma.incident.findFirst({
      where: { monitorId: m.id, status: { in: ['OPEN', 'ACKNOWLEDGED'] } },
    });
    if (existing) continue;
    const run = m.runs[0];
    if (!run || !m.monitorGroup) continue;
    await prisma.incident.create({
      data: {
        organizationId: m.organizationId ?? m.monitorGroup.organizationId,
        pipelineStackId: m.monitorGroup.pipelineStackId,
        monitorId: m.id,
        monitorGroupId: m.monitorGroupId ?? null,
        targetFqn: m.targetFqn ?? 'unknown',
        status: 'OPEN',
        openedAt: run.startedAt,
        openingRunId: run.id,
        signature: 'backfilled',
        consecutiveCount: 1,
        llmHypothesis: 'Backfilled — analysis pending. Click "Open in Co-pilot" to investigate.',
      },
    });
    opened += 1;
  }
  console.log(`Backfill complete. Opened ${opened} incident(s).`);
  await prisma.$disconnect();
}

main().catch((e) => { console.error(e); process.exit(1); });
```

If `Monitor.organizationId` does not exist, drop the `m.organizationId ??` and just use `m.monitorGroup.organizationId`. Verify the field by inspecting `prisma/schema.prisma` before running.

- [ ] **Step 2: Run the backfill against dev DB**

```bash
npx tsx prisma/scripts/backfill-incidents.ts
```

Expected: prints `Backfill complete. Opened N incident(s).` Where N is your current failing-monitor count.

- [ ] **Step 3: Commit**

```bash
git add prisma/scripts/backfill-incidents.ts
git commit -m "chore(incidents): one-shot backfill script for currently-failing monitors"
```

---

### Task 26: End-to-end manual verification

This task has no code — it confirms the redesign works as a system. Use the dev server.

- [ ] **Step 1: Trigger a failing monitor**

Pick a monitor you can deliberately break (e.g., set a freshness threshold to `1 second` on a stale table). Click "Run Now" on the watch.

- [ ] **Step 2: Observe an incident is created**

Within ~5s, hit `/api/incidents?stackId=<id>&status=active` and confirm a new incident exists with `signature` and `llmHypothesis` populated. If the LLM call timed out, the fallback signature like `freshness-over-threshold` should be present plus the deterministic fallback hypothesis.

- [ ] **Step 3: Confirm the Summary page renders**

Open `/dashboard/monitors`. Verify in order:
- Hero is red, says "1 critical incident…"
- Active incidents list shows the card with the hypothesis paragraph
- "Show evidence" toggles the signature/owner/opened-at section
- "Acknowledge" moves the card to faded style
- "Mute → 1h" hides the card under the "+ 1 muted incident" expander

- [ ] **Step 4: Confirm auto-recovery**

Restore the threshold so the next run passes. Click "Run Now" again. Within ~5s, the incident should disappear from Active Incidents (status RESOLVED) and the Recovered tile in TrendStrip should increment.

- [ ] **Step 5: Confirm Open in Co-pilot**

Trigger another failure, click "Open in Co-pilot →" on the card. The co-pilot opens with the hypothesis as the first assistant message.

- [ ] **Step 6: Confirm the Pipeline Monitors tab**

Click into the Pipeline Monitors tab. The six tool tiles render at the top. The Summary tab no longer shows them.

- [ ] **Step 7: Run all tests**

```bash
npx jest lib/incidents
cd scanner && source venv/bin/activate && pytest tests/copilot/test_incident_diagnosis.py -v
```

Expected: all green.

- [ ] **Step 8: Final commit (if any cleanup)**

If any cleanup commits are needed (typo fixes, console.log removal), commit them now with a single `chore(incidents): cleanup after manual verification` message. Otherwise skip.
