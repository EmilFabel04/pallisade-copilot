# Plan 1: Type Rename & Data Contract Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename "policy" → "SLA" across the codebase, rename existing `*Contract*` types → `*SLA*` types, add the `DataContract` Prisma model and TypeScript types, rename API routes, and add the settings toggle for enabling data contracts.

**Architecture:** Two-phase rename (policy→SLA, then contract→SLA for existing types), followed by adding new DataContract types and Prisma model. API routes renamed from `/contract` to `/sla`, new `/data-contracts` CRUD route added. Settings toggle stored on PipelineStack as `dataContractsEnabled` boolean.

**Tech Stack:** TypeScript, Next.js 15, Prisma, Zod, Vitest

**Spec:** `docs/superpowers/specs/2026-03-25-sla-and-data-contracts-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `types/policy.ts` | Rename to `types/sla.ts` | Rename all `Policy*` → `SLA*` types |
| `lib/policy-utils.ts` | Rename to `lib/sla-utils.ts` | Rename all `policy` → `sla` in function/variable names |
| `components/lineage/PolicyEditorPanel.tsx` | Rename to `SLAEditorPanel.tsx` | Rename component and all internal references |
| `components/lineage/PolicyBadge.tsx` | Rename to `SLABadge.tsx` | Rename component and all internal references |
| `components/contracts/types.ts` | Modify | Rename `PipelineContractData` → `PipelineSLAData`, `SourceContractWithOverrides` → `NodeSLAWithOverrides`, `EffectiveContract` → `EffectiveSLA`; add `DataContract` types |
| `lib/contracts/resolver.ts` | Modify | Update imports and type names to SLA types |
| `components/sources/EditContractModal.tsx` | Rename to `EditSLAModal.tsx` | Rename component |
| `components/sources/types.ts` | Modify | Update references to renamed types |
| `components/sources/useSourcesData.ts` | Modify | Update `pipelineContract` → `pipelineSLA` |
| `components/sources/SourceDetailDrawer.tsx` | Modify | Update tab label and imports |
| `components/sources/SourceCard.tsx` | Modify | Update imports |
| `app/(dashboard)/dashboard/sources/page.tsx` | Modify | Update imports and state variable names |
| `app/(dashboard)/dashboard/lineage/page.tsx` | Modify | Update imports to renamed files |
| `app/(dashboard)/dashboard/schedule/page.tsx` | Modify | Update imports |
| `app/(dashboard)/dashboard/schedule/plan/[planId]/page.tsx` | Modify | Update imports |
| `components/schedule/MonitorEditPanel.tsx` | Modify | Update imports |
| `components/lineage/UnifiedNodes.tsx` | Modify | Update imports |
| `app/api/schedule/policies/assign/route.ts` | Modify | Update imports |
| `app/api/pipeline/[stackId]/contract/route.ts` | Move to `sla/route.ts` | Rename route |
| `app/api/pipeline/[stackId]/contract/apply/route.ts` | Move to `sla/apply/route.ts` | Rename route |
| `app/api/integrations/[id]/contract/route.ts` | Move to `sla/route.ts` | Rename route |
| `app/(dashboard)/dashboard/pipeline/settings/page.tsx` | Modify | Rename `contractForm` → `slaForm`, update labels, add toggle |
| `prisma/schema.prisma` | Modify | Rename models, add `DataContract` model, add `dataContractsEnabled` to PipelineStack |
| `app/api/pipeline/[stackId]/data-contracts/route.ts` | Create | CRUD for data contracts |
| `lib/__tests__/sla-utils.test.ts` | Create | Tests for renamed sla-utils |

**Out of scope for this plan:**
- Compliance engine logic (Plan 2)
- CONTRACT_CHECK monitor (Plan 2)
- UI surfaces for data contracts tab, compliance badges, multi-select (Plan 3)

---

### Task 1: Rename `types/policy.ts` → `types/sla.ts`

**Files:**
- Rename: `types/policy.ts` → `types/sla.ts`
- Modify: `types/sla.ts` (all `Policy*` → `SLA*`)
- Modify: All 6 importing files

- [ ] **Step 1: Create `types/sla.ts` with renamed types**

Copy `types/policy.ts` to `types/sla.ts` and rename all types:

```typescript
/**
 * Pipeline Monitoring SLA Types
 *
 * Monitoring SLA is a SEPARATE concept from DataContract:
 * - Monitoring SLA = lightweight operational expectations (freshness, strictness,
 *   sensitivity). Cross-domain. Used to drive monitor defaults and auto-config.
 * - DataContract = governance/compliance artifact. Data-asset-specific. Has
 *   lifecycle, ownership, violation history.
 */

