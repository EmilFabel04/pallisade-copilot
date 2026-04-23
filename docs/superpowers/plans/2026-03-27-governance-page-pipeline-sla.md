# Governance Page & Pipeline SLA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Governance page with Data SLAs and Pipeline SLAs tabs, build full Pipeline SLA mode in lineage, and rename all "Data Contract" references to "Data SLA".

**Architecture:** Lift existing DataContractsTab to a new `/dashboard/governance` page, add search/filter, rename all references from "Data Contract" to "Data SLA". Build Pipeline SLAs tab with per-node cards backed by existing PolicyAssignment table. Add Pipeline SLA mode to the lineage Pipeline Overview tab mirroring Data SLA mode. Drop owner fields (ownerUser, ownerTeam, contactChannel) to simplify.

**Tech Stack:** Next.js 15 (App Router), React, TypeScript, Prisma, Tailwind CSS, Zod

**Spec:** `docs/superpowers/specs/2026-03-26-governance-page-pipeline-sla-design.md`

---

## Phase 1: Global Rename — Data Contracts → Data SLAs

### Task 1: Rename types and Zod schema

**Files:**
- Modify: `lib/data-contracts/types.ts`

- [ ] **Step 1: Rename ContractScope → DataSLAScope**

In `lib/data-contracts/types.ts`, rename:

```typescript
// Before
export const ContractScope = z.enum(['schema', 'dbt_model_group', 'dashboard', 'exception']);
export type ContractScope = z.infer<typeof ContractScope>;

// After
export const DataSLAScope = z.enum(['schema', 'dbt_model_group', 'dashboard', 'exception']);
export type DataSLAScope = z.infer<typeof DataSLAScope>;
```

- [ ] **Step 2: Rename DataContractInputSchema → DataSLAInputSchema, drop owner fields**

```typescript
// Before
export const DataContractInputSchema = z.object({
  scope: ContractScope,
  ...
  ownerUser: z.string().nullable().optional(),
  ownerTeam: z.string().nullable().optional(),
  contactChannel: z.string().nullable().optional(),
  ...
});
export type DataContractInput = z.infer<typeof DataContractInputSchema>;

// After
export const DataSLAInputSchema = z.object({
  scope: DataSLAScope,
  scopeRef: z.string().min(1),
  name: z.string().nullable().optional(),
  nodeFqns: z.array(z.string()).nullable().optional(),

  // SLA tier
  slaTier: z.enum(['T0', 'T1', 'T2', 'T3']).nullable().optional(),
  notes: z.string().nullable().optional(),

  // Domain-specific SLA config sections
  freshnessConfig: FreshnessConfigSchema,
  schemaConfig: SchemaConfigSchema,
  volumeConfig: VolumeConfigSchema,
  anomalyConfig: AnomalyConfigSchema,
  qualityConfig: QualityConfigSchema,
  ingestionConfig: IngestionConfigSchema,
  biConfig: BIConfigSchema,
  orchestrationConfig: OrchestrationConfigSchema,
  transformConfig: TransformConfigSchema,

  // Legacy fields
  expectedFreshnessMinutes: z.number().min(0).nullable().optional(),
  expectedExtractionFrequencyMinutes: z.number().min(0).nullable().optional(),
  alertPolicyJson: z.any().nullable().optional(),

  // Data-asset-specific
  schemaExpectations: z.array(SchemaExpectationSchema).nullable().optional(),
  qualityRules: z.array(QualityRuleSchema).nullable().optional(),
  overridesJson: z.record(z.string(), z.unknown()).nullable().optional(),
  isException: z.boolean().default(false),
  parentContractId: z.string().nullable().optional(),
});
export type DataSLAInput = z.infer<typeof DataSLAInputSchema>;
```

- [ ] **Step 3: Update ContractFieldCompliance and ContractComplianceResult names**

Rename `ContractFieldCompliance` → `DataSLAFieldCompliance`, `ContractComplianceResult` → `DataSLAComplianceResult`. Update `contractId` → `dataSlaId`, `contractValue` → `slaValue` in the interface fields.

- [ ] **Step 4: Verify type compilation**

Run: `npx tsc --noEmit 2>&1 | grep -v vitest | head -30`

This will show all import errors from files still using old names — that's expected. Fix them in the next tasks.

- [ ] **Step 5: Commit**

```bash
git add lib/data-contracts/types.ts
git commit -m "refactor: rename Data Contract types to Data SLA, drop owner fields"
```

---

### Task 2: Rename component files and exports

**Files:**
- Rename: `components/sources/DataContractsTab.tsx` → `components/sources/DataSLAsTab.tsx`
- Rename: `components/sources/DataContractCard.tsx` → `components/sources/DataSLACard.tsx`
- Rename: `components/sources/useDataContracts.ts` → `components/sources/useDataSLAs.ts`

- [ ] **Step 1: Rename files**

```bash
cd /Users/emilfabel/pallisade-copilot
mv components/sources/DataContractsTab.tsx components/sources/DataSLAsTab.tsx
mv components/sources/DataContractCard.tsx components/sources/DataSLACard.tsx
mv components/sources/useDataContracts.ts components/sources/useDataSLAs.ts
```

- [ ] **Step 2: Update useDataSLAs.ts — rename exports and drop owner fields**

In `components/sources/useDataSLAs.ts`:
- Rename `DataContractSummary` → `DataSLASummary`
- Rename `useDataContracts` → `useDataSLAs`
- Remove `ownerUser`, `ownerTeam`, `contactChannel` from the `DataSLASummary` interface
- Rename `dataContractsEnabled` → `dataSLAsEnabled` throughout
- Update fetch URL from `/api/pipeline/${id}/data-contracts` to `/api/pipeline/${id}/data-slas`
- Update error message from `'Failed to fetch data contracts'` to `'Failed to fetch data SLAs'`
- Rename `contracts` state variable to `dataSLAs`

