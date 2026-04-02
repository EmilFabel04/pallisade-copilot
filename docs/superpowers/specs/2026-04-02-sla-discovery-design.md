# SLA Discovery — Embedded in Lineage Scanning

**Date:** 2026-04-02
**Status:** Draft

---

## Overview

When Pallisade builds or refreshes lineage for an asset, it traverses the asset's upstream lineage to find the nearest warehouse table ancestor, queries that warehouse's historical metadata, and computes suggested SLA threshold values. These are written as `PolicyAssignment` records with `assignmentType: 'auto_discovered'`, slotting into the existing resolver chain below user-defined and imported-dbt profiles. The user sees suggestions inline in the Data SLA section of the detail panel and can accept, edit, or dismiss them.

## Goals

- Solve the cold-start problem — new users have calibrated thresholds from day one without manual input.
- Never overwrite thresholds the user has already defined.
- Keep the logic simple — statistics, not ML.

## Non-Goals

- Real-time or continuous profiling.
- Suggesting monitors (that comes later).
- Anything beyond four core categories: freshness, volume, quality, schema.

---

## 1. Storage — PolicyAssignment with `auto_discovered` Source

Auto-discovered profiles use the existing `PolicyAssignment` + `PolicyProfile` tables. No schema changes to `LineageNode`.

### How it works

1. Discovery computes suggested config values (freshness, volume, quality, schema).
2. It upserts a `PolicyProfile` with `name: "Auto-discovered"`, `isBuiltIn: true`, and the computed config blobs.
3. It creates a `PolicyAssignment` with `assignmentType: 'auto_discovered'`, `nodeFqn: <fqn>`, pointing at the profile.

### Resolver chain update

The existing resolver chain becomes (field-by-field, first non-null wins):

1. `direct_override` — per-node overrides JSON
2. `direct_profile` — user-assigned PolicyProfile
3. `imported_dbt` — dbt-imported profiles
4. `branch` — nearest ancestor's branch policy
5. **`auto_discovered`** — computed from warehouse history *(new)*
6. `criticality_default` — matches node domain + criticality
7. `domain_default` — matches node domain
8. `builtin` — hardcoded defaults

Because auto-discovered sits below user-defined/imported-dbt, the resolver naturally skips discovery results when a higher-precedence assignment exists. No special "skip if user-defined" logic needed.

### Per-node profiles

Each node gets its own `PolicyProfile` with its own computed thresholds. These are not shared across nodes — the profile name includes the node FQN for traceability (e.g., `"Auto-discovered: db.schema.orders"`). If discovery re-runs, it updates the existing profile and assignment in place.

---

## 2. When It Runs

### During lineage scan

SLA discovery runs as a step inside `CrossToolLineageOrchestrator.extract_all()`, after the node graph is built and depths are computed, but before the scan completes. It iterates over nodes that don't already have a `direct_profile`, `direct_override`, or `imported_dbt` assignment.

### On-demand

A user can click "Discover from data" in the Data SLA section on a node that has no profile (or only an auto-discovered one). This calls the on-demand route, which returns suggested values for confirmation before writing.

### Skip conditions

Discovery skips a node entirely if:
- The node already has a `direct_profile`, `direct_override`, or `imported_dbt` assignment.
- The node has no warehouse ancestor in its upstream lineage (flagged `discovery_unsupported`).
- The warehouse adapter doesn't support the required historical queries.

---

## 3. Warehouse Ancestor Resolution

Not all nodes are warehouse tables. dbt models, BI dashboards, orchestration DAGs — none of these have row counts or schema history directly. Discovery handles this by traversing upstream lineage.

### Algorithm

```
find_warehouse_ancestor(node, graph):
    if node is a warehouse table (platform_domain == WAREHOUSE, node_type in [table, view]):
        return node
    
    visited = set()
    queue = [upstream neighbors of node]
    
    BFS upstream:
        for each candidate:
            if candidate is a warehouse table:
                return candidate
            add candidate's upstream neighbors to queue
    
    return None  # discovery_unsupported
```

The search returns the **nearest** warehouse table ancestor. If multiple exist at the same depth, pick the first one found (deterministic by node ID sort).

### Attribution

The discovered profile is attributed to the **originating node** (the one we started from), not the warehouse ancestor. The ancestor is just the data source for the statistical queries. This means a dbt model gets its own auto-discovered profile based on the warehouse table it reads from.

