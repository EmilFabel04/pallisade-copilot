# Monitor Creation Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate all monitor creation paths to use the unified 3-step pipeline (FastAPI preview → policy resolve → Next.js plans persist), add policy support, and delete dead code.

**Architecture:** Every monitor creation — SingleAssetMonitorModal, CreateTaskModal, MultiMonitorModal AI-prompt, and copilot — calls the same 3 endpoints: preview for recommendations, policy resolve for config defaults, plans POST for persistence. Dead routes (bundles, watches POST, tasks POST) are deleted.

**Tech Stack:** TypeScript (Next.js, React), Python (FastAPI), Prisma, aiohttp

**Spec:** `docs/superpowers/specs/2026-03-18-monitor-creation-consolidation-design.md`

---

## File Structure

### Modified Files
| File | Change |
|------|--------|
| `app/api/schedule/plans/route.ts` | Add internal auth (X-Internal-Secret) to POST handler |
| `components/schedule/SingleAssetMonitorModal.tsx` | Rewire from watches POST to 3-step plans flow, add policy configure step |
| `components/schedule/CreateTaskModal.tsx` | Retire structured mode, rewire AI prompt to plans flow |
| `components/schedule/MultiMonitorModal.tsx` | Rewire AI-prompt branch from tasks POST to plans flow |
| `app/(dashboard)/dashboard/schedule/page.tsx` | Remove handleCreateTask POST logic |
| `scanner/copilot/tool_executor.py` | Rewire _execute_confirmed_create_watch to 3-step flow |

### Deleted Files/Directories
| File | Reason |
|------|--------|
| `app/api/schedule/bundles/` (entire directory) | Dead code |
| `components/schedule/MonitorConfigForm.tsx` | Only used by retired structured mode |

### Deleted Code (within files)
| File | What to delete |
|------|---------------|
| `app/api/schedule/watches/route.ts` | POST handler function |
| `app/api/schedule/tasks/route.ts` | POST handler function |

---

## Task 1: Add Internal Auth to Plans POST

**Files:**
- Modify: `app/api/schedule/plans/route.ts`

This is a prerequisite for the copilot rewire — the Python executor needs to call this endpoint.

- [ ] **Step 1: Read the current POST handler auth**

Read `app/api/schedule/plans/route.ts` lines 120-135 to see the current session auth pattern.

- [ ] **Step 2: Add internal auth fallback**

Replace the auth block in the POST handler with dual auth (same pattern as watches route):

```typescript
// Support both session auth (browser) and internal auth (copilot executor)
let organizationId: string | undefined;
let userId: string | undefined;

const internalSecret = request.headers.get('X-Internal-Secret');
const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

if (internalSecret && internalSecret === expectedSecret) {
  organizationId = request.headers.get('X-Organization-Id') || undefined;
  userId = 'copilot-system';
} else {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  organizationId = (session.user as any).organizationId;
  userId = (session.user as any).id;
}
```

- [ ] **Step 3: Verify plans route loads**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | grep plans/route`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add app/api/schedule/plans/route.ts
git commit -m "feat: add internal auth to plans POST for copilot access"
```

---

## Task 2: Rewire SingleAssetMonitorModal to Plans Flow

**Files:**
- Modify: `components/schedule/SingleAssetMonitorModal.tsx`

This is the biggest change — the wizard gets a policy configure step and switches from watches POST to the 3-step pipeline.

- [ ] **Step 1: Read the current modal**

Read `components/schedule/SingleAssetMonitorModal.tsx` fully. Understand:
- The 4-step wizard structure
- The `handleCreate` function (around line 218) that POSTs to `/api/schedule/watches`
- The `recommendations` state (monitor recommendations from the asset)
- The `selectedMonitors` state
- The `watchName`, `schedule`, `timezone`, `alertChannels`, `alertOnStatus` state

- [ ] **Step 1b: Extend AssetPrefill interface**

The current `AssetPrefill` type (around line 12-17) only has `{ nodeId, fqn, name, platform? }`. Add `domain`, `criticality`, and `nodeType` fields so policy resolve and plan creation work:

```typescript
export type AssetPrefill = {
  nodeId: string;
  fqn: string;
  name: string;
  platform?: string;
  domain?: string;      // NEW — for policy resolve
  criticality?: string; // NEW — for policy resolve
  nodeType?: string;    // NEW — for plan groups
};
```

Also update the asset search/selection mapping (around line 173) to populate these fields from the lineage graph node data.