- [ ] **Step 3: Update DataSLACard.tsx — rename imports and drop owner display**

In `components/sources/DataSLACard.tsx`:
- Update import: `import type { DataSLASummary } from './useDataSLAs';`
- Rename `DataContractCardProps` → `DataSLACardProps`
- Rename `DataContractCard` → `DataSLACard`
- Remove the `{contract.ownerTeam && <span>Team: {contract.ownerTeam}</span>}` line

- [ ] **Step 4: Update DataSLAsTab.tsx — rename all references, drop owner fields from forms**

In `components/sources/DataSLAsTab.tsx`:
- Update imports to use new names (`DataSLASummary`, `DataSLACard`, `useDataSLAs`)
- Rename `DataContractsTab` → `DataSLAsTab`
- Rename all `dataContractsEnabled` → `dataSLAsEnabled`
- Replace all UI text: "data contracts" → "data SLAs", "Data Contracts" → "Data SLAs", "Create Contract" → "Create Data SLA", "contract" → "data SLA" in user-facing strings
- Remove `ownerUser`, `ownerTeam`, `contactChannel` state variables and their form inputs from both create and edit drawers
- Remove owner fields from API payloads sent to create/update
- Update fetch URLs from `data-contracts` to `data-slas`

- [ ] **Step 5: Commit**

```bash
git add components/sources/DataSLAsTab.tsx components/sources/DataSLACard.tsx components/sources/useDataSLAs.ts
git add -u components/sources/DataContractsTab.tsx components/sources/DataContractCard.tsx components/sources/useDataContracts.ts
git commit -m "refactor: rename Data Contract components to Data SLA, drop owner fields"
```

---

### Task 3: Rename API routes

**Files:**
- Rename directory: `app/api/pipeline/[stackId]/data-contracts/` → `app/api/pipeline/[stackId]/data-slas/`
- Modify: `app/api/pipeline/[stackId]/data-slas/route.ts`
- Modify: `app/api/pipeline/[stackId]/data-slas/[slaId]/route.ts` (renamed from `[contractId]`)

- [ ] **Step 1: Rename directories and files**

```bash
cd /Users/emilfabel/pallisade-copilot
mv app/api/pipeline/\[stackId\]/data-contracts app/api/pipeline/\[stackId\]/data-slas
mv app/api/pipeline/\[stackId\]/data-slas/\[contractId\] app/api/pipeline/\[stackId\]/data-slas/\[slaId\]
```

- [ ] **Step 2: Update route.ts (list + create)**

In `app/api/pipeline/[stackId]/data-slas/route.ts`:
- Update import: `import { DataSLAInputSchema } from '@/lib/data-contracts/types';`
- Rename function `buildCreateData` param type to `Prisma.PipelineDataContractUncheckedCreateInput` (keep Prisma model name until migration)
- Update all `DataContractInputSchema` → `DataSLAInputSchema`
- Update error messages: "data contracts" → "data SLAs"
- Update response key: `contracts` → `dataSLAs`

- [ ] **Step 3: Update [slaId]/route.ts (update + delete)**

In `app/api/pipeline/[stackId]/data-slas/[slaId]/route.ts`:
- Update param extraction: `const { slaId } = params;` (was `contractId`)
- Update import: `DataSLAInputSchema`
- Update all Prisma calls to use `slaId` as the `where` clause ID
- Update error messages

- [ ] **Step 4: Update all files that reference the old API route**

Search for `/data-contracts` in API calls across the codebase and update to `/data-slas`:
- `components/sources/DataSLAsTab.tsx` (already done in Task 2)
- `app/(dashboard)/dashboard/lineage/page.tsx`: line ~245 fetches `/api/pipeline/${stackId}/data-contracts` → update to `/data-slas`
- `app/api/schedule/policies/assign/route.ts`: references to `pipelineDataContract` Prisma model (keep for now — Prisma model name changes in Task 5)

- [ ] **Step 5: Commit**

```bash
git add app/api/pipeline/\[stackId\]/data-slas/
git add -u app/api/pipeline/\[stackId\]/data-contracts/
git add app/(dashboard)/dashboard/lineage/page.tsx
git commit -m "refactor: rename data-contracts API routes to data-slas"
```

---

### Task 4: Update all remaining references across the codebase

