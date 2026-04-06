'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';
import { PipelineLayer, getGraphDomain } from '@/components/pipeline/types';
import { getCapabilities } from './capabilities';
import {
  ControlPlaneSource,
  SourceStatus,
  ExtractionStatus,
  HealthSummary,
  SourceFilters,
  SourceSLAData,
  STATUS_PRIORITY,
  deriveExtractionStatus,
} from './types';

const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_KEY_PREFIX = 'pallisade_sources_cp_';

interface CacheEntry {
  sources: ControlPlaneSource[];
  timestamp: number;
}

function loadCache(pipelineId: string): CacheEntry | null {
  if (typeof window === 'undefined' || !pipelineId) return null;
  try {
    const raw = localStorage.getItem(CACHE_KEY_PREFIX + pipelineId);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() - entry.timestamp < CACHE_TTL_MS) return entry;
    localStorage.removeItem(CACHE_KEY_PREFIX + pipelineId);
    return null;
  } catch {
    return null;
  }
}

function saveCache(pipelineId: string, sources: ControlPlaneSource[]): void {
  if (typeof window === 'undefined' || !pipelineId) return;
  try {
    localStorage.setItem(
      CACHE_KEY_PREFIX + pipelineId,
      JSON.stringify({ sources, timestamp: Date.now() })
    );
  } catch {}
}

// Derive display status from raw integration data
function deriveStatus(
  rawStatus: string,
  healthScore: number | null,
  lastError: string | null,
  tokenExpiry: string | null,
  extractionStatus: ExtractionStatus
): SourceStatus {
  // Check token expiry first
  if (tokenExpiry) {
    const daysUntil = (new Date(tokenExpiry).getTime() - Date.now()) / (1000 * 60 * 60 * 24);
    if (daysUntil <= 0) return 'disconnected';
    if (daysUntil <= 7) return 'expiring_soon';
  }

  const upper = rawStatus?.toUpperCase() || '';
  if (['ERROR', 'FAILED'].includes(upper)) return 'disconnected';
  if (['PENDING', 'INACTIVE'].includes(upper)) return 'pending';

  // Stale extraction degrades a healthy source
  if (extractionStatus === 'stale' || extractionStatus === 'failed') {
    // Only degrade if otherwise healthy — don't override worse states
    if (healthScore === null || healthScore >= 80) return 'degraded';
  }

  if (healthScore !== null && healthScore !== undefined) {
    if (healthScore >= 80) return 'healthy';
    if (healthScore >= 40) return 'degraded';
    return 'disconnected';
  }

  // No health score — infer from status
  if (['CONNECTED', 'HEALTHY', 'ACTIVE'].includes(upper)) return 'healthy';
  if (upper === 'WARNING') return 'degraded';

  return 'pending';
}

// Build a scope summary string from config
function buildScopeSummary(toolType: string, config: Record<string, any> | null, connectionInfo: string | null): string {
  if (!config) return connectionInfo || '';
  const c = config;

  switch (toolType) {
    case 'bigquery':
      return [c.project_id || c.projectId, c.dataset || c.default_dataset || c.datasetId].filter(Boolean).join(' / ') || connectionInfo || '';
    case 'snowflake':
      return [c.account, c.database, c.schema || c.warehouse].filter(Boolean).join(' / ') || connectionInfo || '';
    case 'postgres':
    case 'redshift':
    case 'mysql':
    case 'sqlserver':
    case 'azure_sql':
    case 'azure_synapse':
      return [c.host, c.database || c.dbname].filter(Boolean).join(' / ') || connectionInfo || '';
    case 'databricks':
      return [c.host, c.catalog || c.schema].filter(Boolean).join(' / ') || connectionInfo || '';
    case 'dbt_cloud':
    case 'dbt_core':
      return [c.account_name || c.account_id, c.project_name || c.environment].filter(Boolean).join(' / ') || connectionInfo || '';
    case 'airflow':
      return c.host || c.base_url || connectionInfo || '';
    case 'fivetran':
    case 'airbyte':
    case 'stitch':
      return c.group_id || c.workspace_id || connectionInfo || '';
    case 'looker':
    case 'tableau':
    case 'powerbi':
    case 'metabase':
      return c.host || c.server || c.instance_url || connectionInfo || '';
    default:
      return connectionInfo || '';
  }
}

