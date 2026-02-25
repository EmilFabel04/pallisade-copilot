'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  Position,
  MarkerType,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import { usePipeline } from '@/contexts/PipelineContext';
import { LAYER_COLORS, type PipelineLayer } from '@/components/pipeline/types';
import { unifiedNodeTypes } from '@/components/lineage/UnifiedNodes';
import { DataAssetDetailPanel } from '@/components/lineage/DataAssetDetailPanel';
import { EdgeDetailPanel } from '@/components/lineage/EdgeDetailPanel';
import {
  type UnifiedLineageNode,
  type UnifiedLineageEdge,
  type UnifiedLineageResponse,
  type LineageFilterState,
  type UnifiedNodeCategory,
  type EngineCoverageStats,
  type ControlPlaneOverviewResponse,
  type ControlPlaneNode as CPNode,
  type ControlPlaneEdge as CPEdge,
  type RenderedViewResponse,
  type ViewNode,
  type ViewEdge,
  type LaneMeta,
  type OrchestratorOverlay,
  type PipelineLaneName,
  LANE_COLORS,
  LANE_LABELS,
  getDefaultFilterState,
  isToolCategory,
  isDataAssetCategory,
  nodePassesFilter,
  edgePassesFilter,
  getConfidenceColor,
  CATEGORY_VISUALS,
} from '@/components/lineage/types';

// Map a ViewNode's canonical type + metadata to a UnifiedNodeCategory for rendering
function _viewNodeToCategory(vn: ViewNode): UnifiedNodeCategory {
  // Use originalType when it maps directly to a known category
  const ot = vn.originalType as UnifiedNodeCategory;
  const knownCategories: UnifiedNodeCategory[] = [
    'table', 'view', 'source', 'model', 'dag', 'task', 'workflow',
    'connector', 'workbook', 'dataset', 'question', 'notebook',
    'file', 'test', 'dashboard', 'report',
  ];
  if (knownCategories.includes(ot)) return ot;

  // Fall back on canonical type → category mapping
  switch (vn.canonicalType) {
    case 'dataset': return 'table';
    case 'semantic': return 'dashboard';
    case 'job': return 'workflow';
    case 'service': return vn.platformDomain === 'warehouse' ? 'warehouse'
      : vn.platformDomain === 'transform' ? 'transformation'
      : vn.platformDomain === 'bi' ? 'reporting'
      : vn.platformDomain === 'ingestion' ? 'ingestion'
      : 'warehouse';
    case 'system': return 'infrastructure';
    default: return 'table';
  }
}

