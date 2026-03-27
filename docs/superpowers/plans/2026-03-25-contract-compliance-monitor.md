# Contract Compliance Monitor & Health/Coverage Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify contracts to tool-operability-only, add a CONTRACT_COMPLIANCE monitor with per-child sub-checks, and fix health/coverage scoring for tool nodes.

**Architecture:** Contract types lose data-asset SLA fields (freshness/extraction). Six domain-suffixed CONTRACT_COMPLIANCE_* monitor entries are added to the catalog. Monitor scoring gains a composite health function (40% tool monitors + 60% child asset health) and conditional CONTRACT_COMPLIANCE coverage. InspectorPanel always shows health/coverage including unmonitored state.

**Tech Stack:** TypeScript, Next.js, Zod, Vitest, React

**Spec:** `docs/superpowers/specs/2026-03-25-contract-compliance-monitor-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `components/contracts/types.ts` | Modify | Remove freshness/extraction fields, add infrastructure schema, add ToolContractConfig, add CONTRACT_COMPLIANCE_KEYS |
| `types/monitor-catalog.ts` | Modify | Add 6 CONTRACT_COMPLIANCE_* entries, update TOOL_MONITOR_TYPES, TOOL_NODE_TYPE_MAP, DOMAIN_MONITOR_MAP |
| `lib/monitor-scoring.ts` | Modify | Add computeCompositeToolHealth, update getApplicableMonitorTypes with hasContract option |
| `lib/__tests__/monitor-scoring.test.ts` | Modify | Add tests for composite health, conditional coverage, unmonitored state |
| `components/lineage/pipeline-overview/InspectorPanel.tsx` | Modify | Fix unmonitored display, use composite health, pass hasContract |
| `app/(dashboard)/dashboard/pipeline/settings/page.tsx` | Modify | Remove freshness/extraction form fields |
| `app/api/integrations/[id]/contract/route.ts` | Modify | Remove freshness/extraction references |
| `app/api/integrations/route.ts` | Modify | Remove freshness/extraction references |
| `app/api/pipeline/[stackId]/contract/route.ts` | Modify | Remove freshness/extraction references |
| `components/sources/EditContractModal.tsx` | Modify | Remove freshness/extraction form fields |
| `components/sources/useSourcesData.ts` | Modify | Remove freshness/extraction references |
| `components/sources/types.ts` | Modify | Remove freshness/extraction type references |
| `components/sources/SourceDetailDrawer.tsx` | Modify | Remove freshness/extraction display |
| `lib/contracts/resolver.ts` | Modify | Remove freshness/extraction resolution logic |

**Out of scope for this plan:**
- Backend contract compliance executor (Python) — separate plan
- Per-child contract config UI in pipeline settings — separate plan
- Auto-creation/deletion of CONTRACT_COMPLIANCE monitors on contract save/delete — depends on backend executor

---

### Task 1: Simplify Contract Types

**Files:**
- Modify: `components/contracts/types.ts:7-16` (PipelineContractData)
- Modify: `components/contracts/types.ts:33-44` (SourceContractWithOverrides)
- Modify: `components/contracts/types.ts:47-56` (EffectiveContract)

- [ ] **Step 1: Remove `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes` from PipelineContractData**

In `components/contracts/types.ts`, change the `PipelineContractData` interface from:

```typescript
export interface PipelineContractData {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  alertPolicyJson: AlertPolicy | null;
  notes: string | null;
}
```

to:

```typescript
export interface PipelineContractData {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;
  alertPolicyJson: AlertPolicy | null;
  notes: string | null;
}
```

- [ ] **Step 2: Remove same fields from SourceContractWithOverrides**

Remove `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes` from `SourceContractWithOverrides` (lines 33-44).

- [ ] **Step 3: Remove same fields from EffectiveContract**

Remove `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes` from `EffectiveContract` (lines 47-56).

- [ ] **Step 4: Fix all TypeScript compilation errors from removed fields**

Search for all references to `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes` across the codebase and remove them:

```bash
grep -rn "expectedFreshnessMinutes\|expectedExtractionFrequency" --include="*.ts" --include="*.tsx"
```

**All files with references** (fix each one — remove the field references, update any objects/destructuring):
- `app/(dashboard)/dashboard/pipeline/settings/page.tsx:72-73` — remove from contractForm initial state
- `app/(dashboard)/dashboard/pipeline/settings/page.tsx:286-287` — remove from contract load
- `app/(dashboard)/dashboard/pipeline/settings/page.tsx:522-544` — remove the form fields grid
- `app/api/integrations/[id]/contract/route.ts` — remove field from API response/request handling
- `app/api/integrations/route.ts` — remove field references
- `app/api/pipeline/[stackId]/contract/route.ts` — remove field from contract API
- `components/sources/EditContractModal.tsx` — remove freshness/extraction form inputs
- `components/sources/useSourcesData.ts` — remove field references in data hooks
- `components/sources/types.ts` — remove field from any local type definitions
- `components/sources/SourceDetailDrawer.tsx` — remove freshness/extraction display
- `lib/contracts/resolver.ts` — remove fields from contract resolution logic

- [ ] **Step 5: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors related to removed fields.

- [ ] **Step 6: Commit**

```bash
git add components/contracts/types.ts app/(dashboard)/dashboard/pipeline/settings/page.tsx
# Also add any other files that had references
git commit -m "refactor: remove freshness/extraction fields from contract types"
```

---

### Task 2: Add Infrastructure Override Schema and ToolContractConfig

**Files:**
- Modify: `components/contracts/types.ts:58-66` (OverrideKey), `components/contracts/types.ts:69-105` (INTEGRATION_TYPE_TO_OVERRIDE_KEY), `components/contracts/types.ts:164-172` (OVERRIDE_SCHEMAS), `components/contracts/types.ts:197-205` (OVERRIDE_LABELS)

**Important: Steps 1-4 must be done atomically** — adding `infrastructure` to `OverrideKey` (Step 1) without adding it to `OVERRIDE_SCHEMAS` and `OVERRIDE_LABELS` (Step 4) will cause TypeScript errors because they are `Record<OverrideKey, ...>`. Do all steps before running `tsc`.

- [ ] **Step 1: Add `infrastructure` to OverrideKey union type**

In `components/contracts/types.ts`, change:

```typescript
export type OverrideKey =
  | 'warehouse'
  | 'ingestion'
  | 'orchestration'
  | 'transformation'
  | 'reporting'
  | 'storage'
  | 'observability';
