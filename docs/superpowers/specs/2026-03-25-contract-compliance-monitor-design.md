# Contract Compliance Monitor & Health/Coverage Scoring Fixes

## Summary

Three changes: (1) simplify data contracts to tool-operability-only by removing data-asset SLA fields, (2) add a CONTRACT_COMPLIANCE monitor that checks tools against their contracts with per-child-item granularity, (3) fix health/coverage scoring so unmonitored tools show 0% instead of hiding, and tool health incorporates child asset health.

## Motivation

- Data asset SLAs (freshness, volume, schema) are fully covered by monitoring policies in data lineage. Duplicating them in contracts causes confusion about the source of truth.
- Tools in pipeline overview have no way to enforce operability requirements (query cost limits, sync delay tolerances, required tests) declared in their contracts.
- Tool nodes currently show 100%/healthy when no monitors are configured, and tool health ignores child asset health entirely.

## Design Decisions

- **Policy config stays in data lineage only** — pipeline overview is a read-only rollup surface for health/coverage/contract compliance.
- **Contracts are tool-operability-only** — ownership, SLA tier, alert routing, and per-domain operability fields. No data-asset SLAs.
- **Single CONTRACT_COMPLIANCE monitor with sub-checks** — one monitor type per tool node, internally evaluates each contract operability field. Avoids monitor-type explosion while maintaining granularity.
- **Per-child contract config** — tools like Airflow (multiple DAGs) or Fivetran (multiple connectors) can define different operability requirements per child item, with tool-level defaults.

---

## 1. Contract Type Simplification

### Remove data-asset SLA fields

Remove `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes` from:
- `PipelineContractData`
- `SourceContractWithOverrides`
- `EffectiveContract`

These fields move entirely to data lineage monitoring policies.

### Simplified PipelineContractData

```typescript
interface PipelineContractData {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;        // classification, not enforcement
  alertPolicyJson: AlertPolicy | null;
  notes: string | null;
}
```

### Add InfrastructureOverridesSchema

New override schema for linux_server tool type:

```typescript
const InfrastructureOverridesSchema = z.object({
  maxCpuPct: z.number().min(0).max(100).optional(),
  maxMemoryPct: z.number().min(0).max(100).optional(),
  maxDiskPct: z.number().min(0).max(100).optional(),
  certExpiryWarnDays: z.number().int().min(0).optional(),
  uptimeSlaPercent: z.number().min(0).max(100).optional(),
}).strict();
```

Add `'infrastructure'` to `OverrideKey` type. Also update all `Record<OverrideKey, ...>` maps:
- `INTEGRATION_TYPE_TO_OVERRIDE_KEY`: add `LINUX_SERVER: 'infrastructure'`
- `OVERRIDE_SCHEMAS`: add `infrastructure: InfrastructureOverridesSchema`
- `OVERRIDE_LABELS`: add `infrastructure: 'Infrastructure'`

### Hierarchical child contract structure

Contracts support per-child-item overrides. The tool-level defaults apply to all children unless overridden. Both `defaults` and `overrides` are validated against the existing domain-specific Zod schemas (`WarehouseOverridesSchema`, `IngestionOverridesSchema`, etc.) via the existing `validateOverrides()` function — no `Record<string, any>` bypass.

```typescript
interface ToolContractConfig<T extends Record<string, any> = Record<string, any>> {
  /** Tool-level defaults — validated against the domain's override schema */
  defaults: T;
  /** Per-child overrides keyed by child platformId */
  children: Record<string, {
    name: string;
    platformId: string;       // connector_id, dag_id, job_id, server hostname
    /** Partial overrides — merged with defaults at resolution time */
    overrides: Partial<T>;
  }>;
}

// Usage: ToolContractConfig<OrchestrationContractOverrides> for Airflow
// Usage: ToolContractConfig<IngestionContractOverrides> for Fivetran
```

Example — Airflow node with 2 DAGs:

```
defaults: { maxRetries: 3, retryBackoffMinutes: 5, oncallRequired: true }
children:
  "etl_daily":     { overrides: { oncallRequired: false } }  // relaxed for this DAG
  "weekly_report": { overrides: {} }                          // inherits all defaults
```

