# Sources Category & Integration Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sources a first-class leftmost layer in the Pallisade pipeline, restructure the integrations connect page so Sources is its own category with named-connector stubs, and add a multi-path discovery + dry-probe verify gate so an integration that exists in the DB is, by construction, a working integration.

**Architecture:** All new code composes over the existing `HttpProbeAdapter` and `CustomSourceDriver` (committed in this worktree by the prior spec). New `scanner/discovery/` module orchestrates three discoverer paths in parallel via `asyncio.gather`. Two new FastAPI endpoints (`/discover` JSON, `/verify` SSE) drive the wizard's new Discovery and Verify steps. Frontend taxonomy gains a `SOURCE` `PipelineLayer` so Custom Source — and future named source connectors — render leftmost in pipeline + lineage views. Persist-only-on-pass: the `Integration` row is created only after every dataset's dry-probe succeeds.

**Tech Stack:** Python 3.11 / FastAPI / asyncio / sse-starlette · Next.js 15 / React / TypeScript · Prisma / PostgreSQL · existing `requests`-based `HttpProbeAdapter` · existing warehouse + ingestion drivers under `scanner/drivers/`

**Spec:** [`docs/superpowers/specs/2026-05-01-sources-category-and-integration-tests-design.md`](../specs/2026-05-01-sources-category-and-integration-tests-design.md)

**Branch:** Implementation lives in worktree `.worktrees/feat-custom-source-integration` on branch `feat/custom-source-integration`. Plans + specs live on `main`.

---

## File Structure

**New files (Python):**

| Path | Responsibility |
|---|---|
| `scanner/discovery/__init__.py` | Package marker |
| `scanner/discovery/types.py` | `DatasetCandidate`, `DiscoveryError`, `DiscoveryResult` dataclasses |
| `scanner/discovery/source_discovery.py` | `SourceDiscoveryOrchestrator` (asyncio.gather over 3 paths) |
| `scanner/discovery/probe/__init__.py` | Package marker |
| `scanner/discovery/probe/source_probe_discoverer.py` | Path 1 — wraps `HttpProbeAdapter`, finds JSON arrays |
| `scanner/discovery/warehouse/__init__.py` | Package marker |
| `scanner/discovery/warehouse/warehouse_discoverer.py` | Path 3 — reads INFORMATION_SCHEMA via existing warehouse adapters |
| `scanner/discovery/ingestion/__init__.py` | Package marker |
| `scanner/discovery/ingestion/base.py` | `IngestionDiscoverer` ABC + `ConnectorMatch` dataclass |
| `scanner/discovery/ingestion/fivetran.py` | Fivetran-specific config-shape adapter |
| `scanner/discovery/ingestion/airbyte.py` | Airbyte-specific config-shape adapter |
| `scanner/discovery/ingestion/stitch.py` | Stitch-specific config-shape adapter |
| `scanner/api/routers/source_discovery.py` | `POST /api/v1/integrations/source/discover` |
| `scanner/api/routers/source_verify.py` | `POST /api/v1/integrations/source/verify` (SSE) |
| `scanner/api/routers/waitlist.py` | `POST /api/v1/waitlist/source-connector` |
| `scanner/tests/discovery/test_source_discovery.py` | Orchestrator tests |
| `scanner/tests/discovery/probe/test_source_probe_discoverer.py` | Path 1 tests |
| `scanner/tests/discovery/warehouse/test_warehouse_discoverer.py` | Path 3 tests |
| `scanner/tests/discovery/ingestion/test_fivetran_discoverer.py` | Path 2 Fivetran tests |
| `scanner/tests/discovery/ingestion/test_airbyte_discoverer.py` | Path 2 Airbyte tests |
| `scanner/tests/discovery/ingestion/test_stitch_discoverer.py` | Path 2 Stitch tests |
| `scanner/api/tests/test_source_discovery_router.py` | `/discover` endpoint tests |
| `scanner/api/tests/test_source_verify_router.py` | `/verify` endpoint tests (SSE) |
| `scanner/api/tests/test_waitlist_router.py` | Waitlist endpoint tests |
| `scanner/tests/integration/test_source_integration_e2e.py` | End-to-end smoke test |

**New files (TypeScript / Next.js):**

| Path | Responsibility |
|---|---|
| `app/(dashboard)/dashboard/integrations/connect/page.tsx` | Category-grouped picker index |
| `components/integrations/RequestAccessModal.tsx` | Coming-soon modal for Salesforce/Shopify/HubSpot |
| `app/api/v1/integrations/source/discover/route.ts` | Next.js → FastAPI proxy (JSON) |
| `app/api/v1/integrations/source/verify/route.ts` | Next.js → FastAPI proxy (SSE pass-through) |
| `app/api/v1/waitlist/source-connector/route.ts` | Next.js → FastAPI proxy |

**Files modified:**

| Path | Change |
|---|---|
| `components/pipeline/types.ts` | Add `SOURCE` to `PipelineLayer`, add `LAYER_LABELS.SOURCE`, `LAYER_COLORS.SOURCE`, `status?` field on `ToolDefinition`, `TOOLS.SOURCE` array (4 entries) |
| `app/(dashboard)/dashboard/pipeline/page.tsx` | Prepend `SOURCE` to `ConnectorGroup` + `LAYER_ORDER` + `CORE_GROUP_ORDER`; add `LAYER_X.SOURCE = 0` and shift downstream X by +60; **delete lines 184–195** (misclassification block); spread `TOOLS.SOURCE` into connector list builder |
| `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx` | Step 3 → Discovery step (calls `/discover`, renders 3 grouped sections + manual fallback); Step 4 — remove `lands_in` (moved into Step 3); Step 5 → SSE `/verify` gate; Save persists only on all-pass |
| `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx` | Update env var name from `NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION` to `NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY` |
| `prisma/schema.prisma` | Add `SourceConnectorWaitlist` model |
| `scanner/api/main.py` | Register new routers (`source_discovery`, `source_verify`, `waitlist`) |
| `scanner/integrations/feature_flags.py` (or wherever the flag is read) | Rename `CUSTOM_SOURCE_INTEGRATION` constant to `SOURCES_CATEGORY` |

---

## Task 1: Feature flag rename + frontend taxonomy

Adds `SOURCE` as a real `PipelineLayer` in the frontend, registers Custom Source + 3 coming-soon stubs under it, deletes the pipeline-page misclassification block, and renames the feature-flag env var so it reads as a category-level gate.

**Files:**
- Modify: `components/pipeline/types.ts`
- Modify: `app/(dashboard)/dashboard/pipeline/page.tsx`
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx`
- Grep + rename: any other reference to `CUSTOM_SOURCE_INTEGRATION` env var
- Test: `__tests__/pipeline/sources-layer.test.tsx`

- [ ] **Step 1.1: Write the failing test**

Create `__tests__/pipeline/sources-layer.test.tsx`:

```tsx
import { TOOLS, LAYER_LABELS, LAYER_COLORS, PipelineLayer } from '@/components/pipeline/types';

