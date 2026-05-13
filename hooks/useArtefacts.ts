'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ArtifactKind, ArtifactStatus } from '@prisma/client';
import type { ArtefactListResponse, ArtefactRow } from '@/types/artefact-row';

export type ArtefactSourceFilter = 'all' | 'agent' | 'user';

export interface UseArtefactsParams {
  search?: string;
  kinds?: ArtifactKind[];
  statuses?: ArtifactStatus[];
  source?: ArtefactSourceFilter;
  pinnedOnly?: boolean;
}

export interface UseArtefactsResult {
  artefacts: ArtefactRow[];
  total: number;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

function buildQuery(p: UseArtefactsParams): string {
  const q = new URLSearchParams();
  if (p.search) q.set('search', p.search);
  if (p.kinds && p.kinds.length) q.set('kind', p.kinds.join(','));
  if (p.statuses && p.statuses.length) q.set('status', p.statuses.join(','));
  if (p.source && p.source !== 'all') q.set('source', p.source);
  if (p.pinnedOnly) q.set('pinned', 'true');
  q.set('limit', '100');
  return q.toString();
}

export function useArtefacts(params: UseArtefactsParams): UseArtefactsResult {
  const [artefacts, setArtefacts] = useState<ArtefactRow[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const queryString = buildQuery(params);

  const fetchList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/artifacts?${queryString}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ArtefactListResponse = await res.json();
      setArtefacts(data.artifacts ?? []);
      setTotal(data.pagination?.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load artefacts');
    } finally {
      setIsLoading(false);
    }
  }, [queryString]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  return { artefacts, total, isLoading, error, refresh: fetchList };
}