// Domain config shapes stay the same (FreshnessConfig, SchemaConfig, etc.)
// ... keep all config interfaces unchanged ...

// Renamed types:
export interface SLAProfile { /* was PolicyProfile — same fields */ }
export type SLAAssignmentType = 'direct' | 'branch' | 'domain_default' | 'criticality_default';
export interface SLAAssignment { /* was PolicyAssignment — same fields */ }
export type SLAStatus = 'assigned' | 'inherited' | 'override' | 'none';
export interface EffectiveSLAPolicy { /* was EffectivePolicy — same fields */ }
export interface SLAAssignRequest { /* was PolicyAssignRequest — same fields */ }
export interface SLAResolveRequest { /* was PolicyResolveRequest — same fields */ }
export interface SLAResolveResponse { /* was PolicyResolveResponse, uses EffectiveSLAPolicy */ }
export type SLADomain = 'warehouse' | 'ingestion' | 'bi' | 'orchestration' | 'transform';
export const DOMAIN_SLA_SECTIONS: Record<SLADomain, string[]> = { /* was DOMAIN_POLICY_SECTIONS */ };
export function categoryToSLADomain(category: string): SLADomain | null { /* was categoryToPolicyDomain */ }
export const CRITICALITY_PROFILE_MAP: Record<string, string> = { /* unchanged */ };
```

- [ ] **Step 2: Delete `types/policy.ts`**

```bash
git rm types/policy.ts
```

- [ ] **Step 3: Update import in `components/lineage/PolicyEditorPanel.tsx`**

Change:
```typescript
import { categoryToPolicyDomain, DOMAIN_POLICY_SECTIONS } from '@/types/policy';
```
to:
```typescript
import { categoryToSLADomain, DOMAIN_SLA_SECTIONS } from '@/types/sla';
```

Update all internal references: `categoryToPolicyDomain` → `categoryToSLADomain`, `DOMAIN_POLICY_SECTIONS` → `DOMAIN_SLA_SECTIONS`.

- [ ] **Step 4: Update import in `app/(dashboard)/dashboard/lineage/page.tsx`**

Change:
```typescript
import type { EffectivePolicy, PolicyAssignRequest, PolicyStatus } from '@/types/policy';
```
to:
```typescript
import type { EffectiveSLAPolicy, SLAAssignRequest, SLAStatus } from '@/types/sla';
```

Update all references in the file.

- [ ] **Step 5: Update import in `components/lineage/PolicyBadge.tsx`**

Change:
```typescript
import type { PolicyStatus } from '@/types/policy';
```
to:
```typescript
import type { SLAStatus } from '@/types/sla';
```

Update `PolicyBadgeProps` to use `SLAStatus`.

- [ ] **Step 6: Update import in `app/api/schedule/policies/assign/route.ts`**

Change:
```typescript
import type { PolicyAssignmentType } from '@/types/policy';
```
to:
```typescript
import type { SLAAssignmentType } from '@/types/sla';
```

- [ ] **Step 7: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add types/sla.ts types/policy.ts components/lineage/PolicyEditorPanel.tsx app/(dashboard)/dashboard/lineage/page.tsx components/lineage/PolicyBadge.tsx app/api/schedule/policies/assign/route.ts
git commit -m "refactor: rename types/policy.ts → types/sla.ts, all Policy* → SLA* types"
```

---

### Task 2: Rename `lib/policy-utils.ts` → `lib/sla-utils.ts`

**Files:**
- Rename: `lib/policy-utils.ts` → `lib/sla-utils.ts`
- Modify: `lib/sla-utils.ts` (rename exports)
- Modify: 4 importing files

- [ ] **Step 1: Create `lib/sla-utils.ts` with renamed exports**

Copy `lib/policy-utils.ts` to `lib/sla-utils.ts`. Rename:

| Old | New |
|-----|-----|
| `POLICY_FIELD_MAP` | `SLA_FIELD_MAP` |
| `PolicyFieldMap` | `SLAFieldMap` |
| `getPolicyValueForField` | `getSLAValueForField` |
| `isLessStrictClient` | `isLessStrictClient` (keep — not policy-specific) |
| `MonitorPolicyStatus` | `MonitorSLAStatus` |
| `getMonitorPolicyStatus` | `getMonitorSLAStatus` |

