# SLA & Data Contracts Unified Design

## Summary

Refactor the existing "policy/contract" system into two cleanly separated concepts: **SLAs** (operability expectations for all nodes) and **Data Contracts** (data asset expectations for tables/schemas, dbt models/groups, and dashboards). Rename "policy" to "SLA" across the entire codebase. Add a settings toggle that controls whether data contracts are view-only (auto-synced from SLAs) or editable (primary source of truth).

## Core Concepts

### SLAs (formerly "Policy")

- Apply to **all nodes**: tools and data assets
- Configured per-node in pipeline overview / lineage via SLA modal
- Fields adapt to node type using existing override schemas (warehouse, ingestion, orchestration, transformation, reporting, storage, observability, infrastructure)
- Inherit from pipeline-level SLA defaults (tiers T0, T1, T2, T3, T4)
- Monitors run against SLAs when contracts are disabled

### Data Contracts

- Apply to **data assets only**: tables/schemas, dbt model groups, dashboards
- Scoped at group level (schema/dataset, dbt model group, dashboard) with per-asset exception contracts
- Auto-discoverable from warehouse metadata, dbt manifest, and BI tool metadata
- Viewed in sources page
- When disabled: view-only, auto-synced from SLAs, owner fields blank
- When enabled: editable, becomes the primary source of truth for compliance

### Tools vs Data Assets

| Node Type | Gets | Why |
|-----------|------|-----|
| Tools (Fivetran, Airflow, dbt Cloud, BigQuery-as-engine) | SLAs only | Operability expectations, no data shape |
| Tables/schemas | Data contracts + SLAs | Has schema, consumers, freshness needs |
| dbt models/groups | Data contracts + SLAs | Has schema, tests, freshness needs |
| Dashboards | Data contracts + SLAs | Has upstream dependencies, refresh expectations |

## Settings Toggle

Located in pipeline settings. Two modes:

### SLAs Only (default)

- SLA edits on data assets auto-update the corresponding contract
- Contracts exist but are view-only in sources
- Owner fields on contracts stay blank
- Monitors compare actual results against SLA values
- Compliance badges show based on SLA tier baseline

### Data Contracts Enabled

- Contracts become editable and the primary source of truth for data assets
- SLA edits on data assets do NOT update the contract — they deviate from it
- Deviation produces compliance badges (compliant/override/violation)
- Monitors compare actual results against contract values (for data assets)
- Tools still use SLAs as their baseline (unchanged)
- Contract check monitor becomes available for data assets
- Confirmation dialog on toggle: explains contracts become source of truth

### Behavior Matrix

| Action | Contracts Disabled | Contracts Enabled |
|--------|-------------------|-------------------|
| SLA edit on data asset | Updates contract automatically | Does NOT update contract → compliance badge |
| SLA edit on tool | Updates tool SLA, monitors check against it | Same — tools only have SLAs |
| Contract in sources | View-only, auto-synced from SLAs, owner fields blank | Editable, primary source of truth |
| Compliance baseline for data assets | SLA tier (T0-T4) | Contract |
| Compliance baseline for tools | SLA tier (T0-T4) | SLA tier (T0-T4) — unchanged |
| Contract check monitor | Not available | Available on data assets |

## Contract Scoping & Hierarchy

### Contract Scopes

| Scope | Auto-discoverable | Example |
|-------|-------------------|---------|
| Schema/dataset | Yes — from warehouse metadata | `bigquery:raw`, `snowflake:analytics` |
| dbt model group | Yes — from dbt manifest | `staging`, `intermediate`, `marts` |
| Dashboard | Yes — from BI tool metadata | Looker dashboards, Tableau workbooks |
| Exception (single asset) | No — user-created | Specific table, model, or dashboard |

### Hierarchy Resolution

1. Check for exception contract on the specific asset → use if exists
2. Fall back to group-level contract (schema/dbt group/dashboard)
3. Fall back to pipeline SLA defaults
4. If nothing → unmonitored

### Auto-Discovery Flow

- User connects dbt → "We found model groups: staging, intermediate, marts. Create contracts?"
- User connects warehouse → "We found schemas: raw, analytics, public. Create contracts?"
- User connects BI tool → "We found 12 dashboards. Create contracts?"
- User can dismiss, create for all, or pick selectively

### Exception Contracts

Needed when a specific asset legitimately requires **looser** expectations than its group contract. Without an exception contract, a looser SLA would permanently violate the group contract and fail the monitor.

