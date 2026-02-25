'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ArtifactType } from '@prisma/client';
import { ArtifactFilters, ArtifactList } from '@/components/artifacts';
import { toast } from 'sonner';

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
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedType, setSelectedType] = useState<ArtifactType | null>(null);
  const [showPinnedOnly, setShowPinnedOnly] = useState(false);

  const fetchArtifacts = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (selectedType) params.set('type', selectedType);
      if (showPinnedOnly) params.set('pinned', 'true');

      const response = await fetch(`/api/artifacts?${params.toString()}`);
      if (!response.ok) throw new Error('Failed to fetch artifacts');

      const data = await response.json();
      setArtifacts(data.artifacts);
    } catch (error) {
      console.error('Error fetching artifacts:', error);
      toast.error('Failed to load artifacts');
    } finally {
      setIsLoading(false);
    }
  }, [search, selectedType, showPinnedOnly]);

  useEffect(() => {
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

    setArtifacts((prev) => prev.filter((a) => a.id !== id));
  };

  const handleTogglePin = async (id: string, isPinned: boolean) => {
    const response = await fetch(`/api/artifacts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ isPinned }),
    });

    if (!response.ok) throw new Error('Failed to update artifact');

    setArtifacts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, isPinned } : a))
    );
  };

  const handleViewSource = (sessionId: string) => {
    router.push(`/dashboard/assistant?session=${sessionId}`);
  };

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
