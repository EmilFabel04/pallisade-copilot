# Tool Monitor Config Gate

## Problem

Pipeline overview tool monitors (SYNC_LAG, FAILED_SYNCS, DAG_LAST_RUN, COST_ANOMALY, etc.) require configuration — connector IDs, DAG IDs, threshold values — before they can execute. The `config_schema` in `monitor-catalog.ts` already marks these fields as `required: true`, but the UI does not enforce this. Users can create tool monitors without filling in required config, resulting in monitors that silently fail to run.

This only applies to monitors on **pipeline overview tool nodes** (identified by `subNodeIds.length > 0` in node metadata), not to data asset monitors.

## Scope

- **In scope**: Config gating for tool monitors in `MultiMonitorModal` (used from both the task/schedule page and the lineage tool details "Add Monitor" button)
- **Out of scope**: Data asset monitors (FRESHNESS, VOLUME, SCHEMA_CHANGE, etc.), policy system, data contracts

## Affected Files

| File | Change |
|------|--------|
| `components/schedule/MultiMonitorModal.tsx` | Expand `MonitorCard` for tool monitors, add config validation to `canGoNext`, show config status in Step 3 summary |
| `types/monitor-catalog.ts` | No changes — already has `config_schema` with `required` fields |
| `components/lineage/pipeline-overview/InspectorPanel.tsx` | No changes — `onCreateSingleMonitor` callback already builds `NodeMeta` with `subNodeIds` and `domain` |
| `app/(dashboard)/dashboard/lineage/page.tsx` | No changes — already passes tool node metadata via `preselectedNodeMeta` to `MultiMonitorModal` |

## Design

### 1. MonitorCard Inline Config (Step 2)

When a user checks a tool monitor (`TOOL_ONLY_MONITOR_KEYS` + node has `subNodeIds`), the `MonitorCard` component expands below the description to show an inline config form.

**Behavior:**
- On check: card expands to reveal required `config_schema` fields from the monitor's `MonitorDefinition`
- On uncheck: card collapses, config values are preserved in state (so re-checking restores them)
- Field types rendered based on `ConfigField.type`: `text` → text input, `number` → number input, `select` → dropdown, `multi-text` → textarea (one value per line, used by `log_paths` and `cert_paths`), `textarea` → textarea, `checkbox` → checkbox
- `placeholder` and `help_text` from `ConfigField` are shown on the inputs
- Non-required fields and fields marked `advanced: true` are hidden behind an "Advanced" toggle within the expanded card
- An unconfigured checked tool monitor shows a small amber "Requires configuration" badge on the card

**State:**
- Config values stored in existing `monitorConfigs` state: `Record<string, Record<string, any>>` keyed by `${targetNodeId}::${monitorKey}`
- `monitorConfigs` must be reset when the modal opens — add `setMonitorConfigs({})` to the reset `useEffect` alongside the existing `setMonitorChecks({})` call
- When a tool monitor card expands, seed `monitorConfigs` with any `default_value` from its `config_schema` fields so defaults are pre-filled
- No new state variables needed

**Tool monitor identification:**
```typescript
const isToolMonitor = (meta: NodeMeta, monitorKey: string) =>
  !!meta.subNodeIds?.length && TOOL_ONLY_MONITOR_KEYS.has(monitorKey);
```

### 2. Step 2 Validation Gate

The `canGoNext` check for Step 2 adds a new condition: all checked tool monitors must have their required config fields filled.

**Helper function:**
```typescript
function hasIncompleteToolConfig(
  monitorChecks: Record<string, boolean>,
  monitorConfigs: Record<string, Record<string, any>>,
  selectedNodesWithMonitors: Array<{ meta: NodeMeta; monitors: MonitorOption[] }>,
): boolean {
  for (const { meta, monitors } of selectedNodesWithMonitors) {
    if (!meta.subNodeIds?.length) continue; // skip data nodes
    for (const mon of monitors) {
      const checkKey = `${mon.targetNodeId}::${mon.key}`;
      if (!monitorChecks[checkKey]) continue; // skip unchecked
      if (!TOOL_ONLY_MONITOR_KEYS.has(mon.key)) continue;

      const def = getMonitorDefinition(mon.key);
      if (!def) continue;

      const config = monitorConfigs[checkKey] || {};
      const missingRequired = def.config_schema
        .filter(f => f.required)
        .some(f => !config[f.key] && config[f.key] !== 0);

      if (missingRequired) return true;
    }
  }
  return false;
}
```

