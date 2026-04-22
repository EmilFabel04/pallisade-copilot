'use client';

import React, { useState } from 'react';
import { ArtifactType } from '@prisma/client';
import { toast } from 'sonner';
import { Pin, PinOff } from 'lucide-react';

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

interface ArtifactCardProps {
  artifact: Artifact;
  onDelete?: (id: string) => void;
  onTogglePin?: (id: string, isPinned: boolean) => void;
  onViewSource?: (sessionId: string) => void;
}

const typeConfig: Record<ArtifactType, { label: string; className: string; icon: React.ReactNode }> = {
  QUERY: {
    label: 'Query',
    className: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
      </svg>
    ),
  },
  FIX: {
    label: 'Fix',
    className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  INSIGHT: {
    label: 'Insight',
    className: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  CODE: {
    label: 'Code',
    className: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
      </svg>
    ),
  },
  PLAN: {
    label: 'Plan',
    className: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
      </svg>
    ),
  },
};

export function ArtifactCard({ artifact, onDelete, onTogglePin, onViewSource }: ArtifactCardProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const config = typeConfig[artifact.type];

  const handleCopy = async () => {
    await navigator.clipboard.writeText(artifact.content);
    toast.success('Copied to clipboard');
    setIsMenuOpen(false);
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    setIsDeleting(true);
    try {
      await onDelete(artifact.id);
      toast.success('Artifact deleted');
    } catch (error) {
      toast.error('Failed to delete artifact');
    } finally {
      setIsDeleting(false);
      setIsMenuOpen(false);
    }
  };

  const handleTogglePin = async () => {
    if (!onTogglePin) return;
    try {
      await onTogglePin(artifact.id, !artifact.isPinned);
      toast.success(artifact.isPinned ? 'Unpinned' : 'Pinned');
    } catch (error) {
      toast.error('Failed to update pin status');
    }
    setIsMenuOpen(false);
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined,
    });
  };

  const getPreview = (content: string, maxLength = 150) => {
    if (content.length <= maxLength) return content;
    return content.substring(0, maxLength).trim() + '...';
  };

  return (
    <div className="group relative bg-[var(--surface-inset)] border border-[var(--subtle-border)] rounded-lg p-4 hover:border-[var(--overlay-strong)] transition-all">
      {/* Top-right controls: pin indicator + three-dot menu */}
      <div className="absolute top-2 right-2 flex items-center gap-1">
        {artifact.isPinned && (
          <div className="p-1.5" title="Pinned">
            <Pin className="w-3.5 h-3.5 text-amber-400 fill-amber-400/80 rotate-45" strokeWidth={1.75} />
          </div>
        )}
        <button
          onClick={() => setIsMenuOpen(!isMenuOpen)}
          className="p-1.5 rounded-md opacity-0 group-hover:opacity-100 hover:bg-[var(--hover-bg)] transition-opacity"
        >
          <svg className="w-4 h-4 text-[var(--muted)]" fill="currentColor" viewBox="0 0 20 20">
            <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
          </svg>
        </button>

        {isMenuOpen && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={() => setIsMenuOpen(false)}
            />
            <div className="absolute right-0 top-8 z-20 w-40 bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg shadow-xl overflow-hidden">
              <button
                onClick={handleCopy}
                className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Copy
              </button>
              <button
                onClick={handleTogglePin}
                className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)] transition-colors"
              >
                {artifact.isPinned ? (
                  <PinOff className="w-4 h-4" strokeWidth={1.75} />
                ) : (
                  <Pin className="w-4 h-4" strokeWidth={1.75} />
                )}
                {artifact.isPinned ? 'Unpin' : 'Pin'}
              </button>
              {artifact.sourceSession && (
                <button
                  onClick={() => {
                    onViewSource?.(artifact.sourceSession!.id);
                    setIsMenuOpen(false);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)] transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                  View source
                </button>
              )}
              <div className="h-px bg-[var(--hover-bg)]" />
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                {isDeleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </>
        )}
      </div>

      {/* Type badge */}
      <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-xs font-medium ${config.className}`}>
        {config.icon}
        {config.label}
      </div>

      {/* Title */}
      <h3 className="mt-3 text-[15px] font-medium text-[var(--text)] line-clamp-1">
        {artifact.title}
      </h3>

      {/* Preview */}
      <p className="mt-2 text-[13px] text-[var(--muted)] line-clamp-3 font-mono">
        {getPreview(artifact.content)}
      </p>

      {/* Tags */}
      {artifact.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {artifact.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 bg-[var(--overlay-bg)] text-[var(--muted)] text-[11px] rounded-md"
            >
              {tag}
            </span>
          ))}
          {artifact.tags.length > 3 && (
            <span className="px-2 py-0.5 text-[var(--text-faint)] text-[11px]">
              +{artifact.tags.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-[var(--border-faint)] flex items-center justify-between text-[11px] text-[var(--text-faint)]">
        <span>{formatDate(artifact.createdAt)}</span>
        {artifact.sourceSession && (
          <span className="truncate max-w-[150px]">
            from {artifact.sourceSession.title}
          </span>
        )}
      </div>
    </div>
  );
}
