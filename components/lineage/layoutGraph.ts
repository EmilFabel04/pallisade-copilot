/**
 * Graph layout utility for the lineage page.
 *
 * Handles connected-component detection, per-component dagre layout,
 * vertical stacking of disconnected components, and orphan (zero-edge)
 * node grouping into a labeled ReactFlow group node.
 */

import type { Node, Edge } from 'reactflow';
import { Position } from 'reactflow';
import dagre from 'dagre';

// ── Constants ──────────────────────────────────────────────────────────────

const TOOL_NODE_WIDTH = 240;
const TOOL_NODE_HEIGHT = 110;
const DATA_NODE_WIDTH = 200;
const DATA_NODE_HEIGHT = 100;

export const ORPHAN_GROUP_ID = '__orphan_group__';

const ORPHAN_COLS = 3;
const ORPHAN_CELL_W = 260;
const ORPHAN_CELL_H = 140;
const ORPHAN_PAD = 40;
const ORPHAN_LABEL_H = 30; // vertical space reserved for the group label

const COMPONENT_GAP_Y = 100;
const ORPHAN_GAP_Y = 120;

// ── Types ──────────────────────────────────────────────────────────────────

export interface LayoutOptions {
  direction?: 'LR' | 'TB';
  nodesep?: number;
  ranksep?: number;
}

export interface LayoutResult {
  nodes: Node[];
  edges: Edge[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

function nodeDimensions(node: Node): { width: number; height: number } {
  const isToolNode = node.type === 'toolNode';
  return {
    width: isToolNode ? TOOL_NODE_WIDTH : DATA_NODE_WIDTH,
    height: isToolNode ? TOOL_NODE_HEIGHT : DATA_NODE_HEIGHT,
  };
}

/** Compute the bounding box of a set of positioned nodes. */
function boundingBox(nodes: Node[]): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  for (const n of nodes) {
    const { width, height } = nodeDimensions(n);
    const x = n.position.x;
    const y = n.position.y;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x + width > maxX) maxX = x + width;
    if (y + height > maxY) maxY = y + height;
  }

  return { minX, minY, maxX, maxY };
}

/**
 * Build an undirected adjacency map and a set of nodes that participate in
 * at least one edge.
 */
function buildAdjacency(
  nodeIds: Set<string>,
  edges: Edge[],
): { adj: Map<string, Set<string>>; connectedNodeIds: Set<string> } {
  const adj = new Map<string, Set<string>>();
  const connectedNodeIds = new Set<string>();

  for (const e of edges) {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;

    if (!adj.has(e.source)) adj.set(e.source, new Set());
    if (!adj.has(e.target)) adj.set(e.target, new Set());
    adj.get(e.source)!.add(e.target);
    adj.get(e.target)!.add(e.source);
    connectedNodeIds.add(e.source);
    connectedNodeIds.add(e.target);
  }

  return { adj, connectedNodeIds };
}

/** BFS to discover all connected components among the connected nodes. */
function findComponents(
  connectedNodeIds: Set<string>,
  adj: Map<string, Set<string>>,
): string[][] {
  const visited = new Set<string>();
  const components: string[][] = [];

  // Process in sorted order for determinism
  const sortedIds = [...connectedNodeIds].sort();

  for (const startId of sortedIds) {
    if (visited.has(startId)) continue;

    const component: string[] = [];
    const queue = [startId];
    visited.add(startId);

    while (queue.length > 0) {
      const current = queue.shift()!;
      component.push(current);

      const neighbors = adj.get(current);
      if (neighbors) {
        // Sort neighbors for deterministic traversal
        for (const neighbor of [...neighbors].sort()) {
          if (!visited.has(neighbor)) {
            visited.add(neighbor);
            queue.push(neighbor);
          }
        }
      }
    }

    component.sort();
    components.push(component);
  }

  // Sort components: largest first, then by first node ID for tie-breaking
  components.sort((a, b) => {
    if (b.length !== a.length) return b.length - a.length;
    return a[0].localeCompare(b[0]);
  });

  return components;
}

