'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ArtifactType } from '@prisma/client';
import { ArtifactFilters, ArtifactList } from '@/components/artifacts';
import { usePipeline } from '@/contexts/PipelineContext';
import { toast } from 'sonner';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { isFeatureEnabled } from '@/lib/feature-flags';

interface Artifact {
  id: string;
  title: string;
  content: string;
  type: ArtifactType;
  tags: string[];
  isPinned: boolean;
  createdAt: string;
  sourceSession?: {
    id: string;
    title: string;
  } | null;
}

export default function ArtifactsPage() {
  const router = useRouter();
  const { selectedPipelineId } = usePipeline();
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedType, setSelectedType] = useState<ArtifactType | null>(null);
  const [showPinnedOnly, setShowPinnedOnly] = useState(false);

  const fetchArtifacts = useCallback(async () => {
    if (!selectedPipelineId) {
      setArtifacts([]);
      setIsLoading(false);
      return;
    }
    try {
      const params = new URLSearchParams();
      params.set('stackId', selectedPipelineId);
      if (search) params.set('search', search);
      if (selectedType) params.set('type', selectedType);
      if (showPinnedOnly) params.set('pinned', 'true');

      const response = await cachedFetch(`/api/artifacts?${params.toString()}`);
      if (!response.ok) throw new Error('Failed to fetch artifacts');

      const data = await response.json();
      setArtifacts(data.artifacts);
    } catch (error) {
      console.error('Error fetching artifacts:', error);
      toast.error('Failed to load artifacts');
    } finally {
      setIsLoading(false);
    }
  }, [search, selectedType, showPinnedOnly, selectedPipelineId]);

  // Reset and re-fetch when pipeline changes
  useEffect(() => {
    setIsLoading(true);
    const debounceTimeout = setTimeout(() => {
      fetchArtifacts();
    }, 300);

    return () => clearTimeout(debounceTimeout);
  }, [fetchArtifacts]);

  const handleDelete = async (id: string) => {
    const response = await fetch(`/api/artifacts/${id}`, {
      method: 'DELETE',
    });

    if (!response.ok) throw new Error('Failed to delete artifact');

    invalidateCache('/api/artifacts');
    setArtifacts((prev) => prev.filter((a) => a.id !== id));
  };

  const handleTogglePin = async (id: string, isPinned: boolean) => {
    // Optimistic update — flip the UI immediately so the click feels instant.
    setArtifacts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, isPinned } : a))
    );

    try {
      const response = await fetch(`/api/artifacts/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isPinned }),
      });
      if (!response.ok) throw new Error('Failed to update artifact');
    } catch (err) {
      // Roll back on failure
      setArtifacts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, isPinned: !isPinned } : a))
      );
      throw err;
    }
  };

  const handleViewSource = (sessionId: string) => {
    router.push(`/dashboard/assistant?session=${sessionId}`);
  };

  if (isFeatureEnabled('ff_artefacts_v2')) {
    return (
      <div className="min-h-screen bg-[var(--surface-inset)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="mb-8">
            <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
            <p className="mt-1 text-[14px] text-[var(--muted)]">
              The new artefacts surface is being built. Check back soon.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--surface-inset)]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
          <p className="mt-1 text-[14px] text-[var(--muted)]">
            Saved responses from AI Chat - queries, fixes, insights, and more
          </p>
        </div>

        {/* Filters */}
        <div className="mb-6">
          <ArtifactFilters
            search={search}
            onSearchChange={setSearch}
            selectedType={selectedType}
            onTypeChange={setSelectedType}
            showPinnedOnly={showPinnedOnly}
            onPinnedChange={setShowPinnedOnly}
          />
        </div>

        {/* List */}
        <ArtifactList
          artifacts={artifacts}
          isLoading={isLoading}
          onDelete={handleDelete}
          onTogglePin={handleTogglePin}
          onViewSource={handleViewSource}
        />
      </div>
    </div>
  );
}