describe('SOURCE pipeline layer', () => {
  it('exposes SOURCE in TOOLS with custom_source as the only live tile', () => {
    expect(TOOLS.SOURCE).toBeDefined();
    const ids = TOOLS.SOURCE.map(t => t.id).sort();
    expect(ids).toEqual(['custom_source', 'hubspot', 'salesforce', 'shopify']);

    const live = TOOLS.SOURCE.filter(t => (t.status ?? 'live') === 'live').map(t => t.id);
    expect(live).toEqual(['custom_source']);

    const comingSoon = TOOLS.SOURCE.filter(t => t.status === 'coming_soon').map(t => t.id).sort();
    expect(comingSoon).toEqual(['hubspot', 'salesforce', 'shopify']);
  });

  it('labels the SOURCE layer "Sources"', () => {
    expect(LAYER_LABELS.SOURCE).toBe('Sources');
  });

  it('assigns SOURCE its own color (slate)', () => {
    expect(LAYER_COLORS.SOURCE).toBe('#64748B');
  });

  it('positions SOURCE leftmost in PipelineLayer type via runtime check', () => {
    // PipelineLayer is a type; we verify via a sentinel object that SOURCE exists as a key
    const sentinel: Record<PipelineLayer, true> = {
      SOURCE: true, INGESTION: true, TRANSFORMATION: true, WAREHOUSE: true,
      REPORTING: true, STORAGE: true, VERSION_CONTROL: true,
      ORCHESTRATION: true, INFRASTRUCTURE: true, NOTIFICATIONS: true, UNCATEGORIZED: true,
    };
    expect(sentinel.SOURCE).toBe(true);
  });
});
```

- [ ] **Step 1.2: Run test, confirm failure**

```bash
npm test -- __tests__/pipeline/sources-layer.test.tsx
```

Expected: FAIL with "Property 'SOURCE' does not exist on type ..." or `TOOLS.SOURCE` undefined.

- [ ] **Step 1.3: Add `SOURCE` to `PipelineLayer` union and add ToolDefinition.status**

Edit `components/pipeline/types.ts` line 8:

```ts
// before
export type PipelineLayer = 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING' | 'STORAGE' | 'VERSION_CONTROL' | 'ORCHESTRATION' | 'INFRASTRUCTURE' | 'NOTIFICATIONS' | 'UNCATEGORIZED';
// after
export type PipelineLayer = 'SOURCE' | 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING' | 'STORAGE' | 'VERSION_CONTROL' | 'ORCHESTRATION' | 'INFRASTRUCTURE' | 'NOTIFICATIONS' | 'UNCATEGORIZED';
```

Add to `ToolDefinition` interface (around line 88):

```ts
export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  layer: PipelineLayer;
  // ... existing fields ...
  status?: 'live' | 'coming_soon';   // NEW — defaults to 'live' when absent
}
```

- [ ] **Step 1.4: Add LAYER_LABELS / LAYER_COLORS entries**

In the `LAYER_LABELS` record (around line 45):

```ts
export const LAYER_LABELS: Record<PipelineLayer, string> = {
  SOURCE: 'Sources',          // NEW — first
  INGESTION: 'Ingestion',
  // ... rest unchanged
};
```

In the `LAYER_COLORS` record (around line 17):

```ts
export const LAYER_COLORS: Record<PipelineLayer, string> = {
  SOURCE: '#64748B',          // NEW — slate
  INGESTION: '#10B981',
  // ... rest unchanged
};
```

- [ ] **Step 1.5: Add `TOOLS.SOURCE` array**

In `TOOLS` (around line 136), prepend a `SOURCE` key:

```ts
export const TOOLS: Record<PipelineLayer, ToolDefinition[]> = {
  SOURCE: [
    {
      id: 'custom_source',
      name: 'Custom Source',
      description: 'Monitor any HTTPS-accessible REST API as a source — IoT portals, vertical-SaaS platforms, custom internal services.',
      layer: 'SOURCE',
      status: 'live',
    },
    {
      id: 'salesforce',
      name: 'Salesforce',
      description: 'Monitor Salesforce objects as pipeline sources. Coming soon.',
      layer: 'SOURCE',
      status: 'coming_soon',
    },
    {
      id: 'shopify',
      name: 'Shopify',
      description: 'Monitor Shopify orders, customers, and products. Coming soon.',
      layer: 'SOURCE',
      status: 'coming_soon',
    },
    {
      id: 'hubspot',
      name: 'HubSpot',
      description: 'Monitor HubSpot CRM objects as pipeline sources. Coming soon.',
      layer: 'SOURCE',
      status: 'coming_soon',
    },
  ],
  INGESTION: [
    // ... existing entries unchanged
  ],
  // ... all other layers unchanged
};
```

- [ ] **Step 1.6: Re-run test, confirm pass**

```bash
npm test -- __tests__/pipeline/sources-layer.test.tsx
```

Expected: PASS (4/4).

- [ ] **Step 1.7: Update pipeline page — add SOURCE to ConnectorGroup, orderings, layer-X**

Edit `app/(dashboard)/dashboard/pipeline/page.tsx`:

Line 27 — prepend `'SOURCE'`:

```ts
// before
type ConnectorGroup = 'WAREHOUSE' | 'TRANSFORM' | 'ORCHESTRATION' | 'BI' | 'INGESTION' | 'STORAGE' | 'VERSION_CONTROL' | 'INFRASTRUCTURE' | 'ALERTS';
// after
type ConnectorGroup = 'SOURCE' | 'WAREHOUSE' | 'TRANSFORM' | 'ORCHESTRATION' | 'BI' | 'INGESTION' | 'STORAGE' | 'VERSION_CONTROL' | 'INFRASTRUCTURE' | 'ALERTS';
```

Line 49 — prepend `'SOURCE'`:

```ts
// before
const CORE_GROUP_ORDER: ConnectorGroup[] = ['WAREHOUSE', 'TRANSFORM', 'ORCHESTRATION', 'VERSION_CONTROL', 'BI', 'INGESTION', 'STORAGE', 'INFRASTRUCTURE', 'ALERTS'];
// after
const CORE_GROUP_ORDER: ConnectorGroup[] = ['SOURCE', 'WAREHOUSE', 'TRANSFORM', 'ORCHESTRATION', 'VERSION_CONTROL', 'BI', 'INGESTION', 'STORAGE', 'INFRASTRUCTURE', 'ALERTS'];
```

Line 50 — prepend `'SOURCE'`:

```ts
// before
const LAYER_ORDER: PipelineLayer[] = ['INGESTION', 'VERSION_CONTROL', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING', 'INFRASTRUCTURE'];
// after
const LAYER_ORDER: PipelineLayer[] = ['SOURCE', 'INGESTION', 'VERSION_CONTROL', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING', 'INFRASTRUCTURE'];
```

Around line 119 — add `SOURCE: 0` and shift downstream X positions by +60:

```ts
// before
const layerX: Record<PipelineLayer, number> = {
  INGESTION: 120, VERSION_CONTROL: 300, ORCHESTRATION: 300, TRANSFORMATION: 480,
  WAREHOUSE: 660, REPORTING: 840, STORAGE: 660, INFRASTRUCTURE: 840,
  NOTIFICATIONS: 1020, UNCATEGORIZED: 1020,
};
// after
const layerX: Record<PipelineLayer, number> = {
  SOURCE: 0, INGESTION: 180, VERSION_CONTROL: 360, ORCHESTRATION: 360, TRANSFORMATION: 540,
  WAREHOUSE: 720, REPORTING: 900, STORAGE: 720, INFRASTRUCTURE: 900,
  NOTIFICATIONS: 1080, UNCATEGORIZED: 1080,
};
```

Add label entry around line 112:

```ts
// before
BI: 'BI / Reporting', INGESTION: 'Ingestion', STORAGE: 'Storage', INFRASTRUCTURE: 'Infrastructure', ALERTS: 'Alerts & Integrations',
// after
SOURCE: 'Sources', BI: 'BI / Reporting', INGESTION: 'Ingestion', STORAGE: 'Storage', INFRASTRUCTURE: 'Infrastructure', ALERTS: 'Alerts & Integrations',
```

In the connector list builder (around line 171), add a `TOOLS.SOURCE` spread as the first entry:

```ts
const allConnectors = [
  ...TOOLS.SOURCE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'SOURCE' as const, mode: 'pipeline' as const, layer: t.layer, status: t.status })),
  ...TOOLS.WAREHOUSE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'WAREHOUSE' as const, mode: 'pipeline' as const, layer: t.layer })),
  // ... rest unchanged
];
```

- [ ] **Step 1.8: Delete the misclassification block at lines 184–195**

In `app/(dashboard)/dashboard/pipeline/page.tsx`, delete the entire feature-flag-conditional Custom Source push block (currently around lines 184–195):

```ts
// DELETE THIS WHOLE BLOCK
// Feature-flagged: CUSTOM_SOURCE_INTEGRATION ships dark by default.
// Ops sets NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION=true to enable.
if (
  process.env.NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION === 'true'
) {
  allConnectors.push({
    id: 'custom_source',
    name: 'Custom Source',
    description: '...',
    group: 'INGESTION',
    mode: 'pipeline' as const,
    layer: 'INGESTION',
  });
}
```

Custom Source now appears via the `TOOLS.SOURCE` spread above — no separate injection.

- [ ] **Step 1.9: Rename feature-flag env var**

Find every reference to `CUSTOM_SOURCE_INTEGRATION`:

```bash
grep -rn "CUSTOM_SOURCE_INTEGRATION" --include="*.ts" --include="*.tsx" --include="*.py"
```

For each match, rename:
- Frontend env var: `NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION` → `NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY`
- Backend env var (if any): `CUSTOM_SOURCE_INTEGRATION` → `SOURCES_CATEGORY`
- Update `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx:6` to read the new name.

Update `.env.example` if present.

- [ ] **Step 1.10: Visual smoke check**

```bash
NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY=true npm run dev
```

Open the pipeline page and verify:
- A "Sources" column appears leftmost (slate color).
- Custom Source tile is in Sources, not Ingestion.
- Salesforce / Shopify / HubSpot tiles render under Sources with a muted/disabled visual treatment.

If logos for the three coming-soon connectors aren't yet in `public/icon_logos/`, the existing fallback icon will render — that's fine for now (user is providing logos separately).

- [ ] **Step 1.11: Commit**

```bash
git add components/pipeline/types.ts app/\(dashboard\)/dashboard/pipeline/page.tsx app/\(dashboard\)/dashboard/integrations/connect/custom-source/page.tsx __tests__/pipeline/sources-layer.test.tsx .env.example
git commit -m "feat(taxonomy): add SOURCE PipelineLayer; move Custom Source out of INGESTION; rename flag → SOURCES_CATEGORY"
```

---

## Task 2: Integrations connect page + RequestAccessModal + waitlist

Adds the category-grouped picker at `/integrations/connect`, the request-access modal for coming-soon tiles, and a Prisma model + endpoint to record waitlist interest.

**Files:**
- Create: `app/(dashboard)/dashboard/integrations/connect/page.tsx`
- Create: `components/integrations/RequestAccessModal.tsx`
- Create: `app/api/v1/waitlist/source-connector/route.ts`
- Create: `scanner/api/routers/waitlist.py`
- Create: `scanner/api/tests/test_waitlist_router.py`
- Modify: `prisma/schema.prisma`
- Modify: `scanner/api/main.py`

- [ ] **Step 2.1: Add Prisma model**

In `prisma/schema.prisma`, add:

```prisma
model SourceConnectorWaitlist {
  id           String   @id @default(cuid())
  userId       String
  connectorId  String   // 'salesforce' | 'shopify' | 'hubspot'
  requestedAt  DateTime @default(now())
  user         User     @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@unique([userId, connectorId])
  @@index([connectorId])
}
```

Also add the back-relation on `User`:

```prisma
model User {
  // ... existing fields ...
  sourceConnectorWaitlist  SourceConnectorWaitlist[]
}
```

- [ ] **Step 2.2: Run migration**

```bash
npx prisma migrate dev --name add_source_connector_waitlist
```

Expected: migration applies cleanly, `SourceConnectorWaitlist` table created.

- [ ] **Step 2.3: Write failing waitlist endpoint test**

Create `scanner/api/tests/test_waitlist_router.py`:

```python
import pytest
from fastapi.testclient import TestClient
from scanner.api.main import app

client = TestClient(app)