- [ ] **Step 2: Add policy state and fetch**

Add state for resolved policies and a fetch function:

```typescript
const [resolvedPolicies, setResolvedPolicies] = useState<Record<string, any>>({});
const [policyLoading, setPolicyLoading] = useState(false);

// Fetch policies when monitors are selected (entering step 3)
const fetchPolicies = useCallback(async () => {
  if (!selectedAsset) return;
  setPolicyLoading(true);
  try {
    const res = await fetch('/api/schedule/policies/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nodes: [{ fqn: selectedAsset.fqn, domain: selectedAsset.domain, criticality: selectedAsset.criticality }],
        stackId,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      setResolvedPolicies(data.policies || {});
    }
  } catch (err) {
    console.warn('Policy resolve failed:', err);
  } finally {
    setPolicyLoading(false);
  }
}, [selectedAsset, stackId]);
```

- [ ] **Step 3: Add policy config editing state**

Add state to track per-monitor config overrides:

```typescript
// monitorConfigs[index] = { config: {...}, overrides: string[] }
const [monitorConfigs, setMonitorConfigs] = useState<Record<number, { config: Record<string, any>; overrides: string[] }>>({});
```

When entering the configure step, initialize from recommendations + policy. Use `getPolicyValueForField` from `@/lib/policy-utils` (which already handles monitor-type-to-policy-section mapping) to fill policy defaults for each config field:

```typescript
import { POLICY_FIELD_MAP, getPolicyValueForField } from '@/lib/policy-utils';

const initConfigs = () => {
  const policy = resolvedPolicies[selectedAsset?.fqn || ''];
  const configs: typeof monitorConfigs = {};
  recommendations.forEach((rec, i) => {
    if (!selectedMonitors.has(`${i}`)) return;
    const baseConfig = { ...(rec.config_hints || {}) };
    // Fill policy defaults for fields not already in config_hints
    if (policy) {
      const fields = POLICY_FIELD_MAP[rec.monitor_key] || [];
      for (const field of fields) {
        if (!(field.key in baseConfig)) {
          const policyVal = getPolicyValueForField(field.key, rec.monitor_key, policy);
          if (policyVal != null) baseConfig[field.key] = policyVal;
        }
      }
    }
    configs[i] = { config: baseConfig, overrides: [] };
  });
  setMonitorConfigs(configs);
};
```

Note: `POLICY_FIELD_MAP` and `getPolicyValueForField` are already exported from `lib/policy-utils.ts` and handle the monitor-type → policy-section lookup internally.

- [ ] **Step 4: Add a Configure step to the wizard**

Insert a new step between "Select Monitors" (step 2) and "Schedule" (step 3). The wizard steps become:
1. Pick Asset
2. Select Monitors
3. **Configure & Policy** (NEW)
4. Schedule
5. Alerts & Create

The configure step renders each selected monitor's config fields with policy indicators. Reuse the field rendering pattern from `MonitorEditPanel`:

```tsx
{/* Step 3: Configure & Policy */}
{step === 3 && (
  <div className="space-y-4">
    <p className="text-sm text-muted-foreground">
      Configure monitor settings. Policy defaults are pre-filled.
    </p>
    {recommendations.filter((_, i) => selectedMonitors.has(`${i}`)).map((rec, idx) => {
      const origIdx = recommendations.indexOf(rec);
      const mc = monitorConfigs[origIdx] || { config: {}, overrides: [] };
      return (
        <div key={origIdx} className="border border-border rounded-lg p-3">
          <h4 className="font-medium text-sm mb-2">{rec.monitor_key} — {rec.target_fqn}</h4>
          {/* Render config fields using MonitorEditPanel's field pattern */}
          {/* Each field shows current value, policy value, override indicator */}
          {/* Use PolicyFieldBadge for override indicators */}
        </div>
      );
    })}
  </div>
)}
```

Note: The exact field rendering should follow the pattern in `MonitorEditPanel.tsx` — import `PolicyFieldBadge`, `POLICY_FIELD_MAP`, `getPolicyValueForField`, and `isLessStrictClient` from `@/lib/policy-utils`.

- [ ] **Step 5: Rewrite handleCreate to use 3-step pipeline**

Replace the current `handleCreate` that POSTs to `/api/schedule/watches` with:

