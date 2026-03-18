# Monitor Creation Consolidation

**Date:** 2026-03-18
**Status:** Draft
**Scope:** Unify all monitor creation paths to use the plans system, add policy support, delete dead code

## Problem

Monitor creation is scattered across 3 different API endpoints, each producing different database record shapes with no policy support:

| Path | Used by | Creates | Policy | Tags/Icons |
|------|---------|---------|--------|------------|
| `POST /api/schedule/watches` | SingleAssetMonitorModal | MonitorGroup + Monitors | No | Yes (watchType badge, shield icon) |
| `POST /api/schedule/tasks` | Copilot, AI prompt (CreateTaskModal + MultiMonitorModal) | Standalone Monitor | No | No |
| `POST /api/schedule/plans` | MultiMonitorModal | MonitoringPlan + Groups + Monitors | No (resolved separately) | Consistent with plan UI |
| `POST /api/schedule/bundles` | Nothing (dead code) | MonitorGroup + Monitors | No | N/A |

This causes:
- Monitors look different depending on which path created them (different cards, tags, icons)
- Policy is never applied during creation despite having a full resolution system
- Features added to one path don't exist on others
- Dead code and redundant endpoints

## Goals

1. All monitor creation goes through one pipeline: FastAPI preview → policy resolve → Next.js plans create
2. Policy is automatically resolved and applied during creation, with user-editable overrides
3. Delete dead routes and code
4. Monitors created by any UI component or the copilot look identical in the schedule page

## Non-Goals

- Changing the schedule page display/management UI (WatchCard, WatchDetailPanel stay as-is)
- Migrating existing monitor records (user will delete them)
- Changing the monitoring plan / preset system (already works correctly)

## Architecture: Unified 3-Step Pipeline

Every monitor creation follows the same flow, regardless of source:

```
Step 1: POST /api/v1/monitors/plans/preview (FastAPI, stateless)
        Input:  scope_type, scope_config, mode, families/manual_selections
        Output: groups with recommendations + config_hints

Step 2: POST /api/v1/policies/resolve (FastAPI, stateless)
        Input:  node FQNs from preview result
        Output: effective policy per node (freshness thresholds, anomaly sensitivity, etc.)

Step 3: POST /api/schedule/plans (Next.js, persists to DB)
        Input:  plan name, groups (from preview), policy-enriched configs, schedule, alerts
        Output: MonitoringPlan + MonitorGroup + Monitor records
```

### What each caller provides

| Caller | Preview mode | Scope | Families |
|--------|-------------|-------|----------|
| MultiMonitorModal (presets) | `recommended` | `custom` with selected nodeIds | User-selected families |
| MultiMonitorModal (manual) | `manual` | `custom` with selected nodeIds | Derived from manual selections |
| SingleAssetMonitorModal | `manual` | `asset` with single nodeId | Derived from selected monitor types |
| CreateTaskModal (AI prompt) | `manual` | `asset` with single nodeId | Single prompt-based monitor |
| Copilot | `manual` | `asset` or `custom` | Derived from LLM's create_watch arguments |

### SingleAssetMonitorModal Rewire

**Current flow:**
```
Wizard (Pick Asset → Select Monitors → Schedule → Create)
  → POST /api/schedule/watches { watchType: "custom_watch", monitors: [...] }
```

**New flow:**
```
Wizard (Pick Asset → Select Monitors → Configure with Policy → Schedule & Alerts → Create)
  → POST /api/schedule/plans/preview { scopeType: "asset", mode: "manual", ... }
  → POST /api/schedule/policies/resolve { nodes: [{ fqn, domain, criticality }] }
  → User edits config fields, can override policy values (using MonitorEditPanel field rendering)
  → POST /api/schedule/plans { name, groups with policy-merged configs, schedule, alerts }
```

The wizard gains a **Configure** step between "Select Monitors" and "Schedule" where:
- Each monitor's config fields are shown with policy-resolved defaults pre-filled
- Override indicators show which values differ from policy (reuses `PolicyFieldBadge`)
- "Reset to policy" per field and bulk reset (reuses `MonitorEditPanel` field logic)
- Group settings (name, description) are editable

### CreateTaskModal Rewire

CreateTaskModal has two modes: `prompt` (AI prompt) and `structured` (manual config).

**Structured mode is retired.** Single-monitor creation with manual config now goes through `SingleAssetMonitorModal` (which has the same wizard + policy editing). The structured mode toggle is removed from CreateTaskModal.

