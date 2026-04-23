# Plan 3: UI Surfaces & UX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the UI surfaces: Sources "Data Contracts" tab (read-only/editable), compliance badges on pipeline overview/lineage nodes, SLA modal updates with contract banners and per-field badges, Shift+Click multi-select for bulk SLA, and auto-discovery prompts.

**Architecture:** New `DataContractsTab` component in sources. Compliance badges rendered via `SLABadge` (renamed from PolicyBadge) extended with compliance colors. Multi-select state managed in the pipeline overview page and passed to InspectorPanel. Auto-discovery prompts shown as toast/modal when VCS/warehouse/dbt tools are first connected.

**Tech Stack:** TypeScript, React, Next.js 15, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-25-sla-and-data-contracts-design.md`

**Depends on:** Plan 1 (type renames) and Plan 2 (compliance engine) must be completed first.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `components/sources/DataContractsTab.tsx` | Create | Data Contracts tab for sources page |
| `components/sources/DataContractCard.tsx` | Create | Individual contract card in the tab |
| `components/sources/DataContractEditModal.tsx` | Create | Edit modal for data contracts (when enabled) |
| `components/sources/useDataContracts.ts` | Create | Hook for fetching/mutating data contracts |
| `app/(dashboard)/dashboard/sources/page.tsx` | Modify | Add Data Contracts tab |
| `components/lineage/SLABadge.tsx` | Modify | Add compliance badge colors (green/blue/red/yellow) |
| `components/lineage/ComplianceBadge.tsx` | Create | Node-level compliance badge for pipeline overview |
| `components/lineage/pipeline-overview/InspectorPanel.tsx` | Modify | Add SLA section, contract banner, per-field compliance badges |
| `components/lineage/pipeline-overview/SLASection.tsx` | Create | SLA display/edit section within inspector panel |
| `components/lineage/pipeline-overview/types.ts` | Modify | Add multi-select types |
| `app/(dashboard)/dashboard/lineage/page.tsx` | Modify | Add Shift+Click multi-select state |
| `components/lineage/UnifiedNodes.tsx` | Modify | Render compliance badges on nodes |

**Out of scope for this plan:**
- Auto-discovery from dbt manifest (follow-up plan)
- Schema expectations and quality rules editing UI (follow-up plan)

---

### Task 1: Data Contracts Hook

**Files:**
- Create: `components/sources/useDataContracts.ts`

- [ ] **Step 1: Create the hook**

```typescript
// components/sources/useDataContracts.ts
'use client';

import { useState, useEffect, useCallback } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import type { ContractScope } from '@/lib/data-contracts/types';

export interface DataContractSummary {
  id: string;
  scope: ContractScope;
  scopeRef: string;
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: string | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  isException: boolean;
  parentContractId: string | null;
  autoSynced: boolean;
  exceptions: Array<{ id: string; scopeRef: string }>;
  updatedAt: string;
}