```typescript
const handleCreate = async () => {
  setCreating(true);
  try {
    // Build groups from selected monitors with policy-merged configs
    const selectedRecs = recommendations
      .filter((_, i) => selectedMonitors.has(`${i}`))
      .map((rec, idx) => {
        const origIdx = recommendations.indexOf(rec);
        const mc = monitorConfigs[origIdx];
        return {
          monitor_key: rec.monitor_key,
          target_fqn: rec.target_fqn,
          target_node_id: rec.target_node_id,
          config_hints: mc ? mc.config : (rec.config_hints || {}),
          depth: rec.depth || 0,
          priority: rec.priority || 1,
        };
      });

    const groups = [{
      anchor_name: selectedAsset.name,
      anchor_fqn: selectedAsset.fqn,
      anchor_id: selectedAsset.nodeId,
      anchor_node_type: selectedAsset.nodeType || 'table',
      anchor_platform: selectedAsset.platform || 'unknown',
      watch_type: 'pipeline_health',
      recommendations: selectedRecs,
    }];

    // Step 3: Create plan (preview + policy already done)
    const res = await fetch('/api/schedule/plans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: watchName,
        scopeType: 'asset',
        scopeConfig: { nodeIds: [selectedAsset.nodeId] },
        mode: 'manual',
        families: [],
        schedule,
        timezone,
        alertChannels,
        alertOnStatus,
        groups,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to create monitors');
    }

    onComplete();
    onClose();
  } catch (err: any) {
    console.error('Monitor creation failed:', err);
    // Show error to user
  } finally {
    setCreating(false);
  }
};
```

- [ ] **Step 6: Update step navigation**

Update the step count from 4 to 5. Update Next/Back button logic. Call `fetchPolicies()` when entering step 3. Call `initConfigs()` after policies are loaded.

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | grep SingleAssetMonitor`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add components/schedule/SingleAssetMonitorModal.tsx
git commit -m "feat: rewire SingleAssetMonitorModal to plans flow with policy configure step"
```

---

## Task 3: Rewire CreateTaskModal (Retire Structured Mode)

**Files:**
- Modify: `components/schedule/CreateTaskModal.tsx`
- Modify: `app/(dashboard)/dashboard/schedule/page.tsx`
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx` (also renders CreateTaskModal with inline tasks POST)

- [ ] **Step 1: Read CreateTaskModal**

Read `components/schedule/CreateTaskModal.tsx` fully. Understand the prompt vs structured mode toggle, the handleSubmit logic, and how onSubmit is called.

- [ ] **Step 2: Remove structured mode**

Remove the mode toggle UI (the "AI Prompt" / "Monitor" choice buttons). Make the modal always operate in prompt mode. Remove:
- The `taskMode` state and toggle
- The structured mode fields (monitorType, targetFqn, config)
- The `MonitorConfigForm` import (if present)
- Any conditional rendering based on `taskMode === 'structured'`

Keep:
- The prompt textarea
- Schedule, timezone, alerts fields
- The integration selector (for prompt mode)

- [ ] **Step 3: Rewrite handleSubmit for plans flow**

Replace the current submit that calls `onSubmit(taskData)` → `handleCreateTask` → `POST /tasks` with a direct plans creation:

```typescript
const handleSubmit = async () => {
  if (!name || !schedule) return;
  setCreating(true);
  try {
    // For AI prompt monitors, we create a plan with one group containing one prompt monitor
    const groups = [{
      anchor_name: name,
      anchor_fqn: targetFqn || name,
      anchor_id: 'prompt_monitor',
      anchor_node_type: 'prompt',
      anchor_platform: 'ai',
      watch_type: 'custom_watch',
      recommendations: [{
        monitor_key: 'AI_PROMPT',
        target_fqn: targetFqn || name,
        config_hints: {
          taskMode: 'prompt',
          prompt,
          ...(integrationId ? { integrationId } : {}),
        },
      }],
    }];

    const res = await fetch('/api/schedule/plans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        scopeType: 'asset',
        mode: 'manual',
        families: [],
        schedule,
        timezone,
        alertChannels,
        alertOnStatus,
        groups,
      }),
    });

    if (res.ok) {
      onClose();
      onComplete?.();
    }
  } catch (err) {
    console.error('Prompt monitor creation failed:', err);
  } finally {
    setCreating(false);
  }
};
```

Note: The `onSubmit` prop is no longer needed for creation — the modal handles creation directly. Keep `onUpdate` for editing existing monitors.

- [ ] **Step 4: Update schedule/page.tsx**

In `app/(dashboard)/dashboard/schedule/page.tsx`:
- Remove the `handleCreateTask` function that POSTs to `/api/schedule/tasks`
- Update the `CreateTaskModal` props: remove `onSubmit={handleCreateTask}`, add `onComplete={refreshAll}`
- Keep `onUpdate={handleUpdateTask}` for editing
- IMPORTANT: Verify that the edit path in `CreateTaskModal` uses `onUpdate`, not `onSubmit`. The `handleSubmit` function in the modal should check `if (isEditing && onUpdate)` and call `onUpdate(editTask.id, taskData)` — this path stays unchanged. Only the new-creation path changes to call the plans API directly.

- [ ] **Step 4b: Update lineage/page.tsx**

In `app/(dashboard)/dashboard/lineage/page.tsx` (around line 2327):
- Find the `CreateTaskModal` instance used for AI prompt monitor creation
- It has an inline `onSubmit` that POSTs to `/api/schedule/tasks` — remove this
- Replace with `onComplete` prop that refreshes the relevant data
- The modal now handles creation internally via the plans API

- [ ] **Step 5: Verify compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | head -20`

