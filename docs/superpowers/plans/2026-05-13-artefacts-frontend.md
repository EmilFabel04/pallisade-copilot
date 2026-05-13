# Agentic Artefacts — Frontend (Slices 4-5) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `/dashboard/artifacts` surface as a polymorphic list over the new typed-artefact schema (slice 4) and add the new `/dashboard/artifacts/[artifactId]` per-artefact view with Continue + embedded scoped chat (slice 5). Gated by the existing `ff_artefacts_v2` flag.

**Architecture:** A single `ArtifactListCard` renders any artefact and dispatches to a per-kind preview component. v1 ships `PRArtifactPreview` + `GenericArtifactPreview`; Monitor preview lands in the next plan (slice 6). The detail page has three stacked sections — header, kind-specific body (`PRArtifactBody` / `GenericArtifactBody`), and an embedded chat panel scoped to `artefact.agentSessionId` (reusing `useStreamingChat` + the assistant page's message renderer pattern). The Continue button on list cards routes here.

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind 4, Prisma client types (`ArtifactKind`, `ArtifactStatus`, `ArtifactRisk` from `@prisma/client`), the existing `useStreamingChat` hook.

**Spec reference:** `docs/superpowers/specs/2026-05-13-agentic-artefacts-design.md` §8.2, §8.3, §9.

**Previous plan:** `docs/superpowers/plans/2026-05-13-artefacts-backend-foundation.md` (slices 1-3, already shipped to main as of commit `f9d0a65`).

---

## File Structure

**Created:**
- `lib/artefacts/kinds.ts` — kind metadata (label, icon class, color) for `ArtifactKind`
- `hooks/useArtefacts.ts` — list-page hook (fetch + filters + pagination)
- `hooks/useArtefact.ts` — single-artefact hook (fetch + actions)
- `hooks/useArtefactSession.ts` — fetch a session's messages for the embedded panel
- `components/artefacts/ArtefactListCard.tsx` — single list-item shell
- `components/artefacts/ArtefactStatusBadge.tsx` — status pill
- `components/artefacts/ArtefactKindBadge.tsx` — kind+subtype pill
- `components/artefacts/ArtefactRiskBadge.tsx` — risk pill
- `components/artefacts/ArtefactFilters.tsx` — search + kind/status/source filter bar
- `components/artefacts/ArtefactRowActions.tsx` — inline action menu (pin/archive/delete/continue/open-source-session)
- `components/artefacts/previews/PRArtifactPreview.tsx` — PR_CHANGE list preview
- `components/artefacts/previews/GenericArtifactPreview.tsx` — fallback list preview
- `components/artefacts/previews/index.ts` — preview dispatcher
- `components/artefacts/bodies/PRArtifactBody.tsx` — PR_CHANGE detail body
- `components/artefacts/bodies/GenericArtifactBody.tsx` — fallback detail body
- `components/artefacts/bodies/index.ts` — body dispatcher
- `components/artefacts/ArtefactHeader.tsx` — detail-page header
- `components/artefacts/EmbeddedAgentSession.tsx` — scoped chat panel
- `app/(dashboard)/dashboard/artifacts/[artifactId]/page.tsx` — per-artefact route
- `types/artefact-row.ts` — `ArtefactRow` type (the API response shape)
- `app/api/copilot/sessions/[sessionId]/messages/route.ts` — read-only message list endpoint for the embedded panel (if a suitable one doesn't already exist — see Task 11)

**Modified:**
- `app/(dashboard)/dashboard/artifacts/page.tsx` — replace the stub with the polymorphic list (under the `ff_artefacts_v2` gate)

---

## Conventions used in this plan

- All UI uses the existing CSS-var palette: `var(--surface)`, `var(--surface-inset)`, `var(--text)`, `var(--muted)`, `var(--border)`, `var(--hover-bg)`. Don't invent new variables.
- New artefact components live under `components/artefacts/` (the empty parent that already holds `MessageActionMenu.tsx`). Do not put them in `components/copilot/artifacts/` — that path is reserved for chat-side cards.
- Time formatting uses the existing `formatRelativeTime` if present (search `lib/`); if not, format inline with `Intl.RelativeTimeFormat`.
- API call surface for the list: `GET /api/artifacts?kind=...&status=...&source=...&search=...&pinned=true&limit=50&offset=0`.
- The Prisma client enums (`ArtifactKind`, `ArtifactStatus`) are imported from `@prisma/client`. The TS payload union is in `types/artifact.ts`.

---

### Task 1: Kind metadata helper

A single source of truth for how each `ArtifactKind` is labelled and coloured. Used by badges, filter chips, and the kind dispatcher.

**Files:**
- Create: `lib/artefacts/kinds.ts`

- [ ] **Step 1: Write the helper**

```typescript
// lib/artefacts/kinds.ts
import type { ArtifactKind } from '@prisma/client';

export type KindMeta = {
  label: string;
  group: 'pr-flow' | 'monitor' | 'data' | 'orchestration' | 'governance' | 'doc';
  /** Tailwind text color class — anchors the badge tint. */
  tint: string;
};

export const KIND_META: Record<ArtifactKind, KindMeta> = {
  PR_CHANGE:           { label: 'Pull Request',         group: 'pr-flow',       tint: 'text-emerald-400' },
  DBT_CORE_CHANGE:     { label: 'dbt Change',           group: 'pr-flow',       tint: 'text-orange-400'  },
  DBT_CLOUD_CHANGE:    { label: 'dbt Cloud',            group: 'pr-flow',       tint: 'text-orange-300'  },
  SCHEMA_CHANGE:       { label: 'Schema Change',        group: 'data',          tint: 'text-sky-400'     },
  DAG:                 { label: 'DAG',                  group: 'orchestration', tint: 'text-indigo-400'  },
  INGESTION_CONNECTOR: { label: 'Connector',            group: 'orchestration', tint: 'text-cyan-400'    },
  MONITOR:             { label: 'Monitor',              group: 'monitor',       tint: 'text-violet-400'  },
  WATCH:               { label: 'Watch',                group: 'monitor',       tint: 'text-violet-300'  },
  INCIDENT:            { label: 'Incident',             group: 'governance',    tint: 'text-rose-400'    },
  TICKET:              { label: 'Ticket',               group: 'governance',    tint: 'text-amber-400'   },
  NOTIFICATION_RULE:   { label: 'Notification Rule',    group: 'governance',    tint: 'text-yellow-400'  },
  WAREHOUSE_QUERY:     { label: 'Warehouse Query',      group: 'data',          tint: 'text-blue-400'    },
  BI_ASSET:            { label: 'BI Asset',             group: 'data',          tint: 'text-fuchsia-400' },
  STORAGE_OBJECT:      { label: 'Storage Object',       group: 'data',          tint: 'text-teal-400'    },
  SERVER_ACTION:       { label: 'Server Action',        group: 'orchestration', tint: 'text-slate-300'   },
  DOCUMENT:            { label: 'Document',             group: 'doc',           tint: 'text-zinc-300'    },
};

export const ALL_KINDS = Object.keys(KIND_META) as ArtifactKind[];

export function kindLabel(kind: ArtifactKind): string {
  return KIND_META[kind].label;
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'lib/artefacts|error TS' | head`
Expected: no errors mentioning `lib/artefacts/kinds.ts`.

- [ ] **Step 3: Commit**

```bash
git add lib/artefacts/kinds.ts
git commit -m "feat(artefacts): kind metadata table"
```

---

### Task 2: `ArtefactRow` type — the API response shape

Centralise the shape returned by `GET /api/artifacts` so list/detail components share one source of truth and we don't `any` our way through props.

**Files:**
- Create: `types/artefact-row.ts`

- [ ] **Step 1: Write the type**

`GET /api/artifacts` (see `app/api/artifacts/route.ts:60`) returns rows produced by `prisma.artifact.findMany` with `include: { sourceSession, agentSession, integration }`. Mirror that:

```typescript
// types/artefact-row.ts
import type { ArtifactKind, ArtifactRisk, ArtifactStatus } from '@prisma/client';
import type { ArtifactPayload } from './artifact';

export interface ArtefactRow {
  id: string;
  kind: ArtifactKind;
  subtype: string | null;
  status: ArtifactStatus;
  title: string;
  summary: string | null;
  payload: ArtifactPayload;
  externalRef: Record<string, unknown> | null;
  riskLevel: ArtifactRisk | null;
  rollbackHint: string | null;
  tags: string[];
  isPinned: boolean;
  isSaved: boolean;
  metadata: Record<string, unknown> | null;
  agentSessionId: string | null;
  sourceSessionId: string | null;
  integrationId: string | null;
  agentRunId: string | null;
  toolCallId: string | null;
  createdAt: string;
  updatedAt: string;
  appliedAt: string | null;

  sourceSession: { id: string; title: string | null } | null;
  agentSession: { id: string; title: string | null } | null;
  integration: { id: string; type: string } | null;
}

export interface ArtefactListResponse {
  artifacts: ArtefactRow[];
  pagination: { total: number; limit: number; offset: number; hasMore: boolean };
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'types/artefact-row|error TS' | head`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add types/artefact-row.ts
git commit -m "feat(artefacts): add ArtefactRow API response type"
```

---

### Task 3: `useArtefacts` list hook

**Files:**
- Create: `hooks/useArtefacts.ts`

- [ ] **Step 1: Write the hook**

```typescript
// hooks/useArtefacts.ts
'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ArtifactKind, ArtifactStatus } from '@prisma/client';
import type { ArtefactListResponse, ArtefactRow } from '@/types/artefact-row';

export type ArtefactSourceFilter = 'all' | 'agent' | 'user';

export interface UseArtefactsParams {
  search?: string;
  kinds?: ArtifactKind[];
  statuses?: ArtifactStatus[];
  source?: ArtefactSourceFilter;
  pinnedOnly?: boolean;
}

export interface UseArtefactsResult {
  artefacts: ArtefactRow[];
  total: number;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

function buildQuery(p: UseArtefactsParams): string {
  const q = new URLSearchParams();
  if (p.search) q.set('search', p.search);
  if (p.kinds && p.kinds.length) q.set('kind', p.kinds.join(','));
  if (p.statuses && p.statuses.length) q.set('status', p.statuses.join(','));
  if (p.source && p.source !== 'all') q.set('source', p.source);
  if (p.pinnedOnly) q.set('pinned', 'true');
  q.set('limit', '100');
  return q.toString();
}

export function useArtefacts(params: UseArtefactsParams): UseArtefactsResult {
  const [artefacts, setArtefacts] = useState<ArtefactRow[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const queryString = buildQuery(params);

  const fetchList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/artifacts?${queryString}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ArtefactListResponse = await res.json();
      setArtefacts(data.artifacts ?? []);
      setTotal(data.pagination?.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load artefacts');
    } finally {
      setIsLoading(false);
    }
  }, [queryString]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  return { artefacts, total, isLoading, error, refresh: fetchList };
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'hooks/useArtefacts|error TS' | head`
Expected: no errors mentioning `hooks/useArtefacts.ts`.

- [ ] **Step 3: Commit**

```bash
git add hooks/useArtefacts.ts
git commit -m "feat(artefacts): useArtefacts list hook"
```

---

### Task 4: Badge primitives

Three small components shared by the list card and detail header.

**Files:**
- Create: `components/artefacts/ArtefactStatusBadge.tsx`
- Create: `components/artefacts/ArtefactKindBadge.tsx`
- Create: `components/artefacts/ArtefactRiskBadge.tsx`

- [ ] **Step 1: Status badge**

```tsx
// components/artefacts/ArtefactStatusBadge.tsx
import type { ArtifactStatus } from '@prisma/client';

const TINT: Record<ArtifactStatus, { fg: string; bg: string }> = {
  draft:    { fg: '#9ca3af', bg: 'rgba(156, 163, 175, 0.15)' },
  proposed: { fg: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  approved: { fg: '#60a5fa', bg: 'rgba(96, 165, 250, 0.15)' },
  applied:  { fg: '#34d399', bg: 'rgba(52, 211, 153, 0.15)' },
  rejected: { fg: '#f87171', bg: 'rgba(248, 113, 113, 0.15)' },
  failed:   { fg: '#f87171', bg: 'rgba(248, 113, 113, 0.18)' },
  archived: { fg: '#6b7280', bg: 'rgba(107, 114, 128, 0.15)' },
  open:     { fg: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  resolved: { fg: '#34d399', bg: 'rgba(52, 211, 153, 0.15)' },
};

export function ArtefactStatusBadge({ status }: { status: ArtifactStatus }) {
  const { fg, bg } = TINT[status];
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium uppercase tracking-wide"
      style={{ color: fg, backgroundColor: bg }}
    >
      {status}
    </span>
  );
}
```

- [ ] **Step 2: Kind badge**

```tsx
// components/artefacts/ArtefactKindBadge.tsx
import type { ArtifactKind } from '@prisma/client';
import { KIND_META } from '@/lib/artefacts/kinds';

export function ArtefactKindBadge({ kind, subtype }: { kind: ArtifactKind; subtype?: string | null }) {
  const meta = KIND_META[kind];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ${meta.tint}`}
      style={{ backgroundColor: 'var(--hover-bg)' }}
    >
      {meta.label}
      {subtype ? <span className="text-[var(--muted)] font-normal">· {subtype}</span> : null}
    </span>
  );
}
```

- [ ] **Step 3: Risk badge**

```tsx
// components/artefacts/ArtefactRiskBadge.tsx
import type { ArtifactRisk } from '@prisma/client';

const TINT: Record<ArtifactRisk, { fg: string; bg: string }> = {
  LOW:    { fg: '#34d399', bg: 'rgba(52, 211, 153, 0.12)' },
  MEDIUM: { fg: '#fbbf24', bg: 'rgba(251, 191, 36, 0.12)' },
  HIGH:   { fg: '#f87171', bg: 'rgba(248, 113, 113, 0.12)' },
};

export function ArtefactRiskBadge({ risk }: { risk: ArtifactRisk }) {
  const { fg, bg } = TINT[risk];
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
      style={{ color: fg, backgroundColor: bg }}
    >
      {risk}
    </span>
  );
}
```

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'components/artefacts/Artefact(Status|Kind|Risk)Badge|error TS' | head`
Expected: no errors mentioning these three files.

- [ ] **Step 5: Commit**

```bash
git add components/artefacts/ArtefactStatusBadge.tsx components/artefacts/ArtefactKindBadge.tsx components/artefacts/ArtefactRiskBadge.tsx
git commit -m "feat(artefacts): status/kind/risk badge primitives"
```

---

### Task 5: List-preview dispatcher + `PRArtifactPreview` + `GenericArtifactPreview`

The dispatcher returns a per-kind list preview body (~1-2 lines tall under the title row). Only `PR_CHANGE` gets a real preview in v1; everything else lands on the generic.

**Files:**
- Create: `components/artefacts/previews/PRArtifactPreview.tsx`
- Create: `components/artefacts/previews/GenericArtifactPreview.tsx`
- Create: `components/artefacts/previews/index.ts`

- [ ] **Step 1: Generic preview**

```tsx
// components/artefacts/previews/GenericArtifactPreview.tsx
import type { ArtefactRow } from '@/types/artefact-row';

export function GenericArtifactPreview({ artefact }: { artefact: ArtefactRow }) {
  if (!artefact.summary) return null;
  return (
    <p className="text-[13px] text-[var(--muted)] line-clamp-2">{artefact.summary}</p>
  );
}
```

- [ ] **Step 2: PR preview**

```tsx
// components/artefacts/previews/PRArtifactPreview.tsx
import type { ArtefactRow } from '@/types/artefact-row';

export function PRArtifactPreview({ artefact }: { artefact: ArtefactRow }) {
  // payload.kind === 'PR_CHANGE' is enforced by the dispatcher
  const payload = artefact.payload as Extract<ArtefactRow['payload'], { kind: 'PR_CHANGE' }>;
  const ref = (artefact.externalRef ?? {}) as { pr_url?: string; pr_number?: number; branch?: string };

  return (
    <div className="space-y-1">
      {artefact.summary ? (
        <p className="text-[13px] text-[var(--text)] line-clamp-2">{artefact.summary}</p>
      ) : null}
      <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
        {ref.pr_number ? <span>#{ref.pr_number}</span> : null}
        {ref.branch ? <span>{ref.branch}</span> : null}
        <span>{payload.filesChanged} file{payload.filesChanged === 1 ? '' : 's'}</span>
        {ref.pr_url ? (
          <a
            href={ref.pr_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-emerald-400 hover:underline"
          >
            View PR
          </a>
        ) : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Dispatcher**

```tsx
// components/artefacts/previews/index.ts
import type { ArtefactRow } from '@/types/artefact-row';
import { GenericArtifactPreview } from './GenericArtifactPreview';
import { PRArtifactPreview } from './PRArtifactPreview';

export function ArtefactPreview({ artefact }: { artefact: ArtefactRow }) {
  switch (artefact.kind) {
    case 'PR_CHANGE':
    case 'DBT_CORE_CHANGE':
    case 'DAG':
    case 'SCHEMA_CHANGE':
      // All Group A kinds share the PR-flow preview if there's a PR ref.
      if ((artefact.externalRef as { pr_url?: string } | null)?.pr_url) {
        return <PRArtifactPreview artefact={artefact} />;
      }
      return <GenericArtifactPreview artefact={artefact} />;
    default:
      return <GenericArtifactPreview artefact={artefact} />;
  }
}
```

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'components/artefacts/previews|error TS' | head`
Expected: no errors mentioning the previews directory.

- [ ] **Step 5: Commit**

```bash
git add components/artefacts/previews/
git commit -m "feat(artefacts): list-preview dispatcher with PR and generic previews"
```

---

### Task 6: `ArtefactRowActions` — inline action menu

Three actions for v1: pin/unpin, open source session, delete. Approve/reject only on `proposed` rows. Continue button (the most important one) is a separate primary CTA on the card body, not in this menu.

**Files:**
- Create: `components/artefacts/ArtefactRowActions.tsx`

- [ ] **Step 1: Write the component**

```tsx
// components/artefacts/ArtefactRowActions.tsx
'use client';

import { useState } from 'react';
import type { ArtefactRow } from '@/types/artefact-row';

interface ArtefactRowActionsProps {
  artefact: ArtefactRow;
  onChanged: () => void;
}

export function ArtefactRowActions({ artefact, onChanged }: ArtefactRowActionsProps) {
  const [busy, setBusy] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>) {
    setBusy('patch');
    try {
      await fetch(`/api/artifacts/${artefact.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  async function del() {
    if (!window.confirm('Delete this artefact?')) return;
    setBusy('delete');
    try {
      await fetch(`/api/artifacts/${artefact.id}`, { method: 'DELETE' });
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  const canApprove = artefact.status === 'proposed';
  const canArchive =
    artefact.status === 'proposed' ||
    artefact.status === 'approved' ||
    artefact.status === 'applied' ||
    artefact.status === 'rejected' ||
    artefact.status === 'failed' ||
    artefact.status === 'open' ||
    artefact.status === 'resolved';

  return (
    <div className="flex items-center gap-2 text-[12px]" onClick={(e) => e.stopPropagation()}>
      {canApprove ? (
        <>
          <button
            disabled={!!busy}
            onClick={() => patch({ status: 'approved' })}
            className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-emerald-400 disabled:opacity-40"
          >
            Approve
          </button>
          <button
            disabled={!!busy}
            onClick={() => patch({ status: 'rejected' })}
            className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-rose-400 disabled:opacity-40"
          >
            Reject
          </button>
        </>
      ) : null}
      <button
        disabled={!!busy}
        onClick={() => patch({ isPinned: !artefact.isPinned })}
        className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--muted)] disabled:opacity-40"
        aria-label={artefact.isPinned ? 'Unpin' : 'Pin'}
      >
        {artefact.isPinned ? 'Unpin' : 'Pin'}
      </button>
      {canArchive ? (
        <button
          disabled={!!busy}
          onClick={() => patch({ status: 'archived' })}
          className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--muted)] disabled:opacity-40"
        >
          Archive
        </button>
      ) : null}
      <button
        disabled={!!busy}
        onClick={del}
        className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--muted)] disabled:opacity-40"
      >
        Delete
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'ArtefactRowActions|error TS' | head`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/artefacts/ArtefactRowActions.tsx
git commit -m "feat(artefacts): row action menu with approve/reject/pin/archive/delete"
```

---

### Task 7: `ArtefactListCard`

**Files:**
- Create: `components/artefacts/ArtefactListCard.tsx`

- [ ] **Step 1: Write the card**

```tsx
// components/artefacts/ArtefactListCard.tsx
'use client';

import Link from 'next/link';
import type { ArtefactRow } from '@/types/artefact-row';
import { ArtefactKindBadge } from './ArtefactKindBadge';
import { ArtefactStatusBadge } from './ArtefactStatusBadge';
import { ArtefactRiskBadge } from './ArtefactRiskBadge';
import { ArtefactRowActions } from './ArtefactRowActions';
import { ArtefactPreview } from './previews';

interface ArtefactListCardProps {
  artefact: ArtefactRow;
  onChanged: () => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function ArtefactListCard({ artefact, onChanged }: ArtefactListCardProps) {
  return (
    <Link
      href={`/dashboard/artifacts/${artefact.id}`}
      className="block rounded-xl border border-[var(--border)] hover:border-[var(--hover-bg)] transition-colors bg-[var(--surface)] px-4 py-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <ArtefactKindBadge kind={artefact.kind} subtype={artefact.subtype} />
            <ArtefactStatusBadge status={artefact.status} />
            {artefact.riskLevel ? <ArtefactRiskBadge risk={artefact.riskLevel} /> : null}
            {artefact.isPinned ? <span className="text-[11px] text-amber-400">Pinned</span> : null}
          </div>
          <h3 className="text-[15px] font-medium text-[var(--text)] truncate">{artefact.title}</h3>
          <div className="mt-1">
            <ArtefactPreview artefact={artefact} />
          </div>
        </div>
        <div className="text-[12px] text-[var(--muted)] whitespace-nowrap pt-0.5">
          {formatTime(artefact.createdAt)}
        </div>
      </div>
      <div className="mt-2 flex items-center justify-end">
        <ArtefactRowActions artefact={artefact} onChanged={onChanged} />
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'ArtefactListCard|error TS' | head`
Expected: no errors mentioning the card.

- [ ] **Step 3: Commit**

```bash
git add components/artefacts/ArtefactListCard.tsx
git commit -m "feat(artefacts): polymorphic list card with row actions and preview"
```

---

### Task 8: `ArtefactFilters`

Search + kind multi-select chips + status filter + source filter + pinned toggle. Status default is "active" (excludes `archived`/`rejected`/`draft`); a dropdown lets the user widen.

**Files:**
- Create: `components/artefacts/ArtefactFilters.tsx`

- [ ] **Step 1: Write the component**

```tsx
// components/artefacts/ArtefactFilters.tsx
'use client';

import { useState } from 'react';
import type { ArtifactKind, ArtifactStatus } from '@prisma/client';
import { ALL_KINDS, KIND_META } from '@/lib/artefacts/kinds';
import type { ArtefactSourceFilter } from '@/hooks/useArtefacts';

const DEFAULT_STATUSES: ArtifactStatus[] = ['proposed', 'approved', 'applied', 'open', 'resolved'];
const ALL_STATUSES: ArtifactStatus[] = [
  'proposed', 'approved', 'applied', 'rejected', 'failed', 'archived', 'open', 'resolved',
];

export interface ArtefactFiltersValue {
  search: string;
  kinds: ArtifactKind[];
  statuses: ArtifactStatus[];
  source: ArtefactSourceFilter;
  pinnedOnly: boolean;
}

export function defaultFilters(): ArtefactFiltersValue {
  return { search: '', kinds: [], statuses: DEFAULT_STATUSES, source: 'all', pinnedOnly: false };
}

interface ArtefactFiltersProps {
  value: ArtefactFiltersValue;
  onChange: (v: ArtefactFiltersValue) => void;
}

export function ArtefactFilters({ value, onChange }: ArtefactFiltersProps) {
  const [showAllStatuses, setShowAllStatuses] = useState(false);

  function toggleKind(k: ArtifactKind) {
    onChange({
      ...value,
      kinds: value.kinds.includes(k) ? value.kinds.filter((x) => x !== k) : [...value.kinds, k],
    });
  }

  function toggleStatus(s: ArtifactStatus) {
    onChange({
      ...value,
      statuses: value.statuses.includes(s)
        ? value.statuses.filter((x) => x !== s)
        : [...value.statuses, s],
    });
  }

  const visibleStatuses = showAllStatuses ? ALL_STATUSES : DEFAULT_STATUSES;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          value={value.search}
          onChange={(e) => onChange({ ...value, search: e.target.value })}
          placeholder="Search artefacts…"
          className="flex-1 min-w-[200px] px-3 py-1.5 rounded-md bg-[var(--surface)] border border-[var(--border)] text-[14px] text-[var(--text)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--hover-bg)]"
        />
        <select
          value={value.source}
          onChange={(e) => onChange({ ...value, source: e.target.value as ArtefactSourceFilter })}
          className="px-2 py-1.5 rounded-md bg-[var(--surface)] border border-[var(--border)] text-[13px] text-[var(--text)]"
        >
          <option value="all">All sources</option>
          <option value="agent">Agent-produced</option>
          <option value="user">User-saved</option>
        </select>
        <label className="flex items-center gap-1.5 text-[13px] text-[var(--muted)] cursor-pointer">
          <input
            type="checkbox"
            checked={value.pinnedOnly}
            onChange={(e) => onChange({ ...value, pinnedOnly: e.target.checked })}
          />
          Pinned only
        </label>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[12px] text-[var(--muted)] mr-1">Kind:</span>
        {ALL_KINDS.map((k) => {
          const active = value.kinds.includes(k);
          return (
            <button
              key={k}
              type="button"
              onClick={() => toggleKind(k)}
              className={`px-2 py-0.5 rounded-md text-[11px] font-medium border transition-colors ${
                active
                  ? 'border-[var(--hover-bg)] bg-[var(--hover-bg)] text-[var(--text)]'
                  : 'border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {KIND_META[k].label}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[12px] text-[var(--muted)] mr-1">Status:</span>
        {visibleStatuses.map((s) => {
          const active = value.statuses.includes(s);
          return (
            <button
              key={s}
              type="button"
              onClick={() => toggleStatus(s)}
              className={`px-2 py-0.5 rounded-md text-[11px] font-medium border uppercase tracking-wide ${
                active
                  ? 'border-[var(--hover-bg)] bg-[var(--hover-bg)] text-[var(--text)]'
                  : 'border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {s}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setShowAllStatuses((v) => !v)}
          className="px-2 py-0.5 text-[11px] text-[var(--muted)] hover:text-[var(--text)]"
        >
          {showAllStatuses ? 'Less' : 'More…'}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'ArtefactFilters|error TS' | head`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/artefacts/ArtefactFilters.tsx
git commit -m "feat(artefacts): filter bar with search/kind/status/source/pinned"
```

---

### Task 9: Rewrite `/dashboard/artifacts/page.tsx`

Replace the stub with the polymorphic list. Gate it on `ff_artefacts_v2` (the flag is now exposed; flip on after slice 6 lands).

**Files:**
- Modify: `app/(dashboard)/dashboard/artifacts/page.tsx`

- [ ] **Step 1: Read the current file to confirm it's the stub**

Run: `cat /Users/emilfabel/pallisade-copilot/app/\(dashboard\)/dashboard/artifacts/page.tsx`
Expected: the 21-line stub from commit `ea39078`.

- [ ] **Step 2: Replace with the new page**

Overwrite the file:

```tsx
// app/(dashboard)/dashboard/artifacts/page.tsx
'use client';

import { useState } from 'react';
import { isFeatureEnabled } from '@/lib/feature-flags';
import { useArtefacts } from '@/hooks/useArtefacts';
import {
  ArtefactFilters,
  defaultFilters,
  type ArtefactFiltersValue,
} from '@/components/artefacts/ArtefactFilters';
import { ArtefactListCard } from '@/components/artefacts/ArtefactListCard';

export default function ArtifactsPage() {
  const flagOn = isFeatureEnabled('ff_artefacts_v2');
  const [filters, setFilters] = useState<ArtefactFiltersValue>(defaultFilters);
  const { artefacts, total, isLoading, error, refresh } = useArtefacts({
    search: filters.search || undefined,
    kinds: filters.kinds.length ? filters.kinds : undefined,
    statuses: filters.statuses.length ? filters.statuses : undefined,
    source: filters.source,
    pinnedOnly: filters.pinnedOnly,
  });

  if (!flagOn) {
    return (
      <div className="min-h-screen bg-[var(--surface-inset)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
          <p className="mt-1 text-[14px] text-[var(--muted)]">
            The new artefacts surface is being built. Check back soon.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--surface-inset)]">
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        <header>
          <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
          <p className="mt-1 text-[14px] text-[var(--muted)]">
            Typed deliverables produced by the agent — PRs, monitors, schema changes, queries, documents.
          </p>
        </header>

        <ArtefactFilters value={filters} onChange={setFilters} />

        {error ? (
          <div className="p-4 rounded-lg border border-rose-500/30 bg-rose-500/10 text-[13px] text-rose-300">
            {error}
          </div>
        ) : null}

        {isLoading ? (
          <div className="text-[13px] text-[var(--muted)]">Loading…</div>
        ) : artefacts.length === 0 ? (
          <div className="p-8 rounded-xl border border-dashed border-[var(--border)] text-center">
            <p className="text-[14px] text-[var(--muted)]">No artefacts match these filters.</p>
          </div>
        ) : (
          <>
            <div className="text-[12px] text-[var(--muted)]">
              {total} artefact{total === 1 ? '' : 's'}
            </div>
            <div className="space-y-2">
              {artefacts.map((a) => (
                <ArtefactListCard key={a.id} artefact={a} onChanged={refresh} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'dashboard/artifacts/page|error TS' | head`
Expected: no errors mentioning the page.

- [ ] **Step 4: Commit**

```bash
git add app/\(dashboard\)/dashboard/artifacts/page.tsx
git commit -m "feat(artefacts): polymorphic list page behind ff_artefacts_v2"
```

---

### Task 10: `useArtefact` single-row hook

**Files:**
- Create: `hooks/useArtefact.ts`

- [ ] **Step 1: Write the hook**

`GET /api/artifacts/[artifactId]` returns `{ artifact: ArtefactRow }` (see `app/api/artifacts/[artifactId]/route.ts:41`). It does **not** currently `include` the agentSession/integration relations — extend the route in Step 2.

```typescript
// hooks/useArtefact.ts
'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ArtefactRow } from '@/types/artefact-row';

export interface UseArtefactResult {
  artefact: ArtefactRow | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useArtefact(artifactId: string | null): UseArtefactResult {
  const [artefact, setArtefact] = useState<ArtefactRow | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOne = useCallback(async () => {
    if (!artifactId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/artifacts/${artifactId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setArtefact(data.artifact);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load artefact');
    } finally {
      setIsLoading(false);
    }
  }, [artifactId]);

  useEffect(() => {
    fetchOne();
  }, [fetchOne]);

  return { artefact, isLoading, error, refresh: fetchOne };
}
```

- [ ] **Step 2: Extend `GET /api/artifacts/[artifactId]` to include agentSession + integration**

Edit `app/api/artifacts/[artifactId]/route.ts`. Find the existing `include` block at line 27 (currently only `sourceSession`) and replace with:

```ts
      include: {
        sourceSession: { select: { id: true, title: true } },
        agentSession: { select: { id: true, title: true } },
        integration: { select: { id: true, type: true } },
      },
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'useArtefact|artifacts/\[artifactId\]/route|error TS' | head`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add hooks/useArtefact.ts app/api/artifacts/\[artifactId\]/route.ts
git commit -m "feat(artefacts): useArtefact hook + include agentSession/integration on GET"
```

---

### Task 11: Embedded-session message endpoint + `useArtefactSession` hook

The embedded chat panel on the detail page needs to load a `CopilotSession`'s message history and stream new ones. The existing `GET /api/copilot/sessions/[sessionId]` returns the session + messages already (verified at `app/api/copilot/sessions/[sessionId]/route.ts:21`). Reuse it.

**Files:**
- Create: `hooks/useArtefactSession.ts`

- [ ] **Step 1: Write the hook**

```typescript
// hooks/useArtefactSession.ts
'use client';

import { useCallback, useEffect, useState } from 'react';

export interface SessionMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  toolCalls: unknown;
  createdAt: string;
}

export interface UseArtefactSessionResult {
  sessionId: string | null;
  messages: SessionMessage[];
  title: string | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useArtefactSession(sessionId: string | null): UseArtefactSessionResult {
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [title, setTitle] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/copilot/sessions/${sessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((data.session?.messages ?? []) as SessionMessage[]);
      setTitle(data.session?.title ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load session');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  return { sessionId, messages, title, isLoading, error, refresh: load };
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'useArtefactSession|error TS' | head`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add hooks/useArtefactSession.ts
git commit -m "feat(artefacts): useArtefactSession hook for embedded chat panel"
```

---

### Task 12: `ArtefactHeader`

The detail-page header: kind/status/risk badges, title, summary, external link, action buttons (approve/reject/archive), rollback hint.

**Files:**
- Create: `components/artefacts/ArtefactHeader.tsx`

- [ ] **Step 1: Write the header**

```tsx
// components/artefacts/ArtefactHeader.tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { ArtefactRow } from '@/types/artefact-row';
import { ArtefactKindBadge } from './ArtefactKindBadge';
import { ArtefactStatusBadge } from './ArtefactStatusBadge';
import { ArtefactRiskBadge } from './ArtefactRiskBadge';

interface ArtefactHeaderProps {
  artefact: ArtefactRow;
  onChanged: () => void;
}

function externalLink(ref: Record<string, unknown> | null): { href: string; label: string } | null {
  if (!ref) return null;
  if (typeof ref.pr_url === 'string') {
    return { href: ref.pr_url as string, label: `PR${ref.pr_number ? ` #${ref.pr_number}` : ''}` };
  }
  if (typeof ref.ticket_url === 'string') {
    return { href: ref.ticket_url as string, label: 'Ticket' };
  }
  if (typeof ref.url === 'string') {
    return { href: ref.url as string, label: 'Open' };
  }
  return null;
}

export function ArtefactHeader({ artefact, onChanged }: ArtefactHeaderProps) {
  const [busy, setBusy] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>) {
    setBusy('patch');
    try {
      await fetch(`/api/artifacts/${artefact.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  const ext = externalLink(artefact.externalRef);
  const canApprove = artefact.status === 'proposed';
  const canArchive = artefact.status !== 'draft' && artefact.status !== 'archived';

  return (
    <header className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <ArtefactKindBadge kind={artefact.kind} subtype={artefact.subtype} />
        <ArtefactStatusBadge status={artefact.status} />
        {artefact.riskLevel ? <ArtefactRiskBadge risk={artefact.riskLevel} /> : null}
        {artefact.integration ? (
          <span className="text-[11px] text-[var(--muted)]">
            via {artefact.integration.type}
          </span>
        ) : null}
        {artefact.isPinned ? <span className="text-[11px] text-amber-400">Pinned</span> : null}
      </div>

      <h1 className="text-[20px] font-semibold text-[var(--text)] break-words">{artefact.title}</h1>

      {artefact.summary ? (
        <p className="text-[14px] text-[var(--muted)] whitespace-pre-wrap">{artefact.summary}</p>
      ) : null}

      {artefact.rollbackHint ? (
        <div className="text-[12px] text-[var(--muted)] rounded-md bg-[var(--hover-bg)] px-3 py-2">
          <span className="font-medium text-[var(--text)]">Rollback: </span>
          {artefact.rollbackHint}
        </div>
      ) : null}

      <div className="flex items-center gap-2 flex-wrap pt-1">
        {ext ? (
          <a
            href={ext.href}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 rounded-md bg-[var(--hover-bg)] hover:bg-[var(--border)] text-[13px] text-[var(--text)]"
          >
            Open {ext.label} ↗
          </a>
        ) : null}
        {artefact.sourceSession ? (
          <Link
            href={`/dashboard/assistant?session=${artefact.sourceSessionId}`}
            className="px-3 py-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[13px] text-[var(--muted)] hover:text-[var(--text)]"
          >
            Open source session
          </Link>
        ) : null}
        {canApprove ? (
          <>
            <button
              disabled={!!busy}
              onClick={() => patch({ status: 'approved' })}
              className="px-3 py-1.5 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px] disabled:opacity-50"
            >
              Approve
            </button>
            <button
              disabled={!!busy}
              onClick={() => patch({ status: 'rejected' })}
              className="px-3 py-1.5 rounded-md bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 text-[13px] disabled:opacity-50"
            >
              Reject
            </button>
          </>
        ) : null}
        <button
          disabled={!!busy}
          onClick={() => patch({ isPinned: !artefact.isPinned })}
          className="px-3 py-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[13px] text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-50"
        >
          {artefact.isPinned ? 'Unpin' : 'Pin'}
        </button>
        {canArchive ? (
          <button
            disabled={!!busy}
            onClick={() => patch({ status: 'archived' })}
            className="px-3 py-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[13px] text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-50"
          >
            Archive
          </button>
        ) : null}
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'ArtefactHeader|error TS' | head`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/artefacts/ArtefactHeader.tsx
git commit -m "feat(artefacts): detail-page header with badges, external link, action buttons"
```

---

### Task 13: `ArtefactBody` dispatcher + `PRArtifactBody` + `GenericArtifactBody`

The detail-page body. `PR_CHANGE` shows changePlanId, files-changed, diffSummary, validationResults, externalRef link. Generic body shows a JSON-pretty payload as a fallback.

**Files:**
- Create: `components/artefacts/bodies/PRArtifactBody.tsx`
- Create: `components/artefacts/bodies/GenericArtifactBody.tsx`
- Create: `components/artefacts/bodies/index.ts`

- [ ] **Step 1: Generic body**

```tsx
// components/artefacts/bodies/GenericArtifactBody.tsx
import type { ArtefactRow } from '@/types/artefact-row';

export function GenericArtifactBody({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as Record<string, unknown>;
  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5">
      <h2 className="text-[14px] font-semibold text-[var(--text)] mb-3">Payload</h2>
      <pre className="text-[12px] text-[var(--muted)] whitespace-pre-wrap break-words bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[400px]">
{JSON.stringify(payload, null, 2)}
      </pre>
      {artefact.externalRef ? (
        <>
          <h3 className="text-[13px] font-semibold text-[var(--text)] mt-4 mb-2">External reference</h3>
          <pre className="text-[12px] text-[var(--muted)] whitespace-pre-wrap break-words bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[200px]">
{JSON.stringify(artefact.externalRef, null, 2)}
          </pre>
        </>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 2: PR body**

```tsx
// components/artefacts/bodies/PRArtifactBody.tsx
import type { ArtefactRow } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';

type PRPayload = Extract<ArtifactPayload, { kind: 'PR_CHANGE' }>;
type GroupAPayload = Extract<
  ArtifactPayload,
  { kind: 'PR_CHANGE' | 'DBT_CORE_CHANGE' | 'DAG' | 'SCHEMA_CHANGE' }
>;

function isPrCompatible(payload: GroupAPayload): payload is PRPayload {
  return payload.kind === 'PR_CHANGE';
}

export function PRArtifactBody({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as GroupAPayload;
  const ref = (artefact.externalRef ?? {}) as { pr_url?: string; pr_number?: number; branch?: string };

  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[13px]">
        {ref.pr_number ? (
          <div>
            <div className="text-[var(--muted)]">PR</div>
            <div className="text-[var(--text)] font-medium">#{ref.pr_number}</div>
          </div>
        ) : null}
        {ref.branch ? (
          <div>
            <div className="text-[var(--muted)]">Branch</div>
            <div className="text-[var(--text)] font-medium truncate">{ref.branch}</div>
          </div>
        ) : null}
        {isPrCompatible(payload) ? (
          <div>
            <div className="text-[var(--muted)]">Files</div>
            <div className="text-[var(--text)] font-medium">{payload.filesChanged}</div>
          </div>
        ) : null}
        {payload.kind === 'DBT_CORE_CHANGE' ? (
          <div>
            <div className="text-[var(--muted)]">Models</div>
            <div className="text-[var(--text)] font-medium">{payload.modelsTouched.length}</div>
          </div>
        ) : null}
        {payload.kind === 'DAG' ? (
          <div>
            <div className="text-[var(--muted)]">Tasks</div>
            <div className="text-[var(--text)] font-medium">{payload.affectedTasks.length}</div>
          </div>
        ) : null}
        {payload.kind === 'SCHEMA_CHANGE' ? (
          <div>
            <div className="text-[var(--muted)]">Tables</div>
            <div className="text-[var(--text)] font-medium">{payload.affectedTables.length}</div>
          </div>
        ) : null}
      </div>

      {isPrCompatible(payload) && payload.diffSummary ? (
        <div>
          <div className="text-[12px] text-[var(--muted)] mb-1">Diff summary</div>
          <pre className="text-[12px] text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[400px]">
{payload.diffSummary}
          </pre>
        </div>
      ) : null}

      {isPrCompatible(payload) && payload.validationResults
        ? (
          <div>
            <div className="text-[12px] text-[var(--muted)] mb-1">Validation</div>
            <div className="flex items-center gap-2 flex-wrap">
              {(['static', 'ci', 'sandbox'] as const).map((level) => {
                const status = payload.validationResults[level];
                if (!status) return null;
                const tint =
                  status === 'passed' ? 'text-emerald-400'
                  : status === 'failed' ? 'text-rose-400'
                  : status === 'running' ? 'text-amber-400'
                  : 'text-[var(--muted)]';
                return (
                  <span key={level} className={`text-[12px] ${tint}`}>
                    {level}: {status}
                  </span>
                );
              })}
            </div>
          </div>
        )
        : null}

      {ref.pr_url ? (
        <a
          href={ref.pr_url}
          target="_blank"
          rel="noreferrer"
          className="inline-block px-3 py-1.5 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px]"
        >
          View PR on GitHub ↗
        </a>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 3: Dispatcher**

```tsx
// components/artefacts/bodies/index.ts
import type { ArtefactRow } from '@/types/artefact-row';
import { GenericArtifactBody } from './GenericArtifactBody';
import { PRArtifactBody } from './PRArtifactBody';

export function ArtefactBody({ artefact }: { artefact: ArtefactRow }) {
  switch (artefact.kind) {
    case 'PR_CHANGE':
    case 'DBT_CORE_CHANGE':
    case 'DAG':
    case 'SCHEMA_CHANGE':
      return <PRArtifactBody artefact={artefact} />;
    default:
      return <GenericArtifactBody artefact={artefact} />;
  }
}
```

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'components/artefacts/bodies|error TS' | head`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add components/artefacts/bodies/
git commit -m "feat(artefacts): detail-body dispatcher with PR and generic bodies"
```

---

### Task 14: `EmbeddedAgentSession` — chat panel scoped to `agentSessionId`

A minimal embedded chat panel: shows existing messages from the artefact's `agentSessionId`, lets the user send a new message that streams via `useStreamingChat`. No tool-call UI in v1 — the agent-session messages render as plain text. Confirmations come back via the existing chat flow; the panel just appends streamed content to its local message list.

**Files:**
- Create: `components/artefacts/EmbeddedAgentSession.tsx`

- [ ] **Step 1: Write the component**

```tsx
// components/artefacts/EmbeddedAgentSession.tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import { useStreamingChat } from '@/hooks/useStreamingChat';
import { useArtefactSession, type SessionMessage } from '@/hooks/useArtefactSession';

interface EmbeddedAgentSessionProps {
  agentSessionId: string;
  pipelineStackId?: string;
}

export function EmbeddedAgentSession({ agentSessionId, pipelineStackId }: EmbeddedAgentSessionProps) {
  const { messages, isLoading, error, refresh } = useArtefactSession(agentSessionId);
  const { streamingMessage, sendMessage, abort } = useStreamingChat();

  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  // After the streaming message lands, refresh the persisted message list so
  // the panel converges to the durable transcript and we drop the local copy.
  useEffect(() => {
    if (streamingMessage && !streamingMessage.isStreaming && streamingMessage.stopReason === 'end_turn') {
      refresh();
    }
  }, [streamingMessage, refresh]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages.length, streamingMessage?.content]);

  async function handleSend() {
    if (!input.trim() || pending) return;
    setPending(true);
    try {
      await sendMessage(input, {
        sessionId: agentSessionId,
        pipelineStackId,
        model: 'claude-sonnet-4-6',
        mode: 'chat',
      });
      setInput('');
    } finally {
      setPending(false);
    }
  }

  function renderMessage(m: SessionMessage | { role: string; content: string; id: string }) {
    const isUser = m.role === 'user';
    return (
      <div key={m.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
        <div
          className={`max-w-[85%] rounded-2xl px-3 py-2 text-[14px] whitespace-pre-wrap ${
            isUser
              ? 'bg-[var(--hover-bg)] text-[var(--text)]'
              : 'bg-[var(--surface-inset)] text-[var(--text)]'
          }`}
        >
          {m.content}
        </div>
      </div>
    );
  }

  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] flex flex-col h-[600px]">
      <div className="px-5 py-3 border-b border-[var(--border)] flex items-center justify-between">
        <h2 className="text-[14px] font-semibold text-[var(--text)]">Agent session</h2>
        <span className="text-[11px] text-[var(--muted)] font-mono">{agentSessionId.slice(0, 8)}</span>
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {isLoading ? (
          <div className="text-[13px] text-[var(--muted)]">Loading session…</div>
        ) : error ? (
          <div className="text-[13px] text-rose-300">{error}</div>
        ) : messages.length === 0 && !streamingMessage ? (
          <div className="text-[13px] text-[var(--muted)]">
            No messages yet. Send one below to continue this artefact.
          </div>
        ) : (
          messages.map((m) => renderMessage(m))
        )}
        {streamingMessage ? (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-2xl px-3 py-2 text-[14px] whitespace-pre-wrap bg-[var(--surface-inset)] text-[var(--text)]">
              {streamingMessage.content}
              {streamingMessage.isStreaming ? <span className="text-[var(--muted)]"> ▍</span> : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="px-5 py-3 border-t border-[var(--border)]">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Continue this artefact…"
            rows={2}
            className="flex-1 resize-none rounded-md bg-[var(--surface-inset)] border border-[var(--border)] px-3 py-2 text-[14px] text-[var(--text)] focus:outline-none focus:border-[var(--hover-bg)]"
          />
          {streamingMessage?.isStreaming ? (
            <button
              onClick={abort}
              className="px-3 py-2 rounded-md bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 text-[13px]"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={pending || !input.trim()}
              className="px-3 py-2 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px] disabled:opacity-50"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'EmbeddedAgentSession|error TS' | head`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/artefacts/EmbeddedAgentSession.tsx
git commit -m "feat(artefacts): embedded agent-session panel using useStreamingChat"
```

---

### Task 15: `/dashboard/artifacts/[artifactId]/page.tsx`

The per-artefact detail route. Three stacked sections — header, body, embedded session (only when `agentSessionId` is set).

**Files:**
- Create: `app/(dashboard)/dashboard/artifacts/[artifactId]/page.tsx`

- [ ] **Step 1: Write the page**

```tsx
// app/(dashboard)/dashboard/artifacts/[artifactId]/page.tsx
'use client';

import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { isFeatureEnabled } from '@/lib/feature-flags';
import { useArtefact } from '@/hooks/useArtefact';
import { ArtefactHeader } from '@/components/artefacts/ArtefactHeader';
import { ArtefactBody } from '@/components/artefacts/bodies';
import { EmbeddedAgentSession } from '@/components/artefacts/EmbeddedAgentSession';

export default function ArtefactDetailPage() {
  const params = useParams<{ artifactId: string }>();
  const router = useRouter();
  const flagOn = isFeatureEnabled('ff_artefacts_v2');
  const { artefact, isLoading, error, refresh } = useArtefact(params.artifactId ?? null);

  if (!flagOn) {
    return (
      <div className="min-h-screen bg-[var(--surface-inset)] flex items-center justify-center">
        <p className="text-[14px] text-[var(--muted)]">Artifacts v2 is not enabled.</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--surface-inset)]">
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div>
          <button
            onClick={() => router.push('/dashboard/artifacts')}
            className="text-[13px] text-[var(--muted)] hover:text-[var(--text)]"
          >
            ← Back to artefacts
          </button>
        </div>

        {isLoading ? (
          <div className="text-[14px] text-[var(--muted)]">Loading artefact…</div>
        ) : error ? (
          <div className="p-4 rounded-lg border border-rose-500/30 bg-rose-500/10 text-[13px] text-rose-300">
            {error}
          </div>
        ) : !artefact ? (
          <div className="p-8 rounded-xl border border-dashed border-[var(--border)] text-center">
            <p className="text-[14px] text-[var(--muted)]">Artefact not found.</p>
            <Link href="/dashboard/artifacts" className="text-[13px] text-emerald-400 hover:underline">
              Back to list
            </Link>
          </div>
        ) : (
          <>
            <ArtefactHeader artefact={artefact} onChanged={refresh} />
            <ArtefactBody artefact={artefact} />
            {artefact.agentSessionId ? (
              <EmbeddedAgentSession agentSessionId={artefact.agentSessionId} />
            ) : (
              <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5">
                <h2 className="text-[14px] font-semibold text-[var(--text)] mb-1">Agent session</h2>
                <p className="text-[13px] text-[var(--muted)]">
                  This artefact does not have an agent session. It was either user-saved or created before
                  agent forking was wired up.
                </p>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'artifacts/\[artifactId\]/page|error TS' | head`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/\(dashboard\)/dashboard/artifacts/\[artifactId\]/page.tsx
git commit -m "feat(artefacts): per-artefact detail page with header, body, embedded session"
```

---

### Task 16: Smoke-test the slice locally

End-to-end check that the list page renders, filters work, clicking a card lands on the detail page, the embedded panel loads, and PATCH actions persist.

- [ ] **Step 1: Verify the dev DB has at least one artefact**

The previous backend slice added the polymorphic table but no rows are guaranteed. Create one by running a `create_change_plan` flow in the assistant, or seed directly:

```bash
npx tsx -e "
import prisma from './lib/db';
(async () => {
  const user = await prisma.user.findFirst();
  if (!user) { console.log('no user'); return; }
  const a = await prisma.artifact.create({
    data: {
      userId: user.id,
      organizationId: user.organizationId!,
      kind: 'PR_CHANGE',
      status: 'applied',
      title: 'Smoke test PR artefact',
      summary: 'Seed row for slice-4 smoke test.',
      payload: { kind: 'PR_CHANGE', changePlanId: 'cp_smoke', filesChanged: 3, diffSummary: 'placeholder', validationResults: { static: 'passed' } },
      externalRef: { pr_url: 'https://example.com/pr/1', pr_number: 1, branch: 'feat/smoke' },
      riskLevel: 'LOW',
      isSaved: true,
    },
  });
  console.log('seeded', a.id);
})();
"
```

Expected: prints `seeded <id>`.

- [ ] **Step 2: Run the dev server with the flag on**

```bash
NEXT_PUBLIC_FF_ARTEFACTS_V2=true npm run dev
```

Expected: starts on `:3000` without TS errors.

- [ ] **Step 3: Manual smoke check (browser)**

Visit `http://localhost:3000/dashboard/artifacts`. Confirm:
- Page renders with header "Artifacts" and the filter bar.
- The seeded row appears with `PR_CHANGE` + `applied` badges, `LOW` risk, `View PR` link in the preview.
- Toggling a kind chip filters the list.
- Toggling "Pinned only" filters out the unpinned seed.
- Clicking the card navigates to `/dashboard/artifacts/<id>`.

On the detail page, confirm:
- Header renders title, badges, "Open PR ↗" link, Pin/Archive buttons.
- Body shows the diff summary and validation results.
- The agent-session panel shows "This artefact does not have an agent session" (no `agentSessionId` was seeded).

Click "Approve" on a `proposed` row (you can create one by setting `status: 'proposed'` on the seed) — confirm it transitions to `approved` after refresh.

- [ ] **Step 4: Stop dev server, commit any debug fixes**

If the smoke check surfaced any bugs, fix them with focused commits referencing the symptom. If everything worked, no commit needed.

- [ ] **Step 5: Final type-check**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: zero new errors introduced by this plan. Pre-existing errors in unrelated files (e.g. lineage tests) are fine.

---

## Self-review notes (for the engineer)

- **Spec coverage:**
  - §8.2 filters — covered by Task 8 (search, kind, status, source, pinned).
  - §8.2 polymorphic list card — covered by Tasks 5, 7.
  - §8.2 inline actions — covered by Task 6 (approve/reject/pin/archive/delete). "View source session" lives on the detail header (Task 12) rather than the list card; both surface the action.
  - §8.3 detail header — Task 12.
  - §8.3 kind-specific body — Task 13.
  - §8.3 embedded agent session — Task 14.
  - §8.3 Continue target — implicit: the list card links to `/dashboard/artifacts/[id]` (Task 7), and the detail page hosts the embedded chat (Tasks 14, 15). No explicit POST to `/api/artifacts/[id]/continue` is needed in v1 — the existing route returns session metadata that the detail page can already derive from the `Artefact` row, so we skip the round-trip. Revisit if SSE rehydration ever needs a server-side handshake.
  - §9 PATCH `status` transitions — wired in Task 6 (list) and Task 12 (detail). DELETE in Task 6.
  - §9 save-snapshot — out of scope here; consumed by the chat-side "Save to artefacts" CTA in the next plan (slice 7 / DOCUMENT path).
- **No placeholders:** every step contains the literal file contents or command to run.
- **Type consistency:** `ArtefactRow` is defined once (Task 2) and reused everywhere. `ArtefactFiltersValue` is exported from the filter component for the page to type its state.
- **Flag gating:** both pages render a fallback when `ff_artefacts_v2` is off, so merging this without flipping the flag remains safe.