**canGoNext update (Step 2):**
```typescript
case 2:
  if (configTab === 'ai-prompt') return aiPrompt.trim().length > 0;
  if (totalMonitorCount === 0) return false;
  return !hasIncompleteToolConfig(monitorChecks, monitorConfigs, selectedNodesWithMonitors);
```

**Dependency array:** The `canGoNext` `useMemo` dependency array must include `monitorConfigs` and `selectedNodesWithMonitors` in addition to the existing deps.

**Next button:** When blocked by incomplete config, show an inline warning below the monitor list: "Configure all selected tool monitors before proceeding". Avoid tooltip-only on the disabled button (hard to discover).

### 3. Step 3 Summary Badges

On the finalize step, each tool monitor in the summary list shows a small green "Configured" badge next to its name, confirming the config values are set. This is informational only — validation already passed in Step 2.

### 4. Lineage Tool Details Entry Point

No changes needed. The lineage page's monitor creation flow works as follows:
1. `InspectorPanel` receives `onCreateSingleMonitor` callback as a prop
2. Its `NodeInspector` calls `onCreateSingleMonitor` with an `AssetPrefill` containing the tool node info
3. The lineage page (`app/(dashboard)/dashboard/lineage/page.tsx`) handles this by building `NodeMeta` (with `subNodeIds` and `domain`) and opening `MultiMonitorModal` with `preselectedNodeMeta`

The config-gating behavior activates automatically via the shared `isToolMonitor` check since the `NodeMeta` includes `subNodeIds`.

## Monitor Keys Affected

All monitors in `TOOL_ONLY_MONITOR_KEYS` that have required config fields:

| Monitor Key | Required Config | Domain |
|-------------|----------------|--------|
| SYNC_LAG | `connector_id` | ingestion |
| FAILED_SYNCS | `connector_id` | ingestion |
| CONNECTOR_SCHEMA_DRIFT | `connector_id` | ingestion |
| DAG_LAST_RUN | `dag_id` | orchestration |
| DAG_SCHEDULE_LAG | `dag_id` | orchestration |
| TASK_FAILURE_RATE | `dag_id` | orchestration |
| QUERY_PERFORMANCE | *(no required fields, has defaults)* | warehouse |
| COST_ANOMALY | *(no required fields)* | warehouse |
| STORAGE_GROWTH | *(no required fields)* | warehouse |
| SERVER_HEALTH | *(no config fields)* | infrastructure |
| CERTIFICATE | *(no required fields, all advanced)* | infrastructure |
| LOG_ANALYSIS | `log_paths` (multi-text) | infrastructure |

Monitors without required fields (QUERY_PERFORMANCE, COST_ANOMALY, STORAGE_GROWTH, SERVER_HEALTH, CERTIFICATE) will not show the expanded config form — they work as today.

**Note on dbt monitors:** DBT_TEST_FAILURES, DBT_MODEL_FRESHNESS, and DBT_SOURCE_FRESHNESS have required `job_id` fields but are intentionally excluded from `TOOL_ONLY_MONITOR_KEYS` because their targets (models, sources) appear as data-like nodes in the lineage graph, not as tool service nodes. Their config gating is out of scope for this change.

## Non-Goals

- No new "policy" system for tools — tool monitors are operational/cost monitors, not data SLAs
- No `PAUSED` / `PENDING_CONFIG` monitor state — config is enforced at creation time
- No changes to the backend monitor execution — monitors created through this flow will always have valid config