**Files:**
- Modify: `app/(dashboard)/dashboard/sources/page.tsx`
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx`
- Modify: `components/lineage/SLAEditorPanel.tsx`
- Modify: `components/lineage/DataAssetDetailPanel.tsx`
- Modify: `components/lineage/pipeline-overview/SLASection.tsx`
- Modify: `components/pipeline/AutoDiscoveryPrompt.tsx`
- Modify: `components/sources/types.ts`
- Modify: `components/contracts/types.ts`
- Modify: `components/sources/SourceCard.tsx`
- Modify: `components/sources/EditSLAModal.tsx`
- Modify: `components/sources/useSourcesData.ts`
- Modify: `lib/contracts/resolver.ts`
- Modify: `app/api/schedule/policies/assign/route.ts`
- Modify: `app/api/schedule/policies/resolve/route.ts`
- Modify: `app/api/schedule/plans/route.ts`
- Modify: `types/sla.ts`

- [ ] **Step 1: Update sources/page.tsx**

- Update import: `import { DataSLAsTab } from '@/components/sources/DataSLAsTab';`
- Update tab state type: `'sources' | 'data-slas'`
- Update URL param check: `params.get('tab') === 'data-slas'`
- Update tab button text: "Data SLAs"
- Update conditional render: `activeTab === 'data-slas' ? <DataSLAsTab />`

- [ ] **Step 2: Update lineage/page.tsx**

- Rename `dataContractsEnabled` → `dataSLAsEnabled` state variable
- Update fetch URL from `/data-contracts` to `/data-slas`
- Update response field: `data.dataContractsEnabled` → `data.dataSLAsEnabled`
- Pass `dataSLAsEnabled` to SLAEditorPanel

- [ ] **Step 3: Update SLAEditorPanel.tsx**

- Rename props and internal references from `dataContractsEnabled` → `dataSLAsEnabled`
- Update UI text: "data contracts" → "data SLAs", "Data Contracts" → "Data SLAs"
- Update link: `Sources → Data Contracts tab` → `Governance → Data SLAs tab`

- [ ] **Step 4: Update DataAssetDetailPanel.tsx**

- Update link href from `/dashboard/sources?tab=data-contracts` to `/dashboard/governance?tab=data-slas`
- Update link text: "View Data Contract" → "View Data SLA"

- [ ] **Step 5: Update SLASection.tsx (pipeline overview)**

- Update text: "data contract" → "data SLA"

- [ ] **Step 6: Update remaining component files**

- `AutoDiscoveryPrompt.tsx`: "data contracts" → "data SLAs"
- `components/sources/types.ts`: Remove `ownerUser`, `ownerTeam`, `contactChannel` from `SourceSLAData`
- `components/contracts/types.ts`: Remove `ownerUser`, `ownerTeam`, `contactChannel` from `PipelineSLAData`, `NodeSLAWithOverrides`, `EffectiveSLA`
- `components/sources/SourceCard.tsx`: Remove ownerUser display block
- `components/sources/EditSLAModal.tsx`: Remove owner field state/inputs/payloads
- `components/sources/useSourcesData.ts`: Remove owner field mappings and search filters
- `lib/contracts/resolver.ts`: Remove owner field defaults and fallbacks

- [ ] **Step 7: Update API routes that reference data contracts**

- `app/api/schedule/policies/assign/route.ts`: Update comments "data contracts" → "data SLAs"
- `app/api/schedule/policies/resolve/route.ts`: Update comments
- `app/api/schedule/plans/route.ts`: Update comments
- `app/api/integrations/route.ts`: Remove `ownerUser`, `ownerTeam`, `contactChannel` from Prisma selects and mappings
- All Prisma model references (`prisma.pipelineDataContract`) stay unchanged until Task 5

- [ ] **Step 8: Update types/sla.ts comments**

Update comment block referencing "DataContract" to say "DataSLA".

- [ ] **Step 9: Verify compilation**

Run: `npx tsc --noEmit 2>&1 | grep -v vitest | head -30`
Expected: Clean (no errors except pre-existing vitest ones)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: update all data contract references to data SLA, drop owner fields"
```

---

### Task 5: Fix PipelineSLAEditor bug

**Files:**
- Modify: `components/lineage/pipeline-overview/PipelineSLAEditor.tsx`

- [ ] **Step 1: Fix assignmentType**

In `components/lineage/pipeline-overview/PipelineSLAEditor.tsx`, find:

```typescript
assignmentType: 'explicit',
```

Replace with:

```typescript
assignmentType: 'direct',
```

- [ ] **Step 2: Commit**

```bash
git add components/lineage/pipeline-overview/PipelineSLAEditor.tsx
git commit -m "fix: PipelineSLAEditor sends 'direct' instead of invalid 'explicit' assignmentType"
```

---

## Phase 2: Governance Page

### Task 6: Create Governance page with tab routing

**Files:**
- Create: `app/(dashboard)/dashboard/governance/page.tsx`

- [ ] **Step 1: Create the Governance page**

```tsx
'use client';

import React, { useState } from 'react';
import { DataSLAsTab } from '@/components/sources/DataSLAsTab';

type GovernanceTab = 'data-slas' | 'pipeline-slas';

export default function GovernancePage() {
  const [activeTab, setActiveTab] = useState<GovernanceTab>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get('tab');
      if (tab === 'pipeline-slas') return 'pipeline-slas';
    }
    return 'data-slas';
  });

  return (
    <div className="flex-1 overflow-y-auto p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-[var(--text)]">Governance</h1>
          <p className="text-[13px] text-[var(--muted)]">
            Manage data SLAs and pipeline SLA expectations
          </p>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => {
              setActiveTab('data-slas');
              window.history.replaceState(null, '', '/dashboard/governance?tab=data-slas');
            }}
            className={`px-4 py-2 text-[13px] font-medium rounded-lg transition-colors ${
              activeTab === 'data-slas'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--subtle-bg)]'
            }`}
          >
            Data SLAs
          </button>
          <button
            onClick={() => {
              setActiveTab('pipeline-slas');
              window.history.replaceState(null, '', '/dashboard/governance?tab=pipeline-slas');
            }}
            className={`px-4 py-2 text-[13px] font-medium rounded-lg transition-colors ${
              activeTab === 'pipeline-slas'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--subtle-bg)]'
            }`}
          >
            Pipeline SLAs
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'data-slas' ? (
          <DataSLAsTab />
        ) : (
          <div className="text-center py-12 text-[var(--muted)]">
            Pipeline SLAs tab — built in Task 10
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify it renders**

Run: `npm run dev` and navigate to `http://localhost:3000/dashboard/governance`
Expected: Page renders with "Governance" header, two tabs, Data SLAs tab shows existing content.

- [ ] **Step 3: Commit**

```bash
git add app/(dashboard)/dashboard/governance/page.tsx
git commit -m "feat: create Governance page with Data SLAs tab"
```

---

### Task 7: Add Governance to sidebar

**Files:**
- Modify: `components/dashboard/Sidebar.tsx`

- [ ] **Step 1: Add Governance nav item**

In the primary navigation array in `Sidebar.tsx`, add a "Governance" entry between Sources and Pipeline. Use a shield icon (inline SVG):

```tsx
{
  href: '/dashboard/governance',
  label: 'Governance',
  icon: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
},
```

