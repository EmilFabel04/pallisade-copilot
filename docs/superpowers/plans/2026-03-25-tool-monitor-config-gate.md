# Tool Monitor Config Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block tool monitor creation in MultiMonitorModal until required config fields (connector_id, dag_id, etc.) are filled in.

**Architecture:** Extend the existing `MonitorCard` component to render inline config forms for tool monitors. Add a validation helper that checks required fields from `config_schema` in `monitor-catalog.ts`. Gate the Step 2 → Step 3 transition on this validation.

**Tech Stack:** React, TypeScript, Next.js — all changes are frontend-only in `components/schedule/MultiMonitorModal.tsx`.

**Notes:**
- `types/monitor-catalog.ts` already has `config_schema` with `required` fields — no changes needed there
- The "Advanced" toggle for non-required fields is deferred — only required fields are rendered in this iteration
- `monitorConfigs` values are already merged into `config_hints` on create via `handleCreate` (line 838-844) — no changes needed there
- When a tool monitor card expands in a multi-column grid, adjacent cards may misalign vertically — accepted cosmetic trade-off for now

**Spec:** `docs/superpowers/specs/2026-03-25-tool-monitor-config-gate-design.md`

---

### Task 1: Add `monitorConfigs` Reset on Modal Open

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx:358-381` (reset `useEffect`)

Currently `monitorConfigs` is not reset when the modal opens, so stale config from a previous session bleeds through.

- [ ] **Step 1: Add `setMonitorConfigs({})` to the reset effect**

In `components/schedule/MultiMonitorModal.tsx`, inside the `useEffect` that runs when `open` changes (around line 358-381), add the reset call alongside the existing `setMonitorChecks({})`:

```typescript
// Inside the useEffect(() => { if (open) { ... } }, [open, ...])
// After line 368: setMonitorChecks({});
setMonitorConfigs({});
```

- [ ] **Step 2: Verify modal still opens and resets correctly**

Run the dev server and open the MultiMonitorModal from the task page. Select some monitors, close the modal, reopen it. Confirm that no stale config values persist.

- [ ] **Step 3: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "fix: reset monitorConfigs when MultiMonitorModal opens"
```

---

### Task 2: Add `hasIncompleteToolConfig` Validation Helper

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx` (add helper function before the component, around line 198-216)

- [ ] **Step 1: Add the helper function**

Add this function after the `TOOL_ONLY_MONITOR_KEYS` constant (line 203) and before the `CONFIG_TABS` constant (line 205):

```typescript
/**
 * Returns true if any checked tool monitor has missing required config fields.
 * Only applies to tool nodes (subNodeIds.length > 0) with TOOL_ONLY_MONITOR_KEYS monitors.
 */
function hasIncompleteToolConfig(
  checks: Record<string, boolean>,
  configs: Record<string, Record<string, any>>,
  nodesWithMonitors: Array<{ meta: NodeMeta; monitors: MonitorOption[] }>,
): boolean {
  for (const { meta, monitors } of nodesWithMonitors) {
    if (!meta.subNodeIds?.length) continue;
    for (const mon of monitors) {
      const checkKey = `${mon.targetNodeId}::${mon.key}`;
      if (!checks[checkKey]) continue;
      if (!TOOL_ONLY_MONITOR_KEYS.has(mon.key)) continue;

      const def = getMonitorDefinition(mon.key);
      if (!def) continue;

      const config = configs[checkKey] || {};
      const hasMissing = def.config_schema
        .filter((f) => f.required)
        .some((f) => !config[f.key] && config[f.key] !== 0);

      if (hasMissing) return true;
    }
  }
  return false;
}
```

- [ ] **Step 2: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: add hasIncompleteToolConfig validation helper"
```

---

### Task 3: Gate Step 2 → Step 3 Transition

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx:754-766` (`canGoNext` useMemo)

- [ ] **Step 1: Compute `incompleteToolConfig` flag**

Add a `useMemo` right before `canGoNext` (before line 754):

```typescript
const incompleteToolConfig = useMemo(
  () => hasIncompleteToolConfig(monitorChecks, monitorConfigs, selectedNodesWithMonitors),
  [monitorChecks, monitorConfigs, selectedNodesWithMonitors],
);
```

- [ ] **Step 2: Update `canGoNext` to use the flag**

Replace the Step 2 case in `canGoNext` (lines 758-760):

```typescript
// Before:
case 2:
  if (configTab === 'ai-prompt') return aiPrompt.trim().length > 0;
  return totalMonitorCount > 0;

