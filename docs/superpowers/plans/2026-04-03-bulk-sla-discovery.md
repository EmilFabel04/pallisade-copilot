# Bulk SLA Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Discover from data" button to the SLA Editor Panel that runs auto-discovery on all selected nodes simultaneously, shows a per-node results summary, and applies each node's discovered SLA individually.

**Architecture:** New bulk discovery endpoint in FastAPI reuses existing `discover_sla_profile()` per node with adapter connection reuse. Next.js proxy forwards to it. SLAEditorPanel gains bulk discovery state that toggles between the manual form and a results summary table. A new `onApplyBulkDiscovery` callback on the lineage page handles per-node assign calls.

**Tech Stack:** Python/FastAPI, TypeScript/React/Next.js

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `scanner/api/routers/discovery.py` | Modify | Add `POST /api/v1/discovery/bulk` endpoint |
| `app/api/nodes/sla/discover-bulk/route.ts` | Create | Next.js proxy to bulk endpoint (120s timeout) |
| `components/lineage/SLAEditorPanel.tsx` | Modify | Add bulk discovery button, loading state, results summary, "Apply All" |
| `app/(dashboard)/dashboard/lineage/page.tsx` | Modify | Add `onApplyBulkDiscovery` handler, pass to SLAEditorPanel |

---

### Task 1: Add bulk discovery endpoint to FastAPI

**Files:**
- Modify: `scanner/api/routers/discovery.py`

- [ ] **Step 1: Add request/response models**

In `scanner/api/routers/discovery.py`, add after the existing `NodeDiscoveryResponse` class (around line 41):

```python
class BulkDiscoveryRequest(BaseModel):
    """Request body for bulk SLA discovery."""
    nodeIds: list[str] = Field(..., description="Engine stable_ids of the nodes", max_length=50)
    stackId: Optional[str] = None


class BulkDiscoveryResponse(BaseModel):
    """Response with discovery results for multiple nodes."""
    results: list[NodeDiscoveryResponse]
```

- [ ] **Step 2: Add bulk endpoint**

Add after the existing `/discovery/node` endpoint (around line 198):

