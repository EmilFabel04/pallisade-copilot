/**
 * Unified Lineage Types
 *
 * Type definitions for the unified pipeline lineage view that combines
 * tool nodes (ingestion, transformation, warehouse, reporting) with
 * data asset nodes (tables, views, models, sources).
 */

import { PipelineLayer, LAYER_COLORS } from '@/components/pipeline/types';

// Which lineage plane an edge belongs to
export type LinePlane = 'data' | 'control' | 'cross';

// Active view tab on the lineage page
export type LineageViewTab = 'data' | 'orchestration';

// Run summary for DAG/task nodes (from raw_metadata)
export interface RunSummary {
  lastRunState?: string;       // 'success' | 'failed' | 'running'
  lastRunDate?: string;        // ISO timestamp
  successRate?: number;        // 0–100
  avgDurationMinutes?: number;
}

// A single DAG run (from Airflow API)
export interface DagRun {
  runId: string;
  state: string;               // 'success' | 'failed' | 'running' | 'queued'
  executionDate?: string;
  startDate?: string;
  endDate?: string;
  durationMinutes?: number;
}

// A single task instance within a DAG run
export interface TaskInstance {
  taskId: string;
  state: string;
  duration?: number;
  operator?: string;
  tryNumber?: number;
}

// Orchestration context for a data asset (cross-link info)
export interface OrchestrationContext {
  dagNode?: UnifiedLineageNode;
  taskNode?: UnifiedLineageNode;
  edgeType: string;            // 'writes_to', 'produced_by', etc.
  runSummary?: RunSummary;
}

// Response from control-plane API
export interface ControlPlaneResponse {
  dagId: string;
  nodes: UnifiedLineageNode[];
  edges: UnifiedLineageEdge[];
  stats: {
    totalNodes: number;
    totalEdges: number;
    taskCount: number;
    crossLinkCount: number;
  };
}

// All possible node categories in the unified lineage
export type UnifiedNodeCategory =
  | 'ingestion'       // Fivetran, Airbyte, Stitch connectors
  | 'transformation'  // dbt, Dagster jobs
  | 'warehouse'       // Snowflake, BigQuery tools (the platform node)
  | 'reporting'       // Tableau, Looker, Power BI dashboards
  | 'orchestration'   // Airflow (tool-level, from pipeline nodes)
  | 'table'           // Database table
  | 'view'            // Database view
  | 'source'          // dbt source
  | 'model'           // dbt model
  | 'dag'             // Airflow DAG (orchestration job)
  | 'task';           // Airflow task (orchestration step)

// Issue summary for data assets
export interface DataAssetIssues {
  total: number;
  open: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  byType: Record<string, number>;  // e.g., { freshness: 2, quality: 1 }
}

// A node in the unified lineage graph
export interface UnifiedLineageNode {
  id: string;
  name: string;           // Display name
  fullName?: string;      // FQN for tables, tool name for tools
  category: UnifiedNodeCategory;
  layer: PipelineLayer;   // Which pipeline layer this belongs to

  // Tool-specific (when category is ingestion/transformation/warehouse/reporting)
  toolType?: string;      // fivetran, dbt_cloud, snowflake, tableau etc.
  status?: string;        // CONNECTED, PENDING, ERROR, etc.
  healthScore?: number;
  findingsCount?: number;
  criticalCount?: number;
  highCount?: number;

  // Table-specific (when category is table/view/source/model)
  database?: string;
  schema?: string;
  tableName?: string;
  nodeType?: string;      // table, view, source, model
  criticality?: string;
  rowCount?: number;
  upstreamCount?: number;
  downstreamCount?: number;

  // Data asset health & issues
  lastUpdated?: string;           // When the table was last updated
  freshnessStatus?: 'fresh' | 'stale' | 'unknown';  // Computed freshness
  freshnessHours?: number;        // Hours since last update
  issues?: DataAssetIssues;       // Issue summary