- [ ] **Step 6: Commit**

```bash
git add components/schedule/CreateTaskModal.tsx 'app/(dashboard)/dashboard/schedule/page.tsx'
git commit -m "feat: retire structured mode, rewire AI prompt to plans flow"
```

---

## Task 4: Rewire MultiMonitorModal AI-Prompt Branch

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx`

- [ ] **Step 1: Find the AI-prompt branch**

Read `components/schedule/MultiMonitorModal.tsx` around line 680. The AI-prompt branch calls `POST /api/schedule/tasks`.

- [ ] **Step 2: Rewrite AI-prompt creation to use plans**

Replace the `fetch('/api/schedule/tasks', ...)` call with a plans creation:

```typescript
// AI-prompt branch — wrap in a plan
const groups = [{
  anchor_name: planName,
  anchor_fqn: planName,
  anchor_id: 'ai_prompt',
  anchor_node_type: 'prompt',
  anchor_platform: 'ai',
  watch_type: 'custom_watch',
  recommendations: [{
    monitor_key: 'AI_PROMPT',
    target_fqn: planName,
    config_hints: {
      taskMode: 'prompt',
      prompt: aiPrompt,
      ...(aiIntegrationId ? { integrationId: aiIntegrationId } : {}),
    },
  }],
}];

const res = await fetch('/api/schedule/plans', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    name: planName,
    scopeType: 'asset',
    mode: 'manual',
    families: [],
    schedule,
    timezone,
    alertChannels,
    alertOnStatus,
    groups,
  }),
});
```

- [ ] **Step 3: Verify compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | grep MultiMonitorModal`

- [ ] **Step 4: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: rewire MultiMonitorModal AI-prompt branch to plans flow"
```

---

## Task 5: Rewire Copilot Executor to 3-Step Flow

**Files:**
- Modify: `scanner/copilot/tool_executor.py`

- [ ] **Step 1: Add helper methods**

Add these helper methods to the `ToolExecutor` class:

```python
async def _call_fastapi(self, path: str, body: dict) -> dict:
    """POST to FastAPI (scanner) endpoint."""
    import aiohttp
    base = "http://127.0.0.1:8000"  # FastAPI runs locally
    stack_id = getattr(self.context, 'pipeline_stack_id', '') or ''
    url = f"{base}{path}"
    if stack_id:
        url += f"?stack_id={stack_id}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers={"Content-Type": "application/json"}) as resp:
            if resp.status != 200:
                error = await resp.text()
                raise Exception(f"FastAPI {path} failed ({resp.status}): {error}")
            return await resp.json()

async def _call_nextjs(self, path: str, body: dict) -> dict:
    """POST to Next.js endpoint with internal auth."""
    import aiohttp
    import os
    url = f"{self.context.base_url}{path}"
    headers = {
        "X-Internal-Secret": os.environ.get("INTERNAL_API_SECRET", "pallisade-internal"),
        "X-Organization-Id": self.context.org_id,
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers) as resp:
            if resp.status not in (200, 201):
                error = await resp.text()
                raise Exception(f"Next.js {path} failed ({resp.status}): {error}")
            return await resp.json()

def _resolve_fqn_to_node_id(self, fqn: str) -> str:
    """Look up node ID from lineage graph."""
    if hasattr(self.context, 'graph') and self.context.graph:
        for node in self.context.graph.nodes:
            if hasattr(node, 'fqn') and node.fqn == fqn:
                return getattr(node, 'id', '') or getattr(node, 'node_id', '') or ''
    return ''

