'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Position,
  MarkerType,
  BackgroundVariant,
  type NodeMouseHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { cn } from '@/lib/utils';
import { layoutGraph } from '@/components/lineage/layoutGraph';
import { unifiedNodeTypes } from '@/components/lineage/UnifiedNodes';
import {
  type ViewNode,
  type RenderedViewResponse,
  type UnifiedNodeCategory,
  isToolCategory,
  getConfidenceColor,
} from '@/components/lineage/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SelectionViewMode = 'lineage' | 'pipeline-overview';

export interface ChildItem {
  id: string;
  name: string;
  platformId: string;
}

export interface NodeMeta {
  id: string;
  name: string;
  fqn: string;
  platform: string;
  domain: string;
  /** For tool/service nodes from pipeline overview: actual graph node IDs of children */
  subNodeIds?: string[];
  /** Platform-specific child items (connectors, DAGs) with their IDs */
  childItems?: ChildItem[];
}

export interface NodeSelectionSurfaceProps {
  stackId: string;
  mode: SelectionViewMode;
  selectedNodeIds: string[];
  onSelectionChange: (nodeIds: string[]) => void;
  preselectedNodeIds?: string[];
  onNodesLoaded?: (nodes: NodeMeta[]) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Platform-specific overrides for service nodes that don't fit cleanly under
// a domain (e.g., Linux is "other" domain but should render as infrastructure).
const _SERVICE_PLATFORM_TO_CATEGORY: Record<string, UnifiedNodeCategory> = {
  github: 'version_control',
  gitlab: 'version_control',
  bitbucket: 'version_control',
  linux: 'infrastructure',
  linux_server: 'infrastructure',
};

const _DOMAIN_TO_CATEGORY: Record<string, UnifiedNodeCategory> = {
  warehouse: 'warehouse',
  transform: 'transformation',
  orchestration: 'orchestration',
  bi: 'reporting',
  ingestion: 'ingestion',
};

function viewNodeToCategory(vn: ViewNode): UnifiedNodeCategory {
  if (
    vn.platformDomain === 'ingestion' &&
    (vn.originalType === 'table' || vn.originalType === 'source')
  ) {
    return 'source';
  }
  const ot = vn.originalType as UnifiedNodeCategory;
  const known: UnifiedNodeCategory[] = [
    'table', 'view', 'source', 'model', 'dag', 'task', 'workflow',
    'connector', 'workbook', 'dataset', 'question', 'notebook',
    'file', 'test', 'dashboard', 'report',
  ];
  if (known.includes(ot)) return ot;

  // Service (tool) nodes: map by platform first, then by domain. This matches
  // the main lineage page's Pipeline Overview rendering (which colors and
  // labels each tool by its actual role, not the literal word "connector").
  if (vn.canonicalType === 'service') {
    const platform = (vn.platform || '').toLowerCase();
    const platformOverride = _SERVICE_PLATFORM_TO_CATEGORY[platform];
    if (platformOverride) return platformOverride;
    const domainCategory = _DOMAIN_TO_CATEGORY[vn.platformDomain || ''];
    if (domainCategory) return domainCategory;
    return 'connector';  // last-resort fallback for unknown service nodes
  }

  // Other canonical-type fallbacks
  switch (vn.canonicalType) {
    case 'job': return 'task';
    case 'dataset': return 'table';
    case 'semantic': return 'view';
    default: return 'table';
  }
}

// ---------------------------------------------------------------------------
// Selection highlight wrapper — wraps existing node types with selection ring
// ---------------------------------------------------------------------------

function withSelectionHighlight(
  NodeComponent: React.ComponentType<any>,
  selectedIds: Set<string>,
) {
  return function SelectableNode(props: any) {
    const isSelected = selectedIds.has(props.id);
    return (
      <div
        className={cn(
          'rounded-lg transition-all',
          isSelected && 'ring-2 ring-[var(--accent)] ring-offset-1 ring-offset-[var(--bg)]',
        )}
      >
        <NodeComponent {...props} />
      </div>
    );
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NodeSelectionSurface({
  stackId,
  mode,
  selectedNodeIds,
  onSelectionChange,
  preselectedNodeIds,
  onNodesLoaded,
}: NodeSelectionSurfaceProps) {
  const [viewData, setViewData] = useState<RenderedViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeSLAs, setNodeSLAs] = useState<Map<string, { status: string; profileName?: string | null }>>(new Map());

  // Fetch graph data
  useEffect(() => {
    if (!stackId) return;

    const action = mode === 'pipeline-overview'
      ? 'view-lane-pipeline-overview'
      : 'view-data-plane';

    setLoading(true);
    setError(null);

    fetch(`/api/pipeline/${stackId}/lineage/engine?action=${action}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
        return res.json();
      })
      .then((data: RenderedViewResponse) => {
        setViewData(data);
        setLoading(false);
        // Expose node metadata to parent
        if (onNodesLoaded && data.nodes) {
          const metas: NodeMeta[] = data.nodes.map((n) => {
            // Extract sub-node IDs for tool/service nodes (pipeline overview)
            const rawSubs: Array<{ id: string; name?: string; platformId?: string }> =
              n.metadata?.subNodes || [];
            const subs: string[] | undefined =
              rawSubs.map((s) => s.id).filter(Boolean);
            // Build childItems with platform-specific IDs (connector_id, dag_id)
            const childItems: ChildItem[] | undefined =
              rawSubs.length > 0
                ? rawSubs
                    .filter((s) => s.platformId)
                    .map((s) => ({ id: s.id, name: s.name || s.id, platformId: s.platformId! }))
                : undefined;
            return {
              id: n.id,
              name: n.name,
              fqn: n.metadata?.fqn || n.name,
              platform: n.platform || 'unknown',
              domain: n.platformDomain || 'other',
              subNodeIds: subs?.length ? subs : undefined,
              childItems: childItems?.length ? childItems : undefined,
            };
          });
          onNodesLoaded(metas);
        }
      })
      .catch((err) => {
        console.error('[NodeSelectionSurface] fetch error:', err);
        setError(err.message);
        setLoading(false);
      });
  }, [stackId, mode]);

  // Fetch SLA policies for nodes to show badges
  useEffect(() => {
    if (!viewData?.nodes?.length || !stackId) return;
    const fqns = viewData.nodes
      .filter((n) => n.canonicalType !== 'service')
      .map((n) => n.metadata?.fqn || n.name)
      .filter(Boolean);
    if (fqns.length === 0) return;
    fetch('/api/schedule/policies/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nodes: fqns.map((fqn) => ({ fqn, domain: 'warehouse', criticality: 'medium' })),
        stackId,
      }),
    })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data?.policies) return;
        const map = new Map<string, { status: string; profileName?: string | null }>();
        for (const [fqn, policy] of Object.entries(data.policies as Record<string, any>)) {
          if (policy.status && policy.status !== 'none') {
            map.set(fqn, { status: policy.status, profileName: policy.profileName });
          }
        }
        setNodeSLAs(map);
      })
      .catch(() => {});
  }, [viewData, stackId]);

  // Apply preselected nodes on mount
  useEffect(() => {
    if (preselectedNodeIds?.length && selectedNodeIds.length === 0) {
      onSelectionChange(preselectedNodeIds);
    }
    // Only run once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectedNodeIds]);

  const selectedSet = useMemo(() => new Set(selectedNodeIds), [selectedNodeIds]);

  // Build ReactFlow nodes/edges from view data
  const { flowNodes, flowEdges, allNodeIds } = useMemo(() => {
    if (!viewData?.nodes?.length) {
      return { flowNodes: [], flowEdges: [], allNodeIds: [] as string[] };
    }

    // Filter out service/system/job canonical types for data-plane view
    const visibleNodes = mode === 'lineage'
      ? viewData.nodes.filter(
          (n) =>
            n.canonicalType !== 'job' &&
            n.canonicalType !== 'service' &&
            n.canonicalType !== 'system',
        )
      : viewData.nodes;

    const visibleIds = new Set(visibleNodes.map((n) => n.id));

    const nodes: Node[] = visibleNodes.map((vn) => {
      const fqn = vn.metadata?.fqn || vn.name;
      const sla = nodeSLAs.get(fqn);
      return {
        id: vn.id,
        type: vn.canonicalType === 'service' ? 'toolNode' : 'dataAssetNode',
        position: { x: vn.x, y: vn.y },
        targetPosition: Position.Left,
        sourcePosition: Position.Right,
        data: {
          name: vn.name,
          fullName: fqn,
          category: viewNodeToCategory(vn),
          layer: vn.layer,
          toolType: vn.platform,
          database: vn.metadata?.database,
          schema: vn.metadata?.schema,
          tableName: vn.name,
          nodeType: vn.originalType,
          platforms: vn.metadata?.platforms,
          isInferred: vn.inferred,
          slaStatus: sla?.status || 'none',
          slaProfileName: sla?.profileName,
        },
      };
    });

    const edges: Edge[] = viewData.edges
      .filter((e) => visibleIds.has(e.sourceId) && visibleIds.has(e.targetId))
      .map((ve) => ({
        id: ve.id,
        source: ve.sourceId,
        target: ve.targetId,
        type: 'smoothstep',
        animated: false,
        style: {
          stroke: 'var(--text-faint)',
          strokeWidth: 1.5,
          opacity: 0.4,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: 'var(--text-faint)',
        },
      }));

    // If positions are all 0 (or not provided), use Dagre layout
    const hasPositions = nodes.some((n) => n.position.x !== 0 || n.position.y !== 0);
    if (!hasPositions && nodes.length > 0) {
      const layouted = layoutGraph(nodes, edges, { direction: 'LR' });
      return {
        flowNodes: layouted.nodes,
        flowEdges: layouted.edges,
        allNodeIds: visibleNodes.map((n) => n.id),
      };
    }

    return {
      flowNodes: nodes,
      flowEdges: edges,
      allNodeIds: visibleNodes.map((n) => n.id),
    };
  }, [viewData, mode, nodeSLAs]);

  // Build selectable node types with highlight ring
  const selectableNodeTypes = useMemo(
    () => ({
      toolNode: withSelectionHighlight(unifiedNodeTypes.toolNode, selectedSet),
      dataAssetNode: withSelectionHighlight(unifiedNodeTypes.dataAssetNode, selectedSet),
    }),
    [selectedSet],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  // Handle node click — toggle selection
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const id = node.id;
      if (selectedSet.has(id)) {
        onSelectionChange(selectedNodeIds.filter((nid) => nid !== id));
      } else {
        onSelectionChange([...selectedNodeIds, id]);
      }
    },
    [selectedNodeIds, selectedSet, onSelectionChange],
  );

  // Select all / clear
  const handleSelectAll = useCallback(() => {
    onSelectionChange([...allNodeIds]);
  }, [allNodeIds, onSelectionChange]);

  const handleClear = useCallback(() => {
    onSelectionChange([]);
  }, [onSelectionChange]);

  // ----- Loading & Error states -----
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center space-y-3">
          <div className="w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-[13px] text-[var(--muted)]">Loading graph...</p>
        </div>
      </div>
    );
  }

  if (error || !viewData) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center space-y-2">
          <p className="text-[13px] text-red-400">
            {error || 'No graph data available.'}
          </p>
          <p className="text-[11px] text-[var(--muted)]">
            Run a lineage scan first, then try again.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* ---- Toolbar ---- */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border)] bg-[var(--surface)]">
        <span className="text-[13px] font-medium text-[var(--accent)]">
          {selectedNodeIds.length}
        </span>
        <span className="text-[12px] text-[var(--muted)]">
          asset{selectedNodeIds.length !== 1 ? 's' : ''} selected
        </span>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={handleSelectAll}
            className="px-2 py-1 text-[11px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--subtle-bg)] rounded transition-colors"
          >
            Select All ({allNodeIds.length})
          </button>
          <button
            onClick={handleClear}
            disabled={selectedNodeIds.length === 0}
            className="px-2 py-1 text-[11px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--subtle-bg)] rounded transition-colors disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      </div>

      {/* ---- Graph ---- */}
      <div className="flex-1 min-h-[400px]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          nodeTypes={selectableNodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.05}
          maxZoom={1.5}
          defaultEdgeOptions={{ type: 'smoothstep' }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
        >
          <Controls
            className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg"
            showInteractive={false}
          />
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1.5}
            color="var(--text-faint)"
          />
        </ReactFlow>
      </div>
    </div>
  );
}
