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
  Handle,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import { usePipeline } from '@/contexts/PipelineContext';

interface LineageNode {
  id: string;
  name: string;
  tableName: string;
  database?: string;
  schema?: string;
  nodeType: string;
  criticality: string;
  rowCount?: number;
  upstreamCount: number;
  downstreamCount: number;
}

interface LineageEdge {
  id: string;
  source: string;
  target: string;
  edgeType: string;
  columns?: string[];
}

interface LineageData {
  nodes: LineageNode[];
  edges: LineageEdge[];
  stats: {
    totalNodes: number;
    totalEdges: number;
  };
  lastExtracted?: string;
}

// Custom Node Component
function TableNode({ data }: { data: any }) {
  const nodeType = data.nodeType || 'table';
  const criticality = data.criticality || 'MEDIUM';

  const typeColors: Record<string, { bg: string; border: string; icon: string }> = {
    table: { bg: 'bg-blue-500/20', border: 'border-blue-500/40', icon: '🗃️' },
    view: { bg: 'bg-purple-500/20', border: 'border-purple-500/40', icon: '👁️' },
    source: { bg: 'bg-emerald-500/20', border: 'border-emerald-500/40', icon: '📥' },
    model: { bg: 'bg-orange-500/20', border: 'border-orange-500/40', icon: '⚙️' },
  };

  const colors = typeColors[nodeType] || typeColors.table;
  const shortName = data.label?.split('.').pop() || data.label;

  return (
    <div
      className={`px-3 py-2 rounded-lg border ${colors.bg} ${colors.border} min-w-[120px] max-w-[180px] hover:scale-105 transition-transform cursor-pointer shadow-lg relative`}
      title={data.label}
    >
      {/* Input handle (left side - for incoming edges) */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-3 !h-3 !bg-indigo-500 !border-2 !border-indigo-300"
      />
      
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm">{colors.icon}</span>
        <span className="text-[10px] uppercase text-white/50 font-medium">{nodeType}</span>
      </div>
      <div className="text-sm font-mono text-white truncate">{shortName}</div>
      <div className="flex items-center gap-2 mt-1 text-[10px] text-white/40">
        {data.upstreamCount > 0 && <span>↑{data.upstreamCount}</span>}
        {data.downstreamCount > 0 && <span>↓{data.downstreamCount}</span>}
        {data.rowCount && <span>{data.rowCount.toLocaleString()} rows</span>}
      </div>
      
      {/* Output handle (right side - for outgoing edges) */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-3 !h-3 !bg-indigo-500 !border-2 !border-indigo-300"
      />
    </div>
  );
}

const nodeTypes = { tableNode: TableNode };

// Dagre layout
const getLayoutedElements = (nodes: Node[], edges: Edge[]) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 150 });

  const nodeWidth = 160;
  const nodeHeight = 70;

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      targetPosition: Position.Left,
      sourcePosition: Position.Right,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

