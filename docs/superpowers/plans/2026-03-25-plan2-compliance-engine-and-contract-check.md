# Plan 2: Compliance Engine & CONTRACT_CHECK Monitor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the compliance comparison engine (per-field direction, tier baselines), SLA ↔ contract sync logic, and the CONTRACT_CHECK monitor type.

**Architecture:** A `lib/compliance/` module handles per-field comparison direction and compliance evaluation. The existing `lib/sla-utils.ts` `isLessStrictClient` function is extended/reused. A new `lib/data-contracts/sync.ts` module handles auto-sync (SLA→contract) when contracts are disabled. The CONTRACT_CHECK monitor is added to the monitor catalog and scoring system.

**Tech Stack:** TypeScript, Vitest, Prisma, Zod

**Spec:** `docs/superpowers/specs/2026-03-25-sla-and-data-contracts-design.md`

**Depends on:** Plan 1 (type renames and data contract foundation) must be completed first.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `lib/compliance/field-comparison.ts` | Create | Per-field comparison direction and compliance check |
| `lib/compliance/tier-baselines.ts` | Create | SLA tier default values (T0-T3) |
| `lib/compliance/evaluate.ts` | Create | Evaluate node compliance against contract or tier |
| `lib/compliance/__tests__/field-comparison.test.ts` | Create | Tests for field comparison |
| `lib/compliance/__tests__/tier-baselines.test.ts` | Create | Tests for tier baselines |
| `lib/compliance/__tests__/evaluate.test.ts` | Create | Tests for compliance evaluation |
| `lib/data-contracts/sync.ts` | Create | Auto-sync SLA→contract when contracts disabled |
| `lib/data-contracts/__tests__/sync.test.ts` | Create | Tests for sync logic |
| `types/monitor-catalog.ts` | Modify | Add CONTRACT_CHECK monitor definition |
| `lib/monitor-scoring.ts` | Modify | Add CONTRACT_CHECK to applicable monitors |
| `lib/__tests__/monitor-scoring.test.ts` | Modify | Tests for CONTRACT_CHECK in scoring |

**Out of scope for this plan:**
- UI rendering of compliance badges (Plan 3)
- Sources data contracts tab (Plan 3)
- Multi-select UX (Plan 3)

---

### Task 1: Per-Field Comparison Direction

**Files:**
- Create: `lib/compliance/field-comparison.ts`
- Create: `lib/compliance/__tests__/field-comparison.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// lib/compliance/__tests__/field-comparison.test.ts
import { describe, it, expect } from 'vitest';
import { compareFieldToBaseline, type ComplianceStatus } from '../field-comparison';

describe('compareFieldToBaseline — numeric lower-is-stricter', () => {
  it('returns compliant when equal', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 30, 30)).toBe('compliant');
  });
  it('returns override when SLA is stricter (lower)', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 15, 30)).toBe('override');
  });
  it('returns violation when SLA is looser (higher)', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 60, 30)).toBe('violation');
  });
});

describe('compareFieldToBaseline — numeric higher-is-stricter', () => {
  it('returns override when SLA is stricter (higher retries)', () => {
    expect(compareFieldToBaseline('maxRetries', 5, 3)).toBe('override');
  });
  it('returns violation when SLA is looser (lower retries)', () => {
    expect(compareFieldToBaseline('maxRetries', 1, 3)).toBe('violation');
  });
});

describe('compareFieldToBaseline — boolean true-is-stricter', () => {
  it('returns override when SLA=true, baseline=false', () => {
    expect(compareFieldToBaseline('oncallRequired', true, false)).toBe('override');
  });
  it('returns violation when SLA=false, baseline=true', () => {
    expect(compareFieldToBaseline('oncallRequired', false, true)).toBe('violation');
  });
  it('returns compliant when both true', () => {
    expect(compareFieldToBaseline('oncallRequired', true, true)).toBe('compliant');
  });
});

describe('compareFieldToBaseline — ordered enum', () => {
  it('schemaChangePolicy: fail > warn = override', () => {
    expect(compareFieldToBaseline('schemaChangePolicy', 'fail', 'warn')).toBe('override');
  });
  it('schemaChangePolicy: ignore < warn = violation', () => {
    expect(compareFieldToBaseline('schemaChangePolicy', 'ignore', 'warn')).toBe('violation');
  });
  it('connectorPriority: critical > high = override', () => {
    expect(compareFieldToBaseline('connectorPriority', 'critical', 'high')).toBe('override');
  });
});

describe('compareFieldToBaseline — superset (requiredTests)', () => {
  it('superset is override', () => {
    expect(compareFieldToBaseline('requiredTests', ['not_null', 'unique', 'freshness'], ['not_null', 'unique'])).toBe('override');
  });
  it('subset is violation', () => {
    expect(compareFieldToBaseline('requiredTests', ['not_null'], ['not_null', 'unique'])).toBe('violation');
  });
  it('equal set is compliant', () => {
    expect(compareFieldToBaseline('requiredTests', ['not_null', 'unique'], ['not_null', 'unique'])).toBe('compliant');
  });
});

describe('compareFieldToBaseline — null handling', () => {
  it('returns unknown when SLA value is null', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', null, 30)).toBe('unknown');
  });
  it('returns unknown when baseline is null', () => {
    expect(compareFieldToBaseline('expectedFreshnessMinutes', 30, null)).toBe('unknown');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run lib/compliance/__tests__/field-comparison.test.ts --reporter=verbose`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement field-comparison.ts**