export function useDataContracts() {
  const { selectedPipelineId } = usePipeline();
  const [contracts, setContracts] = useState<DataContractSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchContracts = useCallback(async () => {
    if (!selectedPipelineId) { setContracts([]); setLoading(false); return; }
    setLoading(true);
    try {
      const res = await cachedFetch(`/api/pipeline/${selectedPipelineId}/data-contracts`);
      if (!res.ok) throw new Error('Failed to fetch');
      const data = await res.json();
      setContracts(data.contracts || []);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedPipelineId]);

  useEffect(() => { fetchContracts(); }, [fetchContracts]);

  const refresh = useCallback(() => {
    if (selectedPipelineId) {
      invalidateCache(`/api/pipeline/${selectedPipelineId}/data-contracts`);
    }
    return fetchContracts();
  }, [selectedPipelineId, fetchContracts]);

  return { contracts, loading, error, refresh };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add components/sources/useDataContracts.ts
git commit -m "feat: add useDataContracts hook for fetching pipeline data contracts"
```

---

### Task 2: Data Contracts Tab in Sources

**Files:**
- Create: `components/sources/DataContractsTab.tsx`
- Create: `components/sources/DataContractCard.tsx`
- Modify: `app/(dashboard)/dashboard/sources/page.tsx`

- [ ] **Step 1: Create DataContractCard component**

```typescript
// components/sources/DataContractCard.tsx
'use client';

import React from 'react';
import { FileText, Shield, AlertTriangle } from 'lucide-react';
import type { DataContractSummary } from './useDataContracts';

const SCOPE_LABELS: Record<string, string> = {
  schema: 'Schema',
  dbt_model_group: 'dbt Group',
  dashboard: 'Dashboard',
  exception: 'Exception',
};

const SCOPE_ICONS: Record<string, React.ReactNode> = {
  schema: <FileText className="w-3.5 h-3.5" />,
  dbt_model_group: <Shield className="w-3.5 h-3.5" />,
  dashboard: <FileText className="w-3.5 h-3.5" />,
  exception: <AlertTriangle className="w-3.5 h-3.5" />,
};

interface DataContractCardProps {
  contract: DataContractSummary;
  editable: boolean;
  onClick: (contract: DataContractSummary) => void;
}

export function DataContractCard({ contract, editable, onClick }: DataContractCardProps) {
  return (
    <button
      onClick={() => onClick(contract)}
      className="w-full text-left p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] hover:border-[var(--accent)] transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[var(--muted)]">{SCOPE_ICONS[contract.scope]}</span>
          <span className="text-xs font-medium text-[var(--muted)] uppercase">
            {SCOPE_LABELS[contract.scope] || contract.scope}
          </span>
          {contract.autoSynced && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 font-medium">
              Auto-synced
            </span>
          )}
          {contract.isException && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium">
              Exception
            </span>
          )}
        </div>
        {contract.slaTier && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--muted)] font-medium">
            {contract.slaTier}
          </span>
        )}
      </div>
      <h4 className="text-sm font-medium text-[var(--foreground)] truncate">{contract.scopeRef}</h4>
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--muted)]">
        {contract.ownerTeam && <span>Team: {contract.ownerTeam}</span>}
        {contract.expectedFreshnessMinutes && <span>Freshness: {contract.expectedFreshnessMinutes}m</span>}
        {contract.exceptions.length > 0 && (
          <span>{contract.exceptions.length} exception{contract.exceptions.length > 1 ? 's' : ''}</span>
        )}
      </div>
      {!editable && (
        <p className="text-[10px] text-[var(--muted)] mt-2 italic">View only — enable data contracts in settings to edit</p>
      )}
    </button>
  );
}
```

- [ ] **Step 2: Create DataContractsTab component**

```typescript
// components/sources/DataContractsTab.tsx
'use client';

import React, { useState } from 'react';
import { Loader2, FileText } from 'lucide-react';
import { useDataContracts, type DataContractSummary } from './useDataContracts';
import { DataContractCard } from './DataContractCard';

interface DataContractsTabProps {
  dataContractsEnabled: boolean;
}

