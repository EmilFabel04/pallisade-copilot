# SLA & Data Contracts Unified Design

## Summary

Refactor the existing "policy/contract" system into two cleanly separated concepts: **SLAs** (operability expectations for all nodes) and **Data Contracts** (data asset expectations for tables/schemas, dbt models/groups, and dashboards). Rename "policy" to "SLA" across the entire codebase. Add a settings toggle that controls whether data contracts are view-only (auto-synced from SLAs) or editable (primary source of truth).

## Core Concepts

### SLAs (formerly "Policy")

- Apply to **all nodes**: tools and data assets
- Configured per-node in pipeline overview / lineage via SLA modal
- Fields adapt to node type using existing override schemas (warehouse, ingestion, orchestration, transformation, reporting, storage, observability, infrastructure)
- Inherit from pipeline-level SLA defaults (tiers T0, T1, T2, T3)
- Monitors run against SLAs when contracts are disabled

### Data Contracts

- Apply to **data assets only**: tables/schemas, dbt model groups, dashboards
- Scoped at group level (schema/dataset, dbt model group, dashboard) with per-asset exception contracts
- Auto-discoverable from warehouse metadata, dbt manifest, and BI tool metadata
- Viewed in sources page
- When disabled: view-only, auto-synced from SLAs, owner fields not editable on contract
- When enabled: editable, becomes the primary source of truth for compliance

### Data Contract Data Model

```typescript
interface DataContract {
  id: string;
  pipelineId: string;
  scope: ContractScope;
  scopeRef: string;               // e.g., "bigquery:public", "staging", dashboard ID

  // Ownership (editable only when contracts enabled)
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;

  // SLA expectations (same fields as node SLAs, scoped to data assets)
  slaTier: SlaTier | null;        // T0, T1, T2, T3
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  alertPolicyJson: AlertPolicy | null;
  notes: string | null;

  // Data-asset-specific fields
  schemaExpectations: SchemaExpectation[] | null;  // expected columns, types, constraints
  qualityRules: QualityRule[] | null;              // not-null, uniqueness, accepted values

  // Override fields from the relevant category schema
  overridesJson: Record<string, unknown> | null;

  // Metadata
  isException: boolean;           // true = overrides a group contract for this specific asset
  parentContractId: string | null; // group contract ID if this is an exception
  autoSynced: boolean;            // true when contracts disabled (SLA-synced)
  createdAt: string;
  updatedAt: string;
}

type ContractScope = 'schema' | 'dbt_model_group' | 'dashboard' | 'exception';

interface SchemaExpectation {
  columnName: string;
  expectedType: string | null;
  notNull: boolean;
  unique: boolean;
}

interface QualityRule {
  field: string;
  rule: 'not_null' | 'unique' | 'accepted_values' | 'range' | 'custom';
  params: Record<string, unknown>;
}

interface ContractComplianceResult {
  contractId: string;
  nodeId: string;
  overallStatus: 'PASS' | 'WARN' | 'FAIL';
  fields: ContractFieldCompliance[];
  checkedAt: string;
}

interface ContractFieldCompliance {
  fieldName: string;
  contractValue: unknown;
  slaValue: unknown | null;
  actualValue: unknown | null;       // from latest monitor result, null if no monitor
  status: 'compliant' | 'override' | 'violation' | 'unknown';  // unknown = no monitor data
}
```

### Tools vs Data Assets

| Node Type | Gets | Why |
|-----------|------|-----|
| Tools (Fivetran, Airflow, dbt Cloud, BigQuery-as-engine) | SLAs only | Operability expectations, no data shape |
| Storage tools (S3, GCS, ADLS) | SLAs only | Infrastructure operability, no data shape |
| Observability tools (Elementary, Monte Carlo) | SLAs only | Meta-tooling, monitors the monitors |
| Tables/schemas | Data contracts + SLAs | Has schema, consumers, freshness needs |
| dbt models/groups | Data contracts + SLAs | Has schema, tests, freshness needs |
| Dashboards | Data contracts + SLAs | Has upstream dependencies, refresh expectations |

## Settings Toggle

Located in pipeline settings. Two modes:

### SLAs Only (default)

- SLA edits on data assets auto-update the corresponding contract
- Contracts exist but are view-only in sources
- Owner fields on contracts are not editable (synced from SLA if set)
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
| Contract in sources | View-only, auto-synced from SLAs, owner fields not editable | Editable, primary source of truth |
| Compliance baseline for data assets | SLA tier (T0-T3) | Contract |
| Compliance baseline for tools | SLA tier (T0-T3) | SLA tier (T0-T3) — unchanged |
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

Needed when a specific asset legitimately requires **different** expectations than its group contract — either looser or stricter. The most common case is looser: without an exception contract, a looser SLA would permanently violate the group contract and fail the monitor.

Example (looser): `marts` group contract says freshness 30min, but one large aggregation model legitimately takes 2 hours. Exception contract gives it its own baseline.

