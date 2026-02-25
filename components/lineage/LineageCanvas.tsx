'use client';

import React, { useCallback, useMemo, useEffect } from 'react';
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
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';

// Types
interface LineageTable {
  name: string;
  criticality?: string;
  type?: string;
  platform?: string;
  distance?: number;
  health?: 'healthy' | 'degraded' | 'failing' | 'unknown';
  columns?: string[];
}

interface LineageCanvasProps {
  centerTable: string;
  upstreamTables: LineageTable[];
  downstreamTables: LineageTable[];
  onNodeClick?: (tableName: string) => void;
  className?: string;
}

// Custom Node Component
function LineageNode({ data }: { data: any }) {
  const criticality = data.criticality || 'MEDIUM';
  const type = data.type || 'table';
  const health = data.health || 'unknown';
  const isCenter = data.isCenter;

  const criticalityColors: Record<string, { bg: string; border: string; text: string }> = {
    CRITICAL: { bg: 'bg-red-500/20', border: 'border-red-500/50', text: 'text-red-400' },
    HIGH: { bg: 'bg-orange-500/20', border: 'border-orange-500/50', text: 'text-orange-400' },
    MEDIUM: { bg: 'bg-amber-500/20', border: 'border-amber-500/50', text: 'text-amber-400' },
    LOW: { bg: 'bg-emerald-500/20', border: 'border-emerald-500/50', text: 'text-emerald-400' },
  };

  const typeIcons: Record<string, React.ReactNode> = {
    source: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
      </svg>
    ),
    table: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
      </svg>
    ),
    view: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      </svg>
    ),
    model: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
      </svg>
    ),
    dashboard: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
    report: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  };

  const healthColors: Record<string, string> = {
    healthy: 'bg-emerald-500',
    degraded: 'bg-amber-500',
    failing: 'bg-red-500',
    unknown: 'bg-gray-500',
  };

  const colors = criticalityColors[criticality] || criticalityColors.MEDIUM;
  const icon = typeIcons[type] || typeIcons.table;

  // Get short name (last part of FQN)
  const shortName = data.label?.split('.').pop() || data.label;
  const fullName = data.label;

  return (
    <div
      className={`
        px-3 py-2 rounded-lg border-2 min-w-[140px] max-w-[200px]
        ${isCenter ? 'bg-purple-500/30 border-purple-500' : colors.bg + ' ' + colors.border}
        hover:scale-105 transition-transform cursor-pointer
        shadow-lg backdrop-blur-sm
      `}
      title={fullName}
    >
      {/* Health indicator */}
      <div className={`absolute -top-1 -right-1 w-3 h-3 rounded-full ${healthColors[health]} ring-2 ring-[var(--surface)]`} />
      
      {/* Header */}
      <div className="flex items-center gap-2 mb-1">
        <span className={isCenter ? 'text-purple-400' : colors.text}>
          {icon}
        </span>
        <span className={`text-[10px] uppercase font-medium ${isCenter ? 'text-purple-400' : 'text-[var(--muted)]'}`}>
          {type}
        </span>
        {data.platform && (
          <span className="text-[9px] text-[var(--text-faint)] ml-auto">{data.platform}</span>
        )}
      </div>
      
      {/* Table name */}
      <div className={`text-sm font-mono truncate ${isCenter ? 'text-[var(--text)] font-semibold' : 'text-[var(--text-secondary)]'}`}>
        {shortName}
      </div>
      
      {/* Criticality badge */}
      {!isCenter && (
        <div className="flex items-center gap-1 mt-1">
          <span className={`text-[9px] px-1.5 py-0.5 rounded ${colors.bg} ${colors.text} font-medium`}>
            {criticality}
          </span>
          {data.distance && (
            <span className="text-[9px] text-[var(--text-faint)]">{data.distance} hop{data.distance > 1 ? 's' : ''}</span>
          )}
        </div>
      )}
      
      {/* Center node label */}
      {isCenter && (
        <div className="text-[9px] text-purple-400 mt-1 font-medium">
          ← Issue Source
        </div>
      )}
    </div>
  );
}

// Node types for React Flow
const nodeTypes = {
  lineageNode: LineageNode,
};