  // Orchestration context (for DAG/task nodes or cross-linked assets)
  runSummary?: RunSummary;

  // Common
  integrationId?: string;
  description?: string;
  owner?: string;
  tags?: string[];
}

// Evidence record for a lineage edge (from engine)
export interface EdgeEvidence {
  adapterId: string;
  sourceRef: string;
  observedAt?: string;
  snippet?: string;
}

// Column mapping from engine (from_column -> to_column)
export interface ColumnMapping {
  from: string;
  to: string;
  transformExpr?: string;
  confidence?: number;
}

// An edge in the unified lineage graph
export interface UnifiedLineageEdge {
  id: string;
  source: string;       // source node ID
  target: string;       // target node ID
  edgeType: string;     // depends_on, populates, reads_from, contains, etc.
  label?: string;
  columns?: (string | ColumnMapping)[];  // strings from Prisma, objects from engine
  animated?: boolean;
  // Engine fields (when available)
  confidence?: number;          // 0.0–1.0 from evidence weighting
  lineageLevel?: string;        // "tool" | "table" | "column"
  plane?: LinePlane;            // "data" | "control" | "cross"
  evidence?: EdgeEvidence[];    // provenance records from adapters
}

// Blast radius result from engine API
export interface BlastRadiusResult {
  total_downstream: number;
  by_domain: Record<string, number>;
  by_kind: Record<string, number>;
  critical_paths: number;
}

// Helper to render a column mapping (handles both string and object forms)
export function formatColumnMapping(col: string | ColumnMapping): string {
  if (typeof col === 'string') return col;
  return `${col.from} \u2192 ${col.to}`;
}

// Lineage level for engine filtering
export type LineageLevelFilter = 'all' | 'tool' | 'table' | 'column';

// Filter state for the lineage view
export interface LineageFilterState {
  layers: Set<PipelineLayer>;     // Which layers are visible
  showToolNodes: boolean;          // Show ingestion/transformation/warehouse/reporting tool nodes
  showTableNodes: boolean;         // Show table/view/model nodes
  searchQuery: string;
  lineageLevel: LineageLevelFilter; // Filter edges by lineage level
  minConfidence: number;            // Min confidence threshold (0.0–1.0)
}

// Quick filter preset
export type LineageFilterPreset = 'full' | 'warehouse-only' | 'etl-only' | 'bi-impact';

// Engine coverage statistics
export interface EngineCoverageStats {
  totalNodes: number;
  totalEdges: number;
  edgesByLevel: Record<string, number>;
  coverageTable: number;   // 0.0–1.0
  coverageColumn: number;  // 0.0–1.0
  highConfidencePct: number;
  mediumConfidencePct: number;
  lowConfidencePct: number;
}

// API response from unified endpoint
export interface UnifiedLineageResponse {
  nodes: UnifiedLineageNode[];
  edges: UnifiedLineageEdge[];
  stats: {
    totalNodes: number;
    totalEdges: number;
    toolNodes: number;
    tableNodes: number;
    viewNodes: number;
    modelNodes: number;
  };
  availableLayers: PipelineLayer[];
  availableTools: string[];
  lastExtracted?: string;
  engineStats?: EngineCoverageStats;  // Present when engine graph is available
}

// Category-to-layer mapping
export const CATEGORY_LAYER_MAP: Record<UnifiedNodeCategory, PipelineLayer> = {
  ingestion: 'INGESTION',
  transformation: 'TRANSFORMATION',
  warehouse: 'WAREHOUSE',
  reporting: 'REPORTING',
  orchestration: 'ORCHESTRATION',
  table: 'WAREHOUSE',
  view: 'WAREHOUSE',
  source: 'INGESTION',  // dbt sources are upstream
  model: 'TRANSFORMATION',
  dag: 'ORCHESTRATION',
  task: 'ORCHESTRATION',
};