// Map a raw API layer string to PipelineLayer
function mapLayer(raw: string | undefined): PipelineLayer {
  if (!raw) return 'WAREHOUSE';
  const upper = raw.toUpperCase();
  const valid: PipelineLayer[] = ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'STORAGE', 'VERSION_CONTROL', 'ORCHESTRATION', 'INFRASTRUCTURE'];
  return valid.includes(upper as PipelineLayer) ? (upper as PipelineLayer) : 'WAREHOUSE';
}

// Normalize SLA data from API
function normalizeContract(raw: any): SourceSLAData | null {
  if (!raw) return null;
  return {
    slaTier: raw.slaTier || null,
    expectedFreshnessMinutes: raw.expectedFreshnessMinutes ?? null,
    expectedExtractionFrequencyMinutes: raw.expectedExtractionFrequencyMinutes ?? null,
    notes: raw.notes || null,
    inheritFromPipeline: raw.inheritFromPipeline ?? true,
    pipelineStackId: raw.pipelineStackId || null,
    overridesJson: raw.overridesJson || null,
  };
}

// Normalize raw API integration into ControlPlaneSource
function normalize(raw: any, allToolTypes: string[]): ControlPlaneSource {
  const toolType = (raw.toolType || raw.type || '').toLowerCase();
  const layer = mapLayer(raw.layer);
  const contract = normalizeContract(raw.sourceContract);
  const lastExtractedAt = raw.lastExtractedAt || null;
  const extractionStatus = deriveExtractionStatus(
    lastExtractedAt,
    contract?.expectedExtractionFrequencyMinutes ?? null,
    raw.lastError
  );

  return {
    id: raw.id,
    name: raw.name,
    toolType,
    integrationType: (raw.type || toolType).toUpperCase(),
    layer,
    origin: raw.source || 'legacy',
    status: deriveStatus(raw.status, raw.healthScore, raw.lastError, raw.tokenExpiry, extractionStatus),
    healthScore: raw.healthScore ?? null,
    lastTestedAt: raw.lastTestAt || raw.lastTestedAt || null,
    lastError: raw.lastError || null,
    lastScanAt: raw.lastScanAt || null,
    lastExtractedAt,
    lastLineageExtractedAt: raw.lastLineageExtractedAt || null,
    lastSchemaExtractedAt: raw.lastSchemaExtractedAt || null,
    lastLogsExtractedAt: raw.lastLogsExtractedAt || null,
    extractionStatus,
    connectionInfo: raw.connectionInfo || null,
    scopeSummary: buildScopeSummary(toolType, raw.config, raw.connectionInfo),
    capabilities: getCapabilities(toolType, allToolTypes),
    tokenExpiry: raw.tokenExpiry || null,
    findingsCount: raw.findingsCount || 0,
    criticalCount: raw.criticalCount || 0,
    highCount: raw.highCount || 0,
    contract,
    effectiveContract: raw.effectiveContract || null,
    inheritanceState: raw.inheritanceState || null,
    config: raw.config || null,
    stackId: raw.stackId || null,
    graphDomain: getGraphDomain(toolType),
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
  };
}

function computeSummary(sources: ControlPlaneSource[]): HealthSummary {
  let healthy = 0, degraded = 0, disconnected = 0, staleExtractions = 0;
  let nextExpiry: string | null = null;
  let defaultWarehouse: string | null = null;

  for (const s of sources) {
    if (s.status === 'healthy') healthy++;
    else if (s.status === 'degraded' || s.status === 'expiring_soon') degraded++;
    else if (s.status === 'disconnected') disconnected++;

    if (s.extractionStatus === 'stale' || s.extractionStatus === 'failed') staleExtractions++;

    if (s.tokenExpiry) {
      if (!nextExpiry || new Date(s.tokenExpiry) < new Date(nextExpiry)) {
        nextExpiry = s.tokenExpiry;
      }
    }

    if (!defaultWarehouse && s.layer === 'WAREHOUSE' && s.status === 'healthy') {
      defaultWarehouse = s.name;
    }
  }

  return { total: sources.length, healthy, degraded, disconnected, staleExtractions, nextExpiry, defaultWarehouse };
}