### `discovery_unsupported`

If no warehouse ancestor exists anywhere upstream, the node is flagged as `discovery_unsupported`. This is not an error — it means the node's data characteristics can't be inferred from warehouse metadata. The UI shows this as a neutral state: "SLA discovery is not available for this node — no upstream warehouse table found."

---

## 4. What It Computes Per Category

All computations query the warehouse adapter for the node's nearest warehouse ancestor. The lookback window is 30 days.

### Freshness

- Query: table modification timestamps from `INFORMATION_SCHEMA` over the last 30 days.
- Adapter method: `get_table_freshness()` extended to return a list of timestamps, or a new `get_freshness_history(table, days=30)` method.
- Computation: mean hours between updates and p95 interval.
- Output:
  - `freshnessConfig.enabled`: `true`
  - `freshnessConfig.maxHours`: p95 rounded up to nearest whole hour, plus 20% buffer, minimum 1.
  - `freshnessConfig.warningHours`: mean rounded up to nearest whole hour.

### Volume

- Query: row count history. BigQuery: `INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE`. Snowflake: `ACCOUNT_USAGE.TABLE_STORAGE_METRICS`. Postgres/Redshift: not available (single-point only, skip volume discovery).
- Adapter method: new `get_row_count_history(table, days=30)` returning `List[{date, row_count}]`.
- Computation: mean and standard deviation of daily row counts.
- Output:
  - `volumeConfig.enabled`: `true`
  - `volumeConfig.minRows`: `max(0, mean - 2 * stddev)`, rounded to integer.
  - `volumeConfig.maxRows`: `mean + 2 * stddev`, rounded to integer.
  - `volumeConfig.growthRateThreshold`: if the table shows consistent day-over-day growth, set to `mean_daily_growth_rate * 2`. Otherwise `null`.
- Edge case: if fewer than 7 data points exist in the window, skip volume discovery for this node (insufficient history).

### Quality

- Query: null rates and duplicate rates. Uses the existing `get_column_stats()` adapter method which already returns null counts and distinct counts per column.
- Computation: per-column null rate (`null_count / total_rows`), per-column duplicate rate (`1 - distinct_count / total_rows`). Compute mean and stddev across columns for each metric. Threshold is set to the cross-column mean plus two standard deviations.
- Output:
  - `qualityConfig.enabled`: `true`
  - `qualityConfig.maxNullRate`: `min(0.5, mean_null_rate + 2 * stddev_null_rate)`. Capped at 50%.
  - `qualityConfig.maxDuplicateRate`: `min(0.5, mean_dup_rate + 2 * stddev_dup_rate)`. Capped at 50%.
- Note: quality stats are point-in-time (current snapshot), not historical. The cross-column stddev buffer accounts for variation between columns.

### Schema

- Query: schema change history. The existing `supports_schema_changes` adapter capability. For BigQuery, `INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` with `INFORMATION_SCHEMA.SCHEMATA` history. For Snowflake, `ACCOUNT_USAGE.COLUMNS` history.
- Adapter method: new `get_schema_change_history(table, days=30)` returning `List[{date, change_type, column_name}]` where `change_type` is `added` or `removed`.
- Computation:
  - If no schema changes in 30 days: `strictness: 'strict'`, `allowEvolution: false`.
  - If only additions occurred: `strictness: 'warn'`, `allowEvolution: true`.
  - If removals occurred: `strictness: 'warn'`, `allowEvolution: true` (the table schema is actively changing).
- Output:
  - `schemaConfig.enabled`: `true`
  - `schemaConfig.strictness`: as computed above.
  - `schemaConfig.allowEvolution`: as computed above.

---

## 5. Module Structure

### New file: `scanner/lineage/sla_discovery.py`

Single module, one public entry point:

```python
@dataclass
class DiscoveryResult:
    node_fqn: str
    warehouse_ancestor_fqn: str | None
    freshness: FreshnessConfig | None
    volume: VolumeConfig | None
    quality: QualityConfig | None
    schema: SchemaConfig | None
    unsupported: bool  # True if no warehouse ancestor found
    skipped_reason: str | None  # "user_defined", "no_warehouse_ancestor", "insufficient_history"

async def discover_sla_profile(
    node: LineageNode,
    graph: LineageGraph,
    adapter: BaseAdapter,
) -> DiscoveryResult:
    """Compute suggested SLA thresholds for a single node."""

async def discover_sla_profiles_bulk(
    nodes: List[LineageNode],
    graph: LineageGraph,
    adapter_registry: Dict[str, BaseAdapter],
) -> List[DiscoveryResult]:
    """Batch discovery for all eligible nodes after a lineage scan."""
```

