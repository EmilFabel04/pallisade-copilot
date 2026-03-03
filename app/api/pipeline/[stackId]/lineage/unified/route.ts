import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import type { PipelineLayer } from '@/components/pipeline/types';
import type {
  UnifiedLineageNode,
  UnifiedLineageEdge,
  UnifiedNodeCategory,
  UnifiedLineageResponse,
  LinePlane,
} from '@/components/lineage/types';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

/**
 * Fetch the engine graph (nodes + edges with confidence/evidence).
 * Returns null if engine is not available or has no data.
 */
async function fetchEngineGraph(stackId: string, plane?: string): Promise<{
  nodes: any[];
  edges: any[];
} | null> {
  try {
    const params = new URLSearchParams({ stack_id: stackId });
    if (plane) params.set('plane', plane);
    const url = `${SCANNER_API_URL}/api/v1/lineage/engine/graph?${params}`;
    const res = await fetch(url, {
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.nodes?.length) return null;
    return data;
  } catch {
    return null;
  }
}

/**
 * Try to restore the engine graph from a persisted LineageSnapshot.
 * Called when the in-memory engine graph is empty (e.g., after server restart).
 * Returns the restored engine graph, or null if no snapshot exists.
 */
async function tryRestoreEngineFromSnapshot(
  organizationId: string,
  stackId: string,
): Promise<{ nodes: any[]; edges: any[] } | null> {
  try {
    // Find the latest snapshot with graphData (org-scoped, no integrationId filter
    // because save-snapshot stores with integrationId=null)
    const snapshot = await prisma.lineageSnapshot.findFirst({
      where: {
        organizationId,
        graphData: { not: null as any },
      },
      orderBy: { createdAt: 'desc' },
      select: { id: true, graphData: true },
    });

    if (!snapshot?.graphData) return null;

    console.log(`[UNIFIED LINEAGE] Restoring engine graph from snapshot ${snapshot.id}`);

    // Send the graph data to FastAPI to restore the in-memory store
    const restoreRes = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/restore?stack_id=${stackId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ graph_data: snapshot.graphData }),
      signal: AbortSignal.timeout(10000),
    });

    if (!restoreRes.ok) return null;
    const restoreData = await restoreRes.json();
    if (!restoreData.success) return null;

    console.log(`[UNIFIED LINEAGE] Engine graph restored: ${restoreData.nodes} nodes, ${restoreData.edges} edges`);

    // Now fetch the engine graph normally (it's in memory again)
    return fetchEngineGraph(stackId);
  } catch (e) {
    console.warn('[UNIFIED LINEAGE] Failed to restore engine from snapshot:', e);
    return null;
  }
}

/**
 * Fetch engine coverage stats.
 */
