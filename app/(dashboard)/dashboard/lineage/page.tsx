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
import { LineageFilterBar } from '@/components/lineage/LineageFilterBar';
import { DataAssetDetailPanel } from '@/components/lineage/DataAssetDetailPanel';
import { EdgeDetailPanel } from '@/components/lineage/EdgeDetailPanel';
import {
  type UnifiedLineageNode,
  type UnifiedLineageEdge,
  type UnifiedLineageResponse,
  type LineageFilterState,
  type LineageViewTab,
  type EngineCoverageStats,
  getDefaultFilterState,
  isToolCategory,
  isDataAssetCategory,
  nodePassesFilter,
  edgePassesFilter,
  getConfidenceColor,
  CATEGORY_VISUALS,
} from '@/components/lineage/types';

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

export default function LineagePage() {
  const { selectedPipelineId: stackId, loading: pipelineLoading } = usePipeline();
  const [lineageData, setLineageData] = useState<UnifiedLineageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<UnifiedLineageNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<UnifiedLineageEdge | null>(null);
  const [filters, setFilters] = useState<LineageFilterState>(getDefaultFilterState());
  const [activeTab, setActiveTab] = useState<LineageViewTab>('data');
  const [showOrchOverlay, setShowOrchOverlay] = useState(false);

  // Track fetch version to ignore stale responses on rapid tab switches
  const fetchVersionRef = useRef(0);

  // Fetch unified lineage data
  const fetchLineage = useCallback(async () => {
    if (!stackId) return;

    const thisVersion = ++fetchVersionRef.current;
    setLoading(true);
    setError(null);

    try {
      const plane = activeTab === 'orchestration'
        ? 'control'
        : showOrchOverlay
        ? 'all'
        : 'data';
      const res = await fetch(`/api/pipeline/${stackId}/lineage/unified?plane=${plane}`);

      // Ignore stale response if a newer fetch has started
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
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'Failed to fetch lineage');
      }
    } catch (err) {
      if (fetchVersionRef.current !== thisVersion) return;
      setError('Failed to connect to server');
    } finally {
      if (fetchVersionRef.current === thisVersion) {
        setLoading(false);
      }
    }
  }, [stackId, activeTab, showOrchOverlay]);

  useEffect(() => {
    if (stackId) {
      fetchLineage();
    }
  }, [stackId, fetchLineage]);

  // Clear selection when switching tabs
  const handleTabChange = useCallback((tab: LineageViewTab) => {
    setActiveTab(tab);
    setSelectedNode(null);
    setSelectedEdge(null);
    setLineageData(null); // Clear stale data to prevent wrong-layout flash
  }, []);

  // Extract lineage from warehouse (uses original endpoint)
  const extractLineage = async () => {
    if (!stackId) return;

    setExtracting(true);
    setError(null);

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
        if (result.success) {
          // Clear stale data before re-fetch to prevent jumpy transition
          setLineageData(null);
          await fetchLineage();
        } else {
          setError(result.results?.[0]?.error || 'Extraction failed');
        }
      } else {
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'Extraction request failed');
      }
    } catch (err) {
      setError('Failed to extract lineage');
    } finally {
      setExtracting(false);
    }
  };

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

  // Build React Flow nodes and edges
  const { flowNodes, flowEdges } = useMemo(() => {
    if (!filteredNodes.length) return { flowNodes: [], flowEdges: [] };

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const nodeMap = new Map(filteredNodes.map((n) => [n.id, n]));

    // Determine if node is an overlay orchestration node (data tab + overlay on)
    const isOverlayNode = (n: UnifiedLineageNode) =>
      activeTab === 'data' && showOrchOverlay &&
      (n.category === 'dag' || n.category === 'task');

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
        // Overlay flag for orchestration nodes on data tab
        isOverlay: isOverlayNode(node),
      },
    }));

    // Only render edges matching the active plane in the graph.
    // All edges (including other planes) remain in lineageData for the detail panel.
    const isDisplayPlane = (e: UnifiedLineageEdge): boolean => {
      if (activeTab === 'orchestration') {
        // Orchestration graph: control + cross edges only
        return e.plane === 'control' || e.plane === 'cross';
      }
      // Data graph: everything except pure control-plane edges
      // (pipeline/synthetic edges have no plane field — always show them)
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

    const direction = activeTab === 'orchestration' ? 'TB' : 'LR';
    const layouted = getLayoutedElements(nodes, edges, direction);
    return { flowNodes: layouted.nodes, flowEdges: layouted.edges };
  }, [filteredNodes, lineageData?.edges, filters, activeTab, showOrchOverlay]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, node: Node) => {
      const unifiedNode = lineageData?.nodes.find((n) => n.id === node.id);
      setSelectedNode(unifiedNode || null);
      setSelectedEdge(null);
    },
    [lineageData?.nodes]
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
      const targetNode = lineageData?.nodes.find((n) => n.id === nodeId);
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
          <div className="w-10 h-10 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-white/50">Loading lineage...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col -m-6">
      {/* Header */}
      <div className="px-6 py-4 border-b border-white/[0.06] bg-[#030303]">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-lg font-semibold text-white">Pipeline Lineage</h1>
            <p className="text-[13px] text-white/50">
              Visualize your complete data pipeline from ingestion to reporting
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lineageData?.lastExtracted && (
              <span className="text-[12px] text-white/40">
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
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
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
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex items-center gap-1 mb-4">
          <button
            onClick={() => handleTabChange('data')}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all border
              ${activeTab === 'data'
                ? 'bg-indigo-500/15 border-indigo-500/30 text-indigo-300'
                : 'border-transparent text-white/40 hover:text-white/60 hover:bg-white/[0.04]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            Data Lineage
          </button>
          <button
            onClick={() => handleTabChange('orchestration')}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all border
              ${activeTab === 'orchestration'
                ? 'bg-orange-500/15 border-orange-500/30 text-orange-300'
                : 'border-transparent text-white/40 hover:text-white/60 hover:bg-white/[0.04]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            Orchestration
          </button>
        </div>

        {/* Filter bar */}
        <LineageFilterBar
          filters={filters}
          onChange={setFilters}
          availableLayers={lineageData?.availableLayers || []}
          stats={filteredStats}
          activeTab={activeTab}
          showOrchOverlay={showOrchOverlay}
          onOrchOverlayToggle={() => setShowOrchOverlay((prev) => !prev)}
        />

        {/* Stats */}
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-white/[0.04]">
          {activeTab === 'data' ? (
            <>
              <div className="text-center">
                <div className="text-xl font-semibold text-white">{filteredStats.toolNodes}</div>
                <div className="text-[11px] text-white/40">Tools</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-white">{filteredStats.tableNodes}</div>
                <div className="text-[11px] text-white/40">Tables</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-white">{filteredStats.viewNodes}</div>
                <div className="text-[11px] text-white/40">Views</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-white">{filteredStats.modelNodes}</div>
                <div className="text-[11px] text-white/40">Models</div>
              </div>
              {(filteredStats.dagNodes + filteredStats.taskNodes) > 0 && (
                <div className="text-center">
                  <div className="text-xl font-semibold text-white">
                    {filteredStats.dagNodes + filteredStats.taskNodes}
                  </div>
                  <div className="text-[11px] text-white/40">Orchestration</div>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="text-center">
                <div className="text-xl font-semibold text-orange-400">{filteredStats.dagNodes}</div>
                <div className="text-[11px] text-white/40">DAGs</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-orange-300">{filteredStats.taskNodes}</div>
                <div className="text-[11px] text-white/40">Tasks</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-white">
                  {filteredStats.tableNodes + filteredStats.viewNodes}
                </div>
                <div className="text-[11px] text-white/40">Linked Assets</div>
              </div>
            </>
          )}
          <div className="text-center">
            <div className="text-xl font-semibold text-white">
              {lineageData?.stats?.totalEdges || 0}
            </div>
            <div className="text-[11px] text-white/40">Dependencies</div>
          </div>

          {/* Engine coverage stats (when available, data tab only) */}
          {activeTab === 'data' && lineageData?.engineStats && (
            <>
              <div className="w-px h-8 bg-white/10" />
              <div className="text-center">
                <div className="text-xl font-semibold text-emerald-400">
                  {Math.round(lineageData.engineStats.coverageTable * 100)}%
                </div>
                <div className="text-[11px] text-white/40">Table Coverage</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-violet-400">
                  {Math.round(lineageData.engineStats.coverageColumn * 100)}%
                </div>
                <div className="text-[11px] text-white/40">Column Coverage</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-emerald-400">
                  {Math.round(lineageData.engineStats.highConfidencePct * 100)}%
                </div>
                <div className="text-[11px] text-white/40">High Confidence</div>
              </div>
            </>
          )}
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
          {nodes.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              <svg
                className="w-16 h-16 text-white/20 mb-4"
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
              {lineageData && lineageData.nodes.length > 0 ? (
                <>
                  <p className="text-white/50 text-[15px] mb-2">No nodes match current filters</p>
                  <p className="text-white/30 text-[13px]">
                    {activeTab === 'orchestration'
                      ? 'No orchestration data available. Connect Airflow to see DAGs and tasks.'
                      : 'Try adjusting the layer or node type filters'}
                  </p>
                </>
              ) : (
                <>
                  <p className="text-white/50 text-[15px] mb-2">
                    {activeTab === 'orchestration' ? 'No orchestration data' : 'No lineage data yet'}
                  </p>
                  <p className="text-white/30 text-[13px] mb-4">
                    {activeTab === 'orchestration'
                      ? 'Connect an Airflow instance to your pipeline to see DAG and task graphs'
                      : 'Configure your pipeline and click "Extract Lineage" to discover dependencies'}
                  </p>
                  {activeTab === 'data' && (
                    <button
                      onClick={extractLineage}
                      disabled={extracting || !stackId}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 text-white text-[13px] font-medium"
                    >
                      {extracting ? 'Extracting...' : 'Extract Lineage'}
                    </button>
                  )}
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
              <Controls className="!bg-white/5 !border-white/10 !rounded-lg [&>button]:!bg-white/5 [&>button]:!border-white/10 [&>button]:!text-white/60" />
              <MiniMap
                nodeColor={(n) => {
                  const category = n.data.category as string;
                  if (CATEGORY_VISUALS[category as keyof typeof CATEGORY_VISUALS]) {
                    return CATEGORY_VISUALS[category as keyof typeof CATEGORY_VISUALS].color;
                  }
                  return '#6366F1';
                }}
                maskColor="rgba(0,0,0,0.8)"
                className="!bg-white/5 !border-white/10 !rounded-lg"
              />
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={2}
                color="rgba(255,255,255,0.15)"
              />
            </ReactFlow>
          )}

          {/* Legend */}
          {nodes.length > 0 && (
            <div className="absolute bottom-4 left-4 flex flex-wrap items-center gap-3 px-3 py-2 bg-black/60 backdrop-blur-sm rounded-lg border border-white/10 text-[10px] max-w-md">
              {activeTab === 'data' ? (
                <>
                  {/* Layer colors */}
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.INGESTION }} />
                    <span className="text-white/50">Ingestion</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.TRANSFORMATION }} />
                    <span className="text-white/50">Transform</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.WAREHOUSE }} />
                    <span className="text-white/50">Warehouse</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.REPORTING }} />
                    <span className="text-white/50">Reporting</span>
                  </div>
                  <div className="w-px h-3 bg-white/20" />
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.table.color }} />
                    <span className="text-white/50">Table</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.view.color }} />
                    <span className="text-white/50">View</span>
                  </div>
                </>
              ) : (
                <>
                  {/* Orchestration legend */}
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.dag.color }} />
                    <span className="text-white/50">DAG</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                    <span className="text-white/50">Task</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.table.color }} />
                    <span className="text-white/50">Linked Table</span>
                  </div>
                  <div className="w-px h-3 bg-white/20" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: LAYER_COLORS.ORCHESTRATION }} />
                    <span className="text-white/50">Control</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded border border-dashed border-orange-400/50" />
                    <span className="text-white/50">Cross-link</span>
                  </div>
                </>
              )}
              {/* Confidence legend (shows when engine data present, data tab) */}
              {activeTab === 'data' && lineageData?.engineStats && (
                <>
                  <div className="w-px h-3 bg-white/20" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#10B981' }} />
                    <span className="text-white/50">&ge;80%</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#F59E0B' }} />
                    <span className="text-white/50">50-80%</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#EF4444' }} />
                    <span className="text-white/50">&lt;50%</span>
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

        {/* Side panel - Node details */}
        {selectedNode && !selectedEdge && (
          (selectedNode.category === 'dag' || selectedNode.category === 'task') ? (
            <div className="w-80 border-l border-white/[0.06] bg-[#030303] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-white">
                  {selectedNode.category === 'dag' ? 'DAG Details' : 'Task Details'}
                </h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 hover:bg-white/[0.05] rounded"
                >
                  <svg className="w-4 h-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-white font-mono mt-1 break-all">{selectedNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-white mt-1 capitalize">{selectedNode.category}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Layer</label>
                    <p className="text-[13px] text-white mt-1">{selectedNode.layer}</p>
                  </div>
                </div>

                {/* Run summary */}
                {selectedNode.runSummary && (
                  <div className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06] space-y-3">
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Run Summary</label>
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
                          <span className="text-[11px] text-white/40">
                            {new Date(selectedNode.runSummary.lastRunDate).toLocaleString()}
                          </span>
                        )}
                      </div>
                    )}
                    {selectedNode.runSummary.successRate !== undefined && (
                      <div>
                        <div className="flex items-center justify-between text-[11px] text-white/50 mb-1">
                          <span>Success Rate</span>
                          <span>{Math.round(selectedNode.runSummary.successRate)}%</span>
                        </div>
                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
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
                        <span className="text-[11px] text-white/40">Avg Duration</span>
                        <span className="text-[11px] text-white">{selectedNode.runSummary.avgDurationMinutes.toFixed(1)} min</span>
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
                        <label className="text-[11px] text-white/40 uppercase tracking-wide">Tasks ({tasks.length})</label>
                        <div className="mt-2 space-y-1.5">
                          {tasks.map(task => (
                            <button
                              key={task.id}
                              onClick={() => handleNavigateToNode(task.id)}
                              className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-white/[0.03] hover:bg-white/[0.06] text-left transition-colors"
                            >
                              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                              <span className="text-[12px] text-white font-mono truncate flex-1">{task.name}</span>
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
                          <label className="text-[11px] text-white/40 uppercase tracking-wide">Parent DAG</label>
                          <button
                            onClick={() => handleNavigateToNode(parentDag.id)}
                            className="w-full flex items-center gap-2 px-2 py-1.5 mt-1 rounded bg-white/[0.03] hover:bg-white/[0.06] text-left transition-colors"
                          >
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.dag.color }} />
                            <span className="text-[12px] text-white font-mono truncate flex-1">{parentDag.name}</span>
                          </button>
                        </div>
                      )}
                      {upstreamTasks.length > 0 && (
                        <div>
                          <label className="text-[11px] text-white/40 uppercase tracking-wide">Depends On ({upstreamTasks.length})</label>
                          <div className="mt-2 space-y-1.5">
                            {upstreamTasks.map(task => (
                              <button
                                key={task.id}
                                onClick={() => handleNavigateToNode(task.id)}
                                className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-white/[0.03] hover:bg-white/[0.06] text-left transition-colors"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                                <span className="text-[12px] text-white font-mono truncate flex-1">{task.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                      {downstreamTasks.length > 0 && (
                        <div>
                          <label className="text-[11px] text-white/40 uppercase tracking-wide">Required By ({downstreamTasks.length})</label>
                          <div className="mt-2 space-y-1.5">
                            {downstreamTasks.map(task => (
                              <button
                                key={task.id}
                                onClick={() => handleNavigateToNode(task.id)}
                                className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-white/[0.03] hover:bg-white/[0.06] text-left transition-colors"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                                <span className="text-[12px] text-white font-mono truncate flex-1">{task.name}</span>
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
                      <label className="text-[11px] text-white/40 uppercase tracking-wide">Data Assets ({crossEdges.length})</label>
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
                            <div key={edge.id} className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                              <button
                                onClick={() => handleNavigateToNode(linkedId)}
                                className="w-full flex items-center gap-2 text-left"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS[linked.category]?.color || '#6366F1' }} />
                                <span className="text-[12px] text-white font-mono truncate flex-1">{linked.name}</span>
                                <span className="text-[10px] text-white/30 capitalize">{edge.edgeType.replace(/_/g, ' ')}</span>
                              </button>
                              {/* Data-plane lineage for this asset */}
                              {(dataUpstream.length > 0 || dataDownstream.length > 0) && (
                                <div className="mt-1.5 pt-1.5 border-t border-white/[0.04] space-y-1">
                                  {dataUpstream.length > 0 && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-[10px] text-white/30 shrink-0 mt-0.5">from</span>
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
                                      <span className="text-[10px] text-white/30 shrink-0 mt-0.5">to</span>
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
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Description</label>
                    <p className="text-[13px] text-white/70 mt-1">{selectedNode.description}</p>
                  </div>
                )}
                {selectedNode.owner && (
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Owner</label>
                    <p className="text-[13px] text-white mt-1">{selectedNode.owner}</p>
                  </div>
                )}
                {selectedNode.tags && selectedNode.tags.length > 0 && (
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Tags</label>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {selectedNode.tags.map(tag => (
                        <span key={tag} className="px-2 py-0.5 text-[10px] bg-white/10 text-white/60 rounded">{tag}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : isToolCategory(selectedNode.category) ? (
            <div className="w-80 border-l border-white/[0.06] bg-[#030303] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-white">Tool Details</h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 hover:bg-white/[0.05] rounded"
                >
                  <svg className="w-4 h-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-white font-mono mt-1 break-all">{selectedNode.fullName || selectedNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-white mt-1 capitalize">{selectedNode.category}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Layer</label>
                    <p className="text-[13px] text-white mt-1">{selectedNode.layer}</p>
                  </div>
                </div>
                {selectedNode.toolType && (
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Tool Type</label>
                    <p className="text-[13px] text-white mt-1">{selectedNode.toolType}</p>
                  </div>
                )}
                {selectedNode.status && (
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Status</label>
                    <p className="text-[13px] text-white mt-1">{selectedNode.status}</p>
                  </div>
                )}
                {selectedNode.healthScore !== undefined && (
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Health Score</label>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${selectedNode.healthScore}%`,
                            backgroundColor: selectedNode.healthScore >= 80 ? '#10B981' : selectedNode.healthScore >= 60 ? '#F59E0B' : '#EF4444',
                          }}
                        />
                      </div>
                      <span className="text-[13px] text-white">{Math.round(selectedNode.healthScore)}%</span>
                    </div>
                  </div>
                )}
                {(selectedNode.findingsCount ?? 0) > 0 && (
                  <div>
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Findings</label>
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
                    <label className="text-[11px] text-white/40 uppercase tracking-wide">Description</label>
                    <p className="text-[13px] text-white/70 mt-1">{selectedNode.description}</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <DataAssetDetailPanel
              key={selectedNode.id}
              node={selectedNode}
              allNodes={lineageData?.nodes || []}
              allEdges={lineageData?.edges || []}
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