```python
@router.post("/discovery/bulk", response_model=BulkDiscoveryResponse)
async def discover_bulk_sla(request: BulkDiscoveryRequest):
    """
    Run on-demand SLA discovery for multiple lineage nodes.

    Groups nodes by platform to reuse adapter connections. Each node is
    discovered independently — results are per-node, not merged.
    """
    from .lineage import _get_engine_store, _engine_tool_configs_map

    stack_id = request.stackId
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(
            status_code=404,
            detail="No lineage graph found for this pipeline. Run an investigation first.",
        )

    try:
        from lineage.sla_discovery import _find_warehouse_ancestor, discover_sla_profile
    except ImportError:
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor, discover_sla_profile

    cache_key = stack_id or "default"
    tool_configs = _engine_tool_configs_map.get(cache_key, {})

    # Group nodes by platform to reuse adapter connections
    platform_nodes: Dict[str, list] = {}  # platform -> [(node, ancestor)]
    skipped_results: list[NodeDiscoveryResponse] = []

    for node_id in request.nodeIds:
        node = store.graph.nodes.get(node_id)
        if not node:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node_id,
                unsupported=True,
                skipped_reason=f"Node '{node_id}' not found in lineage graph",
            ))
            continue

        ancestor = _find_warehouse_ancestor(node, store.graph)
        if ancestor is None:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason="No warehouse ancestor found",
            ))
            continue

        platform = (ancestor.platform or "").lower()
        if platform not in _WAREHOUSE_PLATFORMS:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason=f"Platform '{platform}' not supported",
            ))
            continue

        if platform not in tool_configs:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason=f"No cached config for '{platform}'. Re-run investigation.",
            ))
            continue

        platform_nodes.setdefault(platform, []).append((node, ancestor))

    # Discover per-platform with adapter reuse
    discovered_results: list[NodeDiscoveryResponse] = []

    for platform, node_pairs in platform_nodes.items():
        adapter = _create_warehouse_adapter(platform, tool_configs[platform])
        if not adapter:
            for node, _ in node_pairs:
                discovered_results.append(NodeDiscoveryResponse(
                    node_fqn=node.fqn,
                    unsupported=True,
                    skipped_reason=f"Could not create adapter for '{platform}'",
                ))
            continue

        try:
            adapter.connect()
        except Exception as e:
            logger.warning("[SLA Discovery] Bulk: failed to connect %s: %s", platform, e)
            for node, _ in node_pairs:
                discovered_results.append(NodeDiscoveryResponse(
                    node_fqn=node.fqn,
                    unsupported=True,
                    skipped_reason=f"Failed to connect to {platform}",
                ))
            continue

        try:
            for node, ancestor in node_pairs:
                try:
                    result = await discover_sla_profile(node, store.graph, adapter)
                    discovered_results.append(NodeDiscoveryResponse(
                        node_fqn=result.node_fqn,
                        warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
                        freshness=result.freshness,
                        volume=result.volume,
                        quality=result.quality,
                        schema_profile=result.schema,
                        uniqueness=result.uniqueness,
                        unsupported=result.unsupported,
                        skipped_reason=result.skipped_reason,
                    ))
                except Exception as e:
                    logger.error("[SLA Discovery] Bulk: node %s failed: %s", node.fqn, e)
                    discovered_results.append(NodeDiscoveryResponse(
                        node_fqn=node.fqn,
                        unsupported=True,
                        skipped_reason=f"Discovery failed: {e}",
                    ))
        finally:
            try:
                adapter.disconnect()
            except Exception:
                pass

    return BulkDiscoveryResponse(results=[*skipped_results, *discovered_results])
```

- [ ] **Step 3: Verify endpoint loads**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && python3 -c "from api.routers.discovery import router; print('OK')" 2>&1`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scanner/api/routers/discovery.py
git commit -m "feat(sla-discovery): add POST /api/v1/discovery/bulk endpoint"
```

---

### Task 2: Add Next.js proxy for bulk discovery

**Files:**
- Create: `app/api/nodes/sla/discover-bulk/route.ts`

- [ ] **Step 1: Create the proxy route**