- [ ] **Step 2: Delete `lib/policy-utils.ts`**

```bash
git rm lib/policy-utils.ts
```

- [ ] **Step 3: Update import in `app/(dashboard)/dashboard/schedule/page.tsx`**

Change:
```typescript
import { getMonitorPolicyStatus } from '@/lib/policy-utils';
```
to:
```typescript
import { getMonitorSLAStatus } from '@/lib/sla-utils';
```

Update all references.

- [ ] **Step 4: Update import in `app/(dashboard)/dashboard/schedule/plan/[planId]/page.tsx`**

Same pattern as Step 3.

- [ ] **Step 5: Update import in `components/schedule/MonitorEditPanel.tsx`**

Change:
```typescript
import { POLICY_FIELD_MAP, getPolicyValueForField, isLessStrictClient } from '@/lib/policy-utils';
```
to:
```typescript
import { SLA_FIELD_MAP, getSLAValueForField, isLessStrictClient } from '@/lib/sla-utils';
```

Update all internal references.

- [ ] **Step 6: Update import in `app/api/schedule/plans/route.ts`**

Change:
```typescript
import { POLICY_FIELD_MAP, getPolicyValueForField } from '@/lib/policy-utils';
```
to:
```typescript
import { SLA_FIELD_MAP, getSLAValueForField } from '@/lib/sla-utils';
```

- [ ] **Step 7: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add lib/sla-utils.ts lib/policy-utils.ts app/(dashboard)/dashboard/schedule/page.tsx app/(dashboard)/dashboard/schedule/plan/[planId]/page.tsx components/schedule/MonitorEditPanel.tsx app/api/schedule/plans/route.ts
git commit -m "refactor: rename lib/policy-utils.ts → lib/sla-utils.ts, all policy → sla exports"
```

---

### Task 3: Rename Component Files (PolicyEditorPanel, PolicyBadge, EditContractModal)

**Files:**
- Rename: `components/lineage/PolicyEditorPanel.tsx` → `SLAEditorPanel.tsx`
- Rename: `components/lineage/PolicyBadge.tsx` → `SLABadge.tsx`
- Rename: `components/sources/EditContractModal.tsx` → `EditSLAModal.tsx`
- Modify: All importing files

- [ ] **Step 1: Rename PolicyEditorPanel → SLAEditorPanel**

```bash
git mv components/lineage/PolicyEditorPanel.tsx components/lineage/SLAEditorPanel.tsx
```

In `SLAEditorPanel.tsx`, rename the exported component:
- `PolicyEditorPanel` → `SLAEditorPanel`
- `PolicyEditorPanelProps` → `SLAEditorPanelProps`

- [ ] **Step 2: Update import in `app/(dashboard)/dashboard/lineage/page.tsx`**

Change:
```typescript
import { PolicyEditorPanel, type ApplyScope } from '@/components/lineage/PolicyEditorPanel';
```
to:
```typescript
import { SLAEditorPanel, type ApplyScope } from '@/components/lineage/SLAEditorPanel';
```

Update JSX: `<PolicyEditorPanel` → `<SLAEditorPanel`.

- [ ] **Step 3: Rename PolicyBadge → SLABadge**

```bash
git mv components/lineage/PolicyBadge.tsx components/lineage/SLABadge.tsx
```

In `SLABadge.tsx`, rename:
- `PolicyBadge` → `SLABadge`
- `PolicyBadgeProps` → `SLABadgeProps`
- Update label fallback: `'Policy'` → `'SLA'`

- [ ] **Step 4: Update import in `components/lineage/UnifiedNodes.tsx`**

Change:
```typescript
import { PolicyBadge } from './PolicyBadge';
```
to:
```typescript
import { SLABadge } from './SLABadge';
```

Update JSX: `<PolicyBadge` → `<SLABadge`.

- [ ] **Step 5: Rename EditContractModal → EditSLAModal**

```bash
git mv components/sources/EditContractModal.tsx components/sources/EditSLAModal.tsx
```

In `EditSLAModal.tsx`, rename the component and update the modal title from "Edit Contract" to "Edit SLA".

- [ ] **Step 6: Update import in `app/(dashboard)/dashboard/sources/page.tsx`**

Change:
```typescript
import EditContractModal from '@/components/sources/EditContractModal';
```
to:
```typescript
import EditSLAModal from '@/components/sources/EditSLAModal';
```

Update JSX and rename state: `contractSource` → `slaSource`, `handleEditContract` → `handleEditSLA`, `handleContractSaved` → `handleSLASaved`.

- [ ] **Step 7: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add -A components/lineage/SLAEditorPanel.tsx components/lineage/SLABadge.tsx components/sources/EditSLAModal.tsx app/(dashboard)/dashboard/lineage/page.tsx components/lineage/UnifiedNodes.tsx app/(dashboard)/dashboard/sources/page.tsx
git commit -m "refactor: rename Policy/Contract component files to SLA naming"
```