```typescript
// lib/compliance/field-comparison.ts

export type ComplianceStatus = 'compliant' | 'override' | 'violation' | 'unknown';

// Fields where lower numeric value = stricter
const LOWER_IS_STRICTER = new Set([
  'expectedFreshnessMinutes',
  'expectedExtractionFrequencyMinutes',
  'maxQueryCostUsd',
  'maxSyncDelayMinutes',
  'retryBackoffMinutes',
  'refreshSlaMinutes',
  'expectedRunCadenceMinutes',
]);

// Fields where higher numeric value = stricter
const HIGHER_IS_STRICTER = new Set([
  'maxRetries',
  'retentionDays',
]);

// Boolean fields where true = stricter
const TRUE_IS_STRICTER = new Set([
  'requireDryRun',
  'oncallRequired',
  'encryptionRequired',
  'readOnlyEnforced',
  'freshnessTestsRequired',
  'ownerAckRequired',
]);

// Ordered enums: first = strictest
const ORDERED_ENUMS: Record<string, string[]> = {
  schemaChangePolicy: ['fail', 'warn', 'ignore'],
  connectorPriority: ['critical', 'high', 'normal', 'low'],
};

// Set fields where superset = stricter
const SET_FIELDS = new Set(['requiredTests']);

export function compareFieldToBaseline(
  fieldName: string,
  slaValue: unknown,
  baselineValue: unknown,
): ComplianceStatus {
  if (slaValue == null || baselineValue == null) return 'unknown';

  // Set comparison
  if (SET_FIELDS.has(fieldName)) {
    const slaSet = new Set(slaValue as string[]);
    const baseSet = new Set(baselineValue as string[]);
    const slaHasAll = [...baseSet].every(v => slaSet.has(v));
    const baseHasAll = [...slaSet].every(v => baseSet.has(v));
    if (slaHasAll && baseHasAll) return 'compliant';
    if (slaHasAll) return 'override'; // SLA is superset
    return 'violation'; // SLA is subset
  }

  // Ordered enum comparison
  if (fieldName in ORDERED_ENUMS) {
    const order = ORDERED_ENUMS[fieldName];
    const slaIdx = order.indexOf(String(slaValue));
    const baseIdx = order.indexOf(String(baselineValue));
    if (slaIdx === -1 || baseIdx === -1) return 'unknown';
    if (slaIdx === baseIdx) return 'compliant';
    return slaIdx < baseIdx ? 'override' : 'violation';
  }

  // Boolean comparison
  if (TRUE_IS_STRICTER.has(fieldName)) {
    if (slaValue === baselineValue) return 'compliant';
    return slaValue === true ? 'override' : 'violation';
  }

  // Numeric comparison
  const slaNum = Number(slaValue);
  const baseNum = Number(baselineValue);
  if (Number.isNaN(slaNum) || Number.isNaN(baseNum)) return 'unknown';

  if (slaNum === baseNum) return 'compliant';

  if (LOWER_IS_STRICTER.has(fieldName)) {
    return slaNum < baseNum ? 'override' : 'violation';
  }

  if (HIGHER_IS_STRICTER.has(fieldName)) {
    return slaNum > baseNum ? 'override' : 'violation';
  }

  return 'unknown';
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run lib/compliance/__tests__/field-comparison.test.ts --reporter=verbose`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/compliance/field-comparison.ts lib/compliance/__tests__/field-comparison.test.ts
git commit -m "feat: add per-field compliance comparison with direction-aware logic"
```

---

### Task 2: SLA Tier Baseline Definitions

**Files:**
- Create: `lib/compliance/tier-baselines.ts`
- Create: `lib/compliance/__tests__/tier-baselines.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// lib/compliance/__tests__/tier-baselines.test.ts
import { describe, it, expect } from 'vitest';
import { getTierBaseline, getTierBaselineValue } from '../tier-baselines';

