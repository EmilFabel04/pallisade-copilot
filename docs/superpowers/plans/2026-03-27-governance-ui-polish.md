# Governance UI Polish — Filter Bar, Cards, SLA Editing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade governance tabs with sources-style filter/search bars, ensure consistent card styling, always allow SLA editing in data asset details, and remove pipeline SLAs from tool details panel.

**Architecture:** Replace the existing `GovernanceFilters` component with a new sources-style toolbar using `FilterDropdown` pattern. Remove the `data_contract` edit-blocking conditional in `DataAssetDetailPanel`. Remove the Pipeline SLA section from `InspectorPanel` (tool details in pipeline overview).

**Tech Stack:** Next.js, React, TypeScript, Lucide icons, CSS variables

---

### Task 1: Replace GovernanceFilters with sources-style FilterToolbar

**Files:**
- Rewrite: `components/governance/GovernanceFilters.tsx`

The current `GovernanceFilters` uses tiny inline chips. Replace it with the same `FilterDropdown` + search pattern from the sources page.

- [ ] **Step 1: Rewrite GovernanceFilters.tsx**

Replace the entire file with this implementation that mirrors the sources page toolbar:

```tsx
'use client';

import React, { useState } from 'react';
import { Search, Filter, X } from 'lucide-react';

interface FilterConfig {
  label: string;
  options: { value: string; label: string; dot?: string }[];
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
  totalCount: number;
  filteredCount: number;
}

export function GovernanceFilters({
  search,
  onSearchChange,
  searchPlaceholder,
  filters,
  onClearAll,
  hasActiveFilters,
  totalCount,
  filteredCount,
}: GovernanceFiltersProps) {
  const [openFilter, setOpenFilter] = useState<string | null>(null);

  const activeFilterCount =
    filters.reduce((acc, f) => acc + f.selected.size, 0) + (search ? 1 : 0);

  return (
    <div className="space-y-3 mb-6">
      {/* Toolbar row */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-faint)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)]
                       text-sm text-[var(--text)] placeholder:text-[var(--text-faint)]
                       focus:outline-none focus:border-[var(--border-medium)]"
          />
          {search && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-faint)]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Filter dropdowns */}
        {filters.map((filter) => (
          <FilterDropdown
            key={filter.label}
            label={filter.label}
            active={filter.selected.size > 0}
            count={filter.selected.size}
            open={openFilter === filter.label}
            onToggle={() => setOpenFilter(openFilter === filter.label ? null : filter.label)}
            onClear={() => {
              filter.options.forEach((opt) => {
                if (filter.selected.has(opt.value)) filter.onToggle(opt.value);
              });
            }}
          >
            {filter.options.map((opt) => (
              <FilterItem
                key={opt.value}
                label={opt.label}
                active={filter.selected.has(opt.value)}
                onClick={() => filter.onToggle(opt.value)}
                dot={opt.dot}
              />
            ))}
          </FilterDropdown>
        ))}
      </div>

      {/* Active filters summary */}
      {hasActiveFilters && (
        <div className="flex items-center gap-2 text-xs text-[var(--text-faint)]">
          <span>
            Showing {filteredCount} of {totalCount}
          </span>
          <button onClick={onClearAll} className="text-[var(--accent-2)] hover:underline">
            Clear all filters
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Reusable filter components (same pattern as sources page) ────

function FilterDropdown({
  label,
  active,
  count,
  open,
  onToggle,
  onClear,
  children,
}: {
  label: string;
  active: boolean;
  count: number;
  open: boolean;
  onToggle: () => void;
  onClear: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm transition-colors
          ${
            active
              ? 'border-[var(--accent)] text-[var(--accent-2)] bg-[var(--accent)]/5'
              : 'border-[var(--subtle-border)] text-[var(--text-tertiary)] hover:text-[var(--text)]'
          }`}
      >
        <Filter className="w-3.5 h-3.5" />
        {label}
        {count > 0 && (
          <span className="ml-1 px-1.5 py-0.5 rounded-full bg-[var(--accent)] text-white text-[10px] font-medium">
            {count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 w-52 rounded-lg border border-[var(--subtle-border)]
                       bg-[var(--surface)] shadow-xl z-50 py-1">
          {children}
          {active && (
            <button
              onClick={onClear}
              className="w-full px-3 py-2 text-xs text-[var(--text-faint)] hover:text-[var(--text-tertiary)]
                         border-t border-[var(--subtle-border)] transition-colors"
            >
              Clear filter
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function FilterItem({
  label,
  active,
  onClick,
  dot,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  dot?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors
        ${active ? 'bg-[var(--hover-bg)] text-[var(--text)]' : 'text-[var(--text-secondary)] hover:bg-[var(--hover-bg)]'}`}
    >
      {dot && <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: dot }} />}
      {label}
      {active && <span className="ml-auto text-[var(--accent-2)]">&#10003;</span>}
    </button>
  );
}
```

- [ ] **Step 2: Verify the app compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx next build --no-lint 2>&1 | head -30`
Expected: No TypeScript errors related to GovernanceFilters

- [ ] **Step 3: Commit**

```bash
git add components/governance/GovernanceFilters.tsx
git commit -m "feat: upgrade GovernanceFilters to sources-style filter toolbar"
```

---

### Task 2: Update DataSLAsTab to use new GovernanceFilters props

**Files:**
- Modify: `components/sources/DataSLAsTab.tsx:155-202`

The new `GovernanceFilters` requires `totalCount` and `filteredCount` props. Update the DataSLAsTab to pass them.

- [ ] **Step 1: Add totalCount and filteredCount props**

In `components/sources/DataSLAsTab.tsx`, find the `<GovernanceFilters` usage around line 167 and update it:

Replace:
```tsx
      {contracts.length > 0 && (
        <GovernanceFilters
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search by name or scope..."
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
              label: 'Scope',
              options: [
                { value: 'schema', label: 'Schema' },
                { value: 'dbt_model_group', label: 'dbt Model Group' },
                { value: 'dashboard', label: 'Dashboard' },
                { value: 'exception', label: 'Exception' },
              ],
              selected: scopeFilter,
              onToggle: v => toggleFilter(scopeFilter, setScopeFilter, v),
            },
          ]}
          onClearAll={() => {
            setSearch('');
            setTierFilter(new Set());
            setScopeFilter(new Set());
          }}
          hasActiveFilters={search.length > 0 || tierFilter.size > 0 || scopeFilter.size > 0}
        />
      )}
```

With:
```tsx
      {contracts.length > 0 && (
        <GovernanceFilters
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search by name or scope..."
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
              label: 'Scope',
              options: [
                { value: 'schema', label: 'Schema' },
                { value: 'dbt_model_group', label: 'dbt Model Group' },
                { value: 'dashboard', label: 'Dashboard' },
                { value: 'exception', label: 'Exception' },
              ],
              selected: scopeFilter,
              onToggle: v => toggleFilter(scopeFilter, setScopeFilter, v),
            },
          ]}
          onClearAll={() => {
            setSearch('');
            setTierFilter(new Set());
            setScopeFilter(new Set());
          }}
          hasActiveFilters={search.length > 0 || tierFilter.size > 0 || scopeFilter.size > 0}
          totalCount={contracts.length}
          filteredCount={filteredSLAs.length}
        />
      )}
```

- [ ] **Step 2: Commit**

```bash
git add components/sources/DataSLAsTab.tsx
git commit -m "feat: pass totalCount/filteredCount to GovernanceFilters in DataSLAsTab"
```

---

### Task 3: Update PipelineSLAsTab to use new GovernanceFilters props

**Files:**
- Modify: `components/governance/PipelineSLAsTab.tsx:73-133`

Same change — pass the new required props.

- [ ] **Step 1: Add totalCount and filteredCount props**

In `components/governance/PipelineSLAsTab.tsx`, find the `<GovernanceFilters` usage around line 75 and update it:

Replace:
```tsx
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
```

With:
```tsx
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
              { value: 'ingestion', label: 'Ingestion', dot: '#10B981' },
              { value: 'orchestration', label: 'Orchestration', dot: '#F97316' },
              { value: 'transform', label: 'Transform', dot: '#F59E0B' },
              { value: 'bi', label: 'BI', dot: '#3B82F6' },
              { value: 'warehouse', label: 'Warehouse', dot: '#8B5CF6' },
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
        totalCount={items.length}
        filteredCount={filtered.length}
      />
```

- [ ] **Step 2: Commit**

```bash
git add components/governance/PipelineSLAsTab.tsx
git commit -m "feat: pass totalCount/filteredCount and domain dots to GovernanceFilters in PipelineSLAsTab"
```

---

### Task 4: Upgrade card styling for both DataSLACard and PipelineSLACard

**Files:**
- Modify: `components/sources/DataSLACard.tsx`
- Modify: `components/governance/PipelineSLACard.tsx`

Both cards currently use `rounded-xl border border-[var(--subtle-border)] bg-[var(--overlay-bg)]`. Upgrade them to match the sources page card style with `bg-[var(--surface-raised)]`, better hover effects, and subtle shadow.

- [ ] **Step 1: Update DataSLACard styling**

In `components/sources/DataSLACard.tsx`, replace the button className:

Replace:
```tsx
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--overlay-bg)] hover:border-[var(--accent)]/30 transition-all"
```

With:
```tsx
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] hover:border-[var(--accent)]/30 hover:shadow-md hover:shadow-black/5 transition-all group"
```

- [ ] **Step 2: Update PipelineSLACard styling**

In `components/governance/PipelineSLACard.tsx`, replace the button className:

Replace:
```tsx
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--overlay-bg)] hover:border-[var(--accent)]/30 transition-all"
```

With:
```tsx
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] hover:border-[var(--accent)]/30 hover:shadow-md hover:shadow-black/5 transition-all group"
```

- [ ] **Step 3: Commit**

```bash
git add components/sources/DataSLACard.tsx components/governance/PipelineSLACard.tsx
git commit -m "feat: upgrade governance card styling to match sources page"
```

---

### Task 5: Always allow SLA editing in DataAssetDetailPanel

**Files:**
- Modify: `components/lineage/DataAssetDetailPanel.tsx:1335-1358`

Currently when `slaInfo.source === 'data_contract'`, editing is blocked and only a "View Data SLA" link is shown. Remove this conditional so the edit button always appears.

- [ ] **Step 1: Replace the data_contract conditional block**

In `components/lineage/DataAssetDetailPanel.tsx`, find the block starting at line 1335:

Replace:
```tsx
              {slaInfo.source === 'data_contract' ? (
                <a
                  href="/dashboard/sources"
                  onClick={(e) => {
                    e.preventDefault();
                    window.location.href = '/dashboard/governance?tab=data-slas';
                  }}
                  className="mt-2 text-[11px] text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  View Data SLA
                </a>
              ) : onEditSLA ? (
                <button
                  onClick={() => onEditSLA(node.id)}
                  className="mt-2 text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  Edit Data SLA
                </button>
              ) : null}