def _merge_policy_into_groups(self, groups: list, policies: dict) -> list:
    """Merge resolved policy configs into group recommendations.

    The /policies/resolve endpoint returns nested sections:
      { "fqn": { freshness: {maxHours: 2}, schema: {strictness: "strict"}, ... } }

    merge_policy_config() expects flat policy-field keys:
      { "freshness_max_hours": 2, "schema_strictness": "strict", ... }

    We flatten the nested structure before calling merge_policy_config.
    """
    from scanner.monitors.policy_config import merge_policy_config
    policy_map = policies.get("policies", {})

    def _flatten_policy(nested: dict) -> dict:
        """Convert nested {section: {field: val}} to flat {section_field: val}."""
        flat = {}
        for section, fields in nested.items():
            if isinstance(fields, dict):
                for key, val in fields.items():
                    # Convert camelCase to snake_case: maxHours → max_hours
                    snake_key = ''.join(f'_{c.lower()}' if c.isupper() else c for c in key)
                    flat[f"{section}_{snake_key}"] = val
            # Skip non-dict fields like 'source', 'profileId', 'status'
        return flat

    for group in groups:
        for rec in group.get("recommendations", []):
            fqn = rec.get("target_fqn", "")
            policy = policy_map.get(fqn)
            if policy and rec.get("monitor_key"):
                flat_policy = _flatten_policy(policy)
                merged, _ = merge_policy_config(
                    monitor_type=rec["monitor_key"],
                    config=rec.get("config_hints", {}),
                    policy_config=flat_policy,
                    policy_overrides=[],
                )
                rec["config_hints"] = merged
    return groups
```

- [ ] **Step 2: Rewrite _execute_confirmed_create_watch**

Replace the current implementation with the 3-step flow:

```python
async def _execute_confirmed_create_watch(self, data: Dict[str, Any]) -> ToolResult:
    """Create monitors via the unified 3-step pipeline."""
    anchor_fqn = data.get("anchorFqn") or data.get("anchor_fqn") or ""
    node_id = self._resolve_fqn_to_node_id(anchor_fqn)
    monitors = data.get("monitors", [])

    # Normalize monitor types
    monitor_types = []
    for mon in monitors:
        mt = mon.get("monitorType") or mon.get("monitor_type") or ""
        monitor_types.append(mt)

    try:
        # Step 1: Preview
        manual_selections = {node_id: monitor_types} if node_id else {}
        preview = await self._call_fastapi("/api/v1/monitors/plans/preview", {
            "scope_type": "asset",
            "scope_config": {"nodeIds": [node_id]} if node_id else {},
            "mode": "manual",
            "manual_selections": manual_selections,
            "families": [],
        })
    except Exception as e:
        logger.error(f"[CreateMonitor] Preview failed: {e}")
        return ToolResult(success=False, error=f"Preview failed: {e}")

    # Step 2: Policy resolve (non-fatal)
    policies = {}
    try:
        policies = await self._call_fastapi("/api/v1/policies/resolve", {
            "nodes": [{"fqn": anchor_fqn}],
            "stackId": getattr(self.context, 'pipeline_stack_id', ''),
        })
    except Exception as e:
        logger.warning(f"[CreateMonitor] Policy resolve failed (non-fatal): {e}")

    # Merge policy into groups
    groups = preview.get("groups", [])
    if policies:
        groups = self._merge_policy_into_groups(groups, policies)

    try:
        # Step 3: Create plan
        result = await self._call_nextjs("/api/schedule/plans", {
            "name": data.get("name", "Copilot Monitor"),
            "scopeType": "asset",
            "scopeConfig": {"nodeIds": [node_id]} if node_id else {},
            "mode": "manual",
            "families": [],
            "schedule": data.get("schedule", "0 * * * *"),
            "timezone": data.get("timezone", "UTC"),
            "groups": groups,
        })
    except Exception as e:
        logger.error(f"[CreateMonitor] Plan creation failed: {e}")
        return ToolResult(success=False, error=f"Monitor creation failed: {e}")

    return ToolResult(
        success=True,
        data={
            "planId": result.get("id"),
            "name": result.get("name"),
            "monitorCount": result.get("totalMonitors", len(monitors)),
            "message": f"Created {result.get('totalMonitors', 0)} monitor(s) in plan '{result.get('name')}'",
        }
    )
