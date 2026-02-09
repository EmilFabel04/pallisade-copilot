'use client';

/**
 * Pipeline Canvas
 * 
 * Interactive n8n-style canvas for building data pipelines
 * Features: Auto-layout, keyboard shortcuts, templates
 */

import { useCallback, useMemo, useState, useEffect } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  BackgroundVariant,
  Connection,
  Handle,
  Position,
  MarkerType,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  Panel,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { PipelineNode, PipelineEdge, LAYER_COLORS, PipelineLayer } from './types';
import NodeConfigModal from './NodeConfigModal';
import { LayoutGrid, Trash2 } from 'lucide-react';

interface PipelineCanvasProps {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  stackId?: string; // Pipeline stack ID for API calls
  onNodesChange: (nodes: PipelineNode[]) => void;
  onEdgesChange: (edges: PipelineEdge[]) => void;
  onSave?: () => void;
}

// Layer positions for auto-layout
const LAYER_X_POSITIONS: Record<PipelineLayer, number> = {
  INGESTION: 100,
  VERSION_CONTROL: 250,
  TRANSFORMATION: 400,
  WAREHOUSE: 700,
  REPORTING: 1000,
};

// Auto-layout algorithm
function calculateAutoLayout(nodes: PipelineNode[]): PipelineNode[] {
  const layerCounts: Record<string, number> = {};
  const baseY = 80;
  const spacing = 180;
  
  return nodes.map(node => {
    const layer = node.layer;
    const xPos = LAYER_X_POSITIONS[layer] || 400;
    const count = layerCounts[layer] || 0;
    const yPos = baseY + (count * spacing);
    
    layerCounts[layer] = count + 1;
    
    return {
      ...node,
      positionX: xPos,
      positionY: yPos,
    };
  });
}

