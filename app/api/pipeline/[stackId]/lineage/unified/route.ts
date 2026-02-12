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
} from '@/components/lineage/types';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

/**
 * Fetch the engine graph (nodes + edges with confidence/evidence).
 * Returns null if engine is not available or has no data.
 */
async function fetchEngineGraph(): Promise<{
  nodes: any[];
  edges: any[];
} | null> {
  try {
    const res = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/graph`, {
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
  integrationIds: string[],
): Promise<{ nodes: any[]; edges: any[] } | null> {
  try {
    // Find the latest snapshot with graphData
    const snapshot = await prisma.lineageSnapshot.findFirst({
      where: {
        organizationId,
        ...(integrationIds.length > 0
          ? { integrationId: { in: integrationIds } }
          : {}),
        graphData: { not: null as any },
      },
      orderBy: { createdAt: 'desc' },
      select: { id: true, graphData: true },
    });

    if (!snapshot?.graphData) return null;

    console.log(`[UNIFIED LINEAGE] Restoring engine graph from snapshot ${snapshot.id}`);

    // Send the graph data to FastAPI to restore the in-memory store
    const restoreRes = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/restore`, {
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
    return fetchEngineGraph();
  } catch (e) {
    console.warn('[UNIFIED LINEAGE] Failed to restore engine from snapshot:', e);
    return null;
  }
}

/**
 * Fetch engine coverage stats.
 */
async function fetchEngineStats() {
  try {
    const res = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/stats`, {
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

  if (nodeType === 'model' || isDbtModel) {
    // Nodes that are dbt models (including merged warehouse+dbt nodes)
    category = 'model';
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
  }

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
    description: eNode.description || undefined,
    owner: eNode.owner || undefined,
    tags: eNode.tags || undefined,
    issues: issuesSummary,
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

    // Fetch engine graph and stats in parallel
    let [engineGraph, engineStats] = await Promise.all([
      fetchEngineGraph(),
      fetchEngineStats(),
    ]);

    // If engine graph is empty (e.g., after server restart), try restoring from DB snapshot
    if (!engineGraph) {
      engineGraph = await tryRestoreEngineFromSnapshot(organizationId, integrationIds);
      if (engineGraph) {
        // Re-fetch stats now that the graph is restored
        engineStats = await fetchEngineStats();
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

    // Convert PipelineNodes to UnifiedLineageNodes (tool nodes)
    const toolNodes: UnifiedLineageNode[] = stack.nodes.map((pNode) => {
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

      // Build engine node ID → unified node ID lookup
      const engineIdToUnifiedId = new Map<string, string>();

      dataAssetNodes = engineGraph.nodes.map((eNode: any) => {
        const unified = engineNodeToUnified(eNode, findingsByFqn);
        engineIdToUnifiedId.set(eNode.id, unified.id);

        // Primary: read integration_id from engine node directly
        // Fallback: Prisma FQN lookup (backward compatibility)
        const intId = eNode.integration_id || fqnToIntegrationId.get(eNode.fqn);
        if (intId) {
          unified.integrationId = intId;
        }

        return unified;
      });

      // Convert engine edges
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

    // Combine all nodes and edges
    let allNodes = [...toolNodes, ...dataAssetNodes];
    let allEdges = [...pipelineEdges, ...tableEdges, ...syntheticEdges];

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

    // Compute stats
    const stats = {
      totalNodes: allNodes.length,
      totalEdges: allEdges.length,
      toolNodes: allNodes.filter((n) =>
        ['ingestion', 'transformation', 'warehouse', 'reporting'].includes(n.category)
      ).length,
      tableNodes: allNodes.filter((n) => n.category === 'table').length,
      viewNodes: allNodes.filter((n) => n.category === 'view').length,
      modelNodes: allNodes.filter((n) => n.category === 'model' || n.category === 'source')
        .length,
    };

    // Get available layers and tools
    const availableLayers = [...new Set(stack.nodes.map((n) => n.layer as PipelineLayer))];
    if (dataAssetNodes.length > 0 && !availableLayers.includes('WAREHOUSE')) {
      availableLayers.push('WAREHOUSE');
    }
    // Add INGESTION if any source nodes exist (dbt sources act as ingestion layer)
    if (allNodes.some((n) => n.category === 'source') && !availableLayers.includes('INGESTION')) {
      availableLayers.push('INGESTION');
    }
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