---

### Task 4: Rename Contract Types → SLA Types in `components/contracts/types.ts`

**Files:**
- Modify: `components/contracts/types.ts`
- Modify: `lib/contracts/resolver.ts`
- Modify: `app/(dashboard)/dashboard/pipeline/settings/page.tsx`
- Modify: `components/sources/types.ts`
- Modify: `components/sources/EditSLAModal.tsx` (renamed in Task 3)
- Modify: `app/api/pipeline/[stackId]/contract/route.ts`
- Modify: `app/api/integrations/[id]/contract/route.ts`
- Modify: `app/api/integrations/route.ts`

- [ ] **Step 1: Rename types in `components/contracts/types.ts`**

| Old | New |
|-----|-----|
| `PipelineContractData` | `PipelineSLAData` |
| `SourceContractWithOverrides` | `NodeSLAWithOverrides` |
| `EffectiveContract` | `EffectiveSLA` |
| `WarehouseContractOverrides` | `WarehouseOverrides` (drop "Contract") |
| `IngestionContractOverrides` | `IngestionOverrides` |
| `OrchestrationContractOverrides` | `OrchestrationOverrides` |
| `TransformationContractOverrides` | `TransformationOverrides` |
| `ReportingContractOverrides` | `ReportingOverrides` |
| `StorageContractOverrides` | `StorageOverrides` |
| `ObservabilityContractOverrides` | `ObservabilityOverrides` |

Keep `validateOverrides`, `getOverrideKey`, `OVERRIDE_SCHEMAS`, `OVERRIDE_LABELS`, `INTEGRATION_TYPE_TO_OVERRIDE_KEY`, `INHERITANCE_CONFIG`, `InheritanceState`, `SlaTier`, `AlertPolicy` unchanged.

- [ ] **Step 2: Update `lib/contracts/resolver.ts`**

Change imports:
```typescript
import {
  PipelineSLAData,
  NodeSLAWithOverrides,
  EffectiveSLA,
  InheritanceState,
  SlaTier,
  validateOverrides,
} from '@/components/contracts/types';
```

Rename function signature:
```typescript
export function resolveEffectiveSLA(
  pipelineSLA: PipelineSLAData | null,
  nodeSLA: NodeSLAWithOverrides | null,
  integrationType: string
): EffectiveSLA {
```

- [ ] **Step 3: Update `app/(dashboard)/dashboard/pipeline/settings/page.tsx`**

Change:
```typescript
import type { SlaTier, PipelineContractData } from '@/components/contracts/types';
```
to:
```typescript
import type { SlaTier, PipelineSLAData } from '@/components/contracts/types';
```

Rename `contractForm` → `slaForm`, `contractSaving` → `slaSaving`, `contractDirty` → `slaDirty`.

- [ ] **Step 4: Update all other importing files**

Update imports in:
- `components/sources/types.ts`
- `components/sources/EditSLAModal.tsx`
- `app/api/pipeline/[stackId]/contract/route.ts`
- `app/api/integrations/[id]/contract/route.ts`
- `app/api/integrations/route.ts`

