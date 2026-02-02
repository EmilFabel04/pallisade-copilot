'use client';

import React, { useState, useCallback, useMemo, useEffect } from 'react';
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
  Panel,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import { useRouter } from 'next/navigation';

// Types
interface LineageNodeData {
  id: string;
  name: string;
  type: 'table' | 'view' | 'source' | 'model' | 'dashboard' | 'report';
  platform?: string;
  database?: string;
  schema?: string;
  description?: string;
  criticality?: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  rowCount?: number;
  lastUpdated?: string;
  owner?: string;
  columns?: { name: string; type: string }[];
  upstreamCount: number;
  downstreamCount: number;
}

interface LineageEdgeData {
  source: string;
  target: string;
  columns?: string[];
  transformation?: string;
}

// Sample data - in production this would come from the API
const sampleNodes: LineageNodeData[] = [
  { id: 'raw_orders', name: 'raw.orders', type: 'source', platform: 'Fivetran', database: 'raw', schema: 'stripe', criticality: 'HIGH', rowCount: 1500000, lastUpdated: '2024-01-15T10:30:00Z', upstreamCount: 0, downstreamCount: 3 },
  { id: 'raw_customers', name: 'raw.customers', type: 'source', platform: 'Fivetran', database: 'raw', schema: 'stripe', criticality: 'HIGH', rowCount: 250000, lastUpdated: '2024-01-15T10:30:00Z', upstreamCount: 0, downstreamCount: 2 },
  { id: 'raw_products', name: 'raw.products', type: 'source', platform: 'Airbyte', database: 'raw', schema: 'shopify', criticality: 'MEDIUM', rowCount: 5000, lastUpdated: '2024-01-15T09:00:00Z', upstreamCount: 0, downstreamCount: 2 },
  { id: 'stg_orders', name: 'staging.stg_orders', type: 'model', platform: 'dbt', database: 'analytics', schema: 'staging', criticality: 'HIGH', rowCount: 1500000, lastUpdated: '2024-01-15T11:00:00Z', upstreamCount: 1, downstreamCount: 2 },
  { id: 'stg_customers', name: 'staging.stg_customers', type: 'model', platform: 'dbt', database: 'analytics', schema: 'staging', criticality: 'HIGH', rowCount: 250000, lastUpdated: '2024-01-15T11:00:00Z', upstreamCount: 1, downstreamCount: 2 },
  { id: 'stg_products', name: 'staging.stg_products', type: 'model', platform: 'dbt', database: 'analytics', schema: 'staging', criticality: 'MEDIUM', rowCount: 5000, lastUpdated: '2024-01-15T11:00:00Z', upstreamCount: 1, downstreamCount: 1 },
  { id: 'dim_customers', name: 'analytics.dim_customers', type: 'table', platform: 'Snowflake', database: 'analytics', schema: 'core', criticality: 'CRITICAL', rowCount: 250000, lastUpdated: '2024-01-15T12:00:00Z', upstreamCount: 1, downstreamCount: 2 },
  { id: 'dim_products', name: 'analytics.dim_products', type: 'table', platform: 'Snowflake', database: 'analytics', schema: 'core', criticality: 'MEDIUM', rowCount: 5000, lastUpdated: '2024-01-15T12:00:00Z', upstreamCount: 1, downstreamCount: 1 },
  { id: 'fct_orders', name: 'analytics.fct_orders', type: 'table', platform: 'Snowflake', database: 'analytics', schema: 'core', criticality: 'CRITICAL', rowCount: 1500000, lastUpdated: '2024-01-15T12:00:00Z', upstreamCount: 3, downstreamCount: 3 },
  { id: 'revenue_dashboard', name: 'Revenue Dashboard', type: 'dashboard', platform: 'Looker', criticality: 'CRITICAL', upstreamCount: 2, downstreamCount: 0 },
  { id: 'customer_report', name: 'Customer Analytics', type: 'report', platform: 'Tableau', criticality: 'HIGH', upstreamCount: 1, downstreamCount: 0 },
  { id: 'product_performance', name: 'Product Performance', type: 'dashboard', platform: 'Looker', criticality: 'MEDIUM', upstreamCount: 2, downstreamCount: 0 },
];

