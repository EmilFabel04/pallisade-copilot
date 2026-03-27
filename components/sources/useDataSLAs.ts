'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';
import type { DataSLAScope } from '@/lib/data-contracts/types';

export interface DataSLASummary {
  id: string;
  scope: DataSLAScope;
  scopeRef: string;
  name: string | null;
  nodeFqns: string[] | null;
  slaTier: string | null;
  notes: string | null;
  // Domain-specific SLA config sections
  freshnessConfig: Record<string, unknown> | null;
  schemaConfig: Record<string, unknown> | null;
  volumeConfig: Record<string, unknown> | null;
  anomalyConfig: Record<string, unknown> | null;
  qualityConfig: Record<string, unknown> | null;
  ingestionConfig: Record<string, unknown> | null;
  biConfig: Record<string, unknown> | null;
  orchestrationConfig: Record<string, unknown> | null;
  transformConfig: Record<string, unknown> | null;
  // Legacy
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  isException: boolean;
  parentContractId: string | null;
  autoSynced: boolean;
  status: string; // 'active' | 'inactive' | 'archived'
  archivedAt: string | null;
  exceptions: Array<{ id: string; scopeRef: string }>;
  updatedAt: string;
}

const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_KEY_PREFIX = 'pallisade_data_slas_';

interface CacheEntry {
  contracts: DataSLASummary[];
  dataSLAsEnabled: boolean;
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

function saveCache(pipelineId: string, contracts: DataSLASummary[], dataSLAsEnabled: boolean): void {
  if (typeof window === 'undefined' || !pipelineId) return;
  try {
    localStorage.setItem(
      CACHE_KEY_PREFIX + pipelineId,
      JSON.stringify({ contracts, dataSLAsEnabled, timestamp: Date.now() })
    );
  } catch {}
}

export function useDataSLAs() {
  const { selectedPipelineId, loading: pipelineLoading } = usePipeline();
  const [contracts, setContracts] = useState<DataSLASummary[]>([]);
  const [dataSLAsEnabled, setDataSLAsEnabled] = useState(false);
  const [contractAllowOverrides, setContractAllowOverrides] = useState(false);
  const [contractViolationAlerting, setContractViolationAlerting] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastPipelineIdRef = useRef<string | null>(null);

  const refresh = useCallback(async (force = false) => {
    if (!selectedPipelineId) {
      setContracts([]);
      setLoading(false);
      return;
    }

    if (!force) {
      const cached = loadCache(selectedPipelineId);
      if (cached) {
        setContracts(cached.contracts);
        setDataSLAsEnabled(cached.dataSLAsEnabled);
        setLoading(false);
        return;
      }
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}/data-slas`);
      if (!res.ok) throw new Error('Failed to fetch data SLAs');
      const data = await res.json();
      const fetched: DataSLASummary[] = data.dataSLAs || data.contracts || [];
      const enabled: boolean = data.dataSLAsEnabled ?? false;
      setContracts(fetched);
      setDataSLAsEnabled(enabled);
      setContractAllowOverrides(data.contractAllowOverrides ?? false);
      setContractViolationAlerting(data.contractViolationAlerting ?? true);
      // Only cache non-empty results — empty results should re-fetch next time
      if (fetched.length > 0) {
        saveCache(selectedPipelineId, fetched, enabled);
      }
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [selectedPipelineId]);

  useEffect(() => {
    if (pipelineLoading) return;
    lastPipelineIdRef.current = selectedPipelineId || null;
    // Always fetch fresh — SLA data changes frequently via mutations
    refresh(true);
  }, [selectedPipelineId, pipelineLoading, refresh]);

  return { contracts, dataSLAsEnabled, contractAllowOverrides, contractViolationAlerting, loading: loading || pipelineLoading, error, refresh };
}
