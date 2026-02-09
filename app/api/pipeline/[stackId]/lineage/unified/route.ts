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

/**
 * GET /api/pipeline/[stackId]/lineage/unified
 *
 * Returns a unified lineage graph that merges:
 * - PipelineNodes (tool nodes: ingestion, transformation, warehouse, reporting)
 * - LineageNodes (data asset nodes: tables, views, sources, models)
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

    // Fetch lineage nodes linked to these integrations
    const lineageNodes = await prisma.lineageNode.findMany({
      where: {
        organizationId,
        ...(integrationIds.length > 0
          ? { integrationId: { in: integrationIds } }
          : {}),
      },
    });

    // Fetch lineage edges between these nodes
    const lineageNodeIds = lineageNodes.map((n) => n.id);
    const lineageEdges = await prisma.lineageEdge.findMany({
      where: {
        organizationId,
        sourceId: { in: lineageNodeIds },
        targetId: { in: lineageNodeIds },
      },
    });

    // Fetch findings for all tables in this lineage
    const tableNames = lineageNodes.map((n) => n.name);
    const findings = await prisma.finding.findMany({
      where: {
        organizationId,
        table: { in: tableNames },
        status: { in: ['OPEN', 'IN_PROGRESS'] },
      },
      select: {
        table: true,
        severity: true,
        scanType: true,
        status: true,
      },
    });

    // Group findings by table name
    const findingsByTable = new Map<string, typeof findings>();
    for (const finding of findings) {
      const existing = findingsByTable.get(finding.table) || [];
      existing.push(finding);
      findingsByTable.set(finding.table, existing);
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

    // Convert PipelineNodes to UnifiedLineageNodes
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

    // Convert LineageNodes to UnifiedLineageNodes
    // Prefix IDs with 'lineage-' to avoid collision with PipelineNode IDs
    const dataAssetNodes: UnifiedLineageNode[] = lineageNodes.map((lNode) => {
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
      } else {
        category = 'table';
        layer = 'WAREHOUSE';
      }

      // Get findings for this table
      const tableFindings = findingsByTable.get(lNode.name) || [];
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

      // Compute freshness status
      let freshnessStatus: 'fresh' | 'stale' | 'unknown' = 'unknown';
      let freshnessHours: number | undefined;
      if (lNode.lastUpdated) {
        const hoursSinceUpdate = (Date.now() - new Date(lNode.lastUpdated).getTime()) / (1000 * 60 * 60);
        freshnessHours = Math.round(hoursSinceUpdate);
        // Consider stale if older than 24 hours (configurable later)
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

    // Group lineage nodes by integrationId for edge synthesis
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
    }));

    // Convert LineageEdges to UnifiedLineageEdges (table-to-table)
    const tableEdges: UnifiedLineageEdge[] = lineageEdges.map((lEdge) => ({
      id: `lineage-edge-${lEdge.id}`,
      source: `lineage-${lEdge.sourceId}`,
      target: `lineage-${lEdge.targetId}`,
      edgeType: lEdge.edgeType,
      columns: lEdge.columns,
      animated: true,
    }));

    // Synthesize cross-system edges
    const syntheticEdges: UnifiedLineageEdge[] = [];

    for (const toolNode of toolNodes) {
      if (!toolNode.integrationId) continue;

      const relatedAssets = lineageByIntegration.get(toolNode.integrationId) || [];

      if (toolNode.layer === 'WAREHOUSE') {
        // Connect warehouse tool -> root tables (upstreamCount === 0)
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
          });
        }
      }

      if (toolNode.layer === 'TRANSFORMATION') {
        // Connect transformation tool -> model nodes
        const models = relatedAssets.filter((a) => a.category === 'model');
        for (const model of models) {
          syntheticEdges.push({
            id: `synth-${toolNode.id}-${model.id}`,
            source: toolNode.id,
            target: model.id,
            edgeType: 'produces',
            animated: false,
          });
        }
      }
    }

    // For REPORTING nodes: connect from leaf tables to reporting tools
    const reportingNodes = toolNodes.filter((n) => n.layer === 'REPORTING');
    for (const reportingNode of reportingNodes) {
      // Find upstream pipeline nodes connected to this reporting node
      const upstreamPipelineNodeIds = stack.edges
        .filter((e) => e.targetId === reportingNode.id)
        .map((e) => e.sourceId);

      // Get integration IDs from those upstream nodes
      const upstreamIntegrationIds = toolNodes
        .filter((tn) => upstreamPipelineNodeIds.includes(tn.id) && tn.integrationId)
        .map((tn) => tn.integrationId!);

      // Find leaf tables from those integrations
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
          });
        }
      }
    }

    // Combine all nodes and edges
    let allNodes = [...toolNodes, ...dataAssetNodes];
    let allEdges = [...pipelineEdges, ...tableEdges, ...syntheticEdges];

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
    if (lineageNodes.length > 0 && !availableLayers.includes('WAREHOUSE')) {
      availableLayers.push('WAREHOUSE');
    }
    const availableTools = [...new Set(stack.nodes.map((n) => n.toolType))];

    const response: UnifiedLineageResponse = {
      nodes: allNodes,
      edges: allEdges,
      stats,
      availableLayers,
      availableTools,
      lastExtracted: latestSnapshot?.createdAt?.toISOString() ?? undefined,
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