**AI prompt mode stays** and is rewired to the plans system:
- `taskMode: "prompt"` is preserved in the monitor config
- The prompt text is stored in the monitor's `prompt` field
- Preview step uses `manual` mode with the target node
- Policy is resolved and applied to the monitor config
- Creation goes through `POST /api/schedule/plans`

After this rewire, `MonitorConfigForm.tsx` is no longer used by any component and can be deleted.

### MultiMonitorModal (AI Prompt Mode) Rewire

MultiMonitorModal's AI-prompt branch (line 682) also uses `POST /api/schedule/tasks`. This must be rewired to `POST /api/schedule/plans` with the same pattern as CreateTaskModal: wrap the prompt monitor in a plan with one group.

### Plans POST — Internal Auth for Copilot

`POST /api/schedule/plans` currently uses session-based auth only. The copilot executor needs to call it with the `X-Internal-Secret` header (same pattern already added to watches and tasks routes). Add internal auth fallback to the plans POST handler:

```typescript
// In app/api/schedule/plans/route.ts POST handler:
const internalSecret = request.headers.get('X-Internal-Secret');
const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

if (internalSecret && internalSecret === expectedSecret) {
  organizationId = request.headers.get('X-Organization-Id') || undefined;
  userId = 'copilot-system';
} else {
  // existing session auth
}
```

### Pipeline Scoping

All 3 steps must include the pipeline context:
- Step 1 (preview): `stack_id` query param (already supported by FastAPI)
- Step 2 (policy resolve): `stackId` in request body (already supported)
- Step 3 (plans create): the `scopeConfig` contains `nodeIds` which are pipeline-scoped

Callers must pass `pipelineStackId` from the active pipeline context. The copilot gets this from `self.context.pipeline_stack_id`.

### Policy-to-Config Merge

The canonical policy → monitor config mapping is defined in `POLICY_TO_MONITOR_CONFIG` in `scanner/monitors/policy_config.py`. The existing `merge_policy_config()` function in that file handles the merge logic. **All callers must use this shared function — do not reimplement the mapping.**

The merge semantics: policy provides defaults, user/LLM config overrides. Track overridden fields in `policyOverrides[]` on the Monitor record.

For frontend callers (SingleAssetMonitorModal, MultiMonitorModal), the policy resolve response already provides the resolved values in a structured format. The frontend merges these into `config_hints` from the preview response. The existing `MonitorEditPanel` handles override tracking via its `overrides` state.

For the copilot, `_merge_policy_into_groups` must call `merge_policy_config()` from `scanner.monitors.policy_config` for each monitor in each group — not reimplement the field mapping inline.

### Error Handling in the 3-Step Pipeline

If any step fails, the behavior is:
- **Step 1 (preview) fails**: Abort. Show error to user. No monitors created.
- **Step 2 (policy resolve) fails**: Non-fatal. Proceed with empty policy (config_hints from preview are still used). Log a warning.
- **Step 3 (plans create) fails**: Abort. Show error. The preview and policy data are stateless so nothing to roll back.

### Copilot Rewire

The copilot's `_execute_confirmed_create_watch` calls all 3 steps:

```python
async def _execute_confirmed_create_watch(self, data):
    # Resolve anchor_fqn to node_id from lineage graph
    node_id = self._resolve_fqn_to_node_id(data["anchorFqn"])

    # Step 1: Preview
    preview = await self._call_fastapi("/api/v1/monitors/plans/preview", {
        "scope_type": "asset",
        "scope_config": {"nodeIds": [node_id]},
        "mode": "manual",
        "manual_selections": {node_id: [mon["monitorType"] for mon in data["monitors"]]},
    })

    # Step 2: Policy resolve
    policies = await self._call_fastapi("/api/v1/policies/resolve", {
        "nodes": [{"fqn": data["anchorFqn"]}],
    })

    # Step 3: Merge policy into group configs and create plan
    groups = self._merge_policy_into_groups(preview["groups"], policies)
    result = await self._call_nextjs("/api/schedule/plans", {
        "name": data["name"],
        "scopeType": "asset",
        "scopeConfig": {"nodeIds": [node_id]},
        "mode": "manual",
        "families": [],
        "schedule": data["schedule"],
        "timezone": data["timezone"],
        "groups": groups,
    })
```