Example (stricter): A critical revenue table in the `analytics` schema needs 5-minute freshness while the schema contract allows 30 minutes. Exception contract tightens the baseline for that table.

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

### Per-Field Comparison Direction

"Stricter" and "looser" are field-specific. Each field has a comparison direction that determines which way is stricter:

| Field | Stricter means | Comparison |
|-------|---------------|------------|
| `expectedFreshnessMinutes` | Lower value | SLA < baseline → override, SLA > baseline → violation |
| `expectedExtractionFrequencyMinutes` | Lower value | SLA < baseline → override, SLA > baseline → violation |
| `maxQueryCostUsd` | Lower value | SLA < baseline → override, SLA > baseline → violation |
| `maxSyncDelayMinutes` | Lower value | SLA < baseline → override, SLA > baseline → violation |
| `maxRetries` | Higher value | SLA > baseline → override, SLA < baseline → violation |
| `retentionDays` | Higher value | SLA > baseline → override, SLA < baseline → violation |
| `requireDryRun` | `true` | SLA=true, baseline=false → override; SLA=false, baseline=true → violation |
| `oncallRequired` | `true` | SLA=true, baseline=false → override; SLA=false, baseline=true → violation |
| `encryptionRequired` | `true` | SLA=true, baseline=false → override; SLA=false, baseline=true → violation |
| `schemaChangePolicy` | `"fail"` > `"warn"` > `"ignore"` | Ordered comparison |
| `connectorPriority` | `"critical"` > `"high"` > `"normal"` > `"low"` | Ordered comparison |
| `requiredTests` | Superset | SLA is superset of baseline → override; SLA is subset → violation |

For fields where SLA value equals baseline value → **Compliant**.

### SLA Tier Baseline Definitions

Each tier defines default expectations. When contracts are disabled, compliance is checked against these tier defaults:

| Field | T0 (Critical) | T1 (High) | T2 (Standard) | T3 (Low) |
|-------|--------------|-----------|---------------|----------|
| `expectedFreshnessMinutes` | 15 | 60 | 360 | 1440 |
| `maxSyncDelayMinutes` | 15 | 60 | 360 | 1440 |
| `oncallRequired` | true | true | false | false |
| `maxRetries` | 5 | 3 | 3 | 1 |
| `schemaChangePolicy` | fail | warn | warn | ignore |

Tier defaults serve as the compliance baseline when no contract exists. Per-node SLAs can override individual fields. Fields not defined in the tier default are not checked for compliance.

### What "baseline" means per mode