```

- [ ] **Step 3: Run existing tests**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_write_tools.py -v`
Note: Tests may need updating since the mock expectations changed (now calls FastAPI + plans instead of tasks). Update mocks if needed.

- [ ] **Step 4: Commit**

```bash
git add scanner/copilot/tool_executor.py
git commit -m "feat: rewire copilot executor to 3-step plans pipeline"
```

---

## Task 6: Delete Dead Code

**Files:**
- Delete: `app/api/schedule/bundles/` (entire directory)
- Modify: `app/api/schedule/watches/route.ts` (remove POST handler)
- Modify: `app/api/schedule/tasks/route.ts` (remove POST handler)
- Delete: `components/schedule/MonitorConfigForm.tsx`

- [ ] **Step 1: Delete bundles directory**

```bash
rm -rf app/api/schedule/bundles/
```

- [ ] **Step 2: Remove POST handler from watches route**

In `app/api/schedule/watches/route.ts`, delete the entire `export async function POST(request: NextRequest)` function and its helper imports that are only used by POST (like `computeNextRun` if only POST uses it — check first).

Keep: `GET` handler, all imports used by GET.

- [ ] **Step 3: Remove POST handler from tasks route**

In `app/api/schedule/tasks/route.ts`, delete the `export async function POST(request: NextRequest)` function.

Keep: `GET` handler.

- [ ] **Step 4: Delete MonitorConfigForm**

```bash
rm components/schedule/MonitorConfigForm.tsx
```

- [ ] **Step 5: Clean up imports**

Search for and remove any remaining imports of:
- `MonitorConfigForm` in any file
- References to `/api/schedule/bundles` in any file
- The `handleCreateTask` function if not already removed

Run: `grep -r "MonitorConfigForm\|/schedule/bundles\|handleCreateTask" --include="*.ts" --include="*.tsx" app/ components/ | grep -v node_modules`

Fix any remaining references.

- [ ] **Step 6: Verify everything compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | head -20`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: delete dead code — bundles route, watches/tasks POST, MonitorConfigForm"
```

---

## Task 7: Smoke Test All Creation Paths

- [ ] **Step 1: Test SingleAssetMonitorModal**

Navigate to Lineage → click a table node → click "Monitor" → go through the 5-step wizard:
1. Asset should be pre-selected
2. Select monitors (e.g., FRESHNESS)
3. Configure step should show policy-resolved defaults
4. Set schedule
5. Click Create

Verify: Monitor appears on schedule page as a plan with 1 group, 1 monitor. No shield icon or watchType tag.

- [ ] **Step 2: Test MultiMonitorModal (manual mode)**

Schedule page → "+ New" → select nodes → manual mode → select monitors → create.
Verify: Creates a plan with correct groups and monitors.

- [ ] **Step 3: Test MultiMonitorModal (AI prompt)**

Schedule page → "+ New" → AI prompt mode → enter prompt → create.
Verify: Creates a plan with one group containing the prompt monitor.

- [ ] **Step 4: Test copilot**

Assistant page → "Create a freshness monitor for public.orders"
Verify: Card appears → click Confirm → monitor created as a plan. No shield icon.

- [ ] **Step 5: Verify dead routes are gone**

```bash
curl -X POST http://localhost:3000/api/schedule/bundles -H "Content-Type: application/json" -d '{}'
# Expected: 404

curl -X POST http://localhost:3000/api/schedule/watches -H "Content-Type: application/json" -d '{}'
# Expected: 405 Method Not Allowed (GET still works, POST removed)

curl -X POST http://localhost:3000/api/schedule/tasks -H "Content-Type: application/json" -d '{}'
# Expected: 405 Method Not Allowed (GET still works, POST removed)
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "test: smoke test fixes for monitor creation consolidation"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Internal auth on plans POST | `plans/route.ts` |
| 2 | Rewire SingleAssetMonitorModal | `SingleAssetMonitorModal.tsx` |
| 3 | Rewire CreateTaskModal | `CreateTaskModal.tsx`, `schedule/page.tsx` |
| 4 | Rewire MultiMonitorModal AI-prompt | `MultiMonitorModal.tsx` |
| 5 | Rewire copilot executor | `tool_executor.py` |
| 6 | Delete dead code | bundles/, watches POST, tasks POST, MonitorConfigForm |
| 7 | Smoke test all paths | Manual testing |