```

to:

```typescript
export type OverrideKey =
  | 'warehouse'
  | 'ingestion'
  | 'orchestration'
  | 'transformation'
  | 'reporting'
  | 'storage'
  | 'observability'
  | 'infrastructure';
```

- [ ] **Step 2: Add LINUX_SERVER to INTEGRATION_TYPE_TO_OVERRIDE_KEY**

After the Storage entries (line 104), add:

```typescript
  // Infrastructure
  LINUX_SERVER: 'infrastructure',
```

- [ ] **Step 3: Add InfrastructureOverridesSchema**

After `ObservabilityOverridesSchema` (line 161), add:

```typescript
// Infrastructure (Linux Server)
export const InfrastructureOverridesSchema = z.object({
  maxCpuPct: z.number().min(0).max(100).optional(),
  maxMemoryPct: z.number().min(0).max(100).optional(),
  maxDiskPct: z.number().min(0).max(100).optional(),
  certExpiryWarnDays: z.number().int().min(0).optional(),
  uptimeSlaPercent: z.number().min(0).max(100).optional(),
}).strict();
export type InfrastructureContractOverrides = z.infer<typeof InfrastructureOverridesSchema>;
```

- [ ] **Step 4: Add infrastructure to OVERRIDE_SCHEMAS and OVERRIDE_LABELS**

In `OVERRIDE_SCHEMAS`, add:

```typescript
  infrastructure: InfrastructureOverridesSchema,
