'use client';

import React, { useCallback, useMemo, useEffect, useState } from 'react';
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
  ConnectionLineType,
  EdgeLabelRenderer,
  getBezierPath,
  EdgeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';

// Types
interface GraphNode {
  id: string;
  name: string;
  fqn?: string;
  type: string;
  criticality: string;
  owner?: string | null;
  affected_column?: string;
  is_source?: boolean;
  finding_type?: string;
  finding_severity?: string;
  impact_reason?: string;
  distance: number;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  transformation_type?: string;
  transformation?: string;
  target_criticality?: string;
}

interface FindingLineageCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  sourceTable: string;
  sourceColumn?: string;
  onNodeClick?: (nodeId: string) => void;
  selectedNodeId?: string;
  className?: string;
}

// Custom Node Component for Finding Lineage
function FindingLineageNode({ data, selected }: { data: any; selected?: boolean }) {
  const isSource = data.isSource;
  const criticality = (data.criticality || 'medium').toUpperCase();
  const type = data.type || 'table';

  const criticalityColors: Record<string, { bg: string; border: string; text: string; ring: string }> = {
    CRITICAL: { bg: 'bg-red-500/20', border: 'border-red-500', text: 'text-red-400', ring: 'ring-red-500/50' },
    HIGH: { bg: 'bg-orange-500/20', border: 'border-orange-500', text: 'text-orange-400', ring: 'ring-orange-500/50' },
    MEDIUM: { bg: 'bg-amber-500/20', border: 'border-amber-500/50', text: 'text-amber-400', ring: 'ring-amber-500/50' },
    LOW: { bg: 'bg-slate-500/20', border: 'border-slate-500/50', text: 'text-slate-400', ring: 'ring-slate-500/50' },
  };

  const typeIcons: Record<string, React.ReactNode> = {
    source: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
      </svg>
    ),
    table: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
      </svg>
    ),
    view: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      </svg>
    ),
    model: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
      </svg>
    ),
    dashboard: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
    report: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  };

  const colors = isSource 
    ? { bg: 'bg-purple-500/30', border: 'border-red-500', text: 'text-purple-400', ring: 'ring-purple-500/50' }
    : criticalityColors[criticality] || criticalityColors.MEDIUM;
  
  const icon = typeIcons[type] || typeIcons.table;
  const shortName = data.label?.split('.').pop() || data.label;

  return (
    <div
      className={`
        px-4 py-3 rounded-xl min-w-[160px] max-w-[220px]
        ${colors.bg} border-2 ${colors.border}
        ${selected ? `ring-2 ${colors.ring}` : ''}
        ${isSource ? 'border-red-500 shadow-red-500/20' : ''}
        hover:scale-105 transition-all cursor-pointer
        shadow-lg backdrop-blur-sm
      `}
      title={data.fullName || data.label}
    >
      {/* Source indicator - red dot for finding source */}
      {isSource && (
        <div className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-500 ring-2 ring-[var(--surface)] flex items-center justify-center">
          <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M12 9v2m0 4h.01" />
          </svg>
        </div>
      )}
      
      {/* Header with type icon */}
      <div className="flex items-center gap-2 mb-2">
        <span className={isSource ? 'text-purple-400' : colors.text}>
          {icon}
        </span>
        <span className={`text-[10px] uppercase font-semibold ${isSource ? 'text-purple-400' : 'text-[var(--muted)]'}`}>
          {type}
        </span>
        {data.owner && (
          <span className="text-[9px] text-[var(--text-faint)] ml-auto truncate max-w-[60px]" title={data.owner}>
            {data.owner}
          </span>
        )}
      </div>
      
      {/* Table name */}
      <div className={`text-sm font-mono truncate ${isSource ? 'text-[var(--text)] font-semibold' : 'text-[var(--text-secondary)]'}`}>
        {shortName}
      </div>
      
      {/* Column badge */}
      {data.affectedColumn && (
        <div className="mt-2 flex items-center gap-1">
          <span className="text-[9px] text-[var(--muted)]">
            {isSource ? 'Issue in:' : 'Affected:'}
          </span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
            isSource 
              ? 'bg-red-500/30 text-red-300 border border-red-500/50' 
              : 'bg-purple-500/20 text-purple-300'
          }`}>
            {data.affectedColumn}
          </span>
        </div>
      )}
      
      {/* Criticality and distance for non-source nodes */}
      {!isSource && (
        <div className="flex items-center gap-2 mt-2">
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${colors.bg} ${colors.text}`}>
            {criticality}
          </span>
          {data.distance !== undefined && data.distance > 0 && (
            <span className="text-[9px] text-[var(--text-faint)]">
              {data.distance} hop{data.distance > 1 ? 's' : ''}
            </span>
          )}
        </div>
      )}
      
      {/* Source node label */}
      {isSource && (
        <div className="flex items-center gap-1 mt-2 text-[9px] text-red-400 font-medium">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          Issue Source
        </div>
      )}
    </div>
  );
}