/** Run dagre layout on a single connected component. Returns positioned nodes. */
function layoutComponent(
  componentNodeIds: Set<string>,
  allNodes: Node[],
  allEdges: Edge[],
  options: Required<LayoutOptions>,
): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: options.direction,
    nodesep: options.nodesep,
    ranksep: options.ranksep,
    align: 'UL',
  });

  const componentNodes = allNodes.filter((n) => componentNodeIds.has(n.id));
  const componentEdges = allEdges.filter(
    (e) => componentNodeIds.has(e.source) && componentNodeIds.has(e.target),
  );

  for (const node of componentNodes) {
    const { width, height } = nodeDimensions(node);
    g.setNode(node.id, { width, height });
  }

  for (const edge of componentEdges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const isHorizontal = options.direction === 'LR';

  return componentNodes.map((node) => {
    const pos = g.node(node.id);
    const { width, height } = nodeDimensions(node);
    return {
      ...node,
      targetPosition: isHorizontal ? Position.Left : Position.Top,
      sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
      position: {
        x: pos.x - width / 2,
        y: pos.y - height / 2,
      },
    };
  });
}

/** Create the orphan group node and grid-position orphan nodes inside it. */
function buildOrphanGroup(
  orphanNodes: Node[],
  groupY: number,
  direction: 'LR' | 'TB',
): Node[] {
  if (orphanNodes.length === 0) return [];

  const sorted = [...orphanNodes].sort((a, b) => a.id.localeCompare(b.id));

  const totalCols = Math.min(sorted.length, ORPHAN_COLS);
  const totalRows = Math.ceil(sorted.length / ORPHAN_COLS);
  const groupWidth = 2 * ORPHAN_PAD + totalCols * ORPHAN_CELL_W;
  const groupHeight = 2 * ORPHAN_PAD + ORPHAN_LABEL_H + totalRows * ORPHAN_CELL_H;

  const isHorizontal = direction === 'LR';

  const groupNode: Node = {
    id: ORPHAN_GROUP_ID,
    type: 'orphanGroup',
    position: { x: 0, y: groupY },
    data: { label: 'Unconnected / Not Yet Mapped' },
    draggable: false,
    selectable: false,
    connectable: false,
    style: {
      backgroundColor: 'rgba(100, 116, 139, 0.06)',
      border: '1px dashed rgba(148, 163, 184, 0.3)',
      borderRadius: '12px',
      width: groupWidth,
      height: groupHeight,
    },
  };

  const positionedOrphans: Node[] = sorted.map((node, index) => {
    const col = index % ORPHAN_COLS;
    const row = Math.floor(index / ORPHAN_COLS);
    return {
      ...node,
      parentNode: ORPHAN_GROUP_ID,
      extent: 'parent' as const,
      targetPosition: isHorizontal ? Position.Left : Position.Top,
      sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
      position: {
        x: ORPHAN_PAD + col * ORPHAN_CELL_W,
        y: ORPHAN_PAD + ORPHAN_LABEL_H + row * ORPHAN_CELL_H,
      },
    };
  });

  // Group node must come before its children in the array
  return [groupNode, ...positionedOrphans];
}

// ── Public API ─────────────────────────────────────────────────────────────

/**
 * Layout a graph with connected-component detection, per-component dagre
 * positioning, vertical stacking, and orphan grouping.
 *
 * Replaces the previous `getLayoutedElements` function.
 */