Helper methods:
- `_call_fastapi(path, body)` — HTTP POST to FastAPI (scanner) with stack_id query param
- `_call_nextjs(path, body)` — HTTP POST to Next.js with X-Internal-Secret header
- `_resolve_fqn_to_node_id(fqn)` — looks up node ID from `self.context.graph`
- `_merge_policy_into_groups(groups, policies)` — merges resolved policy configs into group recommendations

## What Gets Deleted

### Routes — delete entirely
| Item | Reason |
|------|--------|
| `app/api/schedule/bundles/` (entire directory) | Dead code, zero frontend usage |

### Routes — delete POST handler only (keep GET/PATCH/DELETE)
| Item | Reason |
|------|--------|
| `POST` in `app/api/schedule/watches/route.ts` | Creation replaced by plans flow |
| `POST` in `app/api/schedule/tasks/route.ts` | Creation replaced by plans flow |

### Dead UI code — delete after rewire
| Item | Reason |
|------|--------|
| `MonitorConfigForm.tsx` | Only used by CreateTaskModal's structured mode, which is retired. Delete after rewire. |
| Internal auth additions on watches/tasks POST | POST handlers are deleted, auth goes with them |

### Routes — keep (still needed)
| Item | Reason |
|------|--------|
| `GET /api/schedule/watches` | Schedule page lists watch groups |
| `GET/PATCH/DELETE /api/schedule/watches/[watchId]` | Manage existing groups |
| `POST /api/schedule/watches/[watchId]/run` | Run monitors in a group |
| `GET /api/schedule/tasks` | List standalone legacy monitors (display only) |
| `PUT /api/schedule/tasks/[taskId]` | Edit existing monitors |
| All `/api/schedule/plans/` endpoints | The creation system |
| `app/api/schedule/plans/preview/route.ts` | Next.js proxy to FastAPI preview |
| `app/api/schedule/policies/resolve/route.ts` | Next.js proxy to FastAPI policy resolve |
| All FastAPI routers (`plans.py`, `policies.py`) | Source of truth |

### UI components — keep (still needed)
| Component | Reason |
|-----------|--------|
| `SingleAssetMonitorModal.tsx` | Rewired to plans, not deleted |
| `MultiMonitorModal.tsx` | Already on new system |
| `CreateTaskModal.tsx` | Rewired for AI prompt mode |
| `MonitorEditPanel.tsx` | Used for editing + policy overrides |
| `PolicyFieldBadge.tsx` | Used in policy override UI |
| `WatchCard.tsx` | Schedule page display |
| `WatchDetailPanel.tsx` | Schedule page detail |

## Changes Summary

| Layer | File(s) | Change |
|-------|---------|--------|
| Backend | `app/api/schedule/bundles/` | Delete entire directory |
| Backend | `app/api/schedule/watches/route.ts` | Delete POST handler |
| Backend | `app/api/schedule/tasks/route.ts` | Delete POST handler |
| Frontend | `SingleAssetMonitorModal.tsx` | Rewire from watches POST to 3-step plans flow. Add policy configure step. |
| Frontend | `CreateTaskModal.tsx` | Rewire AI prompt creation from tasks POST to plans flow |
| Frontend | `MultiMonitorModal.tsx` | Rewire AI-prompt branch from tasks POST to plans flow |
| Frontend | `schedule/page.tsx` | Remove `handleCreateTask` POST logic, keep edit logic |
| Frontend | `lineage/page.tsx` | Update CreateTaskModal usage for AI prompt |
| Backend | `app/api/schedule/plans/route.ts` | Add internal auth (X-Internal-Secret) to POST handler for copilot access |
| Backend | `scanner/copilot/tool_executor.py` | Rewire `_execute_confirmed_create_watch` to 3-step flow. Add `_call_fastapi`, `_call_nextjs`, `_resolve_fqn_to_node_id`, `_merge_policy_into_groups` helpers. |
| Frontend | `MonitorConfigForm.tsx` | Delete (structured mode retired, no longer used) |

## Implementation Order

1. **Rewire SingleAssetMonitorModal** — biggest UI change (add policy step, change API calls)
2. **Rewire CreateTaskModal** — smaller change (AI prompt to plans flow)
3. **Rewire copilot executor** — backend change (3-step API calls)
4. **Delete dead code** — bundles directory, POST handlers, unused components
5. **Test all creation paths** — verify monitors from all sources look identical in schedule page