Internal functions (private):
- `_find_warehouse_ancestor(node, graph) -> LineageNode | None`
- `_compute_freshness(adapter, table_fqn) -> FreshnessConfig | None`
- `_compute_volume(adapter, table_fqn) -> VolumeConfig | None`
- `_compute_quality(adapter, table_fqn) -> QualityConfig | None`
- `_compute_schema(adapter, table_fqn) -> SchemaConfig | None`

### Adapter extensions

Three new methods on `BaseAdapter` (with `NotImplementedError` defaults):

- `get_freshness_history(table: str, days: int = 30) -> List[Dict]` — returns `[{timestamp: datetime}]`
- `get_row_count_history(table: str, days: int = 30) -> List[Dict]` — returns `[{date: date, row_count: int}]`
- `get_schema_change_history(table: str, days: int = 30) -> List[Dict]` — returns `[{date: date, change_type: str, column_name: str}]`

Implemented in BigQuery and Snowflake adapters first. Postgres/Redshift get freshness and quality only (no row count history or schema change history available via standard metadata views).

---

## 6. Integration with Lineage Scan

### Hook point in orchestrator

In `CrossToolLineageOrchestrator.extract_all()`, after `graph.compute_depths()`:

```python
# After graph is built and depths computed
if self.discovery_enabled:
    from scanner.lineage.sla_discovery import discover_sla_profiles_bulk
    discovery_results = await discover_sla_profiles_bulk(
        nodes=list(graph.nodes.values()),
        graph=graph,
        adapter_registry=self._adapter_registry,
    )
    result.discovery_results = discovery_results
```

The Next.js API that receives the scan results then writes the `PolicyProfile` + `PolicyAssignment` records for each successful discovery.

### Performance

Discovery adds warehouse queries. To bound the cost:
- Batch queries where possible (one `INFORMATION_SCHEMA` query per dataset, not per table).
- Cap at 100 nodes per scan. If more nodes are eligible, prioritize by criticality (critical first), then by upstream depth (sources first).
- Total discovery timeout: 60 seconds. If exceeded, return whatever results completed.

---

## 7. Resolver Changes

### Python: `scanner/monitors/policy_resolver.py`

Add `auto_discovered` as a new layer in `resolve_policy()`, between `branch` and `criticality_default`:

```python
# Layer 5: Auto-discovered (from warehouse history)
auto_discovered = [
    a for a in assignments
    if a.get("assignmentType") == "auto_discovered"
    and a.get("nodeFqn") == node_fqn
]
if auto_discovered:
    ad = auto_discovered[0]
    profile = profiles.get(ad.get("profileId", ""), {})
    pid = ad.get("profileId")
    pname = profile.get("name")
    profile_fields = _extract_all_fields_from_profile(profile)
    if profile_fields:
        layers.append(("auto_discovered", profile_fields, pid, pname))
```

### TypeScript: `app/api/schedule/policies/resolve/route.ts`

Add `auto_discovered` assignment type to the local fallback indexing (alongside direct, criticality_default, domain_default).

### TypeScript: `types/sla.ts`

Update `SLAAssignmentType`:
```typescript
export type SLAAssignmentType = 'direct' | 'branch' | 'auto_discovered' | 'domain_default' | 'criticality_default';
```

Update `EffectiveSLAPolicy.source` comment:
```typescript
source: string;  // direct_override | direct_profile | imported_dbt | branch | auto_discovered | criticality_default | domain_default | builtin
```

---

## 8. API Route

### `POST /api/nodes/[nodeId]/sla/discover`

On-demand discovery for a single node. Does NOT write — returns the suggested profile for frontend confirmation.

**Request:** empty body (node ID in URL).

**Response:**
```json
{
  "status": "ok",
  "result": {
    "nodeFqn": "project.dataset.orders",
    "warehouseAncestorFqn": "project.dataset.orders",
    "freshness": { "enabled": true, "maxHours": 6, "warningHours": 3 },
    "volume": { "enabled": true, "minRows": 8000, "maxRows": 52000 },
    "quality": { "enabled": true, "maxNullRate": 0.05, "maxDuplicateRate": 0.02 },
    "schema": { "enabled": true, "strictness": "strict", "allowEvolution": false }
  }
}
```