const sampleEdges: LineageEdgeData[] = [
  { source: 'raw_orders', target: 'stg_orders' },
  { source: 'raw_customers', target: 'stg_customers' },
  { source: 'raw_products', target: 'stg_products' },
  { source: 'stg_orders', target: 'fct_orders' },
  { source: 'stg_customers', target: 'dim_customers' },
  { source: 'stg_products', target: 'dim_products' },
  { source: 'dim_customers', target: 'fct_orders' },
  { source: 'dim_products', target: 'fct_orders' },
  { source: 'fct_orders', target: 'revenue_dashboard' },
  { source: 'dim_customers', target: 'revenue_dashboard' },
  { source: 'dim_customers', target: 'customer_report' },
  { source: 'fct_orders', target: 'product_performance' },
  { source: 'dim_products', target: 'product_performance' },
];

// Custom Node Component
function LineageGraphNode({ data, selected }: { data: LineageNodeData & { highlighted?: 'upstream' | 'downstream' | 'selected' }; selected: boolean }) {
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

  const criticalityColors: Record<string, { bg: string; border: string; text: string }> = {
    CRITICAL: { bg: 'bg-red-500/20', border: 'border-red-500', text: 'text-red-400' },
    HIGH: { bg: 'bg-orange-500/20', border: 'border-orange-500', text: 'text-orange-400' },
    MEDIUM: { bg: 'bg-amber-500/20', border: 'border-amber-500', text: 'text-amber-400' },
    LOW: { bg: 'bg-emerald-500/20', border: 'border-emerald-500', text: 'text-emerald-400' },
  };

  const highlightColors: Record<string, { bg: string; border: string }> = {
    upstream: { bg: 'bg-blue-500/30', border: 'border-blue-500' },
    downstream: { bg: 'bg-purple-500/30', border: 'border-purple-500' },
    selected: { bg: 'bg-cyan-500/30', border: 'border-cyan-500' },
  };

  const colors = criticalityColors[data.criticality || 'MEDIUM'];
  const highlight = data.highlighted ? highlightColors[data.highlighted] : null;
  const icon = typeIcons[data.type] || typeIcons.table;

  const shortName = data.name?.split('.').pop() || data.name;

  return (
    <div
      className={`
        px-4 py-3 rounded-xl min-w-[160px] max-w-[220px] transition-all duration-200
        ${highlight ? highlight.bg + ' ' + highlight.border : colors.bg + ' ' + colors.border}
        ${selected ? 'ring-2 ring-white/50 scale-105' : ''}
        border-2 shadow-xl backdrop-blur-sm cursor-pointer hover:scale-102
      `}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span className={highlight ? 'text-white' : colors.text}>{icon}</span>
        <span className={`text-[10px] uppercase font-semibold tracking-wide ${highlight ? 'text-white/70' : 'text-white/50'}`}>
          {data.type}
        </span>
        {data.platform && (
          <span className="text-[9px] text-white/40 ml-auto font-medium">{data.platform}</span>
        )}
      </div>

      {/* Name */}
      <div className="text-sm font-mono text-white font-medium truncate mb-2" title={data.name}>
        {shortName}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-3 text-[10px] text-white/50">
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
          </svg>
          {data.upstreamCount}
        </span>
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
          {data.downstreamCount}
        </span>
        {data.rowCount && (
          <span className="ml-auto">{(data.rowCount / 1000).toFixed(0)}K rows</span>
        )}
      </div>
    </div>
  );
}

const nodeTypes = {
  lineageNode: LineageGraphNode,
};

// Layout function
const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