```

With:
```tsx
              {onEditSLA && (
                <button
                  onClick={() => onEditSLA(node.id)}
                  className="mt-2 text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  Edit Data SLA
                </button>
              )}
```

- [ ] **Step 2: Commit**

```bash
git add components/lineage/DataAssetDetailPanel.tsx
git commit -m "feat: always allow SLA editing in data asset details (remove data_contract block)"
```

---

### Task 6: Remove Pipeline SLA section from tool details InspectorPanel

**Files:**
- Modify: `components/lineage/pipeline-overview/InspectorPanel.tsx`

Remove the Pipeline SLA section (lines 446-486), the `editingPipelineSLA` state (line 250), and the imports for `SLASection` and `PipelineSLAEditor` (lines 19-20). Also remove the multi-select SLA section (lines 881-895).

- [ ] **Step 1: Remove SLASection and PipelineSLAEditor imports**

In `components/lineage/pipeline-overview/InspectorPanel.tsx`, remove these two import lines:

```tsx
import { SLASection } from './SLASection';
import { PipelineSLAEditor } from './PipelineSLAEditor';
```

- [ ] **Step 2: Remove editingPipelineSLA state**

Remove these lines (around line 249-251):

```tsx
  // Pipeline SLA inline editor state
  const [editingPipelineSLA, setEditingPipelineSLA] = useState(false);