Effective config per child = `{ ...defaults, ...child.overrides }`.

The child list is populated from the existing `childItems` array returned by the tool details endpoint.

---

## 2. CONTRACT_COMPLIANCE Monitor

### Catalog entries

CONTRACT_COMPLIANCE uses **domain-suffixed keys** to avoid duplicate key collisions in the catalog. Each domain gets its own entry with a unique key.

```typescript
// Domain-suffixed keys — avoids getMonitorDefinition() collision
{
  key: 'CONTRACT_COMPLIANCE_INGESTION',
  label: 'Contract Compliance',
  description: 'Checks ingestion tool operability against its data contract',
  category: 'ingestion',
  required_integrations: ['fivetran', 'airbyte'],
  target_selector_type: 'none',  // contract fully defines targets — no picker needed
  executor_type: 'tool_api',
  supports_baselines: false,
  auto_configurable: false,
  config_schema: []    // contract IS the config — no user fields
},
{
  key: 'CONTRACT_COMPLIANCE_ORCHESTRATION',
  label: 'Contract Compliance',
  description: 'Checks orchestration tool operability against its data contract',
  category: 'orchestration',
  required_integrations: ['airflow', 'dagster'],
  // ... same shape
},
// Also: CONTRACT_COMPLIANCE_TRANSFORMATION (dbt_cloud, dbt_core)
//        CONTRACT_COMPLIANCE_WAREHOUSE (bigquery, snowflake, postgres, redshift, databricks, ...)
//        CONTRACT_COMPLIANCE_INFRASTRUCTURE (linux_server)
//        CONTRACT_COMPLIANCE_REPORTING (looker, tableau, powerbi, metabase)
```

Domain-suffixed keys mean `getMonitorDefinition('CONTRACT_COMPLIANCE_ORCHESTRATION')` works correctly with no ambiguity. A helper constant maps domains to their contract compliance key:

```typescript
const CONTRACT_COMPLIANCE_KEYS: Record<string, string> = {
  ingestion: 'CONTRACT_COMPLIANCE_INGESTION',
  orchestration: 'CONTRACT_COMPLIANCE_ORCHESTRATION',
  transformation: 'CONTRACT_COMPLIANCE_TRANSFORMATION',
  warehouse: 'CONTRACT_COMPLIANCE_WAREHOUSE',
  infrastructure: 'CONTRACT_COMPLIANCE_INFRASTRUCTURE',
  reporting: 'CONTRACT_COMPLIANCE_REPORTING',
};
```

The `target_selector_type: 'none'` is intentional — the contract's `ToolContractConfig.children` map fully defines which child items are checked. No picker UI is needed because the contract config UI (in pipeline settings) already handles child selection.

Updates to catalog helper structures:
- Add all `CONTRACT_COMPLIANCE_*` keys to `TOOL_MONITOR_TYPES` array
- Add each key to `TOOL_NODE_TYPE_MAP` with the domain's tool types
- Add each key to `DOMAIN_MONITOR_MAP` — note that `DOMAIN_MONITOR_MAP` uses **platform domain strings** as keys (`ingestion`, `orchestration`, `transform`, `warehouse`, `bi`, `infrastructure`), not `MonitorCategory` values. So `CONTRACT_COMPLIANCE_REPORTING` goes under the `bi` key, and `CONTRACT_COMPLIANCE_TRANSFORMATION` goes under the `transform` key.

### Sub-checks per domain