export function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  options?: LayoutOptions,
): LayoutResult {
  if (nodes.length === 0) return { nodes: [], edges };

  const opts: Required<LayoutOptions> = {
    direction: options?.direction ?? 'LR',
    nodesep: options?.nodesep ?? 80,
    ranksep: options?.ranksep ?? 200,
  };

  const nodeIds = new Set(nodes.map((n) => n.id));
  const { adj, connectedNodeIds } = buildAdjacency(nodeIds, edges);

  // Separate orphans (nodes with zero edges)
  const orphanNodes = nodes.filter((n) => !connectedNodeIds.has(n.id));
  const connectedNodes = nodes.filter((n) => connectedNodeIds.has(n.id));

  // If everything is orphaned, just build the group — no dagre needed
  if (connectedNodes.length === 0) {
    const groupNodes = buildOrphanGroup(orphanNodes, 0, opts.direction);
    return { nodes: groupNodes, edges };
  }

  // Find connected components among the connected nodes
  const components = findComponents(connectedNodeIds, adj);

  // Layout each component and stack vertically
  let yOffset = 0;
  const allPositioned: Node[] = [];

  for (const component of components) {
    const componentSet = new Set(component);
    const positioned = layoutComponent(componentSet, connectedNodes, edges, opts);

    if (positioned.length === 0) continue;

    // Compute bounding box of this component
    const bb = boundingBox(positioned);
    const componentMinY = bb.minY;

    // Shift component so its top aligns at yOffset (and left at x=0)
    const shiftY = yOffset - componentMinY;
    const shiftX = -bb.minX;

    for (const node of positioned) {
      node.position.x += shiftX;
      node.position.y += shiftY;
      allPositioned.push(node);
    }

    // Update offset for next component
    const adjustedMaxY = bb.maxY + shiftY;
    yOffset = adjustedMaxY + COMPONENT_GAP_Y;
  }

  // Build orphan group below all connected components
  const orphanGroupY = yOffset - COMPONENT_GAP_Y + ORPHAN_GAP_Y;
  const orphanGroupNodes = buildOrphanGroup(orphanNodes, orphanGroupY, opts.direction);

  // Dev-mode assertions
  if (process.env.NODE_ENV === 'development') {
    for (const n of allPositioned) {
      console.assert(
        typeof n.position.x === 'number' && typeof n.position.y === 'number',
        `[layoutGraph] Node ${n.id} missing position`,
      );
    }
    if (orphanGroupNodes.length > 0) {
      const groupNode = orphanGroupNodes[0];
      for (let i = 1; i < orphanGroupNodes.length; i++) {
        const orphan = orphanGroupNodes[i];
        console.assert(
          orphan.parentNode === ORPHAN_GROUP_ID,
          `[layoutGraph] Orphan ${orphan.id} missing parentNode`,
        );
        console.assert(
          orphan.position.x >= 0 && orphan.position.y >= 0,
          `[layoutGraph] Orphan ${orphan.id} has negative position inside group`,
        );
      }
    }
  }

  return {
    nodes: [...allPositioned, ...orphanGroupNodes],
    edges,
  };
}

/**
 * Handle orphan nodes for the rendered-view path where the backend already
 * provides x/y positions for connected nodes.
 *
 * Detects orphan nodes (no edges) among the positioned nodes, incorporates
 * unmapped nodes from the backend response, and places them in a group
 * below the main graph.
 */
export function layoutRenderedViewOrphans(
  positionedNodes: Node[],
  edges: Edge[],
  unmappedNodes?: Array<{
    id: string;
    name: string;
    fqn: string;
    originalType: string;
    platform: string;
    sources: string[];
  }>,
): LayoutResult {
  if (positionedNodes.length === 0 && (!unmappedNodes || unmappedNodes.length === 0)) {
    return { nodes: positionedNodes, edges };
  }

  // Find which nodes have edges
  const edgeNodeIds = new Set<string>();
  for (const e of edges) {
    edgeNodeIds.add(e.source);
    edgeNodeIds.add(e.target);
  }

  // Split existing nodes into connected and orphaned
  const connectedNodes: Node[] = [];
  const orphanNodes: Node[] = [];

  for (const node of positionedNodes) {
    if (edgeNodeIds.has(node.id)) {
      connectedNodes.push(node);
    } else {
      orphanNodes.push(node);
    }
  }

  // Convert unmapped nodes from backend into ReactFlow node objects
  if (unmappedNodes && unmappedNodes.length > 0) {
    const existingIds = new Set(positionedNodes.map((n) => n.id));
    for (const un of unmappedNodes) {
      if (existingIds.has(un.id)) continue;
      orphanNodes.push({
        id: un.id,
        type: 'dataAssetNode',
        position: { x: 0, y: 0 },
        targetPosition: Position.Left,
        sourcePosition: Position.Right,
        data: {
          name: un.name,
          fullName: un.fqn,
          category: un.originalType === 'view' ? 'view'
            : un.originalType === 'model' ? 'model'
            : un.originalType === 'source' ? 'source'
            : 'table',
          layer: 'WAREHOUSE',
          toolType: un.platform,
          nodeType: un.originalType,
          isOverlay: true,
        },
      });
    }
  }

  // If no orphans, return as-is
  if (orphanNodes.length === 0) {
    return { nodes: positionedNodes, edges };
  }

  // Compute bounding box of connected nodes to place orphan group below
  const bb = connectedNodes.length > 0
    ? boundingBox(connectedNodes)
    : { minX: 0, minY: 0, maxX: 0, maxY: 0 };

  const groupY = bb.maxY + ORPHAN_GAP_Y;
  const orphanGroupNodes = buildOrphanGroup(orphanNodes, groupY, 'LR');

  return {
    nodes: [...connectedNodes, ...orphanGroupNodes],
    edges,
  };
}
