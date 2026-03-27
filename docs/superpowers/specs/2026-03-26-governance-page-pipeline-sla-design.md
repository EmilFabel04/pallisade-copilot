# Governance Page & Pipeline SLA Design

**Date:** 2026-03-26 (updated 2026-03-27)
**Status:** Approved
**Approach:** Lift & Extend (Approach A)

## Overview

Rename "Data Contracts" to "Data SLAs" across the entire codebase and UI. Split Data SLAs out of the Sources page into a new Governance page with two tabs: Data SLAs and Pipeline SLAs. Add search and filtering to both. Build a full Pipeline SLA mode in the lineage Pipeline Overview tab, mirroring the existing Data SLA mode pattern. Both lineage mode and Governance page read/write the same backing store. Drop owner/team config fields to reduce friction.

---

## 0. Global Rename & Simplification

### Rename: Data Contracts → Data SLAs

All references to "Data Contracts" become "Data SLAs" — in UI labels, component names, file names, API routes, types, and comments. This includes:

- **UI labels:** "Data Contracts" tab → "Data SLAs" tab, "Create Contract" → "Create Data SLA", card badges, tooltips, empty states, settings toggles
- **Component names:** `DataContractsTab` → `DataSLAsTab`, `DataContractCard` → `DataSLACard`, `useDataContracts` → `useDataSLAs`
- **File names:** `DataContractsTab.tsx` → `DataSLAsTab.tsx`, `DataContractCard.tsx` → `DataSLACard.tsx`, `useDataContracts.ts` → `useDataSLAs.ts`
- **API routes:** `/api/pipeline/[stackId]/data-contracts/` → `/api/pipeline/[stackId]/data-slas/`
- **Types:** `DataContractInput` → `DataSLAInput`, `PipelineDataContract` → `PipelineDataSLA`, `ContractScope` → `DataSLAScope`
- **Prisma model:** `PipelineDataContract` → `PipelineDataSLA` (with migration)
- **Internal references:** variable names, hook names, comments, error messages

### Drop Owner Config

Remove ownership fields from the data model and UI to simplify the experience:

- **Remove from types/schema:** `ownerUser`, `ownerTeam`, `contactChannel` fields from `DataSLAInput` (formerly `DataContractInput`)
- **Remove from UI:** Owner/team inputs in create/edit flows, owner/team display on cards
- **Remove from filters:** No "Owner/Team" filter on the Governance page
- **Remove from search:** No owner/team in search scope
- **Database migration:** Drop columns or leave nullable (no breaking change since they become unused)

**Rationale:** Owner config is organizational metadata for multi-team setups with defined producer/consumer relationships. Single-team or small-team users don't need it and it adds config friction at onboarding. If needed later, it can be re-added as an optional layer.

---

## 1. Governance Page & Navigation

**New route:** `/dashboard/governance` with two tabs.

**Sidebar:**
- Add "Governance" entry to the sidebar (shield or scale icon), positioned between Sources and Pipeline (or nearby in the nav)
- Single entry pointing to `/dashboard/governance`
- Remove the "Data SLAs" tab from the Sources page — Sources becomes sources-only

**Tab behavior:**
- URL param controls active tab: `?tab=data-slas` (default) or `?tab=pipeline-slas`
- Tab state persists in URL for bookmarkable links

**Page header:**
- Title: "Governance"
- Subtitle: "Manage data SLAs and pipeline SLA expectations"
- Tabs below header, styled consistently with existing tab patterns (Sources, Lineage)

---

## 2. Data SLAs Tab (Enhanced)

The existing Data SLAs tab (formerly DataContractsTab) lifted to the Governance page with search and filtering added.

### New Features

**Search bar:**
- Text input at the top, searches across SLA name and scope reference
- Debounced (300ms), filters card grid in real-time

**Filter bar** (horizontal, below search):
- **SLA Tier:** multi-select chips (T0, T1, T2, T3)
- **Scope Type:** multi-select chips (Schema, dbt Model Group, Dashboard, Exception)
- Clear all filters button when any filter is active

### Preserved Features
- Enable/disable toggle, allow overrides toggle, violation alerting toggle — moved to a "Settings" collapsible section or gear icon to reduce top-level clutter
- "Create Data SLA" button
- SLA cards in responsive grid (same card component, renamed to `DataSLACard`)

### Removed
- "Group Contracts" / "Exception Contracts" section headers — replaced by scope type filter. Exception SLAs already have an amber badge on the card.
- Owner/team fields from create/edit flows and card display

---

## 3. Pipeline SLAs Tab

Same search + filter bar + card grid pattern as Data SLAs tab.

### Search & Filters

**Search bar:**
- Searches across node name, platform, profile name

**Filter bar:**
- **SLA Tier:** multi-select chips (T0, T1, T2, T3)
- **Domain:** multi-select chips (Ingestion, Orchestration, Transform, BI, Warehouse)
- **Platform:** dropdown populated from actual assigned nodes (Fivetran, Airflow, dbt, BigQuery, etc.)
- Clear all filters button

### Card Design (Per-Node)

Each card represents a single node with a pipeline SLA assigned:

- **Header:** Node name + platform icon/badge
- **Metadata row:** Domain badge (colored like lineage layer colors), SLA tier badge, profile name
- **Key expectations:** 2-3 most relevant fields for that domain (e.g., for ingestion: sync lag tolerance, failure tolerance)
- **Compliance indicator:** Small dot (green/red/gray) showing current compliance status
- **Click action:** Opens side drawer with full SLA details and edit capability — same fields as `PipelineSLAEditor` but in drawer form

### Empty State
"No pipeline SLAs assigned yet. Use Pipeline SLA mode in lineage or create one here."