```

In `OVERRIDE_LABELS`, add:

```typescript
  infrastructure: 'Infrastructure',
```

- [ ] **Step 5: Add ToolContractConfig generic type and CONTRACT_COMPLIANCE_KEYS**

After `OVERRIDE_LABELS`, add:

```typescript
// ─── Hierarchical Child Contract ─────────────────────────────

export interface ToolContractChildEntry<T extends Record<string, any> = Record<string, any>> {
  name: string;
  platformId: string;
  overrides: Partial<T>;
}

export interface ToolContractConfig<T extends Record<string, any> = Record<string, any>> {
  defaults: T;
  children: Record<string, ToolContractChildEntry<T>>;
}

// ─── Contract Compliance Key Map ─────────────────────────────

export const CONTRACT_COMPLIANCE_KEYS: Record<string, string> = {
  ingestion: 'CONTRACT_COMPLIANCE_INGESTION',
  orchestration: 'CONTRACT_COMPLIANCE_ORCHESTRATION',
  transformation: 'CONTRACT_COMPLIANCE_TRANSFORMATION',
  warehouse: 'CONTRACT_COMPLIANCE_WAREHOUSE',
  infrastructure: 'CONTRACT_COMPLIANCE_INFRASTRUCTURE',
  reporting: 'CONTRACT_COMPLIANCE_REPORTING',
};
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add components/contracts/types.ts
git commit -m "feat: add infrastructure override schema and ToolContractConfig type"
```

---

### Task 3: Add CONTRACT_COMPLIANCE Monitor Catalog Entries

**Files:**
- Modify: `types/monitor-catalog.ts:668-769` (catalog helpers and constants)

- [ ] **Step 1: Write failing test for CONTRACT_COMPLIANCE availability**

Create the test in `lib/__tests__/monitor-scoring.test.ts` (append to existing file):

```typescript
describe('CONTRACT_COMPLIANCE in APPLICABLE_MONITORS', () => {
  it('getApplicableMonitorTypes includes CONTRACT_COMPLIANCE when hasContract is true', () => {
    const types = getApplicableMonitorTypes('ingestion', { hasContract: true });
    expect(types).toContain('CONTRACT_COMPLIANCE_INGESTION');
  });

  it('getApplicableMonitorTypes excludes CONTRACT_COMPLIANCE when hasContract is false', () => {
    const types = getApplicableMonitorTypes('ingestion', { hasContract: false });
    expect(types).not.toContain('CONTRACT_COMPLIANCE_INGESTION');
  });

  it('getApplicableMonitorTypes excludes CONTRACT_COMPLIANCE by default', () => {
    const types = getApplicableMonitorTypes('ingestion');
    expect(types).not.toContain('CONTRACT_COMPLIANCE_INGESTION');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: FAIL — `getApplicableMonitorTypes` doesn't accept options parameter yet.

- [ ] **Step 3: Add 6 CONTRACT_COMPLIANCE_* entries to MONITOR_CATALOG**

In `types/monitor-catalog.ts`, after the BI_REFRESH_FAILURE entry (before the filtering functions), add:

```typescript
  // ==========================================================================
  // CONTRACT COMPLIANCE — Per-domain contract checks
  // ==========================================================================
  {
    key: 'CONTRACT_COMPLIANCE_INGESTION',
    label: 'Contract Compliance',
    description: 'Checks ingestion tool operability against its data contract',
    category: 'ingestion',
    required_integrations: ['fivetran', 'airbyte'],
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
  {
    key: 'CONTRACT_COMPLIANCE_ORCHESTRATION',
    label: 'Contract Compliance',
    description: 'Checks orchestration tool operability against its data contract',
    category: 'orchestration',
    required_integrations: ['airflow', 'dagster'],
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
  {
    key: 'CONTRACT_COMPLIANCE_TRANSFORMATION',
    label: 'Contract Compliance',
    description: 'Checks transformation tool operability against its data contract',
    category: 'transformation',
    required_integrations: ['dbt_cloud', 'dbt_core'],
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
  {
    key: 'CONTRACT_COMPLIANCE_WAREHOUSE',
    label: 'Contract Compliance',
    description: 'Checks warehouse tool operability against its data contract',
    category: 'warehouse',
    required_integrations: WAREHOUSE_TOOL_TYPES,
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
  {
    key: 'CONTRACT_COMPLIANCE_INFRASTRUCTURE',
    label: 'Contract Compliance',
    description: 'Checks infrastructure tool operability against its data contract',
    category: 'infrastructure',
    required_integrations: ['linux_server'],
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
  {
    key: 'CONTRACT_COMPLIANCE_REPORTING',
    label: 'Contract Compliance',
    description: 'Checks BI/reporting tool operability against its data contract',
    category: 'reporting',
    required_integrations: ['looker', 'tableau', 'powerbi', 'metabase'],
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
```

- [ ] **Step 4: Update TOOL_MONITOR_TYPES**

Add the 6 new keys to the `TOOL_MONITOR_TYPES` array:

```typescript
export const TOOL_MONITOR_TYPES = [
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'QUERY_PERFORMANCE', 'COST_ANOMALY', 'STORAGE_GROWTH',
  'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS',
  'CONTRACT_COMPLIANCE_INGESTION', 'CONTRACT_COMPLIANCE_ORCHESTRATION',
  'CONTRACT_COMPLIANCE_TRANSFORMATION', 'CONTRACT_COMPLIANCE_WAREHOUSE',
  'CONTRACT_COMPLIANCE_INFRASTRUCTURE', 'CONTRACT_COMPLIANCE_REPORTING',
];
```

- [ ] **Step 5: Update TOOL_NODE_TYPE_MAP**

Add entries for each CONTRACT_COMPLIANCE_* key:

```typescript
  CONTRACT_COMPLIANCE_INGESTION: ['fivetran', 'airbyte'],
  CONTRACT_COMPLIANCE_ORCHESTRATION: ['airflow', 'dagster'],
  CONTRACT_COMPLIANCE_TRANSFORMATION: ['dbt_cloud', 'dbt_core'],
  CONTRACT_COMPLIANCE_WAREHOUSE: ['bigquery', 'snowflake', 'postgres', 'redshift', 'databricks'],
  CONTRACT_COMPLIANCE_INFRASTRUCTURE: ['linux_server'],
  CONTRACT_COMPLIANCE_REPORTING: ['looker', 'tableau', 'powerbi', 'metabase'],
```

- [ ] **Step 6: Update DOMAIN_MONITOR_MAP**

Add the appropriate CONTRACT_COMPLIANCE_* key to each domain set. Note: keys are **platform domain strings**, not MonitorCategory:

```typescript
export const DOMAIN_MONITOR_MAP: Record<string, Set<string>> = {
  ingestion: new Set(['SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT', 'CONTRACT_COMPLIANCE_INGESTION']),
  orchestration: new Set(['DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE', 'CONTRACT_COMPLIANCE_ORCHESTRATION']),
  transform: new Set(['DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS', 'CONTRACT_COMPLIANCE_TRANSFORMATION']),
  warehouse: new Set(['QUERY_PERFORMANCE', 'COST_ANOMALY', 'STORAGE_GROWTH', 'CONTRACT_COMPLIANCE_WAREHOUSE']),
  bi: new Set(['BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_CONTENT_HEALTH', 'BI_REFRESH_FAILURE', 'CONTRACT_COMPLIANCE_REPORTING']),
  infrastructure: new Set(['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS', 'CONTRACT_COMPLIANCE_INFRASTRUCTURE']),
};
```

- [ ] **Step 7: Verify TypeScript compiles**

Run: `npx tsc --noEmit`

- [ ] **Step 8: Commit**

```bash
git add types/monitor-catalog.ts
git commit -m "feat: add CONTRACT_COMPLIANCE monitor catalog entries for all domains"
```

---

### Task 4: Update Monitor Scoring — Conditional Coverage & Composite Health

**Files:**
- Modify: `lib/monitor-scoring.ts:28-68` (APPLICABLE_MONITORS), `lib/monitor-scoring.ts:208-238` (computeMonitorCoverage), `lib/monitor-scoring.ts:266-268` (getApplicableMonitorTypes)
- Modify: `lib/__tests__/monitor-scoring.test.ts`

**Important: Steps 4-6 must be done atomically** — adding CONTRACT_COMPLIANCE_* to APPLICABLE_MONITORS (Step 4) without simultaneously updating getApplicableMonitorTypes to filter them by default (Step 5) and computeMonitorCoverage to use the filtered helper (Step 6) will break existing tests that assert specific monitor counts. Make all three changes before running tests.

- [ ] **Step 1: Update test file imports**

In `lib/__tests__/monitor-scoring.test.ts`, update the import to include the new function:

```typescript
import {
  computeMonitorHealth,
  computeMonitorCoverage,
  computeMonitorScoring,
  computeCompositeToolHealth,
  resolveAssetCategory,
  healthStatusFromScore,
  getApplicableMonitorTypes,
  type AssetCategory,
} from '../monitor-scoring';
```

- [ ] **Step 2: Write failing tests for conditional coverage**

The test from Task 3 Step 1 should already be in place. Add more:

```typescript
describe('computeMonitorCoverage with hasContract', () => {
  it('includes CONTRACT_COMPLIANCE in available count when hasContract is true', () => {
    const result = computeMonitorCoverage(
      ['SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT', 'CONTRACT_COMPLIANCE_INGESTION'],
      'ingestion',
      { hasContract: true },
    );
    expect(result.available).toBe(4);
    expect(result.configured).toBe(4);
    expect(result.coveragePct).toBe(100);
  });

  it('excludes CONTRACT_COMPLIANCE from available count when hasContract is false', () => {
    const result = computeMonitorCoverage(
      ['SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT'],
      'ingestion',
      { hasContract: false },
    );
    expect(result.available).toBe(3);
    expect(result.configured).toBe(3);
    expect(result.coveragePct).toBe(100);
  });
});
```

- [ ] **Step 3: Write failing tests for composite tool health**

```typescript
describe('computeCompositeToolHealth', () => {
  it('weights tool monitors 40% and child health 60%', () => {
    const result = computeCompositeToolHealth(
      [{ lastStatus: 'PASS' }],  // tool health = 100
      [50],                       // child health = 50
    );
    // 100 * 0.4 + 50 * 0.6 = 40 + 30 = 70
    expect(result.healthScore).toBe(70);
    expect(result.healthStatus).toBe('degraded');
  });

  it('uses child health only when no tool monitors', () => {
    const result = computeCompositeToolHealth([], [80]);
    expect(result.healthScore).toBe(80);
    expect(result.healthStatus).toBe('degraded');
  });

  it('uses tool health only when no children', () => {
    const result = computeCompositeToolHealth(
      [{ lastStatus: 'PASS' }],
      [],
    );
    expect(result.healthScore).toBe(100);
    expect(result.healthStatus).toBe('healthy');
  });

  it('returns unmonitored when neither monitors nor children', () => {
    const result = computeCompositeToolHealth([], []);
    expect(result.healthScore).toBeNull();
    expect(result.healthStatus).toBe('unmonitored');
  });

  it('handles all-failing tool monitors with healthy children', () => {
    const result = computeCompositeToolHealth(
      [{ lastStatus: 'FAIL' }],  // tool health = 0
      [100],                      // child health = 100
    );
    // 0 * 0.4 + 100 * 0.6 = 60
    expect(result.healthScore).toBe(60);
    expect(result.healthStatus).toBe('at_risk');
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `npx vitest run lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: FAIL — functions don't exist yet / wrong signatures.

- [ ] **Step 5: Add CONTRACT_COMPLIANCE_* keys to APPLICABLE_MONITORS (do Steps 5-7 atomically)**

In `lib/monitor-scoring.ts`, add the contract compliance key to each category array:

```typescript
export const APPLICABLE_MONITORS: Record<AssetCategory, string[]> = {
  warehouse: [
    'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK', 'UNIQUENESS_CHECK',
    'REFERENTIAL', 'RANGE_VALIDATION', 'ACCEPTED_VALUES', 'DATE_CONSISTENCY',
    'DATA_TYPE_VALIDATION', 'OUTLIER_DETECTION',
    'CONTRACT_COMPLIANCE_WAREHOUSE',
  ],
  bi: [
    'BI_FRESHNESS_PROXY', 'BI_CONTENT_HEALTH', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE',
    'CONTRACT_COMPLIANCE_REPORTING',
  ],
  ingestion: [
    'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
    'CONTRACT_COMPLIANCE_INGESTION',
  ],
  orchestration: [
    'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
    'CONTRACT_COMPLIANCE_ORCHESTRATION',
  ],
  dbt_transform: [
    'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
    'CONTRACT_COMPLIANCE_TRANSFORMATION',
  ],
  infra: [
    'SERVER_HEALTH', 'CERTIFICATE', 'LOG_ANALYSIS',
    'CONTRACT_COMPLIANCE_INFRASTRUCTURE',
  ],
};
```

- [ ] **Step 6: Update getApplicableMonitorTypes to accept options**

Replace the existing function:

```typescript
export function getApplicableMonitorTypes(
  category: AssetCategory,
  options?: { hasContract?: boolean },
): string[] {
  const types = APPLICABLE_MONITORS[category] || [];
  if (options?.hasContract) return types;
  // Exclude CONTRACT_COMPLIANCE_* when no contract
  return types.filter(t => !t.startsWith('CONTRACT_COMPLIANCE_'));
}
```

- [ ] **Step 7: Update computeMonitorCoverage to accept options**

Change the signature and pass through:

```typescript
export function computeMonitorCoverage(
  configuredTypes: string[],
  category: AssetCategory,
  options?: { hasContract?: boolean },
): CoverageResult {
  const applicableTypes = getApplicableMonitorTypes(category, options);
  if (applicableTypes.length === 0) {
    return { coveragePct: 0, coverageStatus: 'none', configured: 0, available: 0, missingTypes: [] };
  }
  // ... rest of function unchanged, but use applicableTypes instead of APPLICABLE_MONITORS[category]
```

Update the body to use `applicableTypes` directly (it already does via the old call, just need to replace `const applicableTypes = APPLICABLE_MONITORS[category] || [];` with using the helper).

- [ ] **Step 8: Update computeMonitorScoring to accept options**

```typescript
export function computeMonitorScoring(
  monitors: Array<{ monitorType: string; lastStatus: string | null }>,
  category: AssetCategory,
  options?: { hasContract?: boolean },
): MonitorScoringResult {
  const health = computeMonitorHealth(monitors);
  const configuredTypes = [...new Set(monitors.map(m => m.monitorType.toUpperCase()))];
  const coverage = computeMonitorCoverage(configuredTypes, category, options);
  return { ...health, ...coverage };
}
```

- [ ] **Step 9: Add computeCompositeToolHealth function**

Add after `computeMonitorScoring`:

```typescript
const TOOL_MONITOR_WEIGHT = 0.4;
const CHILD_HEALTH_WEIGHT = 0.6;

export function computeCompositeToolHealth(
  toolMonitors: Array<{ lastStatus: string | null }>,
  childAssetHealthScores: number[],
): HealthResult {
  const toolHealth = computeMonitorHealth(toolMonitors);
  const hasToolHealth = toolHealth.healthScore !== null;
  const hasChildHealth = childAssetHealthScores.length > 0;

  if (!hasToolHealth && !hasChildHealth) {
    return { healthScore: null, healthStatus: 'unmonitored' };
  }

  if (!hasToolHealth) {
    const avg = childAssetHealthScores.reduce((a, b) => a + b, 0) / childAssetHealthScores.length;
    const score = Math.round(avg * 10) / 10;
    return { healthScore: score, healthStatus: healthStatusFromScore(score) };
  }

  if (!hasChildHealth) {
    return toolHealth;
  }

  const childAvg = childAssetHealthScores.reduce((a, b) => a + b, 0) / childAssetHealthScores.length;
  const composite = toolHealth.healthScore! * TOOL_MONITOR_WEIGHT + childAvg * CHILD_HEALTH_WEIGHT;
  const score = Math.round(composite * 10) / 10;
  return { healthScore: score, healthStatus: healthStatusFromScore(score) };
}
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `npx vitest run lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: All tests PASS.

- [ ] **Step 11: Commit**

```bash
git add lib/monitor-scoring.ts lib/__tests__/monitor-scoring.test.ts
git commit -m "feat: add composite tool health and conditional CONTRACT_COMPLIANCE coverage"
```

**Note:** Existing tests for `computeMonitorCoverage` and `getApplicableMonitorTypes` should still pass because `CONTRACT_COMPLIANCE_*` keys are filtered out by default when no `hasContract` option is provided. The existing test assertions for counts (e.g., `toHaveLength(11)` for warehouse) remain correct.

---

### Task 5: Fix InspectorPanel Unmonitored State and Composite Health

**Files:**
- Modify: `components/lineage/pipeline-overview/InspectorPanel.tsx:104-113` (toolScoring useMemo), `components/lineage/pipeline-overview/InspectorPanel.tsx:207-265` (health/coverage rendering)

- [ ] **Step 1: Remove nodeMonitors.length === 0 early-return from toolScoring**

Change the `toolScoring` useMemo (lines 104-113) from:

```typescript
const toolScoring = useMemo((): MonitorScoringResult | null => {
  if (nodeMonitors.length === 0) return null;
  const category = resolveAssetCategory(node.layer, node.metadata?.platformDomain as string, node.platform ?? undefined);
  if (!category) return null;
  return computeMonitorScoring(
    nodeMonitors.map(m => ({ monitorType: m.monitorType || '', lastStatus: m.lastStatus })),
    category,
  );
}, [nodeMonitors, node.layer, node.metadata?.platformDomain, node.platform]);
```

to:

```typescript
const toolCategory = useMemo(
  () => resolveAssetCategory(node.layer, node.metadata?.platformDomain as string, node.platform ?? undefined),
  [node.layer, node.metadata?.platformDomain, node.platform],
);

const toolScoring = useMemo((): MonitorScoringResult | null => {
  if (!toolCategory) return null;
  // TODO: pass hasContract once contract data is available in this component
  return computeMonitorScoring(
    nodeMonitors.map(m => ({ monitorType: m.monitorType || '', lastStatus: m.lastStatus })),
    toolCategory,
  );
}, [nodeMonitors, toolCategory]);
```

- [ ] **Step 2: Update health/coverage rendering to show unmonitored state**

Change the condition at line 208 from:

```tsx
{toolScoring && toolScoring.healthScore != null && (
```

to:

```tsx
{toolScoring && (
```

Then inside the health section, handle unmonitored:

```tsx
{/* Monitor Health & Coverage */}
{toolScoring && (
  <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] space-y-2">
    <div className="flex items-center justify-between">
      <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Monitor Health</span>
      <div className="flex items-center gap-2">
        {toolScoring.healthStatus === 'unmonitored' ? (
          <span className="text-[11px] font-medium text-[#6B7280]">Unmonitored</span>
        ) : (
          <>
            <div className="w-14 h-1.5 rounded-full bg-[var(--subtle-bg)] overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${toolScoring.healthScore}%`,
                  backgroundColor: toolScoring.healthStatus === 'healthy' ? '#10B981'
                    : toolScoring.healthStatus === 'degraded' ? '#F59E0B'
                    : toolScoring.healthStatus === 'at_risk' ? '#F97316'
                    : '#EF4444',
                }}
              />
            </div>
            <span
              className="text-[11px] font-medium"
              style={{
                color: toolScoring.healthStatus === 'healthy' ? '#10B981'
                  : toolScoring.healthStatus === 'degraded' ? '#F59E0B'
                  : toolScoring.healthStatus === 'at_risk' ? '#F97316'
                  : '#EF4444',
              }}
            >
              {Math.round(toolScoring.healthScore!)}%
            </span>
          </>
        )}
      </div>
    </div>
    <div className="flex items-center justify-between">
      <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Coverage</span>
      <div className="flex items-center gap-2">
        <div className="w-14 h-1.5 rounded-full bg-[var(--subtle-bg)] overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{
              width: `${Math.min(toolScoring.coveragePct, 100)}%`,
              backgroundColor: toolScoring.coverageStatus === 'good' ? '#10B981'
                : toolScoring.coverageStatus === 'partial' ? '#F59E0B'
                : '#6B7280',
            }}
          />
        </div>
        <span
          className="text-[11px] font-medium"
          style={{
            color: toolScoring.coverageStatus === 'good' ? '#10B981'
              : toolScoring.coverageStatus === 'partial' ? '#F59E0B'
              : '#6B7280',
          }}
        >
          {toolScoring.configured}/{toolScoring.available}
        </span>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 3: Update effectiveHealthColor to handle unmonitored**