- **Contracts disabled**: SLA tier (T0-T3) defines the baseline
- **Contracts enabled (data assets)**: Contract defines the baseline
- **Contracts enabled (tools)**: SLA tier defines the baseline (tools don't have contracts)

## SLA ↔ Contract Sync

### Contracts Disabled (SLA is source of truth)

- SLA change on a data asset → contract value auto-updates to match
- Contract is always a mirror of SLAs
- No conflict possible — one direction only

**Auto-sync mechanics:** Contracts are scoped at group level (schema, dbt group, dashboard), but SLAs are per-node. When a node SLA changes:
1. Find the group contract that covers this node (by schema, dbt group, or dashboard scope)
2. If no group contract exists, create one with `autoSynced: true`
3. Update the group contract's fields to reflect the **most common** SLA values across all nodes in the group (mode, not average)
4. If a node has values that differ from the group mode, it gets an auto-generated exception contract with `autoSynced: true`
5. All auto-synced contracts are replaced on every SLA edit — they are ephemeral projections, not user data

When contracts are toggled from disabled → enabled, all `autoSynced` contracts become editable starting points. The `autoSynced` flag flips to `false` and the contracts are now user-owned.

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
- Reports per-field compliance

**Evaluation logic:** The CONTRACT_CHECK monitor resolves the active contract for the node (exception → group → pipeline default), then for each field in the contract that has a value:
1. Collects the latest monitor results for related monitors (e.g., FRESHNESS monitor result for `expectedFreshnessMinutes`)
2. Collects the node's SLA value for that field
3. Compares the SLA value against the contract value using the per-field comparison direction (see Compliance Badges section)
4. Compares the actual monitor result against the contract value
5. Reports: field name, contract value, SLA value, actual value, compliance status (compliant/override/violation)

The overall CONTRACT_CHECK status is:
- **PASS**: all fields compliant or override
- **WARN**: any field has no monitor result (can't verify)
- **FAIL**: any field is in violation

## UI Surfaces

### Pipeline Overview / Lineage — SLA Modal (per node or multi-node)

- Click any node → inspector panel shows SLA section
- **Multi-select**: Shift+Click to select multiple nodes, then open SLA modal to apply the same SLA to all selected nodes at once
- SLA modal header shows: single node name, or "X nodes selected" for multi-select
- When multi-selecting, the modal shows a hint: `💡 Shift+Click nodes to select multiple` (displayed in the modal footer when a single node is selected, so users discover the shortcut)
- Fields adapt to node type (existing override schemas). For multi-select, only fields common to all selected node types are shown.
- Inherits from pipeline defaults, "Inherited" label with option to customize
- When contracts enabled (data assets): banner — "This node has a data contract. SLA changes will show as override or violation against the contract."
- Compliance badge next to each field when contracts enabled (per-field green/blue/red)

### Sources — Contract View (per data asset)

Located as a new "Data Contracts" tab within the existing Sources page. Each row represents a group or exception contract.

- Shows contract for each data asset scope (schema, dbt group, dashboard, or exception)
- Contracts disabled: view-only, SLA values auto-synced, owner fields not editable
- Contracts enabled: editable with field-level controls
- Shows which group contract applies, or if it's an exception
- Shows compliance status of all nodes under this contract
- One contract per dashboard (each dashboard is its own scope)

### Pipeline Settings

- Pipeline-level SLA defaults by category (renamed from "policy")
- SLA tiers: T0, T1, T2, T3
- Toggle: "Enable Data Contracts" with explanation text
- Confirmation dialog on enable

### Node Badges (pipeline overview + lineage)

- Compliance badge on each node (always visible)
- Color-coded: green (compliant), blue (override), red (violation), yellow (missing SLA)

### Monitor Inspector

- Shows monitor result vs active baseline (SLA or contract)
- Per-field breakdown with compliance status

## Rename Scope

Two renames: "policy" → "SLA", and existing "contract" types → "SLA" types (since "Data Contract" now means something different).

### Existing types renamed to SLA types

| Current Name | New Name | Reason |
|-------------|----------|--------|
| `PipelineContractData` | `PipelineSLAData` | This is SLA config, not a data contract |
| `SourceContractWithOverrides` | `NodeSLAWithOverrides` | Per-node SLA with category overrides |
| `EffectiveContract` | `EffectiveSLA` | Resolved SLA after inheritance |
| `ToolContractConfig` | `ToolSLAConfig` | Tool-level SLA config |
| `ToolContractChildEntry` | `ToolSLAChildEntry` | Child entry in tool SLA |
| `EditContractModal` | `EditSLAModal` | Modal edits SLAs, not data contracts |
| `contractForm` (state var) | `slaForm` | Form state for SLA editing |

### New Data Contract types (added)

| Type | Purpose |
|------|---------|
| `DataContract` | Group or exception contract for data assets |
| `ContractScope` | `'schema' \| 'dbt_model_group' \| 'dashboard' \| 'exception'` |
| `SchemaExpectation` | Column-level schema expectations |
| `QualityRule` | Data quality rules |
| `ContractComplianceResult` | Per-field compliance output from CONTRACT_CHECK |

### UI label renames

- "Policy" → "SLA" in all modals, badges, settings, tooltips
- "Contract" in pipeline settings → "SLA" (the pipeline-level defaults)
- "Data Contract" is only used for the new data contract concept in sources

### API route renames

- `/api/integrations/[id]/contract` → `/api/integrations/[id]/sla`
- `/api/pipeline/[stackId]/contract` → `/api/pipeline/[stackId]/sla`
- `/api/pipeline/[stackId]/contract/apply` → `/api/pipeline/[stackId]/sla/apply`
- New: `/api/pipeline/[stackId]/data-contracts` (CRUD for data contracts)

### Other renames

- `alertPolicyJson` field name stays — this is an alert policy object, not an "SLA" or "contract" in our domain sense
- SLA tiers: T0, T1, T2, T3 (unchanged from codebase, was already correct)

## Existing Plan Impact

The existing `2026-03-25-contract-compliance-monitor.md` plan needs revision:
- Task 1 (remove freshness/extraction fields) — **superseded**: these fields stay, they're part of SLA/contract
- Task 2 (infrastructure override schema) — **still valid**: new override category
- Task 3 (CONTRACT_COMPLIANCE monitor entries) — **revised**: becomes single `CONTRACT_CHECK` monitor type
- Task 4 (monitor scoring) — **revised**: composite health logic still applies, but compliance checks against contract when enabled
- Task 5 (InspectorPanel) — **revised**: show compliance badges always, not just when monitors exist
- Task 6 (remove form fields) — **superseded**: fields stay, they become SLA fields
- Task 7 (run full test suite) — **still valid**: verification step applies to new implementation

## Known Limitations (MVP)

- **Multi-user conflict**: Last-write-wins on contract edits. Acceptable for MVP but concurrent edits could silently overwrite. Future: optimistic locking.
- **Auto-sync is eventual**: When contracts are disabled, group contract projection recalculates on SLA save, not in real-time.
- **Schema expectations**: `SchemaExpectation` and `QualityRule` fields on DataContract are defined but not populated by auto-sync. They require manual entry or dbt contract import. Auto-discovery from dbt `contract: {enforced: true}` is a follow-up.