Insert this after the Sources entry and before the Pipeline entry in the navigation array.

- [ ] **Step 2: Verify sidebar renders correctly**

Run dev server, check sidebar shows "Governance" with shield icon. Click navigates to `/dashboard/governance`. Active state highlights correctly.

- [ ] **Step 3: Commit**

```bash
git add components/dashboard/Sidebar.tsx
git commit -m "feat: add Governance entry to sidebar navigation"
```

---

### Task 8: Remove Data SLAs tab from Sources page

**Files:**
- Modify: `app/(dashboard)/dashboard/sources/page.tsx`

- [ ] **Step 1: Remove tab switching from Sources**

In `sources/page.tsx`:
- Remove the `DataSLAsTab` import
- Remove the `activeTab` state and tab buttons
- Remove the conditional render — always show sources content directly
- Remove the `?tab=data-contracts` / `?tab=data-slas` URL param logic

The sources page should now just be the sources list with its filters — no tabs.

- [ ] **Step 2: Update DataAssetDetailPanel link**

Verify `components/lineage/DataAssetDetailPanel.tsx` already points to `/dashboard/governance?tab=data-slas` (done in Task 4 Step 4). If not, update it now.

- [ ] **Step 3: Update SLAEditorPanel link**

Verify `components/lineage/SLAEditorPanel.tsx` says "Governance → Data SLAs tab" (done in Task 4 Step 3). If not, update it now.

- [ ] **Step 4: Verify Sources page works**

Navigate to `/dashboard/sources` — should show sources list directly with no tabs.
Navigate to `/dashboard/governance` — should show Data SLAs tab.

- [ ] **Step 5: Commit**

```bash
git add app/(dashboard)/dashboard/sources/page.tsx
git commit -m "refactor: remove Data SLAs tab from Sources page — now lives in Governance"
```

---

### Task 9: Add search and filtering to Data SLAs tab

**Files:**
- Create: `components/governance/GovernanceFilters.tsx`
- Modify: `components/sources/DataSLAsTab.tsx`

- [ ] **Step 1: Create GovernanceFilters component**

