# Monitor Edit & Runtime Policy Enforcement

## Problem

Monitor groups (watches) have no edit capability for individual monitor configs after creation. Policies set thresholds at recommendation time but are never checked again at execution time. Users cannot adjust monitor behavior without recreating watches, and there is no visibility into whether a monitor follows its asset's policy or has drifted.

## Design Decisions

- **Runtime policy enforcement**: The executor resolves the live policy at run time and uses those thresholds. Policy changes propagate automatically to non-overridden monitors.
- **Per-monitor overrides**: Users can override any config field per monitor. Overrides are tracked explicitly. The policy itself is never modified from the monitor editor.
- **Override persistence**: Overrides stick when the policy changes. If an override is less strict than the updated policy, a warning badge is shown.
- **Resolution split**: Next.js resolves the policy (has Prisma access), sends both `policy_config` and `config` to Python. Python merges and reports provenance.
- **Full config editing**: All config fields are editable, with policy-relevant fields showing inline policy status badges.

## Data Model

### Monitor model (Prisma)

Add one field:

```prisma
policyOverrides  String[]  // ["max_hours", "anomaly_threshold"]
```

A list of config field keys that the user has explicitly overridden. Empty array means the monitor fully follows its asset's policy.

When a user edits a field:
- If the new value differs from the resolved policy value -> add the key to `policyOverrides`
- If the user resets it back to the policy value -> remove the key

Override values are stored in the existing `Monitor.config` JSON field. `policyOverrides` only tracks *which* fields are user-controlled vs policy-controlled.

No new models. PolicyProfile and PolicyAssignment are untouched.

Requires a Prisma migration (`prisma migrate dev`). This is a non-destructive additive change (nullable field with default empty array).

## Runtime Enforcement

### Execution flow

In `/api/schedule/tasks/[taskId]/run/route.ts`, after resolving integration config:

1. If `targetFqn` is null (prompt-mode or CUSTOM_SQL monitors), skip policy resolution and use `config` as-is.
2. Otherwise, look up the monitor's `targetFqn` -> resolve the effective policy via `/api/schedule/policies/resolve`
3. Map policy fields to monitor config fields using `POLICY_TO_MONITOR_CONFIG` (see below)
4. Send to Python executor:
   ```json
   {
     "config": { "max_hours": 6 },
     "policy_config": { "max_hours": 2, "warning_hours": 1 },
     "policy_overrides": ["max_hours"]
   }
   ```
5. Python merges: for each threshold field, if in `policy_overrides` -> use `config` value, otherwise -> use `policy_config` value. Non-policy fields (timestamp_column, lookback_days, etc.) always come from `config`.

The watch-level run route (`/api/schedule/watches/[watchId]/run`) and the plan-level run route (`/api/schedule/plans/[planId]/run`) both delegate to the per-task run route, so policy resolution happens automatically for all execution paths.

### Policy-to-monitor-config mapping

New file: `scanner/monitors/policy_config.py`

Maps `(monitor_type, policy_field)` -> `config_field`:

| Monitor Type | Policy Field | Config Field |
|---|---|---|
| FRESHNESS | `freshness_max_hours` | `max_hours` |
| FRESHNESS | `freshness_warning_hours` | `warning_hours` |
| VOLUME | `volume_min_rows` | `min_rows` |
| VOLUME | `volume_max_rows` | `max_rows` |
| VOLUME | `volume_growth_threshold` | `growth_rate_threshold` |
| OUTLIER_DETECTION | `anomaly_sensitivity` | `anomaly_threshold` (via `sensitivity_to_zscore()`) |
| OUTLIER_DETECTION | `anomaly_lookback_days` | `lookback_days` |
| NULL_CHECK | `quality_max_null_rate` | `max_null_rate` |
| UNIQUENESS_CHECK | `quality_max_duplicate_rate` | `max_duplicate_rate` |
| SCHEMA_CHANGE | `schema_strictness` | `strictness` |
| SYNC_LAG | `sync_lag_tolerance_minutes` | `max_lag_minutes` |
| FAILED_SYNCS | `failure_tolerance` | `failure_tolerance` |
| CONNECTOR_SCHEMA_DRIFT | `schema_drift_strictness` | `strictness` |
| BI_FRESHNESS_PROXY | `bi_freshness_hours` | `max_stale_hours` |
| BI_UPSTREAM_BREAK_RISK | `upstream_break_strictness` | `strictness` |
| DAG_LAST_RUN | `run_latency_minutes` | `max_latency_minutes` |
| DAG_SCHEDULE_LAG | `schedule_lag_minutes` | `max_schedule_lag_minutes` |
| TASK_FAILURE_RATE | `orch_failure_tolerance` | `max_failure_pct` |
| DBT_TEST_FAILURES | `test_failure_tolerance` | `failure_tolerance` |
| DBT_MODEL_FRESHNESS | `model_freshness_hours` | `max_hours` |
| DBT_SOURCE_FRESHNESS | `model_freshness_hours` | `max_hours` |