- [ ] **Step 5: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add components/contracts/types.ts lib/contracts/resolver.ts app/(dashboard)/dashboard/pipeline/settings/page.tsx components/sources/types.ts components/sources/EditSLAModal.tsx app/api/pipeline/[stackId]/contract/route.ts app/api/integrations/[id]/contract/route.ts app/api/integrations/route.ts
git commit -m "refactor: rename PipelineContractData → PipelineSLAData, EffectiveContract → EffectiveSLA"
```

---

### Task 5: Rename API Routes (`/contract` → `/sla`)

**Files:**
- Move: `app/api/pipeline/[stackId]/contract/route.ts` → `app/api/pipeline/[stackId]/sla/route.ts`
- Move: `app/api/pipeline/[stackId]/contract/apply/route.ts` → `app/api/pipeline/[stackId]/sla/apply/route.ts`
- Move: `app/api/integrations/[id]/contract/route.ts` → `app/api/integrations/[id]/sla/route.ts`
- Modify: All frontend files that call these endpoints

- [ ] **Step 1: Move pipeline SLA route**

```bash
mkdir -p app/api/pipeline/\[stackId\]/sla
git mv app/api/pipeline/\[stackId\]/contract/route.ts app/api/pipeline/\[stackId\]/sla/route.ts
```

- [ ] **Step 2: Move pipeline SLA apply route**

```bash
mkdir -p app/api/pipeline/\[stackId\]/sla/apply
git mv app/api/pipeline/\[stackId\]/contract/apply/route.ts app/api/pipeline/\[stackId\]/sla/apply/route.ts
```

- [ ] **Step 3: Move integration SLA route**

```bash
mkdir -p app/api/integrations/\[id\]/sla
git mv app/api/integrations/\[id\]/contract/route.ts app/api/integrations/\[id\]/sla/route.ts
```

- [ ] **Step 4: Clean up empty directories**

```bash
rmdir app/api/pipeline/\[stackId\]/contract/apply app/api/pipeline/\[stackId\]/contract app/api/integrations/\[id\]/contract
```

- [ ] **Step 5: Update frontend fetch URLs**

Search for all references to `/api/pipeline/` + `/contract` and `/api/integrations/` + `/contract` in frontend files and update to `/sla`:

Files to check:
- `app/(dashboard)/dashboard/pipeline/settings/page.tsx` — fetch URLs for pipeline SLA
- `components/sources/EditSLAModal.tsx` — fetch URL for source SLA
- `components/sources/useSourcesData.ts` — fetch URL for pipeline SLA
- `app/(dashboard)/dashboard/sources/page.tsx` — any direct fetch calls

- [ ] **Step 6: Verify TypeScript compiles and routes are accessible**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename API routes /contract → /sla"
```

---

### Task 6: Add DataContract Prisma Model and TypeScript Types

**Files:**
- Modify: `prisma/schema.prisma`
- Modify: `components/contracts/types.ts`
- Create: `lib/data-contracts/types.ts`

- [ ] **Step 1: Add DataContract model to Prisma schema**

After the existing `PipelineContract` model (line 2117), add:

```prisma
// Data Contract — group-level or exception contract for data assets
model DataContract {
  id String @id @default(cuid())

  // Scope
  scope    String  // 'schema' | 'dbt_model_group' | 'dashboard' | 'exception'
  scopeRef String  // e.g., "bigquery:public", "staging", dashboard ID

  // Ownership
  ownerUser      String?
  ownerTeam      String?
  contactChannel String?

  // SLA expectations
  slaTier                           String? // T0, T1, T2, T3
  expectedFreshnessMinutes          Int?
  expectedExtractionFrequencyMinutes Int?
  alertPolicyJson                   Json?
  notes                             String? @db.Text

  // Data-asset-specific
  schemaExpectations Json? // SchemaExpectation[]
  qualityRules       Json? // QualityRule[]

  // Override fields
  overridesJson Json?

  // Exception contract support
  isException      Boolean @default(false)
  parentContractId String?
  parentContract   DataContract?  @relation("ExceptionParent", fields: [parentContractId], references: [id])
  exceptions       DataContract[] @relation("ExceptionParent")

  // Auto-sync tracking
  autoSynced Boolean @default(false)

  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  // Relation to pipeline
  pipelineStack   PipelineStack @relation(fields: [pipelineStackId], references: [id], onDelete: Cascade)
  pipelineStackId String

  @@unique([pipelineStackId, scope, scopeRef])
  @@index([pipelineStackId])
  @@index([parentContractId])
}
```

- [ ] **Step 2: Add `dataContractsEnabled` to PipelineStack**

Find the `PipelineStack` model and add:

```prisma
  dataContractsEnabled Boolean @default(false)
```

Add the `dataContracts` relation:

```prisma
  dataContracts DataContract[]
```

- [ ] **Step 3: Run Prisma migration**

```bash
npx prisma migrate dev --name add_data_contract_model
```

Expected: Migration succeeds.

- [ ] **Step 4: Create `lib/data-contracts/types.ts`**