async function fetchEngineStats(stackId: string) {
  try {
    const res = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/stats?stack_id=${stackId}`, {
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return undefined;
    const raw = await res.json();
    if (!raw.total_nodes && !raw.total_edges) return undefined;
    return {
      totalNodes: raw.total_nodes || 0,
      totalEdges: raw.total_edges || 0,
      edgesByLevel: raw.edges_by_level || {},
      coverageTable: raw.coverage_table || 0,
      coverageColumn: raw.coverage_column || 0,
      highConfidencePct: raw.high_confidence_pct || 0,
      mediumConfidencePct: raw.medium_confidence_pct || 0,
      lowConfidencePct: raw.low_confidence_pct || 0,
    };
  } catch {
    return undefined;
  }
}

/**
 * Convert an engine node to a UnifiedLineageNode.
 */
function engineNodeToUnified(
  eNode: any,
  findingsByFqn: Map<string, any[]>,
): UnifiedLineageNode {
  const nodeType = eNode.node_type?.toLowerCase() || 'table';
  let category: UnifiedNodeCategory = 'table';
  let layer: PipelineLayer = 'WAREHOUSE';

  // Check if this node is a dbt model/seed/snapshot (survives resolver dedup).
  // After resolver merges dbt + warehouse nodes, node_type becomes view/table,
  // but dbt_resource_type is preserved in raw_metadata through the merge.
  const dbtResourceType = eNode.dbt_resource_type;
  const isDbtModel = dbtResourceType === 'model' || dbtResourceType === 'seed' || dbtResourceType === 'snapshot';

  if (nodeType === 'dag') {
    category = 'dag';
    layer = 'ORCHESTRATION';
  } else if (nodeType === 'task') {
    category = 'task';
    layer = 'ORCHESTRATION';
  } else if (nodeType === 'workflow') {
    category = 'workflow';
    layer = 'ORCHESTRATION';
  } else if (nodeType === 'model' || isDbtModel) {
    // Nodes that are dbt models (including merged warehouse+dbt nodes)
    category = 'model';
    layer = 'TRANSFORMATION';
  } else if (nodeType === 'notebook') {
    category = 'notebook';
    layer = 'TRANSFORMATION';
  } else if (nodeType === 'view' || nodeType === 'materialized_view') {
    category = 'view';
    layer = 'WAREHOUSE';
  } else if (nodeType === 'source') {
    // dbt sources with warehouse platform_domain are physical tables (post-dedup)
    if (eNode.platform_domain === 'warehouse') {
      category = 'table';
      layer = 'WAREHOUSE';
    } else {
      category = 'source';
      layer = 'INGESTION';
    }
  } else if (nodeType === 'connector') {
    category = 'connector';
    layer = 'INGESTION';
  } else if (nodeType === 'dashboard') {
    category = 'dashboard';
    layer = 'REPORTING';
  } else if (nodeType === 'report') {
    category = 'report';
    layer = 'REPORTING';
  } else if (nodeType === 'workbook') {
    category = 'workbook';
    layer = 'REPORTING';
  } else if (nodeType === 'dataset' && eNode.platform_domain === 'bi') {
    category = 'dataset';
    layer = 'REPORTING';
  } else if (nodeType === 'question') {
    category = 'question';
    layer = 'REPORTING';
  } else if (nodeType === 'file') {
    category = 'file';
    layer = 'INGESTION';
  } else if (nodeType === 'monitor') {
    category = 'test';
    layer = 'WAREHOUSE';
  } else if (nodeType === 'table' && eNode.platform_domain === 'ingestion') {
    // Ingestion tables (e.g., Fivetran synced tables) — green table nodes
    category = 'table';
    layer = 'INGESTION';
  } else if (eNode.platform_domain === 'bi') {
    // Catch-all for BI domain nodes
    category = 'dashboard';
    layer = 'REPORTING';
  } else if (eNode.platform_domain === 'ingestion') {
    category = 'source';
    layer = 'INGESTION';
  }

  // Extract run summary from raw_metadata (for DAG/task nodes)
  const rawRunSummary = eNode.raw_metadata?.run_summary;
  const runSummary = rawRunSummary ? {
    lastRunState: rawRunSummary.last_run_state,
    lastRunDate: rawRunSummary.last_run_date,
    successRate: rawRunSummary.success_rate,
    avgDurationMinutes: rawRunSummary.avg_duration_minutes,
  } : undefined;

  // Match findings by FQN
  const tableFindings = findingsByFqn.get(eNode.fqn) || [];
  const issuesSummary = tableFindings.length > 0 ? {
    total: tableFindings.length,
    open: tableFindings.filter((f: any) => f.status === 'OPEN').length,
    critical: tableFindings.filter((f: any) => f.severity === 'CRITICAL').length,
    high: tableFindings.filter((f: any) => f.severity === 'HIGH').length,
    medium: tableFindings.filter((f: any) => f.severity === 'MEDIUM').length,
    low: tableFindings.filter((f: any) => f.severity === 'LOW').length,
    byType: tableFindings.reduce((acc: Record<string, number>, f: any) => {
      acc[f.scanType] = (acc[f.scanType] || 0) + 1;
      return acc;
    }, {}),
  } : undefined;

  return {
    id: `lineage-${eNode.id}`,
    name: eNode.name,
    fullName: eNode.fqn,
    category,
    layer,
    database: eNode.database || undefined,
    schema: eNode.schema || eNode.schema_name || undefined,
    tableName: eNode.name,
    nodeType: eNode.node_type,
    criticality: eNode.criticality || 'medium',
    rowCount: eNode.row_count || undefined,
    upstreamCount: eNode.upstream_count || 0,
    downstreamCount: eNode.downstream_count || 0,
    runSummary,
    description: eNode.description || undefined,
    owner: eNode.owner || undefined,
    tags: eNode.tags || undefined,
    issues: issuesSummary,
    // Multi-platform provenance & enriched data
    platforms: eNode.raw_metadata?.discovered_platforms ||
              (eNode.platform ? [eNode.platform] : undefined),
    columns: eNode.columns?.length > 0
      ? eNode.columns.map((c: any) => ({ name: c.name, type: c.type || c.data_type || '' }))
      : undefined,
    sqlDefinition: eNode.raw_metadata?.sql || undefined,
    materialization: eNode.raw_metadata?.materialized || undefined,
  };
}

/**
 * Convert an engine edge to a UnifiedLineageEdge,
 * using an engineId→unifiedNodeId lookup.
 */
function engineEdgeToUnified(
  eEdge: any,
  nodeIdLookup: Map<string, string>,
): UnifiedLineageEdge | null {
  const source = nodeIdLookup.get(eEdge.source_id);
  const target = nodeIdLookup.get(eEdge.target_id);
  if (!source || !target) return null;

  return {
    id: `engine-edge-${eEdge.id}`,
    source,
    target,
    edgeType: eEdge.edge_type,
    columns: eEdge.column_mappings?.map((m: any) => ({
      from: m.from_column,
      to: m.to_column,
    })) || [],
    animated: true,
    confidence: eEdge.confidence,
    lineageLevel: eEdge.lineage_level,
    plane: eEdge.plane as LinePlane | undefined,
    evidence: eEdge.evidence?.map((ev: any) => ({
      adapterId: ev.adapter_id,
      sourceRef: ev.source_ref,
      observedAt: ev.observed_at,
      snippet: ev.snippet,
    })),
  };
}

/**
 * GET /api/pipeline/[stackId]/lineage/unified
 *
 * Returns a unified lineage graph that merges:
 * - PipelineNodes (tool nodes: ingestion, transformation, warehouse, reporting)
 * - Engine graph (data asset nodes with confidence/evidence) OR Prisma LineageNodes as fallback
 *
 * Query params:
 * - layers: comma-separated list of layers to include (e.g., "INGESTION,WAREHOUSE")
 * - search: text search filter
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { stackId } = await params;
    const { searchParams } = new URL(request.url);
    const layersParam = searchParams.get('layers');
    const searchParam = searchParams.get('search')?.toLowerCase() || '';
    const planeParam = searchParams.get('plane') || 'data'; // 'data' | 'control' | 'all'

    // Parse layer filter
    const layerFilter: Set<PipelineLayer> | null = layersParam
      ? new Set(layersParam.split(',').filter(Boolean) as PipelineLayer[])
      : null;

    // Get the pipeline stack with nodes and edges
    const stack = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
      include: {
        nodes: true,
        edges: true,
      },
    });

    if (!stack) {
      return NextResponse.json({ error: 'Pipeline stack not found' }, { status: 404 });
    }

    // Collect integration IDs from pipeline nodes
    const integrationIds = stack.nodes
      .map((n) => n.integrationId)
      .filter((id): id is string => id !== null);

    // Map plane param to engine API filter
    // data → data,cross (show data assets + their orchestration cross-links)
    // control → control,cross (show orchestration + their data cross-links)
    // all → no filter (everything)
    const enginePlaneFilter = planeParam === 'all'
      ? undefined
      : planeParam === 'control'
        ? 'control,cross'
        : 'data,cross';

    // Fetch engine graph and stats in parallel
    let [engineGraph, engineStats] = await Promise.all([
      fetchEngineGraph(stackId, enginePlaneFilter),
      fetchEngineStats(stackId),
    ]);

    // If engine graph is empty (e.g., after server restart), try restoring from DB snapshot
    if (!engineGraph) {
      const restored = await tryRestoreEngineFromSnapshot(organizationId, stackId);
      if (restored) {
        // Re-fetch with plane filter now that the graph is restored
        [engineGraph, engineStats] = await Promise.all([
          fetchEngineGraph(stackId, enginePlaneFilter),
          fetchEngineStats(stackId),
        ]);
      }
    }

    // We still need Prisma lineage nodes for integration ID mapping and as fallback
    const lineageNodes = await prisma.lineageNode.findMany({
      where: {
        organizationId,
        ...(integrationIds.length > 0
          ? { integrationId: { in: integrationIds } }
          : {}),
      },
    });

    // Fetch findings for all tables
    const allFqns = engineGraph
      ? engineGraph.nodes.map((n: any) => n.fqn)
      : lineageNodes.map((n) => n.name);
    const findings = await prisma.finding.findMany({
      where: {
        organizationId,
        table: { in: allFqns },
        status: { in: ['OPEN', 'IN_PROGRESS'] },
      },
      select: {
        table: true,
        severity: true,
        scanType: true,
        status: true,
      },
    });

    // Group findings by table FQN
    const findingsByFqn = new Map<string, typeof findings>();
    for (const finding of findings) {
      const existing = findingsByFqn.get(finding.table) || [];
      existing.push(finding);
      findingsByFqn.set(finding.table, existing);
    }

    // Get latest snapshot for timestamp
    const latestSnapshot = await prisma.lineageSnapshot.findFirst({
      where: {
        organizationId,
        ...(integrationIds.length > 0
          ? { integrationId: { in: integrationIds } }
          : {}),
      },
      orderBy: { createdAt: 'desc' },
    });

    // Layers that participate in data lineage flow.
    // VCS and INFRASTRUCTURE don't produce data edges — including them creates
    // disconnected islands in the graph, so we exclude them from the data view.
    const DATA_FLOW_LAYERS = new Set([
      'INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'ORCHESTRATION', 'STORAGE',
    ]);

    // Convert PipelineNodes to UnifiedLineageNodes (tool nodes)
    const toolNodes: UnifiedLineageNode[] = stack.nodes
      .filter((pNode) => DATA_FLOW_LAYERS.has(pNode.layer))
      .map((pNode) => {
        const category = pNode.layer.toLowerCase() as UnifiedNodeCategory;
        return {
          id: pNode.id,
          name: pNode.name,
          fullName: pNode.name,
          category,
          layer: pNode.layer as PipelineLayer,
          toolType: pNode.toolType,
          status: pNode.status,
          healthScore: pNode.healthScore ?? undefined,
          findingsCount: pNode.findingsCount,
          criticalCount: pNode.criticalCount,
          highCount: pNode.highCount,
          integrationId: pNode.integrationId ?? undefined,
        };
      });

    // Build data asset nodes — prefer engine graph, fallback to Prisma
    let dataAssetNodes: UnifiedLineageNode[];
    let tableEdges: UnifiedLineageEdge[];

    // Build FQN → integrationId lookup from Prisma nodes (for synthetic edge synthesis)
    const fqnToIntegrationId = new Map<string, string>();
    for (const ln of lineageNodes) {
      if (ln.integrationId) {
        fqnToIntegrationId.set(ln.name, ln.integrationId);
      }
    }

    if (engineGraph) {
      // --- ENGINE PATH: Use engine nodes/edges with confidence/evidence ---

      // Step 1: Deduplicate Airflow table reference nodes with warehouse table nodes.
      // Airflow adapter creates table ref nodes (platform="airflow", node_type="table")
      // for tables referenced in SQL. These represent the SAME physical tables as
      // warehouse adapter nodes but have different IDs (different system/namespace).
      // We bridge them by FQN matching: Airflow edges get remapped to warehouse nodes
      // so the orchestration graph connects to the main lineage graph.
      const warehouseFqnMap = new Map<string, string>(); // FQN → engine node ID
      const airflowTableRefs = new Map<string, string>(); // FQN → engine node ID

      for (const eNode of engineGraph.nodes) {
        const fqn = eNode.fqn;
        if (!fqn) continue;
        const nodeType = eNode.node_type?.toLowerCase();
        if (nodeType !== 'table' && nodeType !== 'view' && nodeType !== 'materialized_view') continue;

        if (eNode.platform === 'airflow') {
          airflowTableRefs.set(fqn, eNode.id);
        } else if (!warehouseFqnMap.has(fqn)) {
          warehouseFqnMap.set(fqn, eNode.id);
        }
      }

      // Build remap: Airflow table ref engine ID → warehouse engine ID
      const airflowToWarehouseRemap = new Map<string, string>();
      for (const [fqn, airflowId] of airflowTableRefs) {
        const warehouseId = warehouseFqnMap.get(fqn);
        if (warehouseId) {
          airflowToWarehouseRemap.set(airflowId, warehouseId);
        }
      }

      // Step 1b: Deduplicate inferred (bridge) nodes with real extracted nodes.
      // If the reconciler inferred a node that was already discovered by an
      // extractor, drop the inferred duplicate and remap its edges to the real one.
      const realFqnMap = new Map<string, string>(); // FQN → real engine node ID
      const inferredRemap = new Map<string, string>(); // inferred ID → real ID

      for (const eNode of engineGraph.nodes) {
        if (eNode.fqn && !eNode.inferred) {
          if (!realFqnMap.has(eNode.fqn)) {
            realFqnMap.set(eNode.fqn, eNode.id);
          }
        }
      }
      for (const eNode of engineGraph.nodes) {
        if (eNode.fqn && eNode.inferred) {
          const realId = realFqnMap.get(eNode.fqn);
          if (realId && realId !== eNode.id) {
            inferredRemap.set(eNode.id, realId);
          }
        }
      }

      // Step 2: Convert engine nodes to unified nodes, skipping remapped Airflow table refs
      const engineIdToUnifiedId = new Map<string, string>();
      dataAssetNodes = [];

      // Build integration_id → tool node lookup for orchestration edge promotion
      const integrationToToolNode = new Map<string, UnifiedLineageNode>();
      for (const tn of toolNodes) {
        if (tn.integrationId) {
          integrationToToolNode.set(tn.integrationId, tn);
        }
      }

      for (const eNode of engineGraph.nodes) {
        if (airflowToWarehouseRemap.has(eNode.id) || inferredRemap.has(eNode.id)) {
          // Duplicate node (Airflow table ref or inferred bridge) — skip it,
          // its edges will be remapped to the real node below
          continue;
        }

        // In data view, skip orchestration/job/service nodes (n8n tasks/workflows,
        // airflow DAGs/tasks). Remap their edges to the pipeline tool node
        // so the graph shows "n8n → BQ table" instead of "n8n task X → BQ table".
        // Exception: INGESTION service/job nodes are NOT remapped — their synced_table
        // data assets connect directly to warehouse tables via CrossTool edges, so the
        // ingestion tool node should not appear in the data lineage view.
        const canonicalType = (eNode.canonical_type || '').toLowerCase();
        if (planeParam === 'data' && (
          eNode.platform_domain === 'orchestration' ||
          canonicalType === 'job' ||
          canonicalType === 'service'
        )) {
          const intId = eNode.integration_id;
          if (intId) {
            const toolNode = integrationToToolNode.get(intId);
            if (toolNode && toolNode.layer !== 'INGESTION') {
              engineIdToUnifiedId.set(eNode.id, toolNode.id);
            }
          }
          continue;
        }

        const unified = engineNodeToUnified(eNode, findingsByFqn);
        engineIdToUnifiedId.set(eNode.id, unified.id);

        // Primary: read integration_id from engine node directly
        // Fallback: Prisma FQN lookup (backward compatibility)
        const intId = eNode.integration_id || fqnToIntegrationId.get(eNode.fqn);
        if (intId) {
          unified.integrationId = intId;
        }

        dataAssetNodes.push(unified);
      }

      // Step 3: Populate remap entries so duplicate edges → real unified IDs
      for (const [airflowId, warehouseEngineId] of airflowToWarehouseRemap) {
        const warehouseUnifiedId = engineIdToUnifiedId.get(warehouseEngineId);
        if (warehouseUnifiedId) {
          engineIdToUnifiedId.set(airflowId, warehouseUnifiedId);
        }
      }
      for (const [inferredId, realEngineId] of inferredRemap) {
        const realUnifiedId = engineIdToUnifiedId.get(realEngineId);
        if (realUnifiedId) {
          engineIdToUnifiedId.set(inferredId, realUnifiedId);
        }
      }

      if (airflowToWarehouseRemap.size > 0 || inferredRemap.size > 0) {
        console.log(
          `[UNIFIED LINEAGE] Deduped: ${airflowToWarehouseRemap.size} Airflow refs, ${inferredRemap.size} inferred duplicates`
        );
      }

      // Step 4: Convert engine edges (Airflow→table edges now point to warehouse nodes)
      tableEdges = engineGraph.edges
        .map((eEdge: any) => engineEdgeToUnified(eEdge, engineIdToUnifiedId))
        .filter((e: UnifiedLineageEdge | null): e is UnifiedLineageEdge => e !== null);

    } else {
      // --- PRISMA FALLBACK: Original path ---

      const lineageEdges = await prisma.lineageEdge.findMany({
        where: {
          organizationId,
          sourceId: { in: lineageNodes.map((n) => n.id) },
          targetId: { in: lineageNodes.map((n) => n.id) },
        },
      });

      dataAssetNodes = lineageNodes.map((lNode) => {
        const nodeType = lNode.nodeType?.toLowerCase() || 'table';
        let category: UnifiedNodeCategory = 'table';
        let layer: PipelineLayer = 'WAREHOUSE';

        if (nodeType === 'view' || nodeType === 'materialized_view') {
          category = 'view';
          layer = 'WAREHOUSE';
        } else if (nodeType === 'source') {
          category = 'source';
          layer = 'INGESTION';
        } else if (nodeType === 'model') {
          category = 'model';
          layer = 'TRANSFORMATION';
        }

        const tableFindings = findingsByFqn.get(lNode.name) || [];
        const issuesSummary = tableFindings.length > 0 ? {
          total: tableFindings.length,
          open: tableFindings.filter(f => f.status === 'OPEN').length,
          critical: tableFindings.filter(f => f.severity === 'CRITICAL').length,
          high: tableFindings.filter(f => f.severity === 'HIGH').length,
          medium: tableFindings.filter(f => f.severity === 'MEDIUM').length,
          low: tableFindings.filter(f => f.severity === 'LOW').length,
          byType: tableFindings.reduce((acc, f) => {
            acc[f.scanType] = (acc[f.scanType] || 0) + 1;
            return acc;
          }, {} as Record<string, number>),
        } : undefined;

        let freshnessStatus: 'fresh' | 'stale' | 'unknown' = 'unknown';
        let freshnessHours: number | undefined;
        if (lNode.lastUpdated) {
          const hoursSinceUpdate = (Date.now() - new Date(lNode.lastUpdated).getTime()) / (1000 * 60 * 60);
          freshnessHours = Math.round(hoursSinceUpdate);
          freshnessStatus = hoursSinceUpdate <= 24 ? 'fresh' : 'stale';
        }

        return {
          id: `lineage-${lNode.id}`,
          name: lNode.tableName,
          fullName: lNode.name,
          category,
          layer,
          database: lNode.database ?? undefined,
          schema: lNode.schema ?? undefined,
          tableName: lNode.tableName,
          nodeType: lNode.nodeType,
          criticality: lNode.criticality,
          rowCount: lNode.rowCount ?? undefined,
          upstreamCount: lNode.upstreamCount,
          downstreamCount: lNode.downstreamCount,
          integrationId: lNode.integrationId ?? undefined,
          description: lNode.description ?? undefined,
          owner: lNode.owner ?? undefined,
          tags: lNode.tags ?? undefined,
          lastUpdated: lNode.lastUpdated?.toISOString() ?? undefined,
          freshnessStatus,
          freshnessHours,
          issues: issuesSummary,
        };
      });

      tableEdges = lineageEdges.map((lEdge) => ({
        id: `lineage-edge-${lEdge.id}`,
        source: `lineage-${lEdge.sourceId}`,
        target: `lineage-${lEdge.targetId}`,
        edgeType: lEdge.edgeType,
        columns: lEdge.columns,
        animated: true,
      }));
    }

    // Group data asset nodes by integrationId for synthetic edge synthesis
    const lineageByIntegration = new Map<string, UnifiedLineageNode[]>();
    for (const node of dataAssetNodes) {
      if (node.integrationId) {
        const existing = lineageByIntegration.get(node.integrationId) || [];
        existing.push(node);
        lineageByIntegration.set(node.integrationId, existing);
      }
    }

    // Convert PipelineEdges to UnifiedLineageEdges (tool-to-tool)
    const pipelineEdges: UnifiedLineageEdge[] = stack.edges.map((pEdge) => ({
      id: pEdge.id,
      source: pEdge.sourceId,
      target: pEdge.targetId,
      edgeType: 'pipeline_flow',
      label: pEdge.label ?? undefined,
      animated: true,
      lineageLevel: 'tool',
    }));

    // Synthesize cross-system edges (tool ↔ data asset)
    const syntheticEdges: UnifiedLineageEdge[] = [];

    for (const toolNode of toolNodes) {
      if (!toolNode.integrationId) continue;

      const relatedAssets = lineageByIntegration.get(toolNode.integrationId) || [];

      if (toolNode.layer === 'WAREHOUSE') {
        const roots = relatedAssets.filter(
          (a) => a.upstreamCount === 0 && (a.category === 'table' || a.category === 'view')
        );
        for (const root of roots) {
          syntheticEdges.push({
            id: `synth-${toolNode.id}-${root.id}`,
            source: toolNode.id,
            target: root.id,
            edgeType: 'contains',
            animated: false,
            lineageLevel: 'tool',
          });
        }
      }

      if (toolNode.layer === 'TRANSFORMATION') {
        const models = relatedAssets.filter((a) => a.category === 'model');
        for (const model of models) {
          syntheticEdges.push({
            id: `synth-${toolNode.id}-${model.id}`,
            source: toolNode.id,
            target: model.id,
            edgeType: 'produces',
            animated: false,
            lineageLevel: 'tool',
          });
        }
      }

      // INGESTION tools (Fivetran, Airbyte, etc.) are NOT shown in the data lineage view.
      // Their synced_table data assets connect directly to warehouse tables via CrossTool
      // synthesis edges. The ingestion tool node itself only appears in Pipeline Overview.
    }

    // For REPORTING nodes: connect from leaf tables to reporting tools
    const reportingNodes = toolNodes.filter((n) => n.layer === 'REPORTING');
    for (const reportingNode of reportingNodes) {
      const upstreamPipelineNodeIds = stack.edges
        .filter((e) => e.targetId === reportingNode.id)
        .map((e) => e.sourceId);

      const upstreamIntegrationIds = toolNodes
        .filter((tn) => upstreamPipelineNodeIds.includes(tn.id) && tn.integrationId)
        .map((tn) => tn.integrationId!);

      for (const intId of upstreamIntegrationIds) {
        const assets = lineageByIntegration.get(intId) || [];
        const leaves = assets.filter(
          (a) => a.downstreamCount === 0 && (a.category === 'table' || a.category === 'view')
        );
        for (const leaf of leaves) {
          syntheticEdges.push({
            id: `synth-${leaf.id}-${reportingNode.id}`,
            source: leaf.id,
            target: reportingNode.id,
            edgeType: 'reads_from',
            animated: false,
            lineageLevel: 'tool',
          });
        }
      }
    }

    // Combine all nodes and edges.
    // For the control-plane view (orchestration tab), only include engine graph
    // nodes/edges — skip pipeline tool nodes and synthetic edges which are
    // data-plane concepts and would appear as disconnected islands.
    let allNodes: UnifiedLineageNode[];
    let allEdges: UnifiedLineageEdge[];

    if (planeParam === 'control') {
      // Orchestration view: only engine nodes + engine edges
      allNodes = [...dataAssetNodes];
      allEdges = [...tableEdges];

      // Prune nodes that have no edges (the engine returns all nodes but
      // only plane-filtered edges, so tables with only data-plane connections
      // would otherwise appear as isolated nodes)
      const connectedNodeIds = new Set<string>();
      for (const edge of allEdges) {
        connectedNodeIds.add(edge.source);
        connectedNodeIds.add(edge.target);
      }
      allNodes = allNodes.filter((n) => connectedNodeIds.has(n.id));
    } else {
      // In data view, exclude INGESTION tool nodes entirely — their synced_table
      // data assets connect directly to warehouse tables via CrossTool edges.
      // Ingestion tools (Fivetran, Airbyte, etc.) only appear in Pipeline Overview.
      const dataViewToolNodes = planeParam === 'data'
        ? toolNodes.filter((n) => n.layer !== 'INGESTION')
        : toolNodes;

      allNodes = [...dataViewToolNodes, ...dataAssetNodes];
      allEdges = [...pipelineEdges, ...tableEdges, ...syntheticEdges];

      // Prune pipeline tool nodes that have no edges (they'd appear as
      // disconnected orphans). Data asset nodes are always kept.
      const connectedToolIds = new Set<string>();
      for (const edge of allEdges) {
        connectedToolIds.add(edge.source);
        connectedToolIds.add(edge.target);
      }
      const dataViewToolNodeIds = new Set(dataViewToolNodes.map((n) => n.id));
      allNodes = allNodes.filter(
        (n) => !dataViewToolNodeIds.has(n.id) || connectedToolIds.has(n.id)
      );

      // Clean up edges referencing removed nodes
      const allNodeIds = new Set(allNodes.map((n) => n.id));
      allEdges = allEdges.filter(
        (e) => allNodeIds.has(e.source) && allNodeIds.has(e.target)
      );
    }

    // Compute real upstream/downstream counts from edges
    const upstreamCounts = new Map<string, number>();
    const downstreamCounts = new Map<string, number>();
    for (const edge of [...tableEdges, ...syntheticEdges]) {
      downstreamCounts.set(edge.source, (downstreamCounts.get(edge.source) || 0) + 1);
      upstreamCounts.set(edge.target, (upstreamCounts.get(edge.target) || 0) + 1);
    }
    for (const node of dataAssetNodes) {
      node.upstreamCount = upstreamCounts.get(node.id) || 0;
      node.downstreamCount = downstreamCounts.get(node.id) || 0;
    }

    // Apply layer filter
    if (layerFilter) {
      allNodes = allNodes.filter((n) => layerFilter.has(n.layer));
      const nodeIds = new Set(allNodes.map((n) => n.id));
      allEdges = allEdges.filter(
        (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
      );
    }

    // Apply search filter
    if (searchParam) {
      allNodes = allNodes.filter((n) => {
        const nameMatch = n.name.toLowerCase().includes(searchParam);
        const fullNameMatch = n.fullName?.toLowerCase().includes(searchParam) || false;
        const toolTypeMatch = n.toolType?.toLowerCase().includes(searchParam) || false;
        const tableNameMatch = n.tableName?.toLowerCase().includes(searchParam) || false;
        return nameMatch || fullNameMatch || toolTypeMatch || tableNameMatch;
      });
      const nodeIds = new Set(allNodes.map((n) => n.id));
      allEdges = allEdges.filter(
        (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
      );
    }

    // Deduplicate nodes by id
    const seenNodeIds = new Set<string>();
    allNodes = allNodes.filter((n) => {
      if (seenNodeIds.has(n.id)) return false;
      seenNodeIds.add(n.id);
      return true;
    });

    // Deduplicate edges by (source, target) — when orchestration nodes are
    // remapped to tool nodes, multiple internal edges can collapse to the same pair
    const seenEdgePairs = new Set<string>();
    allEdges = allEdges.filter((e) => {
      const pair = `${e.source}→${e.target}`;
      if (seenEdgePairs.has(pair)) return false;
      seenEdgePairs.add(pair);
      return true;
    });

    // Compute stats
    const stats = {
      totalNodes: allNodes.length,
      totalEdges: allEdges.length,
      toolNodes: allNodes.filter((n) =>
        ['ingestion', 'transformation', 'warehouse', 'reporting', 'orchestration'].includes(n.category)
      ).length,
      tableNodes: allNodes.filter((n) => n.category === 'table').length,
      viewNodes: allNodes.filter((n) => n.category === 'view').length,
      modelNodes: allNodes.filter((n) => n.category === 'model' || n.category === 'source')
        .length,
    };

    // Get available layers — for control-plane, derive only from actual nodes in the response
    const availableLayers: PipelineLayer[] = planeParam === 'control'
      ? [...new Set(allNodes.map((n) => n.layer))]
      : (() => {
          const layers = [...new Set(stack.nodes.map((n) => n.layer as PipelineLayer))];
          if (dataAssetNodes.length > 0 && !layers.includes('WAREHOUSE')) {
            layers.push('WAREHOUSE');
          }
          if (allNodes.some((n) => n.category === 'source') && !layers.includes('INGESTION')) {
            layers.push('INGESTION');
          }
          if (allNodes.some((n) => n.category === 'dag' || n.category === 'task') && !layers.includes('ORCHESTRATION')) {
            layers.push('ORCHESTRATION');
          }
          return layers;
        })();
    const availableTools = [...new Set(stack.nodes.map((n) => n.toolType))];

    const response: UnifiedLineageResponse = {
      nodes: allNodes,
      edges: allEdges,
      stats,
      availableLayers,
      availableTools,
      lastExtracted: latestSnapshot?.createdAt?.toISOString() ?? undefined,
      engineStats,
    };

    return NextResponse.json(response);
  } catch (error) {
    console.error('[UNIFIED LINEAGE] Error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch unified lineage' },
      { status: 500 }
    );
  }
}