export function DataContractsTab({ dataContractsEnabled }: DataContractsTabProps) {
  const { contracts, loading, error } = useDataContracts();
  const [selectedContract, setSelectedContract] = useState<DataContractSummary | null>(null);

  // Group contracts: group-level first, then exceptions
  const groupContracts = contracts.filter(c => !c.isException);
  const exceptionContracts = contracts.filter(c => c.isException);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12 text-[var(--muted)]">
        Failed to load data contracts
      </div>
    );
  }

  if (contracts.length === 0) {
    return (
      <div className="text-center py-12">
        <FileText className="w-8 h-8 mx-auto mb-3 text-[var(--muted)]" />
        <p className="text-sm text-[var(--muted)]">
          No data contracts yet. Set SLAs on data assets in pipeline overview to auto-generate contracts.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Group Contracts */}
      {groupContracts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
            Group Contracts ({groupContracts.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {groupContracts.map(c => (
              <DataContractCard
                key={c.id}
                contract={c}
                editable={dataContractsEnabled}
                onClick={setSelectedContract}
              />
            ))}
          </div>
        </div>
      )}

      {/* Exception Contracts */}
      {exceptionContracts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
            Exception Contracts ({exceptionContracts.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {exceptionContracts.map(c => (
              <DataContractCard
                key={c.id}
                contract={c}
                editable={dataContractsEnabled}
                onClick={setSelectedContract}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add tab to sources page**

In `app/(dashboard)/dashboard/sources/page.tsx`, add a "Data Contracts" tab. After the existing filter bar, add tab navigation:

```tsx
const [activeTab, setActiveTab] = useState<'sources' | 'data-contracts'>('sources');

// In the JSX, before the source cards grid:
<div className="flex gap-2 mb-4">
  <button
    onClick={() => setActiveTab('sources')}
    className={cn('px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
      activeTab === 'sources' ? 'bg-[var(--accent)] text-white' : 'text-[var(--muted)] hover:text-[var(--foreground)]'
    )}
  >
    Sources
  </button>
  <button
    onClick={() => setActiveTab('data-contracts')}
    className={cn('px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
      activeTab === 'data-contracts' ? 'bg-[var(--accent)] text-white' : 'text-[var(--muted)] hover:text-[var(--foreground)]'
    )}
  >
    Data Contracts
  </button>
</div>

{activeTab === 'sources' ? (
  /* existing source cards grid */
) : (
  <DataContractsTab dataContractsEnabled={/* fetch from pipeline settings */} />
)}
```

Add import:
```typescript
import { DataContractsTab } from '@/components/sources/DataContractsTab';
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add components/sources/DataContractsTab.tsx components/sources/DataContractCard.tsx app/(dashboard)/dashboard/sources/page.tsx
git commit -m "feat: add Data Contracts tab to sources page"
```

---

### Task 3: Compliance Badge Component

**Files:**
- Create: `components/lineage/ComplianceBadge.tsx`
- Modify: `components/lineage/UnifiedNodes.tsx`

- [ ] **Step 1: Create ComplianceBadge component**

```typescript
// components/lineage/ComplianceBadge.tsx
'use client';

import React from 'react';

export type ComplianceBadgeStatus = 'compliant' | 'override' | 'violation' | 'missing_sla' | 'none';

const BADGE_CONFIG: Record<ComplianceBadgeStatus, { label: string; color: string; bg: string } | null> = {
  compliant: { label: 'Compliant', color: '#10B981', bg: 'rgba(16, 185, 129, 0.15)' },
  override: { label: 'Override', color: '#3B82F6', bg: 'rgba(59, 130, 246, 0.15)' },
  violation: { label: 'Violation', color: '#EF4444', bg: 'rgba(239, 68, 68, 0.15)' },
  missing_sla: { label: 'Missing SLA', color: '#F59E0B', bg: 'rgba(245, 158, 11, 0.15)' },
  none: null,
};

interface ComplianceBadgeProps {
  status: ComplianceBadgeStatus;
}

export function ComplianceBadge({ status }: ComplianceBadgeProps) {
  const config = BADGE_CONFIG[status];
  if (!config) return null;

  return (
    <div
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wide uppercase whitespace-nowrap"
      style={{
        backgroundColor: config.bg,
        color: config.color,
        border: `1px solid ${config.color}33`,
      }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: config.color }}
      />
      {config.label}
    </div>
  );
}
```

- [ ] **Step 2: Add ComplianceBadge to UnifiedNodes**

In `components/lineage/UnifiedNodes.tsx`, import `ComplianceBadge` and render it alongside the existing `SLABadge`:

```typescript
import { ComplianceBadge } from './ComplianceBadge';
```

Find the line where `SLABadge` is rendered (currently `<PolicyBadge status={policyStatus} profileName={data.policyProfileName} />`), and add the compliance badge next to it:

```tsx
<SLABadge status={slaStatus} profileName={data.slaProfileName} />
{data.complianceStatus && (
  <ComplianceBadge status={data.complianceStatus} />
)}
```

Note: The `complianceStatus` field on the node data will be populated by the lineage data enrichment (which reads from the compliance engine). For now, the badge renders when the field is present.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/lineage/ComplianceBadge.tsx components/lineage/UnifiedNodes.tsx
git commit -m "feat: add ComplianceBadge component for node-level compliance display"
```

---

### Task 4: SLA Section in Inspector Panel

**Files:**
- Create: `components/lineage/pipeline-overview/SLASection.tsx`
- Modify: `components/lineage/pipeline-overview/InspectorPanel.tsx`

- [ ] **Step 1: Create SLASection component**

```typescript
// components/lineage/pipeline-overview/SLASection.tsx
'use client';

import React from 'react';
import { ComplianceBadge, type ComplianceBadgeStatus } from '../ComplianceBadge';
import type { ComplianceStatus } from '@/lib/compliance/field-comparison';

interface SLAFieldDisplay {
  fieldName: string;
  label: string;
  slaValue: unknown;
  baselineValue: unknown | null;
  complianceStatus: ComplianceStatus | null;
}

interface SLASectionProps {
  fields: SLAFieldDisplay[];
  overallCompliance: ComplianceBadgeStatus;
  hasContract: boolean;
  contractScopeRef?: string;
  isMultiSelect?: boolean;
  selectedCount?: number;
}

const COMPLIANCE_TO_BADGE: Record<string, string> = {
  compliant: '#10B981',
  override: '#3B82F6',
  violation: '#EF4444',
  unknown: '#6B7280',
};

export function SLASection({
  fields,
  overallCompliance,
  hasContract,
  contractScopeRef,
  isMultiSelect,
  selectedCount,
}: SLASectionProps) {
  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-[var(--foreground)] uppercase tracking-wide">
          SLA {isMultiSelect ? `(${selectedCount} nodes selected)` : ''}
        </h4>
        <ComplianceBadge status={overallCompliance} />
      </div>

      {/* Contract banner */}
      {hasContract && (
        <div className="p-2 rounded-md bg-blue-500/10 border border-blue-500/20 text-[11px] text-blue-400">
          This node has a data contract{contractScopeRef ? ` (${contractScopeRef})` : ''}.
          SLA changes will show as override or violation against the contract.
        </div>
      )}

      {/* Fields */}
      <div className="space-y-2">
        {fields.map(f => (
          <div key={f.fieldName} className="flex items-center justify-between">
            <span className="text-[11px] text-[var(--muted)]">{f.label}</span>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-medium text-[var(--foreground)]">
                {f.slaValue != null ? String(f.slaValue) : '—'}
              </span>
              {f.complianceStatus && f.complianceStatus !== 'unknown' && (
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: COMPLIANCE_TO_BADGE[f.complianceStatus] || '#6B7280' }}
                  title={f.complianceStatus}
                />
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Multi-select hint */}
      {!isMultiSelect && (
        <p className="text-[10px] text-[var(--muted)] italic mt-2">
          💡 Shift+Click nodes to select multiple
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add SLASection to InspectorPanel**

In `components/lineage/pipeline-overview/InspectorPanel.tsx`, import and render `SLASection` inside the `NodeInspector` function, after the existing monitor health/coverage section:

```typescript
import { SLASection } from './SLASection';
```

Add a new section in the inspector:

```tsx
{/* SLA Section */}
<div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
  <SLASection
    fields={slaFields}
    overallCompliance={nodeComplianceStatus}
    hasContract={!!nodeContract}
    contractScopeRef={nodeContract?.scopeRef}
  />
</div>
```

The `slaFields` and `nodeComplianceStatus` will need to be computed from the node's resolved SLA and the compliance evaluation engine. This wiring depends on how the pipeline overview fetches node data. For now, add the component rendering with placeholder data.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/lineage/pipeline-overview/SLASection.tsx components/lineage/pipeline-overview/InspectorPanel.tsx
git commit -m "feat: add SLA section with per-field compliance to inspector panel"
```

---

### Task 5: Shift+Click Multi-Select

**Files:**
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx`
- Modify: `components/lineage/pipeline-overview/InspectorPanel.tsx`
- Modify: `components/lineage/pipeline-overview/types.ts`

- [ ] **Step 1: Add multi-select state to lineage page**

In `app/(dashboard)/dashboard/lineage/page.tsx`, add state for multi-select:

```typescript
const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());

const handleNodeClick = useCallback((nodeId: string, event: React.MouseEvent) => {
  if (event.shiftKey) {
    // Multi-select: toggle this node in selection
    setSelectedNodeIds(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  } else {
    // Single select: clear multi-select, open inspector for this node
    setSelectedNodeIds(new Set([nodeId]));
    // existing single-node inspector logic
  }
}, []);
```

- [ ] **Step 2: Update InspectorTarget to support multi-select**

In `components/lineage/pipeline-overview/types.ts`, extend the types:

```typescript
export interface MultiNodeTarget {
  type: 'multi';
  nodeIds: string[];
  nodes: ViewNode[];
}

export type InspectorTarget =
  | { type: 'node'; node: ViewNode }
  | { type: 'edge'; edge: ViewEdge }
  | MultiNodeTarget;
```

- [ ] **Step 3: Handle multi-select in InspectorPanel**

In `InspectorPanel.tsx`, add a branch for multi-select targets:

```tsx
if (target.type === 'multi') {
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-[var(--foreground)]">
          {target.nodes.length} nodes selected
        </h3>
        <button onClick={onClose} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X className="w-4 h-4" />
        </button>
      </div>
      <SLASection
        fields={commonFields}
        overallCompliance="none"
        hasContract={false}
        isMultiSelect={true}
        selectedCount={target.nodes.length}
      />
      {/* Bulk SLA apply button */}
      <button className="w-full py-2 px-4 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity">
        Apply SLA to All Selected
      </button>
    </div>
  );
}
```

The `commonFields` are computed by finding fields common to all selected node types (using `INTEGRATION_TYPE_TO_OVERRIDE_KEY` to determine which override schema applies to each node).

- [ ] **Step 4: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add app/(dashboard)/dashboard/lineage/page.tsx components/lineage/pipeline-overview/InspectorPanel.tsx components/lineage/pipeline-overview/types.ts
git commit -m "feat: add Shift+Click multi-select for bulk SLA assignment"
```

---

### Task 6: Auto-Discovery Prompts

**Files:**
- Create: `components/pipeline/AutoDiscoveryPrompt.tsx`
- Modify: `app/(dashboard)/dashboard/pipeline/page.tsx`

- [ ] **Step 1: Create AutoDiscoveryPrompt component**

```typescript
// components/pipeline/AutoDiscoveryPrompt.tsx
'use client';

import React from 'react';
import { Database, GitBranch, BarChart3, X } from 'lucide-react';

interface DiscoveredScope {
  scope: 'schema' | 'dbt_model_group' | 'dashboard';
  items: string[];
}

interface AutoDiscoveryPromptProps {
  discovered: DiscoveredScope;
  onCreateAll: (scope: string, items: string[]) => void;
  onCreateSelected: (scope: string, items: string[]) => void;
  onDismiss: () => void;
}

const SCOPE_CONFIG = {
  schema: { icon: Database, label: 'schemas', verb: 'found' },
  dbt_model_group: { icon: GitBranch, label: 'dbt model groups', verb: 'found' },
  dashboard: { icon: BarChart3, label: 'dashboards', verb: 'found' },
};

export function AutoDiscoveryPrompt({ discovered, onCreateAll, onCreateSelected, onDismiss }: AutoDiscoveryPromptProps) {
  const config = SCOPE_CONFIG[discovered.scope];
  const Icon = config.icon;

  return (
    <div className="p-4 rounded-lg border border-blue-500/30 bg-blue-500/10">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-[var(--foreground)]">
            We {config.verb} {discovered.items.length} {config.label}
          </span>
        </div>
        <button onClick={onDismiss} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <p className="text-xs text-[var(--muted)] mt-1 mb-3">
        Create data contracts for these {config.label}?
      </p>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {discovered.items.slice(0, 8).map(item => (
          <span key={item} className="text-[10px] px-2 py-1 rounded bg-[var(--subtle-bg)] text-[var(--foreground)]">
            {item}
          </span>
        ))}
        {discovered.items.length > 8 && (
          <span className="text-[10px] px-2 py-1 rounded bg-[var(--subtle-bg)] text-[var(--muted)]">
            +{discovered.items.length - 8} more
          </span>
        )}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onCreateAll(discovered.scope, discovered.items)}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90"
        >
          Create for All
        </button>
        <button
          onClick={() => onCreateSelected(discovered.scope, discovered.items)}
          className="px-3 py-1.5 text-xs font-medium rounded-md border border-[var(--subtle-border)] text-[var(--foreground)] hover:bg-[var(--subtle-bg)]"
        >
          Pick & Choose
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire into pipeline page**

In `app/(dashboard)/dashboard/pipeline/page.tsx`, add the auto-discovery prompt after the status bar. The prompt checks if there are connected warehouse/dbt/BI tools that have discoverable scopes (schemas, model groups, dashboards) and no existing contracts for them:

```typescript
import { AutoDiscoveryPrompt } from '@/components/pipeline/AutoDiscoveryPrompt';
```

The actual discovery logic (querying schemas from warehouse metadata, model groups from dbt manifest) will be wired when those adapters exist. For now, the component is created and renderable.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/pipeline/AutoDiscoveryPrompt.tsx app/(dashboard)/dashboard/pipeline/page.tsx
git commit -m "feat: add auto-discovery prompt component for data contract creation"
```

---

### Task 7: Final Verification

- [ ] **Step 1: Run full TypeScript check**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 2: Run all tests**

Run: `npx vitest run --reporter=verbose`
Expected: All tests pass.

- [ ] **Step 3: Visual smoke test**

Verify in browser:
1. Sources page shows "Sources" and "Data Contracts" tabs
2. Pipeline settings shows "Data Contracts" toggle
3. Lineage page renders compliance badges on nodes (when compliance data present)
4. Inspector panel shows SLA section with "Shift+Click" hint
5. Shift+Click selects multiple nodes in pipeline overview

- [ ] **Step 4: Commit any remaining fixes**