**Monitor types with no policy mapping** (show no policy badges in UI):
RANGE_VALIDATION, ACCEPTED_VALUES, DATE_CONSISTENCY, DATA_TYPE_VALIDATION, REFERENTIAL, CUSTOM_SQL, CERTIFICATE, SERVER_HEALTH, LOG_ANALYSIS.

These monitors have config fields that are too asset-specific for org-level policies (e.g., accepted values lists, specific column min/max ranges). They are fully user-configured.

This file contains:

- `POLICY_TO_MONITOR_CONFIG`: the mapping dict above
- `sensitivity_to_zscore(sensitivity: float) -> float`: moved from `recommender.py` to shared location
- `merge_policy_config(monitor_type, config, policy_config, policy_overrides) -> (merged_config, provenance)`: returns the merged config dict and a provenance dict (`{ field: "policy" | "override" | "config" }`) for logging
- `is_less_strict(field, policy_value, override_value) -> bool`: compares using field semantics

The recommender's `_build_config_hints()` is refactored to use this shared mapping instead of inline logic. `_sensitivity_to_zscore()` is moved here and the recommender imports it.

## Policy Violation Detection

"Less strict" depends on field semantics. `is_less_strict()` always compares values in **config-field space** (after conversion). For `anomaly_sensitivity`, the conversion to `anomaly_threshold` (z-score) happens first, then comparison uses z-score semantics (higher z-score = less strict = fewer alerts).

**Higher value = less strict:**
- `max_hours`, `warning_hours`, `max_null_rate`, `max_duplicate_rate`, `max_outlier_pct`, `max_lag_minutes`, `max_stale_hours`, `max_latency_minutes`, `max_schedule_lag_minutes`, `growth_rate_threshold`, `anomaly_threshold` (z-score: higher = fewer alerts)

**Lower value = less strict:**
- `min_rows`

**Strictness enums (ordered strict -> relaxed):**
- `schema_strictness`: strict > warn > ignore
- `failure_tolerance`: strict > normal > relaxed
- `upstream_break_strictness`: strict > warn > ignore
- `test_failure_tolerance`: strict > normal > relaxed

`is_less_strict()` in `policy_config.py` encodes these semantics. The UI uses this to decide badge color: amber "override" vs red "policy violation".

## UI Components

### WatchCard quick edit (group-level)

Add a gear icon to the existing `WatchCard.tsx`. Opens `WatchEditModal.tsx`:
- Watch name (text input)
- Schedule (reuse `ScheduleInput` component)
- Alert channels and alert-on-status
- Enable/disable toggle
- Save -> `PUT /api/schedule/watches/[watchId]`

### Monitor detail view (individual monitor editing)

When drilling into a WatchCard, the monitor list shows each monitor as expandable/clickable. Expanding reveals `MonitorEditPanel.tsx`:

**Config fields**: All fields for the monitor type, rendered dynamically from `config_schema` in the monitor catalog (same field rendering as `MonitorConfigForm` at creation).

**Policy badges per field** (`PolicyFieldBadge.tsx`): For fields that have a policy mapping:
- **"Policy"** (violet) -- value matches resolved policy. Shows source: "Critical SLA"
- **"Override"** (amber) -- value differs from policy. Shows: "Policy: 2h, Your value: 6h"
- **"Policy violation"** (red/amber warning) -- override is less strict than current policy
- No badge for fields without a policy equivalent (or for monitor types with no policy mapping)

**Actions**:
- "Reset to policy" button per overridden field -- re-resolves the live policy before writing to ensure fresh values
- "Reset all to policy" button per monitor
- Save -> `PUT /api/schedule/watches/[watchId]/monitors/[monitorId]`