// Dagre layout with layer-aware sizing
const getLayoutedElements = (
  nodes: Node[],
  edges: Edge[],
  direction: 'LR' | 'TB' = 'LR'
): { nodes: Node[]; edges: Edge[] } => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: direction === 'TB' ? 120 : 180,
    align: 'UL',
  });

  // Different dimensions for tool nodes vs data asset nodes
  nodes.forEach((node) => {
    const isToolNode = node.type === 'toolNode';
    const width = isToolNode ? 220 : 170;
    const height = isToolNode ? 90 : 65;
    dagreGraph.setNode(node.id, { width, height });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const isHorizontal = direction === 'LR';
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const isToolNode = node.type === 'toolNode';
    const width = isToolNode ? 220 : 170;
    const height = isToolNode ? 90 : 65;
    return {
      ...node,
      targetPosition: isHorizontal ? Position.Left : Position.Top,
      sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
      position: {
        x: nodeWithPosition.x - width / 2,
        y: nodeWithPosition.y - height / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

// Get edge style based on type and plane
function getEdgeStyle(edge: UnifiedLineageEdge, sourceNode?: UnifiedLineageNode) {
  const edgeType = edge.edgeType;

  // Cross-plane edges (task ↔ table): dashed, orange-tinted
  if (edge.plane === 'cross') {
    return {
      stroke: '#F9731680',
      strokeWidth: 2,
      strokeDasharray: '6,4',
      animated: false,
    };
  }

  // Control-plane edges (DAG → task, task → task)
  if (edge.plane === 'control') {
    const layerColor = LAYER_COLORS.ORCHESTRATION;
    return {
      stroke: layerColor,
      strokeWidth: edgeType === 'depends_on' ? 3 : 2,
      animated: edgeType === 'depends_on',
    };
  }

  // Tool-to-tool pipeline edges
  if (edgeType === 'pipeline_flow') {
    const layerColor = sourceNode ? LAYER_COLORS[sourceNode.layer] : '#6366F1';
    return {
      stroke: layerColor,
      strokeWidth: 3,
      animated: true,
    };
  }

  // Synthetic edges (tool-to-table or table-to-tool)
  if (edgeType === 'contains' || edgeType === 'produces' || edgeType === 'reads_from') {
    const layerColor = sourceNode ? LAYER_COLORS[sourceNode.layer] : '#6366F1';
    return {
      stroke: `${layerColor}80`,
      strokeWidth: 2,
      strokeDasharray: '5,5',
      animated: false,
    };
  }

  // Table-to-table lineage edges — color by confidence when available
  const confidenceColor = getConfidenceColor(edge.confidence);
  return {
    stroke: confidenceColor,
    strokeWidth: 2,
    animated: true,
  };
}

// ---------------------------------------------------------------------------
// Lane Overview Canvas — renders the lane-based pipeline overview
// Uses pre-positioned nodes from backend (no Dagre needed)
// ---------------------------------------------------------------------------
function LaneOverviewCanvas({
  data,
  loading,
  onExtract,
  extracting,
  stackId,
}: {
  data: RenderedViewResponse | null;
  loading: boolean;
  onExtract: () => void;
  extracting: boolean;
  stackId: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 red-spinner" />
          <p className="text-sm text-[var(--muted)]">Loading lane overview...</p>
        </div>
      </div>
    );
  }

  if (!data || !data.nodes || data.nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <svg className="w-16 h-16 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7" />
        </svg>
        <p className="text-[var(--muted)] text-[15px] mb-2">No lane overview available</p>
        <p className="text-[var(--text-faint)] text-[13px] mb-4">
          Extract lineage from the Data Lineage tab first
        </p>
        <button
          onClick={onExtract}
          disabled={extracting || !stackId}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 text-white text-[13px] font-medium"
        >
          {extracting ? 'Extracting...' : 'Extract Lineage'}
        </button>
      </div>
    );
  }

  const lanes = data.lanes || [];
  const nodes = data.nodes;
  const edges = data.edges;

  // Tool box dimensions (larger than old node cards)
  const BOX_W = 200;
  const BOX_H = 56;
  const LANE_PADDING = 40;

  // Build a node map for edge drawing
  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  // Compute bounds for the SVG viewBox
  const allX = nodes.map(n => n.x);
  const allY = nodes.map(n => n.y);
  const minX = Math.min(...allX, 0) - LANE_PADDING - 20;
  const maxX = Math.max(...allX, 0) + BOX_W + LANE_PADDING + 20;
  const minY = -60;  // room for lane headers
  const maxY = Math.max(...allY, 0) + BOX_H + 40;

  const viewWidth = maxX - minX;
  const viewHeight = maxY - minY;

  return (
    <div className="w-full h-full overflow-auto relative bg-[var(--surface-sunken)]">
      <svg
        width="100%"
        height="100%"
        viewBox={`${minX} ${minY} ${viewWidth} ${viewHeight}`}
        className="min-w-full min-h-full"
      >
        {/* Lane backgrounds */}
        {lanes.map((lane) => {
          const laneColor = LANE_COLORS[lane.name as PipelineLaneName] || '#6366F1';
          return (
            <g key={lane.name}>
              <rect
                x={lane.x - LANE_PADDING}
                y={minY}
                width={BOX_W + LANE_PADDING * 2}
                height={viewHeight}
                fill={`${laneColor}08`}
                rx={8}
              />
              {/* Lane header */}
              <text
                x={lane.x + BOX_W / 2}
                y={minY + 22}
                textAnchor="middle"
                fill={laneColor}
                fontSize={12}
                fontWeight={600}
                fontFamily="system-ui, sans-serif"
              >
                {lane.label}
              </text>
            </g>
          );
        })}

        {/* Flow arrows between tool boxes */}
        <defs>
          <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="var(--text-faint)" />
          </marker>
        </defs>
        {edges.map((edge) => {
          const src = nodeMap.get(edge.sourceId);
          const tgt = nodeMap.get(edge.targetId);
          if (!src || !tgt) return null;

          const x1 = src.x + BOX_W;
          const y1 = src.y + BOX_H / 2;
          const x2 = tgt.x;
          const y2 = tgt.y + BOX_H / 2;
          const midX = (x1 + x2) / 2;
          const path = `M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}`;

          return (
            <path
              key={edge.id}
              d={path}
              fill="none"
              stroke="var(--text-faint)"
              strokeWidth={2}
              markerEnd="url(#arrowhead)"
            />
          );
        })}

        {/* Tool boxes */}
        {nodes.map((node) => {
          const lane = node.metadata?.lane as PipelineLaneName | undefined;
          const laneColor = lane ? LANE_COLORS[lane] || '#6366F1' : '#6366F1';
          const isOrch = node.metadata?.isOrchestrator;
          const isInfra = node.metadata?.isInfra;
          const assetCount = node.metadata?.assetCount as number | undefined;

          // Orchestrators get orange accent, infra gets a muted purple
          const accentColor = isOrch ? '#FB923C' : laneColor;

          return (
            <g key={node.id}>
              {/* Box background */}
              <rect
                x={node.x}
                y={node.y}
                width={BOX_W}
                height={BOX_H}
                rx={10}
                fill={isOrch ? 'rgba(251,146,60,0.06)' : 'var(--overlay-faint)'}
                stroke={`${accentColor}50`}
                strokeWidth={1.5}
                strokeDasharray={isOrch ? '5,3' : undefined}
              />
              {/* Left accent bar */}
              <rect
                x={node.x}
                y={node.y + 8}
                width={4}
                height={BOX_H - 16}
                rx={2}
                fill={accentColor}
              />
              {/* Tool name */}
              <text
                x={node.x + 16}
                y={node.y + 24}
                fill="var(--text)"
                fontSize={13}
                fontWeight={600}
                fontFamily="system-ui, sans-serif"
              >
                {node.name.length > 20 ? node.name.slice(0, 20) + '…' : node.name}
              </text>
              {/* Asset count subtitle */}
              <text
                x={node.x + 16}
                y={node.y + 42}
                fill="var(--muted)"
                fontSize={10}
                fontFamily="system-ui, sans-serif"
              >
                {isOrch ? 'orchestrator' : isInfra ? 'infrastructure' : (
                  assetCount ? `${assetCount} asset${assetCount !== 1 ? 's' : ''}` : 'tool'
                )}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Legend — only show lanes present */}
      <div className="absolute bottom-4 left-4 flex flex-wrap items-center gap-3 px-3 py-2 bg-[var(--surface)]/80 backdrop-blur-sm rounded-lg border border-[var(--border-medium)] text-[10px]">
        {lanes.map((lane) => {
          const color = LANE_COLORS[lane.name as PipelineLaneName] || '#6366F1';
          return (
            <div key={lane.name} className="flex items-center gap-1">
              <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: color }} />
              <span className="text-[var(--muted)]">{lane.label}</span>
            </div>
          );
        })}
      </div>

      {/* Stats overlay */}
      {data.stats && (
        <div className="absolute top-4 right-4 px-3 py-2 bg-[var(--surface)]/80 backdrop-blur-sm rounded-lg border border-[var(--border-medium)] text-[10px] space-y-1">
          <div className="text-[var(--muted)]">
            <span className="text-[var(--text)] font-medium">{data.stats.totalNodes}</span> tools
            {data.stats.totalEdges > 0 && (
              <>
                {' / '}
                <span className="text-[var(--text)] font-medium">{data.stats.totalEdges}</span> flows
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


export default function LineagePage() {
  const { selectedPipelineId: stackId, loading: pipelineLoading } = usePipeline();
  const [lineageData, setLineageData] = useState<UnifiedLineageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<UnifiedLineageNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<UnifiedLineageEdge | null>(null);
  const [filters, setFilters] = useState<LineageFilterState>(getDefaultFilterState());
  const [activeTab, setActiveTab] = useState<'data' | 'control-plane'>('data');
  const [controlPlaneData, setControlPlaneData] = useState<ControlPlaneOverviewResponse | null>(null);
  const [controlPlaneLoading, setControlPlaneLoading] = useState(false);
  // Rendered view data (from ViewBuilder backend — pre-positioned, canonical types)
  const [renderedView, setRenderedView] = useState<RenderedViewResponse | null>(null);
  const [renderedOverview, setRenderedOverview] = useState<RenderedViewResponse | null>(null);
  // Lane-based pipeline overview
  const [laneOverview, setLaneOverview] = useState<RenderedViewResponse | null>(null);
  // laneOverview is now populated by fetchControlPlane (lane view is the primary Pipeline Overview)
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  // LLM extraction state
  const [llmExtracting, setLlmExtracting] = useState(false);
  const [llmProgress, setLlmProgress] = useState<Array<{type: string; message: string; ts?: number}>>([]);
  const [llmNodeCount, setLlmNodeCount] = useState(0);
  const [llmEdgeCount, setLlmEdgeCount] = useState(0);

  // Track fetch version to ignore stale responses on rapid tab switches
  const fetchVersionRef = useRef(0);

  // Fetch unified lineage data — tries rendered view first, falls back to unified
  const fetchLineage = useCallback(async () => {
    if (!stackId) return;

    const thisVersion = ++fetchVersionRef.current;
    setLoading(true);
    setError(null);

    try {
      // Try rendered data-plane view first (pre-positioned, canonical types)
      let usedRenderedView = false;
      try {
        const viewRes = await fetch(`/api/pipeline/${stackId}/lineage/engine?action=view-data-plane`);
        if (fetchVersionRef.current !== thisVersion) return;
        if (viewRes.ok) {
          const viewData: RenderedViewResponse = await viewRes.json();
          if (fetchVersionRef.current !== thisVersion) return;
          if (viewData.nodes && viewData.nodes.length > 0) {
            console.log('[Lineage] Data Lineage: using data-plane view');
            setRenderedView(viewData);
            usedRenderedView = true;
          }
        }
      } catch {
        // Non-fatal — fall through to unified endpoint
      }

      // Always fetch unified data (for detail panels, filters, and fallback)
      const res = await fetch(`/api/pipeline/${stackId}/lineage/unified?plane=data`);
      if (fetchVersionRef.current !== thisVersion) return;

      if (res.ok) {
        const data: UnifiedLineageResponse = await res.json();
        if (fetchVersionRef.current !== thisVersion) return;

        setLineageData(data);

        // Update filter with available layers
        if (data.availableLayers.length > 0) {
          setFilters((prev) => ({
            ...prev,
            layers: new Set(data.availableLayers),
          }));
        }
      } else {
        // If we got rendered view, this isn't fatal
        if (!usedRenderedView) {
          const errorData = await res.json().catch(() => ({}));
          setError(errorData.error || 'Failed to fetch lineage');
        }
      }
    } catch (err) {
      if (fetchVersionRef.current !== thisVersion) return;
      setError('Failed to connect to server');
    } finally {
      if (fetchVersionRef.current === thisVersion) {
        setLoading(false);
      }
    }
  }, [stackId]);

  // Fetch pipeline overview — tries lane-based view first (swimlane layout),
  // then falls back to tool-sequence pipeline-overview, then legacy merge.
  const fetchControlPlane = useCallback(async () => {
    if (!stackId) return;
    setControlPlaneLoading(true);
    try {
      // Try lane-based pipeline overview first (swimlane: n8n → BQ raw → dbt → analytics)
      try {
        const laneRes = await fetch(`/api/pipeline/${stackId}/lineage/engine?action=view-lane-pipeline-overview`);
        if (laneRes.ok) {
          const laneData: RenderedViewResponse = await laneRes.json();
          if (laneData.nodes && laneData.nodes.length > 0) {
            console.log('[Lineage] Pipeline Overview: using lane-pipeline-overview view');
            setLaneOverview(laneData);
            setControlPlaneLoading(false);
            return;
          }
        }
      } catch {
        // Non-fatal — fall through
      }

      // Try rendered pipeline overview (tool clusters)
      try {
        const viewRes = await fetch(`/api/pipeline/${stackId}/lineage/engine?action=view-pipeline-overview`);
        if (viewRes.ok) {
          const viewData: RenderedViewResponse = await viewRes.json();
          if (viewData.nodes && viewData.nodes.length > 0) {
            console.log('[Lineage] Pipeline Overview: using pipeline-overview view (fallback)');
            setRenderedOverview(viewData);
            // Also set controlPlaneData for compatibility with side panels
            setControlPlaneData({
              nodes: viewData.nodes.map((n: ViewNode) => ({
                id: n.id,
                name: n.name,
                toolType: n.platform || n.originalType,
                platformDomain: n.platformDomain,
                integrationId: n.metadata?.integrationId,
                assetCount: n.metadata?.assetCount || 0,
                healthSummary: n.metadata?.healthSummary || { healthy: 0, degraded: 0, failing: 0, unknown: 0 },
                position: 0,
              })),
              edges: viewData.edges.map((e: ViewEdge) => ({
                id: e.id,
                source: e.sourceId,
                target: e.targetId,
                dataFlowCount: e.evidenceCount,
                sampleAssets: [],
              })),
              stats: {
                tool_count: viewData.nodes.length,
                flow_count: viewData.edges.length,
              },
            });
            setControlPlaneLoading(false);
            return;
          }
        }
      } catch {
        // Non-fatal — fall through to legacy path
      }

      // Fetch engine control plane data and pipeline stack in parallel
      const [engineRes, stackRes] = await Promise.all([
        fetch(`/api/pipeline/${stackId}/lineage/engine?action=control-plane-overview`).catch(() => null),
        fetch(`/api/pipeline/${stackId}/lineage/unified?plane=data`).catch(() => null),
      ]);

      const engineData: ControlPlaneOverviewResponse | null = engineRes?.ok
        ? await engineRes.json()
        : null;

      // Build a map of engine tool nodes by toolType for merging
      const engineNodesByType = new Map<string, CPNode>();
      if (engineData?.nodes) {
        for (const n of engineData.nodes) {
          engineNodesByType.set(n.toolType, n);
        }
      }

      // Get pipeline stack tool nodes from the unified response
      const stackData: UnifiedLineageResponse | null = stackRes?.ok
        ? await stackRes.json()
        : null;

      const pipelineToolNodes = (stackData?.nodes || []).filter(
        (n) => isToolCategory(n.category)
      );

      // Map pipeline layer to control plane domain
      const layerToDomain: Record<string, string> = {
        INGESTION: 'ingestion',
        TRANSFORMATION: 'transform',
        WAREHOUSE: 'warehouse',
        REPORTING: 'bi',
        ORCHESTRATION: 'orchestration',
        VERSION_CONTROL: 'version_control',
        INFRASTRUCTURE: 'infrastructure',
        STORAGE: 'storage',
      };

      // Domain ordering for position
      const domainOrder: Record<string, number> = {
        ingestion: 0, warehouse: 1, transform: 2,
        orchestration: 3, bi: 4, version_control: 5,
        infrastructure: 6, storage: 0, other: 7,
      };

      // Build merged nodes: start with pipeline tool nodes as the base
      const mergedNodes: CPNode[] = [];
      const seenToolTypes = new Set<string>();

      for (const toolNode of pipelineToolNodes) {
        const toolType = (toolNode.toolType || toolNode.category || '').toLowerCase();
        if (seenToolTypes.has(toolType)) continue;
        seenToolTypes.add(toolType);

        const domain = layerToDomain[toolNode.layer] || 'other';
        const engineNode = engineNodesByType.get(toolType);

        mergedNodes.push({
          id: engineNode?.id || `pipeline:${toolType}`,
          name: toolNode.name,
          toolType: toolType,
          platformDomain: domain,
          integrationId: toolNode.integrationId,
          assetCount: engineNode?.assetCount || 0,
          healthSummary: engineNode?.healthSummary || { healthy: 0, degraded: 0, failing: 0, unknown: 0 },
          position: domainOrder[domain] ?? 7,
        });
      }

      // Add any engine nodes that don't have a matching pipeline tool node
      // (e.g., dbt adapter might discover data but no pipeline tool node exists)
      if (engineData?.nodes) {
        for (const engNode of engineData.nodes) {
          if (!seenToolTypes.has(engNode.toolType)) {
            seenToolTypes.add(engNode.toolType);
            mergedNodes.push(engNode);
          }
        }
      }

      // Use engine edges (data flow counts between tools)
      const edges = engineData?.edges || [];

      // Also create pipeline-flow edges from pipeline stack edges for tools
      // that don't have engine-derived data flows
      const edgeKeys = new Set(edges.map((e) => `${e.source}→${e.target}`));
      const pipelineEdges = (stackData?.edges || []).filter(
        (e) => e.edgeType === 'pipeline_flow'
      );

      // Map pipeline node IDs to control plane tool IDs
      const pipelineIdToToolType = new Map<string, string>();
      for (const tn of pipelineToolNodes) {
        const toolType = (tn.toolType || tn.category || '').toLowerCase();
        pipelineIdToToolType.set(tn.id, toolType);
      }

      const nodeIdMap = new Map(mergedNodes.map((n) => [n.toolType, n.id]));
      const syntheticEdges: CPEdge[] = [];
      for (const pe of pipelineEdges) {
        const srcTool = pipelineIdToToolType.get(pe.source);
        const tgtTool = pipelineIdToToolType.get(pe.target);
        if (!srcTool || !tgtTool) continue;
        const srcId = nodeIdMap.get(srcTool);
        const tgtId = nodeIdMap.get(tgtTool);
        if (!srcId || !tgtId) continue;
        const key = `${srcId}→${tgtId}`;
        if (edgeKeys.has(key)) continue; // Engine already has this edge
        edgeKeys.add(key);
        syntheticEdges.push({
          id: key,
          source: srcId,
          target: tgtId,
          dataFlowCount: 0, // Pipeline edge, no data flow count yet
          sampleAssets: [],
        });
      }

      setControlPlaneData({
        nodes: mergedNodes.sort((a, b) => a.position - b.position),
        edges: [...edges, ...syntheticEdges],
        stats: {
          tool_count: mergedNodes.length,
          flow_count: edges.length + syntheticEdges.length,
        },
      });
    } catch {
      // Non-fatal
    } finally {
      setControlPlaneLoading(false);
    }
  }, [stackId]);

  useEffect(() => {
    if (stackId) {
      if (activeTab === 'control-plane') {
        fetchControlPlane();
      } else {
        fetchLineage();
      }
    }
  }, [stackId, activeTab, fetchLineage, fetchControlPlane]);

  // Clear selection when switching tabs
  const handleTabChange = useCallback((tab: 'data' | 'control-plane') => {
    setActiveTab(tab);
    setSelectedNode(null);
    setSelectedEdge(null);
    setLineageData(null); // Clear stale data to prevent wrong-layout flash
    setRenderedView(null);
    setRenderedOverview(null);
    setLaneOverview(null);
  }, []);

  // Extract lineage from warehouse (uses original endpoint)
  const extractLineage = async () => {
    if (!stackId) return;

    setExtracting(true);
    setError(null);
    // Keep old view visible during extraction (atomic swap on completion)

    try {
      // Clear existing lineage first
      await fetch(`/api/pipeline/${stackId}/lineage`, { method: 'DELETE' });

      const res = await fetch(`/api/pipeline/${stackId}/lineage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          options: {
            region: 'auto',
            days_back: 30,
          },
        }),
      });

      if (res.ok) {
        const result = await res.json();
        if (result.run_id) {
          // Pipeline completed with run_id — poll for completion
          setActiveRunId(result.run_id);
        } else if (result.success) {
          // Backward compat: old response format without run_id
          await fetchLineage();
          setExtracting(false);
        } else {
          setError(result.results?.[0]?.error || 'Extraction failed');
          setExtracting(false);
        }
      } else {
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'Extraction request failed');
        setExtracting(false);
      }
    } catch (err) {
      setError('Failed to extract lineage');
      setExtracting(false);
    }
  };

  // LLM-powered extraction with SSE streaming
  const extractWithLLM = async () => {
    if (!stackId) return;

    setLlmExtracting(true);
    setLlmProgress([]);
    setLlmNodeCount(0);
    setLlmEdgeCount(0);
    setError(null);

    try {
      // Clear existing lineage first
      await fetch(`/api/pipeline/${stackId}/lineage`, { method: 'DELETE' });

      const res = await fetch(`/api/pipeline/${stackId}/lineage/extract-llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llmProvider: 'openai' }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'LLM extraction failed');
        setLlmExtracting(false);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        setError('No stream from server');
        setLlmExtracting(false);
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event = JSON.parse(line.slice(6));
            const { type, data } = event;

            if (type === 'phase') {
              setLlmProgress(prev => [...prev.slice(-29), { type: 'phase', message: data.message }]);
            } else if (type === 'tool_call') {
              setLlmProgress(prev => [...prev.slice(-29), { type: 'tool', message: `Calling ${data.tool}...` }]);
            } else if (type === 'node_added') {
              setLlmNodeCount(data.total_nodes || 0);
              setLlmProgress(prev => [...prev.slice(-29), { type: 'node', message: `Added ${data.node_type}: ${data.name}` }]);
            } else if (type === 'edge_added') {
              setLlmEdgeCount(data.total_edges || 0);
            } else if (type === 'error') {
              setLlmProgress(prev => [...prev.slice(-29), { type: 'error', message: data.message }]);
            } else if (type === 'complete') {
              setLlmProgress(prev => [...prev.slice(-29), { type: 'complete', message: `Done: ${data.stats?.total_nodes || 0} nodes, ${data.stats?.total_edges || 0} edges` }]);
            } else if (type === 'persisted') {
              // Extraction persisted — save snapshot to DB for restart recovery, then refresh
              try {
                await fetch(`/api/pipeline/${stackId}/lineage/engine?action=save-snapshot`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({}),
                });
              } catch {
                console.warn('[LLM-EXTRACT] Failed to save snapshot (non-fatal)');
              }
              await fetchLineage();
            }
          } catch {
            // Ignore parse errors on partial SSE chunks
          }
        }
      }

      setLlmExtracting(false);
    } catch (err) {
      setError('LLM extraction failed');
      setLlmExtracting(false);
    }
  };

  // Poll run status and atomically swap views when complete
  useEffect(() => {
    if (!activeRunId || !stackId) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=run-status&id=${activeRunId}`
        );
        if (!res.ok) return;
        const status = await res.json();

        if (status.status === 'completed') {
          clearInterval(interval);
          setActiveRunId(null);
          // Atomic swap: fetch new views, then update state
          await fetchLineage();
          setExtracting(false);
        } else if (status.status === 'failed') {
          clearInterval(interval);
          setActiveRunId(null);
          setError(status.errors?.[0] || 'Extraction failed');
          setExtracting(false);
        }
      } catch {
        // Polling error — continue trying
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [activeRunId, stackId]);

  // Apply filters to nodes
  const filteredNodes = useMemo(() => {
    if (!lineageData?.nodes) return [];
    return lineageData.nodes.filter((node) => nodePassesFilter(node, filters));
  }, [lineageData?.nodes, filters]);

  // Build filtered stats
  const filteredStats = useMemo(() => {
    return {
      toolNodes: filteredNodes.filter((n) => isToolCategory(n.category)).length,
      tableNodes: filteredNodes.filter((n) => n.category === 'table').length,
      viewNodes: filteredNodes.filter((n) => n.category === 'view').length,
      modelNodes: filteredNodes.filter((n) => n.category === 'model' || n.category === 'source')
        .length,
      dagNodes: filteredNodes.filter((n) => n.category === 'dag').length,
      taskNodes: filteredNodes.filter((n) => n.category === 'task').length,
    };
  }, [filteredNodes]);

  // Build merged edges/nodes for the detail panel
  // Falls back to rendered-view edges when unified data has no data-level edges
  const panelEdges = useMemo(() => {
    const unifiedEdges = lineageData?.edges || [];
    // Check if unified edges include actual data edges (not just synthetic tool edges)
    const hasDataEdges = unifiedEdges.some(
      (e) =>
        e.edgeType !== 'pipeline_flow' &&
        e.edgeType !== 'contains' &&
        e.edgeType !== 'produces' &&
        e.edgeType !== 'reads_from'
    );
    if (hasDataEdges) return unifiedEdges;

    // Fallback: adapt rendered view edges to unified format with lineage- prefix
    if (!renderedView?.edges?.length) return unifiedEdges;

    const adaptedEdges: UnifiedLineageEdge[] = renderedView.edges.map((ve) => ({
      id: ve.id,
      source: `lineage-${ve.sourceId}`,
      target: `lineage-${ve.targetId}`,
      edgeType: ve.canonicalType || 'derives',
      animated: true,
      confidence: ve.confidence,
      columns: [],
    }));
    return [...unifiedEdges, ...adaptedEdges];
  }, [lineageData?.edges, renderedView?.edges]);

  const panelNodes = useMemo(() => {
    const unifiedNodes = lineageData?.nodes || [];
    if (unifiedNodes.length > 0) return unifiedNodes;

    // Fallback: adapt rendered view nodes to unified format
    if (!renderedView?.nodes?.length) return unifiedNodes;

    return renderedView.nodes.map((vn): UnifiedLineageNode => ({
      id: `lineage-${vn.id}`,
      name: vn.name,
      fullName: vn.metadata?.fqn as string || vn.name,
      category: _viewNodeToCategory(vn),
      layer: (vn.layer || 'WAREHOUSE') as any,
      toolType: vn.platform || undefined,
      database: (vn.metadata?.database as string) || undefined,
      schema: (vn.metadata?.schema as string) || undefined,
      tableName: vn.name,
    }));
  }, [lineageData?.nodes, renderedView?.nodes]);

  // Build React Flow nodes and edges
  // Uses pre-positioned rendered view when available, falls back to Dagre
  const { flowNodes, flowEdges } = useMemo(() => {
    // Rendered view path: use backend-computed positions
    if (renderedView && renderedView.nodes.length > 0) {
      // Filter by inferred toggle
      const visibleViewNodes = renderedView.nodes.filter(
        (n) => filters.showInferred || !n.inferred
      );
      const visibleIds = new Set(visibleViewNodes.map((n) => n.id));

      const nodes: Node[] = visibleViewNodes.map((vn) => ({
        id: vn.id,
        type: vn.canonicalType === 'service' ? 'toolNode' : 'dataAssetNode',
        position: { x: vn.x, y: vn.y },
        targetPosition: Position.Left,
        sourcePosition: Position.Right,
        data: {
          name: vn.name,
          fullName: vn.metadata?.fqn || vn.name,
          category: _viewNodeToCategory(vn),
          layer: vn.layer as any,
          toolType: vn.platform,
          database: vn.metadata?.database,
          schema: vn.metadata?.schema,
          tableName: vn.name,
          nodeType: vn.originalType,
          criticality: vn.metadata?.criticality,
          rowCount: vn.metadata?.rowCount,
          upstreamCount: vn.metadata?.upstreamCount,
          downstreamCount: vn.metadata?.downstreamCount,
          healthStatus: vn.metadata?.healthStatus,
          owner: vn.metadata?.owner,
          tags: vn.metadata?.tags,
          platforms: vn.metadata?.platforms,
          columnCount: vn.metadata?.columnCount,
          materialization: vn.metadata?.materialization,
          // Visual flags
          isInferred: vn.inferred,
          isOverlay: vn.inferred,
        },
      }));

      const edges: Edge[] = renderedView.edges
        .filter(
          (e) =>
            visibleIds.has(e.sourceId) &&
            visibleIds.has(e.targetId) &&
            (filters.showInferred || !e.inferred) &&
            e.confidence >= filters.minConfidence
        )
        .map((ve) => {
          const confidenceColor = getConfidenceColor(ve.confidence);
          const isInferred = ve.inferred;
          return {
            id: ve.id,
            source: ve.sourceId,
            target: ve.targetId,
            type: 'smoothstep',
            animated: !isInferred,
            style: {
              stroke: isInferred ? 'var(--text-faint)' : confidenceColor,
              strokeWidth: isInferred ? 1.5 : 2,
              strokeDasharray: isInferred ? '6,4' : undefined,
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isInferred ? 'var(--text-faint)' : confidenceColor,
            },
            label: ve.confidence !== undefined
              ? `${Math.round(ve.confidence * 100)}%`
              : undefined,
          };
        });

      return { flowNodes: nodes, flowEdges: edges };
    }

    // Fallback: use unified data + Dagre layout
    if (!filteredNodes.length) return { flowNodes: [], flowEdges: [] };

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const nodeMap = new Map(filteredNodes.map((n) => [n.id, n]));

    // Convert to ReactFlow nodes
    const nodes: Node[] = filteredNodes.map((node) => ({
      id: node.id,
      type: isToolCategory(node.category) ? 'toolNode' : 'dataAssetNode',
      position: { x: 0, y: 0 },
      data: {
        name: node.name,
        fullName: node.fullName,
        category: node.category,
        layer: node.layer,
        toolType: node.toolType,
        status: node.status,
        healthScore: node.healthScore,
        findingsCount: node.findingsCount,
        criticalCount: node.criticalCount,
        highCount: node.highCount,
        database: node.database,
        schema: node.schema,
        tableName: node.tableName,
        nodeType: node.nodeType,
        criticality: node.criticality,
        rowCount: node.rowCount,
        upstreamCount: node.upstreamCount,
        downstreamCount: node.downstreamCount,
        // Health & freshness data
        lastUpdated: node.lastUpdated,
        freshnessStatus: node.freshnessStatus,
        freshnessHours: node.freshnessHours,
        issues: node.issues,
        owner: node.owner,
        tags: node.tags,
        platforms: node.platforms,
        columnCount: node.columns?.length || 0,
        materialization: node.materialization,
      },
    }));

    // Data graph: show everything except pure control-plane edges
    // (pipeline/synthetic edges have no plane field — always show them)
    const isDisplayPlane = (e: UnifiedLineageEdge): boolean => {
      return e.plane !== 'control';
    };

    // Filter and convert edges (apply node membership + plane + engine-level filters)
    const edges: Edge[] = (lineageData?.edges || [])
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target) && isDisplayPlane(e) && edgePassesFilter(e, filters))
      .map((edge) => {
        const sourceNode = nodeMap.get(edge.source);
        const style = getEdgeStyle(edge, sourceNode);
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: 'smoothstep',
          animated: style.animated,
          style: {
            stroke: style.stroke,
            strokeWidth: style.strokeWidth,
            strokeDasharray: style.strokeDasharray,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: style.stroke,
          },
          label: edge.confidence !== undefined
            ? `${Math.round(edge.confidence * 100)}%`
            : edge.label,
        };
      });

    if (nodes.length === 0) return { flowNodes: [], flowEdges: [] };

    const layouted = getLayoutedElements(nodes, edges, 'LR');
    return { flowNodes: layouted.nodes, flowEdges: layouted.edges };
  }, [filteredNodes, lineageData?.edges, filters, renderedView]);

  // Build control plane flow nodes/edges
  // Uses rendered overview positions when available, falls back to Dagre
  const { cpFlowNodes, cpFlowEdges } = useMemo(() => {
    const DOMAIN_COLORS: Record<string, string> = {
      ingestion: '#10B981',
      warehouse: '#6366F1',
      transform: '#F59E0B',
      orchestration: '#F97316',
      bi: '#06B6D4',
      version_control: '#8B5CF6',
      infrastructure: '#94A3B8',
      storage: '#A855F7',
      catalog: '#8B5CF6',
      app: '#EC4899',
      other: '#6B7280',
    };

    // Rendered overview path: use backend positions
    if (renderedOverview && renderedOverview.nodes.length > 0) {
      const cpNodes: Node[] = renderedOverview.nodes.map((vn) => ({
        id: vn.id,
        type: 'toolNode',
        position: { x: vn.x, y: vn.y },
        targetPosition: Position.Left,
        sourcePosition: Position.Right,
        data: {
          name: vn.name,
          category: vn.platformDomain as UnifiedNodeCategory || 'warehouse',
          layer: vn.layer as PipelineLayer,
          toolType: vn.platform || vn.originalType,
          assetCount: vn.metadata?.assetCount,
          healthSummary: vn.metadata?.healthSummary,
          isControlPlane: true,
          domainColor: DOMAIN_COLORS[vn.platformDomain] || DOMAIN_COLORS.other,
        },
      }));

      const cpEdges: Edge[] = renderedOverview.edges.map((ve) => ({
        id: ve.id,
        source: ve.sourceId,
        target: ve.targetId,
        type: 'smoothstep',
        animated: ve.evidenceCount > 0,
        label: ve.evidenceCount > 0 ? `${ve.evidenceCount} flows` : 'connected',
        style: {
          stroke: ve.evidenceCount > 0 ? '#6366F180' : 'var(--text-faint)',
          strokeWidth: ve.evidenceCount > 0
            ? Math.min(2 + Math.log2(ve.evidenceCount + 1), 6)
            : 2,
          strokeDasharray: ve.evidenceCount > 0 ? undefined : '6,4',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: ve.evidenceCount > 0 ? '#6366F1' : 'var(--text-faint)',
        },
      }));

      return { cpFlowNodes: cpNodes, cpFlowEdges: cpEdges };
    }

    // Fallback: use controlPlaneData + Dagre
    if (!controlPlaneData?.nodes?.length) return { cpFlowNodes: [], cpFlowEdges: [] };

    const cpNodes: Node[] = controlPlaneData.nodes.map((n: CPNode) => ({
      id: n.id,
      type: 'toolNode',
      position: { x: 0, y: 0 },
      data: {
        name: n.name,
        category: n.platformDomain as UnifiedNodeCategory || 'warehouse',
        layer: 'WAREHOUSE' as PipelineLayer,
        toolType: n.toolType,
        assetCount: n.assetCount,
        healthSummary: n.healthSummary,
        isControlPlane: true,
        domainColor: DOMAIN_COLORS[n.platformDomain] || DOMAIN_COLORS.other,
      },
    }));

    const cpEdges: Edge[] = controlPlaneData.edges.map((e: CPEdge) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: e.dataFlowCount > 0,
      label: e.dataFlowCount > 0 ? `${e.dataFlowCount} flows` : 'connected',
      style: {
        stroke: e.dataFlowCount > 0 ? '#6366F180' : 'var(--text-faint)',
        strokeWidth: e.dataFlowCount > 0
          ? Math.min(2 + Math.log2(e.dataFlowCount + 1), 6)
          : 2,
        strokeDasharray: e.dataFlowCount > 0 ? undefined : '6,4',
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: e.dataFlowCount > 0 ? '#6366F1' : 'var(--text-faint)',
      },
    }));

    if (cpNodes.length === 0) return { cpFlowNodes: [], cpFlowEdges: [] };
    const layouted = getLayoutedElements(cpNodes, cpEdges, 'LR');
    return { cpFlowNodes: layouted.nodes, cpFlowEdges: layouted.edges };
  }, [controlPlaneData, renderedOverview]);

  // Pick the right flow data based on active tab
  const activeFlowNodes = activeTab === 'control-plane' ? cpFlowNodes : flowNodes;
  const activeFlowEdges = activeTab === 'control-plane' ? cpFlowEdges : flowEdges;

  const [nodes, setNodes, onNodesChange] = useNodesState(activeFlowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(activeFlowEdges);

  useEffect(() => {
    setNodes(activeFlowNodes);
    setEdges(activeFlowEdges);
  }, [activeFlowNodes, activeFlowEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, node: Node) => {
      if (activeTab === 'control-plane') {
        // For control plane, create a synthetic UnifiedLineageNode so the side panel works
        const cpNode = controlPlaneData?.nodes?.find((n: CPNode) => n.id === node.id);
        if (cpNode) {
          setSelectedNode({
            id: cpNode.id,
            name: cpNode.name,
            category: cpNode.platformDomain as UnifiedNodeCategory || 'warehouse',
            layer: 'WAREHOUSE',
            toolType: cpNode.toolType,
            integrationId: cpNode.integrationId,
          });
        }
      } else {
        // Rendered view uses raw engine IDs, unified data uses `lineage-` prefix
        const unifiedNode = lineageData?.nodes.find((n) => n.id === node.id)
          || lineageData?.nodes.find((n) => n.id === `lineage-${node.id}`);
        setSelectedNode(unifiedNode || null);
      }
      setSelectedEdge(null);
    },
    [lineageData?.nodes, activeTab, controlPlaneData?.nodes]
  );

  const handleEdgeClick = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      const unifiedEdge = lineageData?.edges.find((e) => e.id === edge.id);
      setSelectedEdge(unifiedEdge || null);
      setSelectedNode(null);
    },
    [lineageData?.edges]
  );

  // Navigate to a node from the detail panel (e.g. clicking an upstream/downstream node)
  const handleNavigateToNode = useCallback(
    (nodeId: string) => {
      const targetNode = lineageData?.nodes.find((n) => n.id === nodeId)
        || lineageData?.nodes.find((n) => n.id === `lineage-${nodeId}`);
      if (targetNode) {
        setSelectedNode(targetNode);
        setSelectedEdge(null);
      }
    },
    [lineageData?.nodes]
  );

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  if (loading && !lineageData) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 red-spinner" />
          <p className="text-sm text-[var(--muted)]">Loading lineage...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col -m-6">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[var(--subtle-border)] bg-[var(--surface-sunken)]">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-lg font-semibold text-[var(--text)]">Pipeline Lineage</h1>
            <p className="text-[13px] text-[var(--muted)]">
              Visualize your complete data pipeline from ingestion to reporting
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lineageData?.lastExtracted && (
              <span className="text-[12px] text-[var(--muted)]">
                Last extracted: {formatDate(lineageData.lastExtracted)}
              </span>
            )}
            <button
              onClick={extractLineage}
              disabled={extracting || !stackId}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:cursor-not-allowed text-white text-[13px] font-medium transition-colors"
            >
              {extracting ? (
                <>
                  <div className="w-4 h-4 red-spinner" />
                  Extracting...
                </>
              ) : (
                <>
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                    />
                  </svg>
                  Extract Lineage
                </>
              )}
            </button>
            <button
              onClick={extractWithLLM}
              disabled={llmExtracting || extracting || !stackId}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[13px] font-medium transition-all"
            >
              {llmExtracting ? (
                <>
                  <div className="w-4 h-4 red-spinner" />
                  AI Extracting...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  Extract with AI
                </>
              )}
            </button>
            {extracting && lineageData && (
              <span className="ml-2 px-2 py-1 text-[10px] bg-violet-500/20 text-violet-300 rounded-full animate-pulse">
                Updating...
              </span>
            )}
          </div>
        </div>

        {/* LLM extraction progress panel */}
        {llmExtracting && (
          <div className="mb-4 rounded-xl border border-violet-500/30 bg-violet-500/[0.06] p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-2 h-2 bg-violet-400 rounded-full animate-pulse" />
              <span className="text-[13px] font-medium text-violet-300">AI is analyzing your pipeline...</span>
              <span className="ml-auto text-[12px] text-[var(--muted)]">
                {llmNodeCount} nodes &middot; {llmEdgeCount} edges
              </span>
            </div>
            <div className="max-h-[160px] overflow-y-auto space-y-1 text-[11px] font-mono">
              {llmProgress.map((entry, i) => (
                <div key={i} className={`flex items-start gap-2 ${
                  entry.type === 'tool' ? 'text-blue-400/70' :
                  entry.type === 'node' ? 'text-emerald-400/70' :
                  entry.type === 'error' ? 'text-red-400/80' :
                  entry.type === 'complete' ? 'text-violet-300' :
                  'text-[var(--muted)]'
                }`}>
                  <span className="shrink-0 mt-0.5">
                    {entry.type === 'tool' ? '>' : entry.type === 'node' ? '+' : entry.type === 'error' ? '!' : entry.type === 'complete' ? '*' : '-'}
                  </span>
                  <span>{entry.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab bar */}
        <div className="flex items-center gap-1 mb-4">
          <button
            onClick={() => handleTabChange('data')}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all border
              ${activeTab === 'data'
                ? 'bg-indigo-500/15 border-indigo-500/30 text-indigo-300'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            Data Lineage
          </button>
          <button
            onClick={() => handleTabChange('control-plane')}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all border
              ${activeTab === 'control-plane'
                ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            Pipeline Overview
          </button>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-[var(--border-faint)]">
          {activeTab === 'control-plane' ? (
            <>
              <div className="text-center">
                <div className="text-xl font-semibold text-emerald-400">{laneOverview?.stats?.totalNodes ?? controlPlaneData?.stats?.tool_count ?? 0}</div>
                <div className="text-[11px] text-[var(--muted)]">Tools</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">{laneOverview?.stats?.totalEdges ?? controlPlaneData?.stats?.flow_count ?? 0}</div>
                <div className="text-[11px] text-[var(--muted)]">Data Flows</div>
              </div>
            </>
          ) : (
            <>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.toolNodes}</div>
                <div className="text-[11px] text-[var(--muted)]">Tools</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.tableNodes}</div>
                <div className="text-[11px] text-[var(--muted)]">Tables</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.viewNodes}</div>
                <div className="text-[11px] text-[var(--muted)]">Views</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.modelNodes}</div>
                <div className="text-[11px] text-[var(--muted)]">Models</div>
              </div>
            </>
          )}
          <div className="text-center">
            <div className="text-xl font-semibold text-[var(--text)]">
              {renderedView?.stats?.edgeCount || lineageData?.stats?.totalEdges || 0}
            </div>
            <div className="text-[11px] text-[var(--muted)]">Dependencies</div>
          </div>

        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="mx-6 mt-4 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-[13px]">
          {error}
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Canvas */}
        <div className="flex-1 relative">
          {activeTab === 'control-plane' && laneOverview ? (
            <LaneOverviewCanvas
              data={laneOverview}
              loading={controlPlaneLoading}
              onExtract={extractLineage}
              extracting={extracting}
              stackId={stackId}
            />
          ) : controlPlaneLoading && activeTab === 'control-plane' ? (
            <div className="flex items-center justify-center h-full">
              <div className="flex flex-col items-center gap-4">
                <div className="w-10 h-10 red-spinner" />
                <p className="text-sm text-[var(--muted)]">Loading pipeline overview...</p>
              </div>
            </div>
          ) : nodes.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              <svg
                className="w-16 h-16 text-[var(--text-faint)] mb-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                />
              </svg>
              {activeTab === 'control-plane' ? (
                <>
                  <p className="text-[var(--muted)] text-[15px] mb-2">No pipeline overview available</p>
                  <p className="text-[var(--text-faint)] text-[13px] mb-4">
                    Extract lineage from the Data Lineage tab first to generate the pipeline overview
                  </p>
                </>
              ) : lineageData && lineageData.nodes.length > 0 ? (
                <>
                  <p className="text-[var(--muted)] text-[15px] mb-2">No nodes match current filters</p>
                  <p className="text-[var(--text-faint)] text-[13px]">
                    Try adjusting the layer or node type filters
                  </p>
                </>
              ) : (
                <>
                  <p className="text-[var(--muted)] text-[15px] mb-2">No lineage data yet</p>
                  <p className="text-[var(--text-faint)] text-[13px] mb-4">
                    Configure your pipeline and click &quot;Extract Lineage&quot; to discover dependencies
                  </p>
                  <button
                    onClick={extractLineage}
                    disabled={extracting || !stackId}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 text-white text-[13px] font-medium"
                  >
                    {extracting ? 'Extracting...' : 'Extract Lineage'}
                  </button>
                </>
              )}
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              onEdgeClick={handleEdgeClick}
              nodeTypes={unifiedNodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.1}
              maxZoom={2}
              defaultEdgeOptions={{
                type: 'smoothstep',
              }}
              proOptions={{ hideAttribution: true }}
            >
              <Controls className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg [&>button]:!bg-[var(--subtle-bg)] [&>button]:!border-[var(--border-medium)] [&>button]:!text-[var(--text-tertiary)]" />
              <MiniMap
                nodeColor={(n) => {
                  const category = n.data.category as string;
                  if (CATEGORY_VISUALS[category as keyof typeof CATEGORY_VISUALS]) {
                    return CATEGORY_VISUALS[category as keyof typeof CATEGORY_VISUALS].color;
                  }
                  return '#6366F1';
                }}
                maskColor="var(--overlay-strong)"
                className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg"
              />
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={2}
                color="var(--text-faint)"
              />
            </ReactFlow>
          )}

          {/* Legend */}
          {nodes.length > 0 && (
            <div className="absolute bottom-4 left-4 flex flex-wrap items-center gap-3 px-3 py-2 bg-[var(--surface)]/80 backdrop-blur-sm rounded-lg border border-[var(--border-medium)] text-[10px] max-w-md">
              {activeTab === 'control-plane' ? (
                <>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#10B981' }} />
                    <span className="text-[var(--muted)]">Ingestion</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#6366F1' }} />
                    <span className="text-[var(--muted)]">Warehouse</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#F59E0B' }} />
                    <span className="text-[var(--muted)]">Transform</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#F97316' }} />
                    <span className="text-[var(--muted)]">Orchestration</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#06B6D4' }} />
                    <span className="text-[var(--muted)]">BI</span>
                  </div>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#6366F1' }} />
                    <span className="text-[var(--muted)]">Data Flow</span>
                  </div>
                </>
              ) : (
                <>
                  {/* Layer colors */}
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.INGESTION }} />
                    <span className="text-[var(--muted)]">Ingestion</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.TRANSFORMATION }} />
                    <span className="text-[var(--muted)]">Transform</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.WAREHOUSE }} />
                    <span className="text-[var(--muted)]">Warehouse</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.REPORTING }} />
                    <span className="text-[var(--muted)]">Reporting</span>
                  </div>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.table.color }} />
                    <span className="text-[var(--muted)]">Table</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.view.color }} />
                    <span className="text-[var(--muted)]">View</span>
                  </div>
                </>
              )}
              {/* Inferred legend (shows when rendered view has inferred nodes) */}
              {activeTab === 'data' && renderedView?.stats?.inferredNodeCount > 0 && (
                <>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ borderTop: '1.5px dashed #F59E0B' }} />
                    <span className="text-[var(--muted)]">Inferred</span>
                  </div>
                </>
              )}
              {/* Confidence legend (shows when engine data present, data tab) */}
              {activeTab === 'data' && lineageData?.engineStats && (
                <>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#10B981' }} />
                    <span className="text-[var(--muted)]">&ge;80%</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#F59E0B' }} />
                    <span className="text-[var(--muted)]">50-80%</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#EF4444' }} />
                    <span className="text-[var(--muted)]">&lt;50%</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Side panel - Edge evidence */}
        {selectedEdge && (
          <EdgeDetailPanel
            edge={selectedEdge}
            allNodes={lineageData?.nodes || []}
            onClose={() => setSelectedEdge(null)}
          />
        )}

        {/* Side panel - Control Plane tool details */}
        {activeTab === 'control-plane' && selectedNode && !selectedEdge && (() => {
          const cpNode = controlPlaneData?.nodes?.find((n: CPNode) => n.id === selectedNode.id);
          if (!cpNode) return null;
          const health = cpNode.healthSummary;
          const totalHealth = health.healthy + health.degraded + health.failing + health.unknown;
          return (
            <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-[var(--text)]">Tool Details</h3>
                <button onClick={() => setSelectedNode(null)} className="p-1 hover:bg-[var(--subtle-bg)] rounded">
                  <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-[var(--text)] font-mono mt-1">{cpNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{cpNode.toolType}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Domain</label>
                    <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{cpNode.platformDomain}</p>
                  </div>
                </div>
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Assets</label>
                  <p className="text-2xl font-semibold text-[var(--text)] mt-1">{cpNode.assetCount}</p>
                </div>
                {totalHealth > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Health Summary</label>
                    <div className="mt-2 space-y-2">
                      {health.healthy > 0 && (
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] text-emerald-400">Healthy</span>
                          <span className="text-[12px] text-[var(--text)]">{health.healthy}</span>
                        </div>
                      )}
                      {health.degraded > 0 && (
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] text-amber-400">Degraded</span>
                          <span className="text-[12px] text-[var(--text)]">{health.degraded}</span>
                        </div>
                      )}
                      {health.failing > 0 && (
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] text-red-400">Failing</span>
                          <span className="text-[12px] text-[var(--text)]">{health.failing}</span>
                        </div>
                      )}
                      {health.unknown > 0 && (
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] text-[var(--muted)]">Unknown</span>
                          <span className="text-[12px] text-[var(--text)]">{health.unknown}</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {/* Connected edges in control plane */}
                {(() => {
                  const connEdges = controlPlaneData?.edges?.filter(
                    (e: CPEdge) => e.source === cpNode.id || e.target === cpNode.id
                  ) || [];
                  if (connEdges.length === 0) return null;
                  const cpNodeMap = new Map((controlPlaneData?.nodes || []).map((n: CPNode) => [n.id, n]));
                  return (
                    <div>
                      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Flows ({connEdges.length})</label>
                      <div className="mt-2 space-y-1.5">
                        {connEdges.map((e: CPEdge) => {
                          const otherId = e.source === cpNode.id ? e.target : e.source;
                          const other = cpNodeMap.get(otherId);
                          const direction = e.source === cpNode.id ? '\u2192' : '\u2190';
                          return (
                            <div key={e.id} className="flex items-center justify-between px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                              <span className="text-[12px] text-[var(--text)] font-mono truncate">
                                {direction} {other?.name || otherId}
                              </span>
                              <span className="text-[10px] text-[var(--muted)] shrink-0 ml-2">{e.dataFlowCount} flows</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          );
        })()}

        {/* Side panel - Node details */}
        {activeTab !== 'control-plane' && selectedNode && !selectedEdge && (
          (selectedNode.category === 'dag' || selectedNode.category === 'task') ? (
            <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-[var(--text)]">
                  {selectedNode.category === 'dag' ? 'DAG Details' : 'Task Details'}
                </h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 hover:bg-[var(--subtle-bg)] rounded"
                >
                  <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-[var(--text)] font-mono mt-1 break-all">{selectedNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{selectedNode.category}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Layer</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.layer}</p>
                  </div>
                </div>

                {/* Run summary */}
                {selectedNode.runSummary && (
                  <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] space-y-3">
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Run Summary</label>
                    {selectedNode.runSummary.lastRunState && (
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`
                          px-2 py-0.5 text-[11px] font-medium rounded
                          ${selectedNode.runSummary.lastRunState === 'success'
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : selectedNode.runSummary.lastRunState === 'failed'
                            ? 'bg-red-500/20 text-red-300'
                            : 'bg-blue-500/20 text-blue-300'}
                        `}>
                          {selectedNode.runSummary.lastRunState}
                        </span>
                        {selectedNode.runSummary.lastRunDate && (
                          <span className="text-[11px] text-[var(--muted)]">
                            {new Date(selectedNode.runSummary.lastRunDate).toLocaleString()}
                          </span>
                        )}
                      </div>
                    )}
                    {selectedNode.runSummary.successRate !== undefined && (
                      <div>
                        <div className="flex items-center justify-between text-[11px] text-[var(--muted)] mb-1">
                          <span>Success Rate</span>
                          <span>{Math.round(selectedNode.runSummary.successRate)}%</span>
                        </div>
                        <div className="h-1.5 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${selectedNode.runSummary.successRate}%`,
                              backgroundColor: selectedNode.runSummary.successRate >= 80 ? '#10B981' : selectedNode.runSummary.successRate >= 60 ? '#F59E0B' : '#EF4444',
                            }}
                          />
                        </div>
                      </div>
                    )}
                    {selectedNode.runSummary.avgDurationMinutes !== undefined && (
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-[var(--muted)]">Avg Duration</span>
                        <span className="text-[11px] text-[var(--text)]">{selectedNode.runSummary.avgDurationMinutes.toFixed(1)} min</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Orchestration dependencies (control-plane edges) */}
                {(() => {
                  const allEdges = lineageData?.edges || [];
                  const nodeMap = new Map((lineageData?.nodes || []).map(n => [n.id, n]));

                  // For DAGs: tasks contained in this DAG
                  // For Tasks: upstream deps (what this depends on) + downstream deps (what depends on this)
                  const controlEdges = allEdges.filter(
                    e => e.plane === 'control' && (e.source === selectedNode.id || e.target === selectedNode.id)
                  );

                  if (selectedNode.category === 'dag') {
                    // DAG → show contained tasks
                    const tasks = controlEdges
                      .filter(e => e.source === selectedNode.id)
                      .map(e => nodeMap.get(e.target))
                      .filter((n): n is UnifiedLineageNode => !!n && n.category === 'task');

                    if (tasks.length === 0) return null;
                    return (
                      <div>
                        <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tasks ({tasks.length})</label>
                        <div className="mt-2 space-y-1.5">
                          {tasks.map(task => (
                            <button
                              key={task.id}
                              onClick={() => handleNavigateToNode(task.id)}
                              className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                            >
                              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                              <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{task.name}</span>
                              {task.runSummary?.lastRunState && (
                                <span className={`
                                  px-1.5 py-0.5 text-[10px] font-medium rounded
                                  ${task.runSummary.lastRunState === 'success' ? 'bg-emerald-500/20 text-emerald-300'
                                    : task.runSummary.lastRunState === 'failed' ? 'bg-red-500/20 text-red-300'
                                    : 'bg-blue-500/20 text-blue-300'}
                                `}>
                                  {task.runSummary.lastRunState}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  }

                  // Task: show parent DAG, upstream tasks, downstream tasks
                  const parentDag = controlEdges
                    .filter(e => e.target === selectedNode.id)
                    .map(e => nodeMap.get(e.source))
                    .find(n => n?.category === 'dag');

                  const upstreamTasks = controlEdges
                    .filter(e => e.target === selectedNode.id)
                    .map(e => nodeMap.get(e.source))
                    .filter((n): n is UnifiedLineageNode => !!n && n.category === 'task');

                  const downstreamTasks = controlEdges
                    .filter(e => e.source === selectedNode.id)
                    .map(e => nodeMap.get(e.target))
                    .filter((n): n is UnifiedLineageNode => !!n && n.category === 'task');

                  const hasAny = parentDag || upstreamTasks.length > 0 || downstreamTasks.length > 0;
                  if (!hasAny) return null;

                  return (
                    <div className="space-y-3">
                      {parentDag && (
                        <div>
                          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Parent DAG</label>
                          <button
                            onClick={() => handleNavigateToNode(parentDag.id)}
                            className="w-full flex items-center gap-2 px-2 py-1.5 mt-1 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                          >
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.dag.color }} />
                            <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{parentDag.name}</span>
                          </button>
                        </div>
                      )}
                      {upstreamTasks.length > 0 && (
                        <div>
                          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Depends On ({upstreamTasks.length})</label>
                          <div className="mt-2 space-y-1.5">
                            {upstreamTasks.map(task => (
                              <button
                                key={task.id}
                                onClick={() => handleNavigateToNode(task.id)}
                                className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{task.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                      {downstreamTasks.length > 0 && (
                        <div>
                          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Required By ({downstreamTasks.length})</label>
                          <div className="mt-2 space-y-1.5">
                            {downstreamTasks.map(task => (
                              <button
                                key={task.id}
                                onClick={() => handleNavigateToNode(task.id)}
                                className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{task.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Cross-linked data assets with data-plane lineage context */}
                {(() => {
                  const allEdges = lineageData?.edges || [];
                  const crossEdges = allEdges.filter(
                    e => e.plane === 'cross' && (e.source === selectedNode.id || e.target === selectedNode.id)
                  );
                  if (crossEdges.length === 0) return null;
                  const nodeMap = new Map((lineageData?.nodes || []).map(n => [n.id, n]));
                  return (
                    <div>
                      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Assets ({crossEdges.length})</label>
                      <div className="mt-2 space-y-2">
                        {crossEdges.map(edge => {
                          const linkedId = edge.source === selectedNode.id ? edge.target : edge.source;
                          const linked = nodeMap.get(linkedId);
                          if (!linked) return null;

                          // Find data-plane neighbors of this linked table
                          const dataUpstream = allEdges
                            .filter(e => e.plane === 'data' && e.target === linkedId)
                            .map(e => nodeMap.get(e.source))
                            .filter((n): n is UnifiedLineageNode => !!n);
                          const dataDownstream = allEdges
                            .filter(e => e.plane === 'data' && e.source === linkedId)
                            .map(e => nodeMap.get(e.target))
                            .filter((n): n is UnifiedLineageNode => !!n);

                          return (
                            <div key={edge.id} className="p-2 rounded-lg bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                              <button
                                onClick={() => handleNavigateToNode(linkedId)}
                                className="w-full flex items-center gap-2 text-left"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS[linked.category]?.color || '#6366F1' }} />
                                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{linked.name}</span>
                                <span className="text-[10px] text-[var(--text-faint)] capitalize">{edge.edgeType.replace(/_/g, ' ')}</span>
                              </button>
                              {/* Data-plane lineage for this asset */}
                              {(dataUpstream.length > 0 || dataDownstream.length > 0) && (
                                <div className="mt-1.5 pt-1.5 border-t border-[var(--border-faint)] space-y-1">
                                  {dataUpstream.length > 0 && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-[10px] text-[var(--text-faint)] shrink-0 mt-0.5">from</span>
                                      <div className="flex flex-wrap gap-1">
                                        {dataUpstream.map(n => (
                                          <button
                                            key={n.id}
                                            onClick={() => handleNavigateToNode(n.id)}
                                            className="px-1.5 py-0.5 text-[10px] text-blue-300/70 bg-blue-500/10 rounded hover:bg-blue-500/20 transition-colors font-mono truncate max-w-[120px]"
                                          >
                                            {n.name}
                                          </button>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {dataDownstream.length > 0 && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-[10px] text-[var(--text-faint)] shrink-0 mt-0.5">to</span>
                                      <div className="flex flex-wrap gap-1">
                                        {dataDownstream.map(n => (
                                          <button
                                            key={n.id}
                                            onClick={() => handleNavigateToNode(n.id)}
                                            className="px-1.5 py-0.5 text-[10px] text-emerald-300/70 bg-emerald-500/10 rounded hover:bg-emerald-500/20 transition-colors font-mono truncate max-w-[120px]"
                                          >
                                            {n.name}
                                          </button>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

                {selectedNode.description && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Description</label>
                    <p className="text-[13px] text-[var(--text-tertiary)] mt-1">{selectedNode.description}</p>
                  </div>
                )}
                {selectedNode.owner && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Owner</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.owner}</p>
                  </div>
                )}
                {selectedNode.tags && selectedNode.tags.length > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tags</label>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {selectedNode.tags.map(tag => (
                        <span key={tag} className="px-2 py-0.5 text-[10px] bg-[var(--overlay-medium)] text-[var(--text-tertiary)] rounded">{tag}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : isToolCategory(selectedNode.category) ? (
            <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-[var(--text)]">Tool Details</h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 hover:bg-[var(--subtle-bg)] rounded"
                >
                  <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-[var(--text)] font-mono mt-1 break-all">{selectedNode.fullName || selectedNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{selectedNode.category}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Layer</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.layer}</p>
                  </div>
                </div>
                {selectedNode.toolType && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tool Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.toolType}</p>
                  </div>
                )}
                {selectedNode.status && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Status</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.status}</p>
                  </div>
                )}
                {selectedNode.healthScore !== undefined && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Health Score</label>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="flex-1 h-2 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${selectedNode.healthScore}%`,
                            backgroundColor: selectedNode.healthScore >= 80 ? '#10B981' : selectedNode.healthScore >= 60 ? '#F59E0B' : '#EF4444',
                          }}
                        />
                      </div>
                      <span className="text-[13px] text-[var(--text)]">{Math.round(selectedNode.healthScore)}%</span>
                    </div>
                  </div>
                )}
                {(selectedNode.findingsCount ?? 0) > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Findings</label>
                    <div className="flex items-center gap-2 mt-1">
                      {(selectedNode.criticalCount ?? 0) > 0 && (
                        <span className="px-2 py-1 text-[11px] bg-red-500/20 text-red-400 rounded">{selectedNode.criticalCount} Critical</span>
                      )}
                      {(selectedNode.highCount ?? 0) > 0 && (
                        <span className="px-2 py-1 text-[11px] bg-orange-500/20 text-orange-400 rounded">{selectedNode.highCount} High</span>
                      )}
                    </div>
                  </div>
                )}
                {selectedNode.description && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Description</label>
                    <p className="text-[13px] text-[var(--text-tertiary)] mt-1">{selectedNode.description}</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <DataAssetDetailPanel
              key={selectedNode.id}
              node={selectedNode}
              allNodes={panelNodes}
              allEdges={panelEdges}
              stackId={stackId || ''}
              onClose={() => setSelectedNode(null)}
              onNodeNavigate={handleNavigateToNode}
            />
          )
        )}
      </div>
    </div>
  );
}
