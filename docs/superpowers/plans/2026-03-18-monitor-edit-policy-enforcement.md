# Monitor Edit & Runtime Policy Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add monitor config editing with runtime policy enforcement, per-field override tracking, and policy violation warnings.

**Architecture:** Next.js resolves the effective policy for a monitor's target asset and sends both `policy_config` and `config` to Python. Python merges them (policy as base, overrides win), executes the monitor, and logs provenance. The UI shows inline policy badges per config field with override/violation status.

**Tech Stack:** Prisma (data model), Next.js API routes, FastAPI/Python (executor), React/Tailwind (UI components), pytest (Python tests)

**Spec:** `docs/superpowers/specs/2026-03-18-monitor-edit-policy-enforcement-design.md`

---

### Task 1: Shared policy-to-config mapping (Python)

**Files:**
- Create: `scanner/monitors/policy_config.py`
- Create: `scanner/monitors/tests/test_policy_config.py`
- Modify: `scanner/monitors/recommender.py:136-163` (move `_sensitivity_to_zscore`)

- [ ] **Step 1: Write tests for `sensitivity_to_zscore`**

```python
# scanner/monitors/tests/test_policy_config.py
"""Tests for policy_config module."""
import pytest
from scanner.monitors.policy_config import sensitivity_to_zscore


class TestSensitivityToZscore:
    def test_max_sensitivity(self):
        assert sensitivity_to_zscore(0.99) == 2.0

    def test_standard_sensitivity(self):
        assert sensitivity_to_zscore(0.95) == 3.0

    def test_low_sensitivity(self):
        assert sensitivity_to_zscore(0.50) == 5.0

    def test_clamp_above_1(self):
        assert sensitivity_to_zscore(1.5) == 2.0

    def test_clamp_below_0(self):
        assert sensitivity_to_zscore(-0.1) == 5.0

    def test_interpolation(self):
        result = sensitivity_to_zscore(0.90)
        assert result == 3.5
```

- [ ] **Step 2: Write tests for `merge_policy_config`**

```python
# append to scanner/monitors/tests/test_policy_config.py
from scanner.monitors.policy_config import merge_policy_config


class TestMergePolicyConfig:
    def test_policy_values_used_when_no_overrides(self):
        merged, prov = merge_policy_config(
            monitor_type="FRESHNESS",
            config={"timestamp_column": "_loaded_at"},
            policy_config={"max_hours": 2, "warning_hours": 1},
            policy_overrides=[],
        )
        assert merged["max_hours"] == 2
        assert merged["warning_hours"] == 1
        assert merged["timestamp_column"] == "_loaded_at"
        assert prov["max_hours"] == "policy"
        assert prov["timestamp_column"] == "config"

    def test_override_wins_over_policy(self):
        merged, prov = merge_policy_config(
            monitor_type="FRESHNESS",
            config={"max_hours": 6, "timestamp_column": "_loaded_at"},
            policy_config={"max_hours": 2, "warning_hours": 1},
            policy_overrides=["max_hours"],
        )
        assert merged["max_hours"] == 6
        assert merged["warning_hours"] == 1
        assert prov["max_hours"] == "override"
        assert prov["warning_hours"] == "policy"

    def test_no_policy_config_uses_config_as_is(self):
        merged, prov = merge_policy_config(
            monitor_type="FRESHNESS",
            config={"max_hours": 6},
            policy_config=None,
            policy_overrides=[],
        )
        assert merged["max_hours"] == 6
        assert prov["max_hours"] == "config"

    def test_unknown_monitor_type_uses_config(self):
        merged, prov = merge_policy_config(
            monitor_type="CUSTOM_SQL",
            config={"sql": "SELECT 1"},
            policy_config={"max_hours": 2},
            policy_overrides=[],
        )
        assert merged["sql"] == "SELECT 1"
        assert "max_hours" not in merged

    def test_anomaly_sensitivity_conversion(self):
        merged, prov = merge_policy_config(
            monitor_type="OUTLIER_DETECTION",
            config={},
            policy_config={"anomaly_threshold": 0.95},
            policy_overrides=[],
        )
        # 0.95 sensitivity -> 3.0 z-score
        assert merged["anomaly_threshold"] == 3.0
        assert prov["anomaly_threshold"] == "policy"
```

- [ ] **Step 3: Write tests for `is_less_strict`**

```python
# append to scanner/monitors/tests/test_policy_config.py
from scanner.monitors.policy_config import is_less_strict


class TestIsLessStrict:
    def test_higher_max_hours_is_less_strict(self):
        assert is_less_strict("max_hours", 2, 6) is True

    def test_lower_max_hours_is_not_less_strict(self):
        assert is_less_strict("max_hours", 6, 2) is False

    def test_equal_values_not_less_strict(self):
        assert is_less_strict("max_hours", 2, 2) is False

    def test_lower_min_rows_is_less_strict(self):
        assert is_less_strict("min_rows", 100, 1) is True

    def test_higher_anomaly_threshold_is_less_strict(self):
        # Higher z-score = fewer alerts = less strict
        assert is_less_strict("anomaly_threshold", 3.0, 4.0) is True

    def test_strictness_enum_relaxed_vs_strict(self):
        assert is_less_strict("strictness", "strict", "warn") is True
        assert is_less_strict("strictness", "strict", "ignore") is True
        assert is_less_strict("strictness", "warn", "strict") is False

    def test_failure_tolerance_enum(self):
        assert is_less_strict("failure_tolerance", "strict", "normal") is True
        assert is_less_strict("failure_tolerance", "strict", "relaxed") is True
        assert is_less_strict("failure_tolerance", "relaxed", "strict") is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python3 -m pytest scanner/monitors/tests/test_policy_config.py -v`