| Domain | Fields checked |
|--------|---------------|
| Warehouse | `maxQueryCostUsd` vs actual avg query cost, `requireDryRun` vs config state, `readOnlyEnforced` vs permissions |
| Ingestion | `maxSyncDelayMinutes` vs actual sync lag, `connectorPriority` vs connector config, `schemaChangePolicy` vs drift detection config |
| Orchestration | `maxRetries` vs DAG retry config, `retryBackoffMinutes` vs backoff setting, `oncallRequired` vs alert channel presence |
| Transformation | `expectedRunCadenceMinutes` vs actual run frequency, `requiredTests` vs configured dbt tests (checks test *existence*, not freshness thresholds — that's data lineage policy), `freshnessTestsRequired` checks whether a source freshness test is *configured* (operational readiness), not the threshold value |
| Reporting | `refreshSlaMinutes` vs actual refresh timing, `ownerAckRequired` vs ownership config |
| Infrastructure | `maxCpuPct` vs actual CPU usage, `maxMemoryPct` vs actual memory, `maxDiskPct` vs actual disk, `certExpiryWarnDays` vs cert expiry, `uptimeSlaPercent` vs actual uptime |

### Result shape

```typescript
interface ContractComplianceResult {
  status: 'PASS' | 'WARN' | 'FAIL';
  childResults: Array<{
    platformId: string;
    name: string;
    status: 'PASS' | 'WARN' | 'FAIL';
    subChecks: Array<{
      field: string;        // e.g. 'maxQueryCostUsd'
      label: string;        // e.g. 'Max Query Cost'
      expected: any;        // contract value
      actual: any;          // observed value
      status: 'PASS' | 'WARN' | 'FAIL' | 'SKIPPED';
      message?: string;
    }>;
  }>;
}
```

Overall status = worst across all children's sub-checks. SKIPPED sub-checks (field not set in contract) are excluded from status calculation.

**WARN vs FAIL threshold**: For numeric fields, WARN when actual exceeds contract value by <20%, FAIL when >=20%. For boolean fields (e.g., `oncallRequired`, `encryptionRequired`), any violation is FAIL (no WARN). For enum fields (e.g., `schemaChangePolicy`), mismatch is FAIL.

### Lifecycle

- **Auto-creation**: When a contract is saved for a tool, the system auto-creates the CONTRACT_COMPLIANCE monitor for that tool node. No user prompt — it's an implicit part of having a contract. This matches the "zero config" principle: the contract defines everything.
- **Deletion**: When a contract is deleted, the CONTRACT_COMPLIANCE monitor is also deleted (not SKIPPED). A monitor with no contract has nothing to check.
- The monitor has no user-configurable fields — the contract defines everything.

---

## 3. Health & Coverage Scoring Fixes

### 3a. Unmonitored state

**Current bug**: InspectorPanel's `toolScoring` useMemo returns `null` when `nodeMonitors.length === 0` (line 106), causing the health/coverage section to be hidden entirely. The tool node badge then defaults to whatever `healthColor` it had — often green. Note: `computeMonitorScoring` itself always returns a valid `MonitorScoringResult` (never null) — the early-return is in the component.

**Fix**: Remove the `nodeMonitors.length === 0` early-return in InspectorPanel. Always call `computeMonitorScoring` (which correctly returns `healthStatus: 'unmonitored'` for empty arrays). Render the health/coverage section for all states including unmonitored:
- Health: "Unmonitored" label, gray bar, no percentage number
- Coverage: 0%, `coverageStatus: 'none'`

### 3b. Composite tool health

Tool health becomes a weighted composite of tool-level monitors and child asset health.

```
toolHealth = weighted average of:
  - tool monitor health (weight: 0.4)
  - child asset health average (weight: 0.6)
```

New function in `monitor-scoring.ts`:

```typescript
function computeCompositeToolHealth(
  toolMonitors: Array<{ lastStatus: string | null }>,
  childAssetHealthScores: number[],   // 0-100 per child asset
): HealthResult
```

**Bucket assignment**: CONTRACT_COMPLIANCE contributes to the **tool monitors** bucket (40% weight). It is a tool-level monitor, not a child asset monitor. Child asset health comes from data lineage monitor summaries on the actual data assets (tables/views/models), which are independent of the tool's contract compliance status.

Edge cases:
- No tool monitors, has child health -> health = child health only (weight 1.0)
- Has tool monitors, no children -> health = tool monitor health only (weight 1.0)
- Neither -> `{ healthScore: null, healthStatus: 'unmonitored' }`

**Child asset health source**: The tool details endpoint returns `subNodeIds` (child asset graph node IDs). These are data asset nodes (tables, views, models) that appear in the unified lineage graph, where per-asset monitor summaries are already computed by the lineage route's `buildMonitorSummary` enrichment. InspectorPanel fetches these summaries to compute the child health average. If a tool has no data asset children (e.g., a linux_server), the composite collapses to tool-monitor-only health.

### 3c. Coverage includes CONTRACT_COMPLIANCE conditionally

The domain-appropriate `CONTRACT_COMPLIANCE_*` key is added to `APPLICABLE_MONITORS` for every `AssetCategory`, but only counts toward available monitors when the tool has a contract defined.

**Important naming distinction**: `APPLICABLE_MONITORS` in `monitor-scoring.ts` is keyed by `AssetCategory` (`warehouse`, `bi`, `ingestion`, `orchestration`, `dbt_transform`, `infra`), which differs from `MonitorCategory` (`warehouse`, `reporting`, `ingestion`, `orchestration`, `transformation`, `infrastructure`). The mapping:
- `AssetCategory: 'dbt_transform'` → gets `CONTRACT_COMPLIANCE_TRANSFORMATION`
- `AssetCategory: 'infra'` → gets `CONTRACT_COMPLIANCE_INFRASTRUCTURE`
- `AssetCategory: 'bi'` → gets `CONTRACT_COMPLIANCE_REPORTING`
- Others match directly

Updated signature:

```typescript
function getApplicableMonitorTypes(
  category: AssetCategory,
  options?: { hasContract?: boolean },
): string[]
```

When `hasContract` is false or undefined, CONTRACT_COMPLIANCE is excluded from the available list. When true, it's included. This prevents tools without contracts from showing artificially low coverage.

---

## 4. Affected Files

| File | Changes |
|------|---------|
| `components/contracts/types.ts` | Remove freshness/extraction fields, add `InfrastructureOverridesSchema`, add `ToolContractConfig` generic type, add `infrastructure` to `OverrideKey` |
| `types/monitor-catalog.ts` | Add `CONTRACT_COMPLIANCE` entries (one per domain), add to `TOOL_MONITOR_TYPES`, `TOOL_NODE_TYPE_MAP`, `DOMAIN_MONITOR_MAP` |
| `lib/monitor-scoring.ts` | Add `computeCompositeToolHealth`, update `getApplicableMonitorTypes` signature with `hasContract` option, add CONTRACT_COMPLIANCE to `APPLICABLE_MONITORS` conditionally |
| `components/lineage/pipeline-overview/InspectorPanel.tsx` | Remove `nodeMonitors.length === 0` early-return, show health/coverage for unmonitored state, use composite health, fetch child asset health summaries, pass `hasContract` to coverage calc |
| `app/(dashboard)/dashboard/pipeline/settings/page.tsx` | Remove freshness/extraction form fields, add per-child contract config UI |
| Backend (new executor) | Contract compliance executor with per-child sub-check evaluation |

## 5. Migration

Existing contracts may have `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes` populated. These fields are dropped from the types — no data migration is needed because:
- The fields are stored in a JSON column (`contractJson`). Removing them from the TypeScript interface simply means the UI stops reading/writing them. The JSON blob retains the old values harmlessly.
- No migration to move these values into data lineage policies — they were pipeline-level defaults, not asset-specific. Users define asset-level freshness policies directly in data lineage.

## 6. Constraints

- **No policy config in pipeline overview** — monitoring policy assignment, editing, and profile selection only exists in data lineage. Pipeline overview is read-only for health/coverage/compliance.
- **Data asset SLAs live in data lineage policies only** — contracts do not define freshness, volume, schema, quality, or anomaly thresholds.
- **No `storage` asset category** — the existing `AssetCategory` type in `monitor-scoring.ts` does not include `storage`. Storage tools (S3, GCS, ADLS) do not have monitors in the current catalog. The `StorageOverridesSchema` exists in contract types for future use, but CONTRACT_COMPLIANCE for storage tools is deferred until storage monitors are added to the catalog.
