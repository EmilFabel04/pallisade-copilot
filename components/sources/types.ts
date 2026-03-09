import { PipelineLayer } from '@/components/pipeline/types';
import type { EffectiveContract, InheritanceState } from '@/components/contracts/types';

// Source contract (ownership + expectations)
export interface SourceContractData {
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: SlaTier | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  notes: string | null;
  // Inheritance fields
  inheritFromPipeline?: boolean;
  pipelineStackId?: string | null;
  overridesJson?: Record<string, any> | null;
}

export type SlaTier = 'T0' | 'T1' | 'T2' | 'T3';

export const SLA_CONFIG: Record<SlaTier, { label: string; color: string; bg: string }> = {
  T0: { label: 'T0 Critical', color: 'text-red-400', bg: 'bg-red-500/15' },
  T1: { label: 'T1 High', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  T2: { label: 'T2 Medium', color: 'text-blue-400', bg: 'bg-blue-500/15' },
  T3: { label: 'T3 Low', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

// Extraction status
export type ExtractionStatus = 'ok' | 'stale' | 'failed' | 'never';

export const EXTRACTION_STATUS_CONFIG: Record<ExtractionStatus, { label: string; color: string; bg: string }> = {
  ok: { label: 'OK', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  stale: { label: 'Stale', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  failed: { label: 'Failed', color: 'text-red-400', bg: 'bg-red-500/15' },
  never: { label: 'Never', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

// Normalized source for the control plane view
export interface ControlPlaneSource {
  id: string;
  name: string;
  toolType: string;
  integrationType: string;
  layer: PipelineLayer;
  origin: 'pipeline' | 'legacy';

  // Status
  status: SourceStatus;
  healthScore: number | null;
  lastTestedAt: string | null;
  lastError: string | null;
  lastScanAt: string | null;

  // Extraction timestamps
  lastExtractedAt: string | null;
  lastLineageExtractedAt: string | null;
  lastSchemaExtractedAt: string | null;
  lastLogsExtractedAt: string | null;
  extractionStatus: ExtractionStatus;

  // Scope
  connectionInfo: string | null;
  scopeSummary: string;

  // Capabilities
  capabilities: SourceCapability[];

  // Credential health
  tokenExpiry: string | null;

  // Findings
  findingsCount: number;
  criticalCount: number;
  highCount: number;

  // Contract
  contract: SourceContractData | null;
  effectiveContract: EffectiveContract | null;
  inheritanceState: InheritanceState | null;

  // Metadata
  config: Record<string, any> | null;
  stackId: string | null;
  createdAt: string;
  updatedAt: string;
}

export type SourceStatus = 'healthy' | 'degraded' | 'disconnected' | 'expiring_soon' | 'pending';

export type SourceCapability = 'Query' | 'Logs' | 'Lineage' | 'Metadata' | 'Write' | 'MCP';

export type SortField = 'name' | 'status' | 'layer' | 'lastTestedAt' | 'lastExtractedAt';
export type SortDir = 'asc' | 'desc';

export interface SourceFilters {
  search: string;
  layers: Set<PipelineLayer>;
  statuses: Set<SourceStatus>;
  extractionStatuses: Set<ExtractionStatus>;
  slaTiers: Set<SlaTier>;
  sort: { field: SortField; dir: SortDir };
}

export interface HealthSummary {
  total: number;
  healthy: number;
  degraded: number;
  disconnected: number;
  staleExtractions: number;
  nextExpiry: string | null;
  defaultWarehouse: string | null;
}

// Status priority for sorting (lower = more urgent)
export const STATUS_PRIORITY: Record<SourceStatus, number> = {
  disconnected: 0,
  expiring_soon: 1,
  degraded: 2,
  pending: 3,
  healthy: 4,
};

// Status display config
export const STATUS_CONFIG: Record<SourceStatus, { label: string; color: string; bg: string }> = {
  healthy: { label: 'Healthy', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  degraded: { label: 'Degraded', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  disconnected: { label: 'Disconnected', color: 'text-red-400', bg: 'bg-red-500/15' },
  expiring_soon: { label: 'Expiring Soon', color: 'text-yellow-400', bg: 'bg-yellow-500/15' },
  pending: { label: 'Pending', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

export function getDefaultFilters(): SourceFilters {
  return {
    search: '',
    layers: new Set(),
    statuses: new Set(),
    extractionStatuses: new Set(),
    slaTiers: new Set(),
    sort: { field: 'name', dir: 'asc' },
  };
}

// Compute extraction status from timestamps and contract expectations
export function deriveExtractionStatus(
  lastExtractedAt: string | null,
  expectedFreqMinutes: number | null,
  lastError: string | null
): ExtractionStatus {
  if (!lastExtractedAt) return 'never';
  if (lastError) return 'failed';
  if (expectedFreqMinutes) {
    const elapsed = (Date.now() - new Date(lastExtractedAt).getTime()) / (1000 * 60);
    if (elapsed > expectedFreqMinutes) return 'stale';
  }
  return 'ok';
}