Expected: FAIL (module does not exist)

- [ ] **Step 5: Implement `policy_config.py`**

```python
# scanner/monitors/policy_config.py
"""
Shared policy-to-monitor-config mapping, merge logic, and strictness comparison.

Used by:
  - Executor (runtime policy enforcement)
  - Recommender (recommendation-time config hints)
  - UI (policy violation detection via API)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def sensitivity_to_zscore(sensitivity: float) -> float:
    """Convert a 0-1 sensitivity scale to a z-score anomaly threshold.

    Higher sensitivity -> lower threshold -> more alerts.
    Maps: 0.99->2.0, 0.95->3.0, 0.90->3.5, 0.80->4.0, <=0.50->5.0
    """
    s = max(0.0, min(1.0, sensitivity))
    breakpoints = [
        (0.99, 2.0),
        (0.95, 3.0),
        (0.90, 3.5),
        (0.80, 4.0),
        (0.50, 5.0),
    ]
    if s >= breakpoints[0][0]:
        return breakpoints[0][1]
    if s <= breakpoints[-1][0]:
        return breakpoints[-1][1]
    for i in range(len(breakpoints) - 1):
        s_hi, z_hi = breakpoints[i]
        s_lo, z_lo = breakpoints[i + 1]
        if s_lo <= s <= s_hi:
            ratio = (s - s_lo) / (s_hi - s_lo)
            return z_lo + ratio * (z_hi - z_lo)
    return 3.0


# Maps monitor_type -> { policy_field: config_field }
# For fields where conversion is needed, value is (config_field, converter_func).
POLICY_TO_MONITOR_CONFIG: Dict[str, Dict[str, str | tuple]] = {
    "FRESHNESS": {
        "freshness_max_hours": "max_hours",
        "freshness_warning_hours": "warning_hours",
    },
    "VOLUME": {
        "volume_min_rows": "min_rows",
        "volume_max_rows": "max_rows",
        "volume_growth_threshold": "growth_rate_threshold",
    },
    "OUTLIER_DETECTION": {
        "anomaly_sensitivity": ("anomaly_threshold", sensitivity_to_zscore),
        "anomaly_lookback_days": "lookback_days",
    },
    "ANOMALY": {
        "anomaly_sensitivity": ("anomaly_threshold", sensitivity_to_zscore),
        "anomaly_lookback_days": "lookback_days",
    },
    "NULL_CHECK": {
        "quality_max_null_rate": "max_null_rate",
    },
    "UNIQUENESS_CHECK": {
        "quality_max_duplicate_rate": "max_duplicate_rate",
    },
    "SCHEMA_CHANGE": {
        "schema_strictness": "strictness",
    },
    "SYNC_LAG": {
        "sync_lag_tolerance_minutes": "max_lag_minutes",
    },
    "FAILED_SYNCS": {
        "failure_tolerance": "failure_tolerance",
    },
    "CONNECTOR_SCHEMA_DRIFT": {
        "schema_drift_strictness": "strictness",
    },
    "BI_FRESHNESS_PROXY": {
        "bi_freshness_hours": "max_stale_hours",
    },
    "BI_UPSTREAM_BREAK_RISK": {
        "upstream_break_strictness": "strictness",
    },
    "DAG_LAST_RUN": {
        "run_latency_minutes": "max_latency_minutes",
    },
    "DAG_SCHEDULE_LAG": {
        "schedule_lag_minutes": "max_schedule_lag_minutes",
    },
    "TASK_FAILURE_RATE": {
        "orch_failure_tolerance": "max_failure_pct",
    },
    "DBT_TEST_FAILURES": {
        "test_failure_tolerance": "failure_tolerance",
    },
    "DBT_MODEL_FRESHNESS": {
        "model_freshness_hours": "max_hours",
    },
    "DBT_SOURCE_FRESHNESS": {
        "model_freshness_hours": "max_hours",
    },
}

# Fields where higher value = less strict
_HIGHER_IS_LESS_STRICT = {
    "max_hours", "warning_hours", "max_null_rate", "max_duplicate_rate",
    "max_outlier_pct", "max_lag_minutes", "max_stale_hours",
    "max_latency_minutes", "max_schedule_lag_minutes", "growth_rate_threshold",
    "anomaly_threshold", "max_failure_pct",
}

# Fields where lower value = less strict
_LOWER_IS_LESS_STRICT = {"min_rows"}

# Enum orderings (strict -> relaxed)
_STRICTNESS_ORDER = {"strict": 0, "warn": 1, "ignore": 2}
_TOLERANCE_ORDER = {"strict": 0, "normal": 1, "relaxed": 2}

_ENUM_FIELDS = {
    "strictness": _STRICTNESS_ORDER,
    "failure_tolerance": _TOLERANCE_ORDER,
}


def merge_policy_config(
    monitor_type: str,
    config: Dict[str, Any],
    policy_config: Optional[Dict[str, Any]],
    policy_overrides: List[str],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Merge monitor config with policy config.

    Returns (merged_config, provenance) where provenance maps each key
    to "policy", "override", or "config".
    """
    mapping = POLICY_TO_MONITOR_CONFIG.get(monitor_type.upper(), {})
    merged = dict(config)
    provenance: Dict[str, str] = {k: "config" for k in config}

    if not policy_config or not mapping:
        return merged, provenance

    # Apply policy values for mapped fields (unless overridden)
    for policy_field, target in mapping.items():
        policy_val = policy_config.get(policy_field)
        if policy_val is None:
            # Also check config-field-name keys in policy_config
            # (Next.js may send already-mapped field names)
            if isinstance(target, tuple):
                config_field = target[0]
            else:
                config_field = target
            policy_val = policy_config.get(config_field)

        if policy_val is None:
            continue

        if isinstance(target, tuple):
            config_field, converter = target
            converted_val = converter(policy_val)
        else:
            config_field = target
            converted_val = policy_val

        if config_field in policy_overrides:
            # User override wins — keep config value
            provenance[config_field] = "override"
        else:
            merged[config_field] = converted_val
            provenance[config_field] = "policy"

    return merged, provenance


def is_less_strict(field: str, policy_value: Any, override_value: Any) -> bool:
    """Check if an override value is less strict than the policy value."""
    if policy_value is None or override_value is None:
        return False
    if policy_value == override_value:
        return False

    # Enum fields
    order = _ENUM_FIELDS.get(field)
    if order is not None:
        p_rank = order.get(str(policy_value).lower(), 99)
        o_rank = order.get(str(override_value).lower(), 99)
        return o_rank > p_rank

    # Numeric fields
    try:
        p = float(policy_value)
        o = float(override_value)
    except (ValueError, TypeError):
        return False

    if field in _HIGHER_IS_LESS_STRICT:
        return o > p
    if field in _LOWER_IS_LESS_STRICT:
        return o < p

    return False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest scanner/monitors/tests/test_policy_config.py -v`