### New components

| Component | Location | Purpose |
|---|---|---|
| `WatchEditModal.tsx` | `components/schedule/` | Group-level settings editor (name, schedule, alerts) |
| `MonitorEditPanel.tsx` | `components/schedule/` | Per-monitor config editor with policy integration |
| `PolicyFieldBadge.tsx` | `components/schedule/` | Inline badge showing policy/override/violation per field |

## API Changes

### Next.js

**`GET /api/schedule/watches/[watchId]`** (extend): Include resolved policy data per monitor. Collects all unique `targetFqn` values from monitors and calls `/api/schedule/policies/resolve` once (bulk resolution). Response shape per monitor:

```typescript
monitors[].resolvedPolicy: {
  profileName: string;           // "Critical SLA", "Standard", etc.
  status: PolicyStatus;          // "assigned" | "inherited" | "none"
  fields: Record<string, {       // keyed by config field name (e.g. "max_hours")
    policyValue: any;            // the policy's value for this field
    isOverridden: boolean;       // whether policyOverrides includes this key
    isLessStrict: boolean;       // whether the override is less strict than policy
  }>;
} | null                         // null if no policy exists for this target
```

**`PUT /api/schedule/watches/[watchId]`** (verify/extend): Ensure group-level settings (name, schedule, alerts, enabled) are updatable.

**`PUT /api/schedule/watches/[watchId]/monitors/[monitorId]`** (new): Update a single monitor's config and override tracking.
- Request: `{ config: {...}, policyOverrides: ["max_hours", ...] }`
- Validates policyOverrides keys are actual config keys
- Updates `Monitor.config` and `Monitor.policyOverrides` in Prisma
- Returns updated monitor

**`POST /api/schedule/tasks/[taskId]/run/route.ts`** (extend): After integration resolution, resolve the policy for the target FQN and send `policy_config` + `policy_overrides` alongside `config` to the Python executor.

### Python

**`ExecuteTaskRequest`** in `scanner/api/routers/schedule.py` -- add:
```python
policy_config: Optional[Dict[str, Any]] = None
policy_overrides: Optional[List[str]] = None
```

**`_execute_structured()`** in `scanner/scheduler/executor.py` -- before creating the monitor instance, call `merge_policy_config()` to produce the final config. Log provenance (which thresholds came from policy vs override).

## File Changes Summary

| Layer | File | Change |
|---|---|---|
| Prisma | `schema.prisma` | Add `policyOverrides String[]` to Monitor |
| Shared mapping | `scanner/monitors/policy_config.py` | New: mapping, merge, sensitivity_to_zscore, strictness comparison |
| Python executor | `scanner/scheduler/executor.py` | Policy-aware config merge |
| Python API | `scanner/api/routers/schedule.py` | Add policy fields to request model |
| Next.js run route | `app/api/schedule/tasks/[taskId]/run/route.ts` | Resolve policy, send both configs |
| Next.js watch API | `app/api/schedule/watches/[watchId]/route.ts` | Extend GET with resolved policies, verify PUT |
| Next.js monitor API | `app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts` | New: update monitor config + overrides |
| UI | `components/schedule/WatchCard.tsx` | Add gear icon |
| UI | `components/schedule/WatchEditModal.tsx` | New: group-level editor |
| UI | `components/schedule/MonitorEditPanel.tsx` | New: per-monitor editor with policy badges |
| UI | `components/schedule/PolicyFieldBadge.tsx` | New: inline policy status badge |
| Recommender | `scanner/monitors/recommender.py` | Refactor to use shared mapping, import sensitivity_to_zscore |

## Known Limitations

- **Race condition on reset**: If a user clicks "Reset to policy" while an admin is changing the policy assignment, the reset uses a freshly resolved value (mitigated by re-resolving on reset). Brief staleness is possible but low-risk.
- **No policy enforcement for prompt-mode monitors**: Monitors without a `targetFqn` (CUSTOM_SQL, prompt mode) cannot have policies resolved. They run with their stored config only.

## What stays untouched

- PolicyProfile / PolicyAssignment models
- PolicyEditorPanel in lineage
- Policy resolver logic
- Monitor creation flow (already uses policy at creation)
- PolicyBadge component (existing, for lineage view)