```tsx
'use client';

import React from 'react';

interface FilterConfig {
  label: string;
  options: { value: string; label: string }[];
  selected: Set<string>;
  onToggle: (value: string) => void;
}

interface GovernanceFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  filters: FilterConfig[];
  onClearAll: () => void;
  hasActiveFilters: boolean;
}

export function GovernanceFilters({
  search,
  onSearchChange,
  searchPlaceholder,
  filters,
  onClearAll,
  hasActiveFilters,
}: GovernanceFiltersProps) {
  return (
    <div className="space-y-3 mb-6">
      {/* Search */}
      <div className="relative">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted)]"
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="w-full pl-10 pr-4 py-2 text-[13px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder:text-[var(--muted)] focus:border-slate-500/50 focus:outline-none"
        />
      </div>

      {/* Filter chips */}
      <div className="flex items-center gap-3 flex-wrap">
        {filters.map(filter => (
          <div key={filter.label} className="flex items-center gap-1.5">
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{filter.label}:</span>
            <div className="flex gap-1">
              {filter.options.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => filter.onToggle(opt.value)}
                  className={`px-2 py-0.5 text-[11px] rounded-md border transition-colors ${
                    filter.selected.has(opt.value)
                      ? 'bg-[var(--accent)]/20 border-[var(--accent)]/40 text-[var(--text)]'
                      : 'bg-transparent border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        ))}

        {hasActiveFilters && (
          <button
            onClick={onClearAll}
            className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] underline ml-2"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Integrate GovernanceFilters into DataSLAsTab**

In `components/sources/DataSLAsTab.tsx`, add state for search and filters:

```tsx
const [search, setSearch] = useState('');
const [tierFilter, setTierFilter] = useState<Set<string>>(new Set());
const [scopeFilter, setScopeFilter] = useState<Set<string>>(new Set());
```

Add a `filteredSLAs` memo that filters the `dataSLAs` array by search text (matching name, scopeRef) and by tier/scope chip selections.

Render `<GovernanceFilters>` above the card grid with:
- `searchPlaceholder="Search by name or scope..."`
- Two filter groups: SLA Tier (T0, T1, T2, T3) and Scope Type (Schema, dbt Model Group, Dashboard, Exception)

Use `filteredSLAs` instead of `dataSLAs` when rendering the card grid.

- [ ] **Step 3: Move settings toggles into a collapsible section**

Wrap the enable/disable toggle, allow overrides toggle, and violation alerting toggle in a collapsible `<details>` or a button-toggled section with a gear icon, so they don't dominate the top of the tab.

- [ ] **Step 4: Verify filtering works**

Run dev server, navigate to Governance page. Type in search — cards filter. Click tier chips — cards filter. Click "Clear all" — resets.

- [ ] **Step 5: Commit**

```bash
git add components/governance/GovernanceFilters.tsx components/sources/DataSLAsTab.tsx
git commit -m "feat: add search and filtering to Data SLAs tab"
```

---

## Phase 3: Pipeline SLAs Tab

### Task 10: Create Pipeline SLA assignments list endpoint

**Files:**
- Create: `app/api/schedule/policies/assignments/route.ts`

- [ ] **Step 1: Create the GET endpoint**

```tsx
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { prisma } from '@/lib/prisma';

// GET /api/schedule/policies/assignments?stackId=X&domain=Y&tier=Z
export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.organizationId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { searchParams } = request.nextUrl;
  const stackId = searchParams.get('stackId');
  if (!stackId) {
    return NextResponse.json({ error: 'stackId required' }, { status: 400 });
  }

  const domainFilter = searchParams.get('domain');
  const tierFilter = searchParams.get('tier');

  try {
    const where: any = {
      organizationId: session.user.organizationId,
      stackId,
      assignmentType: 'direct', // Only show explicit per-node assignments
    };

    if (domainFilter) where.nodeDomain = domainFilter;

    const assignments = await prisma.policyAssignment.findMany({
      where,
      include: { profile: true },
      orderBy: { updatedAt: 'desc' },
    });

    // Flatten: each assignment may cover multiple nodeFqns
    const items = assignments.flatMap(a => {
      const fqns: string[] = (a.nodeFqns as string[]) || [];
      return fqns.map(fqn => ({
        assignmentId: a.id,
        nodeFqn: fqn,
        profileId: a.profileId,
        profileName: a.profile?.name || null,
        nodeDomain: a.nodeDomain || null,
        overrides: a.overrides || null,
        slaTier: a.profile?.criticality || null,
        updatedAt: a.updatedAt?.toISOString() || null,
      }));
    });

    // Apply tier filter on resolved items
    const filtered = tierFilter
      ? items.filter(i => i.slaTier?.toUpperCase() === tierFilter.toUpperCase())
      : items;

    return NextResponse.json({ assignments: filtered });
  } catch (error) {
    console.error('Error fetching policy assignments:', error);
    return NextResponse.json({ error: 'Failed to fetch assignments' }, { status: 500 });
  }
}
```

- [ ] **Step 2: Verify endpoint works**

Run dev server, test with curl:
```bash
curl "http://localhost:3000/api/schedule/policies/assignments?stackId=YOUR_STACK_ID"
```
Expected: JSON response with `assignments` array.

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/policies/assignments/route.ts
git commit -m "feat: add GET /api/schedule/policies/assignments endpoint"
```

---

### Task 11: Create PipelineSLACard component

**Files:**
- Create: `components/governance/PipelineSLACard.tsx`

- [ ] **Step 1: Create the card component**

```tsx
'use client';

import React from 'react';
import { LAYER_COLORS, LAYER_LABELS, type PipelineLayer } from '@/components/pipeline/types';

export interface PipelineSLAItem {
  assignmentId: string;
  nodeFqn: string;
  profileId: string;
  profileName: string | null;
  nodeDomain: string | null;
  overrides: Record<string, any> | null;
  slaTier: string | null;
  updatedAt: string | null;
  // Enriched client-side from pipeline overview data
  nodeName?: string;
  platform?: string;
  layer?: string;
}

const DOMAIN_COLORS: Record<string, string> = {
  ingestion: '#10B981',
  orchestration: '#F97316',
  transform: '#F59E0B',
  bi: '#3B82F6',
  warehouse: '#8B5CF6',
};

const TIER_STYLES: Record<string, { color: string; bg: string }> = {
  T0: { color: 'text-red-400', bg: 'bg-red-500/15' },
  T1: { color: 'text-amber-400', bg: 'bg-amber-500/15' },
  T2: { color: 'text-blue-400', bg: 'bg-blue-500/15' },
  T3: { color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

// Extract the top 2-3 key expectation fields from overrides for preview
function getKeyExpectations(domain: string | null, overrides: Record<string, any> | null): string[] {
  if (!overrides) return [];
  const results: string[] = [];

  const sections = Object.entries(overrides);
  for (const [section, config] of sections) {
    if (typeof config !== 'object' || !config) continue;
    for (const [key, value] of Object.entries(config as Record<string, unknown>)) {
      if (key === 'enabled' || value == null) continue;
      // Format nicely
      const label = key
        .replace(/([A-Z])/g, ' $1')
        .replace(/^./, s => s.toUpperCase())
        .replace(/Minutes$/, ' (min)')
        .replace(/Hours$/, ' (hrs)');
      results.push(`${label}: ${value}`);
      if (results.length >= 3) return results;
    }
  }
  return results;
}

interface PipelineSLACardProps {
  item: PipelineSLAItem;
  onClick: (item: PipelineSLAItem) => void;
}

export function PipelineSLACard({ item, onClick }: PipelineSLACardProps) {
  const domainColor = DOMAIN_COLORS[item.nodeDomain || ''] || '#6B7280';
  const domainLabel = item.nodeDomain
    ? item.nodeDomain.charAt(0).toUpperCase() + item.nodeDomain.slice(1)
    : 'Unknown';
  const tierStyle = TIER_STYLES[(item.slaTier || '').toUpperCase()] || TIER_STYLES.T2;
  const expectations = getKeyExpectations(item.nodeDomain, item.overrides);

  return (
    <button
      onClick={() => onClick(item)}
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--overlay-bg)] hover:border-[var(--accent)]/30 transition-all"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium text-[var(--text)] truncate">
          {item.nodeName || item.nodeFqn.split('.').pop() || item.nodeFqn}
        </span>
        {item.slaTier && (
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${tierStyle.color} ${tierStyle.bg}`}>
            {item.slaTier.toUpperCase()}
          </span>
        )}
      </div>

      {/* Metadata row */}
      <div className="flex items-center gap-2 mb-3">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ color: domainColor, background: `${domainColor}14`, border: `1px solid ${domainColor}20` }}
        >
          {domainLabel}
        </span>
        {item.platform && (
          <span className="text-[10px] text-[var(--muted)] capitalize">{item.platform}</span>
        )}
        {item.profileName && (
          <span className="text-[10px] text-[var(--muted)]">{item.profileName}</span>
        )}
      </div>

      {/* Key expectations */}
      {expectations.length > 0 && (
        <div className="space-y-1">
          {expectations.map((exp, i) => (
            <p key={i} className="text-[11px] text-[var(--muted)]">{exp}</p>
          ))}
        </div>
      )}

      {/* Empty state */}
      {expectations.length === 0 && (
        <p className="text-[11px] text-[var(--muted)] italic">Profile assigned, no custom expectations</p>
      )}
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/governance/PipelineSLACard.tsx
git commit -m "feat: create PipelineSLACard component"
```

---

### Task 12: Create PipelineSLAsTab component

**Files:**
- Create: `components/governance/PipelineSLAsTab.tsx`

- [ ] **Step 1: Create the Pipeline SLAs tab**

```tsx
'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { usePipeline } from '@/components/pipeline/PipelineContext';
import { GovernanceFilters } from './GovernanceFilters';
import { PipelineSLACard, type PipelineSLAItem } from './PipelineSLACard';

export function PipelineSLAsTab() {
  const { selectedPipelineId } = usePipeline();
  const [items, setItems] = useState<PipelineSLAItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState('');
  const [tierFilter, setTierFilter] = useState<Set<string>>(new Set());
  const [domainFilter, setDomainFilter] = useState<Set<string>>(new Set());

  // Fetch assignments
  useEffect(() => {
    if (!selectedPipelineId) return;
    setLoading(true);
    setError(null);

    fetch(`/api/schedule/policies/assignments?stackId=${selectedPipelineId}`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to fetch');
        return res.json();
      })
      .then(data => setItems(data.assignments || []))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [selectedPipelineId]);

  // Filter logic
  const filtered = useMemo(() => {
    let result = items;

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(i =>
        (i.nodeName || i.nodeFqn).toLowerCase().includes(q) ||
        (i.platform || '').toLowerCase().includes(q) ||
        (i.profileName || '').toLowerCase().includes(q)
      );
    }

    if (tierFilter.size > 0) {
      result = result.filter(i => i.slaTier && tierFilter.has(i.slaTier.toUpperCase()));
    }

    if (domainFilter.size > 0) {
      result = result.filter(i => i.nodeDomain && domainFilter.has(i.nodeDomain));
    }

    return result;
  }, [items, search, tierFilter, domainFilter]);

  // Unique platforms for info
  const platforms = useMemo(() => {
    const set = new Set<string>();
    items.forEach(i => { if (i.platform) set.add(i.platform); });
    return Array.from(set).sort();
  }, [items]);

  const hasActiveFilters = search.length > 0 || tierFilter.size > 0 || domainFilter.size > 0;

  const toggleFilter = (set: Set<string>, setter: (s: Set<string>) => void, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  };

  if (loading) {
    return <div className="text-center py-12 text-[var(--muted)]">Loading pipeline SLAs...</div>;
  }

  if (error) {
    return <div className="text-center py-12 text-red-400">Failed to load pipeline SLAs: {error}</div>;
  }

  return (
    <div>
      <GovernanceFilters
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search by node name, platform, or profile..."
        filters={[
          {
            label: 'Tier',
            options: [
              { value: 'T0', label: 'T0' },
              { value: 'T1', label: 'T1' },
              { value: 'T2', label: 'T2' },
              { value: 'T3', label: 'T3' },
            ],
            selected: tierFilter,
            onToggle: v => toggleFilter(tierFilter, setTierFilter, v),
          },
          {
            label: 'Domain',
            options: [
              { value: 'ingestion', label: 'Ingestion' },
              { value: 'orchestration', label: 'Orchestration' },
              { value: 'transform', label: 'Transform' },
              { value: 'bi', label: 'BI' },
              { value: 'warehouse', label: 'Warehouse' },
            ],
            selected: domainFilter,
            onToggle: v => toggleFilter(domainFilter, setDomainFilter, v),
          },
        ]}
        onClearAll={() => {
          setSearch('');
          setTierFilter(new Set());
          setDomainFilter(new Set());
        }}
        hasActiveFilters={hasActiveFilters}
      />

      {filtered.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-[var(--muted)] text-[13px]">
            {items.length === 0
              ? 'No pipeline SLAs assigned yet. Use Pipeline SLA mode in lineage or create one here.'
              : 'No pipeline SLAs match your filters.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((item, i) => (
            <PipelineSLACard
              key={`${item.assignmentId}-${item.nodeFqn}`}
              item={item}
              onClick={() => {
                // TODO Task 13: Open edit drawer
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire into Governance page**

In `app/(dashboard)/dashboard/governance/page.tsx`, replace the placeholder:

```tsx
import { PipelineSLAsTab } from '@/components/governance/PipelineSLAsTab';

// In the tab content section, replace the placeholder div:
{activeTab === 'pipeline-slas' ? (
  <PipelineSLAsTab />
) : null}
```

- [ ] **Step 3: Verify it renders**

Navigate to `/dashboard/governance?tab=pipeline-slas`. Should show search/filters and either cards or the empty state.

- [ ] **Step 4: Commit**

```bash
git add components/governance/PipelineSLAsTab.tsx app/(dashboard)/dashboard/governance/page.tsx
git commit -m "feat: create Pipeline SLAs tab with search and filtering"
```

---

## Phase 4: Pipeline SLA Mode in Lineage

### Task 13: Create PipelineSLAModeToolbar

**Files:**
- Create: `components/lineage/PipelineSLAModeToolbar.tsx`

- [ ] **Step 1: Create the toolbar component**

```tsx
'use client';

import React from 'react';

interface PipelineSLAModeToolbarProps {
  selectedCount: number;
  totalNodes: number;
  onSaveAll: () => void;
  onExit: () => void;
  saving?: boolean;
}

export function PipelineSLAModeToolbar({
  selectedCount,
  totalNodes,
  onSaveAll,
  onExit,
  saving,
}: PipelineSLAModeToolbarProps) {
  return (
    <div className="flex items-center gap-4 mt-4 pt-4 border-t border-slate-500/20">
      {/* Mode indicator */}
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse" />
        <span className="text-[13px] font-medium" style={{ color: 'var(--text)' }}>Pipeline SLA Mode</span>
      </div>

      {/* Selection counter */}
      <div className="text-[12px] text-[var(--muted)]">
        {selectedCount > 0 ? (
          <span className="font-medium" style={{ color: 'var(--text)' }}>{selectedCount}</span>
        ) : (
          <span>0</span>
        )}
        {' of '}
        {totalNodes} nodes selected
      </div>

      {/* Badge legend */}
      <div className="flex items-center gap-3 ml-auto text-[11px]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block px-1.5 py-0.5 rounded-sm text-[8px] font-semibold uppercase" style={{ background: 'var(--subtle-bg)', color: 'var(--muted)', border: '1px solid var(--subtle-border)' }}>Profile</span>
          <span style={{ color: 'var(--text-secondary)' }}>= Pipeline SLA assigned</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: 'var(--text-faint)', border: '1px dashed var(--muted)' }} />
          <span style={{ color: 'var(--text-secondary)' }}>= no Pipeline SLA</span>
        </span>
      </div>

      {/* Actions */}
      <button
        onClick={onSaveAll}
        disabled={saving}
        className="px-3 py-1.5 text-[12px] font-medium rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-2)] transition-all disabled:opacity-50"
      >
        {saving ? 'Saving...' : 'Save All'}
      </button>
      <button
        onClick={onExit}
        className="px-3 py-1.5 text-[12px] font-medium rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-all flex items-center gap-1"
      >
        Exit Pipeline SLA Mode
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/lineage/PipelineSLAModeToolbar.tsx
git commit -m "feat: create PipelineSLAModeToolbar component"
```

---

### Task 14: Create PipelineSLAEditorPanel

**Files:**
- Create: `components/lineage/PipelineSLAEditorPanel.tsx`

- [ ] **Step 1: Create the editor panel**

This mirrors `SLAEditorPanel.tsx` but for pipeline/tool nodes. It should:

- Accept props: `selectedNodeIds: Set<string>`, `allNodes` (pipeline overview ViewNode[]), `stackId`, `nodeSLAs`, `saving`, `onApply`, `onRemoveSLA`, `onClose`, `onClearSelection`
- Show empty state "Click a node to define its Pipeline SLA." when no nodes selected
- Profile selector (T0-T3 + DB profiles) — reuse the same profile fetch as SLAEditorPanel
- Auto-detect domains from selected nodes using `categoryToSLADomain` / layer mapping
- Show tool-specific fields based on detected domains (reuse `DOMAIN_SLA_SECTIONS` and the field definitions from `PipelineSLAEditor.tsx` TOOL_FIELDS)
- Override mechanism with "(custom)" badge
- Apply scope: Selected / Downstream / All of Domain
- Remove Pipeline SLA button

The full implementation should be structurally identical to `SLAEditorPanel.tsx` (lines 243-862) but:
- Use "Pipeline SLA" labels instead of "Data SLA"
- Domain detection uses `node.layer` / `node.platform` (pipeline overview nodes) rather than `node.category` (lineage nodes)
- Fields shown are the tool-specific ones (ingestion, orchestration, transform, bi) not the data-quality ones (freshness, schema, volume, anomaly, quality)

Copy the structure of `SLAEditorPanel.tsx` and adapt:
- Replace all "Data SLA" text with "Pipeline SLA"
- Replace `categoryToSLADomain(n.category)` with layer/platform-based domain resolution matching the logic in `InspectorPanel.tsx` lines 456-463
- Use `TOOL_FIELDS` from `PipelineSLAEditor.tsx` for the advanced override section fields

- [ ] **Step 2: Verify compilation**

Run: `npx tsc --noEmit 2>&1 | grep -v vitest | head -20`

- [ ] **Step 3: Commit**

```bash
git add components/lineage/PipelineSLAEditorPanel.tsx
git commit -m "feat: create PipelineSLAEditorPanel for Pipeline SLA mode"
```

---

### Task 15: Wire Pipeline SLA mode into the lineage page

**Files:**
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx`

- [ ] **Step 1: Add imports**

```tsx
import { PipelineSLAEditorPanel } from '@/components/lineage/PipelineSLAEditorPanel';
import { PipelineSLAModeToolbar } from '@/components/lineage/PipelineSLAModeToolbar';
```

- [ ] **Step 2: Add Pipeline SLA mode state**

Near the existing `slaMode` state (around line 260), add:

```tsx
const [pipelineSlaMode, setPipelineSlaMode] = useState(false);
const [pipelineSlaSelectedNodeIds, setPipelineSlaSelectedNodeIds] = useState<Set<string>>(new Set());
```

- [ ] **Step 3: Add Escape handler for Pipeline SLA mode**

Add a useEffect similar to the existing SLA mode escape handler:

```tsx
useEffect(() => {
  if (!pipelineSlaMode) return;
  const handler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      setPipelineSlaMode(false);
      setPipelineSlaSelectedNodeIds(new Set());
    }
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [pipelineSlaMode]);
```

- [ ] **Step 4: Add "Pipeline SLA" button in header**

Near the "Data SLA" button (around line 1552), add the Pipeline SLA button that only shows on Pipeline Overview:

```tsx
{lineageData && controlPlaneData && !pipelineSlaMode && activeTab === 'control-plane' && (
  <button
    onClick={() => {
      setPipelineSlaMode(true);
      setPipelineSlaSelectedNodeIds(new Set());
      setPipelineInspectorTarget(null);
    }}
    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-500/30 text-slate-300 hover:bg-slate-500/10 text-[13px] font-medium transition-all"
  >
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
    Pipeline SLA
  </button>
)}
```

- [ ] **Step 5: Update node click handler for Pipeline SLA mode**

In the `onNodeClick` handler for the control-plane tab, add Pipeline SLA mode handling. When `pipelineSlaMode` is true, Shift+Click toggles node selection instead of opening the inspector:

```tsx
if (pipelineSlaMode) {
  setPipelineSlaSelectedNodeIds(prev => {
    const next = new Set(prev);
    if (next.has(nodeId)) next.delete(nodeId);
    else next.add(nodeId);
    return next;
  });
  return;
}
```

- [ ] **Step 6: Add PipelineSLAModeToolbar rendering**

When `pipelineSlaMode` is true and `activeTab === 'control-plane'`, render the toolbar in place of the normal stats section:

```tsx
{pipelineSlaMode && activeTab === 'control-plane' && (
  <PipelineSLAModeToolbar
    selectedCount={pipelineSlaSelectedNodeIds.size}
    totalNodes={controlPlaneData?.nodes?.length || 0}
    onSaveAll={() => { /* handled by panel */ }}
    onExit={() => {
      setPipelineSlaMode(false);
      setPipelineSlaSelectedNodeIds(new Set());
    }}
  />
)}
```

- [ ] **Step 7: Add PipelineSLAEditorPanel rendering**

When `pipelineSlaMode` is true, render the editor panel (same position as the InspectorPanel, which should be hidden during Pipeline SLA mode):

```tsx
{pipelineSlaMode && activeTab === 'control-plane' && (
  <PipelineSLAEditorPanel
    selectedNodeIds={pipelineSlaSelectedNodeIds}
    allNodes={controlPlaneData?.nodes || []}
    stackId={stackId || ''}
    nodeSLAs={nodeSLAs}
    saving={policySaving}
    onApply={async (request, scope) => {
      setPolicySaving(true);
      try {
        const res = await fetch('/api/schedule/policies/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...request, stackId }),
        });
        if (res.ok) {
          toast.success(`Pipeline SLA applied`);
          await refreshSLAs();
        } else {
          const data = await res.json().catch(() => ({}));
          toast.error(data.error || 'Failed to apply Pipeline SLA');
        }
      } catch {
        toast.error('Failed to apply Pipeline SLA');
      } finally {
        setPolicySaving(false);
      }
    }}
    onRemoveSLA={async (nodeFqns) => {
      try {
        const res = await fetch('/api/schedule/policies/assign?' + new URLSearchParams({ stackId: stackId || '' }), {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nodeFqns }),
        });
        if (res.ok) {
          toast.success('Pipeline SLA removed');
          await refreshSLAs();
        }
      } catch {
        toast.error('Failed to remove Pipeline SLA');
      }
    }}
    onClose={() => {
      setPipelineSlaMode(false);
      setPipelineSlaSelectedNodeIds(new Set());
    }}
    onClearSelection={() => setPipelineSlaSelectedNodeIds(new Set())}
  />
)}
```

- [ ] **Step 8: Hide InspectorPanel when Pipeline SLA mode is active**

Update the InspectorPanel conditional:

```tsx
{activeTab === 'control-plane' && effectiveInspectorTarget && !pipelineSlaMode && (
  <InspectorPanel ... />
)}
```

- [ ] **Step 9: Verify end-to-end**

1. Navigate to lineage page, switch to Pipeline Overview tab
2. Click "Pipeline SLA" button — mode activates, toolbar shows
3. Shift+Click nodes — they get selected
4. Editor panel shows with profile selector and tool-specific fields
5. Apply a profile — toast confirms, SLA badges appear on nodes
6. Press Escape — exits mode

- [ ] **Step 10: Commit**

```bash
git add app/(dashboard)/dashboard/lineage/page.tsx
git commit -m "feat: wire Pipeline SLA mode into lineage Pipeline Overview tab"
```

---

## Deferred: Prisma Model Rename

The spec mentions renaming `PipelineDataContract` → `PipelineDataSLA` in the Prisma schema. This is deferred to avoid a migration mid-feature. All code continues to use `prisma.pipelineDataContract` internally. The rename can be done as a follow-up with `@@map("PipelineDataContract")` to avoid a table rename, or as a proper migration once this feature is stable.

---

## Phase 5: Final Verification

### Task 16: Full integration test

**Files:** None (verification only)

- [ ] **Step 1: Verify Governance page — Data SLAs tab**

1. Navigate to `/dashboard/governance`
2. Default tab is "Data SLAs"
3. Search bar filters cards by name
4. Tier and Scope chips filter correctly
5. "Clear all" resets filters
6. Create/edit/delete data SLAs works
7. Settings toggles are in a collapsible section
8. No "owner" fields anywhere in create/edit forms

- [ ] **Step 2: Verify Governance page — Pipeline SLAs tab**

1. Switch to "Pipeline SLAs" tab
2. Cards show per-node with domain badges, tier badges, key expectations
3. Search and domain/tier filters work
4. Empty state shows correct message

- [ ] **Step 3: Verify Pipeline SLA mode in lineage**

1. Go to `/dashboard/lineage`, switch to Pipeline Overview
2. "Pipeline SLA" button visible, "Data SLA" button hidden
3. Click Pipeline SLA — mode activates
4. Multi-select nodes, apply profile
5. Exit mode — back to normal

- [ ] **Step 4: Verify Data SLA mode still works**

1. Switch to Data Lineage tab
2. "Data SLA" button visible, "Pipeline SLA" button hidden
3. Click Data SLA — mode activates, editor panel works
4. Text says "Data SLA" everywhere (no "Data Contract" remnants)

- [ ] **Step 5: Verify no "Data Contract" references remain in UI**

Search the rendered app for any visible "Data Contract" text. Check:
- Sidebar
- Governance page
- Sources page (no tabs, no contract references)
- Lineage page (both tabs)
- Settings page

- [ ] **Step 6: Verify Sources page is sources-only**

Navigate to `/dashboard/sources` — no tab switching, just the sources list.

- [ ] **Step 7: Verify compilation is clean**

```bash
npx tsc --noEmit 2>&1 | grep -v vitest | head -20
```
Expected: No new errors.

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup and verification"
```