Change lines 115-122 to always return gray for unmonitored:

```typescript
const effectiveHealthColor = toolScoring
  ? (toolScoring.healthStatus === 'healthy' ? '#10B981'
    : toolScoring.healthStatus === 'degraded' ? '#F59E0B'
    : toolScoring.healthStatus === 'at_risk' ? '#F97316'
    : toolScoring.healthStatus === 'unhealthy' ? '#EF4444'
    : '#6B7280')
  : '#6B7280';
```

- [ ] **Step 4: Verify the app compiles and renders**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add components/lineage/pipeline-overview/InspectorPanel.tsx
git commit -m "fix: show unmonitored state for tool nodes instead of hiding health/coverage"
```

---

### Task 6: Remove Freshness/Extraction Form Fields from Pipeline Settings

**Files:**
- Modify: `app/(dashboard)/dashboard/pipeline/settings/page.tsx:70-74` (initial state), `app/(dashboard)/dashboard/pipeline/settings/page.tsx:284-288` (load), `app/(dashboard)/dashboard/pipeline/settings/page.tsx:522-545` (form fields)

- [ ] **Step 1: Remove from initial contractForm state**

Change lines 70-74 from:

```typescript
const [contractForm, setContractForm] = useState<PipelineContractData>({
  ownerUser: null, ownerTeam: null, contactChannel: null,
  slaTier: null, expectedFreshnessMinutes: null,
  expectedExtractionFrequencyMinutes: null, alertPolicyJson: null, notes: null,
});
```

to:

```typescript
const [contractForm, setContractForm] = useState<PipelineContractData>({
  ownerUser: null, ownerTeam: null, contactChannel: null,
  slaTier: null, alertPolicyJson: null, notes: null,
});
```

- [ ] **Step 2: Remove from contract load logic**

Find the contract loading section (around line 286) and remove the two field assignments for `expectedFreshnessMinutes` and `expectedExtractionFrequencyMinutes`.

- [ ] **Step 3: Remove the form grid with freshness/extraction inputs**

Remove the entire grid div (lines 522-545) that contains the "Expected Freshness (minutes)" and "Extraction Frequency (minutes)" inputs.

- [ ] **Step 4: Verify the page compiles and renders**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add app/(dashboard)/dashboard/pipeline/settings/page.tsx
git commit -m "fix: remove freshness/extraction fields from pipeline contract form"
```

---

### Task 7: Run Full Test Suite and Verify

- [ ] **Step 1: Run all monitor scoring tests**

Run: `npx vitest run lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: All tests PASS.

- [ ] **Step 2: Run full TypeScript check**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Search for any remaining references to removed fields**

```bash
grep -rn "expectedFreshnessMinutes\|expectedExtractionFrequency" --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".md"
```

Expected: No results (only markdown docs may still reference them).

- [ ] **Step 4: Commit any remaining fixes**

If Step 3 found references, fix them and commit.
