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
  isJob?: boolean;
}

export interface ToolNodeMetadata {
  lane: string;
  assetCount: number;
  integrationId: string | null;
  isOrchestrator: boolean;
  isInfra: boolean;
  fromPipelineStack: boolean;
  functionalRole?: string;
  healthSummary: HealthSummary;
  jobCount: number;
  lastRunTs: string | null;
  coverageGaps: string[];
  subNodes: SubNodeInfo[];
  totalSubNodeCount: number;
  jobSupport: 'full' | 'not_applicable' | 'no_data';
}

// ── Edge metadata ────────────────────────────────────────────────────────

export interface BypassJob {
  jobNodeId: string;
  jobNodeName: string;
  originalEdgeIds: string[];
}

export interface BypassPath {
  jobs: BypassJob[];
  summary: string;
}

export interface EdgeMetadata {
  semanticType: string;
  label: string;
  evidenceType?: string; // data_derivation | job_orchestration | code_ownership | hosting | monitoring | inferred_adjacency
  edgeOrigin?: 'evidence' | 'structural' | 'inferred';
  relationshipBasis?: string; // WHY this edge exists (see RELATIONSHIP_BASIS_LABELS)
  dataFlowCount: number;
  flowAssetCount?: number;
  topPairs?: { src: string; tgt: string; count: number }[];
  evidenceMix?: Record<string, number>;
  srcLane: string;
  tgtLane: string;
  bypassPath?: BypassPath;
}

/** Human-readable labels for relationship basis values (no vendor-specific text). */
export const RELATIONSHIP_BASIS_LABELS: Record<string, string> = {
  asset_evidence: 'Observed data lineage',
  metadata_reference: 'Metadata cross-reference',
  explicit_config: 'Explicitly configured',
  monitoring_coexistence: 'Quality tool monitors data assets',
  pipeline_coexistence: 'Tools co-exist in pipeline',
};

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

export type InspectorTab = string;  // Dynamic: 'overview' + domain-specific tab keys

// ── Semantic edge styling ────────────────────────────────────────────────

export interface SemanticEdgeStyle {
  label: string;
  color: string;
  dashArray?: string;
}

export const SEMANTIC_EDGE_STYLES: Record<string, SemanticEdgeStyle> = {
  ingests:          { label: 'Ingests',       color: '#8B5CF6' },
  feeds:            { label: 'Feeds',         color: '#3B82F6' },
  transforms:       { label: 'Builds',        color: '#F59E0B' },
  orchestrates:     { label: 'Orchestrates',  color: '#F97316', dashArray: '6,3' },
  serves:           { label: 'Serves',        color: '#EC4899' },
  builds:           { label: 'Builds',        color: '#F59E0B' },
  manages_code_for: { label: 'Manages Code',  color: '#6B7280', dashArray: '4,2' },
  hosts:            { label: 'Hosts',          color: '#9CA3AF', dashArray: '4,2' },
  monitors:         { label: 'Monitors',       color: '#14B8A6', dashArray: '4,2' },
  data_flow:        { label: 'Data Flow',      color: '#6366F1' },
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
    jobSupport: m.jobSupport ?? 'full',
  };
}

/** Safe accessor for edge metadata */
export function getEdgeMeta(edge: ViewEdge): EdgeMetadata {
  const m = (edge as any).metadata || {};
  return {
    semanticType: m.semanticType ?? 'data_flow',
    label: m.label ?? 'Data Flow',
    evidenceType: m.evidenceType,
    edgeOrigin: m.edgeOrigin,
    relationshipBasis: m.relationshipBasis,
    dataFlowCount: m.dataFlowCount ?? edge.evidenceCount ?? 0,
    flowAssetCount: m.flowAssetCount,
    topPairs: m.topPairs,
    evidenceMix: m.evidenceMix,
    srcLane: m.srcLane ?? '',
    tgtLane: m.tgtLane ?? '',
    bypassPath: m.bypassPath,
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
  no_activity_data_yet: 'No activity data yet',
  sparse_lineage: 'Sparse lineage',
  no_query_history: 'No query history',
  limited_perms: 'Limited perms',
  no_column_lineage: 'No column lineage',
};

// ── Tool Details (on-demand detail view per tool) ─────────────────────

/** A single item in a tool detail group */
export interface ToolDetailItem {
  id: string;
  name: string;
  fqn: string;
  canonicalType: string;
  originalType: string;
  healthStatus?: string;
  observedAt?: string | null;
  container?: string;           // schema/dataset grouping key
  itemCount?: number;           // child count (e.g., tables in a dataset)
  zone?: string;                // dataset zone (raw, staging, mart)
  metadata?: Record<string, any>;
}

/** A tab definition in the tool details response */
export interface ToolDetailTab {
  key: string;
  label: string;
  count: number;
}

/** A connected tool reference */
export interface ToolConnection {
  toolId: string;
  name: string;
  platform: string;
  edgeCount: number;
}

/** Full response from the tool-details endpoint */
export interface ToolDetailsResponse {
  toolId: string;
  platform: string;
  platformDomain: string;
  category: string;
  displayName: string;
  integrationId: string | null;
  error?: string;
  summary: {
    totalAssets: number;
    healthSummary: HealthSummary;
    jobCount: number;
    lastRunTs: string | null;
    coverageGaps: string[];
  };
  tabs: ToolDetailTab[];
  groups: Record<string, ToolDetailItem[]>;
  connections: {
    upstream: ToolConnection[];
    downstream: ToolConnection[];
  };
}