```typescript
import { z } from 'zod';

// ─── Contract Scope ────────────────────────────────────────
export const ContractScope = z.enum(['schema', 'dbt_model_group', 'dashboard', 'exception']);
export type ContractScope = z.infer<typeof ContractScope>;

// ─── Schema Expectation ────────────────────────────────────
export const SchemaExpectationSchema = z.object({
  columnName: z.string(),
  expectedType: z.string().nullable().optional(),
  notNull: z.boolean().default(false),
  unique: z.boolean().default(false),
});
export type SchemaExpectation = z.infer<typeof SchemaExpectationSchema>;

// ─── Quality Rule ──────────────────────────────────────────
export const QualityRuleSchema = z.object({
  field: z.string(),
  rule: z.enum(['not_null', 'unique', 'accepted_values', 'range', 'custom']),
  params: z.record(z.unknown()).default({}),
});
export type QualityRule = z.infer<typeof QualityRuleSchema>;

// ─── Data Contract Input ───────────────────────────────────
export const DataContractInputSchema = z.object({
  scope: ContractScope,
  scopeRef: z.string().min(1),
  ownerUser: z.string().nullable().optional(),
  ownerTeam: z.string().nullable().optional(),
  contactChannel: z.string().nullable().optional(),
  slaTier: z.enum(['T0', 'T1', 'T2', 'T3']).nullable().optional(),
  expectedFreshnessMinutes: z.number().min(0).nullable().optional(),
  expectedExtractionFrequencyMinutes: z.number().min(0).nullable().optional(),
  alertPolicyJson: z.any().nullable().optional(),
  notes: z.string().nullable().optional(),
  schemaExpectations: z.array(SchemaExpectationSchema).nullable().optional(),
  qualityRules: z.array(QualityRuleSchema).nullable().optional(),
  overridesJson: z.record(z.unknown()).nullable().optional(),
  isException: z.boolean().default(false),
  parentContractId: z.string().nullable().optional(),
});
export type DataContractInput = z.infer<typeof DataContractInputSchema>;

// ─── Contract Compliance Result ────────────────────────────
export interface ContractFieldCompliance {
  fieldName: string;
  contractValue: unknown;
  slaValue: unknown | null;
  actualValue: unknown | null;
  status: 'compliant' | 'override' | 'violation' | 'unknown';
}

export interface ContractComplianceResult {
  contractId: string;
  nodeId: string;
  overallStatus: 'PASS' | 'WARN' | 'FAIL';
  fields: ContractFieldCompliance[];
  checkedAt: string;
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add prisma/schema.prisma prisma/migrations/ lib/data-contracts/types.ts
git commit -m "feat: add DataContract Prisma model and TypeScript types"
```

---

### Task 7: Create Data Contract CRUD API Route

**Files:**
- Create: `app/api/pipeline/[stackId]/data-contracts/route.ts`

- [ ] **Step 1: Write failing test (manual verification)**

We'll verify the API works via curl after implementation. No vitest for API routes in this codebase.

- [ ] **Step 2: Create the route**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { DataContractInputSchema } from '@/lib/data-contracts/types';

// GET /api/pipeline/[stackId]/data-contracts — list all data contracts for a pipeline
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const { stackId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const contracts = await prisma.dataContract.findMany({
      where: { pipelineStackId: stackId },
      include: { exceptions: { select: { id: true, scopeRef: true } } },
      orderBy: { updatedAt: 'desc' },
    });

    return NextResponse.json({ contracts });
  } catch (error) {
    console.error('Error fetching data contracts:', error);
    return NextResponse.json({ error: 'Failed to fetch data contracts' }, { status: 500 });
  }
}

// POST /api/pipeline/[stackId]/data-contracts — create a data contract
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const { stackId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const parsed = DataContractInputSchema.safeParse(body);
    if (!parsed.success) {
      const issues = parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ');
      return NextResponse.json({ error: `Validation failed: ${issues}` }, { status: 400 });
    }

    // Verify pipeline exists
    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      select: { id: true },
    });
    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    const contract = await prisma.dataContract.create({
      data: {
        pipelineStackId: stackId,
        ...parsed.data,
        schemaExpectations: parsed.data.schemaExpectations ?? undefined,
        qualityRules: parsed.data.qualityRules ?? undefined,
        alertPolicyJson: parsed.data.alertPolicyJson ?? undefined,
        overridesJson: parsed.data.overridesJson ?? undefined,
      },
    });

    return NextResponse.json({ contract }, { status: 201 });
  } catch (error: any) {
    if (error?.code === 'P2002') {
      return NextResponse.json({ error: 'A contract already exists for this scope and reference' }, { status: 409 });
    }
    console.error('Error creating data contract:', error);
    return NextResponse.json({ error: 'Failed to create data contract' }, { status: 500 });
  }
}
```

- [ ] **Step 3: Create individual contract route for PATCH/DELETE**

Create: `app/api/pipeline/[stackId]/data-contracts/[contractId]/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { DataContractInputSchema } from '@/lib/data-contracts/types';

