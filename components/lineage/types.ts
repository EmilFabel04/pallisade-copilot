/**
 * Unified Lineage Types
 *
 * Type definitions for the unified pipeline lineage view that combines
 * tool nodes (ingestion, transformation, warehouse, reporting) with
 * data asset nodes (tables, views, models, sources).
 */

import { PipelineLayer, LAYER_COLORS } from '@/components/pipeline/types';

// All possible node categories in the unified lineage
export type UnifiedNodeCategory =
  | 'ingestion'       // Fivetran, Airbyte, Stitch connectors
  | 'transformation'  // dbt, Airflow, Dagster jobs
  | 'warehouse'       // Snowflake, BigQuery tools (the platform node)
  | 'reporting'       // Tableau, Looker, Power BI dashboards
  | 'table'           // Database table
  | 'view'            // Database view
  | 'source'          // dbt source
  | 'model';          // dbt model

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

  // Common
  integrationId?: string;
  description?: string;
  owner?: string;
  tags?: string[];
}

// An edge in the unified lineage graph
export interface UnifiedLineageEdge {
  id: string;
  source: string;       // source node ID
  target: string;       // target node ID
  edgeType: string;     // depends_on, populates, reads_from, contains, etc.
  label?: string;
  columns?: string[];
  animated?: boolean;
}

// Filter state for the lineage view
export interface LineageFilterState {
  layers: Set<PipelineLayer>;     // Which layers are visible
  showToolNodes: boolean;          // Show ingestion/transformation/warehouse/reporting tool nodes
  showTableNodes: boolean;         // Show table/view/model nodes
  searchQuery: string;
}

// Quick filter preset
export type LineageFilterPreset = 'full' | 'warehouse-only' | 'etl-only' | 'bi-impact';

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
}

// Category-to-layer mapping
export const CATEGORY_LAYER_MAP: Record<UnifiedNodeCategory, PipelineLayer> = {
  ingestion: 'INGESTION',
  transformation: 'TRANSFORMATION',
  warehouse: 'WAREHOUSE',
  reporting: 'REPORTING',
  table: 'WAREHOUSE',
  view: 'WAREHOUSE',
  source: 'INGESTION',  // dbt sources are upstream
  model: 'TRANSFORMATION',
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
    layers: ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING'],
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

// Check if a category is a tool category
export function isToolCategory(category: UnifiedNodeCategory): boolean {
  return ['ingestion', 'transformation', 'warehouse', 'reporting'].includes(category);
}

// Check if a category is a data asset category
export function isDataAssetCategory(category: UnifiedNodeCategory): boolean {
  return ['table', 'view', 'source', 'model'].includes(category);
}

// Get the default filter state
export function getDefaultFilterState(): LineageFilterState {
  return {
    layers: new Set(['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING']),
    showToolNodes: true,
    showTableNodes: true,
    searchQuery: '',
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
  };
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