function getLayoutedElements(nodes: Node[], edges: Edge[], direction = 'LR') {
  const nodeWidth = 200;
  const nodeHeight = 100;
  const isHorizontal = direction === 'LR';

  dagreGraph.setGraph({ rankdir: direction, nodesep: 80, ranksep: 120 });

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
}

export default function LineagePage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState<LineageNodeData | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [highlightType, setHighlightType] = useState<'upstream' | 'downstream' | null>(null);
  const [filterType, setFilterType] = useState<string>('all');
  const [filterPlatform, setFilterPlatform] = useState<string>('all');
  const [loading, setLoading] = useState(true);

  // Simulate loading
  useEffect(() => {
    setTimeout(() => setLoading(false), 500);
  }, []);

  // Filter nodes based on search and filters
  const filteredNodeData = useMemo(() => {
    return sampleNodes.filter((node) => {
      const matchesSearch = searchQuery === '' || 
        node.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        node.platform?.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesType = filterType === 'all' || node.type === filterType;
      const matchesPlatform = filterPlatform === 'all' || node.platform === filterPlatform;
      return matchesSearch && matchesType && matchesPlatform;
    });
  }, [searchQuery, filterType, filterPlatform]);

  // Get unique platforms for filter
  const platforms = useMemo(() => {
    const uniquePlatforms = new Set(sampleNodes.map((n) => n.platform).filter(Boolean));
    return ['all', ...Array.from(uniquePlatforms)];
  }, []);

  // Build React Flow nodes and edges
  const { initialNodes, initialEdges } = useMemo(() => {
    const filteredIds = new Set(filteredNodeData.map((n) => n.id));
    
    const nodes: Node[] = filteredNodeData.map((nodeData) => ({
      id: nodeData.id,
      type: 'lineageNode',
      position: { x: 0, y: 0 },
      data: {
        ...nodeData,
        highlighted: highlightedNodes.has(nodeData.id) 
          ? (selectedNode?.id === nodeData.id ? 'selected' : highlightType)
          : undefined,
      },
    }));

    const edges: Edge[] = sampleEdges
      .filter((e) => filteredIds.has(e.source) && filteredIds.has(e.target))
      .map((edgeData) => {
        const isHighlighted = highlightedNodes.has(edgeData.source) && highlightedNodes.has(edgeData.target);
        return {
          id: `${edgeData.source}-${edgeData.target}`,
          source: edgeData.source,
          target: edgeData.target,
          type: 'smoothstep',
          animated: isHighlighted,
          style: { 
            stroke: isHighlighted 
              ? (highlightType === 'upstream' ? '#3b82f6' : '#a855f7')
              : '#ffffff30',
            strokeWidth: isHighlighted ? 3 : 2,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isHighlighted 
              ? (highlightType === 'upstream' ? '#3b82f6' : '#a855f7')
              : '#ffffff30',
          },
        };
      });

    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(nodes, edges, 'LR');
    return { initialNodes: layoutedNodes, initialEdges: layoutedEdges };
  }, [filteredNodeData, highlightedNodes, highlightType, selectedNode]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  // Get upstream/downstream nodes
  const getUpstreamNodes = useCallback((nodeId: string): Set<string> => {
    const upstream = new Set<string>();
    const visited = new Set<string>();
    
    function traverse(id: string) {
      if (visited.has(id)) return;
      visited.add(id);
      upstream.add(id);
      
      sampleEdges
        .filter((e) => e.target === id)
        .forEach((e) => traverse(e.source));
    }
    
    traverse(nodeId);
    return upstream;
  }, []);

  const getDownstreamNodes = useCallback((nodeId: string): Set<string> => {
    const downstream = new Set<string>();
    const visited = new Set<string>();
    
    function traverse(id: string) {
      if (visited.has(id)) return;
      visited.add(id);
      downstream.add(id);
      
      sampleEdges
        .filter((e) => e.source === id)
        .forEach((e) => traverse(e.target));
    }
    
    traverse(nodeId);
    return downstream;
  }, []);

  const handleNodeClick = useCallback((event: React.MouseEvent, node: Node) => {
    const nodeData = sampleNodes.find((n) => n.id === node.id);
    setSelectedNode(nodeData || null);
    
    // Highlight both upstream and downstream
    const upstream = getUpstreamNodes(node.id);
    const downstream = getDownstreamNodes(node.id);
    const combined = new Set([...upstream, ...downstream]);
    setHighlightedNodes(combined);
    setHighlightType('downstream');
  }, [getUpstreamNodes, getDownstreamNodes]);

  const handleHighlightUpstream = () => {
    if (selectedNode) {
      const upstream = getUpstreamNodes(selectedNode.id);
      setHighlightedNodes(upstream);
      setHighlightType('upstream');
    }
  };

  const handleHighlightDownstream = () => {
    if (selectedNode) {
      const downstream = getDownstreamNodes(selectedNode.id);
      setHighlightedNodes(downstream);
      setHighlightType('downstream');
    }
  };

  const handleClearHighlight = () => {
    setHighlightedNodes(new Set());
    setHighlightType(null);
    setSelectedNode(null);
  };

  const handleAskAboutNode = () => {
    if (selectedNode) {
      router.push(`/dashboard/assistant?context=lineage&node=${encodeURIComponent(selectedNode.name)}`);
    }
  };

  const nodeColor = (node: Node) => {
    if (highlightedNodes.has(node.id)) {
      return highlightType === 'upstream' ? '#3b82f6' : '#a855f7';
    }
    const crit = node.data.criticality;
    if (crit === 'CRITICAL') return '#ef4444';
    if (crit === 'HIGH') return '#f97316';
    if (crit === 'MEDIUM') return '#eab308';
    return '#22c55e';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-120px)]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-purple-500/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-white/50">Loading lineage graph...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-120px)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Lineage Explorer</h1>
          <p className="text-white/50 text-sm mt-1">
            Visualize data dependencies and trace impact across your pipeline
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-white/40 text-sm">
            {filteredNodeData.length} nodes
          </span>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center gap-4 mb-4">
        <div className="relative flex-1 max-w-md">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search nodes by name or platform..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:outline-none focus:border-purple-500/50"
          />
        </div>

        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:border-purple-500/50"
        >
          <option value="all">All Types</option>
          <option value="source">Sources</option>
          <option value="model">Models</option>
          <option value="table">Tables</option>
          <option value="view">Views</option>
          <option value="dashboard">Dashboards</option>
          <option value="report">Reports</option>
        </select>

        <select
          value={filterPlatform}
          onChange={(e) => setFilterPlatform(e.target.value)}
          className="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:border-purple-500/50"
        >
          {platforms.map((p) => (
            <option key={p} value={p}>
              {p === 'all' ? 'All Platforms' : p}
            </option>
          ))}
        </select>

        {highlightedNodes.size > 0 && (
          <button
            onClick={handleClearHighlight}
            className="px-3 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm transition-colors"
          >
            Clear Selection
          </button>
        )}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex gap-4">
        {/* Graph */}
        <div className="flex-1 bg-[#050505] rounded-xl border border-white/10 overflow-hidden">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            nodeTypes={nodeTypes}
            connectionLineType={ConnectionLineType.SmoothStep}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
          >
            <Controls className="!bg-white/5 !border-white/10 !rounded-lg [&>button]:!bg-white/5 [&>button]:!border-white/10 [&>button]:!text-white/60 [&>button:hover]:!bg-white/10" />
            <MiniMap
              nodeColor={nodeColor}
              maskColor="rgba(0, 0, 0, 0.8)"
              className="!bg-white/5 !border-white/10 !rounded-lg"
            />
            <Background color="#ffffff10" gap={20} />

            {/* Legend Panel */}
            <Panel position="bottom-left" className="!m-4">
              <div className="flex items-center gap-4 px-3 py-2 bg-black/80 backdrop-blur-sm rounded-lg border border-white/10 text-[10px]">
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-red-500" />
                  <span className="text-white/50">Critical</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-orange-500" />
                  <span className="text-white/50">High</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-amber-500" />
                  <span className="text-white/50">Medium</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-500" />
                  <span className="text-white/50">Low</span>
                </div>
                <div className="w-px h-3 bg-white/20" />
                <div className="flex items-center gap-1">
                  <div className="w-3 h-0.5 bg-blue-500" />
                  <span className="text-white/50">Upstream</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-3 h-0.5 bg-purple-500" />
                  <span className="text-white/50">Downstream</span>
                </div>
              </div>
            </Panel>
          </ReactFlow>
        </div>

        {/* Details Panel */}
        {selectedNode && (
          <div className="w-80 bg-white/5 rounded-xl border border-white/10 p-4 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white">Node Details</h3>
              <button
                onClick={() => setSelectedNode(null)}
                className="p-1 hover:bg-white/10 rounded transition-colors"
              >
                <svg className="w-5 h-5 text-white/50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Node Info */}
            <div className="space-y-4">
              <div>
                <label className="text-[10px] uppercase text-white/40 font-medium">Name</label>
                <p className="text-white font-mono text-sm break-all">{selectedNode.name}</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] uppercase text-white/40 font-medium">Type</label>
                  <p className="text-white capitalize">{selectedNode.type}</p>
                </div>
                <div>
                  <label className="text-[10px] uppercase text-white/40 font-medium">Platform</label>
                  <p className="text-white">{selectedNode.platform || '-'}</p>
                </div>
              </div>

              {selectedNode.database && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-[10px] uppercase text-white/40 font-medium">Database</label>
                    <p className="text-white">{selectedNode.database}</p>
                  </div>
                  <div>
                    <label className="text-[10px] uppercase text-white/40 font-medium">Schema</label>
                    <p className="text-white">{selectedNode.schema || '-'}</p>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] uppercase text-white/40 font-medium">Criticality</label>
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                    selectedNode.criticality === 'CRITICAL' ? 'bg-red-500/20 text-red-400' :
                    selectedNode.criticality === 'HIGH' ? 'bg-orange-500/20 text-orange-400' :
                    selectedNode.criticality === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
                    'bg-emerald-500/20 text-emerald-400'
                  }`}>
                    {selectedNode.criticality}
                  </span>
                </div>
                {selectedNode.rowCount && (
                  <div>
                    <label className="text-[10px] uppercase text-white/40 font-medium">Row Count</label>
                    <p className="text-white">{selectedNode.rowCount.toLocaleString()}</p>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] uppercase text-white/40 font-medium">Upstream</label>
                  <p className="text-white">{selectedNode.upstreamCount} dependencies</p>
                </div>
                <div>
                  <label className="text-[10px] uppercase text-white/40 font-medium">Downstream</label>
                  <p className="text-white">{selectedNode.downstreamCount} dependents</p>
                </div>
              </div>

              {selectedNode.lastUpdated && (
                <div>
                  <label className="text-[10px] uppercase text-white/40 font-medium">Last Updated</label>
                  <p className="text-white text-sm">
                    {new Date(selectedNode.lastUpdated).toLocaleString()}
                  </p>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="mt-6 pt-4 border-t border-white/10 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={handleHighlightUpstream}
                  className="px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg text-sm font-medium transition-colors"
                >
                  Show Upstream
                </button>
                <button
                  onClick={handleHighlightDownstream}
                  className="px-3 py-2 bg-purple-500/20 hover:bg-purple-500/30 text-purple-400 rounded-lg text-sm font-medium transition-colors"
                >
                  Show Downstream
                </button>
              </div>
              
              <button
                onClick={handleAskAboutNode}
                className="w-full px-4 py-2 bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
                Ask AI About This
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