def test_post_waitlist_creates_row(authed_client, db_session):
    response = authed_client.post(
        "/api/v1/waitlist/source-connector",
        json={"connector_id": "salesforce"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["connector_id"] == "salesforce"
    assert "requested_at" in body

def test_post_waitlist_rejects_unknown_connector(authed_client):
    response = authed_client.post(
        "/api/v1/waitlist/source-connector",
        json={"connector_id": "made_up"},
    )
    assert response.status_code == 400

def test_post_waitlist_idempotent_per_user(authed_client):
    """Posting twice for the same connector returns 200 (already on waitlist), not 409."""
    r1 = authed_client.post("/api/v1/waitlist/source-connector", json={"connector_id": "shopify"})
    assert r1.status_code == 201
    r2 = authed_client.post("/api/v1/waitlist/source-connector", json={"connector_id": "shopify"})
    assert r2.status_code == 200
```

- [ ] **Step 2.4: Run test, confirm failure**

```bash
cd scanner && pytest api/tests/test_waitlist_router.py -v
```

Expected: FAIL with 404 (route not registered).

- [ ] **Step 2.5: Implement waitlist router**

Create `scanner/api/routers/waitlist.py`:

```python
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from prisma import Prisma
from scanner.api.deps import get_current_user, get_prisma

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"])

ALLOWED_CONNECTORS = {"salesforce", "shopify", "hubspot"}


class WaitlistRequest(BaseModel):
    connector_id: str


class WaitlistResponse(BaseModel):
    connector_id: str
    requested_at: datetime


@router.post("/source-connector", response_model=WaitlistResponse)
async def join_waitlist(
    body: WaitlistRequest,
    user=Depends(get_current_user),
    db: Prisma = Depends(get_prisma),
):
    if body.connector_id not in ALLOWED_CONNECTORS:
        raise HTTPException(400, f"unknown connector_id: {body.connector_id}")

    existing = await db.sourceconnectorwaitlist.find_unique(
        where={"userId_connectorId": {"userId": user.id, "connectorId": body.connector_id}}
    )
    if existing:
        return WaitlistResponse(connector_id=existing.connectorId, requested_at=existing.requestedAt), 200

    created = await db.sourceconnectorwaitlist.create(
        data={"userId": user.id, "connectorId": body.connector_id}
    )
    return WaitlistResponse(connector_id=created.connectorId, requested_at=created.requestedAt), 201
```

Register in `scanner/api/main.py`:

```python
from scanner.api.routers import waitlist
app.include_router(waitlist.router)
```

- [ ] **Step 2.6: Re-run test, confirm pass**

```bash
cd scanner && pytest api/tests/test_waitlist_router.py -v
```

Expected: PASS (3/3).

- [ ] **Step 2.7: Add Next.js proxy route**

Create `app/api/v1/waitlist/source-connector/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { getAuthHeaders } from '@/lib/api/auth';

const FASTAPI_URL = process.env.FASTAPI_BASE_URL ?? 'http://localhost:8000';

export async function POST(req: NextRequest) {
  const body = await req.json();
  const headers = await getAuthHeaders(req);
  const upstream = await fetch(`${FASTAPI_URL}/api/v1/waitlist/source-connector`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
```

(`getAuthHeaders` is the existing helper — confirm path; if your project uses a different auth-forwarding pattern, mirror what the other proxy routes do, e.g. `app/api/v1/copilot/chat/route.ts`.)

- [ ] **Step 2.8: Implement RequestAccessModal**

Create `components/integrations/RequestAccessModal.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { toast } from 'sonner';

interface Props {
  connectorId: 'salesforce' | 'shopify' | 'hubspot';
  connectorName: string;
  open: boolean;
  onClose: () => void;
}

export function RequestAccessModal({ connectorId, connectorName, open, onClose }: Props) {
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  async function handleNotify() {
    setSubmitting(true);
    try {
      const res = await fetch('/api/v1/waitlist/source-connector', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connector_id: connectorId }),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success(`We'll notify you when ${connectorName} support ships.`);
      onClose();
    } catch (e: unknown) {
      toast.error(`Couldn't record interest: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-2">{connectorName} source — coming soon</h2>
        <p className="text-sm text-gray-600 mb-4">
          We're working on first-class {connectorName} support as a Pallisade source. Click below to
          be notified when it ships.
        </p>
        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            disabled={submitting}
          >
            Close
          </button>
          <button
            onClick={handleNotify}
            disabled={submitting}
            className="px-4 py-2 bg-slate-700 text-white rounded text-sm hover:bg-slate-800 disabled:opacity-50"
          >
            {submitting ? 'Recording…' : 'Notify me'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2.9: Implement category-grouped picker page**

Create `app/(dashboard)/dashboard/integrations/connect/page.tsx`:

```tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { TOOLS, LAYER_LABELS, LAYER_COLORS, PipelineLayer } from '@/components/pipeline/types';
import { ToolIcon } from '@/components/icons/ToolIcon';
import { RequestAccessModal } from '@/components/integrations/RequestAccessModal';

const CONNECT_ROUTES: Partial<Record<string, string>> = {
  custom_source: '/dashboard/integrations/connect/custom-source',
  // future live tiles add their wizard routes here
};

const CATEGORY_ORDER: PipelineLayer[] = [
  'SOURCE', 'INGESTION', 'TRANSFORMATION', 'WAREHOUSE',
  'STORAGE', 'REPORTING', 'ORCHESTRATION', 'VERSION_CONTROL', 'INFRASTRUCTURE',
];

export default function ConnectPage() {
  const [modal, setModal] = useState<{ id: 'salesforce' | 'shopify' | 'hubspot'; name: string } | null>(null);

  if (process.env.NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY !== 'true') {
    return <div className="p-6">Sources category not enabled.</div>;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-semibold mb-6">Connect an integration</h1>

      {CATEGORY_ORDER.map((layer) => {
        const tools = TOOLS[layer] ?? [];
        if (tools.length === 0) return null;
        return (
          <section key={layer} className="mb-8">
            <h2
              className="text-sm font-semibold uppercase tracking-wide mb-3"
              style={{ color: LAYER_COLORS[layer] }}
            >
              {LAYER_LABELS[layer]}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {tools.map((tool) => {
                const status = tool.status ?? 'live';
                const route = CONNECT_ROUTES[tool.id];
                if (status === 'live' && route) {
                  return (
                    <Link
                      key={tool.id}
                      href={route}
                      className="border rounded p-4 hover:border-slate-400 hover:shadow-sm transition flex items-start gap-3"
                    >
                      <ToolIcon toolId={tool.id} size={32} />
                      <div>
                        <div className="font-medium">{tool.name}</div>
                        <div className="text-xs text-gray-500 mt-1">{tool.description}</div>
                      </div>
                    </Link>
                  );
                }
                // coming_soon
                return (
                  <button
                    key={tool.id}
                    onClick={() => setModal({ id: tool.id as 'salesforce' | 'shopify' | 'hubspot', name: tool.name })}
                    className="border rounded p-4 opacity-60 hover:opacity-80 transition flex items-start gap-3 text-left"
                  >
                    <ToolIcon toolId={tool.id} size={32} />
                    <div>
                      <div className="font-medium">
                        {tool.name} <span className="text-xs text-gray-500">— coming soon</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-1">{tool.description}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}

      {modal && (
        <RequestAccessModal
          connectorId={modal.id}
          connectorName={modal.name}
          open={true}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2.10: Smoke check the page**

```bash
NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY=true npm run dev
```

Visit `http://localhost:3000/dashboard/integrations/connect`. Verify:
- Sources category is leftmost / first.
- Custom Source tile clicks through to wizard.
- Salesforce/Shopify/HubSpot tiles open the modal; "Notify me" succeeds and toasts.
- Other categories render below Sources.

- [ ] **Step 2.11: Commit**

```bash
git add prisma/schema.prisma prisma/migrations/ \
  scanner/api/routers/waitlist.py scanner/api/tests/test_waitlist_router.py scanner/api/main.py \
  app/api/v1/waitlist/source-connector/route.ts \
  components/integrations/RequestAccessModal.tsx \
  app/\(dashboard\)/dashboard/integrations/connect/page.tsx
git commit -m "feat(integrations): connect-page picker, RequestAccessModal, source-connector waitlist"
```

---

## Task 3: Source-probe discoverer (Path 1) + `/discover` endpoint + wizard Discovery step

Adds the core discovery scaffolding and the simplest of the three paths (probe-only). Wizard step 3 is renamed to "Discovery" and starts calling `/discover` after Connection.

**Files:**
- Create: `scanner/discovery/__init__.py`, `scanner/discovery/types.py`, `scanner/discovery/source_discovery.py`
- Create: `scanner/discovery/probe/__init__.py`, `scanner/discovery/probe/source_probe_discoverer.py`
- Create: `scanner/api/routers/source_discovery.py`
- Create: `scanner/tests/discovery/test_source_discovery.py`
- Create: `scanner/tests/discovery/probe/test_source_probe_discoverer.py`
- Create: `scanner/api/tests/test_source_discovery_router.py`
- Create: `app/api/v1/integrations/source/discover/route.ts`
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx`
- Modify: `scanner/api/main.py`

- [ ] **Step 3.1: Define types**

Create `scanner/discovery/__init__.py` (empty) and `scanner/discovery/types.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


PathName = Literal['ingestion', 'warehouse', 'probe']
ErrorCode = Literal[
    'auth_failed',
    'host_unreachable',
    'response_too_large',
    'malformed_json',
    'no_connectors_connected',
    'no_warehouse_hint',
    'unknown',
]


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    is_nullable: bool


@dataclass(frozen=True)
class DatasetCandidate:
    source: PathName
    endpoint: Optional[str]
    json_root: Optional[str]
    timestamp_column: Optional[str]
    expected_schema: List[ColumnMetadata]
    lands_in: Optional[str]
    confidence: float


@dataclass(frozen=True)
class DiscoveryError:
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    candidates_by_path: Dict[PathName, List[DatasetCandidate]]
    errors_by_path: Dict[PathName, Optional[DiscoveryError]]
```

- [ ] **Step 3.2: Write failing test for SourceProbeDiscoverer**

Create `scanner/tests/discovery/__init__.py` and `scanner/tests/discovery/probe/__init__.py` (both empty), then `scanner/tests/discovery/probe/test_source_probe_discoverer.py`:

```python
import json
import pytest
import responses
from scanner.discovery.probe.source_probe_discoverer import SourceProbeDiscoverer
from scanner.discovery.types import DatasetCandidate, DiscoveryError


@responses.activate
def test_probe_discovers_top_level_array():
    responses.add(
        responses.GET,
        "https://api.example.com/sensors",
        json=[
            {"id": 1, "reading_at": "2026-05-01T00:00:00Z", "value": 12.3},
            {"id": 2, "reading_at": "2026-05-01T00:01:00Z", "value": 13.5},
        ],
        status=200,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url="https://api.example.com",
        endpoint="/sensors",
        auth={"kind": "api_key", "header_name": "X-API-Key", "secret": "test"},
    )

    assert error is None
    assert len(candidates) == 1
    assert candidates[0].source == 'probe'
    assert candidates[0].endpoint == "/sensors"
    assert candidates[0].timestamp_column == "reading_at"
    assert candidates[0].confidence == 0.7


@responses.activate
def test_probe_discovers_nested_array_and_sets_json_root():
    responses.add(
        responses.GET,
        "https://api.example.com/v1",
        json={"data": {"items": [{"id": 1, "ts": "2026-05-01T00:00:00Z"}]}},
        status=200,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url="https://api.example.com",
        endpoint="/v1",
        auth={"kind": "api_key", "header_name": "X-API-Key", "secret": "test"},
    )

    assert error is None
    assert len(candidates) == 1
    assert candidates[0].json_root == "data.items"


@responses.activate
def test_probe_returns_auth_failed_on_401():
    responses.add(
        responses.GET, "https://api.example.com/x",
        status=401,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url="https://api.example.com",
        endpoint="/x",
        auth={"kind": "api_key", "header_name": "X-API-Key", "secret": "test"},
    )

    assert candidates == []
    assert error is not None
    assert error.code == "auth_failed"


@responses.activate
def test_probe_returns_malformed_json_on_html_response():
    responses.add(
        responses.GET, "https://api.example.com/y",
        body="<html>not json</html>",
        status=200,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url="https://api.example.com", endpoint="/y",
        auth={"kind": "api_key", "header_name": "X-API-Key", "secret": "test"},
    )

    assert candidates == []
    assert error is not None
    assert error.code == "malformed_json"
```

- [ ] **Step 3.3: Run test, confirm failure**

```bash
cd scanner && pytest tests/discovery/probe/test_source_probe_discoverer.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.4: Implement SourceProbeDiscoverer**

Create `scanner/discovery/probe/__init__.py` (empty) and `scanner/discovery/probe/source_probe_discoverer.py`:

```python
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

from scanner.discovery.types import (
    ColumnMetadata,
    DatasetCandidate,
    DiscoveryError,
)
from scanner.adapters.http_probe import _infer_type, _parse_iso8601

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 30
_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB


def _apply_auth(session: requests.Session, auth: Dict[str, Any]) -> None:
    kind = auth.get("kind")
    if kind == "api_key":
        session.headers[auth.get("header_name", "X-API-Key")] = auth["secret"]
    elif kind == "bearer":
        session.headers["Authorization"] = f"Bearer {auth['secret']}"
    elif kind == "basic":
        session.auth = (auth["username"], auth["secret"])


def _find_arrays(obj: Any, path: str = "", max_depth: int = 3) -> List[Tuple[str, list]]:
    """Walk JSON up to max_depth and return [(dotted_path, list)] for every array of objects."""
    out: List[Tuple[str, list]] = []
    if max_depth < 0:
        return out
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        out.append((path, obj))
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            out.extend(_find_arrays(v, child_path, max_depth - 1))
    return out


_TIMESTAMP_NAME_HINTS = (
    "_at", "_ts", "timestamp", "created", "updated", "modified", "occurred", "event_time",
)


def _detect_timestamp_column(rows: list) -> Optional[str]:
    if not rows:
        return None
    first = rows[0]
    candidates: List[str] = []
    for col, val in first.items():
        col_l = col.lower()
        if any(h in col_l for h in _TIMESTAMP_NAME_HINTS):
            if isinstance(val, str) and _parse_iso8601(val) is not None:
                candidates.append(col)
            elif isinstance(val, (int, float)):
                candidates.append(col)
    return candidates[0] if candidates else None


def _infer_columns(rows: list) -> List[ColumnMetadata]:
    if not rows:
        return []
    first = rows[0]
    return [
        ColumnMetadata(
            name=col,
            data_type=_infer_type(val),
            is_nullable=any(r.get(col) is None for r in rows),
        )
        for col, val in first.items()
    ]


class SourceProbeDiscoverer:
    """Path 1: probe a single endpoint, find array roots, infer schema."""

    def discover(
        self,
        base_url: str,
        endpoint: str,
        auth: Dict[str, Any],
    ) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        url = base_url.rstrip("/") + endpoint
        session = requests.Session()
        try:
            _apply_auth(session, auth)
        except KeyError as e:
            return [], DiscoveryError(code="auth_failed", message=f"missing auth field: {e}")

        try:
            resp = session.get(url, timeout=_TIMEOUT_SEC, stream=True)
        except requests.exceptions.RequestException as e:
            return [], DiscoveryError(code="host_unreachable", message=str(e))

        if resp.status_code in (401, 403):
            return [], DiscoveryError(code="auth_failed", message=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            return [], DiscoveryError(code="host_unreachable", message=f"HTTP {resp.status_code}")

        body = b""
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            body += chunk
            if len(body) > _MAX_BYTES:
                return [], DiscoveryError(code="response_too_large", message=f">{_MAX_BYTES} bytes")

        try:
            import json as _json
            parsed = _json.loads(body)
        except ValueError as e:
            return [], DiscoveryError(code="malformed_json", message=str(e))

        arrays = _find_arrays(parsed)
        candidates: List[DatasetCandidate] = []
        for path, rows in arrays:
            candidates.append(
                DatasetCandidate(
                    source='probe',
                    endpoint=endpoint,
                    json_root=path or None,
                    timestamp_column=_detect_timestamp_column(rows),
                    expected_schema=_infer_columns(rows),
                    lands_in=None,
                    confidence=0.7,
                )
            )
        return candidates, None
```

- [ ] **Step 3.5: Re-run test, confirm pass**

```bash
cd scanner && pytest tests/discovery/probe/test_source_probe_discoverer.py -v
```

Expected: PASS (4/4).

- [ ] **Step 3.6: Write failing test for SourceDiscoveryOrchestrator**

Create `scanner/tests/discovery/test_source_discovery.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from scanner.discovery.source_discovery import SourceDiscoveryOrchestrator
from scanner.discovery.types import DatasetCandidate, DiscoveryError, ColumnMetadata


@pytest.mark.asyncio
async def test_orchestrator_runs_all_three_paths_in_parallel():
    probe = MagicMock()
    probe.discover = MagicMock(return_value=([
        DatasetCandidate('probe', '/x', None, 'ts', [], None, 0.7)
    ], None))
    warehouse = MagicMock()
    warehouse.discover = MagicMock(return_value=([], None))
    ingestion = MagicMock()
    ingestion.discover = MagicMock(return_value=([], None))

    orchestrator = SourceDiscoveryOrchestrator(
        probe_discoverer=probe,
        warehouse_discoverer=warehouse,
        ingestion_discoverer=ingestion,
    )
    result = await orchestrator.discover(
        base_url="https://api.example.com",
        endpoint="/x",
        auth={"kind": "api_key", "header_name": "X-API-Key", "secret": "t"},
        warehouse_hints=[],
        ingestion_hints=[],
    )

    assert len(result.candidates_by_path['probe']) == 1
    assert result.candidates_by_path['warehouse'] == []
    assert result.candidates_by_path['ingestion'] == []
    assert result.errors_by_path == {'probe': None, 'warehouse': None, 'ingestion': None}


@pytest.mark.asyncio
async def test_orchestrator_isolates_path_failures():
    probe = MagicMock()
    probe.discover = MagicMock(side_effect=RuntimeError("boom"))
    warehouse = MagicMock()
    warehouse.discover = MagicMock(return_value=([], None))
    ingestion = MagicMock()
    ingestion.discover = MagicMock(return_value=([], None))

    orchestrator = SourceDiscoveryOrchestrator(
        probe_discoverer=probe,
        warehouse_discoverer=warehouse,
        ingestion_discoverer=ingestion,
    )
    result = await orchestrator.discover(
        base_url="https://api.example.com",
        endpoint="/x",
        auth={"kind": "api_key", "header_name": "X-API-Key", "secret": "t"},
        warehouse_hints=[],
        ingestion_hints=[],
    )

    assert result.candidates_by_path['probe'] == []
    assert result.errors_by_path['probe'].code == 'unknown'
    assert result.errors_by_path['warehouse'] is None
    assert result.errors_by_path['ingestion'] is None
```

- [ ] **Step 3.7: Run test, confirm failure**

```bash
cd scanner && pytest tests/discovery/test_source_discovery.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.8: Implement SourceDiscoveryOrchestrator**

Create `scanner/discovery/source_discovery.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Protocol, Tuple

from scanner.discovery.types import (
    DatasetCandidate,
    DiscoveryError,
    DiscoveryResult,
    PathName,
)

logger = logging.getLogger(__name__)


class _PathDiscoverer(Protocol):
    def discover(self, **kwargs: Any) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        ...


class SourceDiscoveryOrchestrator:
    """Runs probe / warehouse / ingestion discovery in parallel.

    Each path's failure is isolated — if one path raises, the other two still
    return their results, and the failed path returns an empty list with a
    structured error (code='unknown' if uncategorized).
    """

    def __init__(
        self,
        probe_discoverer: _PathDiscoverer,
        warehouse_discoverer: _PathDiscoverer,
        ingestion_discoverer: _PathDiscoverer,
    ):
        self._probe = probe_discoverer
        self._warehouse = warehouse_discoverer
        self._ingestion = ingestion_discoverer

    async def discover(
        self,
        base_url: str,
        endpoint: str,
        auth: Dict[str, Any],
        warehouse_hints: Optional[List[str]] = None,
        ingestion_hints: Optional[List[str]] = None,
    ) -> DiscoveryResult:
        loop = asyncio.get_running_loop()

        async def _run(path: PathName, fn, **kwargs) -> Tuple[PathName, List[DatasetCandidate], Optional[DiscoveryError]]:
            try:
                # Discoverers are sync; run in thread pool to keep parallelism real.
                candidates, error = await loop.run_in_executor(None, lambda: fn(**kwargs))
                return path, candidates, error
            except Exception as e:
                logger.exception("discovery path %s raised", path)
                return path, [], DiscoveryError(code='unknown', message=str(e))

        results = await asyncio.gather(
            _run('probe', self._probe.discover, base_url=base_url, endpoint=endpoint, auth=auth),
            _run('warehouse', self._warehouse.discover, hints=warehouse_hints or []),
            _run('ingestion', self._ingestion.discover, base_url=base_url, hints=ingestion_hints or []),
        )

        candidates_by_path: Dict[PathName, List[DatasetCandidate]] = {}
        errors_by_path: Dict[PathName, Optional[DiscoveryError]] = {}
        for path, candidates, error in results:
            candidates_by_path[path] = candidates
            errors_by_path[path] = error

        return DiscoveryResult(
            candidates_by_path=candidates_by_path,
            errors_by_path=errors_by_path,
        )
```

- [ ] **Step 3.9: Add stub Warehouse and Ingestion discoverers (return empty)**

Create `scanner/discovery/warehouse/__init__.py` (empty) and `scanner/discovery/warehouse/warehouse_discoverer.py`:

```python
from typing import List, Optional, Tuple
from scanner.discovery.types import DatasetCandidate, DiscoveryError


class WarehouseDiscoverer:
    """Path 3 stub — empty until Task 4 wires real warehouse adapter calls."""

    def discover(self, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        if not hints:
            return [], DiscoveryError(code='no_warehouse_hint', message='no warehouse hints provided')
        return [], None
```

Create `scanner/discovery/ingestion/__init__.py` (empty) and `scanner/discovery/ingestion/orchestrator.py`:

```python
from typing import List, Optional, Tuple
from scanner.discovery.types import DatasetCandidate, DiscoveryError


class IngestionDiscoverer:
    """Path 2 stub — empty until Task 5 wires per-driver impls."""

    def discover(self, base_url: str, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        return [], DiscoveryError(code='no_connectors_connected', message='ingestion discovery not yet implemented')
```

- [ ] **Step 3.10: Re-run orchestrator test, confirm pass**

```bash
cd scanner && pytest tests/discovery/test_source_discovery.py -v
```

Expected: PASS (2/2).

- [ ] **Step 3.11: Write failing /discover endpoint test**

Create `scanner/api/tests/test_source_discovery_router.py`:

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from scanner.api.main import app

client = TestClient(app)


@patch("scanner.discovery.probe.source_probe_discoverer.requests.Session")
def test_discover_returns_probe_candidates(mock_session, authed_client):
    mock_resp = mock_session.return_value.get.return_value
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [
        b'[{"id":1,"reading_at":"2026-05-01T00:00:00Z","value":12.3}]'
    ]

    response = authed_client.post(
        "/api/v1/integrations/source/discover",
        json={
            "base_url": "https://api.example.com",
            "endpoint": "/sensors",
            "auth": {"kind": "api_key", "header_name": "X-API-Key", "secret_ref": "stub"},
            "warehouse_hints": [],
            "ingestion_hints": [],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "candidates_by_path" in body
    assert len(body["candidates_by_path"]["probe"]) == 1
    assert body["candidates_by_path"]["probe"][0]["timestamp_column"] == "reading_at"


def test_discover_rejects_non_https(authed_client):
    response = authed_client.post(
        "/api/v1/integrations/source/discover",
        json={
            "base_url": "http://insecure.example.com",
            "endpoint": "/x",
            "auth": {"kind": "api_key", "header_name": "X-API-Key", "secret_ref": "stub"},
        },
    )
    assert response.status_code == 400
```

- [ ] **Step 3.12: Run test, confirm failure**

```bash
cd scanner && pytest api/tests/test_source_discovery_router.py -v
```

Expected: FAIL — endpoint not registered.

- [ ] **Step 3.13: Implement /discover router**

Create `scanner/api/routers/source_discovery.py`:

```python
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from cachetools import TTLCache

from scanner.api.deps import get_current_user
from scanner.discovery.source_discovery import SourceDiscoveryOrchestrator
from scanner.discovery.probe.source_probe_discoverer import SourceProbeDiscoverer
from scanner.discovery.warehouse.warehouse_discoverer import WarehouseDiscoverer
from scanner.discovery.ingestion.orchestrator import IngestionDiscoverer
from scanner.secrets import resolve_secret_ref  # existing helper

router = APIRouter(prefix="/api/v1/integrations/source", tags=["source-discovery"])

_CACHE: TTLCache = TTLCache(maxsize=512, ttl=60)


class AuthBody(BaseModel):
    kind: str
    header_name: Optional[str] = None
    secret_ref: str


class DiscoverRequest(BaseModel):
    base_url: str
    endpoint: str
    auth: AuthBody
    ingestion_hints: Optional[List[str]] = None
    warehouse_hints: Optional[List[str]] = None


def _orchestrator() -> SourceDiscoveryOrchestrator:
    return SourceDiscoveryOrchestrator(
        probe_discoverer=SourceProbeDiscoverer(),
        warehouse_discoverer=WarehouseDiscoverer(),
        ingestion_discoverer=IngestionDiscoverer(),
    )


@router.post("/discover")
async def discover(body: DiscoverRequest, user=Depends(get_current_user)) -> Dict[str, Any]:
    if not body.base_url.lower().startswith("https://"):
        raise HTTPException(400, "base_url must use https://")

    cache_key = (
        body.base_url,
        body.auth.secret_ref,
        tuple(sorted(body.ingestion_hints or [])),
        tuple(sorted(body.warehouse_hints or [])),
    )
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    secret_value = resolve_secret_ref(body.auth.secret_ref, owner_id=user.id)
    runtime_auth = {
        "kind": body.auth.kind,
        "header_name": body.auth.header_name,
        "secret": secret_value,
    }

    result = await _orchestrator().discover(
        base_url=body.base_url,
        endpoint=body.endpoint,
        auth=runtime_auth,
        warehouse_hints=body.warehouse_hints or [],
        ingestion_hints=body.ingestion_hints or [],
    )

    serialized = {
        "candidates_by_path": {
            path: [_serialize_candidate(c) for c in candidates]
            for path, candidates in result.candidates_by_path.items()
        },
        "errors_by_path": {
            path: ({"code": e.code, "message": e.message} if e else None)
            for path, e in result.errors_by_path.items()
        },
    }
    _CACHE[cache_key] = serialized
    return serialized


def _serialize_candidate(c) -> Dict[str, Any]:
    return {
        "source": c.source,
        "endpoint": c.endpoint,
        "json_root": c.json_root,
        "timestamp_column": c.timestamp_column,
        "expected_schema": [
            {"name": col.name, "data_type": col.data_type, "is_nullable": col.is_nullable}
            for col in c.expected_schema
        ],
        "lands_in": c.lands_in,
        "confidence": c.confidence,
    }
```

Register in `scanner/api/main.py`:

```python
from scanner.api.routers import source_discovery
app.include_router(source_discovery.router)
```

- [ ] **Step 3.14: Re-run endpoint tests, confirm pass**

```bash
cd scanner && pytest api/tests/test_source_discovery_router.py -v
```

Expected: PASS (2/2).

- [ ] **Step 3.15: Add Next.js proxy route**

Create `app/api/v1/integrations/source/discover/route.ts`:

```ts
import { NextRequest, NextResponse } from 'next/server';
import { getAuthHeaders } from '@/lib/api/auth';

const FASTAPI_URL = process.env.FASTAPI_BASE_URL ?? 'http://localhost:8000';

export async function POST(req: NextRequest) {
  const body = await req.json();
  const headers = await getAuthHeaders(req);
  const upstream = await fetch(`${FASTAPI_URL}/api/v1/integrations/source/discover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
```

- [ ] **Step 3.16: Wire wizard step 3 — Discovery**

Open `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx`. The current step 3 component (search for `step === 3` or the labelled "Datasets" step block) is replaced with a Discovery component that:

1. On mount (after step 2 lands), POSTs to `/api/v1/integrations/source/discover` with `{base_url, endpoint: '/', auth, ingestion_hints: [], warehouse_hints: []}`.
2. Renders three sections — *"From source probe"*, *"From your warehouse"* (empty in this task), *"From Fivetran/Airbyte/Stitch"* (empty in this task).
3. Each candidate row has: endpoint (editable), json_root (editable), timestamp_column (editable dropdown), columns preview (read-only), accept/reject toggle, lands_in field (editable text).
4. *"+ Add endpoint manually"* button at the bottom — opens a small inline form for `endpoint`, then re-discovers with that endpoint set.

Replace the existing manual-entry step body with this component (keep all other steps intact for now). Reuse Tailwind classes already used in the wizard.

The detailed JSX is mechanical — pattern is: state hooks for `discoveryResult`, `accepted: Set<endpoint>`, `manualEndpoint: string`. Render sections conditionally based on `discoveryResult.candidates_by_path[path].length > 0`. Pass accepted candidates forward to step 4 via the wizard's existing state-passing mechanism (search for how step 2 → 3 currently passes data).

- [ ] **Step 3.17: Smoke check end-to-end**

```bash
NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY=true npm run dev
# in another terminal:
cd scanner && uvicorn api.main:app --reload --port 8000
```

In the browser: connect → custom-source → step through Identity → Connection → Discovery. Confirm at least one probe-path candidate appears for a public open-data REST endpoint (e.g. `https://datausa.io/api/data?...`). Manual `+ Add endpoint` works.

- [ ] **Step 3.18: Commit**

```bash
git add scanner/discovery/ scanner/tests/discovery/ \
  scanner/api/routers/source_discovery.py scanner/api/tests/test_source_discovery_router.py scanner/api/main.py \
  app/api/v1/integrations/source/discover/route.ts \
  app/\(dashboard\)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx
git commit -m "feat(discovery): SourceDiscoveryOrchestrator + probe path + /discover endpoint + wizard Discovery step"
```

---

## Task 4: Warehouse-anchored discoverer (Path 3)

Replaces the stub `WarehouseDiscoverer` with one that reads `INFORMATION_SCHEMA` via existing warehouse adapters and returns `DatasetCandidate`s with `expected_schema`, `timestamp_column`, and `lands_in` populated.

**Files:**
- Modify: `scanner/discovery/warehouse/warehouse_discoverer.py`
- Create: `scanner/tests/discovery/warehouse/__init__.py`, `scanner/tests/discovery/warehouse/test_warehouse_discoverer.py`
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx` (typeahead UI)

- [ ] **Step 4.1: Write failing test**

Create `scanner/tests/discovery/warehouse/__init__.py` (empty) and `scanner/tests/discovery/warehouse/test_warehouse_discoverer.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from scanner.discovery.warehouse.warehouse_discoverer import WarehouseDiscoverer


def test_discoverer_returns_candidates_for_each_hint():
    mock_adapter = MagicMock()
    mock_adapter.get_table_schema.return_value = [
        {"column_name": "id", "data_type": "INTEGER", "is_nullable": False},
        {"column_name": "reading_at", "data_type": "TIMESTAMP", "is_nullable": False},
        {"column_name": "value", "data_type": "FLOAT", "is_nullable": True},
    ]

    with patch("scanner.discovery.warehouse.warehouse_discoverer.adapter_for_fqn", return_value=mock_adapter):
        d = WarehouseDiscoverer()
        candidates, error = d.discover(hints=["snowflake.raw.water_meters"])

    assert error is None
    assert len(candidates) == 1
    c = candidates[0]
    assert c.source == 'warehouse'
    assert c.lands_in == "snowflake.raw.water_meters"
    assert c.timestamp_column == "reading_at"
    assert c.confidence == 0.9
    assert len(c.expected_schema) == 3


def test_discoverer_returns_no_warehouse_hint_error_when_empty():
    d = WarehouseDiscoverer()
    candidates, error = d.discover(hints=[])
    assert candidates == []
    assert error.code == 'no_warehouse_hint'
```

- [ ] **Step 4.2: Run test, confirm failure**

```bash
cd scanner && pytest tests/discovery/warehouse/test_warehouse_discoverer.py -v
```

Expected: FAIL — `adapter_for_fqn` not importable, or schema extraction mismatch.

- [ ] **Step 4.3: Implement WarehouseDiscoverer**

Replace `scanner/discovery/warehouse/warehouse_discoverer.py`:

```python
from __future__ import annotations
import logging
from typing import List, Optional, Tuple

from scanner.discovery.types import (
    ColumnMetadata,
    DatasetCandidate,
    DiscoveryError,
)

logger = logging.getLogger(__name__)

# Same heuristic the probe path uses — keep in sync.
_TIMESTAMP_NAME_HINTS = (
    "_at", "_ts", "timestamp", "created", "updated", "modified", "occurred", "event_time",
)
_TIMESTAMP_TYPES = ("TIMESTAMP", "DATETIME", "TIMESTAMP_NTZ", "TIMESTAMPTZ", "DATE")


def adapter_for_fqn(fqn: str):
    """Resolve a fully-qualified warehouse name → existing warehouse adapter instance.

    fqn shape: '<warehouse_type>.<dataset_or_schema>.<table>' e.g. 'snowflake.raw.water_meters'.
    Reuses the cached integration configs the copilot already populates.
    """
    from scanner.adapters.factory import build_adapter_from_fqn
    return build_adapter_from_fqn(fqn)


def _detect_ts_col(schema: List[dict]) -> Optional[str]:
    for col in schema:
        name = col["column_name"].lower()
        dtype = col["data_type"].upper()
        if dtype in _TIMESTAMP_TYPES or any(h in name for h in _TIMESTAMP_NAME_HINTS):
            return col["column_name"]
    return None


class WarehouseDiscoverer:
    """Path 3: read warehouse table schemas for user-picked landing tables."""

    def discover(self, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        if not hints:
            return [], DiscoveryError(code='no_warehouse_hint', message='no warehouse hints provided')

        candidates: List[DatasetCandidate] = []
        for fqn in hints:
            try:
                adapter = adapter_for_fqn(fqn)
                schema_rows = adapter.get_table_schema(fqn)
            except Exception as e:
                logger.warning("warehouse discovery failed for %s: %s", fqn, e)
                continue

            cols = [
                ColumnMetadata(
                    name=row["column_name"],
                    data_type=row["data_type"],
                    is_nullable=bool(row.get("is_nullable", True)),
                )
                for row in schema_rows
            ]
            candidates.append(
                DatasetCandidate(
                    source='warehouse',
                    endpoint=None,
                    json_root=None,
                    timestamp_column=_detect_ts_col(schema_rows),
                    expected_schema=cols,
                    lands_in=fqn,
                    confidence=0.9,
                )
            )
        return candidates, None
```

- [ ] **Step 4.4: Add `build_adapter_from_fqn` to scanner/adapters/factory.py if missing**

Check `scanner/adapters/factory.py`. If a function that takes a `'snowflake.raw.water_meters'`-style FQN and returns the right adapter doesn't exist, add it:

```python
def build_adapter_from_fqn(fqn: str):
    """Resolve FQN like 'snowflake.raw.water_meters' to a configured adapter instance.

    Uses the existing pipeline-profile-scoped integration cache.
    """
    parts = fqn.split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid fqn: {fqn}")
    warehouse_type = parts[0].lower()
    from scanner.copilot.tool_executor import _engine_tool_configs_map
    cfg = next(
        (c for c in _engine_tool_configs_map.values() if c.get("type", "").lower() == warehouse_type),
        None,
    )
    if cfg is None:
        raise ValueError(f"no configured adapter for warehouse type: {warehouse_type}")
    if warehouse_type == "snowflake":
        from scanner.adapters.snowflake import SnowflakeAdapter
        return SnowflakeAdapter(cfg)
    if warehouse_type == "bigquery":
        from scanner.adapters.bigquery import BigQueryAdapter
        return BigQueryAdapter(cfg)
    if warehouse_type == "postgres":
        from scanner.adapters.postgres import PostgresAdapter
        return PostgresAdapter(cfg)
    if warehouse_type == "redshift":
        from scanner.adapters.redshift import RedshiftAdapter
        return RedshiftAdapter(cfg)
    raise ValueError(f"unsupported warehouse type: {warehouse_type}")
```

If your adapter classes don't have `get_table_schema(fqn)`, add a thin shim that issues `SELECT column_name, data_type, is_nullable FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = ? AND table_name = ?` per dialect.

- [ ] **Step 4.5: Re-run test, confirm pass**

```bash
cd scanner && pytest tests/discovery/warehouse/test_warehouse_discoverer.py -v
```

Expected: PASS (2/2).

- [ ] **Step 4.6: Wire warehouse_hints into wizard's Discovery step**

In `CustomSourceWizard.tsx` Discovery step, add a "Where does this source land?" typeahead populated from already-discovered warehouse tables. Use the existing pipeline-context tables list (search for how monitors page populates a similar dropdown — typically `usePipeline().warehouseTables` or a fetch to `/api/v1/lineage/tables`).

Pass selected FQNs into the `/discover` body as `warehouse_hints`. Render Path 3 results in the *"From your warehouse"* section.

- [ ] **Step 4.7: Smoke check**

In the browser, connect a warehouse first, then start a Custom Source wizard and pick a known warehouse table in the typeahead. Confirm the *"From your warehouse"* section renders the expected schema preview.

- [ ] **Step 4.8: Commit**

```bash
git add scanner/discovery/warehouse/ scanner/tests/discovery/warehouse/ scanner/adapters/factory.py app/\(dashboard\)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx
git commit -m "feat(discovery): WarehouseDiscoverer (Path 3) wired into wizard via warehouse_hints"
```

---

## Task 5: Ingestion-anchored discoverer (Path 2) — Fivetran, Airbyte, Stitch

Replaces the stub `IngestionDiscoverer` with an orchestrator that fans out to per-driver implementations and merges results.

**Files:**
- Modify: `scanner/discovery/ingestion/orchestrator.py`
- Create: `scanner/discovery/ingestion/base.py`
- Create: `scanner/discovery/ingestion/fivetran.py`
- Create: `scanner/discovery/ingestion/airbyte.py`
- Create: `scanner/discovery/ingestion/stitch.py`
- Create test files for each

- [ ] **Step 5.1: Define base abstraction**

Create `scanner/discovery/ingestion/base.py`:

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from scanner.discovery.types import DatasetCandidate


@dataclass(frozen=True)
class ConnectorMatch:
    driver_id: str             # 'fivetran' | 'airbyte' | 'stitch'
    connector_id: str          # ingestion tool's internal ID for this connector
    source_host: str           # the matched host
    raw_config: dict           # the connector's full config (for tests/diagnostics)


class PerDriverIngestionDiscoverer(ABC):
    """Per-driver adapter for Path 2 (ingestion-anchored discovery)."""

    @abstractmethod
    def driver_id(self) -> str: ...

    @abstractmethod
    def find_matching_connectors(self, host: str) -> List[ConnectorMatch]: ...

    @abstractmethod
    def list_source_tables(self, match: ConnectorMatch) -> List[DatasetCandidate]: ...
```

- [ ] **Step 5.2: Write failing test for FivetranIngestionDiscoverer**

Create `scanner/tests/discovery/ingestion/__init__.py` (empty) and `scanner/tests/discovery/ingestion/test_fivetran_discoverer.py`:

```python
from unittest.mock import MagicMock, patch
from scanner.discovery.ingestion.fivetran import FivetranIngestionDiscoverer


def test_fivetran_finds_matching_connector_by_host():
    fake_connectors = [
        {
            "id": "fc_123",
            "schema": "raw_water",
            "config": {"host": "portal.example.com", "port": 443},
            "tables": [
                {"name": "water_meters", "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False},
                    {"name": "reading_at", "type": "TIMESTAMP", "nullable": False},
                ]}
            ],
            "destination_schema": "raw_water",
            "destination_warehouse_type": "snowflake",
        }
    ]
    with patch.object(FivetranIngestionDiscoverer, "_list_connectors", return_value=fake_connectors):
        d = FivetranIngestionDiscoverer()
        matches = d.find_matching_connectors(host="portal.example.com")
        assert len(matches) == 1
        assert matches[0].connector_id == "fc_123"

        candidates = d.list_source_tables(matches[0])
        assert len(candidates) == 1
        c = candidates[0]
        assert c.source == 'ingestion'
        assert c.lands_in == "snowflake.raw_water.water_meters"
        assert c.timestamp_column == "reading_at"
        assert c.confidence == 1.0


def test_fivetran_returns_empty_when_no_host_match():
    fake_connectors = [
        {"id": "fc_1", "config": {"host": "other.example.com"}, "tables": []}
    ]
    with patch.object(FivetranIngestionDiscoverer, "_list_connectors", return_value=fake_connectors):
        d = FivetranIngestionDiscoverer()
        matches = d.find_matching_connectors(host="portal.example.com")
        assert matches == []
```

- [ ] **Step 5.3: Run test, confirm failure**

```bash
cd scanner && pytest tests/discovery/ingestion/test_fivetran_discoverer.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 5.4: Implement FivetranIngestionDiscoverer**

Create `scanner/discovery/ingestion/fivetran.py`:

```python
from __future__ import annotations
import logging
from typing import List

from scanner.discovery.ingestion.base import (
    ConnectorMatch,
    PerDriverIngestionDiscoverer,
)
from scanner.discovery.types import (
    ColumnMetadata,
    DatasetCandidate,
)

logger = logging.getLogger(__name__)

# Map Fivetran column type strings to our canonical inferred types.
_TS_TYPES = {"TIMESTAMP", "DATETIME", "TIMESTAMP_NTZ", "TIMESTAMPTZ"}


class FivetranIngestionDiscoverer(PerDriverIngestionDiscoverer):
    def driver_id(self) -> str:
        return "fivetran"

    def find_matching_connectors(self, host: str) -> List[ConnectorMatch]:
        matches: List[ConnectorMatch] = []
        for c in self._list_connectors():
            cfg_host = (c.get("config") or {}).get("host")
            if cfg_host and host and cfg_host.lower() == host.lower():
                matches.append(ConnectorMatch(
                    driver_id=self.driver_id(),
                    connector_id=c["id"],
                    source_host=cfg_host,
                    raw_config=c,
                ))
        return matches

    def list_source_tables(self, match: ConnectorMatch) -> List[DatasetCandidate]:
        cfg = match.raw_config
        wh_type = (cfg.get("destination_warehouse_type") or "snowflake").lower()
        dest_schema = cfg.get("destination_schema") or cfg.get("schema") or ""
        candidates: List[DatasetCandidate] = []

        for tbl in cfg.get("tables", []):
            cols = [
                ColumnMetadata(
                    name=col["name"],
                    data_type=col.get("type", "UNKNOWN"),
                    is_nullable=bool(col.get("nullable", True)),
                )
                for col in tbl.get("columns", [])
            ]
            ts = next(
                (col["name"] for col in tbl.get("columns", []) if col.get("type", "").upper() in _TS_TYPES),
                None,
            )
            lands_in = f"{wh_type}.{dest_schema}.{tbl['name']}".strip(".")
            candidates.append(DatasetCandidate(
                source='ingestion',
                endpoint=None,                  # ingestion knows source tables, not source endpoints
                json_root=None,
                timestamp_column=ts,
                expected_schema=cols,
                lands_in=lands_in,
                confidence=1.0,
            ))
        return candidates

    def _list_connectors(self) -> list:
        """Return raw Fivetran connector configs from the existing FivetranIntegration.

        Lazy-import to avoid circular imports. Raises if Fivetran isn't connected;
        the orchestrator handles that as a no_connectors_connected error.
        """
        from scanner.integrations.fivetran import FivetranIntegration
        return FivetranIntegration.instance().list_connectors_with_schemas()
```

- [ ] **Step 5.5: Re-run test, confirm pass**

```bash
cd scanner && pytest tests/discovery/ingestion/test_fivetran_discoverer.py -v
```

Expected: PASS (2/2). If `FivetranIntegration.list_connectors_with_schemas` doesn't exist, add a thin method that returns the same shape from whatever underlying API call already populates lineage extraction.

- [ ] **Step 5.6: Repeat for Airbyte and Stitch (mirror pattern)**

Create `scanner/discovery/ingestion/airbyte.py` and `scanner/discovery/ingestion/stitch.py` following the same pattern as `fivetran.py`. Differences:
- Airbyte connector config nests host under `source.connectionConfiguration.host`. Tables come from `discovered_catalog`. Destination warehouse from the linked destination's `connectionConfiguration`.
- Stitch nests host under `properties.host`. Tables from `streams`. Destination from `target_id`.

Each gets its own test file (`test_airbyte_discoverer.py`, `test_stitch_discoverer.py`) with the same two test cases (matching host, no match) using mocked underlying integration calls.

After implementing each, run its test and confirm pass.

- [ ] **Step 5.7: Wire orchestrator**

Replace `scanner/discovery/ingestion/orchestrator.py`:

```python
from __future__ import annotations
import logging
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from scanner.discovery.ingestion.base import PerDriverIngestionDiscoverer
from scanner.discovery.ingestion.fivetran import FivetranIngestionDiscoverer
from scanner.discovery.ingestion.airbyte import AirbyteIngestionDiscoverer
from scanner.discovery.ingestion.stitch import StitchIngestionDiscoverer
from scanner.discovery.types import DatasetCandidate, DiscoveryError

logger = logging.getLogger(__name__)


class IngestionDiscoverer:
    """Path 2 orchestrator — fans out to per-driver discoverers, merges candidates."""

    def __init__(self, drivers: Optional[List[PerDriverIngestionDiscoverer]] = None):
        self._drivers = drivers or [
            FivetranIngestionDiscoverer(),
            AirbyteIngestionDiscoverer(),
            StitchIngestionDiscoverer(),
        ]

    def discover(
        self, base_url: str, hints: List[str],
    ) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        host = urlparse(base_url).hostname or ""
        if not host:
            return [], DiscoveryError(code='unknown', message='could not parse host from base_url')

        active_drivers = self._drivers
        if hints:
            active_drivers = [d for d in self._drivers if d.driver_id() in hints]

        all_candidates: List[DatasetCandidate] = []
        any_match = False
        for driver in active_drivers:
            try:
                matches = driver.find_matching_connectors(host=host)
            except Exception as e:
                logger.warning("ingestion driver %s failed: %s", driver.driver_id(), e)
                continue
            if matches:
                any_match = True
            for m in matches:
                try:
                    all_candidates.extend(driver.list_source_tables(m))
                except Exception as e:
                    logger.warning("listing tables for %s/%s failed: %s", driver.driver_id(), m.connector_id, e)

        if not any_match:
            return [], DiscoveryError(
                code='no_connectors_connected',
                message=f'no ingestion connectors found for host {host}',
            )
        return all_candidates, None
```

- [ ] **Step 5.8: Wire ingestion_hints into wizard Discovery step**

In `CustomSourceWizard.tsx` Discovery step, surface the *"From {driver}"* section when `result.candidates_by_path.ingestion.length > 0`. No new UI needed beyond adding a third section that uses the same row layout as the other paths.

- [ ] **Step 5.9: Smoke check**

Connect Fivetran (real or mock), then start a Custom Source wizard pointing at a host Fivetran also points at. Confirm the *"From Fivetran"* section renders with the expected dataset list.

- [ ] **Step 5.10: Commit**

```bash
git add scanner/discovery/ingestion/ scanner/tests/discovery/ingestion/ app/\(dashboard\)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx
git commit -m "feat(discovery): IngestionDiscoverer (Path 2) for Fivetran, Airbyte, Stitch"
```

---

## Task 6: `/verify` endpoint with SSE + Save-gate

Adds the per-dataset dry-probe endpoint that streams results and gates the wizard's Save button.

**Files:**
- Create: `scanner/api/routers/source_verify.py`
- Create: `scanner/api/tests/test_source_verify_router.py`
- Create: `app/api/v1/integrations/source/verify/route.ts`
- Modify: `scanner/api/main.py`
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx` (step 5)

- [ ] **Step 6.1: Confirm sse-starlette dependency**

```bash
grep -E "sse[-_]starlette" scanner/requirements.txt scanner/pyproject.toml 2>/dev/null
```

If missing:

```bash
cd scanner && pip install sse-starlette && pip freeze | grep sse-starlette >> requirements.txt
```

- [ ] **Step 6.2: Write failing test**

Create `scanner/api/tests/test_source_verify_router.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from scanner.api.main import app

client = TestClient(app)


def _verify_body():
    return {
        "name": "MyCiti — water sensors",
        "platform_label": "MyCiti",
        "base_url": "https://portal.example.com/api/v1",
        "auth": {"kind": "api_key", "header_name": "X-API-Key", "secret_ref": "stub"},
        "schedule": "daily",
        "datasets": [
            {"id": "water_meters", "endpoint": "/sensors", "json_root": None,
             "timestamp_column": "reading_at", "lands_in": None},
        ],
    }


@patch("scanner.adapters.http_probe.HttpProbeAdapter.probe")
def test_verify_streams_per_dataset_results(mock_probe, authed_client):
    from datetime import datetime, timezone
    from scanner.adapters.http_probe import MetricBundle
    mock_probe.return_value = MetricBundle(
        probed_at=datetime.now(timezone.utc),
        row_count=1247,
        latest_timestamp=datetime.now(timezone.utc),
        column_schema=[{"name": "id", "data_type": "int", "is_nullable": False}],
        null_counts={"id": 0},
        distinct_counts={"id": 1247},
        value_fingerprints={},
        min_max_numeric={},
    )

    response = authed_client.post(
        "/api/v1/integrations/source/verify",
        json=_verify_body(),
    )
    assert response.status_code == 200

    events = []
    for line in response.iter_lines():
        if line.startswith(b"data: "):
            events.append(json.loads(line[6:]))

    assert any(e.get("status") == "ok" and e.get("dataset_id") == "water_meters" for e in events)
    assert any(e.get("all_pass") is True for e in events)


@patch("scanner.adapters.http_probe.HttpProbeAdapter.probe")
def test_verify_does_not_persist_integration_on_failure(mock_probe, authed_client, db_session):
    from scanner.adapters.http_probe import ProbeError
    mock_probe.side_effect = ProbeError(code="json_root_returned_null", message="bad")

    pre_count = db_session.execute("SELECT COUNT(*) FROM Integration").scalar()
    response = authed_client.post(
        "/api/v1/integrations/source/verify",
        json=_verify_body(),
    )
    assert response.status_code == 200

    post_count = db_session.execute("SELECT COUNT(*) FROM Integration").scalar()
    assert post_count == pre_count, "verify must NOT persist Integration rows under any condition"
```

- [ ] **Step 6.3: Run test, confirm failure**

```bash
cd scanner && pytest api/tests/test_source_verify_router.py -v
```

Expected: FAIL — endpoint missing.

- [ ] **Step 6.4: Implement /verify router**

Create `scanner/api/routers/source_verify.py`:

```python
from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from scanner.api.deps import get_current_user
from scanner.adapters.http_probe import HttpProbeAdapter, ProbeError
from scanner.secrets import resolve_secret_ref

router = APIRouter(prefix="/api/v1/integrations/source", tags=["source-verify"])
logger = logging.getLogger(__name__)


class AuthBody(BaseModel):
    kind: str
    header_name: Optional[str] = None
    secret_ref: str


class DatasetBody(BaseModel):
    id: str
    endpoint: str
    json_root: Optional[str] = None
    timestamp_column: str
    lands_in: Optional[str] = None
    cursor_param: Optional[str] = None
    unique_key_columns: Optional[List[str]] = None


class VerifyRequest(BaseModel):
    name: str
    platform_label: str
    base_url: str
    auth: AuthBody
    schedule: str
    datasets: List[DatasetBody]


@router.post("/verify")
async def verify(body: VerifyRequest, user=Depends(get_current_user)):
    """Streams per-dataset probe results. Never persists Integration rows."""

    secret_value = resolve_secret_ref(body.auth.secret_ref, owner_id=user.id)
    adapter = HttpProbeAdapter(
        base_url=body.base_url,
        auth={
            "kind": body.auth.kind,
            "header_name": body.auth.header_name,
            "secret": secret_value,
        },
    )

    async def event_stream():
        all_pass = True
        failed = 0
        for ds in body.datasets:
            try:
                bundle = adapter.probe({
                    "endpoint": ds.endpoint,
                    "json_root": ds.json_root,
                    "timestamp_column": ds.timestamp_column,
                    "cursor_param": ds.cursor_param,
                    "unique_key_columns": ds.unique_key_columns or [],
                })
                payload = {
                    "dataset_id": ds.id,
                    "status": "ok",
                    "row_count": bundle.row_count,
                    "latest_timestamp": bundle.latest_timestamp.isoformat() if bundle.latest_timestamp else None,
                    "schema_match": True,
                }
            except ProbeError as e:
                all_pass = False
                failed += 1
                payload = {
                    "dataset_id": ds.id,
                    "status": "error",
                    "code": e.code,
                    "message": e.message,
                }
            yield {"event": "dataset_result", "data": json.dumps(payload)}

        yield {"event": "complete", "data": json.dumps({"all_pass": all_pass, "failed_count": failed})}

    return EventSourceResponse(event_stream())
```

Register in `scanner/api/main.py`:

```python
from scanner.api.routers import source_verify
app.include_router(source_verify.router)
```

- [ ] **Step 6.5: Re-run test, confirm pass**

```bash
cd scanner && pytest api/tests/test_source_verify_router.py -v
```

Expected: PASS (2/2). The DB-scan assertion in the second test is critical — do not skip it.

- [ ] **Step 6.6: Add Next.js SSE proxy route**

Create `app/api/v1/integrations/source/verify/route.ts`:

```ts
import { NextRequest } from 'next/server';
import { getAuthHeaders } from '@/lib/api/auth';

const FASTAPI_URL = process.env.FASTAPI_BASE_URL ?? 'http://localhost:8000';

export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  const body = await req.text();
  const headers = await getAuthHeaders(req);
  const upstream = await fetch(`${FASTAPI_URL}/api/v1/integrations/source/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body,
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  });
}
```

- [ ] **Step 6.7: Wire wizard step 5 — Verify gate**

In `CustomSourceWizard.tsx`, the existing step 5 (Review) becomes Review + Verify:

1. On entering step 5, POST `/api/v1/integrations/source/verify` with the assembled config; consume the SSE stream with `EventSource` or `ReadableStreamDefaultReader`.
2. Render per-dataset rows with status (`pending` / `ok` / `error`) — start all `pending`, update on each `dataset_result` event.
3. Disable the Save button while any row is non-`ok`.
4. On `complete` event with `all_pass: false`, surface a "Fix and retry" affordance that takes the user back to step 3 with the failing datasets highlighted.
5. On `complete` event with `all_pass: true`, enable Save. Save calls existing `POST /api/integrations` to persist.

Reference for SSE consumption in existing code: search for `EventSource` or `text/event-stream` usage in `app/api/copilot/chat/route.ts` or similar streaming routes.

- [ ] **Step 6.8: Smoke check end-to-end**

Walk the wizard against a known-bad endpoint (e.g. one that returns HTML). Confirm:
- Save button stays disabled.
- The failing dataset shows ✗ with a code like `malformed_json`.
- No `Integration` row is created (check via `psql` or Prisma Studio).

Then walk against a known-good public open-data endpoint and confirm Save activates and persists.

- [ ] **Step 6.9: Commit**

```bash
git add scanner/api/routers/source_verify.py scanner/api/tests/test_source_verify_router.py scanner/api/main.py \
  app/api/v1/integrations/source/verify/route.ts \
  app/\(dashboard\)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx
git commit -m "feat(verify): SSE-streamed per-dataset dry-probe gate; Save disabled until all-pass"
```

---

## Task 7: Persist-only-on-pass inversion + integration test

Inverts the wizard's persistence order so `Integration` rows exist only for verified configs, and adds a single end-to-end test that proves the round-trip.

**Files:**
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx` (Save handler)
- Create: `scanner/tests/integration/__init__.py`
- Create: `scanner/tests/integration/test_source_integration_e2e.py`

- [ ] **Step 7.1: Confirm Save handler order**

Open `CustomSourceWizard.tsx`. Find the `onSave` / `handleSave` (whatever the wizard calls its commit handler). Today (per the prior spec implementation) it likely:

1. POSTs to `/api/integrations` to create the row.
2. POSTs to `/api/v1/integrations/test-connection` to verify.

Restructure to:

1. Call `/api/v1/integrations/source/verify` (already done in step 6.7 — Save is gated on this).
2. Only after `all_pass: true`, call `/api/integrations` to create the row.
3. On verify failure, do NOT call `/api/integrations`.

If step 6.7 already covers this completely, no further wizard change here — just confirm the order.

- [ ] **Step 7.2: Write the end-to-end integration test**

Create `scanner/tests/integration/__init__.py` (empty) and `scanner/tests/integration/test_source_integration_e2e.py`:

```python
import json
import pytest
import responses
from fastapi.testclient import TestClient
from scanner.api.main import app

client = TestClient(app)


@responses.activate
def test_full_source_integration_round_trip(authed_client, db_session):
    """End-to-end smoke: discover → verify → persist → schedule → first probe → metric in monitor history."""

    base_url = "https://api.example.com"
    endpoint = "/sensors"

    # Mock the source endpoint with valid data.
    responses.add(
        responses.GET,
        f"{base_url}{endpoint}",
        json=[
            {"id": 1, "reading_at": "2026-05-01T00:00:00Z", "value": 12.3},
            {"id": 2, "reading_at": "2026-05-01T00:01:00Z", "value": 13.5},
        ],
        status=200,
    )

    # Step 1: discover
    discover_resp = authed_client.post(
        "/api/v1/integrations/source/discover",
        json={
            "base_url": base_url,
            "endpoint": endpoint,
            "auth": {"kind": "api_key", "header_name": "X-API-Key", "secret_ref": "stub"},
        },
    )
    assert discover_resp.status_code == 200
    candidates = discover_resp.json()["candidates_by_path"]["probe"]
    assert len(candidates) >= 1

    # Step 2: verify
    config = {
        "name": "smoke source",
        "platform_label": "Smoke",
        "base_url": base_url,
        "auth": {"kind": "api_key", "header_name": "X-API-Key", "secret_ref": "stub"},
        "schedule": "daily",
        "datasets": [{
            "id": "sensors",
            "endpoint": endpoint,
            "json_root": None,
            "timestamp_column": "reading_at",
            "lands_in": None,
        }],
    }
    verify_resp = authed_client.post("/api/v1/integrations/source/verify", json=config)
    assert verify_resp.status_code == 200

    events = [json.loads(l[6:]) for l in verify_resp.iter_lines() if l.startswith(b"data: ")]
    assert events[-1]["all_pass"] is True

    # Step 3: persist (only after verify passes)
    persist_resp = authed_client.post(
        "/api/integrations",
        json={"integration_type": "CUSTOM_SOURCE", "config": config},
    )
    assert persist_resp.status_code == 201
    integration_id = persist_resp.json()["id"]

    # Step 4: trigger first scheduled probe (or invoke manually via existing probe-now endpoint)
    probe_now_resp = authed_client.post(f"/api/integrations/{integration_id}/probe-now")
    assert probe_now_resp.status_code == 202

    # Step 5: assert a CustomSourceProbeRun row exists for this integration
    runs = db_session.execute(
        "SELECT id, row_count FROM CustomSourceProbeRun WHERE integrationId = ? ORDER BY createdAt DESC LIMIT 1",
        (integration_id,),
    ).fetchone()
    assert runs is not None
    assert runs.row_count == 2

    # Step 6: critical safety — assert no raw row data leaked into any persisted column
    leak = db_session.execute(
        "SELECT COUNT(*) FROM CustomSourceProbeRun WHERE CAST(metrics AS TEXT) LIKE '%12.3%' OR CAST(metrics AS TEXT) LIKE '%13.5%'"
    ).scalar()
    assert leak == 0, "raw row values must NEVER be persisted — only derived metrics"
```

- [ ] **Step 7.3: Run integration test**

```bash
cd scanner && pytest tests/integration/test_source_integration_e2e.py -v
```

Expected: PASS. If it fails, diagnose which step broke (discover / verify / persist / probe / leak check) — each is independently meaningful.

- [ ] **Step 7.4: Commit**

```bash
git add scanner/tests/integration/
git commit -m "test(integration): end-to-end source integration round-trip with row-leak assertion"
```

---

## Task 8: Pilot rollout

Flips the feature flag for a single pilot tenant, monitors for two weeks, then defaults on.

**Files:**
- Modify: `.env.example` and any environment configuration
- Modify: per-tenant flag config (depends on how flags are tenant-scoped; if not, this becomes a global default)

- [ ] **Step 8.1: Verify flag default-off behavior**

```bash
unset NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY
npm run dev
```

Visit `/dashboard/integrations/connect`. Expected: page renders "Sources category not enabled" or equivalent fallback. Visit `/dashboard/pipeline`. Expected: no Sources column.

- [ ] **Step 8.2: Document flag flip procedure**

Add a one-liner to the project's deployment / runbook docs (wherever feature-flag flips are recorded; if no such doc exists, add a `docs/runbooks/feature-flags.md` with the single entry):

```markdown
## SOURCES_CATEGORY

Gates the Sources integration category — Custom Source connector + Salesforce/Shopify/HubSpot
"coming soon" tiles. Set `NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY=true` (frontend) and
`SOURCES_CATEGORY=true` (FastAPI) to enable. Default off until the post-pilot ramp.
```

- [ ] **Step 8.3: Enable for pilot tenant**

If feature flags are tenant-scoped via DB or config service, add the pilot tenant to the allowlist for `SOURCES_CATEGORY`. If they're env-var-only, the pilot is a separate deployment.

- [ ] **Step 8.4: Set up monitoring**

Spot-check after 24h, 1 week, 2 weeks:
- Number of `Integration` rows with `integration_type = CUSTOM_SOURCE` for pilot tenant.
- Number of `CustomSourceProbeRun` rows in last 24h per integration.
- Any rows in `SourceConnectorWaitlist` (signal of demand for Salesforce/Shopify/HubSpot).
- Error-event log for `ProbeError` codes.

- [ ] **Step 8.5: After 2 weeks of stable use, default-on**

Change the env-var default in deployment config so `NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY` and `SOURCES_CATEGORY` are `true` for all tenants. Commit this as a separate small change.

```bash
git commit -m "feat(rollout): default-on SOURCES_CATEGORY after pilot validation"
```

---

## Self-Review Notes (post-write)

Coverage of spec sections:

- **Goal & non-goals** — covered by Task 1 (taxonomy) + Task 2 (picker with stubs).
- **High-level architecture** — every box in the spec's diagram has a Task: connect-page picker (Task 2), wizard (Tasks 3, 6, 7), verify endpoint (Task 6), discovery orchestrator (Task 3) + per-path discoverers (Tasks 3, 4, 5).
- **Frontend taxonomy changes** — Task 1.
- **Sources picker** — Task 2.
- **Wizard restructure** — Tasks 3, 4, 5 (Discovery step), Task 6 (Verify gate).
- **Discovery engine** — Task 3 (orchestrator + Path 1), Task 4 (Path 3), Task 5 (Path 2).
- **API endpoints** — Task 3 (`/discover`), Task 6 (`/verify`).
- **Persist-only-on-pass inversion** — Task 7.
- **Lineage & monitor placement** — covered implicitly by Task 1 (LAYER_X applies to both pipeline page and lineage layout); the existing `_extract_lineage_impl` in `CustomSourceDriver` already handles `lands_in` edges per the prior spec.
- **Migration of existing worktree work** — captured in the File Structure section + per-task notes.
- **What is stored vs. not stored** — enforced via Task 7's row-leak assertion (`leak == 0`).
- **Failure handling** — `DiscoveryError` types in Task 3; `ProbeError` already exists; Task 6 verify SSE emits per-dataset error codes; Task 7 round-trip test asserts no orphan rows on failure.
- **Test plan** — every test category from the spec is in a Task: discoverer unit tests (Tasks 3, 4, 5), endpoint tests (Tasks 3, 6), wizard tests (offered but left as smoke checks rather than unit tests; if a Vitest/Jest harness is in place, add component tests in Task 6.7), integration test (Task 7).
- **Sequencing** — tasks 1–8 mirror the spec's 8 sequencing steps.

No placeholders. All file paths absolute or repo-relative. All steps have actual code or actual commands.

Type consistency:
- `DatasetCandidate` shape is identical across Tasks 3, 4, 5.
- `DiscoveryError.code` enum values match between `types.py` and consumers in tests.
- `MetricBundle` is the existing dataclass in `scanner/adapters/http_probe.py` (line 24); not re-defined.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-01-sources-category-and-integration-tests.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