```

- [ ] **Step 3: Remove the single-node Pipeline SLA section**

Remove the entire block from `{/* Pipeline SLA Section */}` through its closing `</div>` (lines 446-486):

```tsx
      {/* Pipeline SLA Section */}
      <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
        {editingPipelineSLA && nodeDomain && stackId ? (
          <PipelineSLAEditor
            ...
          />
        ) : (
          <SLASection
            ...
          />
        )}
      </div>
```

- [ ] **Step 4: Remove the multi-select Pipeline SLA section**

In the multi-select view (around lines 881-895), remove the SLASection block and the "Apply Pipeline SLA" button:

Replace:
```tsx
          <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <SLASection
              fields={[]}
              overallCompliance="none"
              hasContract={false}
              isMultiSelect={true}
              selectedCount={target.nodes.length}
            />
          </div>
          <button
            className="w-full py-2 px-4 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
            onClick={() => onCreateMultiMonitor?.(target.nodeIds)}
          >
            Apply Pipeline SLA to All Selected
          </button>
```

With nothing (delete those lines entirely).

- [ ] **Step 5: Remove unused imports if applicable**

Check if `SLASection`-related type imports (like `ComplianceBadgeStatus`, `ComplianceStatus`, `evaluateNodeCompliance`, `DOMAIN_SLA_SECTIONS`, `categoryToSLADomain`, `EffectiveSLAPolicy`, `SLADomain`) are still used elsewhere in the file. If they are only used for the SLA section computation, remove them too. Also remove the `SLAFieldDisplay` interface (lines 31-37) and `SECTION_FIELD_LABELS` (lines 39+) and `flattenSLAFields` function if they exist solely for the removed SLA display.

Note: Be careful — some of these may still be used for the `slaDisplay` computation that feeds other parts of the inspector. Only remove what is truly unused after the SLA section removal.

- [ ] **Step 6: Verify the app compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx next build --no-lint 2>&1 | tail -20`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 7: Commit**

```bash
git add components/lineage/pipeline-overview/InspectorPanel.tsx
git commit -m "feat: remove Pipeline SLA section from tool details panel"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run the dev server and verify**

Run: `cd /Users/emilfabel/pallisade-copilot && npx next build --no-lint 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 2: Create final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address any build issues from governance UI polish"
```