### Create Flow
"Assign Pipeline SLA" button opens a flow:
1. Pick nodes from a searchable list of pipeline-eligible nodes in the current stack (fetched from the pipeline overview's rendered view — tool nodes like Fivetran, Airflow, dbt, BigQuery, etc.)
2. Select profile (T0-T3) or custom
3. Set tool-specific fields based on detected domain (auto-detected from selected node's layer/platform)
4. Save via POST to `/api/schedule/policies/assign` with `assignmentType: 'direct'`

---

## 4. Pipeline SLA Mode in Lineage

Full SLA mode on the Pipeline Overview tab, mirroring Data SLA mode on the Data Lineage tab.

### Entry
- "Pipeline SLA" button in the Pipeline Overview header (only visible when `activeTab === 'control-plane'`)
- Styled same as the "Data SLA" button

### Mode Activation
- `pipelineSlaMode` boolean state
- Disables normal click/inspector behavior
- Shift+Click to multi-select tool nodes
- Escape exits mode

### Toolbar (PipelineSLAModeToolbar)
- Pulsing dot + "Pipeline SLA Mode" label
- Selection counter: "X of Y nodes selected"
- Badge legend (profile badge = Pipeline SLA assigned, dashed circle = none)
- "Save All" and "Exit Pipeline SLA Mode" buttons

### Editor Panel (PipelineSLAEditorPanel — right sidebar, 320px)
- Profile selector dropdown (T0-T3 + custom DB profiles)
- Tool-specific fields auto-detected from selected nodes' domains
- When multi-selecting nodes of mixed domains: show union of all applicable fields with domain labels
- Override mechanism: local edits on top of base profile, "(custom)" badge
- Apply scope options:
  - **Selected:** apply to selected nodes only
  - **Downstream:** apply to selected + all downstream nodes in the pipeline
  - **All of Domain:** apply to all nodes matching the dominant domain (e.g., all ingestion nodes)
- "Remove Pipeline SLA" button (when nodes already have one)

### Save Flow
- POST to `/api/schedule/policies/assign` with `assignmentType: 'direct'` and `nodeDomain` set
- Re-resolves policies via `/api/schedule/policies/resolve`
- Updates `nodeSLAs` map — cards on Governance page reflect changes immediately

### Relationship to Inline Editor
- The `PipelineSLAEditor` inline component in `InspectorPanel` stays as a quick-edit shortcut when not in full SLA mode
- When Pipeline SLA mode is active, clicking a node selects it for the editor panel instead of opening the inspector

---

## 5. Data Model & API

### No New Database Tables

Both features use existing backing stores:
- **Pipeline SLAs:** `PolicyAssignment` table (already stores profile ID, assignment type, node FQNs, overrides, domain)
- **Data SLAs:** `PipelineDataSLA` table (renamed from `PipelineDataContract`, with migration)

### Schema Changes
- Rename `PipelineDataContract` model to `PipelineDataSLA` in Prisma schema (with `@@map` to avoid table rename, or a proper migration)
- Drop `ownerUser`, `ownerTeam`, `contactChannel` columns (nullable, non-breaking — can be done as a separate migration or left as unused)

### API Route Rename
- `/api/pipeline/[stackId]/data-contracts/` → `/api/pipeline/[stackId]/data-slas/`
- `/api/pipeline/[stackId]/data-contracts/[contractId]/` → `/api/pipeline/[stackId]/data-slas/[slaId]/`

### New API Endpoint

**GET `/api/schedule/policies/assignments?stackId=X`**
- Returns all policy assignments for a stack with resolved profile names and node metadata
- Used by the Pipeline SLAs tab to populate the card grid
- Supports optional query params for server-side filtering: `?domain=ingestion&tier=T0`

### Bug Fix

**PipelineSLAEditor.tsx:** Change `assignmentType: 'explicit'` to `assignmentType: 'direct'` — current code sends an invalid assignment type that would 400.

### Bi-Directional Sync

Both lineage mode and Governance page write to the same `PolicyAssignment` records and read via the same resolve endpoint. No sync layer needed — same data, two views.

---

## 6. What Gets Removed / Moved

### Removed from Sources Page
- "Data SLAs" tab (formerly "Data Contracts") and tab navigation — Sources becomes a single-view page (just sources list)
- Tab component import and conditional render removed from `sources/page.tsx`
- URL param `?tab=data-contracts` handling removed

### Removed from Data Model & UI
- `ownerUser`, `ownerTeam`, `contactChannel` fields — dropped from types, API validation, create/edit forms, card display, search, and filters

### Removed from InspectorPanel
- Pipeline SLA section stays as a quick-view/quick-edit, but when `pipelineSlaMode` is active, inspector panel closes and dedicated `PipelineSLAEditorPanel` takes over the right sidebar

### Renamed (Data Contracts → Data SLAs)
- All component files, type files, API route directories, Prisma model, UI labels, variable names, and comments

### Moved
- Data SLAs tab rendered inside the Governance page instead of Sources
- `useDataSLAs()` hook (renamed from `useDataContracts()`) stays in `components/sources/` or moves to `components/governance/`

### New Files
- `app/(dashboard)/dashboard/governance/page.tsx` — Governance page with tab routing
- `components/governance/PipelineSLAsTab.tsx` — Pipeline SLAs tab with search/filter/card grid
- `components/governance/PipelineSLACard.tsx` — per-node card component
- `components/governance/GovernanceFilters.tsx` — shared search + filter bar (used by both tabs)
- `components/lineage/PipelineSLAEditorPanel.tsx` — right sidebar editor for Pipeline SLA mode (mirrors SLAEditorPanel)
- `components/lineage/PipelineSLAModeToolbar.tsx` — toolbar for Pipeline SLA mode
- `app/api/schedule/policies/assignments/route.ts` — list endpoint for Pipeline SLA cards
