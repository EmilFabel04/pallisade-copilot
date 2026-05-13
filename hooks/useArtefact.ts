'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ArtefactRow } from '@/types/artefact-row';

export interface UseArtefactResult {
  artefact: ArtefactRow | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useArtefact(artifactId: string | null): UseArtefactResult {
  const [artefact, setArtefact] = useState<ArtefactRow | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOne = useCallback(async () => {
    if (!artifactId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/artifacts/${artifactId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setArtefact(data.artifact);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load artefact');
    } finally {
      setIsLoading(false);
    }
  }, [artifactId]);

  useEffect(() => {
    fetchOne();
  }, [fetchOne]);

  return { artefact, isLoading, error, refresh: fetchOne };
}
