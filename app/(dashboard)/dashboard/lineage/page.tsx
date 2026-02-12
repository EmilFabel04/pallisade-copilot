'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
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
  type EngineCoverageStats,
  getDefaultFilterState,
  isToolCategory,
  nodePassesFilter,
  edgePassesFilter,
  getConfidenceColor,
  CATEGORY_VISUALS,
} from '@/components/lineage/types';

// Dagre layout with layer-aware sizing
const getLayoutedElements = (
  nodes: Node[],
  edges: Edge[]
): { nodes: Node[]; edges: Edge[] } => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: 'LR',
    nodesep: 60,
    ranksep: 180,
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

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const isToolNode = node.type === 'toolNode';
    const width = isToolNode ? 220 : 170;
    const height = isToolNode ? 90 : 65;
    return {
      ...node,
      targetPosition: Position.Left,
      sourcePosition: Position.Right,
      position: {
        x: nodeWithPosition.x - width / 2,
        y: nodeWithPosition.y - height / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

// Get edge style based on type
function getEdgeStyle(edge: UnifiedLineageEdge, sourceNode?: UnifiedLineageNode) {
  const edgeType = edge.edgeType;

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

  // Fetch unified lineage data
  const fetchLineage = useCallback(async () => {
    if (!stackId) return;

    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      // Note: We apply filters client-side for faster UX, but could pass to server
      const res = await fetch(`/api/pipeline/${stackId}/lineage/unified`);
      if (res.ok) {
        const data: UnifiedLineageResponse = await res.json();
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
      setError('Failed to connect to server');
    } finally {
      setLoading(false);
    }
  }, [stackId]);

  useEffect(() => {
    if (stackId) {
      fetchLineage();
    }
  }, [stackId, fetchLineage]);

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
          // Refresh unified lineage data
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

  // Filter edges to only include those between visible nodes
  const filteredEdges = useMemo(() => {
    if (!lineageData?.edges) return [];
    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    return lineageData.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
  }, [filteredNodes, lineageData?.edges]);

  // Build filtered stats
  const filteredStats = useMemo(() => {
    return {
      toolNodes: filteredNodes.filter((n) => isToolCategory(n.category)).length,
      tableNodes: filteredNodes.filter((n) => n.category === 'table').length,
      viewNodes: filteredNodes.filter((n) => n.category === 'view').length,
      modelNodes: filteredNodes.filter((n) => n.category === 'model' || n.category === 'source')
        .length,
    };
  }, [filteredNodes]);

  // Build React Flow nodes and edges
  const { flowNodes, flowEdges } = useMemo(() => {
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
      },
    }));

    // Filter and convert edges (apply node membership + engine-level filters)
    const edges: Edge[] = (lineageData?.edges || [])
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target) && edgePassesFilter(e, filters))
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

    const layouted = getLayoutedElements(nodes, edges);
    return { flowNodes: layouted.nodes, flowEdges: layouted.edges };
  }, [filteredNodes, lineageData?.edges, filters]);

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

        {/* Filter bar */}
        <LineageFilterBar
          filters={filters}
          onChange={setFilters}
          availableLayers={lineageData?.availableLayers || []}
          stats={filteredStats}
        />

        {/* Stats */}
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-white/[0.04]">
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
          <div className="text-center">
            <div className="text-xl font-semibold text-white">
              {lineageData?.stats?.totalEdges || 0}
            </div>
            <div className="text-[11px] text-white/40">Dependencies</div>
          </div>

          {/* Engine coverage stats (when available) */}
          {lineageData?.engineStats && (
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
                    Try adjusting the layer or node type filters
                  </p>
                </>
              ) : (
                <>
                  <p className="text-white/50 text-[15px] mb-2">No lineage data yet</p>
                  <p className="text-white/30 text-[13px] mb-4">
                    Configure your pipeline and click "Extract Lineage" to discover dependencies
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
              {/* Layer colors */}
              <div className="flex items-center gap-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: LAYER_COLORS.INGESTION }}
                />
                <span className="text-white/50">Ingestion</span>
              </div>
              <div className="flex items-center gap-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: LAYER_COLORS.TRANSFORMATION }}
                />
                <span className="text-white/50">Transform</span>
              </div>
              <div className="flex items-center gap-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: LAYER_COLORS.WAREHOUSE }}
                />
                <span className="text-white/50">Warehouse</span>
              </div>
              <div className="flex items-center gap-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: LAYER_COLORS.REPORTING }}
                />
                <span className="text-white/50">Reporting</span>
              </div>
              <div className="w-px h-3 bg-white/20" />
              {/* Data asset types */}
              <div className="flex items-center gap-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: CATEGORY_VISUALS.table.color }}
                />
                <span className="text-white/50">Table</span>
              </div>
              <div className="flex items-center gap-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: CATEGORY_VISUALS.view.color }}
                />
                <span className="text-white/50">View</span>
              </div>
              {/* Confidence legend (shows when engine data present) */}
              {lineageData?.engineStats && (
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
          isToolCategory(selectedNode.category) ? (
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
              node={selectedNode}
              allNodes={filteredNodes}
              allEdges={filteredEdges}
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