Example: `marts` group contract says freshness 30min, but one large aggregation model legitimately takes 2 hours. Exception contract gives it its own baseline.

**UX**: From lineage/pipeline overview, click a node that has a group contract → SLA modal shows "Part of [group] contract" → option to "Create exception contract for this asset" → pre-fills from group contract, user adjusts.

## Compliance Badges

Always visible on nodes in pipeline overview and lineage, regardless of contract mode.

### Badge States

| Condition | Badge | Color | Severity |
|-----------|-------|-------|----------|
| Meets or exceeds baseline | Compliant | Green | None |
| Stricter than baseline (intentional) | Override | Blue | Info |
| Looser than baseline | Violation | Red | Alert |
| No SLA set for this node | Missing SLA | Yellow | Warning |

### What "baseline" means per mode

- **Contracts disabled**: SLA tier (T0-T4) defines the baseline
- **Contracts enabled (data assets)**: Contract defines the baseline
- **Contracts enabled (tools)**: SLA tier defines the baseline (tools don't have contracts)

## SLA ↔ Contract Sync

### Contracts Disabled (SLA is source of truth)

- SLA change on a data asset → contract value auto-updates to match
- Contract is always a mirror of SLAs
- No conflict possible — one direction only

### Contracts Enabled (Contract is source of truth)

- SLA change on a data asset → compliance badge recalculates against contract, contract unchanged
- Contract edit → all affected node compliance badges recalculate
- Contract edit does NOT push down to node SLAs — SLAs can deviate
- Last-write-wins on contract edits with toast notification

## Monitors

### Existing Monitor Behavior

- Monitors run against SLAs (when contracts disabled) or contracts (when contracts enabled)
- Monitor results compared against the active baseline to determine compliance
- Per-field compliance breakdown: "freshness: compliant, cost: violation"

### Contract Check Monitor

- New monitor type: `CONTRACT_CHECK`
- Only available when data contracts are enabled
- Can be attached to any data asset node
- Validates the node's current state holistically against its contract
- Reports per-field compliance

## UI Surfaces

### Pipeline Overview / Lineage — SLA Modal (per node)

- Click any node → inspector panel shows SLA section
- Fields adapt to node type (existing override schemas)
- Inherits from pipeline defaults, "Inherited" label with option to customize
- When contracts enabled (data assets): banner — "This node has a data contract. SLA changes will show as override or violation against the contract."
- Compliance badge next to each field when contracts enabled (per-field green/blue/red)

### Sources — Contract View (per data asset)

- Shows contract for each data asset, scoped by group or exception
- Contracts disabled: view-only, SLA values auto-synced, owner fields blank
- Contracts enabled: editable with field-level controls
- Shows which group contract applies, or if it's an exception
- Shows compliance status of all nodes under this contract

### Pipeline Settings

- Pipeline-level SLA defaults by category (renamed from "policy")
- SLA tiers: T0, T1, T2, T3, T4
- Toggle: "Enable Data Contracts" with explanation text
- Confirmation dialog on enable

### Node Badges (pipeline overview + lineage)

- Compliance badge on each node (always visible)
- Color-coded: green (compliant), blue (override), red (violation), yellow (missing SLA)

### Monitor Inspector

- Shows monitor result vs active baseline (SLA or contract)
- Per-field breakdown with compliance status

## Rename Scope

All references to "policy" in the codebase become "SLA":
- Type names: `PipelineContractData` → review and rename policy-related fields
- UI labels: "Policy" → "SLA" in all modals, badges, settings
- API routes: any policy-named endpoints
- Variable names: `contractForm`, `alertPolicyJson` etc. — review for policy terminology
- SLA tiers rename: existing tier system → T0, T1, T2, T3, T4

## Existing Plan Impact

The existing `2026-03-25-contract-compliance-monitor.md` plan needs revision:
- Task 1 (remove freshness/extraction fields) — **superseded**: these fields stay, they're part of SLA/contract
- Task 2 (infrastructure override schema) — **still valid**: new override category
- Task 3 (CONTRACT_COMPLIANCE monitor entries) — **revised**: becomes single `CONTRACT_CHECK` monitor type
- Task 4 (monitor scoring) — **revised**: composite health logic still applies, but compliance checks against contract when enabled
- Task 5 (InspectorPanel) — **revised**: show compliance badges always, not just when monitors exist
- Task 6 (remove form fields) — **superseded**: fields stay
