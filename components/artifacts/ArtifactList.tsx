'use client';

import { ArtifactType } from '@prisma/client';
import { ArtifactCard } from './ArtifactCard';

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

interface ArtifactListProps {
  artifacts: Artifact[];
  isLoading?: boolean;
  onDelete: (id: string) => Promise<void>;
  onTogglePin: (id: string, isPinned: boolean) => Promise<void>;
  onViewSource: (sessionId: string) => void;
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      <div className="w-16 h-16 rounded-full bg-white/[0.03] flex items-center justify-center mb-4">
        <svg className="w-8 h-8 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
      </div>
      <h3 className="text-[15px] font-medium text-white mb-1">No artifacts yet</h3>
      <p className="text-[13px] text-white/40 text-center max-w-sm">
        Save valuable responses from AI Chat using the three-dot menu on any message.
        Queries, fixes, code snippets, and more can be saved here for quick access.
      </p>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div
          key={i}
          className="bg-[#0a0a0f] border border-white/[0.06] rounded-lg p-4 animate-pulse"
        >
          <div className="h-5 w-16 bg-white/[0.06] rounded mb-3" />
          <div className="h-5 w-3/4 bg-white/[0.06] rounded mb-2" />
          <div className="space-y-2">
            <div className="h-3 bg-white/[0.04] rounded" />
            <div className="h-3 bg-white/[0.04] rounded w-5/6" />
            <div className="h-3 bg-white/[0.04] rounded w-4/6" />
          </div>
          <div className="flex gap-1.5 mt-3">
            <div className="h-4 w-12 bg-white/[0.04] rounded" />
            <div className="h-4 w-16 bg-white/[0.04] rounded" />
          </div>
          <div className="mt-3 pt-3 border-t border-white/[0.04] flex justify-between">
            <div className="h-3 w-16 bg-white/[0.04] rounded" />
            <div className="h-3 w-24 bg-white/[0.04] rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ArtifactList({
  artifacts,
  isLoading,
  onDelete,
  onTogglePin,
  onViewSource,
}: ArtifactListProps) {
  if (isLoading) {
    return <LoadingSkeleton />;
  }

  if (artifacts.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
      {artifacts.map((artifact) => (
        <ArtifactCard
          key={artifact.id}
          artifact={artifact}
          onDelete={onDelete}
          onTogglePin={onTogglePin}
          onViewSource={onViewSource}
        />
      ))}
    </div>
  );
}