describe('getTierBaseline', () => {
  it('T0 has strictest freshness', () => {
    const baseline = getTierBaseline('T0');
    expect(baseline.expectedFreshnessMinutes).toBe(15);
  });

  it('T3 has most relaxed freshness', () => {
    const baseline = getTierBaseline('T3');
    expect(baseline.expectedFreshnessMinutes).toBe(1440);
  });

  it('T0 requires oncall', () => {
    const baseline = getTierBaseline('T0');
    expect(baseline.oncallRequired).toBe(true);
  });

  it('T2 does not require oncall', () => {
    const baseline = getTierBaseline('T2');
    expect(baseline.oncallRequired).toBe(false);
  });
});

describe('getTierBaselineValue', () => {
  it('returns the value for a field in a tier', () => {
    expect(getTierBaselineValue('T1', 'maxSyncDelayMinutes')).toBe(60);
  });

  it('returns undefined for a field not in tier baseline', () => {
    expect(getTierBaselineValue('T0', 'maxQueryCostUsd')).toBeUndefined();
  });

  it('returns undefined for invalid tier', () => {
    expect(getTierBaselineValue('T9' as any, 'expectedFreshnessMinutes')).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run lib/compliance/__tests__/tier-baselines.test.ts --reporter=verbose`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement tier-baselines.ts**

```typescript
// lib/compliance/tier-baselines.ts

import type { SlaTier } from '@/components/contracts/types';

export interface TierBaseline {
  expectedFreshnessMinutes: number;
  maxSyncDelayMinutes: number;
  oncallRequired: boolean;
  maxRetries: number;
  schemaChangePolicy: 'fail' | 'warn' | 'ignore';
}

const TIER_BASELINES: Record<SlaTier, TierBaseline> = {
  T0: {
    expectedFreshnessMinutes: 15,
    maxSyncDelayMinutes: 15,
    oncallRequired: true,
    maxRetries: 5,
    schemaChangePolicy: 'fail',
  },
  T1: {
    expectedFreshnessMinutes: 60,
    maxSyncDelayMinutes: 60,
    oncallRequired: true,
    maxRetries: 3,
    schemaChangePolicy: 'warn',
  },
  T2: {
    expectedFreshnessMinutes: 360,
    maxSyncDelayMinutes: 360,
    oncallRequired: false,
    maxRetries: 3,
    schemaChangePolicy: 'warn',
  },
  T3: {
    expectedFreshnessMinutes: 1440,
    maxSyncDelayMinutes: 1440,
    oncallRequired: false,
    maxRetries: 1,
    schemaChangePolicy: 'ignore',
  },
};

export function getTierBaseline(tier: SlaTier): TierBaseline {
  return TIER_BASELINES[tier];
}

export function getTierBaselineValue(tier: SlaTier, field: string): unknown {
  const baseline = TIER_BASELINES[tier];
  if (!baseline) return undefined;
  return (baseline as Record<string, unknown>)[field];
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run lib/compliance/__tests__/tier-baselines.test.ts --reporter=verbose`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/compliance/tier-baselines.ts lib/compliance/__tests__/tier-baselines.test.ts
git commit -m "feat: add SLA tier baseline definitions (T0-T3)"
```

---

### Task 3: Compliance Evaluation Engine

**Files:**
- Create: `lib/compliance/evaluate.ts`
- Create: `lib/compliance/__tests__/evaluate.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// lib/compliance/__tests__/evaluate.test.ts
import { describe, it, expect } from 'vitest';
import { evaluateNodeCompliance, type NodeComplianceResult } from '../evaluate';

describe('evaluateNodeCompliance against tier baseline', () => {
  it('returns compliant when SLA matches T0 baseline', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 15, oncallRequired: true },
      null,  // no contract
      'T0',
    );
    expect(result.overallStatus).toBe('compliant');
    expect(result.fields.every(f => f.status === 'compliant')).toBe(true);
  });

  it('returns violation when SLA is looser than T0', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 60 },
      null,
      'T0',
    );
    const freshness = result.fields.find(f => f.fieldName === 'expectedFreshnessMinutes');
    expect(freshness?.status).toBe('violation');
    expect(result.overallStatus).toBe('violation');
  });

  it('returns override when SLA is stricter than T1', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 15 },
      null,
      'T1',
    );
    const freshness = result.fields.find(f => f.fieldName === 'expectedFreshnessMinutes');
    expect(freshness?.status).toBe('override');
    expect(result.overallStatus).toBe('override');
  });
});

describe('evaluateNodeCompliance against contract', () => {
  it('uses contract as baseline when provided', () => {
    const contract = { expectedFreshnessMinutes: 30, oncallRequired: true };
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 60 },
      contract,
      'T0',  // tier ignored when contract exists
    );
    const freshness = result.fields.find(f => f.fieldName === 'expectedFreshnessMinutes');
    expect(freshness?.status).toBe('violation');
    expect(freshness?.contractValue).toBe(30);
    expect(freshness?.slaValue).toBe(60);
  });
});

describe('evaluateNodeCompliance — overall status priority', () => {
  it('violation wins over override', () => {
    const result = evaluateNodeCompliance(
      { expectedFreshnessMinutes: 10, oncallRequired: false }, // fresher=override, no oncall=violation
      { expectedFreshnessMinutes: 30, oncallRequired: true },
      'T0',
    );
    expect(result.overallStatus).toBe('violation');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run lib/compliance/__tests__/evaluate.test.ts --reporter=verbose`
Expected: FAIL.

- [ ] **Step 3: Implement evaluate.ts**

```typescript
// lib/compliance/evaluate.ts

import type { SlaTier } from '@/components/contracts/types';
import { compareFieldToBaseline, type ComplianceStatus } from './field-comparison';
import { getTierBaseline } from './tier-baselines';

export interface FieldComplianceResult {
  fieldName: string;
  slaValue: unknown;
  contractValue: unknown | null;
  baselineValue: unknown;
  status: ComplianceStatus;
}

export interface NodeComplianceResult {
  overallStatus: 'compliant' | 'override' | 'violation' | 'unknown';
  fields: FieldComplianceResult[];
}

/**
 * Evaluate a node's SLA values against the active baseline.
 * If a contract is provided, it's used as baseline. Otherwise, tier baseline is used.
 */
export function evaluateNodeCompliance(
  slaValues: Record<string, unknown>,
  contractValues: Record<string, unknown> | null,
  slaTier: SlaTier | null,
): NodeComplianceResult {
  // Determine baseline: contract if provided, otherwise tier
  const baseline: Record<string, unknown> = contractValues
    ? contractValues
    : slaTier
      ? (getTierBaseline(slaTier) as unknown as Record<string, unknown>)
      : {};

  const fields: FieldComplianceResult[] = [];

  // Compare each field that has a baseline value
  for (const [fieldName, baselineValue] of Object.entries(baseline)) {
    if (baselineValue == null) continue;
    const slaValue = slaValues[fieldName] ?? null;
    const status = compareFieldToBaseline(fieldName, slaValue, baselineValue);

    fields.push({
      fieldName,
      slaValue,
      contractValue: contractValues?.[fieldName] ?? null,
      baselineValue,
      status,
    });
  }

  // Overall status: violation > override > compliant > unknown
  let overallStatus: NodeComplianceResult['overallStatus'] = 'compliant';
  for (const f of fields) {
    if (f.status === 'violation') { overallStatus = 'violation'; break; }
    if (f.status === 'override' && overallStatus !== 'violation') overallStatus = 'override';
    if (f.status === 'unknown' && overallStatus === 'compliant') overallStatus = 'unknown';
  }

  if (fields.length === 0) overallStatus = 'unknown';

  return { overallStatus, fields };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run lib/compliance/__tests__/evaluate.test.ts --reporter=verbose`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/compliance/evaluate.ts lib/compliance/__tests__/evaluate.test.ts
git commit -m "feat: add compliance evaluation engine (node SLA vs contract/tier baseline)"
```

---

### Task 4: SLA → Contract Auto-Sync

**Files:**
- Create: `lib/data-contracts/sync.ts`
- Create: `lib/data-contracts/__tests__/sync.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// lib/data-contracts/__tests__/sync.test.ts
import { describe, it, expect } from 'vitest';
import { computeGroupContractFromSLAs } from '../sync';

describe('computeGroupContractFromSLAs', () => {
  it('returns mode value for numeric fields', () => {
    const slas = [
      { expectedFreshnessMinutes: 30 },
      { expectedFreshnessMinutes: 30 },
      { expectedFreshnessMinutes: 60 },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBe(30);
  });

  it('returns mode value for string fields', () => {
    const slas = [
      { slaTier: 'T1' },
      { slaTier: 'T1' },
      { slaTier: 'T0' },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.slaTier).toBe('T1');
  });

  it('returns null for field where all values are null', () => {
    const slas = [
      { expectedFreshnessMinutes: null },
      { expectedFreshnessMinutes: null },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBeNull();
  });

  it('handles single SLA', () => {
    const slas = [{ expectedFreshnessMinutes: 15, slaTier: 'T0' }];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBe(15);
    expect(result.slaTier).toBe('T0');
  });

  it('handles empty array', () => {
    const result = computeGroupContractFromSLAs([]);
    expect(result).toEqual({});
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run lib/data-contracts/__tests__/sync.test.ts --reporter=verbose`
Expected: FAIL.

- [ ] **Step 3: Implement sync.ts**

```typescript
// lib/data-contracts/sync.ts

/**
 * Auto-sync: compute a group-level contract from node SLA values.
 * Uses the statistical mode (most common value) for each field.
 *
 * When contracts are disabled, this runs on every SLA save to keep
 * the auto-synced contract in sync.
 */

const SYNCABLE_FIELDS = [
  'ownerUser', 'ownerTeam', 'contactChannel', 'slaTier',
  'expectedFreshnessMinutes', 'expectedExtractionFrequencyMinutes',
  'notes',
] as const;

/**
 * Compute the mode (most frequent non-null value) for each field across SLAs.
 */
export function computeGroupContractFromSLAs(
  slas: Record<string, unknown>[],
): Record<string, unknown> {
  if (slas.length === 0) return {};

  const result: Record<string, unknown> = {};

  for (const field of SYNCABLE_FIELDS) {
    const counts = new Map<string, number>();
    let nullCount = 0;

    for (const sla of slas) {
      const val = sla[field];
      if (val == null) {
        nullCount++;
        continue;
      }
      const key = JSON.stringify(val);
      counts.set(key, (counts.get(key) || 0) + 1);
    }

    if (counts.size === 0) {
      result[field] = null;
      continue;
    }

    let maxCount = 0;
    let modeKey = '';
    for (const [key, count] of counts) {
      if (count > maxCount) {
        maxCount = count;
        modeKey = key;
      }
    }

    result[field] = JSON.parse(modeKey);
  }

  return result;
}

/**
 * Determine which SLAs deviate from the group contract and need exception contracts.
 */
export function findDeviatingNodes(
  slas: Array<{ nodeId: string; values: Record<string, unknown> }>,
  groupContract: Record<string, unknown>,
): string[] {
  const deviating: string[] = [];

  for (const { nodeId, values } of slas) {
    for (const field of SYNCABLE_FIELDS) {
      const slaVal = values[field];
      const contractVal = groupContract[field];
      if (slaVal != null && contractVal != null && JSON.stringify(slaVal) !== JSON.stringify(contractVal)) {
        deviating.push(nodeId);
        break;
      }
    }
  }

  return deviating;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run lib/data-contracts/__tests__/sync.test.ts --reporter=verbose`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/data-contracts/sync.ts lib/data-contracts/__tests__/sync.test.ts
git commit -m "feat: add SLA → contract auto-sync with mode-based group aggregation"
```

---

### Task 5: Add CONTRACT_CHECK Monitor to Catalog

**Files:**
- Modify: `types/monitor-catalog.ts`
- Modify: `lib/monitor-scoring.ts`
- Modify: `lib/__tests__/monitor-scoring.test.ts`

- [ ] **Step 1: Write failing test for CONTRACT_CHECK in applicable monitors**

Add to `lib/__tests__/monitor-scoring.test.ts`:

```typescript
describe('CONTRACT_CHECK in APPLICABLE_MONITORS', () => {
  it('getApplicableMonitorTypes includes CONTRACT_CHECK when hasContract is true', () => {
    const types = getApplicableMonitorTypes('warehouse', { hasContract: true });
    expect(types).toContain('CONTRACT_CHECK');
  });

  it('getApplicableMonitorTypes excludes CONTRACT_CHECK when hasContract is false', () => {
    const types = getApplicableMonitorTypes('warehouse', { hasContract: false });
    expect(types).not.toContain('CONTRACT_CHECK');
  });

  it('getApplicableMonitorTypes excludes CONTRACT_CHECK by default', () => {
    const types = getApplicableMonitorTypes('warehouse');
    expect(types).not.toContain('CONTRACT_CHECK');
  });

  it('CONTRACT_CHECK is available for all data asset categories', () => {
    for (const cat of ['warehouse', 'bi', 'dbt_transform'] as const) {
      const types = getApplicableMonitorTypes(cat, { hasContract: true });
      expect(types).toContain('CONTRACT_CHECK');
    }
  });

  it('CONTRACT_CHECK is NOT available for tool-only categories', () => {
    for (const cat of ['ingestion', 'orchestration', 'infra'] as const) {
      const types = getApplicableMonitorTypes(cat, { hasContract: true });
      expect(types).not.toContain('CONTRACT_CHECK');
    }
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: FAIL — `getApplicableMonitorTypes` doesn't accept options or CONTRACT_CHECK doesn't exist.

- [ ] **Step 3: Add CONTRACT_CHECK to monitor catalog**

In `types/monitor-catalog.ts`, add after the last entry in `MONITOR_CATALOG`:

```typescript
  // ==========================================================================
  // CONTRACT CHECK — Validates data asset against its data contract
  // ==========================================================================
  {
    key: 'CONTRACT_CHECK',
    label: 'Contract Check',
    description: 'Validates a data asset against its data contract, checking per-field compliance',
    category: 'warehouse',  // Cross-category, but primary is warehouse
    required_integrations: [],  // Available for any data asset
    target_selector_type: 'none',
    executor_type: 'tool_api',
    supports_baselines: false,
    auto_configurable: false,
    config_schema: [],
  },
```

- [ ] **Step 4: Add CONTRACT_CHECK to APPLICABLE_MONITORS (data asset categories only)**

In `lib/monitor-scoring.ts`, add `'CONTRACT_CHECK'` to the `warehouse`, `bi`, and `dbt_transform` arrays only (not ingestion, orchestration, or infra — those are tool categories).

- [ ] **Step 5: Update getApplicableMonitorTypes to accept options**

In `lib/monitor-scoring.ts`, update the function signature:

```typescript
export function getApplicableMonitorTypes(
  category: AssetCategory,
  options?: { hasContract?: boolean },
): string[] {
  const types = APPLICABLE_MONITORS[category] || [];
  if (options?.hasContract) return types;
  // Exclude CONTRACT_CHECK when no contract
  return types.filter(t => t !== 'CONTRACT_CHECK');
}
```

- [ ] **Step 6: Update computeMonitorCoverage to pass through options**

```typescript
export function computeMonitorCoverage(
  configuredTypes: string[],
  category: AssetCategory,
  options?: { hasContract?: boolean },
): CoverageResult {
  const applicableTypes = getApplicableMonitorTypes(category, options);
  // ... rest unchanged, use applicableTypes
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `npx vitest run lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: All PASS (existing tests unaffected because CONTRACT_CHECK filtered by default).

- [ ] **Step 8: Commit**

```bash
git add types/monitor-catalog.ts lib/monitor-scoring.ts lib/__tests__/monitor-scoring.test.ts
git commit -m "feat: add CONTRACT_CHECK monitor type with conditional availability"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Run all compliance tests**

Run: `npx vitest run lib/compliance/ lib/data-contracts/ lib/__tests__/monitor-scoring.test.ts --reporter=verbose`
Expected: All PASS.

- [ ] **Step 2: Run full TypeScript check**

Run: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Run full test suite**

Run: `npx vitest run --reporter=verbose`
Expected: All tests pass.

- [ ] **Step 4: Commit any fixes**