// Visual config per category
export const CATEGORY_VISUALS: Record<UnifiedNodeCategory, {
  icon: string;
  color: string;
  borderColor: string;
  bgColor: string;
  label: string;
}> = {
  ingestion: {
    icon: 'upload',
    color: LAYER_COLORS.INGESTION,
    borderColor: LAYER_COLORS.INGESTION,
    bgColor: 'rgba(16,185,129,0.15)',
    label: 'Ingestion',
  },
  transformation: {
    icon: 'shuffle',
    color: LAYER_COLORS.TRANSFORMATION,
    borderColor: LAYER_COLORS.TRANSFORMATION,
    bgColor: 'rgba(245,158,11,0.15)',
    label: 'Transformation',
  },
  warehouse: {
    icon: 'database',
    color: LAYER_COLORS.WAREHOUSE,
    borderColor: LAYER_COLORS.WAREHOUSE,
    bgColor: 'rgba(99,102,241,0.15)',
    label: 'Warehouse',
  },
  reporting: {
    icon: 'bar-chart',
    color: LAYER_COLORS.REPORTING,
    borderColor: LAYER_COLORS.REPORTING,
    bgColor: 'rgba(6,182,212,0.15)',
    label: 'Reporting',
  },
  orchestration: {
    icon: 'workflow',
    color: LAYER_COLORS.ORCHESTRATION,
    borderColor: LAYER_COLORS.ORCHESTRATION,
    bgColor: 'rgba(249,115,22,0.15)',
    label: 'Orchestration',
  },
  table: {
    icon: 'table',
    color: '#3B82F6',
    borderColor: '#3B82F6',
    bgColor: 'rgba(59,130,246,0.15)',
    label: 'Table',
  },
  view: {
    icon: 'eye',
    color: '#A855F7',
    borderColor: '#A855F7',
    bgColor: 'rgba(168,85,247,0.15)',
    label: 'View',
  },
  source: {
    icon: 'arrow-down-to-line',
    color: '#10B981',
    borderColor: '#10B981',
    bgColor: 'rgba(16,185,129,0.1)',
    label: 'Source',
  },
  model: {
    icon: 'cog',
    color: '#F59E0B',
    borderColor: '#F59E0B',
    bgColor: 'rgba(245,158,11,0.1)',
    label: 'Model',
  },
  dag: {
    icon: 'workflow',
    color: '#F97316',
    borderColor: '#F97316',
    bgColor: 'rgba(249,115,22,0.12)',
    label: 'DAG',
  },
  task: {
    icon: 'play',
    color: '#FB923C',
    borderColor: '#FB923C',
    bgColor: 'rgba(251,146,60,0.1)',
    label: 'Task',
  },
};

// Preset filter configurations
export const FILTER_PRESETS: Record<LineageFilterPreset, {
  label: string;
  description: string;
  layers: PipelineLayer[];
  showToolNodes: boolean;
  showTableNodes: boolean;
}> = {
  'full': {
    label: 'Full Pipeline',
    description: 'Show all tools and data assets',
    layers: ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'ORCHESTRATION'],
    showToolNodes: true,
    showTableNodes: true,
  },
  'warehouse-only': {
    label: 'Warehouse Only',
    description: 'Show only tables and views',
    layers: ['WAREHOUSE'],
    showToolNodes: false,
    showTableNodes: true,
  },
  'etl-only': {
    label: 'ETL Only',
    description: 'Show ingestion and transformation',
    layers: ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE'],
    showToolNodes: true,
    showTableNodes: true,
  },
  'bi-impact': {
    label: 'BI Impact',
    description: 'Show warehouse to reporting flow',
    layers: ['WAREHOUSE', 'REPORTING'],
    showToolNodes: true,
    showTableNodes: true,
  },
};

// Check if a category is a tool category (pipeline tool nodes)
export function isToolCategory(category: UnifiedNodeCategory): boolean {
  return ['ingestion', 'transformation', 'warehouse', 'reporting', 'orchestration'].includes(category);
}

