/**
 * Pipeline Overview types
 *
 * Types specific to the enhanced Pipeline Overview tab.
 * These complement (not replace) the shared types in ../types.ts.
 */

import type { ViewNode, ViewEdge } from '../types';

// ── Enriched ViewNode metadata (matches backend enrichment) ──────────────

export interface HealthSummary {
  healthy: number;
  degraded: number;
  failing: number;
  unknown: number;
  stale: number;
}

export interface SubNodeInfo {
  id: string;
  name: string;
  type: string;
  fqn: string;
}

export interface ToolNodeMetadata {
  lane: string;
  assetCount: number;
  integrationId: string | null;
  isOrchestrator: boolean;
  isInfra: boolean;
  fromPipelineStack: boolean;
  healthSummary: HealthSummary;
  jobCount: number;
  lastRunTs: string | null;
  coverageGaps: string[];
  subNodes: SubNodeInfo[];
  totalSubNodeCount: number;
}

// ── Edge metadata ────────────────────────────────────────────────────────

export interface EdgeMetadata {
  semanticType: string;
  label: string;
  dataFlowCount: number;
  srcLane: string;
  tgtLane: string;
}

// ── OpsSummary (from stats.opsSummary) ───────────────────────────────────

export interface OpsSummary {
  totalTools: number;
  totalAssets: number;
  healthDistribution: {
    healthy: number;
    degraded: number;
    failing: number;
    unknown: number;
    stale: number;
  };
  coverageGapCount: number;
}

// ── Inspector panel state ────────────────────────────────────────────────

export type InspectorTarget =
  | { kind: 'node'; node: ViewNode }
  | { kind: 'edge'; edge: ViewEdge }
  | null;

export type InspectorTab = 'overview' | 'jobs' | 'assets' | 'coverage';

// ── Semantic edge styling ────────────────────────────────────────────────

export interface SemanticEdgeStyle {
  label: string;
  color: string;
  dashArray?: string;
}

export const SEMANTIC_EDGE_STYLES: Record<string, SemanticEdgeStyle> = {
  ingests:      { label: 'Ingests',      color: '#8B5CF6' },
  feeds:        { label: 'Feeds',        color: '#3B82F6' },
  transforms:   { label: 'Builds',       color: '#F59E0B' },
  orchestrates: { label: 'Orchestrates', color: '#F97316', dashArray: '6,3' },
  serves:       { label: 'Serves',       color: '#EC4899' },
  builds:       { label: 'Builds',       color: '#F59E0B' },
  data_flow:    { label: 'Data Flow',    color: '#6366F1' },
};

// ── Helpers ──────────────────────────────────────────────────────────────

/** Safe accessor for enriched tool node metadata */
export function getToolMeta(node: ViewNode): ToolNodeMetadata {
  const m = node.metadata || {};
  return {
    lane: m.lane ?? '',
    assetCount: m.assetCount ?? 0,
    integrationId: m.integrationId ?? null,
    isOrchestrator: m.isOrchestrator ?? false,
    isInfra: m.isInfra ?? false,
    fromPipelineStack: m.fromPipelineStack ?? false,
    healthSummary: m.healthSummary ?? { healthy: 0, degraded: 0, failing: 0, unknown: 0, stale: 0 },
    jobCount: m.jobCount ?? 0,
    lastRunTs: m.lastRunTs ?? null,
    coverageGaps: m.coverageGaps ?? [],
    subNodes: m.subNodes ?? [],
    totalSubNodeCount: m.totalSubNodeCount ?? 0,
  };
}

/** Safe accessor for edge metadata */
export function getEdgeMeta(edge: ViewEdge): EdgeMetadata {
  const m = (edge as any).metadata || {};
  return {
    semanticType: m.semanticType ?? 'data_flow',
    label: m.label ?? 'Data Flow',
    dataFlowCount: m.dataFlowCount ?? edge.evidenceCount ?? 0,
    srcLane: m.srcLane ?? '',
    tgtLane: m.tgtLane ?? '',
  };
}

/** Derive overall health status from a HealthSummary */
export function getOverallHealth(hs: HealthSummary): 'healthy' | 'degraded' | 'failing' | 'unknown' {
  if (hs.failing > 0) return 'failing';
  if (hs.degraded > 0 || hs.stale > 0) return 'degraded';
  if (hs.healthy > 0) return 'healthy';
  return 'unknown';
}

export const HEALTH_COLORS: Record<string, string> = {
  healthy: '#10B981',
  degraded: '#F59E0B',
  failing: '#EF4444',
  unknown: '#6B7280',
};

/** Coverage gap display labels */
export const COVERAGE_GAP_LABELS: Record<string, string> = {
  no_data_extracted: 'No data extracted',
  sparse_lineage: 'Sparse lineage',
  no_query_history: 'No query history',
  limited_perms: 'Limited perms',
  no_column_lineage: 'No column lineage',
};
