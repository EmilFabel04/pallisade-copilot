import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';

/**
 * GET /api/pipeline/[stackId]/lineage/engine
 *
 * Proxies to the FastAPI engine endpoints:
 *   ?action=stats        → /api/v1/lineage/engine/stats
 *   ?action=upstream&id= → /api/v1/lineage/engine/upstream/{id}
 *   ?action=downstream&id= → /api/v1/lineage/engine/downstream/{id}
 *   ?action=explain-edge&id= → /api/v1/lineage/engine/explain-edge/{id}
 *   ?action=blast-radius&id= → /api/v1/lineage/engine/blast-radius/{id}
 *   ?action=control-plane&id= → /api/v1/lineage/engine/control-plane/{id} (optional id for specific DAG)
 *   ?action=control-plane-overview → /api/v1/lineage/engine/control-plane-overview (tool-sequence graph)
 *   ?action=cross-links&id= → /api/v1/lineage/engine/cross-links/{id}
 *   ?action=run-history&id= → /api/v1/lineage/engine/run-history/{id}
 *   ?action=view-pipeline-overview → /api/v1/lineage/engine/views/pipeline-overview
 *   ?action=view-lane-pipeline-overview → /api/v1/lineage/engine/views/lane-pipeline-overview
 *   ?action=view-data-plane → /api/v1/lineage/engine/views/data-plane
 *
 * Passes through filter params: level, system, domain, kind, min_confidence, depth, plane
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;
    const { searchParams } = new URL(request.url);
    const action = searchParams.get('action') || 'stats';
    const assetId = searchParams.get('id') || '';

    // Build query params to forward (always include stack_id for pipeline isolation)
    const forwardParams = new URLSearchParams();
    forwardParams.set('stack_id', stackId);
    for (const key of ['level', 'system', 'domain', 'kind', 'min_confidence', 'depth', 'fmt', 'plane', 'direction', 'limit', 'existing_fqns', 'q']) {
      const val = searchParams.get(key);
      if (val) forwardParams.set(key, val);
    }
    const qs = `?${forwardParams.toString()}`;

    let endpoint: string;
    switch (action) {
      case 'stats':
        endpoint = `/api/v1/lineage/engine/stats${qs}`;
        break;
      case 'upstream':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/upstream/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'downstream':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/downstream/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'blast-radius':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/blast-radius/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'recommend-monitors':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/recommend-monitors/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'explain-edge':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/explain-edge/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'export':
        endpoint = `/api/v1/lineage/engine/export${qs}`;
        break;
      case 'control-plane':
        endpoint = assetId
          ? `/api/v1/lineage/engine/control-plane/${encodeURIComponent(assetId)}${qs}`
          : `/api/v1/lineage/engine/control-plane${qs}`;
        break;
      case 'control-plane-overview':
        endpoint = `/api/v1/lineage/engine/control-plane-overview${qs}`;
        break;
      case 'cross-links':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/cross-links/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'run-history':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/run-history/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'search':
        endpoint = `/api/v1/lineage/engine/search${qs}`;
        break;
      case 'auto-anchor':
        endpoint = `/api/v1/lineage/engine/auto-anchor${qs}`;
        break;
      case 'view-pipeline-overview':
        endpoint = `/api/v1/lineage/engine/views/pipeline-overview${qs}`;
        break;
      case 'view-lane-pipeline-overview':
        endpoint = `/api/v1/lineage/engine/views/lane-pipeline-overview${qs}`;
        break;
      case 'view-data-plane':
        endpoint = `/api/v1/lineage/engine/views/data-plane${qs}`;
        break;
      case 'view-tool-details':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/views/tool-details/${encodeURIComponent(assetId)}${qs}`;
        break;
      case 'data-plane-neighbors':
        if (!assetId) return NextResponse.json({ error: 'Missing id param' }, { status: 400 });
        endpoint = `/api/v1/lineage/engine/data-plane/neighbors/${encodeURIComponent(assetId)}?${forwardParams.toString()}`;
        break;
      case 'reconcile-diagnostics':
        endpoint = `/api/v1/lineage/engine/reconcile/diagnostics`;
        break;
      case 'run-status':
        if (!assetId) return NextResponse.json({ error: 'Missing id param for run-status' }, { status: 400 });
        endpoint = `/api/v1/lineage/runs/${encodeURIComponent(assetId)}/status`;
        break;
      case 'runs-current':
        endpoint = `/api/v1/lineage/runs/current`;
        break;
      case 'runs-list':
        endpoint = `/api/v1/lineage/runs${qs}`;
        break;
      case 'run-view':
        if (!assetId) return NextResponse.json({ error: 'Missing id param for run-view' }, { status: 400 });
        const viewType = searchParams.get('viewType') || 'data_plane';
        endpoint = `/api/v1/lineage/runs/${encodeURIComponent(assetId)}/views/${encodeURIComponent(viewType)}`;
        break;
      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }

    let res = await scannerClient.fetch(session, endpoint, {
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(30000),
    });

    let data = await res.json();

    // For view actions: if engine returned empty (no graph in memory after restart),
    // try restoring from the DB snapshot and retry once.
    // Triggers on: (a) empty nodes array, or (b) "No graph loaded" error from tool-details.
    const needsGraph = action.startsWith('view-') || action === 'stats' || action === 'search' || action === 'auto-anchor';
    const hasNodeField = data && 'nodes' in data;
    const isEmpty = hasNodeField && (!data.nodes || (Array.isArray(data.nodes) && data.nodes.length === 0));
    const isNoGraphError = data?.error === 'No graph loaded';
    const isEmptySearch = action === 'search' && data?.results && Array.isArray(data.results) && data.results.length === 0;
    const isNullAnchor = action === 'auto-anchor' && data?.anchor === null;
    if (needsGraph && (isEmpty || isNoGraphError || isEmptySearch || isNullAnchor)) {
      const organizationId = (session.user as any).organizationId;
      if (organizationId) {
        const snapshot = await prisma.lineageSnapshot.findFirst({
          where: { organizationId, graphData: { not: null as any } },
          orderBy: { createdAt: 'desc' },
          select: { id: true, graphData: true },
        });

        if (snapshot?.graphData) {
          console.log(`[ENGINE PROXY] Restoring graph from snapshot ${snapshot.id}`);
          const restoreRes = await scannerClient.fetch(session, `/api/v1/lineage/engine/restore?stack_id=${stackId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graph_data: snapshot.graphData }),
            signal: AbortSignal.timeout(10000),
          });

          if (restoreRes.ok) {
            // Retry the original request now that the graph is loaded
            res = await scannerClient.fetch(session, endpoint, {
              headers: { 'Content-Type': 'application/json' },
              signal: AbortSignal.timeout(30000),
            });
            data = await res.json();
          }
        }
      }
    }

    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[ENGINE PROXY] Error:', error);
    return NextResponse.json(
      { error: 'Failed to proxy to engine API' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/pipeline/[stackId]/lineage/engine
 *
 * Proxies to FastAPI engine POST endpoints:
 *   ?action=build (default) → /api/v1/lineage/engine/build
 *   ?action=reconcile       → /api/v1/lineage/engine/reconcile
 *   ?action=reconcile-apply → /api/v1/lineage/engine/reconcile/apply
 *   ?action=save-snapshot   → Persist engine graph to LineageSnapshot.graphData
 *
 * Body: action-specific payload
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { stackId } = await params;
    const { searchParams } = new URL(request.url);
    const action = searchParams.get('action') || 'build';

    // save-snapshot: Persist engine graph to DB for restart recovery
    if (action === 'save-snapshot') {
      if (!organizationId) {
        return NextResponse.json({ error: 'No organization found' }, { status: 400 });
      }

      // Fetch the serialized graph from FastAPI
      const snapshotRes = await scannerClient.fetch(session, `/api/v1/lineage/engine/snapshot?stack_id=${stackId}`, {
        signal: AbortSignal.timeout(10000),
      });
      if (!snapshotRes.ok) {
        return NextResponse.json({ error: 'Failed to fetch engine snapshot' }, { status: 502 });
      }
      const snapshotData = await snapshotRes.json();
      if (!snapshotData.has_graph || !snapshotData.graph_data) {
        return NextResponse.json({ error: 'No graph to persist' }, { status: 404 });
      }

      // Get integration IDs from pipeline stack
      const stack = await prisma.pipelineStack.findFirst({
        where: { id: stackId, organizationId },
        include: { nodes: { select: { integrationId: true, toolType: true } } },
      });
      const toolTypes = stack?.nodes.map(n => n.toolType).filter(Boolean).join(',') || 'unknown';

      // Find or create a snapshot record and update with graphData
      let snapshot = await prisma.lineageSnapshot.findFirst({
        where: { organizationId },
        orderBy: { createdAt: 'desc' },
      });

      if (snapshot) {
        await prisma.lineageSnapshot.update({
          where: { id: snapshot.id },
          data: {
            graphData: snapshotData.graph_data,
            nodeCount: snapshotData.graph_data.stats?.node_count || 0,
            edgeCount: snapshotData.graph_data.stats?.edge_count || 0,
            source: 'llm_extractor',
          },
        });
      } else {
        snapshot = await prisma.lineageSnapshot.create({
          data: {
            organizationId,
            source: 'llm_extractor',
            dialect: toolTypes,
            status: 'ready',
            nodeCount: snapshotData.graph_data.stats?.node_count || 0,
            edgeCount: snapshotData.graph_data.stats?.edge_count || 0,
            rootCount: 0,
            leafCount: 0,
            graphData: snapshotData.graph_data,
          },
        });
      }

      console.log(`[ENGINE] Persisted engine graph to snapshot ${snapshot.id}`);
      return NextResponse.json({ success: true, snapshotId: snapshot.id });
    }

    const body = await request.json();

    let endpoint: string;
    let timeout = 120000;

    const stackQs = `?stack_id=${stackId}`;
    switch (action) {
      case 'build':
        endpoint = `/api/v1/lineage/engine/build${stackQs}`;
        break;
      case 'reconcile':
        endpoint = `/api/v1/lineage/engine/reconcile${stackQs}`;
        timeout = 180000; // LLM call may take longer
        break;
      case 'reconcile-apply':
        endpoint = `/api/v1/lineage/engine/reconcile/apply${stackQs}`;
        break;
      default:
        return NextResponse.json({ error: `Unknown POST action: ${action}` }, { status: 400 });
    }

    const res = await scannerClient.fetch(session, endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeout),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[ENGINE PROXY] POST error:', error);
    return NextResponse.json(
      { error: 'Failed to proxy to engine API' },
      { status: 500 }
    );
  }
}