Create `app/api/nodes/sla/discover-bulk/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// POST /api/nodes/sla/discover-bulk — Bulk SLA discovery for multiple nodes
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { nodeIds, stackId } = body;

    if (!nodeIds || !Array.isArray(nodeIds) || nodeIds.length === 0) {
      return NextResponse.json({ error: 'nodeIds required' }, { status: 400 });
    }

    if (nodeIds.length > 50) {
      return NextResponse.json({ error: 'Max 50 nodes per request' }, { status: 400 });
    }

    const res = await fetch(`${SCANNER_API_URL}/api/v1/discovery/bulk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodeIds, stackId }),
      signal: AbortSignal.timeout(120000),
    });

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }

    const errorData = await res.json().catch(() => ({}));
    return NextResponse.json(
      { error: errorData.detail || 'Bulk discovery failed' },
      { status: res.status || 500 }
    );
  } catch (error: any) {
    if (error?.name === 'TimeoutError') {
      return NextResponse.json({ error: 'Scanner timeout' }, { status: 504 });
    }
    console.error('[Discovery] Bulk error:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/nodes/sla/discover-bulk/route.ts
git commit -m "feat(sla-discovery): add Next.js proxy for bulk discovery"
```

---

### Task 3: Add bulk discovery UI to SLAEditorPanel

**Files:**
- Modify: `components/lineage/SLAEditorPanel.tsx`

This is the largest task. It adds the "Discover from data" button, loading state, results summary table, and "Apply All" button.

- [ ] **Step 1: Add new props and state**

In `SLAEditorPanel.tsx`, update the `SLAEditorPanelProps` interface (around line 19) to add the new callback:

```typescript
interface SLAEditorPanelProps {
  selectedNodeIds: Set<string>;
  allNodes: UnifiedLineageNode[];
  allEdges: UnifiedLineageEdge[];
  stackId: string;
  nodeSLAs: Map<string, EffectiveSLAPolicy>;
  saving?: boolean;
  discoveryDefaults?: Record<string, any> | null;
  onApply: (request: SLAAssignRequest, scope: ApplyScope) => void;
  onApplyBulkDiscovery?: (entries: Array<{ nodeFqn: string; overrides: Record<string, any> }>) => void;
  onRemoveSLA?: (nodeFqns: string[]) => void;
  onClose: () => void;
  onClearSelection: () => void;
}
```

Update the destructuring (around line 148) to include the new prop:

```typescript
export function SLAEditorPanel({
  selectedNodeIds,
  allNodes,
  allEdges,
  stackId,
  nodeSLAs,
  saving,
  discoveryDefaults,
  onApply,
  onApplyBulkDiscovery,
  onRemoveSLA,
  onClose,
  onClearSelection,
}: SLAEditorPanelProps) {
```

Add new state after the existing state declarations (after line 163):

```typescript
  const [bulkDiscoveryState, setBulkDiscoveryState] = useState<'idle' | 'loading' | 'results'>('idle');
  const [bulkResults, setBulkResults] = useState<Array<{
    node_fqn: string;
    unsupported?: boolean;
    skipped_reason?: string;
    freshness?: any;
    volume?: any;
    quality?: any;
    schema_profile?: any;
    uniqueness?: any;
  }>>([]);
```

Add a reset effect — when selection changes, go back to idle (add after the existing `useEffect` for `selectedNodeIds` around line 191):

```typescript
  useEffect(() => {
    setBulkDiscoveryState('idle');
    setBulkResults([]);
  }, [selectedNodeIds]);
```

- [ ] **Step 2: Add the discover handler**

Add after the existing `handleApply` callback (around line 263):

```typescript
  const handleBulkDiscover = useCallback(async () => {
    setBulkDiscoveryState('loading');
    try {
      // Map selected node IDs to engine IDs (strip lineage- prefix)
      const engineIds = Array.from(selectedNodeIds).map((id) => id.replace(/^lineage-/, ''));
      const res = await fetch('/api/nodes/sla/discover-bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nodeIds: engineIds, stackId }),
      });
      if (res.ok) {
        const data = await res.json();
        setBulkResults(data.results || []);
        setBulkDiscoveryState('results');
      } else {
        setBulkDiscoveryState('idle');
      }
    } catch {
      setBulkDiscoveryState('idle');
    }
  }, [selectedNodeIds, stackId]);

  const handleApplyAll = useCallback(() => {
    if (!onApplyBulkDiscovery) return;
    const entries: Array<{ nodeFqn: string; overrides: Record<string, any> }> = [];
    for (const r of bulkResults) {
      if (r.unsupported) continue;
      const overrides: Record<string, any> = {};
      if (r.freshness) overrides.freshnessConfig = r.freshness;
      if (r.volume) overrides.volumeConfig = r.volume;
      if (r.quality) overrides.qualityConfig = r.quality;
      if (r.schema_profile) overrides.schemaConfig = r.schema_profile;
      if (r.uniqueness) overrides.uniquenessConfig = r.uniqueness;
      entries.push({ nodeFqn: r.node_fqn, overrides });
    }
    onApplyBulkDiscovery(entries);
  }, [bulkResults, onApplyBulkDiscovery]);

  const discoveredCount = bulkResults.filter((r) => !r.unsupported).length;
  const skippedCount = bulkResults.filter((r) => r.unsupported).length;
```

- [ ] **Step 3: Add "Discover from data" button to the header area**

In `SLAEditorPanel.tsx`, find the closing `</div>` of the header section (after the current policy display, around line 317). Add the discover button just before the `{/* Source badge */}` comment:

```tsx
      {/* Bulk discover button */}
      {bulkDiscoveryState === 'idle' && !hasDiscovery && selectedNodeIds.size >= 1 && (
        <div className="mx-4 mt-3">
          <button
            onClick={handleBulkDiscover}
            className="w-full px-3 py-2 text-[12px] font-medium rounded-lg border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 transition-colors flex items-center justify-center gap-2"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            Discover from data ({selectedNodeIds.size} node{selectedNodeIds.size !== 1 ? 's' : ''})
          </button>
        </div>
      )}
```

- [ ] **Step 4: Add loading state**

After the discover button block, add:

```tsx
      {/* Bulk discovery loading */}
      {bulkDiscoveryState === 'loading' && (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
          <div className="w-8 h-8 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin mb-3" />
          <p className="text-[13px] text-[var(--text)]">Discovering {selectedNodeIds.size} nodes...</p>
          <p className="text-[11px] text-[var(--muted)] mt-1">Querying warehouse metadata</p>
        </div>
      )}
```

- [ ] **Step 5: Add results summary view**

After the loading block, add the results view. This replaces the scrollable form content when results are available:

```tsx
      {/* Bulk discovery results */}
      {bulkDiscoveryState === 'results' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {/* Summary header */}
          <div className="flex items-center justify-between">
            <p className="text-[12px] font-medium text-[var(--text)]">
              {discoveredCount} discovered, {skippedCount} skipped
            </p>
            <button
              onClick={() => { setBulkDiscoveryState('idle'); setBulkResults([]); }}
              className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] underline"
            >
              Dismiss
            </button>
          </div>

          {/* Per-node results */}
          {bulkResults.map((r) => {
            const shortName = r.node_fqn.split('.').pop() || r.node_fqn;
            const dims = [
              r.freshness ? 'F' : null,
              r.volume ? 'V' : null,
              r.quality ? 'Q' : null,
              r.schema_profile ? 'S' : null,
              r.uniqueness && !r.uniqueness.skipped ? 'U' : null,
            ].filter(Boolean);

            return (
              <div
                key={r.node_fqn}
                className={`p-2.5 rounded-lg border ${r.unsupported ? 'border-[var(--subtle-border)] opacity-50' : 'border-cyan-500/20 bg-cyan-500/5'}`}
              >
                <p className="text-[11px] font-mono text-[var(--text)] truncate" title={r.node_fqn}>
                  {shortName}
                </p>
                {r.unsupported ? (
                  <p className="text-[10px] text-[var(--text-faint)] mt-0.5">{r.skipped_reason}</p>
                ) : (
                  <div className="flex gap-1 mt-1">
                    {dims.map((d) => (
                      <span key={d} className="px-1.5 py-0.5 text-[9px] font-medium rounded bg-cyan-500/20 text-cyan-400">
                        {d}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
```

- [ ] **Step 6: Modify the scrollable content to hide when results are showing**

Find the `{/* Scrollable content */}` section (around line 329). Wrap the entire scrollable content div and the footer in a condition so they only show when NOT in results mode. The scrollable content currently starts with:

```tsx
      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
```

And the footer starts with:

```tsx
      {/* Footer (sticky) */}
      <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0 space-y-2">
```

Wrap both sections — the scrollable content AND the footer — so they only render when `bulkDiscoveryState !== 'results'`:

Add `{bulkDiscoveryState !== 'results' && bulkDiscoveryState !== 'loading' && (` before `{/* Scrollable content */}` and close with `)}` after the footer's closing `</div>`.

Then add a separate footer for the results view, after the results summary `</div>` but before the closing `</div>` of the component:

```tsx
      {/* Bulk apply footer */}
      {bulkDiscoveryState === 'results' && discoveredCount > 0 && (
        <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0">
          {applied ? (
            <div className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-green-600/90 text-white text-center flex items-center justify-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Data SLA applied to {discoveredCount} nodes
            </div>
          ) : (
            <button
              onClick={handleApplyAll}
              disabled={saving}
              className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? 'Applying...' : `Apply All (${discoveredCount} nodes)`}
            </button>
          )}
        </div>
      )}
```

- [ ] **Step 7: Commit**

```bash
git add components/lineage/SLAEditorPanel.tsx
git commit -m "feat(sla-discovery): add bulk discovery UI to SLAEditorPanel"
```

---

### Task 4: Add `onApplyBulkDiscovery` handler in lineage page

**Files:**
- Modify: `app/(dashboard)/dashboard/lineage/page.tsx`

- [ ] **Step 1: Add the handler and pass it to SLAEditorPanel**

In `app/(dashboard)/dashboard/lineage/page.tsx`, find the `<SLAEditorPanel` render (around line 2071). Add the `onApplyBulkDiscovery` prop after the existing `onApply` prop (around line 2170, before `onClose`):

```tsx
            onApplyBulkDiscovery={async (entries) => {
              setPolicySaving(true);
              try {
                const results = await Promise.allSettled(
                  entries.map((entry) =>
                    fetch('/api/schedule/policies/assign', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        profileId: `auto-discovered-${entry.nodeFqn}`,
                        assignmentType: 'auto_discovered',
                        nodeFqns: [entry.nodeFqn],
                        overrides: entry.overrides,
                        stackId,
                        _profileName: 'Discovered from Data',
                      }),
                    })
                  )
                );

                const succeeded = results.filter((r) => r.status === 'fulfilled' && (r.value as Response).ok).length;
                const failed = entries.length - succeeded;

                if (failed === 0) {
                  toast.success(`SLA applied to ${succeeded} node${succeeded !== 1 ? 's' : ''}`);
                } else {
                  toast.success(`Applied to ${succeeded} of ${entries.length} nodes (${failed} failed)`);
                }

                // Re-fetch resolved policies
                try {
                  const nodesPayload = (lineageData?.nodes || []).map((n) => ({
                    fqn: n.fullName || n.name,
                    domain: n.layer?.toLowerCase() || 'warehouse',
                    criticality: n.criticality?.toLowerCase() || 'medium',
                  }));
                  const resolveRes = await fetch('/api/schedule/policies/resolve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nodes: nodesPayload, stackId }),
                  });
                  if (resolveRes.ok) {
                    const resolveData = await resolveRes.json();
                    const policies = resolveData.policies || {};
                    const map = new Map<string, EffectiveSLAPolicy>();
                    for (const [fqn, pol] of Object.entries(policies)) {
                      if ((pol as any).status !== 'none') {
                        map.set(fqn, pol as EffectiveSLAPolicy);
                      }
                    }
                    setNodeSLAs(map);
                  }
                } catch {
                  // Non-critical
                }
              } catch (err) {
                console.error('[Policy] Bulk assign error:', err);
                toast.error('Failed to apply SLAs');
              } finally {
                setPolicySaving(false);
              }
            }}
```

- [ ] **Step 2: Commit**

```bash
git add app/(dashboard)/dashboard/lineage/page.tsx
git commit -m "feat(sla-discovery): add onApplyBulkDiscovery handler to lineage page"
```

---

### Task 5: Verify end-to-end

**Files:** None (verification only)

- [ ] **Step 1: Run Python import check**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && python3 -c "from api.routers.discovery import router; print('OK')"`
Expected: `OK`

- [ ] **Step 2: Run all SLA discovery tests**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && python3 -m pytest tests/test_sla_discovery.py -v`
Expected: 36 passed

- [ ] **Step 3: Run TypeScript type check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | grep -v vitest | grep -v node_modules`
Expected: No new errors

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "fix: address any type/test fixups from bulk discovery"
```