// Check if a category is a data asset category
export function isDataAssetCategory(category: UnifiedNodeCategory): boolean {
  return ['table', 'view', 'source', 'model', 'dag', 'task'].includes(category);
}

// Get the default filter state
export function getDefaultFilterState(): LineageFilterState {
  return {
    layers: new Set(['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'ORCHESTRATION']),
    showToolNodes: true,
    showTableNodes: true,
    searchQuery: '',
    lineageLevel: 'all',
    minConfidence: 0,
  };
}

// Apply a preset to the filter state
export function applyFilterPreset(preset: LineageFilterPreset): LineageFilterState {
  const config = FILTER_PRESETS[preset];
  return {
    layers: new Set(config.layers),
    showToolNodes: config.showToolNodes,
    showTableNodes: config.showTableNodes,
    searchQuery: '',
    lineageLevel: 'all',
    minConfidence: 0,
  };
}

// Get edge color based on confidence score
export function getConfidenceColor(confidence?: number): string {
  if (confidence === undefined) return '#818CF8'; // default indigo
  if (confidence >= 0.8) return '#10B981'; // green
  if (confidence >= 0.5) return '#F59E0B'; // amber
  return '#EF4444'; // red
}

// Check if an edge passes confidence/level filters
export function edgePassesFilter(
  edge: UnifiedLineageEdge,
  filters: LineageFilterState
): boolean {
  if (filters.lineageLevel !== 'all') {
    if (!edge.lineageLevel || edge.lineageLevel !== filters.lineageLevel) {
      return false;
    }
  }
  if (filters.minConfidence > 0 && edge.confidence !== undefined && edge.confidence < filters.minConfidence) {
    return false;
  }
  return true;
}

// Find orchestration nodes cross-linked to a data asset
export function getCrossLinkedOrchestration(
  nodeId: string,
  allEdges: UnifiedLineageEdge[],
  allNodes: UnifiedLineageNode[],
): OrchestrationContext[] {
  const nodeMap = new Map(allNodes.map(n => [n.id, n]));
  const contexts: OrchestrationContext[] = [];

  for (const edge of allEdges) {
    if (edge.plane !== 'cross') continue;

    // Edge connects this node to an orchestration entity
    let orchNodeId: string | null = null;
    if (edge.source === nodeId) orchNodeId = edge.target;
    else if (edge.target === nodeId) orchNodeId = edge.source;
    else continue;

    const orchNode = nodeMap.get(orchNodeId);
    if (!orchNode) continue;

    const isTask = orchNode.category === 'task';
    const isDag = orchNode.category === 'dag';
    if (!isTask && !isDag) continue;

    contexts.push({
      dagNode: isDag ? orchNode : undefined,
      taskNode: isTask ? orchNode : undefined,
      edgeType: edge.edgeType,
      runSummary: orchNode.runSummary,
    });
  }

  return contexts;
}

// Check if a node passes the current filters
export function nodePassesFilter(
  node: UnifiedLineageNode,
  filters: LineageFilterState
): boolean {
  // Check layer filter
  if (!filters.layers.has(node.layer)) {
    return false;
  }

  // Check tool/table node filter
  const isTool = isToolCategory(node.category);
  if (isTool && !filters.showToolNodes) {
    return false;
  }
  if (!isTool && !filters.showTableNodes) {
    return false;
  }

  // Check search query
  if (filters.searchQuery) {
    const query = filters.searchQuery.toLowerCase();
    const nameMatch = node.name.toLowerCase().includes(query);
    const fullNameMatch = node.fullName?.toLowerCase().includes(query) || false;
    const toolTypeMatch = node.toolType?.toLowerCase().includes(query) || false;
    const tableNameMatch = node.tableName?.toLowerCase().includes(query) || false;

    if (!nameMatch && !fullNameMatch && !toolTypeMatch && !tableNameMatch) {
      return false;
    }
  }

  return true;
}