// PATCH /api/pipeline/[stackId]/data-contracts/[contractId]
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; contractId: string }> }
) {
  try {
    const { stackId, contractId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const parsed = DataContractInputSchema.partial().safeParse(body);
    if (!parsed.success) {
      const issues = parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ');
      return NextResponse.json({ error: `Validation failed: ${issues}` }, { status: 400 });
    }

    const contract = await prisma.dataContract.update({
      where: { id: contractId, pipelineStackId: stackId },
      data: {
        ...parsed.data,
        schemaExpectations: parsed.data.schemaExpectations ?? undefined,
        qualityRules: parsed.data.qualityRules ?? undefined,
        alertPolicyJson: parsed.data.alertPolicyJson ?? undefined,
        overridesJson: parsed.data.overridesJson ?? undefined,
      },
    });

    return NextResponse.json({ contract });
  } catch (error) {
    console.error('Error updating data contract:', error);
    return NextResponse.json({ error: 'Failed to update data contract' }, { status: 500 });
  }
}

// DELETE /api/pipeline/[stackId]/data-contracts/[contractId]
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; contractId: string }> }
) {
  try {
    const { stackId, contractId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    await prisma.dataContract.delete({
      where: { id: contractId, pipelineStackId: stackId },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error deleting data contract:', error);
    return NextResponse.json({ error: 'Failed to delete data contract' }, { status: 500 });
  }
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add app/api/pipeline/\[stackId\]/data-contracts/
git commit -m "feat: add data contract CRUD API routes"
```

---

### Task 8: Add Settings Toggle for Data Contracts

**Files:**
- Modify: `app/(dashboard)/dashboard/pipeline/settings/page.tsx`
- Create: `app/api/pipeline/[stackId]/settings/route.ts`

- [ ] **Step 1: Add API route for pipeline settings**

Create `app/api/pipeline/[stackId]/settings/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// PATCH /api/pipeline/[stackId]/settings — update pipeline settings
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const { stackId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const data: Record<string, any> = {};

    if ('dataContractsEnabled' in body) {
      data.dataContractsEnabled = Boolean(body.dataContractsEnabled);
    }

    if (Object.keys(data).length === 0) {
      return NextResponse.json({ error: 'No valid fields to update' }, { status: 400 });
    }

    const pipeline = await prisma.pipelineStack.update({
      where: { id: stackId },
      data,
      select: { id: true, dataContractsEnabled: true },
    });

    return NextResponse.json({ pipeline });
  } catch (error) {
    console.error('Error updating pipeline settings:', error);
    return NextResponse.json({ error: 'Failed to update settings' }, { status: 500 });
  }
}
```

- [ ] **Step 2: Add toggle to pipeline settings page**

In `app/(dashboard)/dashboard/pipeline/settings/page.tsx`, add a new section in the SLA defaults area (after the existing SLA form fields):

```tsx
{/* Data Contracts Toggle */}
<div className="p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)]">
  <div className="flex items-center justify-between">
    <div>
      <h4 className="text-sm font-medium text-[var(--foreground)]">Data Contracts</h4>
      <p className="text-xs text-[var(--muted)] mt-1">
        When enabled, data contracts become the primary source of truth for data asset compliance.
        SLA changes will show as overrides or violations against the contract.
      </p>
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={dataContractsEnabled}
      onClick={() => handleToggleDataContracts(!dataContractsEnabled)}
      className={cn(
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
        dataContractsEnabled ? 'bg-emerald-500' : 'bg-zinc-600'
      )}
    >
      <span className={cn(
        'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
        dataContractsEnabled ? 'translate-x-6' : 'translate-x-1'
      )} />
    </button>
  </div>
</div>
```

Add the state and handler:

```typescript
const [dataContractsEnabled, setDataContractsEnabled] = useState(false);

const handleToggleDataContracts = async (enabled: boolean) => {
  if (enabled) {
    // Show confirmation dialog
    if (!confirm('Enabling data contracts makes them the primary source of truth. SLA changes will no longer auto-update contracts. Continue?')) {
      return;
    }
  }
  try {
    const res = await fetch(`/api/pipeline/${selectedPipelineId}/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataContractsEnabled: enabled }),
    });
    if (res.ok) {
      setDataContractsEnabled(enabled);
      toast.success(enabled ? 'Data contracts enabled' : 'Data contracts disabled');
    }
  } catch {
    toast.error('Failed to update setting');
  }
};
```

Fetch the current value when loading pipeline data (in the existing `useEffect` that fetches pipeline details).

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add app/api/pipeline/\[stackId\]/settings/route.ts app/(dashboard)/dashboard/pipeline/settings/page.tsx
git commit -m "feat: add data contracts toggle in pipeline settings"
```

---

### Task 9: Write Tests for Renamed SLA Utils

**Files:**
- Create: `lib/__tests__/sla-utils.test.ts`

- [ ] **Step 1: Write tests**

```typescript
import { describe, it, expect } from 'vitest';
import {
  SLA_FIELD_MAP,
  getSLAValueForField,
  isLessStrictClient,
  getMonitorSLAStatus,
  type MonitorSLAStatus,
} from '../sla-utils';

describe('SLA_FIELD_MAP', () => {
  it('maps FRESHNESS monitor fields to SLA sections', () => {
    expect(SLA_FIELD_MAP.FRESHNESS.max_hours).toEqual(['freshness', 'maxHours']);
  });

  it('maps SYNC_LAG monitor fields to SLA sections', () => {
    expect(SLA_FIELD_MAP.SYNC_LAG.max_lag_minutes).toEqual(['ingestion', 'syncLagToleranceMinutes']);
  });
});

describe('getSLAValueForField', () => {
  it('returns SLA value for a mapped field', () => {
    const sla = { freshness: { maxHours: 24 } };
    expect(getSLAValueForField('FRESHNESS', 'max_hours', sla)).toBe(24);
  });

  it('returns undefined for unmapped monitor type', () => {
    expect(getSLAValueForField('UNKNOWN', 'field', {})).toBeUndefined();
  });

  it('returns undefined for null SLA', () => {
    expect(getSLAValueForField('FRESHNESS', 'max_hours', null)).toBeUndefined();
  });
});

describe('isLessStrictClient', () => {
  it('higher max_hours is less strict', () => {
    expect(isLessStrictClient('max_hours', 48, 24)).toBe(true);
  });

  it('lower max_hours is not less strict', () => {
    expect(isLessStrictClient('max_hours', 12, 24)).toBe(false);
  });

  it('strictness: ignore is less strict than warn', () => {
    expect(isLessStrictClient('strictness', 'ignore', 'warn')).toBe(true);
  });

  it('strictness: strict is not less strict than warn', () => {
    expect(isLessStrictClient('strictness', 'strict', 'warn')).toBe(false);
  });
});

describe('getMonitorSLAStatus', () => {
  it('returns policy when config matches SLA', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 24 };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('policy');
  });

  it('returns override when config is stricter', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 12 };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('override');
  });

  it('returns violation when config is less strict', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 48 };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('violation');
  });

  it('returns none for null SLA', () => {
    const result = getMonitorSLAStatus('FRESHNESS', { max_hours: 24 }, null);
    expect(result.status).toBe('none');
  });
});
```

- [ ] **Step 2: Run tests**

Run: `npx vitest run lib/__tests__/sla-utils.test.ts --reporter=verbose`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add lib/__tests__/sla-utils.test.ts
git commit -m "test: add tests for renamed sla-utils"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run full TypeScript check**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 2: Run all tests**

Run: `npx vitest run --reporter=verbose`
Expected: All tests pass.

- [ ] **Step 3: Search for stale references**

```bash
grep -rn "PolicyProfile\|PolicyAssignment\|EffectivePolicy\|PolicyStatus\|PolicyDomain\|DOMAIN_POLICY_SECTIONS\|categoryToPolicyDomain\|PipelineContractData\|SourceContractWithOverrides\|EffectiveContract\b\|EditContractModal\|PolicyEditorPanel\|PolicyBadge\|POLICY_FIELD_MAP\|getPolicyValueForField\|getMonitorPolicyStatus" --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".md" | grep -v __tests__
```

Expected: No results (only markdown docs may reference old names).

- [ ] **Step 4: Commit any remaining fixes**

If Step 3 found references, fix them and commit.