Expected: All PASS

- [ ] **Step 7: Update recommender to import from shared module**

In `scanner/monitors/recommender.py`:
- Replace the `_sensitivity_to_zscore` function (lines 136-163) with an import:
  ```python
  from scanner.monitors.policy_config import sensitivity_to_zscore as _sensitivity_to_zscore
  ```
- Delete the function body (lines 136-163)

- [ ] **Step 8: Run existing recommender tests**

Run: `python3 -m pytest scanner/monitors/tests/test_recommender.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add scanner/monitors/policy_config.py scanner/monitors/tests/test_policy_config.py scanner/monitors/recommender.py
git commit -m "feat: add shared policy-to-monitor-config mapping module"
```

---

### Task 2: Prisma schema + migration

**Files:**
- Modify: `prisma/schema.prisma:3036` (add policyOverrides field to Monitor)

- [ ] **Step 1: Add `policyOverrides` field to Monitor model**

In `prisma/schema.prisma`, after line 3036 (after `externalId String?`), add:

```prisma
  // Policy override tracking
  policyOverrides String[]  // Config field keys overridden by user (e.g. ["max_hours"])
```

- [ ] **Step 2: Generate Prisma migration**

Run: `npx prisma migrate dev --name add_monitor_policy_overrides`
Expected: Migration created successfully

- [ ] **Step 3: Verify Prisma client generation**

Run: `npx prisma generate`
Expected: Generated Prisma Client

- [ ] **Step 4: Commit**

```bash
git add prisma/schema.prisma prisma/migrations/
git commit -m "feat: add policyOverrides field to Monitor model"
```

---

### Task 3: Python executor policy-aware merge

**Files:**
- Modify: `scanner/api/routers/schedule.py:27-41` (add fields to ExecuteTaskRequest)
- Modify: `scanner/scheduler/executor.py:286-413` (add merge logic)

- [ ] **Step 1: Add policy fields to `ExecuteTaskRequest`**

In `scanner/api/routers/schedule.py`, add after line 41 (after `integration_config`):

```python
    policy_config: Optional[Dict[str, Any]] = Field(
        None, description="Resolved policy thresholds for the target asset"
    )
    policy_overrides: Optional[List[str]] = Field(
        None, description="Config field keys explicitly overridden by user"
    )
```

Also add `List` to the typing imports at the top.

- [ ] **Step 2: Pass policy fields through to task dict**

In `scanner/api/routers/schedule.py`, in the `execute_task` function, add to the `task_dict` (after line 98):

```python
        "policyConfig": request.policy_config,
        "policyOverrides": request.policy_overrides,
```

- [ ] **Step 3: Add policy merge to `_execute_structured`**

In `scanner/scheduler/executor.py`, after the baseline injection block (after line 410, before line 412 `# Create monitor instance`), add:

```python
        # --- Policy-aware config merge ---
        policy_config = task.get("policyConfig")
        policy_overrides = task.get("policyOverrides") or []
        if policy_config:
            from scanner.monitors.policy_config import merge_policy_config
            config, provenance = merge_policy_config(
                monitor_type=monitor_type,
                config=config,
                policy_config=policy_config,
                policy_overrides=policy_overrides,
            )
            logger.info(
                "[Executor] Policy config merged",
                provenance=provenance,
                override_count=len(policy_overrides),
            )
```

- [ ] **Step 4: Run existing executor-related tests**

Run: `python3 -m pytest scanner/monitors/tests/ scanner/tests/test_presets.py -x -q`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scanner/api/routers/schedule.py scanner/scheduler/executor.py
git commit -m "feat: add policy-aware config merge to executor"
```

---

### Task 4: Next.js task run route — inject policy resolution

**Files:**
- Modify: `app/api/schedule/tasks/[taskId]/run/route.ts:306-334` (add policy resolution before fetch)

- [ ] **Step 1: Add policy resolution before the executor fetch call**

In `app/api/schedule/tasks/[taskId]/run/route.ts`, after the baseline injection block (after line 315 `}`) and before the `// Call the Python backend to execute` comment (line 317), add:

```typescript
    // --- Resolve policy for runtime enforcement ---
    let policyConfig: Record<string, any> | null = null;
    const policyOverrides: string[] = (task.policyOverrides as string[]) || [];

    if (task.targetFqn && !isInfra && !isTool) {
      try {
        const policyRes = await fetch(`${baseUrl}/api/schedule/policies/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', cookie },
          body: JSON.stringify({
            nodes: [{ fqn: task.targetFqn, domain: 'warehouse', criticality: 'medium' }],
            stackId: undefined,
          }),
        });
        if (policyRes.ok) {
          const policyData = await policyRes.json();
          const resolved = policyData.policies?.[task.targetFqn];
          if (resolved) {
            // Flatten policy sections into a single config dict
            policyConfig = {
              ...resolved.freshness,
              ...resolved.schema,
              ...resolved.volume,
              ...resolved.anomaly,
              ...resolved.quality,
              ...resolved.ingestion,
              ...resolved.bi,
              ...resolved.orchestration,
              ...resolved.transform,
            };
          }
        }
      } catch (err) {
        console.warn('[Schedule] Policy resolution failed (non-fatal):', err);
      }
    }
```

Note: `baseUrl` and `cookie` need to be extracted from the request. Add near the top of the POST handler (after line 67):

```typescript
    const baseUrl = request.nextUrl?.origin || process.env.NEXTAUTH_URL || 'http://localhost:3000';
    const cookie = request.headers.get('cookie') || '';
```

Wait — this file receives a `NextRequest` but it's defined as `request: NextRequest`. Check if it has access to `request.nextUrl`. If not, use `process.env.NEXTAUTH_URL`.

- [ ] **Step 2: Add policy fields to the Python executor request body**

In the same file, in the `JSON.stringify` body (around line 323-334), add after `integration_config: integrationConfig`:

```typescript
        policy_config: policyConfig,
        policy_overrides: policyOverrides,