// Custom Edge Component with transformation labels
function TransformationEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data,
}: EdgeProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const transformationType = data?.transformationType || '';
  const transformation = data?.transformation || '';

  return (
    <>
      <path
        id={id}
        style={style}
        className="react-flow__edge-path"
        d={edgePath}
        markerEnd={markerEnd}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      />
      
      {/* Transformation type label on edge */}
      {transformationType && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'all',
            }}
            className="nodrag nopan"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
          >
            <div className="px-2 py-0.5 rounded text-[9px] font-medium bg-blue-500/20 text-blue-300 border border-blue-500/30">
              {transformationType}
            </div>
            
            {/* SQL Tooltip on hover */}
            {showTooltip && transformation && (
              <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 z-50 max-w-[300px]">
                <div className="p-3 rounded-lg bg-slate-800 border border-slate-600 shadow-xl">
                  <div className="text-[10px] text-slate-400 mb-1">SQL Transformation:</div>
                  <pre className="text-[10px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap break-all">
                    {transformation.length > 200 ? transformation.slice(0, 200) + '...' : transformation}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

// Node and edge types for React Flow
const nodeTypes = {
  findingNode: FindingLineageNode,
};

const edgeTypes = {
  transformation: TransformationEdge,
};

// Dagre layout
const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const getLayoutedElements = (nodes: Node[], edges: Edge[], direction = 'TB') => {
  const nodeWidth = 200;
  const nodeHeight = 100;
  const isHorizontal = direction === 'LR';
  
  dagreGraph.setGraph({ rankdir: direction, nodesep: 60, ranksep: 100 });

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
      targetPosition: isHorizontal ? Position.Left : Position.Top,
      sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

export function FindingLineageCanvas({
  nodes: graphNodes,
  edges: graphEdges,
  sourceTable,
  sourceColumn,
  onNodeClick,
  selectedNodeId,
  className = '',
}: FindingLineageCanvasProps) {
  // Build React Flow nodes and edges
  const { initialNodes, initialEdges } = useMemo(() => {
    if (!graphNodes || graphNodes.length === 0) {
      return { initialNodes: [], initialEdges: [] };
    }

    const nodes: Node[] = graphNodes.map((node) => ({
      id: node.id,
      type: 'findingNode',
      position: { x: 0, y: 0 },
      data: {
        label: node.name || node.fqn || node.id,
        fullName: node.fqn || node.name,
        isSource: node.is_source,
        type: node.type || 'table',
        criticality: node.criticality || 'medium',
        owner: node.owner,
        affectedColumn: node.affected_column,
        distance: node.distance,
        impactReason: node.impact_reason,
      },
      selected: node.id === selectedNodeId || 
                (selectedNodeId && node.name?.toLowerCase().includes(selectedNodeId.toLowerCase())),
    }));

    const edges: Edge[] = graphEdges.map((edge) => {
      const targetCriticality = (edge.target_criticality || 'medium').toUpperCase();
      const edgeColor = targetCriticality === 'CRITICAL' ? '#ef4444' : 
                        targetCriticality === 'HIGH' ? '#f97316' : 
                        '#8b5cf6';
      
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: edge.transformation_type ? 'transformation' : 'smoothstep',
        animated: targetCriticality === 'CRITICAL',
        style: { 
          stroke: edgeColor, 
          strokeWidth: targetCriticality === 'CRITICAL' ? 3 : 2 
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: edgeColor,
        },
        data: {
          transformationType: edge.transformation_type,
          transformation: edge.transformation,
        },
      };
    });

    // Apply dagre layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(nodes, edges, 'TB');
    
    return { initialNodes: layoutedNodes, initialEdges: layoutedEdges };
  }, [graphNodes, graphEdges, selectedNodeId]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback((event: React.MouseEvent, node: Node) => {
    if (onNodeClick) {
      onNodeClick(node.id);
    }
  }, [onNodeClick]);

  const nodeColor = (node: Node) => {
    if (node.data.isSource) return '#ef4444';
    const crit = (node.data.criticality || 'medium').toUpperCase();
    if (crit === 'CRITICAL') return '#ef4444';
    if (crit === 'HIGH') return '#f97316';
    if (crit === 'MEDIUM') return '#eab308';
    return '#64748b';
  };

  if (graphNodes.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full ${className}`}>
        <svg className="w-16 h-16 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
        <p className="text-[var(--muted)] text-sm">No lineage data available</p>
        <p className="text-[var(--text-faint)] text-xs mt-1">Build lineage from your data warehouse to see column-level impact</p>
      </div>
    );
  }

  return (
    <div className={`w-full h-full min-h-[400px] bg-[var(--surface-inset)] ${className}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        connectionLineType={ConnectionLineType.SmoothStep}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
        proOptions={{ hideAttribution: true }}
      >
        <Controls 
          className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg [&>button]:!bg-[var(--subtle-bg)] [&>button]:!border-[var(--border-medium)] [&>button]:!text-[var(--text-tertiary)] [&>button:hover]:!bg-[var(--overlay-medium)]"
        />
        <MiniMap 
          nodeColor={nodeColor}
          maskColor="rgba(0, 0, 0, 0.8)"
          className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg"
          nodeStrokeWidth={3}
        />
        <Background color="var(--text-faint)" gap={24} />
      </ReactFlow>
      
      {/* Legend */}
      <div className="absolute bottom-4 left-4 flex items-center gap-4 px-3 py-2 bg-[var(--surface)]/80 backdrop-blur-sm rounded-lg border border-[var(--border-medium)] text-[10px]">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded border-2 border-red-500 bg-purple-500/30" />
          <span className="text-[var(--muted)]">Issue Source</span>
        </div>
        <div className="w-px h-4 bg-[var(--overlay-strong)]" />
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded bg-red-500" />
          <span className="text-[var(--muted)]">Critical</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded bg-orange-500" />
          <span className="text-[var(--muted)]">High</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded bg-amber-500" />
          <span className="text-[var(--muted)]">Medium</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded bg-slate-500" />
          <span className="text-[var(--muted)]">Low</span>
        </div>
      </div>
    </div>
  );
}