export default function LineagePage() {
  const { selectedPipelineId: stackId, selectedPipeline, loading: pipelineLoading } = usePipeline();
  const [lineageData, setLineageData] = useState<LineageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<LineageNode | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch lineage data
  const fetchLineage = useCallback(async () => {
    if (!stackId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`/api/pipeline/${stackId}/lineage`);
      if (res.ok) {
        const data = await res.json();
        setLineageData(data);
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

  // Clear existing lineage data
  const clearLineage = async () => {
    if (!stackId) return;
    
    try {
      await fetch(`/api/pipeline/${stackId}/lineage`, {
        method: 'DELETE',
      });
    } catch (err) {
      console.error('Failed to clear lineage:', err);
    }
  };

  // Extract lineage from warehouse (clears first to avoid duplicates)
  const extractLineage = async () => {
    if (!stackId) return;
    
    setExtracting(true);
    setError(null);
    
    try {
      // Clear existing lineage first
      await clearLineage();
      
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
          // Refresh lineage data
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

  // Filter nodes by search
  const filteredNodes = useMemo(() => {
    if (!lineageData?.nodes) return [];
    if (!searchQuery) return lineageData.nodes;
    
    const query = searchQuery.toLowerCase();
    return lineageData.nodes.filter(n => 
      n.name.toLowerCase().includes(query) ||
      n.tableName.toLowerCase().includes(query)
    );
  }, [lineageData?.nodes, searchQuery]);

  // Build React Flow nodes and edges
  const { flowNodes, flowEdges } = useMemo(() => {
    if (!filteredNodes.length) return { flowNodes: [], flowEdges: [] };
    
    const nodeIds = new Set(filteredNodes.map(n => n.id));
    
    const nodes: Node[] = filteredNodes.map(node => ({
      id: node.id,
      type: 'tableNode',
      position: { x: 0, y: 0 },
      data: {
        label: node.name,
        nodeType: node.nodeType,
        criticality: node.criticality,
        rowCount: node.rowCount,
        upstreamCount: node.upstreamCount,
        downstreamCount: node.downstreamCount,
      },
    }));
    
    const edges: Edge[] = (lineageData?.edges || [])
      .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map(edge => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: 'default',
        animated: true,
        style: { 
          stroke: '#818cf8', 
          strokeWidth: 2,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#818cf8',
        },
      }));
    
    if (nodes.length === 0) return { flowNodes: [], flowEdges: [] };
    
    const layouted = getLayoutedElements(nodes, edges);
    return { flowNodes: layouted.nodes, flowEdges: layouted.edges };
  }, [filteredNodes, lineageData?.edges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback((event: React.MouseEvent, node: Node) => {
    const lineageNode = lineageData?.nodes.find(n => n.id === node.id);
    setSelectedNode(lineageNode || null);
  }, [lineageData?.nodes]);

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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-white">Data Lineage</h1>
            <p className="text-[13px] text-white/50">
              Visualize how data flows through your warehouse
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
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Extract Lineage
                </>
              )}
            </button>
          </div>
        </div>
        
        {/* Stats and Search */}
        <div className="flex items-center gap-4 mt-4">
          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className="text-xl font-semibold text-white">{lineageData?.stats?.totalNodes || 0}</div>
              <div className="text-[11px] text-white/40">Tables</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-semibold text-white">{lineageData?.stats?.totalEdges || 0}</div>
              <div className="text-[11px] text-white/40">Dependencies</div>
            </div>
          </div>
          
          <div className="flex-1 max-w-md ml-auto">
            <div className="relative">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search tables..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.06] text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.12]"
              />
            </div>
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
          {nodes.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              <svg className="w-16 h-16 text-white/20 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <p className="text-white/50 text-[15px] mb-2">No lineage data yet</p>
              <p className="text-white/30 text-[13px] mb-4">
                Click "Extract Lineage" to discover table dependencies
              </p>
              <button
                onClick={extractLineage}
                disabled={extracting || !stackId}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 text-white text-[13px] font-medium"
              >
                {extracting ? 'Extracting...' : 'Extract Lineage'}
              </button>
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.1}
              maxZoom={2}
              defaultEdgeOptions={{
                type: 'smoothstep',
                animated: true,
              }}
              proOptions={{ hideAttribution: true }}
            >
              <Controls className="!bg-white/5 !border-white/10 !rounded-lg [&>button]:!bg-white/5 [&>button]:!border-white/10 [&>button]:!text-white/60" />
              <MiniMap 
                nodeColor={(n) => n.data.nodeType === 'view' ? '#a855f7' : '#3b82f6'}
                maskColor="rgba(0,0,0,0.8)"
                className="!bg-white/5 !border-white/10 !rounded-lg"
              />
              <Background variant={BackgroundVariant.Dots} gap={20} size={2} color="rgba(255,255,255,0.15)" />
            </ReactFlow>
          )}
          
          {/* Legend */}
          {nodes.length > 0 && (
            <div className="absolute bottom-4 left-4 flex items-center gap-3 px-3 py-2 bg-black/60 backdrop-blur-sm rounded-lg border border-white/10 text-[10px]">
              <div className="flex items-center gap-1">
                <span>🗃️</span>
                <span className="text-white/50">Table</span>
              </div>
              <div className="flex items-center gap-1">
                <span>👁️</span>
                <span className="text-white/50">View</span>
              </div>
              <div className="flex items-center gap-1">
                <span>📥</span>
                <span className="text-white/50">Source</span>
              </div>
              <div className="w-px h-3 bg-white/20" />
              <div className="flex items-center gap-1">
                <div className="w-6 h-0.5 bg-indigo-400 rounded" />
                <svg className="w-2 h-2 text-indigo-400" viewBox="0 0 10 10" fill="currentColor">
                  <path d="M0 0L10 5L0 10z" />
                </svg>
                <span className="text-white/50">Data Flow</span>
              </div>
            </div>
          )}
        </div>

        {/* Side panel - Node details */}
        {selectedNode && (
          <div className="w-80 border-l border-white/[0.06] bg-[#030303] p-4 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[15px] font-medium text-white">Table Details</h3>
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
                <label className="text-[11px] text-white/40 uppercase tracking-wide">Full Name</label>
                <p className="text-[13px] text-white font-mono mt-1 break-all">{selectedNode.name}</p>
              </div>
              
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Type</label>
                  <p className="text-[13px] text-white mt-1 capitalize">{selectedNode.nodeType}</p>
                </div>
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Criticality</label>
                  <p className="text-[13px] text-white mt-1">{selectedNode.criticality}</p>
                </div>
              </div>
              
              {selectedNode.database && (
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Database</label>
                  <p className="text-[13px] text-white font-mono mt-1">{selectedNode.database}</p>
                </div>
              )}
              
              {selectedNode.schema && (
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Schema/Dataset</label>
                  <p className="text-[13px] text-white font-mono mt-1">{selectedNode.schema}</p>
                </div>
              )}
              
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Upstream</label>
                  <p className="text-[13px] text-white mt-1">{selectedNode.upstreamCount} tables</p>
                </div>
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Downstream</label>
                  <p className="text-[13px] text-white mt-1">{selectedNode.downstreamCount} tables</p>
                </div>
              </div>
              
              {selectedNode.rowCount && (
                <div>
                  <label className="text-[11px] text-white/40 uppercase tracking-wide">Row Count</label>
                  <p className="text-[13px] text-white mt-1">{selectedNode.rowCount.toLocaleString()}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
