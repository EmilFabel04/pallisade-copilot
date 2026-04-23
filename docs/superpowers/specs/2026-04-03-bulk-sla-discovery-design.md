# Bulk SLA Discovery from SLA Editor Mode

## Summary

Add a "Discover from data" button to the SLA Editor Panel so users can run auto-discovery on all selected nodes simultaneously. Each node gets its own discovered SLA applied individually. A summary table shows per-node results before applying.

## Current State

- "Discover from data" only exists in `DataAssetDetailPanel` (single-node detail view, hidden when SLA mode is active)
- SLA mode supports multi-select but has no discovery trigger
- Backend has `discover_sla_profiles_bulk()` in `sla_discovery.py` but no API endpoint exposes it
- Single-node endpoint: `POST /api/v1/discovery/node`

## Design

### User Flow

1. User enters Data SLA mode, multi-selects nodes (shift+click or plain click)
2. "Discover from data" button appears in `SLAEditorPanel` header (visible when 1+ nodes selected, discovery not yet run)
3. Click fires one request to `POST /api/v1/discovery/bulk` with all selected node IDs
4. Panel shows loading state: spinner + "Discovering N nodes..."
5. Results return → panel switches to **summary table view**:
   - Discovered nodes: name + dimension badges (freshness, volume, quality, schema, uniqueness)
   - Skipped nodes: name + reason (greyed out)
6. User clicks "Apply All" → each discovered node gets its own SLA assigned individually
7. Green checkmark, done. Skipped nodes remain unassigned.

### Backend

#### New endpoint: `POST /api/v1/discovery/bulk`

**File:** `scanner/api/routers/discovery.py`

Request model:
```python
class BulkDiscoveryRequest(BaseModel):
    nodeIds: list[str]  # Engine stable_ids
    stackId: Optional[str] = None
```

Response model:
```python
class BulkDiscoveryResponse(BaseModel):
    results: list[NodeDiscoveryResponse]  # Reuses existing response model
```

Logic:
1. Get engine graph from `_get_engine_store(stack_id)`
2. Look up each node by stable_id, skip missing nodes
3. For each node, find warehouse ancestor → determine platform → get adapter from cached tool configs
4. Group nodes by platform to reuse adapter connections (connect once per platform, not per node)
5. Call `discover_sla_profile()` for each node sequentially (warehouse queries are the bottleneck, not Python)
6. Collect results, disconnect adapters, return

Adapter connection reuse: create one adapter per platform, connect it once, use for all nodes on that platform, disconnect at the end. This avoids N connection setups.

Cap: limit to 50 nodes per request to prevent timeouts.

#### Next.js proxy: `POST /api/nodes/sla/discover-bulk`

**File:** `app/api/nodes/sla/discover-bulk/route.ts`

- Proxies to `POST /api/v1/discovery/bulk` on the FastAPI backend
- 120s timeout (bulk can take longer than single-node's 60s)
- Passes `stackId` from request body

### Frontend

#### SLAEditorPanel changes

**File:** `components/lineage/SLAEditorPanel.tsx`

New state:
```typescript
const [bulkDiscoveryState, setBulkDiscoveryState] = useState<'idle' | 'loading' | 'results'>('idle');
const [bulkResults, setBulkResults] = useState<Map<string, any>>(new Map());
```

New prop:
```typescript
stackId: string;  // Already passed, needed for the API call
```

**"Discover from data" button:**
- Location: below the node count / current policy info, above the form sections
- Visible when: `bulkDiscoveryState === 'idle'` and `selectedNodeIds.size >= 1`
- Styled: cyan text, matches existing discovery button style
- On click: fires POST to `/api/nodes/sla/discover-bulk` with `{ nodeIds: [...selectedNodeIds], stackId }`

**Loading state** (`bulkDiscoveryState === 'loading'`):
- Replaces the form sections area
- Shows: spinner + "Discovering {N} nodes..."
- No cancel button (keeps it simple)

**Results state** (`bulkDiscoveryState === 'results'`):
- Replaces the form sections area with a summary table
- Each row shows:
  - Node name (truncated, monospace)
  - Status: discovered dimension count OR skipped reason
  - Discovered rows: small badges for each dimension found (F, V, Q, S, U)
  - Skipped rows: greyed out with reason text
- Below the table:
  - "Apply All ({N} nodes)" button — applies discovered SLAs
  - "Dismiss" link — returns to idle state, clears results
- Scope selector hidden during results view (each node gets its own SLA)

**"Apply All" logic:**
- For each discovered result (where `unsupported !== true`):
  - Build an `SLAAssignRequest` with the node's FQN and discovered values as overrides
  - Call `onApply(request, 'selected')` — but we need to handle this differently since we're applying per-node
- Since the existing `onApply` handles a batch of FQNs, we can call it once per discovered node, OR we modify onApply to accept per-node overrides

**Recommended approach for Apply All:**
- New callback prop: `onApplyBulkDiscovery: (entries: Array<{ nodeFqn: string; overrides: Record<string, any> }>) => void`
- The lineage page.tsx implements this by iterating entries and calling the assign API once per node
- This keeps SLAEditorPanel stateless about the assign mechanism

#### Lineage page.tsx changes

**File:** `app/(dashboard)/dashboard/lineage/page.tsx`

- Add `onApplyBulkDiscovery` handler that:
  1. Sets `policySaving = true`
  2. For each entry, POSTs to `/api/schedule/policies/assign` with that node's overrides
  3. Uses `Promise.allSettled()` to handle partial failures
  4. Toasts: "Applied SLA to {succeeded} of {total} nodes" (or "Applied SLA to {N} nodes" if all succeed)
  5. Re-fetches policies via `/api/schedule/policies/resolve`
  6. Sets `policySaving = false`

- Pass the handler to `SLAEditorPanel`

#### DOMAIN_SLA_SECTIONS

No changes needed — the bulk discovery button is not gated by domain sections.

### What stays the same

- Single-node discovery from `DataAssetDetailPanel` — unchanged
- `SLAEditorPanel` manual form — still works when discovery not used
- Existing `onApply` for manual SLA assignment — unchanged
- Backend `discover_sla_profiles_bulk()` — reused as-is (or nearly)
- Assign/resolve API — unchanged

### Error handling

- If the bulk endpoint returns a non-200, toast error and return to idle state
- If some nodes fail within the bulk response (unsupported/skipped), show them in the summary table — user sees what worked and what didn't
- If "Apply All" partially fails (some assign calls fail), toast with count: "Applied to {N} of {M} nodes, {F} failed"
- 120s timeout on the Next.js proxy to handle large batches

### Constraints

- Max 50 nodes per bulk request (backend cap)
- No progress streaming — one request, one response
- Sequential discovery per node on the backend (warehouse queries are the bottleneck)
- Each node gets its own independent SLA — no merging of results