// Custom node component with proper React Flow Handles
function CustomNode({ data }: { data: any }) {
  const layerColor = LAYER_COLORS[data.layer as keyof typeof LAYER_COLORS] || '#6366f1';
  
  return (
    <div
      style={{
        background: '#1a1a24',
        border: `2px solid ${layerColor}`,
        borderRadius: '12px',
        padding: '0',
        minWidth: '200px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
        position: 'relative',
      }}
    >
      {/* Input Handle - Left side (except for Ingestion) */}
      {data.layer !== 'INGESTION' && (
        <Handle
          type="target"
          position={Position.Left}
          style={{
            width: '14px',
            height: '14px',
            background: layerColor,
            border: '3px solid #1a1a24',
            left: '-8px',
          }}
        />
      )}

      {/* Header */}
      <div
        style={{
          background: `${layerColor}20`,
          padding: '12px 16px',
          borderTopLeftRadius: '10px',
          borderTopRightRadius: '10px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: `${layerColor}30`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: layerColor,
              fontWeight: 'bold',
              fontSize: '14px',
            }}
          >
            {data.name?.charAt(0) || 'N'}
          </div>
          <div>
            <div style={{ fontWeight: '600', color: 'white', fontSize: '14px' }}>
              {data.name || 'Node'}
            </div>
            <div style={{ fontSize: '10px', color: '#888', textTransform: 'uppercase' }}>
              {data.layer}
            </div>
          </div>
        </div>
      </div>
      
      {/* Body */}
      <div style={{ padding: '12px 16px' }}>
        {!data.config ? (
          <div
            style={{
              background: 'rgba(245, 158, 11, 0.1)',
              border: '1px solid rgba(245, 158, 11, 0.2)',
              borderRadius: '8px',
              padding: '8px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span style={{ color: '#f59e0b', fontSize: '12px' }}>⚠ Click to configure</span>
          </div>
        ) : (
          <div
            style={{
              background: 'rgba(16, 185, 129, 0.1)',
              border: '1px solid rgba(16, 185, 129, 0.2)',
              borderRadius: '8px',
              padding: '8px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span style={{ color: '#10b981', fontSize: '12px' }}>✓ Connected</span>
          </div>
        )}
        
        {/* Buttons */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onConfigure?.();
            }}
            style={{
              flex: 1,
              padding: '8px 12px',
              borderRadius: '8px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'white',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Configure
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            style={{
              padding: '8px',
              borderRadius: '8px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: '#888',
              cursor: 'pointer',
            }}
          >
            🗑
          </button>
        </div>
      </div>

      {/* Output Handle - Right side (except for Reporting) */}
      {data.layer !== 'REPORTING' && (
        <Handle
          type="source"
          position={Position.Right}
          style={{
            width: '14px',
            height: '14px',
            background: layerColor,
            border: '3px solid #1a1a24',
            right: '-8px',
          }}
        />
      )}
    </div>
  );
}

// Node types must be defined outside the component
const nodeTypes = {
  custom: CustomNode,
};

// Default edge options
const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#6366f1', strokeWidth: 2 },
  markerEnd: {
    type: MarkerType.ArrowClosed,
    color: '#6366f1',
    width: 20,
    height: 20,
  },
};

function PipelineCanvasInner({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onSave,
  stackId,
}: PipelineCanvasProps) {
  const [configNode, setConfigNode] = useState<PipelineNode | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const reactFlowInstance = useReactFlow();

  // Convert pipeline nodes to ReactFlow format
  const initialNodes: Node[] = useMemo(() => {
    return nodes.map(node => ({
      id: node.id,
      type: 'custom',
      position: { x: node.positionX, y: node.positionY },
      data: {
        ...node,
        onConfigure: () => setConfigNode(node),
        onDelete: () => {
          onNodesChange(nodes.filter(n => n.id !== node.id));
          onEdgesChange(edges.filter(e => e.sourceId !== node.id && e.targetId !== node.id));
        },
      },
    }));
  }, [nodes, edges, onNodesChange, onEdgesChange]);

  // Convert pipeline edges to ReactFlow format
  const initialEdges: Edge[] = useMemo(() => {
    return edges.map(edge => ({
      id: edge.id,
      source: edge.sourceId,
      target: edge.targetId,
      ...defaultEdgeOptions,
    }));
  }, [edges]);

  // Use ReactFlow's built-in state management
  const [flowNodes, setFlowNodes, onFlowNodesChange] = useNodesState(initialNodes);
  const [flowEdges, setFlowEdges, onFlowEdgesChange] = useEdgesState(initialEdges);

  // Sync external nodes to internal state
  useEffect(() => {
    const newNodes = nodes.map(node => ({
      id: node.id,
      type: 'custom',
      position: { x: node.positionX, y: node.positionY },
      data: {
        ...node,
        onConfigure: () => setConfigNode(node),
        onDelete: () => {
          onNodesChange(nodes.filter(n => n.id !== node.id));
          onEdgesChange(edges.filter(e => e.sourceId !== node.id && e.targetId !== node.id));
        },
      },
    }));
    setFlowNodes(newNodes);
  }, [nodes]);

  // Sync external edges to internal state
  useEffect(() => {
    const newEdges = edges.map(edge => ({
      id: edge.id,
      source: edge.sourceId,
      target: edge.targetId,
      ...defaultEdgeOptions,
    }));
    setFlowEdges(newEdges);
  }, [edges]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Delete selected node
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNodeId && !configNode) {
        e.preventDefault();
        onNodesChange(nodes.filter(n => n.id !== selectedNodeId));
        onEdgesChange(edges.filter(e => e.sourceId !== selectedNodeId && e.targetId !== selectedNodeId));
        setSelectedNodeId(null);
      }
      
      // Cmd/Ctrl + S to save
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        onSave?.();
      }
      
      // Cmd/Ctrl + L for auto-layout
      if ((e.metaKey || e.ctrlKey) && e.key === 'l') {
        e.preventDefault();
        handleAutoLayout();
      }
      
      // Escape to deselect/close modal
      if (e.key === 'Escape') {
        if (configNode) {
          setConfigNode(null);
        } else {
          setSelectedNodeId(null);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedNodeId, configNode, nodes, edges, onNodesChange, onEdgesChange, onSave]);

  // Auto-layout handler
  const handleAutoLayout = useCallback(() => {
    const layoutedNodes = calculateAutoLayout(nodes);
    onNodesChange(layoutedNodes);
    
    // Fit view after layout
    setTimeout(() => {
      reactFlowInstance.fitView({ padding: 0.2, duration: 300 });
    }, 50);
  }, [nodes, onNodesChange, reactFlowInstance]);

  // Handle node drag
  const handleNodeDragStop = useCallback(
    (_: any, node: Node) => {
      const updatedNodes = nodes.map(n =>
        n.id === node.id
          ? { ...n, positionX: node.position.x, positionY: node.position.y }
          : n
      );
      onNodesChange(updatedNodes);
    },
    [nodes, onNodesChange]
  );

  // Handle new connections - this creates the edge when you drag between handles
  const handleConnect = useCallback(
    (connection: Connection) => {
      if (connection.source && connection.target) {
        // Check if connection already exists
        const exists = edges.some(
          e => e.sourceId === connection.source && e.targetId === connection.target
        );
        if (!exists) {
          const newEdge: PipelineEdge = {
            id: `edge-${Date.now()}`,
            sourceId: connection.source,
            targetId: connection.target,
          };
          onEdgesChange([...edges, newEdge]);
        }
      }
    },
    [edges, onEdgesChange]
  );

  // Handle config save
  const handleConfigSave = useCallback(
    (config: Record<string, any>) => {
      if (configNode) {
        onNodesChange(
          nodes.map(node =>
            node.id === configNode.id
              ? { ...node, config, status: 'CONNECTED' as const }
              : node
          )
        );
      }
      setConfigNode(null);
    },
    [configNode, nodes, onNodesChange]
  );

  return (
    <div style={{ width: '100%', height: '100%', minHeight: '500px', background: '#0a0a0f', position: 'relative' }}>
        <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        onNodesChange={onFlowNodesChange}
        onEdgesChange={onFlowEdgesChange}
        onNodeDragStop={handleNodeDragStop}
        onNodeClick={(_, node) => setSelectedNodeId(node.id)}
        onPaneClick={() => setSelectedNodeId(null)}
        onConnect={handleConnect}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        snapToGrid
        snapGrid={[20, 20]}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={2}
        connectionLineStyle={{ stroke: '#6366f1', strokeWidth: 2 }}
        connectionLineType="smoothstep"
        style={{ background: '#0a0a0f' }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={2}
          color="rgba(255,255,255,0.15)"
        />
        <Controls className="!bg-[#141419] !border-[rgba(255,255,255,0.1)] !rounded-xl" />
        
        {/* Canvas Actions Panel */}
        <Panel position="top-right">
          <div className="flex items-center gap-2">
            <button
              onClick={handleAutoLayout}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#141419]/90 backdrop-blur-md border border-[rgba(255,255,255,0.1)] text-white/80 hover:bg-[rgba(255,255,255,0.1)] transition-colors text-xs"
              title="Auto-layout (Cmd+L)"
            >
              <LayoutGrid className="w-4 h-4" />
              Auto-Layout
            </button>
            
            {selectedNodeId && (
              <button
                onClick={() => {
                  onNodesChange(nodes.filter(n => n.id !== selectedNodeId));
                  onEdgesChange(edges.filter(e => e.sourceId !== selectedNodeId && e.targetId !== selectedNodeId));
                  setSelectedNodeId(null);
                }}
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 backdrop-blur-md border border-red-500/20 text-red-400 hover:bg-red-500/20 transition-colors text-xs"
                title="Delete selected (Del)"
              >
                <Trash2 className="w-4 h-4" />
                Delete
              </button>
            )}
          </div>
        </Panel>
        
        {/* Layer Headers */}
        <Panel position="top-center">
          <div className="flex items-center gap-4 px-5 py-2.5 rounded-full bg-[#141419]/90 backdrop-blur-md border border-[rgba(255,255,255,0.1)]">
            {(['INGESTION', 'VERSION_CONTROL', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING'] as const).map((layer, i) => (
              <div key={layer} className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS[layer] }} />
                <span className="text-xs font-medium text-white/80">
                  {layer === 'TRANSFORMATION' ? 'Transform' :
                   layer === 'VERSION_CONTROL' ? 'VCS' :
                   layer.charAt(0) + layer.slice(1).toLowerCase()}
                </span>
                {i < 4 && <span className="text-white/30 ml-1">→</span>}
              </div>
            ))}
          </div>
        </Panel>

        {/* Connection Instructions & Keyboard Shortcuts */}
        <Panel position="bottom-center">
          <div className="px-4 py-2 rounded-lg bg-[#141419]/80 border border-[rgba(255,255,255,0.08)] text-xs text-white/60">
            <span className="text-white/40">Drag handles to connect</span>
            <span className="mx-2 text-white/20">|</span>
            <kbd className="px-1.5 py-0.5 bg-white/5 rounded text-[10px]">⌘S</kbd> Save
            <span className="mx-1.5 text-white/20">·</span>
            <kbd className="px-1.5 py-0.5 bg-white/5 rounded text-[10px]">⌘L</kbd> Layout
            <span className="mx-1.5 text-white/20">·</span>
            <kbd className="px-1.5 py-0.5 bg-white/5 rounded text-[10px]">Del</kbd> Delete
          </div>
        </Panel>
      </ReactFlow>

      {/* Empty State */}
      {nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <div className="text-center max-w-md">
            <div className="w-16 h-16 mx-auto mb-4 rounded-xl bg-indigo-500/20 flex items-center justify-center border border-indigo-500/30">
              <LayoutGrid className="w-8 h-8 text-indigo-400" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">Build Your Pipeline</h3>
            <p className="text-sm text-gray-400">Click tools from the sidebar to add them</p>
          </div>
        </div>
      )}

      {/* Config Modal */}
      {configNode && (
        <NodeConfigModal
          node={configNode}
          stackId={stackId}
          onSave={handleConfigSave}
          onClose={() => setConfigNode(null)}
        />
      )}
    </div>
  );
}

export default function PipelineCanvas(props: PipelineCanvasProps) {
  return (
    <ReactFlowProvider>
      <PipelineCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