```

Remove the "Wait --" note from the plan — `NextRequest` in Next.js 15 does have `nextUrl`, so the code is correct as written.

- [ ] **Step 3: Verify the server starts without errors**

Run: `npx next build --no-lint` (or just verify TypeScript compiles)
Expected: No type errors

- [ ] **Step 4: Commit**

```bash
git add app/api/schedule/tasks/\\[taskId\\]/run/route.ts
git commit -m "feat: resolve policy at runtime before executor call"
```

---

### Task 5: Monitor update API endpoint

**Files:**
- Create: `app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts`

- [ ] **Step 1: Create the directory**

Run: `mkdir -p app/api/schedule/watches/\\[watchId\\]/monitors/\\[monitorId\\]`

- [ ] **Step 2: Write the PUT endpoint**

```typescript
// app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// PUT /api/schedule/watches/[watchId]/monitors/[monitorId]
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string; monitorId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { watchId, monitorId } = await params;

    // Verify monitor belongs to this watch and org
    const monitor = await prisma.monitor.findFirst({
      where: {
        id: monitorId,
        monitorGroupId: watchId,
        organizationId,
      },
    });

    if (!monitor) {
      return NextResponse.json(
        { error: 'Monitor not found in this watch' },
        { status: 404 },
      );
    }

    const body = await request.json();
    const { config, policyOverrides } = body;

    const updateData: Record<string, any> = {};

    if (config !== undefined) {
      updateData.config = config;
    }

    if (policyOverrides !== undefined) {
      // Validate that overrides are strings
      if (
        !Array.isArray(policyOverrides) ||
        !policyOverrides.every((k: any) => typeof k === 'string')
      ) {
        return NextResponse.json(
          { error: 'policyOverrides must be an array of strings' },
          { status: 400 },
        );
      }
      updateData.policyOverrides = policyOverrides;
    }

    const updated = await prisma.monitor.update({
      where: { id: monitorId },
      data: updateData,
    });

    return NextResponse.json({ monitor: updated });
  } catch (error: any) {
    console.error('[Monitors] Update error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/watches/\\[watchId\\]/monitors/\\[monitorId\\]/route.ts
git commit -m "feat: add PUT endpoint for individual monitor config updates"
```

---

### Task 6: Extend watch GET to include resolved policies

**Files:**
- Modify: `app/api/schedule/watches/[watchId]/route.ts:7-100` (extend GET response)

- [ ] **Step 1: Add policy resolution to the GET handler**

In `app/api/schedule/watches/[watchId]/route.ts`, the existing GET handler uses variable `group` (line 21) for the Prisma query result. The monitors mapping is at lines 39-63 (the `const monitors = group.monitors.map(...)` block).

First, add `policyOverrides` to the monitor mapping. In the existing `monitors` mapping (line 39-63), add after `config: m.config,` (line 50):

```typescript
        policyOverrides: (m as any).policyOverrides || [],
```

Then, after the `const monitors = group.monitors.map(...)` block (after line 63) and before the `return NextResponse.json(...)` (line 65), add:

```typescript
    // Resolve policies for all monitor targets (bulk, deduplicated)
    const uniqueFqns = [
      ...new Set(
        group.monitors
          .map((m) => m.targetFqn)
          .filter(Boolean) as string[]
      ),
    ];

    let resolvedPolicies: Record<string, any> = {};
    if (uniqueFqns.length > 0) {
      try {
        const baseUrl = request.nextUrl?.origin || process.env.NEXTAUTH_URL || 'http://localhost:3000';
        const cookie = request.headers.get('cookie') || '';
        const policyRes = await fetch(`${baseUrl}/api/schedule/policies/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', cookie },
          body: JSON.stringify({
            nodes: uniqueFqns.map((fqn) => ({
              fqn,
              domain: 'warehouse',
              criticality: 'medium',
            })),
          }),
        });
        if (policyRes.ok) {
          const data = await policyRes.json();
          resolvedPolicies = data.policies || {};
        }
      } catch (err) {
        console.warn('[Watch] Policy resolution failed (non-fatal):', err);
      }
    }

    // Attach resolved policy to each monitor in the already-mapped array
    const monitorsWithPolicy = monitors.map((m) => ({
      ...m,
      resolvedPolicy: m.targetFqn ? resolvedPolicies[m.targetFqn] || null : null,
    }));
```

Then update the return statement (line 93) to use `monitorsWithPolicy` instead of `monitors`:

```typescript
        monitors: monitorsWithPolicy,
```

And update the counts to use `monitorsWithPolicy`:

```typescript
        monitorCount: monitorsWithPolicy.length,
        passCount: monitorsWithPolicy.filter((m) => m.lastStatus === 'PASS').length,
        failCount: monitorsWithPolicy.filter((m) => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR').length,
        warnCount: monitorsWithPolicy.filter((m) => m.lastStatus === 'WARN').length,
```

- [ ] **Step 2: Ensure the GET handler receives the `request` parameter**

The GET handler signature must include `request: NextRequest` to access `request.nextUrl` and `request.headers`. Verify or update the function signature.

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/watches/\\[watchId\\]/route.ts
git commit -m "feat: extend watch GET to include resolved policies per monitor"
```

---

### Task 7: PolicyFieldBadge component

**Files:**
- Create: `components/schedule/PolicyFieldBadge.tsx`

- [ ] **Step 1: Write the component**

```tsx
// components/schedule/PolicyFieldBadge.tsx
'use client';

interface PolicyFieldBadgeProps {
  fieldKey: string;
  currentValue: any;
  policyValue: any;
  profileName?: string;
  isOverridden: boolean;
  isLessStrict: boolean;
  onReset?: () => void;
}

// Strictness comparison for enum fields (client-side mirror of Python logic)
const STRICTNESS_ORDER: Record<string, number> = { strict: 0, warn: 1, ignore: 2 };
const TOLERANCE_ORDER: Record<string, number> = { strict: 0, normal: 1, relaxed: 2 };

function formatValue(val: any): string {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'number') return val.toLocaleString();
  return String(val);
}

export default function PolicyFieldBadge({
  fieldKey,
  currentValue,
  policyValue,
  profileName,
  isOverridden,
  isLessStrict,
  onReset,
}: PolicyFieldBadgeProps) {
  if (policyValue === null || policyValue === undefined) return null;

  if (!isOverridden) {
    // Following policy
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
        style={{
          background: 'rgba(139, 92, 246, 0.15)',
          color: 'var(--text-secondary)',
        }}
        title={`Set by policy: ${profileName || 'default'}`}
      >
        Policy{profileName ? `: ${profileName}` : ''}
      </span>
    );
  }

  if (isLessStrict) {
    // Override is less strict than policy — violation warning
    return (
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
          style={{
            background: 'rgba(239, 68, 68, 0.15)',
            color: 'rgb(239, 68, 68)',
          }}
          title={`Policy requires ${formatValue(policyValue)}, current: ${formatValue(currentValue)}`}
        >
          Policy violation: {formatValue(policyValue)}
        </span>
        {onReset && (
          <button
            onClick={onReset}
            className="text-[10px] text-[var(--text-faint)] hover:text-[var(--text-secondary)] underline"
          >
            Reset
          </button>
        )}
      </span>
    );
  }

  // Override but equal or stricter than policy
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
        style={{
          background: 'rgba(245, 158, 11, 0.15)',
          color: 'rgb(245, 158, 11)',
        }}
        title={`Policy: ${formatValue(policyValue)}, Your value: ${formatValue(currentValue)}`}
      >
        Override (policy: {formatValue(policyValue)})
      </span>
      {onReset && (
        <button
          onClick={onReset}
          className="text-[10px] text-[var(--text-faint)] hover:text-[var(--text-secondary)] underline"
        >
          Reset
        </button>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/schedule/PolicyFieldBadge.tsx
git commit -m "feat: add PolicyFieldBadge component for inline policy status"
```

---

### Task 8: MonitorEditPanel component

**Files:**
- Create: `components/schedule/MonitorEditPanel.tsx`

- [ ] **Step 1: Write the component**

This component renders all config fields for a monitor type with policy badges. It reuses the field rendering pattern from `MonitorConfigForm.tsx` (iterating `config_schema` from the monitor catalog).

```tsx
// components/schedule/MonitorEditPanel.tsx
'use client';

import { useState, useCallback } from 'react';
import PolicyFieldBadge from './PolicyFieldBadge';
import { MONITOR_CATALOG, type MonitorDefinition, type ConfigField } from '@/types/monitor-catalog';

// Policy field mapping (mirrors Python POLICY_TO_MONITOR_CONFIG)
const POLICY_FIELD_MAP: Record<string, Record<string, string>> = {
  FRESHNESS: { max_hours: 'freshness_max_hours', warning_hours: 'freshness_warning_hours' },
  VOLUME: { min_rows: 'volume_min_rows', max_rows: 'volume_max_rows', growth_rate_threshold: 'volume_growth_threshold' },
  OUTLIER_DETECTION: { anomaly_threshold: 'anomaly_sensitivity', lookback_days: 'anomaly_lookback_days' },
  ANOMALY: { anomaly_threshold: 'anomaly_sensitivity', lookback_days: 'anomaly_lookback_days' },
  NULL_CHECK: { max_null_rate: 'quality_max_null_rate' },
  UNIQUENESS_CHECK: { max_duplicate_rate: 'quality_max_duplicate_rate' },
  SCHEMA_CHANGE: { strictness: 'schema_strictness' },
  SYNC_LAG: { max_lag_minutes: 'sync_lag_tolerance_minutes' },
  FAILED_SYNCS: { failure_tolerance: 'failure_tolerance' },
  CONNECTOR_SCHEMA_DRIFT: { strictness: 'schema_drift_strictness' },
  BI_FRESHNESS_PROXY: { max_stale_hours: 'bi_freshness_hours' },
  BI_UPSTREAM_BREAK_RISK: { strictness: 'upstream_break_strictness' },
  DAG_LAST_RUN: { max_latency_minutes: 'run_latency_minutes' },
  DAG_SCHEDULE_LAG: { max_schedule_lag_minutes: 'schedule_lag_minutes' },
  TASK_FAILURE_RATE: { max_failure_pct: 'orch_failure_tolerance' },
  DBT_TEST_FAILURES: { failure_tolerance: 'test_failure_tolerance' },
  DBT_MODEL_FRESHNESS: { max_hours: 'model_freshness_hours' },
  DBT_SOURCE_FRESHNESS: { max_hours: 'model_freshness_hours' },
};

// Sensitivity -> z-score conversion (mirrors Python sensitivity_to_zscore)
function sensitivityToZscore(s: number): number {
  s = Math.max(0, Math.min(1, s));
  const bp: [number, number][] = [[0.99,2],[0.95,3],[0.90,3.5],[0.80,4],[0.50,5]];
  if (s >= bp[0][0]) return bp[0][1];
  if (s <= bp[bp.length-1][0]) return bp[bp.length-1][1];
  for (let i = 0; i < bp.length - 1; i++) {
    const [sHi, zHi] = bp[i], [sLo, zLo] = bp[i+1];
    if (s >= sLo && s <= sHi) return zLo + ((s - sLo) / (sHi - sLo)) * (zHi - zLo);
  }
  return 3.0;
}

// Higher value = less strict
const HIGHER_LESS_STRICT = new Set([
  'max_hours', 'warning_hours', 'max_null_rate', 'max_duplicate_rate',
  'max_outlier_pct', 'max_lag_minutes', 'max_stale_hours',
  'max_latency_minutes', 'max_schedule_lag_minutes', 'growth_rate_threshold',
  'anomaly_threshold', 'max_failure_pct',
]);
const LOWER_LESS_STRICT = new Set(['min_rows']);
const STRICTNESS_ORDER: Record<string, number> = { strict: 0, warn: 1, ignore: 2 };
const TOLERANCE_ORDER: Record<string, number> = { strict: 0, normal: 1, relaxed: 2 };

function isLessStrictClient(field: string, policyVal: any, overrideVal: any): boolean {
  if (policyVal == null || overrideVal == null || policyVal === overrideVal) return false;
  const order = field === 'strictness' ? STRICTNESS_ORDER :
                field === 'failure_tolerance' ? TOLERANCE_ORDER : null;
  if (order) {
    return (order[String(overrideVal).toLowerCase()] ?? 99) > (order[String(policyVal).toLowerCase()] ?? 99);
  }
  try {
    const p = Number(policyVal), o = Number(overrideVal);
    if (HIGHER_LESS_STRICT.has(field)) return o > p;
    if (LOWER_LESS_STRICT.has(field)) return o < p;
  } catch { /* ignore */ }
  return false;
}

interface MonitorEditPanelProps {
  monitor: {
    id: string;
    name: string;
    monitorType: string;
    targetFqn?: string;
    config: Record<string, any>;
    policyOverrides: string[];
  };
  resolvedPolicy: {
    profileName?: string;
    status?: string;
    [key: string]: any;
  } | null;
  onSave: (monitorId: string, config: Record<string, any>, policyOverrides: string[]) => Promise<void>;
}

export default function MonitorEditPanel({ monitor, resolvedPolicy, onSave }: MonitorEditPanelProps) {
  const [config, setConfig] = useState<Record<string, any>>({ ...monitor.config });
  const [overrides, setOverrides] = useState<string[]>([...monitor.policyOverrides]);
  const [saving, setSaving] = useState(false);

  const monitorDef = MONITOR_CATALOG.find((d: MonitorDefinition) => d.key === monitor.monitorType);
  const policyMap = POLICY_FIELD_MAP[monitor.monitorType] || {};

  // Get the policy value for a config field (converted to config-field space)
  const getPolicyValue = useCallback((fieldKey: string): any => {
    if (!resolvedPolicy) return undefined;
    const policyField = policyMap[fieldKey];
    if (!policyField) return undefined;
    // Search all policy sections for the field
    for (const section of ['freshness', 'schema', 'volume', 'anomaly', 'quality', 'ingestion', 'bi', 'orchestration', 'transform']) {
      const sectionData = resolvedPolicy[section];
      if (sectionData && policyField in sectionData) {
        let val = sectionData[policyField];
        // Convert anomaly_sensitivity (0-1) to z-score for comparison
        if (policyField === 'anomaly_sensitivity' && typeof val === 'number') {
          val = sensitivityToZscore(val);
        }
        return val;
      }
    }
    return undefined;
  }, [resolvedPolicy, policyMap]);

  const handleFieldChange = (key: string, value: any) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    // Track override if value differs from policy
    const policyVal = getPolicyValue(key);
    if (policyVal !== undefined && value !== policyVal) {
      setOverrides((prev) => prev.includes(key) ? prev : [...prev, key]);
    } else if (policyVal !== undefined && value === policyVal) {
      setOverrides((prev) => prev.filter((k) => k !== key));
    }
  };

  const handleReset = (key: string) => {
    const policyVal = getPolicyValue(key);
    if (policyVal !== undefined) {
      setConfig((prev) => ({ ...prev, [key]: policyVal }));
      setOverrides((prev) => prev.filter((k) => k !== key));
    }
  };

  const handleResetAll = () => {
    const newConfig = { ...config };
    for (const key of overrides) {
      const policyVal = getPolicyValue(key);
      if (policyVal !== undefined) {
        newConfig[key] = policyVal;
      }
    }
    setConfig(newConfig);
    setOverrides([]);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(monitor.id, config, overrides);
    } finally {
      setSaving(false);
    }
  };

  const renderField = (field: ConfigField) => {
    const value = config[field.key] ?? field.default_value ?? '';
    const policyVal = getPolicyValue(field.key);
    const isOverridden = overrides.includes(field.key);
    const hasPolicyMapping = policyVal !== undefined;

    return (
      <div key={field.key} className="space-y-1">
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            {field.label}
          </label>
          {hasPolicyMapping && (
            <PolicyFieldBadge
              fieldKey={field.key}
              currentValue={value}
              policyValue={policyVal}
              profileName={resolvedPolicy?.profileName}
              isOverridden={isOverridden}
              isLessStrict={isOverridden && isLessStrictClient(field.key, policyVal, value)}
              onReset={isOverridden ? () => handleReset(field.key) : undefined}
            />
          )}
        </div>
        {field.type === 'select' && field.options ? (
          <select
            value={value}
            onChange={(e) => handleFieldChange(field.key, e.target.value)}
            className="w-full px-2 py-1.5 text-xs rounded border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--text-primary)]"
          >
            {field.options.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        ) : field.type === 'checkbox' ? (
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => handleFieldChange(field.key, e.target.checked)}
          />
        ) : field.type === 'number' ? (
          <input
            type="number"
            value={value}
            onChange={(e) => handleFieldChange(field.key, parseFloat(e.target.value) || 0)}
            placeholder={field.placeholder}
            className="w-full px-2 py-1.5 text-xs rounded border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--text-primary)]"
          />
        ) : (
          <input
            type="text"
            value={value}
            onChange={(e) => handleFieldChange(field.key, e.target.value)}
            placeholder={field.placeholder}
            className="w-full px-2 py-1.5 text-xs rounded border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--text-primary)]"
          />
        )}
        {field.help_text && (
          <p className="text-[10px] text-[var(--text-faint)]">{field.help_text}</p>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4 p-4 rounded-lg border border-[var(--border-primary)] bg-[var(--bg-secondary)]">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium text-[var(--text-primary)]">{monitor.name}</h4>
          <p className="text-[10px] text-[var(--text-faint)]">{monitor.targetFqn}</p>
        </div>
        {overrides.length > 0 && (
          <button
            onClick={handleResetAll}
            className="text-[10px] text-[var(--text-faint)] hover:text-[var(--text-secondary)] underline"
          >
            Reset all to policy
          </button>
        )}
      </div>

      <div className="space-y-3">
        {monitorDef?.config_schema?.map((field) => renderField(field))}
      </div>

      <div className="flex justify-end pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-3 py-1.5 text-xs font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/schedule/MonitorEditPanel.tsx
git commit -m "feat: add MonitorEditPanel with policy badge integration"
```

---

### Task 9: WatchEditModal component

**Files:**
- Create: `components/schedule/WatchEditModal.tsx`

- [ ] **Step 1: Write the component**

```tsx
// components/schedule/WatchEditModal.tsx
'use client';

import { useState } from 'react';
import { X } from 'lucide-react';

interface WatchEditModalProps {
  watch: {
    id: string;
    name: string;
    schedule?: string;
    timezone?: string;
    alertChannels: string[];
    alertOnStatus: string[];
    enabled: boolean;
  };
  onSave: (data: {
    name: string;
    schedule: string;
    timezone: string;
    alertChannels: string[];
    alertOnStatus: string[];
    enabled: boolean;
  }) => Promise<void>;
  onClose: () => void;
}

const STATUS_OPTIONS = ['FAIL', 'WARN', 'ERROR'];

export default function WatchEditModal({ watch, onSave, onClose }: WatchEditModalProps) {
  const [name, setName] = useState(watch.name);
  const [schedule, setSchedule] = useState(watch.schedule || '0 */6 * * *');
  const [timezone, setTimezone] = useState(watch.timezone || 'UTC');
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(watch.alertOnStatus || ['FAIL']);
  const [enabled, setEnabled] = useState(watch.enabled);
  const [saving, setSaving] = useState(false);

  const toggleStatus = (status: string) => {
    setAlertOnStatus((prev) =>
      prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status]
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        name,
        schedule,
        timezone,
        alertChannels: watch.alertChannels,
        alertOnStatus,
        enabled,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-xl border border-[var(--border-primary)] bg-[var(--bg-primary)] shadow-xl">
        <div className="flex items-center justify-between p-4 border-b border-[var(--border-primary)]">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Edit Watch</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--bg-secondary)]">
            <X size={14} className="text-[var(--text-faint)]" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <label className="text-xs font-medium text-[var(--text-secondary)]">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full px-2 py-1.5 text-xs rounded border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--text-primary)]"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-secondary)]">Schedule (cron)</label>
            <input
              type="text"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="0 */6 * * *"
              className="mt-1 w-full px-2 py-1.5 text-xs rounded border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--text-primary)] font-mono"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-secondary)]">Timezone</label>
            <input
              type="text"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="mt-1 w-full px-2 py-1.5 text-xs rounded border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--text-primary)]"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-secondary)]">Alert on status</label>
            <div className="mt-1 flex gap-2">
              {STATUS_OPTIONS.map((status) => (
                <button
                  key={status}
                  onClick={() => toggleStatus(status)}
                  className={`px-2 py-1 text-[10px] font-medium rounded border ${
                    alertOnStatus.includes(status)
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                      : 'border-[var(--border-primary)] text-[var(--text-faint)]'
                  }`}
                >
                  {status}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-[var(--text-secondary)]">Enabled</label>
            <button
              onClick={() => setEnabled(!enabled)}
              className={`relative w-8 h-4 rounded-full transition-colors ${
                enabled ? 'bg-[var(--accent)]' : 'bg-[var(--border-primary)]'
              }`}
            >
              <span
                className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
                  enabled ? 'translate-x-4' : 'translate-x-0.5'
                }`}
              />
            </button>
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-[var(--border-primary)]">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-lg border border-[var(--border-primary)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/schedule/WatchEditModal.tsx
git commit -m "feat: add WatchEditModal for group-level settings editing"
```

---

### Task 10: Add gear icon to WatchCard + wire up modals

**Files:**
- Modify: `components/schedule/WatchCard.tsx:116-140` (add gear icon)

- [ ] **Step 1: Add gear icon to WatchCard actions**

In `components/schedule/WatchCard.tsx`, import `Settings` from lucide-react and add a gear button in the actions area (after the run button, before the toggle). Also import `WatchEditModal` and add state for showing it.

Add to imports:
```typescript
import { Settings } from 'lucide-react';
import WatchEditModal from './WatchEditModal';
```

Add state:
```typescript
const [showEditModal, setShowEditModal] = useState(false);
```

Add the gear button after the run button (after line 127):
```tsx
<button
  onClick={(e) => { e.stopPropagation(); setShowEditModal(true); }}
  className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] opacity-0 group-hover:opacity-100 transition-all"
  title="Edit watch settings"
>
  <Settings size={14} />
</button>
```

Add the modal at the end of the component (before closing `</div>`):
```tsx
{showEditModal && (
  <WatchEditModal
    watch={watch}
    onSave={async (data) => {
      await fetch(`/api/schedule/watches/${watch.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      // Trigger refresh
      if (onRefresh) onRefresh();
    }}
    onClose={() => setShowEditModal(false)}
  />
)}
```

Note: Check the WatchCard props interface — if `onRefresh` is not already a prop, add it or use an existing refresh mechanism.

- [ ] **Step 2: Commit**

```bash
git add components/schedule/WatchCard.tsx
git commit -m "feat: add gear icon to WatchCard for group-level editing"
```

---

### Task 11: Wire MonitorEditPanel into watch detail view

**Files:**
- Modify: `components/schedule/WatchDetailPanel.tsx`

The `WatchDetailPanel` component (at `components/schedule/WatchDetailPanel.tsx`) receives `detailMonitors: any[]` as a prop. It renders the list of monitors in a watch group. The `detailMonitors` array comes from the parent component which calls `GET /api/schedule/watches/[watchId]` — now enriched with `resolvedPolicy` and `policyOverrides` per monitor (from Task 6).

The component already has `expandedMonitorId` state (line 72) and renders monitors in a list. We add a toggle between "run history" view and "edit config" view when expanded.

- [ ] **Step 1: Add MonitorEditPanel import and edit state**

At the top of `WatchDetailPanel.tsx`, add:

```typescript
import MonitorEditPanel from './MonitorEditPanel';
```

Add state for edit mode (after line 73):

```typescript
const [editingMonitorId, setEditingMonitorId] = useState<string | null>(null);
```

- [ ] **Step 2: Add edit button and MonitorEditPanel to each monitor row**

In the monitor list section, find where each monitor is rendered (the `detailMonitors.map(...)` block). Add an "Edit" button next to each monitor's existing controls, and conditionally render `MonitorEditPanel` when `editingMonitorId` matches:

```tsx
{/* Add edit button in the monitor row actions */}
<button
  onClick={() => setEditingMonitorId(
    editingMonitorId === monitor.id ? null : monitor.id
  )}
  className="text-[10px] text-[var(--text-faint)] hover:text-[var(--text-secondary)] underline"
>
  {editingMonitorId === monitor.id ? 'Close' : 'Edit'}
</button>

{/* Render edit panel when this monitor is being edited */}
{editingMonitorId === monitor.id && (
  <MonitorEditPanel
    monitor={{
      id: monitor.id,
      name: monitor.name,
      monitorType: monitor.monitorType || '',
      targetFqn: monitor.targetFqn,
      config: monitor.config || {},
      policyOverrides: monitor.policyOverrides || [],
    }}
    resolvedPolicy={monitor.resolvedPolicy || null}
    onSave={async (monitorId, config, policyOverrides) => {
      const watchId = watch.id;
      await fetch(`/api/schedule/watches/${watchId}/monitors/${monitorId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, policyOverrides }),
      });
      setEditingMonitorId(null);
      // Trigger parent refresh (call onBack + re-select, or add an onRefresh prop)
    }}
  />
)}
```

- [ ] **Step 3: Commit**

```bash
git add components/schedule/WatchDetailPanel.tsx
git commit -m "feat: wire MonitorEditPanel into watch detail view"
```

---

### Task 12: End-to-end verification

- [ ] **Step 1: Run all Python tests**

Run: `python3 -m pytest scanner/monitors/tests/ scanner/tests/test_presets.py scanner/tests/test_recommender_policy.py scanner/tests/test_policy_resolver.py -x -q`
Expected: All PASS

- [ ] **Step 2: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Manual smoke test**

1. Start the dev server (`npm run dev` + Python backend)
2. Navigate to a watch with monitors
3. Click the gear icon → verify WatchEditModal opens with correct values
4. Click into a monitor → verify MonitorEditPanel shows config fields with policy badges
5. Edit a threshold → verify "Override" badge appears
6. Save → verify the change persists on reload
7. Run the monitor → verify logs show `[Executor] Policy config merged` with correct provenance

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete monitor edit with runtime policy enforcement"
```
