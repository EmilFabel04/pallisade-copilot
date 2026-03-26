'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';
import type { ContractScope } from '@/lib/data-contracts/types';

export interface DataContractSummary {
  id: string;
  scope: ContractScope;
  scopeRef: string;
  ownerUser: string | null;
  ownerTeam: string | null;
  contactChannel: string | null;
  slaTier: string | null;
  expectedFreshnessMinutes: number | null;
  expectedExtractionFrequencyMinutes: number | null;
  isException: boolean;
  parentContractId: string | null;
  autoSynced: boolean;
  exceptions: Array<{ id: string; scopeRef: string }>;
  updatedAt: string;
}

const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_KEY_PREFIX = 'pallisade_data_contracts_';

interface CacheEntry {
  contracts: DataContractSummary[];
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

function saveCache(pipelineId: string, contracts: DataContractSummary[]): void {
  if (typeof window === 'undefined' || !pipelineId) return;
  try {
    localStorage.setItem(
      CACHE_KEY_PREFIX + pipelineId,
      JSON.stringify({ contracts, timestamp: Date.now() })
    );
  } catch {}
}

export function useDataContracts() {
  const { selectedPipelineId, loading: pipelineLoading } = usePipeline();
  const [contracts, setContracts] = useState<DataContractSummary[]>([]);
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
        setLoading(false);
        return;
      }
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}/data-contracts`);
      if (!res.ok) throw new Error('Failed to fetch data contracts');
      const data = await res.json();
      const fetched: DataContractSummary[] = data.contracts || [];
      setContracts(fetched);
      saveCache(selectedPipelineId, fetched);
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [selectedPipelineId]);

  useEffect(() => {
    if (pipelineLoading) return;
    if (lastPipelineIdRef.current === selectedPipelineId && contracts.length > 0) return;
    lastPipelineIdRef.current = selectedPipelineId || null;
    refresh();
  }, [selectedPipelineId, pipelineLoading, refresh]);

  return { contracts, loading: loading || pipelineLoading, error, refresh };
}