// After:
case 2:
  if (configTab === 'ai-prompt') return aiPrompt.trim().length > 0;
  if (totalMonitorCount === 0) return false;
  return !incompleteToolConfig;
```

Add `incompleteToolConfig` to the `canGoNext` dependency array (line 766):

```typescript
}, [step, selectedNodeIds, configTab, aiPrompt, totalMonitorCount, planName, incompleteToolConfig]);
```

- [ ] **Step 3: Add inline warning message when blocked**

In the Step 2 footer area, add a warning message. Find the Next button section in the footer (around line 1446-1462). Add a warning inline right before the Next button, inside the footer div:

```tsx
{/* In the footer, before the Next button (around line 1446) */}
{step === 2 && incompleteToolConfig && (
  <span className="text-[11px] text-amber-400 mr-3">
    Configure all selected tool monitors before proceeding
  </span>
)}
```

- [ ] **Step 4: Verify gating works**

Run the dev server. Open MultiMonitorModal, select a tool node (e.g. Fivetran), check SYNC_LAG. Confirm the Next button is disabled and the warning message appears. (The config form doesn't exist yet — that's Task 4.)

- [ ] **Step 5: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: gate Step 2 → Step 3 on tool monitor config completion"
```

---

### Task 4: Expand MonitorCard with Inline Config Form

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx:222-283` (`MonitorCard` component)

This is the core change. When a checked tool monitor has required config fields, the card expands to show an inline form.

- [ ] **Step 1: Add props to MonitorCard**

Update the `MonitorCard` props to accept config state and a flag for whether it's a tool monitor:

```typescript
function MonitorCard({
  mon,
  checked,
  onToggle,
  showTarget,
  isToolNode,
  config,
  onConfigChange,
}: {
  mon: MonitorOption;
  checked: boolean;
  onToggle: () => void;
  showTarget?: boolean;
  isToolNode?: boolean;
  config?: Record<string, any>;
  onConfigChange?: (key: string, value: any) => void;
}) {
```

- [ ] **Step 2: Render inline config form inside MonitorCard**

After the closing `</div>` of the content section (after line 279, before the closing `</button>`), add the config form. Also change the outer element from `<button>` to `<div>` since it will contain interactive form elements:

Replace the entire `MonitorCard` function body with:

```tsx
function MonitorCard({
  mon,
  checked,
  onToggle,
  showTarget,
  isToolNode,
  config,
  onConfigChange,
}: {
  mon: MonitorOption;
  checked: boolean;
  onToggle: () => void;
  showTarget?: boolean;
  isToolNode?: boolean;
  config?: Record<string, any>;
  onConfigChange?: (key: string, value: any) => void;
}) {
  const def = getMonitorDefinition(mon.key);
  const label = def?.label || mon.key;
  const description = def?.description || mon.reason;

  // Required config fields for tool monitors
  const requiredFields = isToolNode && def
    ? def.config_schema.filter((f) => f.required)
    : [];
  const showConfig = checked && requiredFields.length > 0;

  // Check if all required fields are filled
  const isConfigComplete = requiredFields.length === 0 || requiredFields.every(
    (f) => config?.[f.key] || config?.[f.key] === 0,
  );

  return (
    <div className={cn(
      'rounded-lg border transition-all overflow-hidden',
      checked
        ? (MONITOR_COLORS[mon.key] || 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/30')
        : 'border-[var(--border)] text-[var(--text)] hover:border-[var(--muted)]/50',
    )}>
      <button
        onClick={onToggle}
        className="flex items-start gap-3 p-3 text-left transition-all w-full"
      >
        {/* Checkbox */}
        <div
          className={cn(
            'w-4 h-4 mt-0.5 rounded-sm border flex items-center justify-center shrink-0 transition-colors',
            checked
              ? 'bg-current border-current'
              : 'border-[var(--muted)]/40',
          )}
        >
          {checked && (
            <svg className="w-2.5 h-2.5" fill="none" stroke="var(--bg)" strokeWidth={4} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
        </div>
        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium">{label}</span>
            {checked && isToolNode && requiredFields.length > 0 && (
              <span className={cn(
                'px-1.5 py-0.5 rounded text-[9px] font-medium',
                isConfigComplete
                  ? 'bg-emerald-500/15 text-emerald-400'
                  : 'bg-amber-500/15 text-amber-400',
              )}>
                {isConfigComplete ? 'Configured' : 'Requires config'}
              </span>
            )}
          </div>
          {description && (
            <p className={cn(
              'text-[11px] mt-0.5 leading-relaxed',
              checked ? 'opacity-80' : 'text-[var(--muted)]',
            )}>
              {description}
            </p>
          )}
          {showTarget && mon.targetFqn && (
            <p className="text-[10px] font-mono mt-1 opacity-60 truncate">
              {mon.targetFqn}
            </p>
          )}
        </div>
      </button>

      {/* Inline config form for tool monitors */}
      {showConfig && (
        <div
          className="px-3 pb-3 pt-1 border-t border-[var(--border)] bg-[var(--surface)]/50 space-y-2"
          onClick={(e) => e.stopPropagation()}
        >
          {requiredFields.map((field) => (
            <div key={field.key}>
              <label className="block text-[10px] text-[var(--muted)] uppercase tracking-wide mb-1">
                {field.label}
              </label>
              {field.type === 'select' ? (
                <select
                  value={config?.[field.key] ?? field.default_value ?? ''}
                  onChange={(e) => onConfigChange?.(field.key, e.target.value)}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value="">{field.placeholder || 'Select...'}</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              ) : field.type === 'multi-text' || field.type === 'textarea' ? (
                <textarea
                  value={config?.[field.key] ?? ''}
                  onChange={(e) => onConfigChange?.(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  rows={3}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] placeholder:text-[var(--muted)]/40 focus:outline-none focus:border-[var(--accent)] resize-none"
                />
              ) : field.type === 'checkbox' ? (
                <label className="flex items-center gap-2 text-[12px] text-[var(--text)]">
                  <input
                    type="checkbox"
                    checked={!!config?.[field.key]}
                    onChange={(e) => onConfigChange?.(field.key, e.target.checked)}
                    className="rounded border-[var(--border)]"
                  />
                  {field.placeholder || field.label}
                </label>
              ) : (
                <input
                  type={field.type === 'number' ? 'number' : 'text'}
                  value={config?.[field.key] ?? ''}
                  onChange={(e) => onConfigChange?.(
                    field.key,
                    field.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value,
                  )}
                  placeholder={field.placeholder}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] placeholder:text-[var(--muted)]/40 focus:outline-none focus:border-[var(--accent)]"
                />
              )}
              {field.help_text && (
                <p className="text-[10px] text-[var(--muted)] mt-0.5">{field.help_text}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Update MonitorCard call sites to pass new props**

In the monitor cards rendering section (around line 1249-1254), update the `MonitorCard` usage:

```tsx
// Before (around line 1249-1254):
<MonitorCard
  mon={mon}
  checked={checked}
  onToggle={() => toggleMonitor(mon.targetNodeId, mon.key)}
  showTarget={!!meta.subNodeIds}
/>

// After:
<MonitorCard
  mon={mon}
  checked={checked}
  onToggle={() => toggleMonitor(mon.targetNodeId, mon.key)}
  showTarget={!!meta.subNodeIds}
  isToolNode={!!meta.subNodeIds?.length}
  config={monitorConfigs[checkKey]}
  onConfigChange={(fieldKey, value) =>
    setMonitorConfigs((prev) => ({
      ...prev,
      [checkKey]: { ...(prev[checkKey] || {}), [fieldKey]: value },
    }))
  }
/>
```

- [ ] **Step 4: Seed default values when a tool monitor is checked**

Update the `toggleMonitor` callback (around line 681-685) to seed defaults when checking a tool monitor:

```typescript
const toggleMonitor = useCallback((nodeId: string, monitorKey: string) => {
  const key = `${nodeId}::${monitorKey}`;

  setMonitorChecks((prev) => {
    const willBeChecked = !prev[key];

    // Seed default values for tool monitors when checking
    if (willBeChecked && TOOL_ONLY_MONITOR_KEYS.has(monitorKey)) {
      const def = getMonitorDefinition(monitorKey);
      if (def) {
        const defaults: Record<string, any> = {};
        for (const field of def.config_schema) {
          if (field.default_value !== undefined) {
            defaults[field.key] = field.default_value;
          }
        }
        if (Object.keys(defaults).length > 0) {
          setMonitorConfigs((p) => ({
            ...p,
            [key]: { ...(p[key] || {}), ...defaults },
          }));
        }
      }
    }

    return { ...prev, [key]: willBeChecked };
  });
  setActivePreset(null);
}, []);
```

- [ ] **Step 5: Verify the full flow**

Run the dev server:
1. Open MultiMonitorModal from the task page
2. Switch to "Pipeline Overview" view in Step 1, select a tool node (e.g. Fivetran)
3. In Step 2, check SYNC_LAG — confirm the card expands with a `connector_id` input
4. Leave the input empty — confirm Next button is disabled with the warning message
5. Fill in the connector_id — confirm the badge changes to green "Configured" and Next is enabled
6. Proceed to Step 3 — confirm the monitor appears in the summary
7. Repeat from the lineage page tool details "Add Monitor" button

- [ ] **Step 6: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: inline config form for tool monitors in MonitorCard"
```

---

### Task 5: Add "Configured" Badge in Step 3 Summary

**Files:**
- Modify: `components/schedule/MultiMonitorModal.tsx:1418-1425` (Step 3 summary section)

- [ ] **Step 1: Add a tool monitor summary section in Step 3**

After the existing summary badge section (line 1425, after the `activePreset` badge), add a tool monitor config summary:

```tsx
{/* Tool monitor config summary */}
{configTab === 'presets' && (() => {
  const toolMons = selectedNodesWithMonitors.flatMap(({ meta, monitors }) => {
    if (!meta.subNodeIds?.length) return [];
    return monitors
      .filter((m) => TOOL_ONLY_MONITOR_KEYS.has(m.key) && monitorChecks[`${m.targetNodeId}::${m.key}`])
      .map((m) => {
        const def = getMonitorDefinition(m.key);
        return { mon: m, label: def?.label || m.key, nodeName: meta.name };
      });
  });
  if (toolMons.length === 0) return null;
  return (
    <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]">
      <p className="text-[11px] text-[var(--muted)] mb-2">Tool Monitors</p>
      <div className="space-y-1.5">
        {toolMons.map(({ mon, label, nodeName }) => (
          <div key={`${mon.targetNodeId}::${mon.key}`} className="flex items-center gap-2">
            <span className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-emerald-500/15 text-emerald-400">
              Configured
            </span>
            <span className="text-[12px] text-[var(--text)]">{label}</span>
            <span className="text-[10px] text-[var(--muted)]">on {nodeName}</span>
          </div>
        ))}
      </div>
    </div>
  );
})()}
```

- [ ] **Step 2: Verify Step 3 shows the configured badges**

Run the dev server. Create a tool monitor with config filled in. Proceed to Step 3. Confirm the "Tool Monitors" section shows each configured monitor with a green "Configured" badge.

- [ ] **Step 3: Commit**

```bash
git add components/schedule/MultiMonitorModal.tsx
git commit -m "feat: show configured tool monitor badges in Step 3 summary"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Full end-to-end test — task page entry**

1. Open the task/schedule page
2. Click "New Monitor"
3. Switch to Pipeline Overview, select a Fivetran tool node
4. In Step 2, check SYNC_LAG → card expands, connector_id input shown
5. Leave empty → Next is disabled, warning shown
6. Fill connector_id → badge turns green, Next enabled
7. Step 3 → "Tool Monitors" section with green "Configured" badge
8. Create the monitor → verify it succeeds

- [ ] **Step 2: Full end-to-end test — lineage tool details entry**

1. Open the lineage page
2. Click a tool node (e.g. Fivetran) in pipeline overview
3. Click "Add Monitor" in the tool details panel
4. Confirm the same config-gated flow works

- [ ] **Step 3: Verify data asset monitors are unaffected**

1. Open MultiMonitorModal, select a data asset (table/view)
2. Check FRESHNESS, VOLUME, SCHEMA_CHANGE
3. Confirm no config expansion occurs, Next is enabled immediately

- [ ] **Step 4: Verify unchecking clears the gate**

1. Check a tool monitor (SYNC_LAG) without filling config → Next disabled
2. Uncheck it → Next should re-enable (assuming other monitors are checked)
3. Re-check it → config values should still be preserved from before