**Error responses:**
- `404` — node not found.
- `422` with `{ "reason": "no_warehouse_ancestor" }` — node has no upstream warehouse table.
- `422` with `{ "reason": "user_defined" }` — node already has a user-defined profile (frontend shouldn't have offered the button, but guard anyway).

After the user confirms, the frontend calls the existing `POST /api/schedule/policies/assign` with `assignmentType: 'auto_discovered'`.

---

## 9. Frontend Changes

All changes are in the existing Data SLA section of `DataAssetDetailPanel`.

### Empty state (no profile)

Currently shows an "Edit SLA" button that opens the SLA editor. Add a second action:

```
┌─────────────────────────────────────────┐
│  Data SLA                               │
│  No SLA profile assigned                │
│                                         │
│  [Discover from data]  [Assign manually]│
└─────────────────────────────────────────┘
```

"Discover from data" calls `POST /api/nodes/[id]/sla/discover`. While loading, shows a spinner with "Analyzing warehouse history...". On success, shows the suggested values in a confirmation UI:

```
┌─────────────────────────────────────────┐
│  Suggested SLA Profile                  │
│  Based on 30 days of warehouse history  │
│                                         │
│  Freshness     max 6h, warn 3h         │
│  Volume        8,000 – 52,000 rows     │
│  Quality       null ≤5%, dup ≤2%       │
│  Schema        strict, no evolution     │
│                                         │
│  [Accept]  [Edit & Accept]  [Dismiss]   │
└─────────────────────────────────────────┘
```

- **Accept**: writes the auto-discovered assignment via `POST /api/schedule/policies/assign`.
- **Edit & Accept**: opens the SLA editor pre-filled with the suggested values. On save, writes as `direct_profile` (user-defined).
- **Dismiss**: closes the confirmation, does nothing.

### Auto-discovered state

If the node's effective policy has `source: 'auto_discovered'`, show a subtle banner above the SLA values:

```
┌─────────────────────────────────────────┐
│  Data SLA                    [Edit]     │
│  ┌─────────────────────────────────┐    │
│  │ ℹ Auto-discovered from data.   │    │
│  │   Edit to make user-defined.   │    │
│  └─────────────────────────────────┘    │
│                                         │
│  Freshness     max 6h, warn 3h         │
│  Volume        8,000 – 52,000 rows     │
│  ...                                    │
└─────────────────────────────────────────┘
```

When the user clicks Edit and saves any change, the assignment is written as `direct_profile`, which takes precedence over `auto_discovered` in the resolver. The auto-discovered assignment remains but is shadowed.

### Discovery-unsupported state

If the node was flagged `discovery_unsupported` (or the on-demand route returns `no_warehouse_ancestor`):

```
┌─────────────────────────────────────────┐
│  Data SLA                               │
│  No SLA profile assigned                │
│  Discovery not available — no upstream  │
│  warehouse table found.                 │
│                                         │
│  [Assign manually]                      │
└─────────────────────────────────────────┘
```

### SlaProfileModal update

Add `auto_discovered` to the `SOURCE_LABELS` in `SlaProfileModal.tsx`:
```typescript
auto_discovered: { label: 'Auto-discovered', color: 'text-cyan-400', bg: 'bg-cyan-500/15' },
```

---

## 10. Build Order

1. Write `scanner/lineage/sla_discovery.py` with the four statistical functions and `_find_warehouse_ancestor`.
2. Add `get_freshness_history`, `get_row_count_history`, `get_schema_change_history` to `BaseAdapter` with `NotImplementedError` defaults. Implement in BigQuery and Snowflake adapters.
3. Update the resolver chain: add `auto_discovered` layer in Python `policy_resolver.py` and TypeScript `resolve/route.ts`. Update types.
4. Hook discovery into `CrossToolLineageOrchestrator.extract_all()`.
5. Add `POST /api/nodes/[nodeId]/sla/discover` route.
6. Update `DataAssetDetailPanel` — empty state with "Discover from data", confirmation UI, auto-discovered banner, discovery-unsupported state.
7. Add `auto_discovered` to `SlaProfileModal` source labels.
8. Test: run a lineage scan on a warehouse with history, verify profiles are written, verify user-defined nodes are skipped, verify on-demand discovery returns correct suggestions.