export function filterAndSort(sources: ControlPlaneSource[], filters: SourceFilters): ControlPlaneSource[] {
  let result = sources;

  // Search
  if (filters.search) {
    const q = filters.search.toLowerCase();
    result = result.filter(
      s =>
        s.name.toLowerCase().includes(q) ||
        s.toolType.includes(q) ||
        s.integrationType.toLowerCase().includes(q) ||
        s.scopeSummary.toLowerCase().includes(q)
    );
  }

  // Layer filter
  if (filters.layers.size > 0) {
    result = result.filter(s => filters.layers.has(s.layer));
  }

  // Status filter
  if (filters.statuses.size > 0) {
    result = result.filter(s => filters.statuses.has(s.status));
  }

  // Extraction status filter
  if (filters.extractionStatuses.size > 0) {
    result = result.filter(s => filters.extractionStatuses.has(s.extractionStatus));
  }

  // Graph domain filter (DATA_PLANE / CONTROL_PLANE / ALL)
  if (filters.graphDomain && filters.graphDomain !== 'ALL') {
    result = result.filter(s => s.graphDomain === filters.graphDomain);
  }

  // Sort
  const { field, dir } = filters.sort;
  const mult = dir === 'asc' ? 1 : -1;
  result = [...result].sort((a, b) => {
    switch (field) {
      case 'name':
        return mult * a.name.localeCompare(b.name);
      case 'status':
        return mult * (STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status]);
      case 'layer':
        return mult * a.layer.localeCompare(b.layer);
      case 'lastTestedAt': {
        const ta = a.lastTestedAt ? new Date(a.lastTestedAt).getTime() : 0;
        const tb = b.lastTestedAt ? new Date(b.lastTestedAt).getTime() : 0;
        return mult * (tb - ta);
      }
      case 'lastExtractedAt': {
        const ta = a.lastExtractedAt ? new Date(a.lastExtractedAt).getTime() : 0;
        const tb = b.lastExtractedAt ? new Date(b.lastExtractedAt).getTime() : 0;
        return mult * (tb - ta);
      }
      default:
        return 0;
    }
  });

  return result;
}

export function useSourcesData() {
  const { selectedPipelineId, loading: pipelineLoading } = usePipeline();
  const [sources, setSources] = useState<ControlPlaneSource[]>([]);
  const [pipelineSLA, setPipelineSLA] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastPipelineIdRef = useRef<string | null>(null);

  const refresh = useCallback(async (force = false) => {
    if (!selectedPipelineId) {
      setSources([]);
      setLoading(false);
      return;
    }

    if (!force) {
      const cached = loadCache(selectedPipelineId);
      if (cached) {
        setSources(cached.sources);
        setLoading(false);
        return;
      }
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/integrations?stackId=${selectedPipelineId}`);
      if (!res.ok) throw new Error('Failed to fetch integrations');
      const data = await res.json();

      const rawIntegrations: any[] = data.integrations || [];
      const allToolTypes = rawIntegrations.map((r: any) => (r.toolType || r.type || '').toLowerCase());
      const normalized = rawIntegrations.map((r: any) => normalize(r, allToolTypes));

      setSources(normalized);
      setPipelineSLA(data.pipelineContract || null);
      saveCache(selectedPipelineId, normalized);
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [selectedPipelineId]);

  useEffect(() => {
    if (pipelineLoading) return;
    if (lastPipelineIdRef.current === selectedPipelineId && sources.length > 0) return;
    lastPipelineIdRef.current = selectedPipelineId || null;
    refresh();
  }, [selectedPipelineId, pipelineLoading, refresh]);

  const summary = computeSummary(sources);

  return { sources, summary, pipelineSLA, loading: loading || pipelineLoading, error, refresh };
}