// Dagre layout configuration
const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const getLayoutedElements = (nodes: Node[], edges: Edge[], direction = 'TB') => {
  const nodeWidth = 180;
  const nodeHeight = 80;
  const isHorizontal = direction === 'LR';
  
  dagreGraph.setGraph({ rankdir: direction, nodesep: 50, ranksep: 80 });

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

export function LineageCanvas({
  centerTable,
  upstreamTables,
  downstreamTables,
  onNodeClick,
  className = '',
}: LineageCanvasProps) {
  // Build nodes and edges from lineage data
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    
    // Center node (the affected table)
    const centerId = 'center';
    nodes.push({
      id: centerId,
      type: 'lineageNode',
      position: { x: 0, y: 0 },
      data: {
        label: centerTable,
        isCenter: true,
        type: 'table',
        health: 'failing', // The table with the issue
      },
    });

    // Upstream nodes
    upstreamTables.forEach((table, index) => {
      const nodeId = `upstream-${index}`;
      nodes.push({
        id: nodeId,
        type: 'lineageNode',
        position: { x: 0, y: 0 },
        data: {
          label: table.name,
          criticality: table.criticality?.toUpperCase() || 'MEDIUM',
          type: table.type || 'source',
          platform: table.platform,
          health: 'healthy',
        },
      });
      
      edges.push({
        id: `edge-${nodeId}-to-center`,
        source: nodeId,
        target: centerId,
        type: 'smoothstep',
        animated: true,
        style: { stroke: '#6366f1', strokeWidth: 2 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#6366f1',
        },
      });
    });

    // Downstream nodes
    downstreamTables.forEach((table, index) => {
      const nodeId = `downstream-${index}`;
      const criticality = table.criticality?.toUpperCase() || 'MEDIUM';
      
      nodes.push({
        id: nodeId,
        type: 'lineageNode',
        position: { x: 0, y: 0 },
        data: {
          label: table.name,
          criticality,
          type: table.type || 'table',
          platform: table.platform,
          distance: table.distance,
          health: criticality === 'CRITICAL' ? 'degraded' : 'unknown',
        },
      });
      
      // Edge color based on criticality
      const edgeColor = criticality === 'CRITICAL' ? '#ef4444' : 
                        criticality === 'HIGH' ? '#f97316' : '#6366f1';
      
      edges.push({
        id: `edge-center-to-${nodeId}`,
        source: centerId,
        target: nodeId,
        type: 'smoothstep',
        animated: criticality === 'CRITICAL',
        style: { stroke: edgeColor, strokeWidth: criticality === 'CRITICAL' ? 3 : 2 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: edgeColor,
        },
      });
    });

    // Apply dagre layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(nodes, edges, 'TB');
    
    return { initialNodes: layoutedNodes, initialEdges: layoutedEdges };
  }, [centerTable, upstreamTables, downstreamTables]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes when data changes
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback((event: React.MouseEvent, node: Node) => {
    if (onNodeClick && node.data.label) {
      onNodeClick(node.data.label);
    }
  }, [onNodeClick]);

  // Custom minimap node color
  const nodeColor = (node: Node) => {
    if (node.data.isCenter) return '#a855f7';
    const crit = node.data.criticality;
    if (crit === 'CRITICAL') return '#ef4444';
    if (crit === 'HIGH') return '#f97316';
    if (crit === 'MEDIUM') return '#eab308';
    return '#22c55e';
  };

  if (upstreamTables.length === 0 && downstreamTables.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center py-12 ${className}`}>
        <svg className="w-16 h-16 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
        <p className="text-[var(--muted)] text-sm">No lineage data available</p>
        <p className="text-[var(--text-faint)] text-xs mt-1">Run a lineage scan to populate dependencies</p>
      </div>
    );
  }

  return (
    <div className={`w-full h-[400px] bg-[var(--surface-inset)] rounded-lg border border-[var(--border-medium)] ${className}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        connectionLineType={ConnectionLineType.SmoothStep}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={1.5}
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
        />
        <Background color="var(--text-faint)" gap={20} />
      </ReactFlow>
      
      {/* Legend */}
      <div className="absolute bottom-4 left-4 flex items-center gap-4 px-3 py-2 bg-[var(--surface)]/80 backdrop-blur-sm rounded-lg border border-[var(--border-medium)] text-[10px]">
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-[var(--muted)]">Healthy</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-amber-500" />
          <span className="text-[var(--muted)]">Degraded</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-red-500" />
          <span className="text-[var(--muted)]">Failing</span>
        </div>
        <div className="w-px h-3 bg-[var(--overlay-strong)]" />
        <div className="flex items-center gap-1">
          <div className="w-3 h-0.5 bg-purple-500" />
          <span className="text-[var(--muted)]">Data Flow</span>
        </div>
      </div>
    </div>
  );
}
